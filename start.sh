#!/bin/bash
cd "$(dirname "$0")"
pip install -r requirements.txt --break-system-packages -q
python app.py
