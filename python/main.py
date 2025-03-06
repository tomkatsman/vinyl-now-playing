import requests
import time
import json
import os
import base64
import hashlib
import hmac
import re
import wave
import audioop
import warnings
from difflib import SequenceMatcher
from datetime import datetime

# DeprecationWarning onderdrukken voor audioop
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Config
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "d81b9041a5088eefc54fe9d951e8f40b"
ACR_ACCESS_SECRET = "T7a8zHSW56NFCBJge5pNYTfZpB0vNlMxwujnyFYn"
DISCOGS_USERNAME = "tomkatsman"
DISCOGS_TOKEN = "SxMnoBAJYKjqsqIZPlQuMitpZDRFEbvYVHkhXmxG"
ICECAST_URL = "http://localhost:8000/vinyl.mp3"
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

silence_threshold = 100
silence_required_for_reset = 30
current_album = None
current_track_index = 0
current_track_duration = 0
last_detected_track = None
force_initial_recognition = True
silence_duration = 0

def log(level, message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{level}] {timestamp} {message}")

def clean_title(title):
    return re.sub(r"(\[.*?\]|\(.*?\)|Remaster|Deluxe|Live|Edition|Official Video|\d{4})", "", title).strip()

def capture_stream(duration=10):
    response = requests.get(ICECAST_URL, stream=True)
    buffer = bytearray()
    for chunk in response.iter_content(1024):
        buffer.extend(chunk)
        if len(buffer) >= 44100 * 2 * duration:
            break
    with wave.open("captured_audio.wav", "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(buffer)
    rms = audioop.rms(buffer, 2)
    log("DEBUG", f"Captured {len(buffer)} bytes, RMS volume: {rms}")
    return buffer, rms

def recognize_audio(audio_bytes):
    timestamp = int(time.time())
    signature_string = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{timestamp}"
    signature = base64.b64encode(hmac.new(ACR_ACCESS_SECRET.encode(), signature_string.encode(), hashlib.sha1).digest()).decode()

    response = requests.post(f"https://{ACR_HOST}/v1/identify", files={'sample': ('vinyl.mp3', audio_bytes)}, data={
        'access_key': ACR_ACCESS_KEY,
        'sample_bytes': len(audio_bytes),
        'timestamp': timestamp,
        'signature': signature,
        'data_type': 'audio',
        'signature_version': '1'
    })
    result = response.json()
    log("DEBUG", json.dumps(result, indent=4))
    return result

def extract_metadata(result):
    metadata = result.get('metadata', {})
    music_list = metadata.get('music', [])

    if not music_list:
        music_list = metadata.get('humming', [])
        if music_list:
            log("WARNING", "Geen reguliere match gevonden, fallback naar humming.")

    if not music_list:
        log("WARNING", "Geen herkenbare muziek gevonden.")
        return "Unknown", "Unknown", "Unknown", 0

    music = music_list[0]
    return (
        clean_title(music.get('title', 'Unknown')),
        music['artists'][0]['name'] if music.get('artists') else "Unknown Artist",
        clean_title(music['album'].get('name', 'Unknown Album') if music.get('album') else "Unknown Album"),
        music.get('play_offset_ms', 0)
    )

def fetch_discogs_collection():
    releases, page = [], 1
    while True:
        response = requests.get(f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases", headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}, params={"page": page, "per_page": 100})
        if response.status_code != 200: break
        page_data = response.json().get("releases", [])
        releases.extend(page_data)
        if len(page_data) < 100: break
        page += 1
    log("INFO", f"Fetched {len(releases)} releases from Discogs.")
    return releases

def find_album_and_tracklist(artist, album, collection, track_title):
    for release in collection:
        if artist.lower() not in release['basic_information']['artists'][0]['name'].lower():
            continue
        release_id = release['id']
        details = requests.get(f"https://api.discogs.com/releases/{release_id}", headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}).json()

        for track in details.get('tracklist', []):
            if SequenceMatcher(None, clean_title(track['title']).lower(), clean_title(track_title).lower()).ratio() > 0.7:
                return details

    return None

def find_track_index(title, tracklist):
    for i, track in enumerate(tracklist):
        if SequenceMatcher(None, clean_title(title).lower(), clean_title(track['title']).lower()).ratio() > 0.7:
            return i
    return 0

def update_now_playing(title, artist, cover):
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump({"title": title, "artist": artist, "cover": cover}, f)
    log("INFO", f"Now playing: {artist} - {title}")

def show_current_track(play_offset_ms=0):
    global current_track_duration
    track = current_album['tracklist'][current_track_index]
    title = clean_title(track['title'])
    minutes, seconds = divmod(play_offset_ms // 1000, 60)
    track_duration = sum(int(x) * 60**i for i, x in enumerate(reversed(track['duration'].split(":"))))
    time_until_next = max(track_duration - (play_offset_ms // 1000), 0)
    cover = current_album.get('images', [{}])[0].get('uri', '')
    update_now_playing(title, current_album['artists'][0]['name'], cover)
    current_track_duration = time_until_next

def reset_to_listening_mode():
    global current_album, current_track_index, current_track_duration, force_initial_recognition
    current_album, current_track_index, current_track_duration = None, 0, 0
    force_initial_recognition = True

collection = fetch_discogs_collection()
while True:
    if current_album:
        time.sleep(max(current_track_duration - 10, 0))
        time.sleep(10)
    else:
        audio, rms = capture_stream(10)
        if rms < silence_threshold:
            silence_duration += 10
        else:
            silence_duration = 0

        if silence_duration >= silence_required_for_reset:
            reset_to_listening_mode()
        elif force_initial_recognition:
            title, artist, album, offset = extract_metadata(recognize_audio(audio))
            album_data = find_album_and_tracklist(artist, album, collection, title)
            if album_data:
                current_album = album_data
                current_track_index = find_track_index(title, album_data['tracklist'])
                show_current_track(offset)
                force_initial_recognition = False
        time.sleep(1)
