import requests
import time
import json
import os
import hmac
import hashlib
import base64

# ACRCloud Config
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = os.getenv("3fea776a493631a8e880d625080aa344")
ACR_ACCESS_SECRET = os.getenv("7UklrI2av7z29joyPhOVJj0cT3RN7KmKAnx3vcdG")

# Discogs Config
DISCOGS_KEY = os.getenv("wQvXfQjNsyxrHlmSiCUu")
DISCOGS_SECRET = os.getenv("wVvhtEfwYjwVPZhrwDPZLMBhLqANLBvW")

# Icecast stream URL
ICECAST_URL = "http://localhost:8000/vinyl.mp3"

# Path to now_playing.json
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
    timestamp = str(int(time.time()))
    string_to_sign = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{timestamp}"
    sign = base64.b64encode(hmac.new(ACR_ACCESS_SECRET.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha1).digest()).decode('utf-8')

    files = {"sample": ("vinyl.mp3", audio_bytes, "audio/mpeg")}
    data = {
        "access_key": ACR_ACCESS_KEY,
        "sample_bytes": len(audio_bytes),
        "timestamp": timestamp,
        "signature": sign,
        "data_type": "audio",
        "signature_version": "1"
    }

    response = requests.post(f"https://{ACR_HOST}/v1/identify", files=files, data=data)

    print("ACRCloud Response:")
    print(json.dumps(response.json(), indent=4))

    return response.json()


def get_album_cover(artist, album):
    query = f"{artist} {album}"
    response = requests.get(
        "https://api.discogs.com/database/search",
        params={"q": query, "format": "vinyl", "key": DISCOGS_KEY, "secret": DISCOGS_SECRET}
    )

    results = response.json().get("results", [])
    if results:
        return results[0].get("cover_image", "")
    return ""


while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)

    if result.get("status", {}).get("code") == 0:
        music = result.get("metadata", {}).get("music", [])[0]
        artist = music.get("artists", [{}])[0].get("name", "")
        title = music.get("title", "")
        album = music.get("album", {}).get("name", "")

        cover = get_album_cover(artist, album)

        with open(NOW_PLAYING_PATH, "w") as f:
            json.dump({"title": title, "artist": artist, "cover": cover}, f)

    time.sleep(15)
