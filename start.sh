#!/bin/bash
set -e

# 🧱 Install Chromium dependencies
apt-get update && apt-get install -y \
    libglib2.0-0 libgobject-2.0-0 libnss3 libnspr4 \
    libnssutil3 libsmime3 libcups2 libatk1.0-0 \
    libatk-bridge2.0-0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libpango-1.0-0 libasound2 \
    libxshmfence1 libxkbcommon0 libx11-xcb1 libdrm2 \
    libdbus-1-3 libxcb1 libxext6 libxfixes3 \
    fonts-liberation libappindicator3-1 lsb-release wget xdg-utils

# 🧩 Install Playwright browser (Chromium)
npx playwright install --with-deps chromium

# ✅ Start your Discord bot
python3 bot.py
