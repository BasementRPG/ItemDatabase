#!/bin/bash
set -e

# Install Chromium dependencies and browser
python3 -m playwright install-deps chromium
python3 -m playwright install chromium

# Start your Discord bot
python3 bot.py

