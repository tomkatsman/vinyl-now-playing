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
import subprocess
import re
import time

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
force_initial_recognition = True
silence_duration = 0

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
    source = "music"

    if not music_list:
        music_list = metadata.get('humming', [])
        if music_list:
            source = "humming"
            log("WARNING", "Geen reguliere match gevonden, fallback naar humming.")

    if not music_list:
        log("WARNING", "Geen herkenbare muziek gevonden.")
        return "Unknown", "Unknown", "Unknown", 0, 0, "none"

    music = music_list[0]

    play_offset_ms = music.get('play_offset_ms', 0)
    
    # Verschuif alles één minuut naar voren om vertraging te compenseren.
    play_offset_ms = max(play_offset_ms + 30000, 0)

    return (
        clean_title(music.get('title', 'Unknown')),
        music['artists'][0]['name'] if music.get('artists') else "Unknown Artist",
        clean_title(music['album'].get('name', 'Unknown Album') if music.get('album') else "Unknown Album"),
        play_offset_ms,
        music.get('duration_ms', 0),
        source
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
    matched_releases = [release for release in collection if artist.lower() in release['basic_information']['artists'][0]['name'].lower()]
    for release in matched_releases:
        release_id = release['id']
        details = requests.get(f"https://api.discogs.com/releases/{release_id}", headers={"Authorization": f"Discogs token={DISCOGS_TOKEN}"}).json()
        for track in details.get('tracklist', []):
            if SequenceMatcher(None, clean_title(track['title']).lower(), clean_title(track_title).lower()).ratio() > 0.7:
                return details
    return None

def find_track_index(title, tracklist):
    for index, track in enumerate(tracklist):
        if SequenceMatcher(None, clean_title(track['title']).lower(), clean_title(title).lower()).ratio() > 0.7:
            return index
    return 0

def update_now_playing(title, artist, cover, play_offset_ms, duration_ms, source, tracklist=None):
    data = {
        "title": title,
        "artist": artist,
        "cover": cover,
        "play_offset_ms": play_offset_ms,
        "duration_ms": duration_ms,
        "source": source
    }

    if tracklist:
        data["tracklist"] = [clean_title(track["title"]) for track in tracklist]

    with open(NOW_PLAYING_PATH, "w") as f:
        json.dump(data, f)

    log("INFO", f"Now playing: {artist} - {title} (Source: {source})")

def update_status(status, code):
    """
    Werkt het status.json bestand bij met de huidige status en HTTP-statuscode.
    """
    STATUS_PATH = os.path.join(os.path.dirname(__file__), "../web/status.json")
    try:
        with open(STATUS_PATH, "w") as f:
            json.dump({"status": status, "code": code}, f)
        log("INFO", f"Status geüpdatet: status={status}, code={code}")
    except Exception as e:
        log("ERROR", f"Kon status.json niet bijwerken: {e}")

def show_current_track(play_offset_ms=0, duration_ms=0):
    global current_track_duration
    track = current_album['tracklist'][current_track_index]
    title = clean_title(track['title'])
    cover = current_album.get('images', [{}])[0].get('uri', '')
    log("INFO", f"Now playing: {current_album['artists'][0]['name']} - {title} (Track {current_track_index+1}/{len(current_album['tracklist'])}, {play_offset_ms//60000:02}:{(play_offset_ms//1000)%60:02})")
    current_track_duration = (duration_ms - play_offset_ms) // 1000
    log("INFO", f"Time until next track: {current_track_duration//60:02}:{current_track_duration%60:02}")
    update_now_playing(title, current_album['artists'][0]['name'], cover, play_offset_ms, duration_ms, "music", current_album['tracklist'])

def get_stream_volume():
    """
    Meet het gemiddelde volume van de Icecast-stream met FFmpeg.
    Retourneert het volume in dBFS (Decibels Full Scale).
    """
    try:
        cmd = [
            "ffmpeg", "-i", ICECAST_URL, "-t", "2", "-af", "volumedetect", "-f", "null", "-"
        ]
        result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)

        # Zoek naar het gemeten volume in de uitvoer
        volume_lines = [line for line in result.stderr.split("\n") if "mean_volume" in line]
        if not volume_lines:
            print("[WARNING] Kon geen volume meten met FFmpeg.")
            return None

        # Extract volume value
        mean_volume = float(re.search(r"mean_volume: ([\-\d\.]+) dB", volume_lines[0]).group(1))
        print(f"[DEBUG] Gemeten volume: {mean_volume} dBFS")
        return mean_volume
    except Exception as e:
        print(f"[ERROR] Fout bij het meten van volume: {e}")
        return None

# Simpel testscript dat elke 5 seconden het volume meet

collection = fetch_discogs_collection()

was_silent = False  # Houd bij of we net stilte hadden

while True:
    volume = get_stream_volume()

    if volume is None:
        log("WARNING", "Kon volume niet meten, wachten en opnieuw proberen.")
        update_status(False, 503)
        time.sleep(5)
        continue

    if volume < -50:
        if not was_silent:
            log("INFO", "Stilte gedetecteerd. Wacht op nieuwe track...")
            was_silent = True
        update_status(False, 204)
        time.sleep(2)
        continue

    if was_silent:
        log("INFO", "Volumeherstel na stilte — nieuwe track vermoedelijk gestart.")
        was_silent = False
    else:
        log("DEBUG", "Volume stabiel boven drempel.")

    # Eerste herkenning
    update_status(True, 200)
    log("INFO", "Start herkenning via ACRCloud...")
    audio, rms = capture_stream(10)
    result = recognize_audio(audio)
    title, artist, album, offset, duration, source = extract_metadata(result)

    if title == "Unknown":
        time.sleep(5)
        continue

    album_data = find_album_and_tracklist(artist, album, collection, title)

    if album_data:
        current_album = album_data
        current_track_index = find_track_index(title, current_album['tracklist'])
        show_current_track(offset, duration)

        # ⏱️ Start loop die volgende track afwacht via stilte
        while True:
            low_volume_threshold = -40
            low_volume_required_seconds = 5
            check_interval = 1
            low_volume_seconds = 0

            while True:
                volume = get_stream_volume()
                if volume is None:
                    log("WARNING", "Kon volume niet meten tijdens track monitoring.")
                    time.sleep(check_interval)
                    continue

                if volume < low_volume_threshold:
                    low_volume_seconds += check_interval
                    log("DEBUG", f"Volume onder drempel: {volume} dBFS ({low_volume_seconds}/{low_volume_required_seconds}s)")
                else:
                    low_volume_seconds = 0

                if low_volume_seconds >= low_volume_required_seconds:
                    log("INFO", "Stilte gedetecteerd — volgende track wordt gestart.")
                    break

                time.sleep(check_interval)

            current_track_index += 1
            if current_track_index >= len(current_album['tracklist']):
                log("INFO", "Einde van album bereikt, reset naar luistermodus.")
                current_album = None
                break

            next_track = current_album['tracklist'][current_track_index]
            duration_str = next_track.get('duration', "").strip()

            if not duration_str or not re.match(r"^\d+:\d+$", duration_str):
                log("WARNING", f"Geen geldige duur in Discogs voor '{next_track.get('title', 'Onbekend')}', fallback naar vorige waarde.")
                duration_ms = duration
            else:
                try:
                    minutes, seconds = map(int, duration_str.split(":"))
                    duration_ms = (minutes * 60 + seconds) * 1000
                except ValueError:
                    duration_ms = duration

            # ⏱️ Update nu met nieuwe track
            show_current_track(0, duration_ms)

    else:
        log("WARNING", f"Track '{title}' by '{artist}' not found in collection, displaying without album.")
        update_now_playing(title, artist, None, offset, duration, source)

    time.sleep(1)
