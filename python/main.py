import requests
import time
import json
import os
import base64
import hashlib
import hmac

# ACRCloud keys
ACR_ACCESS_KEY = "3fea776a493631a8e880d625080aa344"
ACR_ACCESS_SECRET = "7UklrI2av7z29joyPhOVJj0cT3RN7KmKAnx3vcdG"

# Discogs keys
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
    return bytes(buffer)

def recognize_audio(audio_bytes):
    timestamp = int(time.time())
    string_to_sign = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{timestamp}"
    sign = base64.b64encode(hmac.new(ACR_ACCESS_SECRET.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha1).digest()).decode('utf-8')

    files = {'sample': ('vinyl.mp3', audio_bytes)}
    data = {
        'access_key': ACR_ACCESS_KEY,
        'data_type': 'audio',
        'signature_version': '1',
        'timestamp': str(timestamp),
        'signature': sign
    }

    response = requests.post("https://identify-eu-west-1.acrcloud.com/v1/identify", files=files, data=data)
    result = response.json()

    print("ACRCloud Response:", json.dumps(result, indent=4))  # Log de volledige response
    return result

def get_album_cover(artist, album):
    if not album:
        query = f"{artist}"
    else:
        query = f"{artist} {album}"

    auth = (DISCOGS_KEY, DISCOGS_SECRET)

    response = requests.get(
        "https://api.discogs.com/database/search",
        params={"q": query, "format": "vinyl"},
        auth=auth
    )

    if response.status_code != 200:
        print(f"Discogs API failed with status {response.status_code}")
        return ""

    results = response.json().get("results", [])
    if results:
        print(f"Found cover image: {results[0].get('cover_image', '')}")
        return results[0].get("cover_image", "")
    else:
        print("No album cover found on Discogs.")
        return ""

while True:
    print("Capturing audio from stream...")
    audio = capture_stream(10)

    print("Sending to ACRCloud for recognition...")
    result = recognize_audio(audio)

    if result.get("status", {}).get("code") == 0 and result.get("metadata"):
        music_info = result["metadata"]["music"][0]
        artist = music_info["artists"][0]["name"]
        title = music_info["title"]
        album = music_info.get("album", {}).get("name", "")

        print(f"Recognized: {artist} - {title} (Album: {album})")

        cover = get_album_cover(artist, album)
        now_playing = {"title": title, "artist": artist, "cover": cover}
    else:
        print("No match found, or error occurred.")
        now_playing = {"title": "Listening...", "artist": "", "cover": ""}

    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump(now_playing, f)

    time.sleep(15)
