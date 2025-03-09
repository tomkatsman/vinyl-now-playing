import requests
import time
import json
import os
import base64
import hashlib
import hmac
import re
import warnings
import numpy as np
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

# Helper functies
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
    return buffer

def detect_audio_presence(audio_bytes, threshold=5000):
    """
    Analyseert de frequentie-inhoud van een audiostream om te bepalen of er echt geluid is.
    threshold: minimale frequentie-energie om te bepalen of er muziek speelt.
    """
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
    if len(audio_np) == 0:
        log("WARNING", "Gelezen audiobuffer is leeg!")
        return False
    energy = np.sum(np.abs(audio_np))
    log("DEBUG", f"Audio-energie: {energy}, drempel: {threshold}")
    return energy > threshold

def wait_for_audio_trigger(check_interval=1):
    log("INFO", "Wachten op hoorbaar geluid in de stream...")
    silent_count = 0
    required_changes = 3

    while True:
        audio = capture_stream(check_interval)
        if detect_audio_presence(audio):
            silent_count += 1
            log("DEBUG", f"Muziek gedetecteerd ({silent_count}/{required_changes})...")
            if silent_count >= required_changes:
                log("INFO", "Muziek bevestigd! Trigger geactiveerd.")
                return
        else:
            silent_count = 0
        time.sleep(check_interval)

def fetch_discogs_collection():
    releases, page = [], 1
    while True:
        response = requests.get(f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases", 
                                headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}, 
                                params={"page": page, "per_page": 100})
        if response.status_code != 200: 
            break
        page_data = response.json().get("releases", [])
        releases.extend(page_data)
        if len(page_data) < 100: 
            break
        page += 1
    log("INFO", f"Fetched {len(releases)} releases from Discogs.")
    return releases

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

    if not music_list:
        log("WARNING", "Geen herkenbare muziek gevonden.")
        return "Unknown", "Unknown", "Unknown", 0, 0, "none"

    music = music_list[0]
    return (
        clean_title(music.get('title', 'Unknown')),
        music['artists'][0]['name'] if music.get('artists') else "Unknown Artist",
        clean_title(music['album'].get('name', 'Unknown Album') if music.get('album') else "Unknown Album"),
        max(music.get('play_offset_ms', 0) + 30000, 0),
        music.get('duration_ms', 0),
        "music"
    )

def find_track_index(title, tracklist):
    for index, track in enumerate(tracklist):
        if SequenceMatcher(None, clean_title(track['title']).lower(), clean_title(title).lower()).ratio() > 0.7:
            return index
    return 0

def update_now_playing(title, artist, cover, play_offset_ms, duration_ms, source):
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump({"title": title, "artist": artist, "cover": cover, "play_offset_ms": play_offset_ms, "duration_ms": duration_ms, "source": source}, f)
    log("INFO", f"Now playing: {artist} - {title} (Source: {source})")

collection = fetch_discogs_collection()

while True:
    wait_for_audio_trigger()
    time.sleep(2)

    audio = capture_stream(10)
    result = recognize_audio(audio)
    title, artist, album, offset, duration, source = extract_metadata(result)

    if title == "Unknown":
        log("WARNING", "Geen herkenbare muziek gevonden, terug naar wachten op trigger.")
        continue

    album_data = next((r for r in collection if album.lower() in r['basic_information']['title'].lower()), None)

    if album_data:
        track_index = find_track_index(title, album_data['tracklist'])
        update_now_playing(title, artist, album_data['images'][0]['uri'], offset, duration, source)
        for current_track_index in range(track_index, len(album_data['tracklist'])):
            track = album_data['tracklist'][current_track_index]
            title = clean_title(track['title'])
            duration_parts = track['duration'].split(":")
            duration_ms = (int(duration_parts[0]) * 60 + int(duration_parts[1])) * 1000
            log("INFO", f"Speelt nu: {title} ({current_track_index+1}/{len(album_data['tracklist'])})")
            update_now_playing(title, artist, album_data['images'][0]['uri'], 0, duration_ms, source)
            time.sleep((duration_ms / 1000) - 5)
            log("INFO", "5 seconden tot volgende track...")
            time.sleep(5)
        log("INFO", "Einde van album bereikt, terug naar luistermodus.")
    else:
        log("WARNING", f"'{title}' niet in collectie gevonden, toont zonder album.")
        update_now_playing(title, artist, None, offset, duration, source)

    log("INFO", "Terug naar wachten op volume-toename (trigger)...")