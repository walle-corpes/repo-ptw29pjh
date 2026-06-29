#!/usr/bin/env bash
# Deploy АЗС Онлайн Табло to /opt/azs-online and (re)start the service.
# Run on the server as root from the repo root: bash deploy/deploy.sh
set -euo pipefail

APP_DIR=/opt/azs-online
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo ">> syncing code to $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete \
  --exclude '.venv' --exclude '.git' \
  --exclude 'backend/data' \
  "$REPO_DIR"/ "$APP_DIR"/

echo ">> python venv + deps"
if [ ! -d "$APP_DIR/.venv" ]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

echo ">> systemd service"
cp "$APP_DIR/deploy/azs-online.service" /etc/systemd/system/azs-online.service
systemctl daemon-reload
systemctl enable azs-online
systemctl restart azs-online

echo ">> apache vhost"
cp "$APP_DIR/deploy/azslive.conf" /etc/apache2/sites-available/azslive.conf
a2ensite azslive.conf >/dev/null 2>&1 || true
a2enmod proxy proxy_http >/dev/null 2>&1 || true
apache2ctl configtest
systemctl reload apache2

echo ">> done. service status:"
systemctl --no-pager --lines=5 status azs-online || true
