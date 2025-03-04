#!/bin/bash
set -e

# Update & install system packages
sudo apt-get update
sudo apt-get install -y darkice icecast2 python3 python3-venv

# Copy darkice config
sudo cp darkice/darkice.cfg /etc/darkice.cfg

# Create and set up Python virtual environment
cd /home/pi/vinyl-now-playing
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
venv/bin/pip install flask requests

# Create systemd service for DarkIce
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

# Create systemd service for Now Playing recognition (ACRCloud versie)
sudo tee /etc/systemd/system/vinyl-now-playing.service > /dev/null <<EOF
[Unit]
Description=Vinyl Now Playing Metadata Service
After=network.target

[Service]
WorkingDirectory=/home/pi/vinyl-now-playing
ExecStart=/home/pi/vinyl-now-playing/venv/bin/python /home/pi/vinyl-now-playing/python/main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Create systemd service for the webserver
sudo tee /etc/systemd/system/vinyl-web.service > /dev/null <<EOF
[Unit]
Description=Vinyl Now Playing Web Server
After=network.target

[Service]
WorkingDirectory=/home/pi/vinyl-now-playing
ExecStart=/home/pi/vinyl-now-playing/venv/bin/python /home/pi/vinyl-now-playing/python/webserver.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Enable & start all services
sudo systemctl enable vinyl-stream
sudo systemctl enable vinyl-now-playing
sudo systemctl enable vinyl-web

sudo systemctl start vinyl-stream
sudo systemctl start vinyl-now-playing
sudo systemctl start vinyl-web

echo "Installation complete! Visit http://<your-pi-ip>:5000 to see the Now Playing page."
