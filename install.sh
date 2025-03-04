#!/bin/bash
set -e

sudo apt-get update
sudo apt-get install -y darkice icecast2 python3 python3-pip

sudo cp darkice/darkice.cfg /etc/darkice.cfg

pip3 install flask requests

sudo tee /etc/systemd/system/vinyl-stream.service > /dev/null <<EOF
[Unit]
Description=Vinyl Streamer (DarkIce)
After=sound.target

[Service]
ExecStart=/usr/bin/darkice -c /etc/darkice.cfg
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/vinyl-now-playing.service > /dev/null <<EOF
[Unit]
Description=Vinyl Now Playing Metadata Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/vinyl-now-playing/python/main.py
WorkingDirectory=/home/pi/vinyl-now-playing
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/vinyl-web.service > /dev/null <<EOF
[Unit]
Description=Vinyl Now Playing Web Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/vinyl-now-playing/python/webserver.py
WorkingDirectory=/home/pi/vinyl-now-playing
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable vinyl-stream
sudo systemctl enable vinyl-now-playing
sudo systemctl enable vinyl-web

sudo systemctl start vinyl-stream
sudo systemctl start vinyl-now-playing
sudo systemctl start vinyl-web

echo "Installation complete! Visit http://<your-pi-ip>:5000 to see the Now Playing page."
