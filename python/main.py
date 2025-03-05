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
silence_threshold = 100
silence_duration = 0
silence_required_for_reset = 30

current_album = None
current_track_index = 0
current_track_duration = 0
last_detected_track = None

def clean_title(title):
    cleaned = re.sub(r"\(.*?\)", "", title)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    to_remove = ["Remaster", "Deluxe", "Live", "Edition", "Official Video", "2021", "2005"]
    for word in to_remove:
        cleaned = cleaned.replace(word, "")
    return cleaned.strip()

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

    return buffer, rms

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
    result = response.json()
    print(f"[DEBUG] ACRCloud Response: {json.dumps(result, indent=4)}")
    return result

def extract_metadata(result):
    music_list = result.get('metadata', {}).get('music', [])
    humming_list = result.get('metadata', {}).get('humming', [])

    if music_list:
        best_match = max(music_list, key=lambda m: m.get('score', 0))
        print(f"[INFO] Found match in 'music' with score {best_match['score']}")
        return parse_match(best_match)

    if humming_list:
        best_match = max(humming_list, key=lambda m: m.get('score', 0))
        print(f"[INFO] Fallback to 'humming' with score {best_match['score']}")
        return parse_match(best_match)

    print("[WARN] No valid match found.")
    return "Unknown", "Unknown", "Unknown", 0

def parse_match(match):
    title = match.get('title', 'Unknown')
    artist = ", ".join([a['name'] for a in match.get('artists', [])])
    album = match.get('album', {}).get('name', 'Unknown')
    play_offset_ms = match.get('play_offset_ms', 0)
    return clean_title(title), artist, clean_title(album), play_offset_ms

def fetch_all_discogs_releases():
    all_releases = []
    page = 1
    per_page = 100

    while True:
        response = requests.get(
            f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases",
            headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"},
            params={"page": page, "per_page": per_page}
        )

        if response.status_code != 200:
            print(f"[WARN] Failed to fetch Discogs collection page {page}")
            break

        releases = response.json().get("releases", [])
        all_releases.extend(releases)

        if len(releases) < per_page:
            break

        page += 1

    print(f"[INFO] Fetched {len(all_releases)} releases from Discogs.")
    return all_releases

def find_album_and_tracklist(artist, album, all_releases):
    for release in all_releases:
        basic_info = release.get("basic_information", {})
        release_artist = basic_info.get("artists", [{}])[0].get("name", "").lower()

        if artist.lower() not in release_artist:
            continue

        release_id = release["id"]
        release_data = requests.get(
            f"https://api.discogs.com/releases/{release_id}",
            headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}
        ).json()

        if clean_title(release_data.get("title", "")) == album:
            return release_data

    return None

def update_now_playing(title, artist, cover):
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump({"title": title, "artist": artist, "cover": cover}, f)
    print(f"[INFO] Now playing: {artist} - {title}")

def show_next_track():
    global current_album, current_track_index

    current_track_index += 1
    if current_track_index >= len(current_album["tracklist"]):
        print("[INFO] Album side finished, back to listening mode.")
        reset_to_listening_mode()
        return

    next_track = current_album["tracklist"][current_track_index]
    title = clean_title(next_track["title"])
    duration = next_track.get("duration", "0:00")
    minutes, seconds = map(int, duration.split(":"))
    global current_track_duration
    current_track_duration = minutes * 60 + seconds

    cover = current_album.get("images", [{}])[0].get("uri", "")
    update_now_playing(title, current_album["artists"][0]["name"], cover)

def reset_to_listening_mode():
    global current_album, current_track_index, current_track_duration
    current_album = None
    current_track_index = 0
    current_track_duration = 0

force_initial_recognition = True
discogs_collection = fetch_all_discogs_releases()

while True:
    if current_album:
        time.sleep(current_track_duration)
        show_next_track()
    else:
        audio, rms = capture_stream(10)
        if rms < silence_threshold:
            silence_duration += 10
            if silence_duration >= silence_required_for_reset:
                print("[INFO] 30 seconden stil, reset naar luisteren.")
                reset_to_listening_mode()
                silence_duration = 0
                continue
        else:
            silence_duration = 0

        if force_initial_recognition or silence_duration == 0:
            result = recognize_audio(audio)
            if result['status']['code'] == 0:
                title, artist, album, _ = extract_metadata(result)
                album_data = find_album_and_tracklist(artist, album, discogs_collection)

                if album_data:
                    current_album = album_data
                    show_next_track()
                else:
                    update_now_playing(title, artist, "")
                force_initial_recognition = False

        time.sleep(poll_interval)
