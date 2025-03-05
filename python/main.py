import requests
import time
import json
import os
import base64
import hashlib
import hmac
import re
import wave
import audioop
from difflib import SequenceMatcher
from datetime import datetime

# ACRCloud credentials
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "d81b9041a5088eefc54fe9d951e8f40b"
ACR_ACCESS_SECRET = "T7a8zHSW56NFCBJge5pNYTfZpB0vNlMxwujnyFYn"

# Discogs credentials
DISCOGS_USERNAME = "tomkatsman"
DISCOGS_TOKEN = "SxMnoBAJYKjqsqIZPlQuMitpZDRFEbvYVHkhXmxG"

ICECAST_URL = "http://localhost:8000/vinyl.mp3"
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

poll_interval = 15
silence_threshold = 100
silence_duration = 0
silence_required_for_reset = 30

current_album = None
current_track_index = 0
current_track_duration = 0
last_detected_track = None

def log(level, message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{level}] {timestamp} {message}")

def clean_title(title):
    cleaned = re.sub(r"\(.*?\)", "", title)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    to_remove = ["Remaster", "Deluxe", "Live", "Edition", "Official Video", "2021", "2005"]
    for word in to_remove:
        cleaned = cleaned.replace(word, "")
    return cleaned.strip()

def capture_stream(duration=10):
    response = requests.get(ICECAST_URL, stream=True)
    buffer = bytearray()
    for chunk in response.iter_content(chunk_size=1024):
        buffer.extend(chunk)
        if len(buffer) >= 44100 * 2 * duration:
            break

    with wave.open("captured_audio.wav", "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(buffer)

    rms = audioop.rms(buffer, 2)
    log("DEBUG", f"Captured {len(buffer)} bytes, RMS volume: {rms}")

    return buffer, rms

def recognize_audio(audio_bytes):
    timestamp = int(time.time())
    string_to_sign = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{timestamp}"
    signature = base64.b64encode(hmac.new(
        ACR_ACCESS_SECRET.encode(),
        string_to_sign.encode(),
        hashlib.sha1
    ).digest()).decode()

    files = {'sample': ('vinyl.mp3', audio_bytes)}
    data = {
        'access_key': ACR_ACCESS_KEY,
        'sample_bytes': len(audio_bytes),
        'timestamp': timestamp,
        'signature': signature,
        'data_type': 'audio',
        'signature_version': '1'
    }

    response = requests.post(f"https://{ACR_HOST}/v1/identify", files=files, data=data)
    result = response.json()
    log("DEBUG", json.dumps(result, indent=4))
    return result

def extract_metadata(result):
    music_list = result.get('metadata', {}).get('music', [])
    if not music_list:
        log("WARN", "Geen muziekdata gevonden in resultaat, waarschijnlijk 'No result' van ACRCloud.")
        return "Unknown", "Unknown", "Unknown", 0

    best_match = max(music_list, key=lambda m: m.get('score', 0))
    title = best_match.get('title', 'Unknown')
    artist = ", ".join([a['name'] for a in best_match.get('artists', [])])
    album = best_match.get('album', {}).get('name', 'Unknown')
    play_offset_ms = best_match.get('play_offset_ms', 0)

    return clean_title(title), artist, clean_title(album), play_offset_ms

def fetch_all_discogs_releases():
    all_releases = []
    page = 1
    per_page = 100

    while True:
        response = requests.get(
            f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases",
            headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"},
            params={"page": page, "per_page": per_page}
        )

        if response.status_code != 200:
            log("WARN", f"Failed to fetch collection page {page}. Status: {response.status_code}")
            break

        data = response.json()
        all_releases.extend(data.get("releases", []))

        if len(data.get("releases", [])) < per_page:
            break

        page += 1

    log("INFO", f"Fetched {len(all_releases)} releases from Discogs.")
    return all_releases

def find_album_and_tracklist(artist, album, all_releases):
    for release in all_releases:
        basic_info = release.get("basic_information", {})
        release_artist = basic_info.get("artists", [{}])[0].get("name", "").lower()

        if artist.lower() not in release_artist:
            continue

        release_id = release.get("id")
        response = requests.get(f"https://api.discogs.com/releases/{release_id}", headers={
            "Authorization": f"Discogs token={DISCOGS_TOKEN}"
        })

        if response.status_code != 200:
            continue

        release_data = response.json()
        discogs_album = clean_title(release_data.get("title", ""))

        if SequenceMatcher(None, album.lower(), discogs_album.lower()).ratio() > 0.7:
            return release_data

    return None

def find_track_index_in_album(target_title, tracklist):
    target_title = clean_title(target_title).lower()

    for index, track in enumerate(tracklist):
        discogs_title = clean_title(track.get("title", "")).lower()
        if SequenceMatcher(None, target_title, discogs_title).ratio() > 0.7:
            return index

    return 0

def update_now_playing(title, artist, cover, track_index=None, total_tracks=None, offset=None, duration=None):
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump({"title": title, "artist": artist, "cover": cover}, f)

    track_info = ""
    if track_index is not None and total_tracks is not None:
        offset_str = f"{offset // 60000}:{offset // 1000 % 60:02}" if offset else "00:00"
        track_info = f" (Track {track_index+1}/{total_tracks}, {offset_str})"

    log("INFO", f"Now playing: {artist} - {title}{track_info}")

    if duration:
        minutes, seconds = divmod(duration, 60)
        log("INFO", f"Time until next track: {minutes:02}:{seconds:02}")

def reset_to_listening_mode():
    global current_album, current_track_index, current_track_duration
    current_album = None
    current_track_index = 0
    current_track_duration = 0

force_initial_recognition = True
discogs_collection = fetch_all_discogs_releases()

while True:
    if current_album:
        time.sleep(max(0, current_track_duration - 10))
        log("INFO", "10 seconden tot volgende track...")
        time.sleep(10)
        current_track_index += 1
        if current_track_index >= len(current_album["tracklist"]):
            log("INFO", "Albumkant is afgelopen, terug naar luistermodus.")
            reset_to_listening_mode()
        else:
            next_track = current_album["tracklist"][current_track_index]
            minutes, seconds = map(int, next_track["duration"].split(":"))
            update_now_playing(next_track["title"], current_album["artists"][0]["name"],
                               current_album.get("images", [{}])[0].get("uri", ""),
                               current_track_index, len(current_album["tracklist"]), 0, minutes*60+seconds)
            current_track_duration = minutes * 60 + seconds
    else:
        audio, rms = capture_stream(10)
        result = recognize_audio(audio)
        if result["status"]["code"] == 0:
            title, artist, album, offset = extract_metadata(result)
            log("INFO", f"New track detected: {artist} - {title}")
        time.sleep(1)
