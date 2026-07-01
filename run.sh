#!/bin/bash
cd "$(dirname "$0")"
echo "🎙 Whisper Транскрипция → http://localhost:7979"
open "http://localhost:7979"
python3 app.py
