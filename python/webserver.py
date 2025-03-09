from flask import Flask, jsonify
import json
import os

app = Flask(__name__)

NOW_PLAYING_PATH = os.path.join(os.path.dirname(__file__), '../web/now_playing.json')

def load_now_playing():
    """
    Probeert 'now_playing.json' in te laden en terug te sturen als JSON.
    Geeft een lege JSON terug als het bestand ontbreekt of er een fout optreedt.
    """
    try:
        with open(NOW_PLAYING_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARNING] Kon 'now_playing.json' niet lezen: {e}")
        return {}  # Retourneer een lege JSON bij fout

@app.route('/now-playing')
def now_playing():
    """
    Haalt de huidige 'Now Playing' status op en geeft deze terug als JSON.
    """
    return jsonify(load_now_playing())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
