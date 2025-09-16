# main.py — unified output (one JSON), GitHub-safe (env vars), robust I/O

import os
import json
import re
import time
import base64
import hashlib
import hmac
import audioop
import warnings
import subprocess
import signal
from difflib import SequenceMatcher
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------- Env / Config (NO SECRETS IN CODE) ----------
ACR_HOST          = os.getenv("ACR_HOST", "identify-eu-west-1.acrcloud.com")
ACR_ACCESS_KEY    = os.environ["ACR_ACCESS_KEY"]
ACR_ACCESS_SECRET = os.environ["ACR_ACCESS_SECRET"]
DISCOGS_USERNAME  = os.environ["DISCOGS_USERNAME"]
DISCOGS_TOKEN     = os.environ["DISCOGS_TOKEN"]

ICECAST_URL       = os.getenv("ICECAST_URL", "http://localhost:8000/vinyl.mp3")
NOW_PLAYING_PATH  = os.getenv(
    "NOW_PLAYING_PATH",
    os.path.join(os.path.dirname(__file__), "now_playing.json"),
)
NOW_PLAYING_POST_URL = os.getenv("NOW_PLAYING_POST_URL")  # optional: push to your API

DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "12"))

# ---------- HTTP session with retries ----------
session = requests.Session()
session.headers.update({"User-Agent": "VinylNowPlaying/1.0"})
retry = Retry(total=5, backoff_factor=0.4, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retry))
session.mount("http://", HTTPAdapter(max_retries=retry))

# ---------- Globals ----------
current_album = None
current_track_index = 0
_stop = False

# ---------- Utils ----------
def log(level, message):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{level}] {ts} {message}", flush=True)

def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)

def _post_json(url, payload):
    if not url:
        return
    try:
        r = session.post(url, json=payload, timeout=DEFAULT_TIMEOUT)
        if r.status_code >= 400:
            log("WARNING", f"POST {url} -> {r.status_code}: {r.text[:160]}")
    except Exception as e:
        log("WARNING", f"POST {url} failed: {e}")

def clean_title(title):
    return re.sub(r"(\[.*?\]|\(.*?\)|Remaster|Deluxe|\bLive\b|Edition|Official Video|\d{4})", "", title or "").strip()

# ---------- Audio I/O ----------
def recognize_audio(audio_bytes):
    timestamp = int(time.time())
    signature_string = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{timestamp}"
    signature = base64.b64encode(
        hmac.new(ACR_ACCESS_SECRET.encode(), signature_string.encode(), hashlib.sha1).digest()
    ).decode()

    response = requests.post(
        f"https://{ACR_HOST}/v1/identify",
        files={'sample': ('vinyl.wav', audio_bytes)},
        data={
            'access_key': ACR_ACCESS_KEY,
            'sample_bytes': len(audio_bytes),
            'timestamp': timestamp,
            'signature': signature,
            'data_type': 'audio',
            'signature_version': '1'
        }
    )

    # Log both status and full JSON response
    try:
        result = response.json()
        log("DEBUG", f"ACRCloud HTTP {response.status_code}")
        log("DEBUG", f"ACRCloud raw JSON: {json.dumps(result, indent=2)}")
        return result
    except Exception as e:
        log("ERROR", f"Failed to parse ACRCloud response: {e}")
        log("ERROR", f"Raw response text: {response.text[:500]}...")
        return {}

def get_stream_volume():
    """Return mean_volume (dBFS) via FFmpeg volumedetect, or None if unavailable."""
    try:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info",
               "-i", ICECAST_URL, "-t", "2", "-af", "volumedetect", "-f", "null", "-"]
        r = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        for line in r.stderr.split("\n"):
            if "mean_volume" in line:
                mv = float(re.search(r"mean_volume: ([\-\d\.]+) dB", line).group(1))
                log("DEBUG", f"Gemeten volume: {mv} dBFS")
                return mv
        log("WARNING", "Kon geen volume meten met FFmpeg.")
        return None
    except Exception as e:
        log("ERROR", f"Fout bij het meten van volume: {e}")
        return None

# ---------- ACR ----------
def recognize_audio(audio_bytes):
    ts = int(time.time())
    sig_str = f"POST\n/v1/identify\n{ACR_ACCESS_KEY}\naudio\n1\n{ts}"
    signature = base64.b64encode(hmac.new(ACR_ACCESS_SECRET.encode(), sig_str.encode(), hashlib.sha1).digest()).decode()
    r = session.post(
        f"https://{ACR_HOST}/v1/identify",
        files={'sample': ('vinyl.mp3', audio_bytes)},
        data={
            'access_key': ACR_ACCESS_KEY,
            'sample_bytes': len(audio_bytes),
            'timestamp': ts,
            'signature': signature,
            'data_type': 'audio',
            'signature_version': '1'
        },
        timeout=DEFAULT_TIMEOUT
    )
    return r.json()

def extract_metadata(result):
    md = result.get('metadata', {})
    music = (md.get('music') or md.get('humming') or [])
    if not music:
        log("WARNING", "Geen herkenbare muziek gevonden.")
        return "Unknown", "Unknown", "Unknown", 0, 0, "none"
    m = music[0]
    play_offset_ms = max(m.get('play_offset_ms', 0) + 30000, 0)  # compensate minor lag
    return (
        clean_title(m.get('title', 'Unknown')),
        m['artists'][0]['name'] if m.get('artists') else "Unknown Artist",
        clean_title(m['album'].get('name', 'Unknown Album') if m.get('album') else "Unknown Album"),
        play_offset_ms,
        m.get('duration_ms', 0),
        "music"
    )

# ---------- Discogs ----------
_discogs_release_cache = {}

def fetch_discogs_collection():
    releases, page = [], 1
    headers = {"Authorization": f"Discogs token={DISCOGS_TOKEN}"}
    while True:
        r = session.get(
            f"https://api.discogs.com/users/{DISCOGS_USERNAME}/collection/folders/0/releases",
            headers=headers, params={"page": page, "per_page": 100}, timeout=DEFAULT_TIMEOUT
        )
        if r.status_code != 200:
            break
        page_data = r.json().get("releases", [])
        releases.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1
    log("INFO", f"Fetched {len(releases)} releases from Discogs.")
    return releases

def find_album_and_tracklist(artist, album, collection, track_title):
    headers = {"Authorization": f"Discogs token={DISCOGS_TOKEN}"}
    cand = [r for r in collection if artist.lower() in r['basic_information']['artists'][0]['name'].lower()]
    for rel in cand:
        rid = rel['id']
        if rid not in _discogs_release_cache:
            rr = session.get(f"https://api.discogs.com/releases/{rid}", headers=headers, timeout=DEFAULT_TIMEOUT)
            if rr.status_code != 200:
                continue
            _discogs_release_cache[rid] = rr.json()
        details = _discogs_release_cache[rid]
        for t in details.get('tracklist', []):
            if SequenceMatcher(None, clean_title(t.get('title','')).lower(), clean_title(track_title).lower()).ratio() > 0.7:
                return details
    return None

def find_track_index(title, tracklist):
    for i, t in enumerate(tracklist):
        if SequenceMatcher(None, clean_title(t.get('title','')).lower(), clean_title(title).lower()).ratio() > 0.7:
            return i
    return 0

# ---------- Unified output ----------
def update_now_playing(
    status=False,
    code=204,
    title="",
    artist="",
    cover="",
    play_offset_ms=0,
    duration_ms=0,
    source="",
    tracklist=None
):
    data = {
        "status": status,
        "code": code,
        "title": title,
        "artist": artist,
        "cover": cover,
        "play_offset_ms": play_offset_ms,
        "duration_ms": duration_ms,
        "source": source,
    }
    if tracklist:
        data["tracklist"] = [
            {"position": t.get("position", ""), "title": clean_title(t.get("title", ""))}
            for t in tracklist if "title" in t and "position" in t
        ]
    _atomic_write(NOW_PLAYING_PATH, data)
    _post_json(NOW_PLAYING_POST_URL, data)
    log("INFO", f"Updated now_playing.json: {title or 'Idle'}")

def show_current_track(album, idx, play_offset_ms=0, duration_ms=0):
    track = album['tracklist'][idx]
    title = clean_title(track['title'])
    cover = album.get('images', [{}])[0].get('uri', '')
    update_now_playing(
        status=True, code=200, title=title, artist=album['artists'][0]['name'],
        cover=cover, play_offset_ms=play_offset_ms, duration_ms=duration_ms,
        source="music", tracklist=album['tracklist']
    )

# ---------- Graceful shutdown ----------
def _handle_stop(signum, frame):
    global _stop
    _stop = True
signal.signal(signal.SIGINT, _handle_stop)
signal.signal(signal.SIGTERM, _handle_stop)

# ---------- Main ----------
def main():
    global current_album, current_track_index

    collection = fetch_discogs_collection()
    was_silent = False
    low_threshold = -30  # dBFS for inter-track silence

    while not _stop:
        volume = get_stream_volume()
        if volume is None:
            update_now_playing(status=False, code=503)
            time.sleep(5)
            continue

        if volume < -45:
            if not was_silent:
                log("INFO", "Stilte gedetecteerd. Wachten op nieuwe track…")
            was_silent = True
            update_now_playing(status=False, code=204)
            time.sleep(2)
            continue

        if was_silent:
            log("INFO", "Volumeherstel na stilte — nieuwe track vermoedelijk gestart.")
            was_silent = False

        update_now_playing(status=True, code=200)  # heartbeat

        # Recognize
        log("INFO", "Start herkenning via ACRCloud…")
        pcm, rms = capture_stream(10)
        if not pcm:
            time.sleep(4)
            continue

        try:
            result = recognize_audio(pcm)
        except Exception as e:
            log("WARNING", f"ACRCloud error: {e}")
            time.sleep(4)
            continue

        title, artist, album, offset, duration, _ = extract_metadata(result)
        if title == "Unknown":
            time.sleep(4)
            continue

        album_data = find_album_and_tracklist(artist, album, collection, title)
        if not album_data:
            time.sleep(3)
            continue

        current_album = album_data
        current_track_index = find_track_index(title, current_album['tracklist'])
        show_current_track(current_album, current_track_index, offset, duration)

        # Track advance via silence→resume
        last_side = None
        while not _stop:
            # wait until silence
            while not _stop:
                v = get_stream_volume()
                if v is None:
                    time.sleep(1); continue
                if v < low_threshold:
                    log("INFO", f"Stilte: {v} dBFS. Wachten op volgende track…")
                    break
                time.sleep(1)

            if _stop: break

            # wait until resume
            while not _stop:
                v = get_stream_volume()
                if v is None:
                    time.sleep(1); continue
                if v > low_threshold:
                    log("INFO", f"Herstel: {v} dBFS. Volgende track.")
                    break
                time.sleep(1)

            if _stop: break

            # increment track
            current_track_index += 1
            if current_track_index >= len(current_album['tracklist']):
                log("INFO", "Einde album — nieuwe herkenning volgt.")
                current_album = None
                update_now_playing(status=False, code=204)
                time.sleep(5)
                break

            next_track = current_album['tracklist'][current_track_index]
            pos = (next_track.get('position', '') or '').strip()
            m = re.match(r"([A-Z])", pos)
            current_side = m.group(1) if m else None
            if last_side and current_side and current_side != last_side:
                log("INFO", f"Kantwissel {last_side}→{current_side}, pauze 5s…")
                time.sleep(5)
            last_side = current_side

            dur_str = (next_track.get('duration', '') or '').strip()
            if re.match(r"^\d+:\d+$", dur_str):
                minutes, seconds = map(int, dur_str.split(":"))
                duration_ms = (minutes * 60 + seconds) * 1000
            else:
                duration_ms = duration

            show_current_track(current_album, current_track_index, 0, duration_ms)

    log("INFO", "Stopping main loop.")

if __name__ == "__main__":
    main()
