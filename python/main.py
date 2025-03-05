import requests
import time
import json
import os
import base64
import hashlib
import hmac
import re
import audioop
import wave

# ACRCloud credentials
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "d81b9041a5088eefc54fe9d951e8f40b"
ACR_ACCESS_SECRET = "T7a8zHSW56NFCBJge5pNYTfZpB0vNlMxwujnyFYn"

# Discogs credentials
DISCOGS_USERNAME = "tomkatsman"
DISCOGS_TOKEN = "SxMnoBAJYKjqsqIZPlQuMitpZDRFEbvYVHkhXmxG"

ICECAST_URL = "http://localhost:8000/vinyl.mp3"
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

poll_interval = 15
last_track = None
tracklist = []
current_track_index = 0

def clean_title(title):
    return re.sub(r"\(.*?\)|\[.*?\]", "", title).strip()

def capture_stream(duration=10):
    response = requests.get(ICECAST_URL, stream=True)
    buffer = bytearray()

    for chunk in response.iter_content(chunk_size=1024):
        buffer.extend(chunk)
        if len(buffer) >= 44100 * 2 * duration:
            break

    with wave.open("captured_audio.wav", "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(buffer)

    rms = audioop.rms(buffer, 2)
    print(f"[DEBUG] Captured {len(buffer)} bytes, RMS volume: {rms}")

    if rms < 100:
        print("[WARN] Audio volume lijkt erg laag!")

    return buffer

def recognize_audio(audio_bytes):
    timestamp = int(time.time())

    string_to_sign = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{timestamp}"
    signature = base64.b64encode(hmac.new(
        ACR_ACCESS_SECRET.encode(), string_to_sign.encode(), hashlib.sha1
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
    print(f"[DEBUG] ACRCloud Response: {response.json()}")
    return response.json()

def extract_metadata(result):
    music = result.get('metadata', {}).get('music', [{}])[0]
    title = clean_title(music.get('title', 'Unknown'))
    artist = ", ".join([a['name'] for a in music.get('artists', [])])
    album = music.get('album', {}).get('name', 'Unknown')
    play_offset = music.get('play_offset_ms', 0) // 1000
    duration = music.get('duration_ms', 0) // 1000

    return title, artist, album, play_offset, duration

def fetch_discogs_tracklist(artist, album):
    print(f"[INFO] Fetching tracklist for {artist} - {album} from your Discogs collection...")
    url = f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases"
    response = requests.get(url, headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"})

    if response.status_code != 200:
        print(f"[WARN] Failed to fetch collection. Status: {response.status_code}")
        return []

    for release in response.json().get("releases", []):
        release_artist = release.get("basic_information", {}).get("artists", [{}])[0].get("name", "").lower()
        release_title = release.get("basic_information", {}).get("title", "").lower()

        if artist.lower() in release_artist and album.lower() in release_title:
            release_id = release.get("id")
            details = requests.get(f"https://api.discogs.com/releases/{release_id}", headers={
                "Authorization": f"Discogs token={DISCOGS_TOKEN}"
            }).json()
            return [clean_title(track["title"]) for track in details.get("tracklist", [])]

    print(f"[WARN] No matching album found for {artist} - {album}")
    return []

def fetch_album_cover(artist, album):
    url = f"https://api.discogs.com/database/search"
    response = requests.get(url, headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}, params={
        "artist": artist, "release_title": album, "format": "vinyl"
    })

    if response.status_code != 200:
        return ""

    results = response.json().get("results", [])
    if results:
        return results[0].get("cover_image", "")
    return ""

def write_now_playing(title, artist, cover, source=""):
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump({"title": title, "artist": artist, "cover": cover, "source": source}, f)

def detect_silence():
    audio = capture_stream(5)
    rms = audioop.rms(audio, 2)
    return rms < 100

def wait_for_silence(threshold=30):
    print("[INFO] Waiting for silence to detect end of side...")
    silence_timer = 0
    while silence_timer < threshold:
        if detect_silence():
            silence_timer += 5
        else:
            silence_timer = 0
        time.sleep(5)

def play_album_side():
    global current_track_index

    while current_track_index < len(tracklist):
        current_track = tracklist[current_track_index]
        print(f"[INFO] Displaying next track: {current_track}")

        write_now_playing(current_track, current_artist, current_cover, "Discogs Tracklist")
        current_track_index += 1
        time.sleep(240)  # Simpele schatting van tracklengte, of haal echte lengte uit Discogs

    print("[INFO] Album side complete. Waiting for new ACRCloud detection after silence.")
    wait_for_silence()

while True:
    audio = capture_stream(10)
    result = recognize_audio(audio)

    if result.get('status', {}).get('code') == 0:
        title, artist, album, play_offset, duration = extract_metadata(result)
        remaining_time = max(0, duration - play_offset)

        print(f"[INFO] Recognized {artist} - {title}, Album: {album}, Time left: {remaining_time} sec")

        current_cover = fetch_album_cover(artist, album)

        tracklist = fetch_discogs_tracklist(artist, album)
        if not tracklist:
            print("[WARN] No tracklist found, fallback to basic now playing.")
            write_now_playing(title, artist, current_cover, "ACRCloud")
            time.sleep(remaining_time)
            continue

        try:
            current_track_index = tracklist.index(title)
        except ValueError:
            current_track_index = 0

        write_now_playing(title, artist, current_cover, "ACRCloud First Detection")

        time.sleep(remaining_time)
        play_album_side()
    else:
        print(f"[WARN] No track recognized. ACRCloud status: {result.get('status')}")
        time.sleep(poll_interval)
