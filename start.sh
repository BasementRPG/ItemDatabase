#!/bin/bash
set -e

echo "🚀 Starting deployment..."

# -------------------------------
# 1️⃣ Install Playwright browsers only once
# -------------------------------

if [ ! -d "/root/.cache/ms-playwright/chromium*" ]; then
  echo "🧩 Installing Playwright Chromium dependencies..."
  python3 -m playwright install-deps chromium
  python3 -m playwright install chromium
else
  echo "✅ Playwright Chromium already installed. Skipping download."
fi

# -------------------------------
# 2️⃣ Start your Discord bot
# -------------------------------
echo "🎮 Launching Discord bot..."
python3 bot.py
