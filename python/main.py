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
import warnings
from difflib import SequenceMatcher
from datetime import datetime

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Config
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "d81b9041a5088eefc54fe9d951e8f40b"
ACR_ACCESS_SECRET = "T7a8zHSW56NFCBJge5pNYTfZpB0vNlMxwujnyFYn"
DISCOGS_USERNAME = "tomkatsman"
DISCOGS_TOKEN = "SxMnoBAJYKjqsqIZPlQuMitpZDRFEbvYVHkhXmxG"
ICECAST_URL = "http://localhost:8000/vinyl.mp3"
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

silence_threshold = 100
silence_required_for_reset = 30
current_album = None
current_track_index = 0
current_track_duration = 0
force_initial_recognition = True
silence_duration = 0

def log(level, message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{level}] {timestamp} {message}")

def clean_title(title):
    return re.sub(r"(\[.*?\]|\(.*?\)|Remaster|Deluxe|\bLive\b|Edition|Official Video|\d{4})", "", title).strip()

def capture_stream(duration=10):
    response = requests.get(ICECAST_URL, stream=True)
    buffer = bytearray()
    for chunk in response.iter_content(1024):
        buffer.extend(chunk)
        if len(buffer) >= 44100 * 2 * duration:
            break
    rms = audioop.rms(buffer, 2)
    log("DEBUG", f"Captured {len(buffer)} bytes, RMS volume: {rms}")
    return buffer, rms

def recognize_audio(audio_bytes):
    timestamp = int(time.time())
    signature_string = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{timestamp}"
    signature = base64.b64encode(hmac.new(ACR_ACCESS_SECRET.encode(), signature_string.encode(), hashlib.sha1).digest()).decode()

    response = requests.post(f"https://{ACR_HOST}/v1/identify", files={'sample': ('vinyl.mp3', audio_bytes)}, data={
        'access_key': ACR_ACCESS_KEY,
        'sample_bytes': len(audio_bytes),
        'timestamp': timestamp,
        'signature': signature,
        'data_type': 'audio',
        'signature_version': '1'
    })
    result = response.json()
    log("DEBUG", json.dumps(result, indent=4))
    return result

def extract_metadata(result):
    metadata = result.get('metadata', {})
    music_list = metadata.get('music', [])
    source = "music"

    if not music_list:
        music_list = metadata.get('humming', [])
        if music_list:
            source = "humming"
            log("WARNING", "Geen reguliere match gevonden, fallback naar humming.")

    if not music_list:
        log("WARNING", "Geen herkenbare muziek gevonden.")
        return "Unknown", "Unknown", "Unknown", 0, 0, "none"

    music = music_list[0]

    play_offset_ms = music.get('play_offset_ms', 0)
    
    # Verschuif alles één minuut naar voren om vertraging te compenseren.
    play_offset_ms = max(play_offset_ms - 60000, 0)

    return (
        clean_title(music.get('title', 'Unknown')),
        music['artists'][0]['name'] if music.get('artists') else "Unknown Artist",
        clean_title(music['album'].get('name', 'Unknown Album') if music.get('album') else "Unknown Album"),
        play_offset_ms,
        music.get('duration_ms', 0),
        source
    )

def fetch_discogs_collection():
    releases, page = [], 1
    while True:
        response = requests.get(f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases", headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}, params={"page": page, "per_page": 100})
        if response.status_code != 200: break
        page_data = response.json().get("releases", [])
        releases.extend(page_data)
        if len(page_data) < 100: break
        page += 1
    log("INFO", f"Fetched {len(releases)} releases from Discogs.")
    return releases

def find_album_and_tracklist(artist, album, collection, track_title):
    matched_releases = [release for release in collection if artist.lower() in release['basic_information']['artists'][0]['name'].lower()]
    for release in matched_releases:
        release_id = release['id']
        details = requests.get(f"https://api.discogs.com/releases/{release_id}", headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}).json()
        for track in details.get('tracklist', []):
            if SequenceMatcher(None, clean_title(track['title']).lower(), clean_title(track_title).lower()).ratio() > 0.7:
                return details
    return None

def find_track_index(title, tracklist):
    for index, track in enumerate(tracklist):
        if SequenceMatcher(None, clean_title(track['title']).lower(), clean_title(title).lower()).ratio() > 0.7:
            return index
    return 0

def update_now_playing(title, artist, cover, play_offset_ms, duration_ms, source):
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump({"title": title, "artist": artist, "cover": cover, "play_offset_ms": play_offset_ms, "duration_ms": duration_ms, "source": source}, f)
    log("INFO", f"Now playing: {artist} - {title} (Source: {source})")

def show_current_track(play_offset_ms=0, duration_ms=0):
    global current_track_duration
    track = current_album['tracklist'][current_track_index]
    title = clean_title(track['title'])
    cover = current_album.get('images', [{}])[0].get('uri', '')
    log("INFO", f"Now playing: {current_album['artists'][0]['name']} - {title} (Track {current_track_index+1}/{len(current_album['tracklist'])}, {play_offset_ms//60000:02}:{(play_offset_ms//1000)%60:02})")
    current_track_duration = (duration_ms - play_offset_ms) // 1000
    log("INFO", f"Time until next track: {current_track_duration//60:02}:{current_track_duration%60:02}")
    update_now_playing(title, current_album['artists'][0]['name'], cover, play_offset_ms, duration_ms, "music")

collection = fetch_discogs_collection()

while True:
    audio, rms = capture_stream(10)

    if rms < silence_threshold:
        silence_duration += 10
        if silence_duration >= silence_required_for_reset:
            log("INFO", "Resetting to listening mode after silence.")
            current_album = None
            current_track_index = 0
            force_initial_recognition = True
        continue
    else:
        silence_duration = 0

    result = recognize_audio(audio)
    title, artist, album, offset, duration, source = extract_metadata(result)

    if title == "Unknown":
        continue

    album_data = find_album_and_tracklist(artist, album, collection, title)

    if album_data:
        current_album = album_data
        current_track_index = find_track_index(title, current_album['tracklist'])
        show_current_track(offset, duration)

        while current_track_duration > 0:
            if current_track_duration > 10:
                time.sleep(current_track_duration - 10)
                log("INFO", "10 seconds until next track...")
                time.sleep(10)
            else:
                time.sleep(current_track_duration)
            current_track_index += 1
            if current_track_index >= len(current_album['tracklist']):
                log("INFO", "End of album reached, resetting to listening mode.")
                current_album = None
                break
            else:
                next_track = current_album['tracklist'][current_track_index]
                duration_parts = next_track['duration'].split(":")
                duration_ms = (int(duration_parts[0]) * 60 + int(duration_parts[1])) * 1000
                show_current_track(0, duration_ms)
    else:
        log("WARNING", f"Track '{title}' by '{artist}' not found in collection, displaying without album.")
        update_now_playing(title, artist, None, offset, duration, source)

    time.sleep(1)