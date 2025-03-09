import requests
import time
import json
import os
import base64
import hashlib
import hmac
import re
import audioop
import warnings
from difflib import SequenceMatcher
from datetime import datetime

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Config
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "d81b9041a5088eefc54fe9d951e8f40b"
ACR_ACCESS_SECRET = "T7a8zHSW56NFCBJge5pNYTfZpB0vNlMxwujnyFYn"
DISCOGS_USERNAME = "tomkatsman"
DISCOGS_TOKEN = "SxMnoBAJYKjqsqIZPlQuMitpZDRFEbvYVHkhXmxG"
ICECAST_URL = "http://localhost:8000/vinyl.mp3"
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

volume_threshold = 100
trigger_increase_factor = 1.5

# Helper functies
def log(level, message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{level}] {timestamp} {message}")

def clean_title(title):
    return re.sub(r"(\[.*?\]|\(.*?\)|Remaster|Deluxe|\bLive\b|Edition|Official Video|\d{4})", "", title).strip()

def capture_stream(duration=10):
    response = requests.get(ICECAST_URL, stream=True)
    buffer = bytearray()
    for chunk in response.iter_content(1024):
        buffer.extend(chunk)
        if len(buffer) >= 44100 * 2 * duration:
            break
    rms = audioop.rms(buffer, 2)
    log("DEBUG", f"Captured {len(buffer)} bytes, RMS volume: {rms}")
    return buffer, rms

def measure_silence(threshold=200):
    """
    Meet het RMS-volume van de stream en kijkt of de data écht stil is.
    Geeft een waarschuwing als de stream constant volume heeft terwijl er geen geluid te horen is.
    """
    log("INFO", "Meten van het volume om te controleren of de stream echt stil is...")

    rms_values = []
    for _ in range(5):
        _, rms = capture_stream(1)
        rms_values.append(rms)
        log("DEBUG", f"Gemeten RMS: {rms}")

    avg_rms = sum(rms_values) / len(rms_values)

    if avg_rms > threshold:
        log("WARNING", f"RMS blijft hoog ({avg_rms}), maar je hoort niets! Mogelijk kunstmatige ruis in de stream.")
    else:
        log("INFO", f"RMS lijkt laag ({avg_rms}). De stream is waarschijnlijk echt stil.")

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
        log("WARNING", "Geen herkenbare muziek gevonden.")
        return "Unknown", "Unknown", "Unknown", 0, 0, "none"

    music = music_list[0]
    play_offset_ms = max(music.get('play_offset_ms', 0) + 30000, 0)

    return (
        clean_title(music.get('title', 'Unknown')),
        music['artists'][0]['name'] if music.get('artists') else "Unknown Artist",
        clean_title(music['album'].get('name', 'Unknown Album') if music.get('album') else "Unknown Album"),
        play_offset_ms,
        music.get('duration_ms', 0),
        "music"
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
    matched_releases = []
    
    for release in collection:
        discogs_artists = [a['name'].lower() for a in release['basic_information']['artists']]
        acr_artist = artist.lower()

        # Controleer of een van de artiesten exact overeenkomt
        if any(acr_artist in discogs_artist or discogs_artist in acr_artist for discogs_artist in discogs_artists):
            matched_releases.append(release)

    for release in matched_releases:
        release_id = release['id']
        details = requests.get(f"https://api.discogs.com/releases/{release_id}", 
                               headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}).json()
        
        for track in details.get('tracklist', []):
            discogs_track_title = clean_title(track['title']).lower()
            acr_track_title = clean_title(track_title).lower()
            
            # Controleer of de titels een deelstring zijn van elkaar
            if acr_track_title in discogs_track_title or discogs_track_title in acr_track_title:
                return details  # Retourneer het juiste album
        
    return None

def find_track_index(title, tracklist):
    for index, track in enumerate(tracklist):
        if SequenceMatcher(None, clean_title(track['title']).lower(), clean_title(title).lower()).ratio() > 0.7:
            return index
    return 0

def update_now_playing(title, artist, cover, play_offset_ms, duration_ms, source):
    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump({"title": title, "artist": artist, "cover": cover, "play_offset_ms": play_offset_ms, "duration_ms": duration_ms, "source": source}, f)
    log("INFO", f"Now playing: {artist} - {title} (Source: {source})")

def wait_for_audio_trigger(check_interval=1):
    log("INFO", "Wachten op audio-trigger (volume-toename)...")
    previous_rms = None
    threshold_count = 0  # Telt hoe vaak een verhoging wordt gedetecteerd

    while True:
        _, rms = capture_stream(check_interval)
        log("DEBUG", f"Actueel RMS: {rms}, Vorige RMS: {previous_rms}")

        if previous_rms is not None:
            # Controleer of er een significante toename is
            if rms > previous_rms * trigger_increase_factor and rms > volume_threshold:
                threshold_count += 1
                log("DEBUG", f"Volume-stijging {threshold_count}/3 gedetecteerd...")
                
                # Zorg ervoor dat de stijging een paar keer voorkomt om toevallige spikes te voorkomen
                if threshold_count >= 3:
                    log("INFO", f"Volume-toename bevestigd na {threshold_count} metingen. Trigger geactiveerd.")
                    return  # Stop met wachten en ga verder
            else:
                threshold_count = 0  # Reset de teller als de stijging stopt

        previous_rms = rms  # Update vorige RMS-waarde

collection = fetch_discogs_collection()

while True:
    measure_silence()
    wait_for_audio_trigger()  # Wachten tot een plaat wordt opgezet
    time.sleep(2)  # Wachten voordat audio wordt opgenomen

    # Stap 1: Herken muziek
    audio, _ = capture_stream(10)
    result = recognize_audio(audio)
    title, artist, album, offset, duration, source = extract_metadata(result)

    if title == "Unknown":
        log("WARNING", "Geen herkenbare muziek gevonden, terug naar wachten op trigger.")
        continue

    # Stap 2: Zoek album en tracklist
    album_data = find_album_and_tracklist(artist, album, collection, title)

    if album_data:
        track_index = find_track_index(title, album_data['tracklist'])
        update_now_playing(title, artist, album_data['images'][0]['uri'], offset, duration, source)
        
        # Stap 3: Automatisch album afspelen
        for current_track_index in range(track_index, len(album_data['tracklist'])):
            track = album_data['tracklist'][current_track_index]
            title = clean_title(track['title'])
            duration_parts = track['duration'].split(":")
            duration_ms = (int(duration_parts[0]) * 60 + int(duration_parts[1])) * 1000
            
            log("INFO", f"Speelt nu: {title} ({current_track_index+1}/{len(album_data['tracklist'])})")
            update_now_playing(title, artist, album_data['images'][0]['uri'], 0, duration_ms, source)

            # Wachten tot track is afgelopen
            time.sleep((duration_ms / 1000) - 5)
            log("INFO", "5 seconden tot volgende track...")
            time.sleep(5)
        
        log("INFO", "Einde van album bereikt, terug naar luistermodus.")

    else:
        log("WARNING", f"'{title}' niet in collectie gevonden, toont zonder album.")
        update_now_playing(title, artist, None, offset, duration, source)

    # Na afspelen van het album: Terug naar wachten op volume-toename
    log("INFO", "Terug naar wachten op volume-toename (trigger)...")
