# Vinyl Now Playing

Stream your turntable over Icecast and auto-detect the album/track via ACRCloud, enrich with Discogs (cover + tracklist), and expose a single `now_playing.json` for Home Assistant / tvOS.

## Requirements

- Raspberry Pi (or any Linux box)
- USB audio input (e.g., Behringer USB Audio CODEC)
- `icecast2`, `darkice`, `ffmpeg`
- Python 3 with `requests`, `urllib3`
- ACRCloud account (access key + secret)
- Discogs personal access token

## Setup

```bash
sudo apt update
sudo apt install -y git python3-pip ffmpeg darkice icecast2
git clone <your-repo-url> ~/vinyl-now-playing
cd ~/vinyl-now-playing
pip3 install -r requirements.txt
cp .env.sample .env
nano .env   # fill ACR/DISCOGS keys, adjust paths if needed
chmod +x start_vinyl.sh
```
