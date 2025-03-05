from flask import Flask, jsonify
import json
import os

app = Flask(__name__)

NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), '../web/now_playing.json')

# Cache voor de laatst bekende track
last_known_now_playing = {
    "title": "Listening...",
    "artist": "",
    "cover": "default-cover.jpg"
}

def load_now_playing():
    global last_known_now_playing
    try:
        with open(NOW_PLAYING_PATH, 'r') as f:
            data = json.load(f)

        # Alleen als er echt iets in staat (dus geen lege "Listening...")
        if data.get("title") and data.get("artist"):
            last_known_now_playing = data

    except Exception as e:
        print(f"Error reading now_playing.json: {e}")

@app.route('/now-playing')
def now_playing():
    load_now_playing()
    return jsonify(last_known_now_playing)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
