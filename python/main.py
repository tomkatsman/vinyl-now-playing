import requests
import time
import json
import os
import base64
import hashlib
import hmac

# Vul je ACRCloud gegevens hier in!
ACR_HOST = "identify-eu-west-1.acrcloud.com"              # bijv: "eu-west-1.api.acrcloud.com"
ACR_ACCESS_KEY = "3fea776a493631a8e880d625080aa344"
ACR_ACCESS_SECRET = "7UklrI2av7z29joyPhOVJj0cT3RN7KmKAnx3vcdG"

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

    # Direct de ruwe response printen naar je terminal (en in logs als je via systemd draait)
    print("ACRCloud Response:")
    print(json.dumps(response.json(), indent=4))

    return response.json()

def extract_metadata(result):
    metadata = result.get('metadata', {})
    music = metadata.get('music', [{}])[0]
    title = music.get('title', 'Unknown')
    artist = ", ".join([a['name'] for a in music.get('artists', [])])
    album = music.get('album', {}).get('name', 'Unknown')
    cover = music.get('album', {}).get('cover', '')

    return title, artist, album, cover

while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)

    if result.get('status', {}).get('code') == 0:
        title, artist, album, cover = extract_metadata(result)

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
