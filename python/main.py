import requests
import time
import json
import os
import base64
import hashlib
import hmac

ACR_ACCESS_KEY = "3fea776a493631a8e880d625080aa344"
ACR_ACCESS_SECRET = "7UklrI2av7z29joyPhOVJj0cT3RN7KmKAnx3vcdG"

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
    timestamp = str(int(time.time()))
    string_to_sign = "\n".join([
        "POST",
        "/v1/identify",
        ACR_ACCESS_KEY,
        "audio",
        "1",
        timestamp
    ])
    signature = base64.b64encode(hmac.new(
        ACR_ACCESS_SECRET.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha1
    ).digest()).decode('utf-8')

    files = {'sample': ('vinyl.mp3', audio_bytes)}

    data = {
        'access_key': ACR_ACCESS_KEY,
        'data_type': 'audio',
        'signature_version': '1',
        'timestamp': timestamp,
        'signature': signature
    }

    response = requests.post("https://identify-eu-west-1.acrcloud.com/v1/identify", files=files, data=data)
    print("ACRCloud Full Response:", response.json())
    return response.json()


def get_album_cover(artist, title):
    query = f"{artist} {title}"
    response = requests.get(
        "https://api.discogs.com/database/search",
        params={"q": query, "format": "vinyl", "key": DISCOGS_KEY, "secret": DISCOGS_SECRET}
    )
    results = response.json().get("results", [])
    if results:
        return results[0].get("cover_image", "")
    return ""


while True:
    print("Capturing audio from stream...")
    audio = capture_stream(10)

    print("Sending to ACRCloud for recognition...")
    result = recognize_audio(audio)

    if result.get("status", {}).get("code") == 0 and "metadata" in result:
        music = result["metadata"]["music"][0]
        artist = music["artists"][0]["name"]
        title = music["title"]

        print(f"Recognized: {artist} - {title}")
        cover = get_album_cover(artist, title)

        now_playing = {"title": title, "artist": artist, "cover": cover}
    else:
        print("No match found or error.")
        now_playing = {"title": "Listening...", "artist": "", "cover": ""}

    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump(now_playing, f)

    time.sleep(15)
