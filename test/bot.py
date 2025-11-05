import os
import math
import discord
import re
import io
import aiohttp
import asyncio
from textwrap import wrap
from PIL import Image, ImageDraw, ImageFont
from discord import app_commands, Interaction
from discord.ext import commands
from discord import app_commands, Attachment
from discord.ui import Modal, TextInput
from datetime import datetime
import asyncpg 
from discord.ui import View, Button
from discord.ui import View, Select
from discord import SelectOption, Interaction
from bs4 import BeautifulSoup
from bs4 import NavigableString
from playwright.async_api import async_playwright
from typing import Optional, Callable, Awaitable



active_views = {}

print("discord.py version:", discord.__version__)

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
UPLOAD_GUILD_ID = 1424737490064904365
UPLOAD_CHANNEL_ID = 1432472242029334600


RACE_OPTIONS = ["DDF","DEF","DGN","DWF","ELF","GNM","GOB","HFL","HIE","HUM","ORG","TRL"]
CLASS_OPTIONS = ["ARC", "BRD", "BST", "CLR", "DRU", "ELE", "ENC", "FTR", "INQ", "MNK", "NEC", "PAL", "RNG", "ROG", "SHD", "SHM", "SPB", "WIZ"]
ITEM_SLOTS = ["Ammo","Back","Chest","Ear","Face","Feet","Finger","Hands","Head","Legs","Neck","Primary","Range","Secondary","Shirt","Shoulders","Waist","Wrist",
              "1H Bludgeoning","2H Bludgeoning","1H Piercing","2H Piercing","1H Slashing","2H Slashing"]
ITEM_STATS = ["AGI","CHA","DEX","INT","STA","STR","WIS","HP","Mana","SV Cold","SV Corruption","SV Disease","SV Electricity","SV Fire","SV Holy","SV Magi","SV Poison"]

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)
db_pool: asyncpg.Pool = None

# ---------- DB Helpers ----------



@bot.tree.command(name="help_itemdb", description="Show help for the Item Database system.")
async def help_itemdb(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛡️ Guild Item Database Bot — Command Guide",
        color=discord.Color.orange()
    )

    embed.add_field(
        name="🔍 Search Items",
        value=(
            "\n**Public Search**\n"
            "`/view_item_db`\n"
            "• Anyone can see & use the filters\n\n"

