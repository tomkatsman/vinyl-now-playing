import requests
import time
import json
import os
import base64
import hashlib
import hmac

# ACRCloud credentials
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "3fea776a493631a8e880d625080aa344"
ACR_ACCESS_SECRET = "7UklrI2av7z29joyPhOVJj0cT3RN7KmKAnx3vcdG"

# Discogs credentials
DISCOGS_KEY = "wQvXfQjNsyxrHlmSiCUu"
DISCOGS_SECRET = "wVvhtEfwYjwVPZhrwDPZLMBhLqANLBvW"
DISCOGS_USERNAME = "tomkatsman"  # <- vul hier jouw Discogs gebruikersnaam in

ICECAST_URL = "http://localhost:8000/vinyl.mp3"
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

last_track = None
poll_interval = 15  # start met 15 seconden, past zichzelf aan

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
    return title, artist, album

def find_album_cover_on_discogs(artist, album):
    print(f"[INFO] Searching Discogs for '{artist} - {album}' in your collection...")
    url = f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases"
    response = requests.get(url, params={
        "token": f"{DISCOGS_KEY}-{DISCOGS_SECRET}"
    })
    if response.status_code != 200:
        print("[WARN] Failed to fetch collection from Discogs.")
        return ""

    releases = response.json().get("releases", [])
    for release in releases:
        if artist.lower() in release["basic_information"]["artists"][0]["name"].lower() and \
           album.lower() in release["basic_information"]["title"].lower():
            return release["basic_information"].get("cover_image", "")

    print("[INFO] No match found in your collection.")
    return ""

while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)

    global poll_interval
    global last_track

    if result.get('status', {}).get('code') == 0:
        title, artist, album = extract_metadata(result)

        current_track = f"{artist} - {title}"
        if current_track == last_track:
            poll_interval = 60  # zelfde track, check na 60 sec
        else:
            poll_interval = 15  # nieuwe track, check sneller
            last_track = current_track

        cover = find_album_cover_on_discogs(artist, album)

        now_playing_data = {
            "title": title,
            "artist": artist,
            "cover": cover
        }

        with open(NOW_PLAYING_PATH, "w") as f:
            json.dump(now_playing_data, f)

        print(f"[INFO] Now playing: {artist} - {title}")
    else:
        print("[WARN] Geen track herkend. Poll interval blijft 15 seconden.")
        poll_interval = 15

    time.sleep(poll_interval)
