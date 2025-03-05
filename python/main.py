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
last_track = None

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
    print(f"[DEBUG] Captured {len(buffer)} bytes, RMS volume: {rms}")

    if rms < 100:
        print("[WARN] Audio volume lijkt erg laag, mogelijk probleem met input.")

    return buffer

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
    print(f"[DEBUG] ACRCloud Response: {json.dumps(result, indent=4)}")
    return result

def extract_metadata(result):
    music_list = result.get('metadata', {}).get('music', [])

    if not music_list:
        return "Unknown", "Unknown", "Unknown"

    best_match = max(music_list, key=lambda m: m.get('score', 0))

    if best_match.get('score', 0) < 0.3:
        print("[WARN] Match gevonden maar score is erg laag, mogelijk ruis.")
        return "Unknown", "Unknown", "Unknown"

    title = best_match.get('title', 'Unknown')
    artist = ", ".join([a['name'] for a in best_match.get('artists', [])])
    album = best_match.get('album', {}).get('name', 'Unknown')

    return clean_title(title), artist, album


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
            print(f"[WARN] Failed to fetch collection page {page}. Status: {response.status_code}")
            break

        data = response.json()
        releases = data.get("releases", [])
        all_releases.extend(releases)

        if len(releases) < per_page:
            break

        page += 1

    print(f"[INFO] Fetched {len(all_releases)} releases from Discogs.")
    return all_releases

def find_album_cover_on_discogs(artist, track_title, all_releases):
    print(f"[INFO] Searching Discogs collection for artist '{artist}' and track '{track_title}'...")

    for release in all_releases:
        basic_info = release.get("basic_information", {})
        release_artist = basic_info.get("artists", [{}])[0].get("name", "").lower()

        if artist.lower() not in release_artist:
            continue

        release_id = release.get("id")
        release_response = requests.get(
            f"https://api.discogs.com/releases/{release_id}",
            headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}
        )

        if release_response.status_code != 200:
            continue

        release_data = release_response.json()
        tracklist = release_data.get("tracklist", [])

        for track in tracklist:
            clean_track_name = clean_title(track.get("title", ""))
            if track_title.lower() == clean_track_name.lower():
                cover_image = basic_info.get("cover_image", "")
                print(f"[INFO] Found matching album cover: {cover_image}")
                return cover_image

    print("[INFO] No matching album found for this track in your collection.")
    return ""

# Fetch volledige collectie bij opstarten, hergebruik daarna voor performance
discogs_collection = fetch_all_discogs_releases()

while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)

    if result.get('status', {}).get('code') == 0:
        title, artist, album = extract_metadata(result)

        current_track = f"{artist} - {title}"
        if current_track == last_track:
            poll_interval = 60
        else:
            poll_interval = 15
            last_track = current_track

        cover = find_album_cover_on_discogs(artist, title, discogs_collection)

        now_playing_data = {
            "title": title,
            "artist": artist,
            "cover": cover
        }

        with open(NOW_PLAYING_PATH, "w") as f:
            json.dump(now_playing_data, f)

        print(f"[INFO] Now playing: {artist} - {title}")
    else:
        print(f"[WARN] Geen track herkend. ACRCloud status: {result.get('status')}. Poll interval blijft 15 seconden.")
        poll_interval = 15

    time.sleep(poll_interval)
