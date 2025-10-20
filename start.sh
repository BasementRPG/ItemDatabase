#!/bin/bash
set -e

# Install system deps for Chromium
npx playwright install-deps chromium

# Install Chromium browser
npx playwright install --with-deps chromium

# Start your Discord bot
python3 bot.py

