from flask import Flask, jsonify
import json
import os

app = Flask(__name__)

NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), '../web/now_playing.json')

# Cache voor de laatst bekende track
last_known_now_playing = None

def load_now_playing():
    global last_known_now_playing
    try:
        with open(NOW_PLAYING_PATH, 'r') as f:
            data = json.load(f)

        # **Forceer update van de cache als de data anders is**
        if last_known_now_playing != data:
            last_known_now_playing = data
            print(f"[INFO] Now Playing JSON is geüpdatet: {data}")

        return last_known_now_playing

    except Exception as e:
        print(f"[WARNING] Kon 'now_playing.json' niet lezen: {e}")
        return {
            "title": "Kies een plaat uit en zet hem aan",
            "artist": "",
            "cover": "https://img.freepik.com/free-vector/vinyl-retro-music-illustration_24877-60144.jpg",
            "play_offset_ms": 0,
            "duration_ms": 0,
            "source": ""
        }  # **Retourneer standaard JSON als er een fout is**

@app.route('/now-playing')
def now_playing():
    return jsonify(load_now_playing())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
