import requests
import time
import json
import os
import base64
import hashlib
import hmac

# Vul je ACRCloud gegevens hier in!
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "3fea776a493631a8e880d625080aa344"
ACR_ACCESS_SECRET = "7UklrI2av7z29joyPhOVJj0cT3RN7KmKAnx3vcdG"

# Vul je Discogs gegevens hier in!
DISCOGS_KEY = "wQvXfQjNsyxrHlmSiCUu"
DISCOGS_SECRET = "wVvhtEfwYjwVPZhrwDPZLMBhLqANLBvW"

ICECAST_URL = "http://localhost:8000/vinyl.mp3"

NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

def capture_stream(duration=10):
    response = requests.get(ICECAST_URL, stream=True)
    buffer = bytearray()
    for chunk in response.iter_content(chunk_size=1024):
        buffer.extend(chunk)
        if len(buffer) >= 44100 * 2 * duration:
            break
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
    return response.json()

def extract_metadata(result):
    metadata = result.get('metadata', {})
    music = metadata.get('music', [{}])[0]
    title = music.get('title', 'Unknown')
    artist = ", ".join([a['name'] for a in music.get('artists', [])])
    album = music.get('album', {}).get('name', 'Unknown')
    cover = music.get('album', {}).get('cover', '')

    return title, artist, album, cover

def get_album_cover_from_discogs(artist, album):
    print(f"[INFO] Searching Discogs for cover: {artist} - {album}")
    query = f"{artist} {album}"
    response = requests.get(
        "https://api.discogs.com/database/search",
        params={
            "q": query,
            "format": "vinyl",
            "key": DISCOGS_KEY,
            "secret": DISCOGS_SECRET
        }
    )
    response_json = response.json()
    results = response_json.get("results", [])
    
    if results:
        cover = results[0].get("cover_image", "")
        print(f"[INFO] Found cover on Discogs: {cover}")
        return cover
    
    print("[WARN] No cover found on Discogs.")
    return ""

while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)

    if result.get('status', {}).get('code') == 0:
        title, artist, album, cover = extract_metadata(result)

        if not cover:
            cover = get_album_cover_from_discogs(artist, album)

        now_playing_data = {
            "title": title,
            "artist": artist,
            "cover": cover or ""
        }

        with open(NOW_PLAYING_PATH, "w") as f:
            json.dump(now_playing_data, f)

        print(f"Now playing: {artist} - {title}")
    else:
        print("Geen track herkend.")

    time.sleep(15)
