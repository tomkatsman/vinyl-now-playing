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
DISCOGS_USERNAME = "tomkatsman"  # <- Vul hier jouw Discogs gebruikersnaam in
DISCOGS_TOKEN = "SxMnoBAJYKjqsqIZPlQuMitpZDRFEbvYVHkhXmxG"

ICECAST_URL = "http://localhost:8000/vinyl.mp3"
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

# Variabelen voor het tracken van polling en laatste track
poll_interval = 15  # start met 15 seconden, past zichzelf aan
last_track = None


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


def find_album_cover_on_discogs(artist, track_title):
    print(f"[INFO] Searching Discogs collection for artist '{artist}' and track '{track_title}'...")

    url = f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases"
    response = requests.get(url, headers={
        "Authorization": f"Discogs token={DISCOGS_KEY}"
    })

    if response.status_code != 200:
        print(f"[WARN] Failed to fetch collection from Discogs. Status: {response.status_code}")
        return ""

    releases = response.json().get("releases", [])

    for release in releases:
        basic_info = release.get("basic_information", {})
        release_artist = basic_info.get("artists", [{}])[0].get("name", "").lower()

        # Skip albums van andere artiesten
        if artist.lower() not in release_artist:
            continue

        # Haal de volledige release details op (voor de tracklist)
        release_id = release.get("id")
        release_response = requests.get(f"https://api.discogs.com/releases/{release_id}", headers={
            "Authorization": f"Discogs token={DISCOGS_KEY}"
        })

        if release_response.status_code != 200:
            continue

        release_data = release_response.json()
        tracklist = release_data.get("tracklist", [])

        # Zoek de tracktitel in de tracklist
        track_found = any(track_title.lower() in track.get("title", "").lower() for track in tracklist)

        if track_found:
            cover_image = basic_info.get("cover_image", "")
            print(f"[INFO] Found matching album cover: {cover_image}")
            return cover_image

    print("[INFO] No matching album found for this track in your collection.")
    return ""


while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)

    if result.get('status', {}).get('code') == 0:
        title, artist, album = extract_metadata(result)

        current_track = f"{artist} - {title}"
        if current_track == last_track:
            poll_interval = 60  # Zelfde track, check na 60 sec
        else:
            poll_interval = 15  # Nieuwe track, check sneller
            last_track = current_track

        cover = find_album_cover_on_discogs(artist, title)

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

