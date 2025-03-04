import requests
import time
import json
import os
import base64
import hashlib
import hmac

# ACRCloud Config
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "3fea776a493631a8e880d625080aa344"  # Jouw echte key
ACR_ACCESS_SECRET = "7UklrI2av7z29joyPhOVJj0cT3RN7KmKAnx3vcdG"  # Jouw echte secret

# Icecast Stream Config
ICECAST_URL = "http://localhost:8000/vinyl.mp3"

# Path naar now_playing.json (voor de webserver)
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")


def capture_stream(duration=10):
    print("[INFO] Capturing audio from Icecast stream...")
    response = requests.get(ICECAST_URL, stream=True)
    buffer = bytearray()
    for chunk in response.iter_content(chunk_size=1024):
        buffer.extend(chunk)
        if len(buffer) >= 44100 * 2 * duration:
            break
    print(f"[INFO] Captured {len(buffer)} bytes of audio.")
    return bytes(buffer)


def recognize_audio(audio_bytes):
    print("[INFO] Sending audio to ACRCloud for recognition...")
    timestamp = int(time.time())

    string_to_sign = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{timestamp}"
    signature = base64.b64encode(
        hmac.new(ACR_ACCESS_SECRET.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha1).digest()
    ).decode('utf-8')

    files = {'sample': ('vinyl.mp3', audio_bytes)}
    data = {
        'access_key': ACR_ACCESS_KEY,
        'data_type': 'audio',
        'signature_version': '1',
        'timestamp': str(timestamp),
        'signature': signature
    }

    response = requests.post(f"https://{ACR_HOST}/v1/identify", files=files, data=data)
    print(f"[DEBUG] ACRCloud Response: {response.json()}")
    return response.json()


while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)

    if result.get("status", {}).get("code") == 0 and "metadata" in result:
        music_info = result["metadata"]["music"][0]
        artist = music_info["artists"][0]["name"]
        title = music_info["title"]
        album = music_info.get("album", {}).get("name", "")

        print(f"[INFO] Recognized: {artist} - {title} (Album: {album})")

        # Cover was hier niet opgehaald — we gebruikten alleen ACRCloud
        now_playing = {"title": title, "artist": artist, "cover": ""}  # cover leeggelaten

    else:
        print("[WARN] No match found, or ACRCloud error.")
        now_playing = {"title": "Listening...", "artist": "", "cover": ""}

    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump(now_playing, f)

    time.sleep(15)
