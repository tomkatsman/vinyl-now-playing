from flask import Flask, jsonify, send_from_directory
import json

app = Flask(__name__)

@app.route("/now-playing")
def now_playing():
    try:
        with open("web/now_playing.json") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"title": "Listening...", "artist": "", "cover": ""})

@app.route("/")
def index():
    return send_from_directory("web", "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
