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

# Cleanup voor titels
def clean_title(title):
    cleaned = re.sub(r"\(.*?\)", "", title)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    to_remove = ["Remaster", "Deluxe", "Live", "Edition", "Official Video", "2021", "2005"]
    for word in to_remove:
        cleaned = cleaned.replace(word, "")
    return cleaned.strip()

# Audio capture en volume check
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

# Stuur audio naar ACRCloud
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

# Extract metadata uit ACR response
def extract_metadata(result):
    def parse_match(match):
        return (
            clean_title(match.get('title', 'Unknown')),
            ", ".join([a['name'] for a in match.get('artists', [])]),
            match.get('album', {}).get('name', 'Unknown'),
            match.get('play_offset_ms', 0),
            match.get('duration_ms', 0)
        )

    music_list = result.get('metadata', {}).get('music', [])
    humming_list = result.get('metadata', {}).get('humming', [])

    if music_list:
        best_match = max(music_list, key=lambda m: m.get('score', 0))
        if best_match.get('score', 0) >= 30:
            print(f"[INFO] Found match in 'music' with score {best_match['score']}")
            return parse_match(best_match)

    if humming_list:
        best_match = max(humming_list, key=lambda m: m.get('score', 0))
        if best_match.get('score', 0) >= 70:
            print(f"[INFO] No match in 'music', fallback to 'humming' with score {best_match['score']}")
            return parse_match(best_match)

    print("[WARN] No valid match found in 'music' or 'humming'.")
    return "Unknown", "Unknown", "Unknown", 0, 0

# Haal Discogs collectie op
def fetch_discogs_collection():
    all_releases = []
    page = 1

    while True:
        response = requests.get(
            f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases",
            headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"},
            params={"page": page, "per_page": 100}
        )
        if response.status_code != 200:
            print(f"[WARN] Failed to fetch Discogs collection (page {page}).")
            break

        releases = response.json().get("releases", [])
        all_releases.extend(releases)
        if len(releases) < 100:
            break
        page += 1

    print(f"[INFO] Fetched {len(all_releases)} releases from Discogs.")
    return all_releases

# Update now-playing JSON
def update_now_playing(title, artist, cover):
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump({"title": title, "artist": artist, "cover": cover}, f)
    print(f"[INFO] Now playing: {artist} - {title}")

# Zoek album+tracklist in collectie
def find_album_and_tracklist(artist, album, collection):
    for release in collection:
        basic_info = release["basic_information"]
        if artist.lower() in basic_info["artists"][0]["name"].lower():
            release_id = release["id"]
            release_data = requests.get(
                f"https://api.discogs.com/releases/{release_id}",
                headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}
            ).json()

            if clean_title(release_data["title"]) == album:
                return release_data

    return None

# Toon volgende track in album
def show_next_track():
    global current_track_index, current_album

    current_track_index += 1
    if current_track_index >= len(current_album["tracklist"]):
        print("[INFO] Album side finished, back to listening mode.")
        current_album = None
        return

    next_track = current_album["tracklist"][current_track_index]
    title = clean_title(next_track["title"])
    minutes, seconds = map(int, next_track["duration"].split(":"))
    global current_track_duration
    current_track_duration = minutes * 60 + seconds

    cover = current_album.get("images", [{}])[0].get("uri", "")
    update_now_playing(title, current_album["artists"][0]["name"], cover)

# Init
collection = fetch_discogs_collection()

while True:
    if current_album:
        time.sleep(current_track_duration)
        show_next_track()
        continue

    audio, rms = capture_stream(10)

    if rms < silence_threshold:
        silence_duration += 10
        if silence_duration >= silence_required_for_reset:
            print("[INFO] 30 sec silence detected, resetting...")
            current_album = None
            last_detected_track = None
            silence_duration = 0
        continue

    result = recognize_audio(audio)
    if result['status']['code'] != 0:
        time.sleep(15)
        continue

    title, artist, album, play_offset, duration = extract_metadata(result)
    track_time_left = (duration - play_offset) // 1000

    if f"{artist} - {title}" != last_detected_track:
        print(f"[INFO] New track detected: {artist} - {title}")
        last_detected_track = f"{artist} - {title}"

        album_data = find_album_and_tracklist(artist, album, collection)
        if album_data:
            current_album, current_track_index, current_track_duration = album_data, 0, track_time_left
            show_next_track()
        else:
            update_now_playing(title, artist, "")

    time.sleep(15)
