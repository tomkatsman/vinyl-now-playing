from flask import Flask, jsonify, send_from_directory
import json
import os

# Bepaal de absolute paden correct ongeacht waar het script wordt gestart
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB_DIR = os.path.join(BASE_DIR, "web")
NOW_PLAYING_PATH = os.path.join(WEB_DIR, "now_playing.json")

# Maak de Flask app aan met de juiste static folder
app = Flask(__name__, static_folder=WEB_DIR)

@app.route('/now-playing')
def now_playing():
    if os.path.exists(NOW_PLAYING_PATH):
        with open(NOW_PLAYING_PATH, 'r') as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify({"title": "Listening...", "artist": "", "cover": ""})

@app.route('/')
def index():
    return send_from_directory(WEB_DIR, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
