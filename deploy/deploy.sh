#!/usr/bin/env bash
# Ultra Job Agent — one-command server deploy script
# Usage: bash deploy/deploy.sh [--update]
# Requirements: Ubuntu 22.04+, Python 3.11+, nginx, certbot

set -euo pipefail
APP_DIR="/opt/ultra-job-agent"
REPO_URL="${REPO_URL:-https://github.com/your-username/ultra-job-agent.git}"
DOMAIN="${DOMAIN:-your-domain.com}"
SERVICE="ultra-job-agent"

echo "==> Ultra Job Agent Deploy"

if [[ "${1:-}" == "--update" ]]; then
    echo "--- Updating existing deploy ---"
    cd "$APP_DIR"
    git pull origin main
    .venv/bin/pip install -r requirements.txt --quiet
    .venv/bin/python -m playwright install chromium --with-deps
    sudo systemctl restart "$SERVICE"
    echo "Deploy updated ✓"
    exit 0
fi

# Fresh install
echo "--- Fresh install to $APP_DIR ---"
sudo apt-get update -q
sudo apt-get install -y python3.11 python3.11-venv nginx certbot python3-certbot-nginx git

sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet
.venv/bin/python -m playwright install chromium --with-deps

# Copy .env
if [[ ! -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "!!! Edit $APP_DIR/.env with your values before starting !!!"
fi

# Create resume dirs
mkdir -p resumes/tailored resumes/generated resumes/variants resumes/uploads

# Systemd service
sudo cp deploy/systemd.service "/etc/systemd/system/$SERVICE.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE"

# Nginx
sudo cp deploy/nginx.conf "/etc/nginx/sites-available/$SERVICE"
sudo sed -i "s/your-domain.com/$DOMAIN/g" "/etc/nginx/sites-available/$SERVICE"
sudo ln -sf "/etc/nginx/sites-available/$SERVICE" "/etc/nginx/sites-enabled/$SERVICE"
sudo nginx -t && sudo nginx -s reload

echo ""
echo "Deploy complete!"
echo "  1. Edit $APP_DIR/.env with your Supabase/OpenRouter/etc keys"
echo "  2. Run: sudo systemctl start $SERVICE"
echo "  3. SSL: sudo certbot --nginx -d $DOMAIN"
