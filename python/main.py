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
    to_remove = ["Remaster", "Deluxe", "Live", "Edition", "Official Video", "2011", "2021", "2022", "Remixed"]
    for word in to_remove:
        cleaned = cleaned.replace(word, "")
    return cleaned.strip().lower()

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
    print(f"[DEBUG] ACRCloud Response: {response.json()}")
    return response.json()

def extract_metadata(result):
    metadata = result.get('metadata', {})
    
    # Prioriteit geven aan 'music', anders fallback naar 'humming'
    track_data = metadata.get('music', metadata.get('humming', [{}]))

    if not track_data or not isinstance(track_data, list):
        return "Unknown", "Unknown", "Unknown"

    # Neem de track met de hoogste score
    best_match = sorted(track_data, key=lambda x: x.get('score', 0), reverse=True)[0]

    title = best_match.get('title', 'Unknown')
    artist = ", ".join([a['name'] for a in best_match.get('artists', [])])
    album = best_match.get('album', {}).get('name', 'Unknown')

    return title, artist, album

def fetch_discogs_collection():
    url = f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases"
    releases = []
    page = 1

    while True:
        response = requests.get(url, headers={
            "Authorization": f"Discogs token={DISCOGS_TOKEN}"
        }, params={"page": page, "per_page": 100})

        if response.status_code != 200:
            print(f"[WARN] Failed to fetch collection page {page} from Discogs (status {response.status_code})")
            break

        page_data = response.json()
        releases.extend(page_data.get("releases", []))

        if page >= page_data.get("pagination", {}).get("pages", 1):
            break

        page += 1

    return releases

def find_cover(artist, album, track):
    cleaned_track = clean_title(track)
    collection = fetch_discogs_collection()

    # 1. Directe match op album
    for release in collection:
        basic = release.get("basic_information", {})
        if artist.lower() in basic.get("artists", [{}])[0].get("name", "").lower() and album.lower() in basic.get("title", "").lower():
            print(f"[INFO] Direct album match gevonden: {basic.get('title')}")
            return basic.get("cover_image", "")

    # 2. Geen album match -> door alle releases zoeken op track (slow path)
    print("[INFO] Geen direct album match. Nu zoeken op track in alle releases van de artiest.")
    for release in collection:
        basic = release.get("basic_information", {})
        if artist.lower() not in basic.get("artists", [{}])[0].get("name", "").lower():
            continue

        release_id = release.get("id")
        release_response = requests.get(f"https://api.discogs.com/releases/{release_id}", headers={
            "Authorization": f"Discogs token={DISCOGS_TOKEN}"
        })

        if release_response.status_code != 200:
            continue

        tracks = release_response.json().get("tracklist", [])
        for track_info in tracks:
            cleaned_discogs_track = clean_title(track_info.get("title", ""))
            if cleaned_track == cleaned_discogs_track:
                print(f"[INFO] Track match gevonden op release: {basic.get('title')}")
                return basic.get("cover_image", "")

    print("[WARN] Geen match gevonden in jouw collectie.")
    return ""

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

        cover = find_cover(artist, album, title)

        with open(NOW_PLAYING_PATH, "w") as f:
            json.dump({"title": title, "artist": artist, "cover": cover}, f)

        print(f"[INFO] Now playing: {artist} - {title} (Cover source: {'Discogs' if cover else 'None'})")
    else:
        print(f"[WARN] Geen track herkend. Status: {result.get('status')}. Poll interval blijft 15 seconden.")
        poll_interval = 15

    time.sleep(poll_interval)
