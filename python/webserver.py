from flask import Flask, jsonify, send_from_directory
import json
import os

app = Flask(__name__, static_folder="web")

NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), "../web/now_playing.json")

@app.route('/now-playing')
def now_playing():
    if os.path.exists(NOW_PLAYING_PATH):
        with open(NOW_PLAYING_PATH, 'r') as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify({"title": "Listening...", "artist": "", "cover": ""})

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)