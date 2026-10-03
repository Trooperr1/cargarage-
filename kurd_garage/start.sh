#!/bin/sh
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fi
.venv/bin/python -c "import PIL" 2>/dev/null || .venv/bin/pip install -q pillow
.venv/bin/python app.py
