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
import sys
import math

# Ensure stdout handles UTF-8 properly
sys.stdout.reconfigure(encoding='utf-8')

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Config
ACR_HOST = "identify-eu-west-1.acrcloud.com"
ACR_ACCESS_KEY = "d81b9041a5088eefc54fe9d951e8f40b"
ACR_ACCESS_SECRET = "T7a8zHSW56NFCBJge5pNYTfZpB0vNlMxwujnyFYn"
DISCOGS_USERNAME = "tomkatsman"
DISCOGS_TOKEN = "SxMnoBAJYKjqsqIZPlQuMitpZDRFEbvYVHkhXmxG"
ICECAST_URL = "http://localhost:8000/vinyl.mp3"
NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

current_album = None
current_track_index = 0
current_track_duration = 0


def log(level, message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{level}] {timestamp} {message}")


def rms_to_dbfs(rms, sample_width=2):
    if rms == 0:
        return -float('inf')
    max_val = float(2 ** (8 * sample_width - 1))
    return 20 * math.log10(rms / max_val)


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
    dbfs = rms_to_dbfs(rms)
    log("DEBUG", f"Captured {len(buffer)} bytes, RMS volume: {rms}, dBFS: {dbfs:.2f}")
    return buffer, dbfs


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
    log("DEBUG", json.dumps(result, indent=4, ensure_ascii=False))
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
    raw_title = music.get('title', 'Unknown')
    log("DEBUG", f"Raw title from ACRCloud: {raw_title}")

    play_offset_ms = music.get('play_offset_ms', 0)
    play_offset_ms = max(play_offset_ms + 30000, 0)

    return (
        clean_title(raw_title),
        music['artists'][0]['name'] if music.get('artists') else "Unknown Artist",
        clean_title(music['album'].get('name', 'Unknown Album') if music.get('album') else "Unknown Album"),
        play_offset_ms,
        music.get('duration_ms', 0),
        source
    )


def update_now_playing(title, artist, cover, play_offset_ms, duration_ms, source):
    data = {
        "title": title,
        "artist": artist,
        "cover": cover,
        "play_offset_ms": play_offset_ms,
        "duration_ms": duration_ms,
        "source": source
    }
    with open(NOW_PLAYING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    log("INFO", f"Now playing: {artist} - {title} (Source: {source})")


def get_stream_volume():
    try:
        cmd = ["ffmpeg", "-i", ICECAST_URL, "-t", "2", "-af", "volumedetect", "-f", "null", "-"]
        result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        volume_lines = [line for line in result.stderr.split("\n") if "mean_volume" in line]
        if not volume_lines:
            return None
        mean_volume = float(re.search(r"mean_volume: ([\-\d\.]+) dB", volume_lines[0]).group(1))
        return mean_volume
    except Exception as e:
        log("ERROR", f"Fout bij volume meten: {e}")
        return None


# --- MAIN LOOP ---

log("INFO", "Vinyl recognizer gestart.")

while True:
    audio, baseline_volume_dbfs = capture_stream(10)
    result = recognize_audio(audio)
    title, artist, album, offset, duration, source = extract_metadata(result)

    if title == "Unknown":
        time.sleep(5)
        continue

    update_now_playing(title, artist, None, offset, duration, source)
    log("INFO", f"Time until next track: {duration//60000:02}:{(duration//1000)%60:02}")

    duration_seconds = duration // 1000
    track_end_time = time.time() + duration_seconds
    silence_threshold = baseline_volume_dbfs - 14
    silence_seconds = 0

    log("INFO", f"Stilte drempel ingesteld op {silence_threshold:.2f} dBFS (baseline: {baseline_volume_dbfs:.2f})")

    while True:
        current_volume = get_stream_volume()

        if current_volume is None:
            log("DEBUG", "Geen volume gemeten.")
            time.sleep(1)
            continue

        log("DEBUG", f"Gemeten volume: {current_volume:.1f} dBFS")
        if current_volume < silence_threshold:
            silence_seconds += 1
            log("DEBUG", f"Stilte gedetecteerd ({silence_seconds}s onder drempel)")
        else:
            silence_seconds = 0

        if silence_seconds >= 5:
            log("INFO", f"Vroegtijdige trackwissel na {silence_seconds}s stilte.")
            break

        if time.time() >= track_end_time:
            log("INFO", f"Tijd verlopen ({duration_seconds}s), wissel naar volgende track.")
            break

        time.sleep(1)

    log("INFO", f"Wachten op herkenning volgende track...")
    time.sleep(1)
