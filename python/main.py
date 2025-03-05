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
current_album = None
current_track_index = None

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
    music = result.get('metadata', {}).get('music', [{}])[0]
    title = clean_title(music.get('title', 'Unknown'))
    artist = ", ".join([a['name'] for a in music.get('artists', [])])
    album = music.get('album', {}).get('name', 'Unknown')
    return title, artist, album

def fetch_discogs_collection():
    collection = []
    page = 1

    while True:
        response = requests.get(
            f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases",
            headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"},
            params={"page": page, "per_page": 100}
        )
        if response.status_code != 200:
            print(f"[WARN] Failed to fetch Discogs collection page {page}")
            break

        data = response.json()
        collection.extend(data.get("releases", []))

        if len(data.get("releases", [])) < 100:
            break
        page += 1

    print(f"[INFO] Fetched {len(collection)} releases from Discogs.")
    return collection

def find_album_in_collection(artist, track_title, collection):
    for release in collection:
        basic_info = release["basic_information"]
        if artist.lower() not in basic_info["artists"][0]["name"].lower():
            continue

        release_id = release["id"]
        release_data = requests.get(
            f"https://api.discogs.com/releases/{release_id}",
            headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}
        ).json()

        for track in release_data.get("tracklist", []):
            if clean_title(track["title"]).lower() == track_title.lower():
                print(f"[INFO] Match gevonden in collectie: {basic_info['title']}")
                return {
                    "title": basic_info["title"],
                    "cover": basic_info.get("cover_image", ""),
                    "artist": artist,
                    "tracklist": release_data["tracklist"]
                }
    return None

def update_now_playing(track):
    now_playing_data = {
        "title": track["title"],
        "artist": current_album["artist"],
        "cover": current_album["cover"]
    }
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump(now_playing_data, f)

def detect_silence(threshold=100, duration=30):
    silent_seconds = 0
    while silent_seconds < duration:
        _, rms = capture_stream(1)
        if rms > threshold:
            return False
        silent_seconds += 1
        time.sleep(1)
    return True

def recognize_new_record():
    global current_album, current_track_index
    audio, _ = capture_stream(10)
    result = recognize_audio(audio)

    if result.get('status', {}).get('code') != 0:
        print("[WARN] Geen herkenning. Blijven luisteren...")
        return

    title, artist, album = extract_metadata(result)
    print(f"[INFO] Nieuwe plaat herkend: {artist} - {title}, Album: {album}")

    current_album = find_album_in_collection(artist, title, discogs_collection)
    if current_album:
        print(f"[INFO] Album gevonden: {current_album['title']}")
        current_track_index = next(
            (i for i, t in enumerate(current_album["tracklist"]) if clean_title(t["title"]).lower() == title.lower()), 
            0
        )
        update_now_playing(current_album["tracklist"][current_track_index])
    else:
        print("[WARN] Geen album gevonden in jouw collectie. Terug naar luisteren...")
        current_album = None
        current_track_index = None

def show_next_track():
    global current_album, current_track_index

    if not current_album:
        print("[INFO] Geen album actief. Wachten op nieuwe herkenning.")
        return

    current_track_index += 1

    if current_track_index >= len(current_album["tracklist"]):
        print("[INFO] Einde album. Terug naar luistermodus.")
        current_album = None
        current_track_index = None
        return

    next_track = current_album["tracklist"][current_track_index]
    print(f"[INFO] Nu spelen: {next_track['title']}")
    update_now_playing(next_track)


# Start flow
discogs_collection = fetch_discogs_collection()
recognize_new_record()  # Direct bij opstarten!

while True:
    if detect_silence():
        print("[INFO] Stilte gedetecteerd, terug naar luistermodus.")
        recognize_new_record()
    else:
        show_next_track()
        time.sleep(15)
