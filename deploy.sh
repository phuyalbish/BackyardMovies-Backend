#!/usr/bin/env bash
# Runs on the cPanel server after each upload (see .github/workflows/deploy.yml): install, migrate, collect static, restart.
# The cPanel Python App's "Application root" must be this repository's folder.
set -euo pipefail
cd "$(dirname "$0")"
APP_DIR="$(pwd)"
REL="${APP_DIR#"$HOME"/}"

# cPanel puts the app's virtualenv at ~/virtualenv/<application root>/<python version>/
ACTIVATE="$(ls -d "$HOME/virtualenv/$REL"/*/bin/activate 2>/dev/null | sort -V | tail -n1 || true)"
if [[ -z "$ACTIVATE" ]]; then
  echo "No virtualenv at ~/virtualenv/$REL. Create the app first: cPanel > Setup Python App, application root '$REL'." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ACTIVATE"
echo "Using $(python --version) from $(dirname "$(dirname "$ACTIVATE")")"
if ! python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Django 6 needs Python 3.12 or newer. In cPanel > Setup Python App, edit the app and pick 3.12+, then deploy again." >&2
  exit 1
fi

# .env must hold the production settings, not just the TMDB token the workflow writes.
missing=()
for key in DJANGO_SECRET_KEY DJANGO_DEBUG DJANGO_ALLOWED_HOSTS CSRF_TRUSTED_ORIGINS CORS_ORIGINS; do
  grep -q "^$key=." .env 2>/dev/null || missing+=("$key")
done
if (( ${#missing[@]} )); then
  echo "$APP_DIR/.env is missing: ${missing[*]}. See the README's 'Deploy on cPanel' section for the lines to add." >&2
  exit 1
fi
if ! grep -q '^DJANGO_DEBUG=0$' .env; then
  echo "$APP_DIR/.env must have DJANGO_DEBUG=0 on the server." >&2
  exit 1
fi

LOG_START=$(wc -l < stderr.log 2>/dev/null || echo 0)
trap 'echo "--- stderr.log during this deploy ---" >&2; tail -n +"$((LOG_START + 1))" stderr.log 2>/dev/null | tail -n 25 >&2 || true' ERR

pip install -q --upgrade pip
pip install -q -r requirements.txt
python manage.py check --deploy --fail-level ERROR
python manage.py migrate --noinput
python manage.py collectstatic --noinput -v0
mkdir -p tmp media
touch tmp/restart.txt   # tells Passenger to reload the app
echo "Backend deployed from $(git rev-parse --short HEAD 2>/dev/null || echo 'working tree')."
