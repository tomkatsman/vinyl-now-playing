import requests
import time
import json
import os

AUDD_API_KEY = "your_audd_api_key"
DISCOGS_KEY = "your_discogs_key"
DISCOGS_SECRET = "your_discogs_secret"
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
    response = requests.post(
        "https://api.audd.io/",
        data={"api_token": AUDD_API_KEY},
        files={"file": ("vinyl.mp3", audio_bytes)}
    )
    return response.json()

def get_album_cover(artist, album):
    query = f"{artist} {album}"
    response = requests.get(
        "https://api.discogs.com/database/search",
        params={"q": query, "format": "vinyl", "key": DISCOGS_KEY, "secret": DISCOGS_SECRET}
    )
    results = response.json().get("results", [])
    if results:
        return results[0]["cover_image"]
    return ""

while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)
    if result.get("result"):
        song = result['result']
        cover = get_album_cover(song['artist'], song.get('album', ''))
        with open(NOW_PLAYING_PATH, "w") as f:
            json.dump({"title": song['title'], "artist": song['artist'], "cover": cover}, f)
    time.sleep(15)
