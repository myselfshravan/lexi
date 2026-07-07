#!/usr/bin/env bash
# Start the Lexi backend. Reads GROQ_API_KEY / ALEXA_SKILL_ID from .env (or env).
set -euo pipefail
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [ -f .env ]; then
  set -a; # shellcheck disable=SC1091
  source .env; set +a
fi

exec python app.py
