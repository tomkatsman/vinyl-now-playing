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
last_track = None
silence_counter = 0
current_album_tracklist = []
current_track_index = 0

# Opschoonfunctie voor titels
def clean_title(title):
    cleaned = re.sub(r"\(.*?\)", "", title)
    cleaned = re.sub(r"\[.*?\]", "", cleaned)
    to_remove = ["Remaster", "Deluxe", "Live", "Edition", "Official Video", "2021", "2005"]
    for word in to_remove:
        cleaned = cleaned.replace(word, "")
    return cleaned.strip()

# Stream capture met stilte-detectie
def capture_stream(duration=10):
    global silence_counter
    response = requests.get(ICECAST_URL, stream=True)
    buffer = bytearray()

    for chunk in response.iter_content(chunk_size=1024):
        buffer.extend(chunk)
        if len(buffer) >= 44100 * 2 * duration:
            break

    rms = audioop.rms(buffer, 2)
    if rms < 100:
        silence_counter += 1
    else:
        silence_counter = 0

    print(f"[DEBUG] Captured {len(buffer)} bytes, RMS volume: {rms}, Silence counter: {silence_counter}")
    return buffer

# ACRCloud fingerprinting
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

# Metadata parsing
def extract_metadata(result):
    music_list = result.get('metadata', {}).get('music', [])
    if not music_list:
        return "Unknown", "Unknown", "Unknown", 0, 180

    best_match = max(music_list, key=lambda m: m.get('score', 0))
    title = best_match.get('title', 'Unknown')
    artist = ", ".join([a['name'] for a in best_match.get('artists', [])])
    album = best_match.get('album', {}).get('name', 'Unknown')
    play_offset = best_match.get('play_offset_ms', 0) // 1000
    duration = best_match.get('duration_ms', 180000) // 1000

    return clean_title(title), artist, album, play_offset, duration

# Zoek en cache de tracklist van een album
def fetch_tracklist_from_discogs(artist, album):
    global current_album_tracklist
    print(f"[INFO] Fetching tracklist for {artist} - {album} from your Discogs collection...")
    releases = fetch_all_discogs_releases()

    for release in releases:
        basic_info = release.get('basic_information', {})
        if artist.lower() in basic_info.get('artists', [{}])[0].get('name', '').lower() and album.lower() in basic_info.get('title', '').lower():
            release_id = release.get('id')
            release_details = requests.get(
                f"https://api.discogs.com/releases/{release_id}",
                headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}
            ).json()
            current_album_tracklist = [track['title'] for track in release_details.get('tracklist', [])]
            return release_details.get('images', [{}])[0].get('uri', '')
    return ""

# Hoofdlus
while True:
    if silence_counter >= 3:  # 30 seconden stilte
        print("[INFO] 30 seconden stilte gedetecteerd, starten met trackherkenning.")
        audio = capture_stream(10)
        result = recognize_audio(audio)

        if result.get('status', {}).get('code') == 0:
            title, artist, album, play_offset, duration = extract_metadata(result)
            cover = fetch_tracklist_from_discogs(artist, album)
            remaining_time = max(0, duration - play_offset)

            with open(NOW_PLAYING_PATH, "w") as f:
                json.dump({"title": title, "artist": artist, "cover": cover}, f)

            print(f"[INFO] Now playing: {artist} - {title}, Next track in {remaining_time} seconds")
            time.sleep(remaining_time)
            
            # Automatisch volgende track spelen
            for track in current_album_tracklist[1:]:
                with open(NOW_PLAYING_PATH, "w") as f:
                    json.dump({"title": track, "artist": artist, "cover": cover}, f)
                print(f"[INFO] Now playing: {artist} - {track}")
                time.sleep(180)  # Gemiddelde tracklengte als schatting

    time.sleep(poll_interval)
