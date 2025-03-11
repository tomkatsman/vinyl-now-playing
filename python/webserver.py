from flask import Flask, jsonify
import json
import os

app = Flask(__name__)

NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), '../web/now_playing.json')
STATUS_PATH = os.path.join(os.path.dirname(__file__), '../web/status.json')

# Cache voor de laatst bekende track
last_known_now_playing = None

def load_json_file(path, default_data=None):
    """
    Probeert een JSON-bestand in te laden en geeft een standaardwaarde terug bij fouten.
    """
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARNING] Kon '{path}' niet lezen: {e}")
        return default_data or {}

@app.route('/now-playing')
def now_playing():
    """
    Haalt de huidige 'Now Playing' status op en geeft deze terug als JSON.
    """
    global last_known_now_playing
    data = load_json_file(NOW_PLAYING_PATH, {
        "title": "Kies een plaat uit en zet hem aan",
        "artist": "",
        "cover": "https://img.freepik.com/free-vector/vinyl-retro-music-illustration_24877-60144.jpg",
        "play_offset_ms": 0,
        "duration_ms": 0,
        "source": ""
    })

    if last_known_now_playing != data:
        last_known_now_playing = data
        print(f"[INFO] Now Playing JSON is geüpdatet: {data}")

    return jsonify(last_known_now_playing)

@app.route('/status')
def status():
    """
    Geeft de status van de muziekweergave terug (afspelen of stil).
    """
    return jsonify(load_json_file(STATUS_PATH, {"status": False, "code": 204}))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
