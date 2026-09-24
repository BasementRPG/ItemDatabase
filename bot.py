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
ITEM_SLOTS = ["Ammo","Back","Bag","Chest","Ear","Face","Feet","Finger","Hands","Head","Legs","Neck","Primary","Range","Secondary","Shirt","Shoulders","Waist","Wrist"]
ITEM_STATS = ["AGI","CHA","DEX","INT","STA","STR","WIS","HP","Mana","Hp Regeneration","Mana Regeneration","Haste","Ranged Haste","Spell Haste","SV Cold","SV Corruption","SV Disease","SV Electricity","SV Fire","SV Holy","SV Magic","SV Poison","Instrument"]

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
           
            "**Private Search**\n"
            "`/view_item_dbp`\n"
            "• Only you can see & use the filters\n\n"
            
            "**Search Filters (all optional)**\n"
            "• Select slot, class, and/or stat\n"
            "• Text search — click **Enter Search Terms**\n"
            " ‎ ‎  ‎ ‎ ◦ Enter partial (item, zone, npc) name\n"
            " ‎ ‎  ‎ ‎ ‎‎◦ Submit → Search\n\n"
            
            "🧭 **Navigation**\n"
            "• Previous / Next page buttons\n"
            "• Back to filters\n"
            "• Item dropdown → sends details privately\n"
            "• All links point to the Wiki (zones, NPCs)\n\n"
             
            "📜 **Add Items**\n"
            "`/add_item_db`\n"
            "• Upload item image (required)\n"
            "• Upload NPC image (optional)\n"
            "• Select slots, classes, and stats\n"
            "• Fill item form popup\n"
            "*Check spelling — affects search accuracy*\n\n"
       
            "✏️ **Modify Existing Items**\n"
            "`/edit_item_db`\n"
            "• Enter item name\n"
            "• Edit fields in popup\n\n"
          
            "`/edit_item_image`\n"
            "• Replace item/NPC images only\n"
            "• Enter name → upload new image\n\n"

        ),
        inline=False
    )

    embed.set_footer(text="Tip: Accurate spelling = better results.")

    await interaction.response.send_message(embed=embed)




async def ensure_upload_channel(guild: discord.Guild):
    for ch in guild.text_channels:
        if ch.name == "guild-bank-upload-log":
            return ch
    # create hidden channel
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    return await guild.create_text_channel("guild-bank-upload-log", overwrites=overwrites)



async def ensure_upload_channel1(guild: discord.Guild):
    """Ensure the hidden item database upload log exists or create it."""
    for ch in guild.text_channels:
        if ch.name == "item-database-upload-log":
            return ch

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    return await guild.create_text_channel("item-database-upload-log", overwrites=overwrites)



def format_item_name(name: str) -> str:
    """Capitalize each word except small connectors like 'of' and 'and'."""
    if not name:
        return name

    lowercase_words = {"of", "and", "the"}

    words = name.split()
    formatted = []

    for i, word in enumerate(words):
        lw = word.lower()
        if lw in lowercase_words and i != 0:  # keep lowercase if not first word
            formatted.append(lw)
        else:
            formatted.append(word.capitalize())

    return " ".join(formatted)



class SlotSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        
             
       # Always show all options
        options = [discord.SelectOption(label=i) for i in ITEM_SLOTS]
        
        # ✅ Mark selected slots as default
        for opt in options:
            if hasattr(self.parent_view, "slot") and opt.label in (self.parent_view.slot or []):
                opt.default = True

        # ✅ Multi-select enabled here
        super().__init__(
            placeholder="Select Slot(s)",
            options=options,
            min_values=1,
            max_values=len(options)
        )


    async def callback(self, interaction: discord.Interaction):
        try:
            print(f"DEBUG: SlotSelect callback - values: {self.values}")
    
            # Store selected slots
            self.parent_view.slot = self.values
    
            # Keep selections highlighted
            for opt in self.options:
                opt.default = (opt.value in self.values)
    
            # Update Skill Use dropdown
            if hasattr(self.parent_view, "skill_use_select"):
                self.parent_view.skill_use_select.update_options()
    
            await interaction.response.edit_message(
                view=self.parent_view
            )
    
        except Exception as e:
            print(f"ERROR in SlotSelect callback: {e}")
            import traceback
            traceback.print_exc()
    
            try:
                await interaction.response.send_message(
                    f"Error: {str(e)}",
                    ephemeral=True
                )
            except:
                pass
              

class SkillUseSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view

        super().__init__(
            placeholder="⚔️ Skill Use (select Primary, Secondary, or Range first)...",
            options=[
                discord.SelectOption(
                    label="Select a Slot first",
                    value="disabled"
                )
            ],
            min_values=0,
            max_values=1,
            disabled=True
        )

    def update_options(self):
        selected_slots = self.parent_view.slot or []

        # Reset current Skill Use whenever Slot changes
        self.parent_view.skill_use = None

        if len(selected_slots) != 1:
            self.options = [
                discord.SelectOption(
                    label="Select one Slot first",
                    value="disabled"
                )
            ]
            self.disabled = True
            self.placeholder = "⚔️ Skill Use (select one Slot first)..."
            return

        selected_slot = selected_slots[0]

        if selected_slot == "Primary":
            options = [
                ("1H Bludgeoning", "BLG"),
                ("2H Bludgeoning", "BLG Two Handed"),
                ("1H Piercing", "STA"),
                ("2H Piercing", "STA Two Handed"),
                ("1H Slashing", "SLA"),
                ("2H Slashing", "SLA Two Handed"),
                ("Hand to Hand", "H2H")
            ]

        elif selected_slot == "Secondary":
            options = [
                ("1H Bludgeoning", "BLG"),
                ("1H Piercing", "STA"),
                ("1H Slashing", "SLA"),
                ("Hand to Hand", "H2H")
            ]

        elif selected_slot == "Range":
            options = [
                ("Archery", "ARC"),
                ("Throwing", "THR")
            ]

        else:
            self.options = [
                discord.SelectOption(
                    label="No Skill Use for this Slot",
                    value="disabled"
                )
            ]
            self.disabled = True
            self.placeholder = "⚔️ Skill Use unavailable for this Slot..."
            return

        self.options = [
            discord.SelectOption(
                label=label,
                value=value,
                default=(value == self.parent_view.skill_use)
            )
            for label, value in options
        ]

        self.disabled = False
        self.placeholder = "⚔️ Select Skill Use..."

    async def callback(self, interaction: discord.Interaction):
        if not self.values or self.values[0] == "disabled":
            self.parent_view.skill_use = None
        else:
            # Save the VALUE of the SelectOption
            self.parent_view.skill_use = self.values[0]

        for option in self.options:
            option.default = (
                option.value == self.parent_view.skill_use
            )

        await interaction.response.edit_message(
            view=self.parent_view
        )



class TypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="All",
                value="all"
            ),
            discord.SelectOption(
                label="With Stats",
                value="with_stats",
                default=True
            ),
        ]

        super().__init__(
            placeholder="Select item type",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.type_filter = self.values[0]
        await interaction.response.defer()


class ClassesSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
    
        # Always show all options
        options = [discord.SelectOption(label="All")] + [discord.SelectOption(label=c) for c in CLASS_OPTIONS]
    
        for opt in options:
            if self.parent_view.usable_classes and opt.label in self.parent_view.usable_classes:
                opt.default = True
        
        super().__init__(
            placeholder="Select usable classes (multi)",
            options=options,
            min_values=0,
            max_values=len(options)
        )
    
    async def callback(self, interaction: discord.Interaction):
        # If All is selected, ignore other selections
        if "All" in self.values:
            self.view.usable_classes = ["All"]
        else:
            # If other classes selected while All is in previous selection, remove All
            self.view.usable_classes = self.values
    
        # Update the dropdown so selections are visible
        for option in self.options:
            option.default = option.label in self.view.usable_classes
    
        await interaction.response.edit_message(view=self.view)

    
class StatSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
    
        # Always show all options
        options = [discord.SelectOption(label=s) for s in ITEM_STATS]

        for opt in options:
            if self.parent_view.all_stats and opt.label in self.parent_view.all_stats:
                opt.default = True
        
        super().__init__(
            placeholder="Select all stats (multi)",
            options=options,
            min_values=0,
            max_values=len(options)
        )
    
    async def callback(self, interaction: discord.Interaction):

        self.view.all_stats= self.values
    
        # Update the dropdown so selections are visible
        for option in self.options:
            option.default = option.label in self.view.all_stats
    
        await interaction.response.edit_message(view=self.view)



# ============================================================
# Item Name Start View
# ============================================================

class ItemNameStartView(discord.ui.View):
    def __init__(
        self,
        db_pool,
        guild_id,
        added_by,
        item_image_url,
        npc_image_url,
        item_msg_id,
        npc_msg_id,
        upload_channel_id
    ):
        super().__init__(timeout=900)

        self.db_pool = db_pool
        self.guild_id = guild_id
        self.added_by = added_by

        self.item_image_url = item_image_url
        self.npc_image_url = npc_image_url
        self.item_msg_id = item_msg_id
        self.npc_msg_id = npc_msg_id
        self.upload_channel_id = upload_channel_id

    async def _delete_uploads(self, interaction: discord.Interaction):
        """Best-effort delete of uploaded item/NPC images."""
        try:
            channel = (
                interaction.client.get_channel(self.upload_channel_id)
                or await interaction.client.fetch_channel(self.upload_channel_id)
            )

            if self.item_msg_id:
                try:
                    msg = await channel.fetch_message(self.item_msg_id)
                    await msg.delete()
                except Exception:
                    pass

            if self.npc_msg_id:
                try:
                    msg = await channel.fetch_message(self.npc_msg_id)
                    await msg.delete()
                except Exception:
                    pass

        except Exception:
            pass

    @discord.ui.button(
        label="📝 Enter Item Name",
        style=discord.ButtonStyle.primary
    )
    async def enter_item_name(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_modal(
            ItemNameCheckModal(
                db_pool=self.db_pool,
                guild_id=self.guild_id,
                added_by=self.added_by,
                item_image_url=self.item_image_url,
                npc_image_url=self.npc_image_url,
                item_msg_id=self.item_msg_id,
                npc_msg_id=self.npc_msg_id,
                upload_channel_id=self.upload_channel_id
            )
        )

    @discord.ui.button(
        label="❌ Cancel",
        style=discord.ButtonStyle.danger
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self._delete_uploads(interaction)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content="❌ Upload cancelled and images deleted.",
            view=None
        )

        self.stop()




async def fetch_wiki_item_data(item_name):
    """
    Fetch and parse Wiki information for a single item.

    Returns:
        dict with Wiki item information
        or None if the Wiki page cannot be processed.
    """

    base_url = "https://monstersandmemories.miraheze.org/wiki"
    wiki_base = "https://monstersandmemories.miraheze.org"

    item_url = f"{base_url}/{item_name.replace(' ', '_')}"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        async with aiohttp.ClientSession(headers=headers) as session:

            async with session.get(
                item_url,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:

                if resp.status != 200:
                    print(
                        f"⚠️ Wiki returned HTTP {resp.status} "
                        f"for {item_name}"
                    )
                    return None

                html = await resp.text()

            soup = BeautifulSoup(
                html,
                "html.parser"
            )

            # ---------------------------------------------------------
            # Confirm this is actually the requested Wiki page.
            # ---------------------------------------------------------

            actual_title = ""

            heading = soup.find(
                "h1",
                id="firstHeading"
            )

            if heading:
                actual_title = heading.get_text(
                    strip=True
                )

            if not actual_title:

                title_tag = soup.find("title")

                if title_tag:
                    actual_title = title_tag.get_text(
                        strip=True
                    )

                    actual_title = actual_title.split(
                        " - Monsters and Memories Wiki"
                    )[0].strip()

            if actual_title.lower() != item_name.lower():
                return None


            # ---------------------------------------------------------
            # Drops From
            # ---------------------------------------------------------
            
            npc_name = ""
            zone_name = ""
            
            drops_section = soup.find(
                "h2",
                id="Drops_From"
            )
            
            if drops_section:
            
                # The Wiki places the Drops From content immediately
                # after the heading wrapper.
                drops_heading_wrapper = drops_section.parent
            
                if drops_heading_wrapper:
            
                    # Look only at the immediate siblings of the
                    # Drops From heading.
                    current_sibling = drops_heading_wrapper.find_next_sibling()
            
                    # Find the zone paragraph first.
                    if current_sibling and current_sibling.name == "p":
            
                        zone_name = current_sibling.get_text(
                            " ",
                            strip=True
                        )
            
                        # The NPC list should be the next sibling.
                        current_sibling = current_sibling.find_next_sibling()
            
                    # IMPORTANT:
                    # Only accept the UL directly associated with
                    # Drops From.
                    #
                    # This prevents a Related Quests or Player Crafted
                    # list from being mistaken for an NPC.
                    if current_sibling and current_sibling.name == "ul":
            
                        npc_links = current_sibling.find_all(
                            "a",
                            href=True
                        )
            
                        if npc_links:
            
                            npc_names = []
            
                            for link in npc_links:
            
                                name = link.get_text(
                                    " ",
                                    strip=True
                                )
            
                                if name and name not in npc_names:
                                    npc_names.append(name)
            
                            npc_name = ", ".join(npc_names)
            
                        else:
            
                            # Fallback for plain-text NPC entries.
                            npc_items = current_sibling.find_all("li")
            
                            npc_names = []
            
                            for li in npc_items:
            
                                name = li.get_text(
                                    " ",
                                    strip=True
                                )
            
                                if name and name not in npc_names:
                                    npc_names.append(name)
            
                            npc_name = ", ".join(npc_names)
            
            
            # ---------------------------------------------------------
            # Related Quests
            # ---------------------------------------------------------
            
            quest_name = ""
            
            quest_section = soup.find(
                "h2",
                id="Related_quests"
            )
            
            if quest_section:
            
                quest_heading_wrapper = quest_section.parent
            
                if quest_heading_wrapper:
            
                    quest_list = quest_heading_wrapper.find_next_sibling()
            
                    if quest_list and quest_list.name == "ul":
            
                        quest_links = quest_list.find_all(
                            "a",
                            href=True
                        )
            
                        if quest_links:
            
                            quest_names = []
            
                            for link in quest_links:
            
                                name = link.get_text(
                                    " ",
                                    strip=True
                                )
            
                                if name and name not in quest_names:
                                    quest_names.append(name)
            
                            quest_name = ", ".join(quest_names)
            
            
            # ---------------------------------------------------------
            # If NPC and quest are identical, clear NPC
            # ---------------------------------------------------------
            
            if (
                quest_name
                and npc_name
                and npc_name.strip().lower()
                == quest_name.strip().lower()
            ):
                npc_name = ""
            
            
            # ---------------------------------------------------------
            # NPC Details
            # ---------------------------------------------------------
            
            npc_image = ""
            npc_level = ""
            
            if npc_name:
            
                # Only use the first NPC when multiple NPCs are listed.
                first_npc = (
                    npc_name
                    .split(",")[0]
                    .strip()
                )
            
                # Build the Wiki page URL safely.
                npc_page_name = first_npc.replace(
                    " ",
                    "_"
                )
            
                npc_url = (
                    f"{wiki_base}/wiki/{npc_page_name}"
                )
            
                try:
            
                    async with session.get(
                        npc_url,
                        ssl=False,
                        timeout=aiohttp.ClientTimeout(total=20)
                    ) as npc_resp:
            
                        if npc_resp.status == 200:
            
                            npc_html = await npc_resp.text(
                                errors="ignore"
                            )
            
                            npc_soup = BeautifulSoup(
                                npc_html,
                                "html.parser"
                            )
            
                            # -------------------------------------------------
                            # NPC Image
                            # -------------------------------------------------
            
                            npc_img = None
            
                            # Try the Wiki's normal file image first.
                            image_selectors = [
                                'span[typeof="mw:File"] img',
                                'span[typeof="mw:Image"] img',
                                'figure img',
                                'table.infobox img',
                                'table.wikitable img',
                                'img'
                            ]
            
                            for selector in image_selectors:
            
                                candidate = npc_soup.select_one(
                                    selector
                                )
            
                                if candidate:
            
                                    src = (
                                        candidate.get("src")
                                        or candidate.get("data-src")
                                        or candidate.get("data-original")
                                        or ""
                                    )
            
                                    if src:
                                        npc_img = src
                                        break
            
                            if npc_img:
            
                                # Protocol-relative URL
                                if npc_img.startswith("//"):
            
                                    npc_image = (
                                        f"https:{npc_img}"
                                    )
            
                                # Root-relative Wiki image URL
                                elif npc_img.startswith("/"):
            
                                    npc_image = (
                                        "https://monstersandmemories."
                                        "miraheze.org"
                                        f"{npc_img}"
                                    )
            
                                # Already a complete URL
                                elif npc_img.startswith("http"):
            
                                    npc_image = npc_img
            
                                else:
            
                                    # Relative image URL
                                    npc_image = (
                                        f"{wiki_base}/{npc_img.lstrip('/')}"
                                    )
            
                            # -------------------------------------------------
                            # NPC Level
                            # -------------------------------------------------
            
                            mob_stats = npc_soup.find(
                                "table",
                                class_="mobStatsBox"
                            )
            
                            if mob_stats:
            
                                tds = mob_stats.find_all(
                                    "td"
                                )
            
                                if len(tds) >= 3:
            
                                    npc_level = (
                                        tds[2]
                                        .get_text(
                                            " ",
                                            strip=True
                                        )
                                    )
            
                except Exception as e:
            
                    print(
                        f"⚠️ Failed NPC fetch "
                        f"{npc_url}: {e}"
                    )

           

            # ---------------------------------------------------------
            # Item Stats
            # ---------------------------------------------------------

            item_stats = "None listed"

            item_stats_div = soup.find(
                "div",
                class_="item-stats"
            )

            if item_stats_div:

                lines = [
                    line.strip()
                    for line in item_stats_div.stripped_strings
                ]

                item_stats = "\n".join(lines)

            # ---------------------------------------------------------
            # Same zone/NPC cleanup as existing updater
            # ---------------------------------------------------------

            if any(
                char.isdigit()
                for char in zone_name
            ):

                npc_name, zone_name = (
                    zone_name,
                    ""
                )

            return {
                "item_name": item_name,
                "zone_name": zone_name,
                "zone_area": "",
                "npc_name": npc_name,
                "npc_level": npc_level,
                "npc_image": npc_image,
                "item_stats": item_stats,
                "quest_name": quest_name

            }

    except Exception as e:

        print(
            f"❌ Failed to gather Wiki data "
            f"for '{item_name}': {e}"
        )

        return None


class WikiFoundDataView(discord.ui.View):
    def __init__(
        self,
        item_name,
        wiki_data,
        db_pool,
        guild_id,
        added_by,
        item_image_attachment,
        npc_image_attachment
    ):
        super().__init__(timeout=900)

        self.item_name = item_name
        self.wiki_data = wiki_data or {}
        self.db_pool = db_pool
        self.guild_id = guild_id
        self.added_by = added_by

        self.item_image_attachment = item_image_attachment
        self.npc_image_attachment = npc_image_attachment

    def _extract_item_slot(self, item_stats):
        """
        Extract everything after 'Slot:' from the Wiki item_stats.

        Examples:
            Slot: SLOT1 SLOT2 SLOT3
            -> SLOT1 SLOT2 SLOT3

            Slot: PRIMARY SECONDARY RANGE
            -> PRIMARY SECONDARY RANGE
        """

        if not item_stats:
            return ""

        for line in item_stats.splitlines():
            line = line.strip()

            if line.lower().startswith("slot:"):
                return line.split(":", 1)[1].strip()

        return ""

    async def _upload_item_image(self, upload_channel, interaction):
        """Upload the user's item image and return the Discord message."""

        item_msg = await upload_channel.send(
            file=await self.item_image_attachment.to_file(),
            content=f"📦 Uploaded item image by {interaction.user.mention}"
        )

        return item_msg

    async def _upload_npc_image_from_attachment(
        self,
        upload_channel,
        interaction
    ):
        """Upload the user's supplied NPC image."""

        npc_msg = await upload_channel.send(
            file=await self.npc_image_attachment.to_file(),
            content=f"👹 Uploaded NPC image by {interaction.user.mention}"
        )

        return npc_msg

    async def _upload_npc_image_from_wiki(
        self,
        upload_channel,
        interaction,
        npc_image_url
    ):
        """
        Download the NPC image from the Wiki and upload it to the
        hidden upload channel so the database can use our stored URL.
        """

        if not npc_image_url:
            return None

        try:
            headers = {"User-Agent": "Mozilla/5.0"}

            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(
                    npc_image_url,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:

                    if resp.status != 200:
                        print(
                            f"⚠️ Could not download Wiki NPC image. "
                            f"HTTP {resp.status}"
                        )
                        return None

                    image_bytes = await resp.read()

                    if not image_bytes:
                        return None

                    content_type = (
                        resp.headers.get("Content-Type", "")
                        .lower()
                    )

                    if "jpeg" in content_type or "jpg" in content_type:
                        filename = "wiki_npc_image.jpg"
                    elif "webp" in content_type:
                        filename = "wiki_npc_image.webp"
                    else:
                        filename = "wiki_npc_image.png"

                    npc_file = discord.File(
                        io.BytesIO(image_bytes),
                        filename=filename
                    )

                    npc_msg = await upload_channel.send(
                        file=npc_file,
                        content=(
                            f"👹 Wiki NPC image uploaded by "
                            f"{interaction.user.mention}"
                        )
                    )

                    return npc_msg

        except Exception as e:
            print(f"⚠️ Failed to upload Wiki NPC image: {e}")
            return None

    async def _save_wiki_data(self, interaction):
        """Save the gathered Wiki information directly to item_database."""

        wiki_data = self.wiki_data

        item_name = self.item_name
        item_stats = wiki_data.get("item_stats", "") or ""

        # -----------------------------------------
        # Extract Slot from item_stats
        # -----------------------------------------

        item_slot = self._extract_item_slot(item_stats)

        # -----------------------------------------
        # Get Wiki data
        # -----------------------------------------

        zone_name = wiki_data.get("zone_name", "") or ""
        zone_area = wiki_data.get("zone_area", "") or ""
        npc_name = wiki_data.get("npc_name", "") or ""
        npc_level = wiki_data.get("npc_level", "") or ""

        quest_name = wiki_data.get("quest_name", "") or ""

        wiki_npc_image = wiki_data.get("npc_image", "") or ""

        upload_channel = await ensure_upload_channel1(
            interaction.guild
        )

        # -----------------------------------------
        # Upload user's item image
        # -----------------------------------------

        item_msg = await self._upload_item_image(
            upload_channel,
            interaction
        )

        item_image_url = (
            item_msg.attachments[0].url
            if item_msg.attachments
            else ""
        )

        item_msg_id = item_msg.id

        # -----------------------------------------
        # NPC image
        #
        # User supplied NPC image takes priority.
        # Otherwise use the Wiki NPC image.
        # -----------------------------------------

        npc_msg = None

        if self.npc_image_attachment:
            npc_msg = await self._upload_npc_image_from_attachment(
                upload_channel,
                interaction
            )

        elif wiki_npc_image:
            npc_msg = await self._upload_npc_image_from_wiki(
                upload_channel,
                interaction,
                wiki_npc_image
            )

        if npc_msg and npc_msg.attachments:
            npc_image_url = npc_msg.attachments[0].url
            npc_msg_id = npc_msg.id
        else:
            # If the Wiki image could not be uploaded, retain
            # the Wiki URL rather than losing the information.
            npc_image_url = wiki_npc_image
            npc_msg_id = None

        # -----------------------------------------
        # Insert directly into database
        # -----------------------------------------

        await self.db_pool.execute(
            """
            INSERT INTO item_database (
                guild_id,
                item_name,
                zone_name,
                zone_area,
                npc_name,
                npc_level,
                item_image,
                npc_image,
                item_msg_id,
                npc_msg_id,
                item_stats,
                item_slot,
                added_by,
                created_at,
                quest_name
            )
            VALUES (
                $1,
                $2,
                $3,
                $4,
                $5,
                $6,
                $7,
                $8,
                $9,
                $10,
                $11,
                $12,
                $13,
                NOW(),
                $14
            )
            """,
            self.guild_id,
            item_name,
            zone_name,
            zone_area,
            npc_name,
            npc_level,
            item_image_url,
            npc_image_url,
            item_msg_id,
            npc_msg_id,
            item_stats,
            item_slot,
            self.added_by,
            quest_name
        )

        # -----------------------------------------
        # Finished
        # -----------------------------------------

       
        await interaction.edit_original_response(
            content=(
                f"✅ **{item_name}** has been added to the item database "
                
            ),
            embed=None,
            view=None
        )

        self.stop()

    @discord.ui.button(
        label="📖 Use Found Data",
        style=discord.ButtonStyle.success
    )
    async def use_found_data(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        try:
            await interaction.response.defer()

            await self._save_wiki_data(interaction)

        except Exception as e:
            print(
                f"❌ Failed to save Wiki data for "
                f"'{self.item_name}': {e}"
            )

            if interaction.response.is_done():
                try:
                    await interaction.edit_original_response(
                        content=(
                            f"❌ Failed to add **{self.item_name}** "
                            f"to the database.\n\n"
                            f"Error: `{e}`"
                        ),
                        embed=None,
                        view=self
                    )
                except Exception as edit_error:
                    print(
                        f"❌ Could not update Wiki data error message: "
                        f"{edit_error}"
                    )
            else:
                await interaction.response.send_message(
                    (
                        f"❌ Failed to add **{self.item_name}** "
                        f"to the database.\n\n"
                        f"Error: `{e}`"
                    ),
                    ephemeral=True
                )

    @discord.ui.button(
        label="✏️ Manually Enter",
        style=discord.ButtonStyle.primary
    )

    async def manually_enter(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        try:
            # Acknowledge the button immediately so Discord does not
            # expire the interaction while images are being uploaded.
            await interaction.response.defer()
    
            upload_channel = await ensure_upload_channel1(
                interaction.guild
            )

            # Upload item image
            item_msg = await upload_channel.send(
                file=await self.item_image_attachment.to_file(),
                content=(
                    f"📦 Uploaded item image by "
                    f"{interaction.user.mention}"
                )
            )

            # Upload optional NPC image
            npc_msg = None

            if self.npc_image_attachment:
                npc_msg = await upload_channel.send(
                    file=await self.npc_image_attachment.to_file(),
                    content=(
                        f"👹 Uploaded NPC image by "
                        f"{interaction.user.mention}"
                    )
                )

            item_url = (
                item_msg.attachments[0].url
                if item_msg.attachments
                else ""
            )

            npc_url = (
                npc_msg.attachments[0].url
                if npc_msg and npc_msg.attachments
                else ""
            )

            view = SlotStatClassSelectView(
                db_pool=self.db_pool,
                guild_id=self.guild_id,
                added_by=self.added_by,
                item_image_url=item_url,
                npc_image_url=npc_url if npc_msg else None,
                item_msg_id=item_msg.id,
                npc_msg_id=npc_msg.id if npc_msg else None,
                upload_channel_id=upload_channel.id,
                wiki_data=self.wiki_data
            )

            # IMPORTANT:
            # Manual entry completely ignores the Wiki data.
            view.item_name_from_check = self.item_name
            view.wiki_data = self.wiki_data

            await interaction.edit_original_response(
                content=(
                    "✏️ Continue with the manual item entry.\n\n"
                    "Select the **Slot**, **Classes**, and **Stats**:"
                ),
                embed=None,
                view=view
            )

            view.origin_message = await interaction.original_response()

            self.stop()

        
        except Exception as e:
            print(
                f"❌ Failed to start manual entry for "
                f"'{self.item_name}': {e}"
            )
        
            try:
                await interaction.edit_original_response(
                    content=f"❌ Could not start manual entry: {e}",
                    embed=None,
                    view=None
                )
            except Exception as response_error:
                print(
                    f"❌ Could not send manual entry error message: "
                    f"{response_error}"
                ) 

    @discord.ui.button(
        label="❌ Cancel",
        style=discord.ButtonStyle.danger
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.edit_message(
            content="❌ Item entry cancelled.",
            embed=None,
            view=None
        )

        self.stop()


# ============================================================
# Item Name Check Modal
# ============================================================

class ItemNameCheckModal(discord.ui.Modal, title="Add Item to Database"):
    def __init__(
        self,
        db_pool,
        guild_id,
        added_by,
        item_image,
        npc_image,
        upload_channel_id=None
        
    ):
        super().__init__(timeout=900)

        self.db_pool = db_pool
        self.guild_id = guild_id
        self.added_by = added_by

        # Keep the original uploaded attachments so they can be
        # uploaded to item-database-upload-log after the name check.
        self.item_image_attachment = item_image
        self.npc_image_attachment = npc_image
        self.upload_channel_id = upload_channel_id

        self.item_name = discord.ui.TextInput(
            label="Item Name",
            placeholder="Example: Flowing Black Silk Sash",
            required=True,
            max_length=100
        )

        self.add_item(self.item_name)

    async def _delete_uploads(self, interaction: discord.Interaction):
        """Best-effort cleanup of uploaded item/NPC images."""
        return

    async def _upload_images(self, interaction: discord.Interaction):
        """Upload the item/NPC images to the hidden upload channel."""

        guild = interaction.guild

        upload_channel = None

        if self.upload_channel_id:
            try:
                upload_channel = (
                    interaction.client.get_channel(self.upload_channel_id)
                    or await interaction.client.fetch_channel(self.upload_channel_id)
                )
            except Exception:
                upload_channel = None

        if upload_channel is None:
            upload_channel = await ensure_upload_channel1(guild)

        item_msg = await upload_channel.send(
            file=await self.item_image_attachment.to_file(),
            content=f"📦 Uploaded item image by {interaction.user.mention}"
        )

        npc_msg = None

        if self.npc_image_attachment:
            npc_msg = await upload_channel.send(
                file=await self.npc_image_attachment.to_file(),
                content=f"👹 Uploaded NPC image by {interaction.user.mention}"
            )

        item_url = item_msg.attachments[0].url
        npc_url = npc_msg.attachments[0].url if npc_msg else ""

        return (
            upload_channel,
            item_msg,
            npc_msg,
            item_url,
            npc_url,
            item_msg.id,
            npc_msg.id if npc_msg else None
        )

    async def on_submit(self, interaction: discord.Interaction):

        item_name = self.item_name.value.strip()

        if not item_name:
            await interaction.response.send_message(
                "❌ Please enter an item name.",
                ephemeral=True
            )
            return

        # ============================================================
        # 1. CHECK DATABASE FIRST
        # ============================================================

        try:
            existing_item = await self.db_pool.fetchrow(
                """
                SELECT id, item_name
                FROM item_database
                WHERE (guild_id = $1 OR guild_id IS NULL)
                  AND LOWER(TRIM(item_name)) = LOWER(TRIM($2))
                LIMIT 1
                """,
                self.guild_id,
                item_name
            )

        except Exception as e:
            print(f"❌ Item name database check failed: {e}")

            await interaction.response.send_message(
                "❌ I couldn't check the item database. Please try again.",
                ephemeral=True
            )
            return

        # ============================================================
        # ITEM ALREADY EXISTS
        # ============================================================

        if existing_item:

            await interaction.response.send_message(
                (
                    f"❌ **{existing_item['item_name']}** already exists in the database.\n\n"
                    "Please use `/edit_item_db` for existing items."
                ),
                ephemeral=True
            )
            return

        # ============================================================
        # 2. ITEM NOT IN DATABASE
        #    CHECK THE WIKI
        # ============================================================

        base_url = "https://monstersandmemories.miraheze.org/wiki"
        wiki_url = f"{base_url}/{item_name.replace(' ', '_')}"

        wiki_found = False
        wiki_html = None

        try:
            headers = {
                "User-Agent": "Mozilla/5.0"
            }

            async with aiohttp.ClientSession(headers=headers) as session:

                async with session.get(
                    wiki_url,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:

                    if resp.status == 200:

                        wiki_html = await resp.text()

                        soup = BeautifulSoup(
                            wiki_html,
                            "html.parser"
                        )

                        # Make sure this is an actual Wiki article
                        # and not a MediaWiki missing-page response.
                        heading = soup.find(
                            "h1",
                            id="firstHeading"
                        )

                        if heading:
                            wiki_title = heading.get_text(
                                strip=True
                            )

                            if wiki_title.lower() == item_name.lower():
                                wiki_found = True

                        # Fallback check using page title.
                        if not wiki_found:

                            page_title = soup.find("title")

                            if page_title:
                                title_text = page_title.get_text(
                                    strip=True
                                )

                                title_text = title_text.split(
                                    " - Monsters and Memories Wiki"
                                )[0].strip()

                                if title_text.lower() == item_name.lower():
                                    wiki_found = True

        except Exception as e:
            print(f"⚠️ Wiki check failed for '{item_name}': {e}")

        # ============================================================
        # 3. WIKI ITEM FOUND
        # ============================================================

        if wiki_found:
        
            # ---------------------------------------------------------
            # Wiki item found.
            # Gather the actual information before showing the
            # user the choices.
            # ---------------------------------------------------------
        
            await interaction.response.send_message(
                (
                    f"📖 **{item_name}** was found on the Wiki.\n\n"
                    "🔎 Gathering item information..."
                ),
                ephemeral=True
            )
        
            wiki_data = await fetch_wiki_item_data(item_name)
        
            if not wiki_data:
        
                # If the page disappeared or could not be parsed,
                # fall back to the normal manual workflow.
                try:
        
                    (
                        upload_channel,
                        item_msg,
                        npc_msg,
                        item_url,
                        npc_url,
                        item_msg_id,
                        npc_msg_id
                    ) = await self._upload_images(interaction)
        
                    view = SlotStatClassSelectView(
                        db_pool=self.db_pool,
                        guild_id=self.guild_id,
                        added_by=self.added_by,
                        item_image_url=item_url,
                        npc_image_url=npc_url if npc_msg else None,
                        item_msg_id=item_msg_id,
                        npc_msg_id=npc_msg_id if npc_msg else None,
                        upload_channel_id=upload_channel.id
                    )
        
                    view.item_name_from_check = item_name
                    view.wiki_data = None
        
                    await interaction.edit_original_response(
                        content=(
                            f"⚠️ **{item_name}** was found on the Wiki, "
                            "but I couldn't gather its information.\n\n"
                            "Continue with the manual item entry:"
                        ),
                        view=view
                    )
        
                    view.origin_message = (
                        await interaction.original_response()
                    )
        
                except Exception as e:
        
                    print(
                        f"❌ Manual fallback failed: {e}"
                    )
        
                    await interaction.followup.send(
                        f"❌ Could not continue item entry: {e}",
                        ephemeral=True
                    )
        
                return
        
            # ---------------------------------------------------------
            # Build Wiki review embed
            # ---------------------------------------------------------
        
            review_embed = discord.Embed(
                title=f"📖 Item Data Found: {item_name}",
                description=(
                    "The following information was gathered.\n\n"
                    "Choose how you want to continue."
                ),
                color=discord.Color.blurple()
            )
        
            if wiki_data["zone_name"]:
                review_embed.add_field(
                    name="🗺️ Zone",
                    value=wiki_data["zone_name"][:1024],
                    inline=True
                )
        
            if wiki_data["npc_name"]:
                review_embed.add_field(
                    name="👹 NPC",
                    value=wiki_data["npc_name"][:1024],
                    inline=True
                )
        
            if wiki_data["npc_level"]:
                review_embed.add_field(
                    name="📊 NPC Level",
                    value=wiki_data["npc_level"][:1024],
                    inline=True
                )
        
            if wiki_data["item_stats"]:
                review_embed.add_field(
                    name="⚔️ Item Stats",
                    value=wiki_data["item_stats"][:1024],
                    inline=False
                )
        
            if wiki_data["quest_name"]:
                review_embed.add_field(
                    name="🧩 Related Quest",
                    value=wiki_data["quest_name"][:1024],
                    inline=False
                )
        
        
            review_view = WikiFoundDataView(
                item_name=item_name,
                wiki_data=wiki_data,
                db_pool=self.db_pool,
                guild_id=self.guild_id,
                added_by=self.added_by,
                item_image_attachment=self.item_image_attachment,
                npc_image_attachment=self.npc_image_attachment
            )
        
            # Replace the "Gathering..." message with the review screen.
            await interaction.edit_original_response(
                content=None,
                embed=review_embed,
                view=review_view
            )
        
            return

        # ============================================================
        # 4. NOT IN DATABASE AND NOT ON WIKI
        #    CONTINUE WITH EXISTING MANUAL ADD FLOW
        # ============================================================

        try:

            (
                upload_channel,
                item_msg,
                npc_msg,
                item_url,
                npc_url,
                item_msg_id,
                npc_msg_id
            ) = await self._upload_images(interaction)

            view = SlotStatClassSelectView(
                db_pool=self.db_pool,
                guild_id=self.guild_id,
                added_by=self.added_by,
                item_image_url=item_url,
                npc_image_url=npc_url if npc_msg else None,
                item_msg_id=item_msg_id,
                npc_msg_id=npc_msg_id if npc_msg else None,
                upload_channel_id=upload_channel.id
            )

            # Store the item name so the next stage can use it.
            view.item_name_from_check = item_name

            await interaction.response.send_message(
                (
                    "❌ The item was not found on the Wiki.\n\n"
                    "Continue with the manual item entry:"
                ),
                view=view,
                ephemeral=True
            )

            # Get the actual message because send_message()
            # does not return the Message object.
            view.origin_message = await interaction.original_response()

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to upload files here.",
                ephemeral=True
            )

        except Exception as e:

            print(f"❌ Image upload failed after item-name check: {e}")

            await interaction.response.send_message(
                f"❌ Upload failed: {e}",
                ephemeral=True
            )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception
    ):
        print(f"❌ ItemNameCheckModal error: {error}")

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Something went wrong while checking the item name.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "❌ Something went wrong while checking the item name.",
                    ephemeral=True
                )
        except Exception as e:
            print(f"⚠️ Error handler failed: {e}")



class SlotStatClassSelectView(discord.ui.View):
    def __init__(
        self,
        db_pool,
        guild_id,
        added_by,
        item_image_url,
        npc_image_url,
        item_msg_id,
        npc_msg_id,
        upload_channel_id,
        wiki_data=None
    ):
        super().__init__(timeout=900)

        self.db_pool = db_pool
        self.guild_id = guild_id
        self.added_by = added_by
        self.item_image_url = item_image_url
        self.npc_image_url = npc_image_url
        self.item_msg_id = item_msg_id
        self.npc_msg_id = npc_msg_id
        self.upload_channel_id = upload_channel_id

        self.wiki_data = wiki_data or {}

        self.slot = []
        self.skill_use = None
        self.usable_classes = []
        self.all_stats = []

        # ============================================================
        # PRE-POPULATE DROPDOWNS FROM WIKI DATA
        # ============================================================

        wiki_stats = self.wiki_data.get("item_stats", "") or ""

        if wiki_stats:
            for raw_line in wiki_stats.splitlines():

                line = raw_line.strip()

                if not line:
                    continue

                # ----------------------------------------------------
                # SLOT
                # ----------------------------------------------------

                if line.lower().startswith("slot:"):
                    raw_slots = line.split(":", 1)[1].strip()

                    for slot_name in re.split(r"[,/|]+", raw_slots):
                        slot_name = slot_name.strip()

                        for valid_slot in ITEM_SLOTS:
                            if slot_name.lower() == valid_slot.lower():
                                if valid_slot not in self.slot:
                                    self.slot.append(valid_slot)

                # ----------------------------------------------------
                # CLASSES
                # Supports:
                # Classes: ARC, FTR, WIZ
                # Class: ARC, FTR, WIZ
                # ----------------------------------------------------

                elif (
                    line.lower().startswith("classes:")
                    or line.lower().startswith("class:")
                ):
                    raw_classes = line.split(":", 1)[1].strip()

                    for class_name in re.split(r"[,/|]+", raw_classes):
                        class_name = class_name.strip()

                        for valid_class in CLASS_OPTIONS:
                            if class_name.lower() == valid_class.lower():
                                if valid_class not in self.usable_classes:
                                    self.usable_classes.append(valid_class)

                # ----------------------------------------------------
                # STATS
                # Supports:
                # Stats: STR, STA, HP
                # Stat: STR, STA, HP
                # ----------------------------------------------------

                elif (
                    line.lower().startswith("stats:")
                    or line.lower().startswith("stat:")
                ):
                    raw_stats = line.split(":", 1)[1].strip()

                    for stat_name in re.split(r"[,/|]+", raw_stats):
                        stat_name = stat_name.strip()

                        for valid_stat in ITEM_STATS:
                            if stat_name.lower() == valid_stat.lower():
                                if valid_stat not in self.all_stats:
                                    self.all_stats.append(valid_stat)

                # ----------------------------------------------------
                # SKILL USE
                # ----------------------------------------------------

                elif line.lower().startswith("skill use:"):
                    skill_value = line.split(":", 1)[1].strip()

                    valid_skill_uses = {
                        "1H Bludgeoning",
                        "2H Bludgeoning",
                        "1H Piercing",
                        "2H Piercing",
                        "1H Slashing",
                        "2H Slashing",
                        "Hand to Hand",
                        "Archery",
                        "Throwing"
                    }

                    for valid_skill in valid_skill_uses:
                        if skill_value.lower() == valid_skill.lower():
                            self.skill_use = valid_skill
                            break

        # ============================================================
        # CREATE DROPDOWNS
        # ============================================================

        self._finalized = False

        self.add_item(SlotSelect(self))

        self.skill_use_select = SkillUseSelect(self)

        # SkillUseSelect starts disabled, so populate it from
        # the Wiki-selected slot.
        self.skill_use_select.update_options()

        self.add_item(self.skill_use_select)

        self.add_item(ClassesSelect(self))
        self.add_item(StatSelect(self))

    async def _delete_uploads(self, interaction: discord.Interaction):
        """Best-effort delete of uploaded messages."""
        try:
            channel = interaction.client.get_channel(self.upload_channel_id) or await interaction.client.fetch_channel(self.upload_channel_id)
            if self.item_msg_id:
                try:
                    msg = await channel.fetch_message(self.item_msg_id)
                    await msg.delete()
                except Exception:
                    pass
            if self.npc_msg_id:
                try:
                    msg = await channel.fetch_message(self.npc_msg_id)
                    await msg.delete()
                except Exception:
                    pass
        except Exception:
            pass

    async def on_timeout(self):
        # If user never completed the flow, delete the uploads
        if not self._finalized:
            # We don't have an interaction here to reply, just best-effort delete
            try:
                # You can’t access an interaction here; fetch bot + channel by ID via bot object if you store it.
                # If you have `bot` global, you can use it here similarly to _delete_uploads.
                pass
            except Exception:
                pass

    @discord.ui.button(label="✅ Submit new item", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.slot:
            await interaction.response.send_message("❌ Please select at least one slot.", ephemeral=True)
            return

        item_slot = ", ".join(self.slot)
        
        item_stats = ""
        
        # Combine classes + stats
        if self.usable_classes:
            item_stats += f"Classes: {', '.join(self.usable_classes)}"
        
        if hasattr(self, "all_stats") and self.all_stats:
            if item_stats:
                item_stats += "\n"
        
            formatted_stats = []
        
            for stat in self.all_stats:
                if stat == "Instrument":
                    formatted_stats.append("Brass:")
                else:
                    formatted_stats.append(stat)
        
            item_stats += f"Stats: {', '.join(formatted_stats)}"
        
        # Add Skill Use
        if getattr(self, "skill_use", None):
            if item_stats:
                item_stats += "\n"
            item_stats += f"Skill: {self.skill_use}"
          
        
        await interaction.response.send_modal(
            ItemDatabaseModal(
                db_pool=self.db_pool,
                guild_id=self.guild_id,
                added_by=self.added_by,
                item_image_url=self.item_image_url,
                npc_image_url=self.npc_image_url,
                item_slot=item_slot,
                item_msg_id=self.item_msg_id,
                npc_msg_id=self.npc_msg_id,
                item_stats=item_stats,
                upload_channel_id=self.upload_channel_id,
                origin_message=self.origin_message,
                wiki_data=getattr(self, "wiki_data", None),
                item_name_default=getattr(self, "item_name_from_check", "")
               
            )
        )
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._delete_uploads(interaction)
        # Disable components to prevent further interaction
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❌ Upload cancelled and images deleted.", view=None)
        self.stop()


class ItemDatabaseModal(discord.ui.Modal, title="Add Item to Database"):
    def __init__(
        self,
        db_pool,
        guild_id,
        added_by,
        item_image_url=None,
        npc_image_url=None,
        item_msg_id=None,
        npc_msg_id=None,
        item_stats=None,
        item_slot=None,
        upload_channel_id=None,
        origin_message=None,
        wiki_data=None,
        item_name_default=None
    ):
          
      
        super().__init__(timeout=None)
        self.db_pool = db_pool
        self.guild_id = guild_id
        self.added_by = added_by
        self.item_image_url = item_image_url
        self.npc_image_url = npc_image_url
        self.item_msg_id = item_msg_id
        self.npc_msg_id = npc_msg_id
        self.item_stats = item_stats or ""
        self.item_slot = item_slot
        self.upload_channel_id = upload_channel_id
        self.origin_message = origin_message
        self.wiki_data = wiki_data or {}

        self.item_name_default = (
            item_name_default
            or self.wiki_data.get("item_name", "")
        )
        
        self.wiki_zone_name = self.wiki_data.get("zone_name", "")
        self.wiki_zone_area = self.wiki_data.get("zone_area", "")
        self.wiki_npc_name = self.wiki_data.get("npc_name", "")
        self.wiki_npc_level = self.wiki_data.get("npc_level", "")

        # Fields
        zone_default = self.wiki_zone_name

        if self.wiki_zone_area:
            zone_default = f"{zone_default} - {self.wiki_zone_area}"
        
        self.item_name = discord.ui.TextInput(
            label="Item Name",
            placeholder="Example: Flowing Black Silk Sash",
            default=self.item_name_default[:100],
            required=True
        )
        
        self.zone_field = discord.ui.TextInput(
            label="Zone Name - Zone Area (Optional)",
            placeholder="Examples: Shaded Dunes - Ashira Camp",
            default=zone_default[:4000],
            required=False,
        )
        
        self.npc_name = discord.ui.TextInput(
            label="NPC Name",
            placeholder="Example: Fippy Darkpaw",
            default=self.wiki_npc_name[:4000],
            required=False
        )
        
        self.npc_level = discord.ui.TextInput(
            label="NPC Level",
            placeholder="Example: 15-17 (Estimate/Optional)",
            default=self.wiki_npc_level[:4000],
            required=False
        )
        

        self.add_item(self.item_name)
        self.add_item(self.zone_field)
        self.add_item(self.npc_name)
        self.add_item(self.npc_level)
        


    
    async def on_submit(self, interaction: discord.Interaction):
        # 🧹 Clean and title-case all text inputs
        item_name = self.item_name.value.strip().title()
        raw_zone_value = self.zone_field.value.strip()
        npc_name = self.npc_name.value.strip().title()
        npc_level = self.npc_level.value.strip().title()
    
        # 🗺️ Split "Zone - Area"
        if "-" in raw_zone_value:
            zone_name, zone_area = map(str.strip, raw_zone_value.split("-", 1))
            zone_name = zone_name.title()
            zone_area = zone_area.title()
        else:
            zone_name = raw_zone_value.title()
            zone_area = None
    
        # ✅ Format item_name and zone_name but not npc_name
        item_name = format_item_name(item_name)
        zone_name = format_item_name(zone_name)
    
        try:
            async with self.db_pool.acquire() as conn:
    
                 # 🔍 Check for duplicates in this guild or global (fuzzy, case-insensitive)
                exists = await conn.fetchval("""
                    SELECT 1 FROM item_database
                    WHERE TRIM(LOWER(REPLACE(item_name, '-', ''))) = TRIM(LOWER(REPLACE($1, '-', '')))
                      AND TRIM(LOWER(REPLACE(npc_name, '-', ''))) = TRIM(LOWER(REPLACE($2, '-', '')))
                      AND (guild_id = $3 OR guild_id IS NULL)
                    LIMIT 1
                """, item_name, npc_name, self.guild_id)
    
    
               
             
                if exists:
                # 🧹 Clean up uploaded images if duplicate is found
                    try:
                        upload_channel = interaction.client.get_channel(self.upload_channel_id)
                        if upload_channel:
                            for msg_id in (self.item_msg_id, self.npc_msg_id):
                                if msg_id:
                                    try:
                                        msg = await upload_channel.fetch_message(msg_id)
                                        await msg.delete()
                                        print(f"✅ Deleted uploaded message {msg_id}")
                                    except discord.NotFound:
                                        print(f"⚠️ Message {msg_id} already deleted.")
                                    except discord.Forbidden:
                                        print(f"❌ Missing permissions to delete in {upload_channel.name}")
                                    except Exception as e:
                                        print(f"⚠️ Error deleting message {msg_id}: {e}")
                        else:
                            print("⚠️ Upload channel not found for cleanup.")
                    except Exception as e:
                        print(f"⚠️ Error cleaning up uploaded images: {e}")
               

    
                    # ✅ Acknowledge modal silently (no popup)
                    if not interaction.response.is_done():
                        await interaction.response.defer(ephemeral=True)
                
                    # ✅ Replace dropdown UI with duplicate error
                    try:
                        await self.origin_message.edit(
                            content=f"❌ `{item_name}` from `{npc_name}` already exists.\n🗑️ Uploaded images deleted.",
                            view=None
                        )
                    except Exception as e:
                        print(f"⚠️ Could not edit original ephemeral message: {e}")
                
                    return
    
    
                # ✅ Insert new record
                await conn.execute("""
                    INSERT INTO item_database (
                        guild_id, item_name, zone_name, zone_area,
                        npc_name, npc_level, item_image, npc_image,
                        item_msg_id, npc_msg_id, item_stats, item_slot, added_by, created_at
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                """,
                self.guild_id,
                item_name,
                zone_name,
                zone_area,
                npc_name,
                npc_level,
                self.item_image_url,
                self.npc_image_url,
                self.item_msg_id,
                self.npc_msg_id,
                self.item_stats,
                self.item_slot,
                self.added_by)
    
            
            
            
            # ✅ DO NOT send a new ephemeral popup here
            # await interaction.response.send_message(...)
            
            # ✅ Just acknowledge the modal silently
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            
            # ✅ now edit the original ephemeral dropdown message
            try:
                await self.origin_message.edit(
                    content=f"✅ `{item_name}` added successfully!",
                    view=None  # remove dropdowns
                )
            except Exception as e:
                print(f"⚠️ Could not edit original ephemeral message: {e}")


     
       
   
        except Exception as e:
            print(f"❌ Database error: {e}")  # log only
    
            # ✅ Safe failure response logic
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⚠️ Something went wrong while saving this item.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "⚠️ Something went wrong while saving this item.",
                        ephemeral=True
                    )
            except Exception as err:
                print(f"⚠️ Secondary DB error handler failed: {err}")



@bot.tree.command(name="clear_wiki_cache", description="Clear cached wiki results (forces fresh scraping)")
@app_commands.checks.has_permissions(administrator=True)
async def clear_wiki_cache(interaction: discord.Interaction):
    global wiki_cache
    count = len(wiki_cache)
    wiki_cache.clear()
    await interaction.response.send_message(
        f"🧹 Cache cleared! ({count} cached slot pages flushed)\nNext wiki pull will be fresh.",
        ephemeral=True
    )


             
        

# ---------------- Slash Command ----------------

@bot.tree.command(name="add_item_db", description="Add a new item to the database.")
@app_commands.describe(
    item_image="Upload item image",
    npc_image="Upload NPC image (optional)"
)
async def add_item_db(
    interaction: discord.Interaction,
    item_image: discord.Attachment,
    npc_image: Optional[discord.Attachment] = None
):
    """Start the new item workflow by immediately asking for the item name."""

    if not item_image:
        await interaction.response.send_message(
            "❌ Item image is required.",
            ephemeral=True
        )
        return

    added_by = str(interaction.user)
    guild = interaction.guild

    # We don't defer here because the next response must be the modal.
    # The images are passed into the modal and uploaded after the
    # item-name/database/wiki checks.
    try:

        upload_channel = await ensure_upload_channel1(guild)

        await interaction.response.send_modal(
            ItemNameCheckModal(
                db_pool=db_pool,
                guild_id=guild.id,
                added_by=added_by,
                item_image=item_image,
                npc_image=npc_image,
                upload_channel_id=upload_channel.id
            )
        )

    except Exception as e:
        print(f"❌ Could not open Item Name modal: {e}")

        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"❌ Could not start the item entry: {e}",
                ephemeral=True
            )



class EditItemModal(discord.ui.Modal, title="Edit Item"):
    def __init__(self, item_row, db_pool, origin_interaction):
        super().__init__(timeout=None)
        self.item_row = item_row
        self.db_pool = db_pool
        self.origin_interaction = origin_interaction

        # ✅ Item name REQUIRED
        self.item_name = discord.ui.TextInput(
            label="Item Name",
            default=item_row['item_name'],
            required=True
        )

        # ✅ All other fields optional now
        zone_default = (
            f"{item_row['zone_name']} - {item_row['zone_area']}"
            if item_row['zone_area'] else item_row['zone_name']
        )

        self.zone_field = discord.ui.TextInput(
            label="Zone - Area",
            default=zone_default,
            required=False
        )

        self.npc_name = discord.ui.TextInput(
            label="NPC Name",
            default=item_row['npc_name'],
            required=False
        )

        self.npc_level = discord.ui.TextInput(
            label="NPC Level",
            default=str(item_row['npc_level'] or ""),
            required=False
        )

        self.item_slot = discord.ui.TextInput(
            label="Item Slot",
            default=item_row['item_slot'] or "",
            required=False
        )

        self.add_item(self.item_name)
        self.add_item(self.zone_field)
        self.add_item(self.npc_name)
        self.add_item(self.npc_level)
        self.add_item(self.item_slot)

    async def on_submit(self, interaction: discord.Interaction):
        # 🧹 Normalize
        new_name = format_item_name(self.item_name.value.strip().title())
        old_name = self.item_row['item_name']

        raw_zone = self.zone_field.value.strip() if self.zone_field.value else ""

        if "-" in raw_zone:
            zone_name, zone_area = map(str.strip, raw_zone.split("-", 1))
            zone_name = format_item_name(zone_name.title())
            zone_area = zone_area.title()
        else:
            zone_name = format_item_name(raw_zone.title()) if raw_zone else None
            zone_area = None

        npc_name = self.npc_name.value.strip().title() if self.npc_name.value else None
        npc_level_val = self.npc_level.value.strip() or None
        item_slot = self.item_slot.value.strip() or None

        try:
            async with self.db_pool.acquire() as conn:

                # Only check duplicates if the name CHANGED
                if new_name != old_name:
                    exists = await conn.fetchval("""
                        SELECT 1 FROM item_database
                        WHERE TRIM(LOWER(item_name)) = TRIM(LOWER($1))
                          AND (guild_id = $2 OR guild_id IS NULL)
                        LIMIT 1
                    """, new_name, interaction.guild.id)

                    if exists:
                        if not interaction.response.is_done():
                            await interaction.response.defer(ephemeral=True)

                        await self.origin_interaction.edit_original_response(
                            content=f"❌ `{new_name}` already exists. Item name cannot be changed to a duplicate.",
                            view=None
                        )
                        return

                # ✅ Update DB
                await conn.execute("""
                    UPDATE item_database
                    SET item_name=$1,
                        zone_name=$2,
                        zone_area=$3,
                        npc_name=$4,
                        npc_level=$5,
                        item_slot=$6,
                        updated_at=NOW()
                    WHERE id=$7
                """,
                new_name, zone_name, zone_area,
                npc_name, npc_level_val, item_slot,
                self.item_row['id'])

           
            # ✅ Toast success
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"✅ `{new_name}` successfully updated!", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"✅ `{new_name}` successfully updated!", ephemeral=True
                )

            # ✅ Replace original ephemeral dropdown, but ignore if expired
            try:
                await self.origin_interaction.edit_original_response(
                    content=f"✅ `{new_name}` updated successfully!",
                    view=None
                )
            except discord.NotFound:
                pass  # ephemeral expired, ignore
            except Exception as e:
                print(f"UI update warning (non-fatal): {e}")

        except Exception as e:
            print(f"❌ DB Update Error: {e}")

            # ✅ Only notify user for DB failures
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ Database update failed. Try again.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ Database update failed. Try again.",
                    ephemeral=True
                )





@bot.tree.command(name="edit_item_db", description="Edit an existing item in the database by item name.")
@app_commands.describe(item_name="The name of the item to edit.")
async def edit_database_item(interaction: discord.Interaction, item_name: str):

    # fetch item (guild only — global items edited by guild only if copied)
    async with db_pool.acquire() as conn:
        item_row = await conn.fetchrow("""
            SELECT *
            FROM item_database
            WHERE (guild_id = $1 OR guild_id IS NULL)
              AND TRIM(LOWER(item_name)) = TRIM(LOWER($2))
            LIMIT 1
        """, interaction.guild.id, item_name)

    if not item_row:
        await interaction.response.send_message("❌ Item not found.", ephemeral=True)
        return

    # Store original interaction reference for replacing dropdown later
    modal = EditItemModal(item_row=item_row, db_pool=db_pool, origin_interaction=interaction)
    await interaction.response.send_modal(modal)





class ConfirmRemoveItemView(View):
    def __init__(self, item_name, npc_name, db_pool):
        super().__init__(timeout=60)
        self.item_name = item_name
        self.npc_name = npc_name
        self.db_pool = db_pool

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        try:
            async with self.db_pool.acquire() as conn:
                # Fetch message IDs to delete the images
                row = await conn.fetchrow("""
                    SELECT item_msg_id, npc_msg_id 
                    FROM item_database 
                    WHERE item_name=$1 AND npc_name=$2 AND guild_id=$3
                """, self.item_name, self.npc_name, interaction.guild_id)

                if not row:
                    await interaction.response.edit_message(
                        content=f"❌ Item **{self.item_name} from {self.npc_name}** not found in the database.",
                        view=None
                    )
                    return

                # Delete the uploaded messages
                upload_channel = await ensure_upload_channel1(interaction.guild)
                if upload_channel:
                    for msg_id in [row["item_msg_id"], row["npc_msg_id"]]:
                        if msg_id:
                            try:
                                msg = await upload_channel.fetch_message(msg_id)
                                await msg.delete()
                            except discord.NotFound:
                                pass
                            except Exception as e:
                                print(f"⚠️ Failed to delete message {msg_id}: {e}")

                # Remove entry from database
                await conn.execute("""
                    DELETE FROM item_database 
                    WHERE item_name=$1 AND npc_name=$2 AND guild_id=$3
                """, self.item_name, self.npc_name, interaction.guild_id)

            await interaction.response.edit_message(
                content=f"🗑️ **{self.item_name}** was successfully removed from the database.",
                view=None
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.response.edit_message(
                content=f"❌ Error while removing **{self.item_name}**: {e}",
                view=None
            )

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content=f"❎ Removal of **{self.item_name}** canceled.",
            view=None
        )





@bot.tree.command(name="remove_item_db", description="Remove an item from the item database by name.")
@app_commands.describe(item_name="Name of the item to remove.")
@app_commands.describe(npc_name="Name of the NPC to remove.")
async def remove_itemdb(interaction: discord.Interaction, item_name: str, npc_name: str, ):
    # Ask for confirmation first
    view = ConfirmRemoveItemView(item_name=item_name, npc_name=npc_name, db_pool=db_pool)
    await interaction.response.send_message(
        f"⚠️ Are you sure you want to remove **{item_name}** from the item database?",
        view=view,
        ephemeral=True
    )







#------------VIEW------------

@bot.tree.command(name="view_item_dbp", description="Privately view items stored in the database with optional filters.")
async def view_item_db(interaction: discord.Interaction):
    # Show filters and return; the runner will take over on ✅
    view = WikiSelectView(source_command="dbp", on_submit=run_item_db, optional_slot=True, show_search=True)
    await interaction.response.send_message(
        "Search the **Database** (Private) using the filters below:",
        view=view,  ephemeral=True
    )




@bot.tree.command(name="view_item_db", description="View items stored in the database with optional filters.")
async def view_item_db(interaction: discord.Interaction):
    # Show filters and return; the runner will take over on ✅
    view = WikiSelectView(source_command="db", on_submit=run_item_db, optional_slot=True, show_search=True)
    await interaction.response.send_message(
        "Search the **Database** using the filters below:",
        view=view
    )


async def run_item_db(
    interaction: discord.Interaction,
    slot: Optional[str],
    stat: Optional[str],
    classes: Optional[str],
    type_filter:Optional[str] = "with_stats",
    search_query = None,
    source_command="db",
    show_search = True,
    skill_use: Optional[str] = None
):
    try:
        await interaction.response.defer(thinking=True)
    except discord.InteractionResponded:
        pass

    # Replace the filter UI
    await interaction.edit_original_response(
        content=f"⏳ Searching the database{f' for `{slot}`' if slot else ''}"
                f"{f' with {stat}' if stat else ''}{f' for {classes}' if classes else ''}"
                f"{f' matching `{search_query}`' if search_query else ''}...",
        view=None,
        embeds=[]
    )

    # Build WHERE based on optional search + slot
    where_clauses = []
    params = []

    # Search across item_name, npc_name, zone_name with ILIKE
    if search_query:
        where_clauses.append("(item_name ILIKE $%d OR npc_name ILIKE $%d OR zone_name ILIKE $%d)" % (len(params)+1, len(params)+2, len(params)+3))
        params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

  
    if slot:
        # Primary / Secondary / Range are identified in item_stats.
        slot_lower = slot.lower()

        if slot_lower in ("primary", "secondary", "range"):
            where_clauses.append(
                "(item_stats ILIKE $%d OR item_slot ILIKE $%d)"
                % (len(params) + 1, len(params) + 2)
            )
            params.append(f"%{slot}%")
            params.append(f"%{slot}%")

        else:
            where_clauses.append(
                "LOWER(item_slot) = LOWER($%d)"
                % (len(params) + 1)
            )
            params.append(slot)
    
    # Search across item_name, npc_name, zone_name with ILIKE
    if search_query:
        where_clauses.append(
            "(item_name ILIKE $%d OR npc_name ILIKE $%d OR zone_name ILIKE $%d)"
            % (len(params) + 1, len(params) + 2, len(params) + 3)
        )
        params.extend([
            f"%{search_query}%",
            f"%{search_query}%",
            f"%{search_query}%"
        ])

    # --------------------------------------------------------
    # Slot filtering
    # --------------------------------------------------------

    if slot:
        slot_lower = slot.lower()

        if slot_lower in ("primary", "secondary", "range"):
            where_clauses.append(
                "(item_stats ILIKE $%d OR item_slot ILIKE $%d)"
                % (len(params) + 1, len(params) + 2)
            )
            params.append(f"%{slot}%")
            params.append(f"%{slot}%")

        else:
            where_clauses.append(
                "LOWER(item_slot) = LOWER($%d)"
                % (len(params) + 1)
            )
            params.append(slot)


    # --------------------------------------------------------
    # Skill Use filtering
    # --------------------------------------------------------

    if skill_use and slot:

        slot_lower = str(slot).strip().lower()
        skill_lower = str(skill_use).strip().lower()

        # Skill Use dropdown stores abbreviated values.
        # Convert them back to the existing search names.
        skill_use_map = {
            "blg": "1h bludgeoning",
            "blg two handed": "2h bludgeoning",
            "sta": "1h piercing",
            "sta two handed": "2h piercing",
            "sla": "1h slashing",
            "sla two handed": "2h slashing",
            "h2h": "hand to hand",
            "arc": "archery",
            "thr": "throwing"
        }
        
        skill_lower = skill_use_map.get(skill_lower, skill_lower)

        # --------------------------------------------------------
        # Primary
        # --------------------------------------------------------
        if slot_lower == "primary":

            # 1H Bludgeoning
            if skill_lower == "1h bludgeoning":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND item_stats ILIKE $%d
                    AND item_stats NOT ILIKE $%d
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Primary%",
                    "%Skill: BLG%",
                    "%Two Handed%"
                ])

            
            
            # 2H Bludgeoning
            elif skill_lower == "2h bludgeoning":
            
                where_clauses.append(
                    """
                    (
                        LOWER(item_slot) = 'primary'
                        OR item_stats ILIKE $%d
                    )
                    AND
                    (
                        (
                            item_stats ILIKE $%d
                            AND item_stats ILIKE $%d
                        )
                        OR item_stats ILIKE $%d
                    )
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3,
                        len(params) + 4
                    )
                )
            
                params.extend([
                    "%Primary%",
                    "%Skill: BLG%",
                    "%Two Handed%",
                    "%Skill: BLG Two Handed%"
                ])

            # 1H Piercing
            elif skill_lower == "1h piercing":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND item_stats ILIKE $%d
                    AND item_stats NOT ILIKE $%d
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Primary%",
                    "%Skill: STA%",
                    "%Two Handed%"
                ])

            
            # 2H Piercing
            elif skill_lower == "2h piercing":
            
            
                where_clauses.append(
                    """
                    (
                        LOWER(item_slot) = 'primary'
                        OR item_stats ILIKE $%d
                    )
                    AND
                    (
                        (
                            item_stats ILIKE $%d
                            AND item_stats ILIKE $%d
                        )
                        OR item_stats ILIKE $%d
                    )
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3,
                        len(params) + 4
                    )
                )
            
                params.extend([
                    "%Primary%",
                    "%Skill: STA%",
                    "%Two Handed%",
                    "%Skill: STA Two Handed%"
                ])

            # 1H Slashing
            elif skill_lower == "1h slashing":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND item_stats ILIKE $%d
                    AND item_stats NOT ILIKE $%d
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Primary%",
                    "%Skill: SLA%",
                    "%Two Handed%"
                ])

        
            # 2H Slashing
            elif skill_lower == "2h slashing":
            
                
                where_clauses.append(
                    """
                    (
                        LOWER(item_slot) = 'primary'
                        OR item_stats ILIKE $%d
                    )
                    AND
                    (
                        (
                            item_stats ILIKE $%d
                            AND item_stats ILIKE $%d
                        )
                        OR item_stats ILIKE $%d
                    )
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3,
                        len(params) + 4
                    )
                )
            
                params.extend([
                    "%Primary%",
                    "%Skill: SLA%",
                    "%Two Handed%",
                    "%Skill: SLA Two Handed%"
                ])

            # Hand to Hand
            elif skill_lower == "hand to hand":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND (
                        item_stats ILIKE $%d
                        OR item_stats ILIKE $%d
                    )
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Primary%",
                    "%Hand to Hand%",
                    "%H2H%"
                ])

        # --------------------------------------------------------
        # Secondary
        # --------------------------------------------------------
        elif slot_lower == "secondary":

            # 1H Bludgeoning
            if skill_lower == "1h bludgeoning":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND item_stats ILIKE $%d
                    AND item_stats NOT ILIKE $%d
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Secondary%",
                    "%Skill: BLG%",
                    "%Two Handed%"
                ])

            # 1H Piercing
            elif skill_lower == "1h piercing":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND item_stats ILIKE $%d
                    AND item_stats NOT ILIKE $%d
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Secondary%",
                    "%Skill: STA%",
                    "%Two Handed%"
                ])

            # 1H Slashing
            elif skill_lower == "1h slashing":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND item_stats ILIKE $%d
                    AND item_stats NOT ILIKE $%d
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Secondary%",
                    "%Skill: SLA%",
                    "%Two Handed%"
                ])

            # Hand to Hand
            elif skill_lower == "hand to hand":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND (
                        item_stats ILIKE $%d
                        OR item_stats ILIKE $%d
                    )
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Secondary%",
                    "%Hand to Hand%",
                    "%H2H%"
                ])

        # --------------------------------------------------------
        # Range
        # --------------------------------------------------------
        elif slot_lower == "range":

            # Archery
            if skill_lower == "archery":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND (
                        item_stats ILIKE $%d
                        OR item_stats ILIKE $%d
                    )
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Range%",
                    "%Archery%",
                    "%Skill: ARC%"
                ])

            # Throwing
            elif skill_lower == "throwing":

                where_clauses.append(
                    """
                    item_stats ILIKE $%d
                    AND (
                        item_stats ILIKE $%d
                        OR item_stats ILIKE $%d
                    )
                    """
                    % (
                        len(params) + 1,
                        len(params) + 2,
                        len(params) + 3
                    )
                )

                params.extend([
                    "%Range%",
                    "%Throwing%",
                    "%Skill: THR%"
                ])
              

    # Only this guild and global entries
    where_clauses.append("(guild_id = $%d OR guild_id IS NULL)" % (len(params)+1))
    params.append(interaction.guild.id)

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    query = f"""
        SELECT item_name, item_image, npc_image, npc_name, zone_name, zone_area,
               item_slot, item_stats, description, quest_name, npc_level, source
        FROM item_database
        {where_sql}
        ORDER BY item_name ASC;
    """

    async with db_pool.acquire() as conn:
        db_rows = await conn.fetch(query, *params)
        
        # --- Step 5: Apply stat and class filters (regex-based) ---
        def text_cleanup(text: str) -> str:
            return (text or "").replace("\n", " ").replace("\r", " ")
        
        def has_value(val):
            return val is not None and str(val).strip().lower() not in ("", "none", "null")
        

        # ✅ Apply item type filter FIRST
        # "all" = keep everything
        # "with_stats" = item must contain one of the allowed stats
        
        tf = (type_filter or "with_stats").lower()
        
        if tf == "with_stats" and not search_query:
        
            # These are the ONLY stats that qualify an item for "With Stats"
            allowed_stats = [
                "AGI",
                "CHA",
                "DEX",
                "INT",
                "STA",
                "STR",
                "WIS",
                "HP",
                "Mana",
                "Haste",
                "SV",
            ]
        
            def has_allowed_stat(item_stats):
                if not item_stats:
                    return False
        
                stats_text = str(item_stats).strip()
        
                if not stats_text:
                    return False
        
                if stats_text.lower() in ("none", "none listed", "null"):
                    return False
        
                # Normalize the text so different spacing/newline formats
                # do not affect the search.
                stats_text = re.sub(r"\s+", " ", stats_text)
        
                # ---------------------------------------------------------
                # Look specifically for actual stat names.
                #
                # We require the stat name to be followed by a colon,
                # whitespace, or the end of the string.
                #
                # This prevents things such as:
                #   BACKAC
                #   Class
                #   Race
                #   Weight
                #   Size
                # from being treated as stats.
                # ---------------------------------------------------------
        
                for stat in allowed_stats:
        
                    if stat == "SV":
                        # Match things such as:
                        # SV Fire:
                        # SV Cold:
                        # SV Holy:
                        # SV Poison:
                        # SV Disease:
                        # SV Electricity:
                        # etc.
                        if re.search(
                            r"\bSV(?:\s+[A-Za-z]+)?\s*:",
                            stats_text,
                            re.IGNORECASE
                        ):
                            return True
        
                    else:
                        # Match the exact stat name followed by a colon.
                        #
                        # Examples:
                        # STR: 5      -> TRUE
                        # HP: 100     -> TRUE
                        # Mana: 50    -> TRUE
                        # Haste: 10   -> TRUE
                        #
                        # But:
                        # Classes:    -> FALSE
                        # Weight:     -> FALSE
                        # Race:       -> FALSE
                        # BACKAC:     -> FALSE
                        # AC:         -> FALSE
                        if re.search(
                            rf"(?<![A-Za-z]){re.escape(stat)}\s*:",
                            stats_text,
                            re.IGNORECASE
                        ):
                            return True
        
                return False
        
            db_rows = [
                r for r in db_rows
                if has_allowed_stat(r["item_stats"])
            ]


      
                # --- Stat filtering (with special handling for Haste / Spell Haste) ---

        stat_patterns = []
        if stat:
            stat_filter = str(stat).strip().lower()

            if stat_filter == "haste":
                # Match Haste but NOT Spell Haste or Skill: Haste
                stat_patterns = [
                    re.compile(r"(?<!Spell\s)Haste(?!\s*\w)", re.IGNORECASE)
                ]

            elif stat_filter == "spell haste":
                # Match only Spell Haste
                stat_patterns = [
                    re.compile(r"\bSpell\s+Haste\b", re.IGNORECASE)
                ]
     
            elif stat_filter == "ranged haste":
                # Match only Ranged Haste
                stat_patterns = [
                    re.compile(r"\bRanged\s+Haste\b", re.IGNORECASE)
                ]

            
            elif stat_filter == "instrument":
                # Instrument items can be any of these instrument types.
                # Search item_stats for the instrument type followed by a colon.
                stat_patterns = [
                    re.compile(r"Brass\s*:", re.IGNORECASE),
                    re.compile(r"Percussion\s*:", re.IGNORECASE),
                    re.compile(r"Stringed\s*:", re.IGNORECASE),
                    re.compile(r"Wind\s*:", re.IGNORECASE)
                ]

            else:
                # Generic fallback patterns for other stats
                stat_keywords = {
                    "str": [r"\bstr\b", r"\bstrength\b"],
                    "agi": [r"\bagi\b", r"\bagility\b"],
                    "dex": [r"\bdex\b", r"\bdexterity\b"],
                    "int": [r"\bint\b", r"\bintelligence\b"],
                    "sta": [r"\bsta\b", r"\bstamina\b"],
                    "wis": [r"\bwis\b", r"\bwisdom\b"],
                }
                stat_patterns = [
                    re.compile(pat, re.IGNORECASE)
                    for pat in stat_keywords.get(stat_filter, [rf"{re.escape(stat_filter)}"])
                ]


        class_patterns = []
        if classes:
            classes_filter = str(classes).strip().lower()
            class_keywords = {
                "arc": [r"\barc\b"], "brd": [r"\bbrd\b"], "bst": [r"\bbst\b"],
                "clr": [r"\bclr\b"], "dru": [r"\bdru\b"], "ele": [r"\bele\b"],
                "enc": [r"\benc\b"], "ftr": [r"\bftr\b"], "inq": [r"\binq\b"],
                "mnk": [r"\bmnk\b"], "nec": [r"\bnec\b"], "pal": [r"\bpal\b"],
                "rng": [r"\brng\b"], "rog": [r"\brog\b"], "shd": [r"\bshd\b"],
                "shm": [r"\bshm\b"], "spd": [r"\bspd\b"], "wiz": [r"\bwiz\b"],
            }
            class_patterns = [re.compile(pat, re.IGNORECASE)
                              for pat in (class_keywords.get(classes_filter, [rf"\b{classes_filter}\b"]) + [r"\bclass: all\b"])]
   # ----- TYPE FILTER -----

          
        def matches_filters(text: str) -> bool:
          text = text_cleanup(text)
      
          stat_match = True
          if stat_patterns:
            stat_match = any(p.search(text) for p in stat_patterns)
        
            # ❌ Exclude weapon Skill: entries from normal stat searches.
            # Instrument is different because Brass:, Percussion:, Stringed:
            # and Wind: are actual instrument types, not weapon skills.
            if stat_filter != "instrument":
                for p in stat_patterns:
                    # Safely build a simplified pattern string without word boundaries
                    simple_pat = p.pattern.replace(r"\b", "")
                    if re.search(f"Skill:\\s*{simple_pat}", text, re.IGNORECASE):
                        stat_match = False
                        break
      
          class_match = any(p.search(text) for p in class_patterns) if class_patterns else True
          return stat_match and class_match



        db_rows = [r for r in db_rows if matches_filters(r.get("item_stats") or "")]

       

       
        if not db_rows:
            try:
                # 👇 Recreate the filter view with the same source settings
                if source_command == "wiki":
                    prompt = "Please select the **Slot**, and (optionally) **Stat** and/or **Class**, then press ✅ **Search**:"
                    ephemeral = False
                    optional_slot = False
                    show_search = False
                elif source_command == "db":
                    prompt = "Search the **Database** using filters below:"
                    ephemeral = False
                    optional_slot = True
                    show_search = True
                elif source_command == "dbp":
                    prompt = "Search the **Database (Private)** using filters below:"
                    ephemeral = True
                    optional_slot = True
                    show_search = True
                else:
                    prompt = "Please select your filters again:"
                    ephemeral = False
                    optional_slot = True
                    show_search = True
        
                # Recreate the filter UI view
                new_filter_view = WikiSelectView(
                    source_command=source_command,
                    optional_slot=optional_slot,
                    show_search=show_search
                )
        
                # Inform user with popup + refresh the view
                await interaction.followup.send("❌ No items found matching your search and filters. Try adjusting your filters:", ephemeral=True)
                await interaction.edit_original_response(content=prompt, embeds=[], view=new_filter_view)
            except discord.errors.InteractionResponded:
                await interaction.followup.send("❌ No items found. Relaunching filters...", ephemeral=True)
            return



        # --- Step 6: Format and display results ---
        results = [
            {
                "item_name": row["item_name"],
                "item_image": row["item_image"] or "",
                "npc_image": row["npc_image"] or "",
                "npc_name": row["npc_name"] or "",
                "zone_name": row["zone_name"] or "",
                "zone_area": row["zone_area"] or "",
                "item_stats": row["item_stats"] or "",
                "description": row["description"] or "",
                "quest_name": row["quest_name"] or "",
                "npc_level": row["npc_level"] or "",
                "source": "Database",
            }
            for row in db_rows
        ]

        results_view = WikiView(results, source_command=source_command)
        await interaction.edit_original_response(
            content=None,
            embeds=results_view.build_embeds(0),
            view=results_view,
            
        )




# --- Search button that opens a modal ---
class SearchButton(discord.ui.Button):
    def __init__(self, parent_view: "WikiSelectView"):
        super().__init__(
            label="🖋️ Enter Search Term",
            style=discord.ButtonStyle.primary,
            row=4
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SearchModal(self.parent_view))


# --- All Items button ---
class AllItemsButton(discord.ui.Button):
    def __init__(self, parent_view: "WikiSelectView"):
        super().__init__(
            label="🔍 All Items",
            style=discord.ButtonStyle.secondary,  # GREY
            row=4
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        # Set the filter
        self.parent_view.type_filter = "all"

        # All Items = GREY
        self.style = discord.ButtonStyle.secondary

        # Items With Stats = GREEN
        self.parent_view.items_with_stats_button.style = discord.ButtonStyle.success

        # Immediately run the search
        await self.parent_view.confirm_selection(interaction)


# --- Items With Stats button ---
class ItemsWithStatsButton(discord.ui.Button):
    def __init__(self, parent_view: "WikiSelectView"):
        super().__init__(
            label="🔍 Items With Stats",
            style=discord.ButtonStyle.success,  # GREEN
            row=4
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        # Set the filter
        self.parent_view.type_filter = "with_stats"

        # Items With Stats = GREEN
        self.style = discord.ButtonStyle.success

        # All Items = GREY
        self.parent_view.all_items_button.style = discord.ButtonStyle.secondary

        # Immediately run the search
        await self.parent_view.confirm_selection(interaction)


# --- Modal with a single text input (the "search bar") ---
class SearchModal(discord.ui.Modal, title="Search Database"):
    def __init__(self, parent_view: "WikiSelectView"):
        super().__init__(timeout=None)
        self.parent_view = parent_view

        self.query = discord.ui.TextInput(
            label="Search",
            placeholder="Enter partial item, NPC, or zone name",
            required=False,
            style=discord.TextStyle.short
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        # Store the search term
        self.parent_view.search_query = (self.query.value or "").strip()

        # Immediately run the search using all currently selected filters.
        # An empty search term is allowed and simply searches the dropdown filters.
        await self.parent_view.confirm_selection(interaction)






@bot.tree.command(
    name="edit_item_image",
    description="Upload a new item and/or NPC image for an existing database entry."
)
@app_commands.describe(
    item_name="The exact item name to update",
    new_item_image="Upload a new image for the item (optional)",
    new_npc_image="Upload a new image for the NPC (optional)",
)
async def edit_item_image(
    interaction: discord.Interaction,
    item_name: str,
    new_item_image: discord.Attachment = None,
    new_npc_image: discord.Attachment = None,
):
    guild = interaction.guild
    guild_id = guild.id
    updated_by = str(interaction.user)

    # Must upload at least one file
    if not new_item_image and not new_npc_image:
        await interaction.response.send_message(
            "⚠️ You must upload at least one new image.",
            ephemeral=True
        )
        return

    async with db_pool.acquire() as conn:
        # 🔍 Fetch matching item by name ONLY, guild OR global
        existing = await conn.fetchrow(
            """
            SELECT id, item_msg_id, npc_msg_id, item_image, npc_image
            FROM item_database
            WHERE TRIM(LOWER(item_name)) = TRIM(LOWER($1))
              AND (guild_id = $2 OR guild_id IS NULL)
            LIMIT 1
            """,
            item_name, guild_id
        )

        if not existing:
            await interaction.response.send_message(
                f"❌ No record found for `{item_name}`",
                ephemeral=True
            )
            return

        upload_channel = await ensure_upload_channel1(guild)

        # ✅ Delete old item image if new one provided
        if new_item_image and existing["item_msg_id"]:
            try:
                msg = await upload_channel.fetch_message(int(existing["item_msg_id"]))
                await msg.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"⚠️ Could not delete old item message: {e}")

        # ✅ Delete old NPC image if new one provided
        if new_npc_image and existing["npc_msg_id"]:
            try:
                msg = await upload_channel.fetch_message(int(existing["npc_msg_id"]))
                await msg.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"⚠️ Could not delete old NPC message: {e}")

        # Upload new images to channel
        new_item_image_url, new_npc_image_url = None, None
        new_item_msg_id, new_npc_msg_id = None, None

        try:
            if new_item_image:
                msg = await upload_channel.send(
                    file=await new_item_image.to_file(),
                    content=f"🧾 Updated item image for **{item_name}** by {interaction.user.mention}"
                )
                new_item_image_url = msg.attachments[0].url
                new_item_msg_id = msg.id

            if new_npc_image:
                msg = await upload_channel.send(
                    file=await new_npc_image.to_file(),
                    content=f"👹 Updated NPC image for item **{item_name}** by {interaction.user.mention}"
                )
                new_npc_image_url = msg.attachments[0].url
                new_npc_msg_id = msg.id

        except discord.Forbidden:
            await interaction.response.send_message("❌ I don’t have permission to upload images.", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"❌ Upload failed: {e}", ephemeral=True)
            return

        # ✅ Update DB
        await conn.execute(
            """
            UPDATE item_database
            SET
                item_image = COALESCE($1, item_image),
                npc_image = COALESCE($2, npc_image),
                item_msg_id = COALESCE($3, item_msg_id),
                npc_msg_id = COALESCE($4, npc_msg_id),
                updated_by = $5,
                updated_at = NOW()
            WHERE id = $6
            """,
            new_item_image_url,
            new_npc_image_url,
            new_item_msg_id,
            new_npc_msg_id,
            updated_by,
            existing["id"]
        )

    # ✅ Response embed
    embed = discord.Embed(
        title=f"🖼️ Updated Images for {item_name}",
        description=f"👤 Updated by: {interaction.user.mention}",
        color=discord.Color.green()
    )

    if new_item_image_url:
        embed.add_field(name="📦 Item Image", value=f"[View Updated Item]({new_item_image_url})", inline=False)
        embed.set_image(url=new_item_image_url)

    if new_npc_image_url:
        embed.add_field(name="👹 NPC Image", value=f"[View Updated NPC]({new_npc_image_url})", inline=False)
        if not new_item_image_url:  # only set as main image if item image wasn't updated
            embed.set_image(url=new_npc_image_url)

    await interaction.response.send_message(embed=embed, ephemeral=True)





# -------------------- WikiView Class --------------------

class WikiView(discord.ui.View):
    def __init__(self, items, source_command = "wiki",
                 on_submit: Optional[Callable[[discord.Interaction, str, Optional[str]], Awaitable[None]]] = None):
        super().__init__(timeout=None)
        self.items = items
        self.source_command = source_command
        self.on_submit = on_submit
        self.current_page = 0
        self.items_per_page = 5
 
        self.item_select_menu = ItemSelectMenu(self)
        self.add_item(self.item_select_menu)        
        

    def build_embeds(self, page_index: int):
        """Builds up to 5 embeds per page."""
        start = page_index * self.items_per_page
        end = start + self.items_per_page
        current_items = self.items[start:end]
        embeds = []
        linkback= "https://monstersandmemories.miraheze.org/wiki/"
  
        for i, item in enumerate(current_items, start=1):
            color = discord.Color.blurple()

            

 # --- 2️⃣ If zone_name contains a number, swap it into npc_name and clear zone_name
            if any(char.isdigit() for char in item["npc_name"]):
                npc_name=item["npc_name"]
    
            else:    
                npc_string= item["npc_name"]
                # Split by comma and strip spaces
                npc_name = [name.strip() for name in npc_string.split(",") if name.strip()]
                # Build full wiki links

                linked_npc = []
                for name in npc_name:
                
                    # Trash Mobs is not a wiki page, so leave it as plain text.
                    if name.strip().lower() == "trash mobs":
                        linked_npc.append(name)
                    else:
                        # Replace spaces with underscores for proper wiki URL formatting
                        npc_url = linkback + name.replace(" ", "_")
                        linked_npc.append(f"[{name}]({npc_url})")
                # Join with newlines for vertical display in embed
                npc_name = " \n ".join(linked_npc)


           
            zone_name= format_item_name(item["zone_name"])
            
            item_link =f"{linkback}{item['item_name'].replace(' ', '_')}"
            zone_link = f"{linkback}{zone_name.replace(' ', '_')}"
            
            quest_link = f"{linkback}{item['quest_name'].replace(' ', '_')}"
                    
            
            embed = discord.Embed(
                title=item["item_name"],
                color=color,
                url=f"{item_link}"
            )
            
    
            level = item["npc_level"]
            level_number = re.search(r'\d', level)
            if level_number:
                npc_level = f"Level: ~{level[level_number.start():]}"
            else:
                npc_level=""

            if item["zone_name"] != "":
                embed.add_field(name="🗺️ Zone ", value=f"[{zone_name}]({zone_link})" f"\n{item['zone_area']}", inline=True)
            if npc_name != "":
                embed.add_field(name="👹 Npc", value=f"{npc_name}" f"\n{npc_level}", inline=True)
            

            if item["item_image"] != "":
                embed.set_image(url=item["item_image"])
            if item["npc_image"] != "":
                embed.set_thumbnail(url=item["npc_image"])            
            if item["quest_name"] != "":
                embed.add_field(name="🧩 Related Quest", value=f"[{item['quest_name']}]({quest_link})", inline=False)
            embed.set_footer(
                text=f"Page {page_index + 1}/{self.total_pages()} - Total Results: {len(self.items)}"
            )
            embeds.append(embed)

        return embeds

    def total_pages(self):
        return (len(self.items) + self.items_per_page - 1) // self.items_per_page
    
    






    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = (self.current_page - 1) % self.total_pages()
        self.item_select_menu.options = self.item_select_menu._build_options()
        await interaction.response.edit_message(embeds=self.build_embeds(self.current_page), view=self)




    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = (self.current_page + 1) % self.total_pages()
        self.item_select_menu.options = self.item_select_menu._build_options()
        await interaction.response.edit_message(embeds=self.build_embeds(self.current_page), view=self)

    
    

 
   # 🔄 Back to Filters Button
    @discord.ui.button(label="🔄 Back to Filters", style=discord.ButtonStyle.danger)
    async def back_to_filters(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        # Recreate a new filter view
        

        # Detect which command was the source
        if self.source_command == "wiki":
            prompt = "Please select the **Slot**, and (optionally) **Stat** and/or **Class**, then press ✅ **Search**:"
            ephemeral = False
            optional_slot = False
            source_command = "wiki"
            show_search=False
            
            
        elif self.source_command == "db":
            prompt = "Search the **Database** using filters below:"
            ephemeral = False
            optional_slot=True
            source_command = "db"
            show_search=True
           
        
        elif self.source_command == "dbp":
            prompt = "Search the **Database (Private)** using filters below:"
            ephemeral = True
            optional_slot=True
            source_command = "dbp"
            show_search=True
            
           
        
        else:
            prompt = "Please select your filters again:"
            ephemeral = False

        new_filter_view = WikiSelectView(source_command=source_command, optional_slot=optional_slot, show_search=show_search)
        
        try:
            # Replace message with a new filter menu
            await interaction.edit_original_response(
                content=prompt,
                embeds=[],
                view=new_filter_view
            )
        except discord.errors.InteractionResponded:
            # Fallback in case original interaction expired
            await interaction.followup.send(
                content=prompt,
                view=new_filter_view,
                ephemeral=ephemeral
            )



# -------------------- Helper Function --------------------


wiki_cache = {}

async def fetch_wiki_items(slot_name: str):
    """Scrape the Monsters & Memories Wiki for a specific item slot.
       Uses aiohttp directly to avoid Playwright/Chromium dependency issues.
    """
    base_url = "https://monstersandmemories.miraheze.org"
    category_url = f"{base_url}/wiki/Category:{slot_name}"
    items = []

    # ✅ Cache check
    if slot_name in wiki_cache:
        print(f"📦 Using cached results for {slot_name}")
        return wiki_cache[slot_name]

    print(f"🌐 Fetching {category_url} ...")

    # =========================================================
    # AIOHTTP WIKI FETCH
    # Same HTTP method used by the working spell scraper
    # =========================================================

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,image/webp,"
            "*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": (
            "https://monstersandmemories.miraheze.org/"
        ),
    }

    timeout = aiohttp.ClientTimeout(
        total=60
    )

    # =========================================================
    # Fetch category page
    # =========================================================

    try:

        print(
            f"🌐 [ITEMS] Opening wiki category: "
            f"{category_url}"
        )

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout
        ) as session:

            async with session.get(
                category_url,
                allow_redirects=True,
                ssl=False
            ) as response:

                print(
                    f"🌐 [ITEMS] aiohttp HTTP status: "
                    f"{response.status}"
                )

                html = await response.text(
                    errors="ignore"
                )

                print(
                    f"🌐 [ITEMS] aiohttp HTML received: "
                    f"{len(html) if html else 0} bytes"
                )

                if response.status != 200:
                    print(
                        f"❌ Wiki category request failed "
                        f"with HTTP {response.status}"
                    )
                    return []

                if not html or len(html) < 1000:
                    print(
                        "❌ Wiki category returned insufficient HTML."
                    )
                    return []

            soup = BeautifulSoup(
                html,
                "html.parser"
            )

            # -----------------------------
            # 🔎 Parse item links
            # -----------------------------

            links = soup.select(
                "div.mw-category a"
            )

            print(
                f"🔎 Found {len(links)} item links "
                f"in Category:{slot_name}"
            )

            # =================================================
            # Fetch individual item pages
            # =================================================

            for link in links:

                href = link.get("href")

                if not href:
                    continue

                if href.startswith("/"):
                    item_url = f"{base_url}{href}"
                elif href.startswith("http"):
                    item_url = href
                else:
                    item_url = f"{base_url}/wiki/{href}"

                item_name = link.text.strip()

                try:

                    print(
                        f"📖 Fetching item: {item_name}"
                    )

                    async with session.get(
                        item_url,
                        allow_redirects=True,
                        ssl=False
                    ) as resp:

                        if resp.status != 200:
                            print(
                                f"⚠️ Failed to fetch item page "
                                f"({resp.status}): {item_url}"
                            )
                            continue

                        page_html = await resp.text(
                            errors="ignore"
                        )

                    if not page_html or len(page_html) < 500:
                        print(
                            f"⚠️ Item page returned insufficient HTML: "
                            f"{item_url}"
                        )
                        continue

                    s2 = BeautifulSoup(
                        page_html,
                        "html.parser"
                    )

                    # --- Item Name ---
                    title = s2.find(
                        "h1",
                        id="firstHeading"
                    )

                    # Preserve the existing item name behavior,
                    # but use the category link name as fallback.
                    item_name = (
                        title.text.strip()
                        if title
                        else item_name
                    )

                    # --- Image ---
                    image_url = None

                    img_tag = s2.select_one(
                        ".infobox img, "
                        ".pi-image img, "
                        ".mainPageInnerBox img"
                    )

                    if img_tag:

                        src = img_tag.get(
                            "src",
                            ""
                        )

                        image_url = (
                            f"https:{src}"
                            if src.startswith("//")
                            else src
                        )

                    # -------------------------------------------------
                    # Extract NPC and Zone
                    # -------------------------------------------------

                    npc_name = ""
                    zone_name = ""

                    drops_section = s2.find(
                        "h2",
                        id="Drops_From"
                    )

                    if drops_section:

                        # The next <p> tag should hold the zone name
                        zone_tag = drops_section.find_next("p")

                        if zone_tag:
                            zone_name = zone_tag.get_text(
                                strip=True
                            )

                        # Then look for <ul><li> list of NPCs
                        npc_list = drops_section.find_next("ul")

                        if npc_links:
                        
                            npc_names = [
                                a.get_text(strip=True)
                                for a in npc_links
                                if a.get_text(strip=True)
                            ]
                        
                            if len(npc_names) > 3:
                                npc_name = "Trash Mobs"
                            else:
                                npc_name = ", ".join(npc_names)
                            
                                # Fallback: plain text <li>
                                npc_items = [
                                    li.get_text(strip=True)
                                    for li in npc_list.find_all("li")
                                    if li.get_text(strip=True)
                                ]
                            
                                if len(npc_items) > 3:
                                    npc_name = "Trash Mobs"
                                else:
                                    npc_name = ", ".join(npc_items)


                    # -------------------------------------------------
                    # Extract Related Quest
                    # -------------------------------------------------
                    
                    quest_name = ""
                    
                    quest_section = s2.find(
                        "h2",
                        id="Related_quests"
                    )
                    
                    if quest_section:
                    
                        # The Wiki places the Related Quests content
                        # immediately after the heading's wrapper.
                        quest_heading_wrapper = quest_section.parent
                    
                        if quest_heading_wrapper:
                    
                            quest_list = quest_heading_wrapper.find_next_sibling()
                    
                            # IMPORTANT:
                            # Only accept a UL directly following the
                            # Related quests heading.
                            #
                            # This prevents the Player_crafted UL
                            # from being mistaken for a Related Quest.
                            if quest_list and quest_list.name == "ul":
                    
                                quest_links = quest_list.find_all(
                                    "a",
                                    href=True
                                )
                    
                                if quest_links:
                    
                                    quest_names = []
                    
                                    for link in quest_links:
                    
                                        name = link.get_text(
                                            " ",
                                            strip=True
                                        )
                    
                                        if name and name not in quest_names:
                                            quest_names.append(name)
                    
                                    quest_name = ", ".join(quest_names)
                    
                                else:
                    
                                    # Fallback for plain-text quest entries.
                                    quest_items = quest_list.find_all("li")
                    
                                    quest_names = []
                    
                                    for li in quest_items:
                    
                                        name = li.get_text(
                                            " ",
                                            strip=True
                                        )
                    
                                        if name and name not in quest_names:
                                            quest_names.append(name)
                    
                                    quest_name = ", ".join(quest_names)
                    
                    
                    # -------------------------------------------------
                    # If NPC and quest are identical, clear NPC
                    # -------------------------------------------------
                    
                    if (
                        quest_name
                        and npc_name
                        and npc_name.strip().lower()
                        == quest_name.strip().lower()
                    ):
                        npc_name = ""

                    # -------------------------------------------------
                    # Fetch NPC details
                    # -------------------------------------------------

                    npc_image = ""
                    npc_level = ""

                    if npc_name:

                        for npc in npc_name.split(","):

                            npc_clean = (
                                npc.strip()
                                .replace(" ", "_")
                            )

                            npc_url = (
                                "https://monstersandmemories.miraheze.org/wiki/"
                                f"{npc_clean}"
                            )

                            try:

                                async with session.get(
                                    npc_url,
                                    allow_redirects=True,
                                    ssl=False
                                ) as npc_resp:

                                    if npc_resp.status != 200:

                                        print(
                                            f"⚠️ Failed to fetch NPC page: "
                                            f"{npc_url}"
                                        )

                                        continue

                                    npc_html = await npc_resp.text(
                                        errors="ignore"
                                    )

                                npc_soup = BeautifulSoup(
                                    npc_html,
                                    "html.parser"
                                )

                                # --- NPC Image ---
                                file_span = npc_soup.select_one(
                                    'span[typeof="mw:File"] img'
                                )

                                if file_span:

                                    src = file_span.get(
                                        "src",
                                        ""
                                    )

                                    npc_image = (
                                        f"https:{src}"
                                        if src.startswith("//")
                                        else src
                                    )

                                # --- NPC Level ---
                                mob_stats_table = npc_soup.find(
                                    "table",
                                    class_="mobStatsBox"
                                )

                                if mob_stats_table:

                                    tds = mob_stats_table.find_all(
                                        "td"
                                    )

                                    if len(tds) >= 3:

                                        npc_level = (
                                            tds[2].get_text(
                                                strip=True
                                            )
                                        )

                                # Stop after first NPC
                                break

                            except Exception as npc_error:

                                print(
                                    f"⚠️ NPC fetch failed "
                                    f"for {npc_url}: {npc_error}"
                                )

                                continue

                    
                    # -------------------------------------------------
                    # Item Stats
                    # -------------------------------------------------

                    item_stats_div = s2.find(
                        "div",
                        class_="item-stats"
                    )

                    item_stats = "None listed"

                    if item_stats_div:

                        lines = [
                            line.strip()
                            for line in item_stats_div.stripped_strings
                        ]

                        item_stats = "\n".join(lines)

                    # -------------------------------------------------
                    # Description
                    # -------------------------------------------------

                    desc_tag = s2.select_one(
                        "div.mw-parser-output > p"
                    )

                    description = (
                        desc_tag.text.strip()
                        if desc_tag
                        else "No description available."
                    )

                    # -------------------------------------------------
                    # Add item
                    # -------------------------------------------------

                    items.append({
                        "item_name": format_item_name(
                            item_name
                        ),
                        "item_image": image_url,
                        "npc_name": npc_name,
                        "zone_name": zone_name,
                        "slot_name": slot_name,
                        "item_stats": item_stats,
                        "wiki_url": item_url,
                        "description": description,
                        "quest_name": quest_name,
                        "npc_level": npc_level,
                        "npc_image": npc_image,
                        "source": "Wiki"
                    })

                    print(
                        f"✅ Parsed item: {item_name}"
                    )

                    # ✅ polite delay
                    await asyncio.sleep(1.0)

                except Exception as e:

                    print(
                        f"⚠️ Failed to parse "
                        f"{item_url}: {e}"
                    )

                    continue

    except Exception as e:

        print(
            f"❌ Item wiki fetch failed: "
            f"{type(e).__name__}: {e}"
        )

        import traceback
        traceback.print_exc()

        return []

    wiki_cache[slot_name] = items

    print(
        f"✅ Finished Category:{slot_name} — "
        f"{len(items)} items parsed."
    )

    return items



class WikiSelectView(discord.ui.View):
    def __init__(
        self,
        source_command: str = "wiki",
        on_submit: Optional[Callable[[discord.Interaction, Optional[str], Optional[str], Optional[str]], Awaitable[None]]] = None,
        optional_slot: bool = False, ephemeral: bool = False, initial_results=None, show_search=False,
        
    ):
        super().__init__(timeout=None)
        self.source_command = source_command  # 'wiki' or 'db'
        self.on_submit = on_submit            # callback to run the search
        self.optional_slot = optional_slot
        self.search_query = None
        self.show_search = show_search
        self.slot: Optional[str] = None
        self.stat: Optional[str] = None
        self.classes: Optional[str] = None
        self.skill_use: Optional[str] = None
        self.ephermeral = ephemeral

        
        # Slot dropdown
        self.slot_select = discord.ui.Select(
            placeholder="🎒 Select item slot...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Ammo", value="Ammo"),
                discord.SelectOption(label="Back", value="Back"),
                discord.SelectOption(label="Bag", value="Bag"),
                discord.SelectOption(label="Chest", value="Chest"),
                discord.SelectOption(label="Ear", value="Ear"),
                discord.SelectOption(label="Face", value="Face"),
                discord.SelectOption(label="Feet", value="Feet"),
                discord.SelectOption(label="Finger", value="Finger"),
                discord.SelectOption(label="Hands", value="Hands"),
                discord.SelectOption(label="Head", value="Head"),
                discord.SelectOption(label="Legs", value="Legs"),
                discord.SelectOption(label="Neck", value="Neck"),
                discord.SelectOption(label="Primary", value="Primary"),
                discord.SelectOption(label="Range", value="Range"),
                discord.SelectOption(label="Secondary", value="Secondary"),
                discord.SelectOption(label="Shirt", value="Shirt"),
                discord.SelectOption(label="Shoulders", value="Shoulders"),
                discord.SelectOption(label="Waist", value="Waist"),
                discord.SelectOption(label="Wrist", value="Wrist"),

            ]
        )
        self.slot_select.callback = self.select_slot
        self.add_item(self.slot_select)

                # Skill Use dropdown
        self.skill_use_select = discord.ui.Select(
            placeholder="⚔️ Skill Use (select Primary, Secondary, or Range first)...",
            min_values=0,
            max_values=1,
            disabled=True,
            options=[
                discord.SelectOption(
                    label="Select a Slot first",
                    value="disabled"
                )
            ]
        )
        self.skill_use_select.callback = self.select_skill_use
        self.add_item(self.skill_use_select)

        # Stat dropdown
        self.stat_select = discord.ui.Select(
            placeholder="⚔️ Filter by stat (optional)...",
            min_values=0,
            max_values=1,
            options=[
                discord.SelectOption(label="AGI", value="AGI"),
                discord.SelectOption(label="CHA", value="CHA"),
                discord.SelectOption(label="DEX", value="DEX"),
                discord.SelectOption(label="INT", value="INT"),
                discord.SelectOption(label="STA", value="STA"),
                discord.SelectOption(label="STR", value="STR"),
                discord.SelectOption(label="WIS", value="WIS"),
                discord.SelectOption(label="HP", value="HP"),
                discord.SelectOption(label="Mana", value="Mana"),
                discord.SelectOption(label="HP Regen", value="HP Regeneration"),
                discord.SelectOption(label="Mana Regen", value="Mana Regeneration"),
                discord.SelectOption(label="Haste", value="Haste"),
                discord.SelectOption(label="Ranged Haste", value="Ranged Haste"),
                discord.SelectOption(label="Spell Haste", value="Spell Haste"),
                discord.SelectOption(label="SV Cold", value="SV Cold"),
                discord.SelectOption(label="SV Corruption", value="SV Corruption"),
                discord.SelectOption(label="SV Disease", value="SV Disease"),
                discord.SelectOption(label="SV Electricity", value="SV Electricity"),
                discord.SelectOption(label="SV Fire", value="SV Fire"),
                discord.SelectOption(label="SV Holy", value="SV Holy"),
                discord.SelectOption(label="SV Magic", value="SV Magic"),
                discord.SelectOption(label="SV Poison", value="SV Poison"),
                discord.SelectOption(label="Instrument", value="Instrument"),
                
              
            ]
        )
        self.stat_select.callback = self.select_stat
        self.add_item(self.stat_select)
        
        # Classes dropdown
        self.classes_select = discord.ui.Select(
            placeholder="🧙 Filter by class (optional)...",
            min_values=0,
            max_values=1,
            options=[
                discord.SelectOption(label="ARC", value="ARC"),
                discord.SelectOption(label="BRD", value="BRD"),
                discord.SelectOption(label="BST", value="BST"),
                discord.SelectOption(label="CLR", value="CLR"),
                discord.SelectOption(label="DRU", value="DRU"),
                discord.SelectOption(label="ELE", value="ELE"),
                discord.SelectOption(label="ENC", value="ENC"),
                discord.SelectOption(label="FTR", value="FTR"),
                discord.SelectOption(label="INQ", value="INQ"),
                discord.SelectOption(label="MNK", value="MNK"),
                discord.SelectOption(label="NEC", value="NEC"),
                discord.SelectOption(label="PAL", value="PAL"),
                discord.SelectOption(label="RNG", value="RNG"),
                discord.SelectOption(label="ROG", value="ROG"),
                discord.SelectOption(label="SHD", value="SHD"),
                discord.SelectOption(label="SHM", value="SHM"),
                discord.SelectOption(label="SPB", value="SPB"),
                discord.SelectOption(label="WIZ", value="WIZ"),
            ]
        )
        self.classes_select.callback = self.select_classes
        self.add_item(self.classes_select)

        
        # ---------------------------------------------------------
        # Bottom button row
        # Row 4 is shared by buttons.
        # The four dropdowns above occupy rows 0-3.
        # ---------------------------------------------------------

        self.type_filter = "with_stats"

        if source_command in ("db", "dbp"):

            # Search text button
            if show_search:
                self.add_item(SearchButton(self))

            # All Items button
            self.all_items_button = AllItemsButton(self)
            self.add_item(self.all_items_button)

            # Items With Stats button
            self.items_with_stats_button = ItemsWithStatsButton(self)
            self.add_item(self.items_with_stats_button)

         

        else:

            # Wiki search does not use the database Type buttons.
            if show_search:
                self.add_item(SearchButton(self))

        self.value = None


    async def select_slot(self, interaction: discord.Interaction):
        self.slot = self.slot_select.values[0]

        # Keep the selected Slot highlighted in the dropdown.
        for option in self.slot_select.options:
            option.default = (option.value == self.slot)

        # Clear any previous Skill Use selection.
        self.skill_use = None

        # ----------------------------------------------------
        # Build Skill Use options based on selected Slot.
        # ----------------------------------------------------

        if self.slot == "Primary":

            self.skill_use_select.options = [
                discord.SelectOption(
                    label="1H Bludgeoning",
                    value="BLG"
                ),
                discord.SelectOption(
                    label="2H Bludgeoning",
                    value="BLG Two Handed"
                ),
                discord.SelectOption(
                    label="1H Piercing",
                    value="STA"
                ),
                discord.SelectOption(
                    label="2H Piercing",
                    value="STA Two Handed"
                ),
                discord.SelectOption(
                    label="1H Slashing",
                    value="SLA"
                ),
                discord.SelectOption(
                    label="2H Slashing",
                    value="SLA Two Handed"
                ),
                discord.SelectOption(
                    label="Hand to Hand",
                    value="H2H"
                ),
            ]

            self.skill_use_select.disabled = False
            self.skill_use_select.placeholder = "⚔️ Select Skill Use (optional)..."

        elif self.slot == "Secondary":

            self.skill_use_select.options = [
                discord.SelectOption(
                    label="1H Bludgeoning",
                    value="BLG"
                ),
                discord.SelectOption(
                    label="1H Piercing",
                    value="STA"
                ),
                discord.SelectOption(
                    label="1H Slashing",
                    value="SLA"
                ),
                discord.SelectOption(
                    value="H2H",
                    label="Hand to Hand"
                ),
            ]

            self.skill_use_select.disabled = False
            self.skill_use_select.placeholder = "⚔️ Select Skill Use (optional)..."

        elif self.slot == "Range":

            self.skill_use_select.options = [
                discord.SelectOption(
                    label="Archery",
                    value="ARC"
                ),
                discord.SelectOption(
                    label="Throwing",
                    value="THR"
                ),
            ]

            self.skill_use_select.disabled = False
            self.skill_use_select.placeholder = "⚔️ Select Skill Use (optional)..."

        else:

            self.skill_use_select.options = [
                discord.SelectOption(
                    label="Select a Slot first",
                    value="disabled"
                )
            ]

            self.skill_use_select.disabled = True
            self.skill_use_select.placeholder = (
                "⚔️ Skill Use (select Primary, Secondary, or Range first)..."
            )

        await interaction.response.edit_message(view=self)
      

    async def select_skill_use(self, interaction: discord.Interaction):
        if self.skill_use_select.values:
            self.skill_use = self.skill_use_select.values[0]

            # Keep the selected Skill Use highlighted.
            for option in self.skill_use_select.options:
                option.default = (option.value == self.skill_use)
        else:
            self.skill_use = None

        await interaction.response.edit_message(view=self)


  

    async def select_stat(self, interaction: discord.Interaction):
        self.stat = (
            self.stat_select.values[0]
            if self.stat_select.values
            else None
        )

        # Keep the selected Stat highlighted.
        for option in self.stat_select.options:
            option.default = (option.value == self.stat)

        await interaction.response.edit_message(view=self)

  
        
    async def select_classes(self, interaction: discord.Interaction):
        self.classes = (
            self.classes_select.values[0]
            if self.classes_select.values
            else None
        )

        # Keep the selected Class highlighted.
        for option in self.classes_select.options:
            option.default = (option.value == self.classes)

        await interaction.response.edit_message(view=self)

  
    
   
    async def confirm_selection(self, interaction: discord.Interaction):
        if not self.optional_slot and not self.slot:
            await interaction.response.send_message("❌ Please select a slot first!", ephemeral=True)
            return
         # Replace filters message immediately
        await interaction.response.edit_message(
            content=f"⏳ Searching {self.source_command.upper()} for `{self.slot}` items"
                    f"{f' with {self.stat}' if self.stat else ''}..."
                    f"{f' for {self.classes}' if self.classes else ''}...",
            view=None
        )
        search_query = self.search_query or ""
        type_filter = getattr(self, "type_filter", "with_stats")
        if self.source_command in ("db", "dbp"):
            search_query = self.search_query or ""  # ✅ MAKE SURE WE PASS THE QUERY
            return await run_item_db(
                interaction,
                self.slot,
                self.stat,
                self.classes,
                getattr(self, "type_filter", "with_stats"),
                search_query,
                self.source_command,
                True,
                self.skill_use
              
            )

        
        
        # If the handler isn’t attached, fall back to auto-detect based on command
        if self.on_submit is None:
            if hasattr(self, "source_command"):
                source = self.source_command
                if source == "wiki":
                    await run_wiki_items(interaction, self.slot, self.stat, self.classes)
                    return
                elif source == "db":
                    await run_item_db(interaction, self.slot, self.stat, self.classes, getattr(self, "type_filter", "with_stats"), search_query)
                    return
                elif source == "dbp":
                    await run_item_db(interaction, self.slot, self.stat, self.classes, getattr(self, "type_filter", "with_stats"), search_query)
                    return
    
            # still no handler? give warning
            await interaction.response.send_message("⚠️ No handler attached to this filter.", ephemeral=True)
            return
    
        # Otherwise, use the explicitly provided handler
        await self.on_submit(interaction, self.slot, self.stat, self.classes)





@bot.tree.command(name="view_wiki_items", description="View items from the Monsters & Memories Wiki.")
async def view_wiki_items(interaction: discord.Interaction):
    # Step 1 — Show filter UI
    view = WikiSelectView(source_command="wiki", optional_slot=False, show_search=False)
    view.origin_interaction = interaction
    await interaction.response.send_message(
        "Please select a **Slot**, optional **Stat** or **Class**, then press ✅ **Search**:",
        view=view
    )

    # Wait for user input
    await view.wait()

    if not view.value:
        await interaction.followup.send("❌ Selection timed out or cancelled.", ephemeral=True)
        return

    slot = view.slot
    stat = view.stat
    classes = view.classes

    # Step 2 — Tell user we’re searching
    await interaction.response.edit_message(
        content=f"⏳ Searching Wiki and Database for `{slot}` items{f' with {stat}' if stat else ''}...",
        view=None
    )

    # Step 3 — Fetch + filter results
    combined_items = await run_wiki_items(view.search_interaction, slot, stat, classes)

    if not combined_items:
        await interaction.followup.send("❌ No items found matching that search.", ephemeral=True)
        return

    # Step 4 — Display results through WikiView
    results_view = WikiView(combined_items, source_command="wiki")
    await interaction.edit_original_response(
        content=None,
        embeds=results_view.build_embeds(0),
        view=results_view
    )




async def run_wiki_items(interaction: discord.Interaction, slot: str, stat: Optional[str], classes: Optional[str]):
    try:
        await interaction.response.defer(thinking=True)
    except discord.InteractionResponded:
        pass 
    
    followup = interaction.followup   
    guild_id = interaction.guild.id

    try:
        # --- Step 1: Pull Wiki items first ---
        print(f"🌐 Fetching Wiki items for slot: {slot}")
        wiki_items = await fetch_wiki_items(slot)
        if not wiki_items:
            print("⚠️ No wiki items returned.")
            wiki_items = []

        # --- Step 2: Pull DB items for this slot ---
        async with db_pool.acquire() as conn:
            db_rows = await conn.fetch("""
                SELECT item_name, item_image, item_slot, npc_name, zone_name, item_stats,
                       description, quest_name, npc_image, npc_level
                FROM item_database
                WHERE LOWER(item_slot) = LOWER($1)
            """, slot)
        
        
        # --- Apply Filters ---
        def text_cleanup(text: str) -> str:
            return (text or "").replace("\n", " ").replace("\r", " ")

        # Prepare regex patterns
        stat_patterns = []
        class_patterns = []

        if stat:
            stat_filter = str(stat).strip().lower()
            stat_keywords = {
                "str": [r"\bstr\b", r"\bstrength\b"],
                "agi": [r"\bagi\b", r"\bagility\b"],
                "dex": [r"\bdex\b", r"\bdexterity\b"],
                "int": [r"\bint\b", r"\bintelligence\b"],
                "sta": [r"\bsta\b", r"\bstamina\b"],
                "wis": [r"\bwis\b", r"\bwisdom\b"],
            }
            stat_patterns = [re.compile(pat, re.IGNORECASE) for pat in stat_keywords.get(stat_filter, [rf"\b{stat_filter}\b"])]

        if classes:
            classes_filter = str(classes).strip().lower()
            class_keywords = {
                "arc": [r"\barc\b"],
                "brd": [r"\bbrd\b"],
                "bst": [r"\bbst\b"],
                "clr": [r"\bclr\b"],
                "dru": [r"\bdru\b"],
                "ele": [r"\bele\b"],
                "enc": [r"\benc\b"],
                "ftr": [r"\bftr\b"],
                "inq": [r"\binq\b"],
                "mnk": [r"\bmnk\b"],
                "nec": [r"\bnec\b"],
                "pal": [r"\bpal\b"],
                "rng": [r"\brng\b"],
                "rog": [r"\brog\b"],
                "shd": [r"\bshd\b"],
                "shm": [r"\bshm\b"],
                "spd": [r"\bspd\b"],
                "wiz": [r"\bwiz\b"],
            }
            # Also include "ALL" automatically
            class_patterns = [re.compile(pat, re.IGNORECASE) for pat in (class_keywords.get(classes_filter, [rf"\b{classes_filter}\b"]) + [r"\bclass: all\b"])]

        # Function to check a text block against active filters
        def matches_filters(text: str) -> bool:
            text = text_cleanup(text)
            stat_match = any(p.search(text) for p in stat_patterns) if stat_patterns else True
            class_match = any(p.search(text) for p in class_patterns) if class_patterns else True
            # Both must match if both filters active
            return stat_match and class_match

        # Apply filters
        wiki_items = [i for i in wiki_items if matches_filters(i.get("item_stats" or ""))]
        db_rows = [r for r in db_rows if matches_filters(r.get("item_stats") or "")]

        print(f"🔍 Final filter results — Stat: {stat or 'None'}, Class: {classes or 'None'} | Wiki: {len(wiki_items)}, DB: {len(db_rows)}")

        
        def normalize_name(name):
            return name.strip().lower().replace("’", "'").replace("‘", "'").replace("`", "'")

        db_item_names = {normalize_name(row["item_name"]) for row in db_rows}

        # --- Step 3: Identify wiki items not yet in DB ---
        new_wiki_items = []
        for item in wiki_items:
            if normalize_name(item["item_name"]) not in db_item_names:
                new_wiki_items.append(item)

        # --- Step 4: Insert missing wiki items into DB ---
        if new_wiki_items:
            print(f"🟢 Found {len(new_wiki_items)} new wiki items — inserting...")
                        
            async with db_pool.acquire() as conn:
                for item in new_wiki_items:
                    npc_name = item.get("npc_name") or ""
                    quest_name = item.get("quest_name") or ""
                    zone_name = item.get("zone_name") or ""

                    # --- 1️⃣ If npc_name and quest_name are the same, clear npc_name
                    if npc_name.strip().lower() == quest_name.strip().lower() and npc_name:
                        npc_name = ""
            
                    # --- 2️⃣ If zone_name contains a number, swap it into npc_name and clear zone_name
                    if any(char.isdigit() for char in zone_name):
                        npc_name = zone_name
                        zone_name = ""

                    
                    await conn.execute("""
                        INSERT INTO item_database (
                            item_name, item_slot, item_image, npc_image, npc_name, zone_name, zone_area,
                            item_stats, description, quest_name, npc_level, added_by, source
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'Wiki')
                        ON CONFLICT (item_name) DO NOTHING
                    """,
                    item["item_name"],
                    slot,
                    item.get("item_image") or "",
                    item.get("npc_image") or "",                   
                    npc_name,
                    zone_name,
                    item.get("zone_area") or "",
                    item.get("item_stats") or "",
                    item.get("description") or "",                 
                    item.get("quest_name") or "",
                    item.get("npc_level") or "",
                    interaction.user.name
                    )
            print(f"✅ Inserted {len(new_wiki_items)} wiki items into DB.")
    
            # 🖼️ Now that all inserts are safely committed
            for item in new_wiki_items:
                img_width, img_height = 700, 300
                text_color = (255, 255, 255)
            
                image = Image.open("assets/backgrounds/itembg.png").convert("RGBA")
                draw = ImageDraw.Draw(image)
                

                def draw_wrapped_text(draw, text, font, position, max_width, line_height, fill=(255,255,255), spacing=3):
                    lines = []
                    for line in text.split("\n"):
                        lines.extend(wrap(line, width=max_width))
                    y = position[1]
                    for line in lines:
                        draw.text((position[0], y), line, font=font, fill=fill)
                        y += line_height + spacing

                try:
                    font_title = ImageFont.truetype("assets/WinthorpeScB.ttf", 28)
                    font_stats = ImageFont.truetype("assets/Winthorpe.ttf", 16)
                except:
                    font_title = ImageFont.load_default()
                    font_stats = ImageFont.load_default()
            
                title = item["item_name"]
                stats = item.get("item_stats", "None listed")
                                
                                              
                # Title and stat spacing
                draw.text((40, 3), title, font=font_title, fill="white")
                draw_wrapped_text(draw, stats, font_stats, (110, 55), max_width=70, line_height=18, spacing=5, fill=text_color )
            
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                buffer.seek(0)
                guild = bot.get_guild(UPLOAD_GUILD_ID)
                upload_channel = guild.get_channel(UPLOAD_CHANNEL_ID)
                if upload_channel:
                    msg = await upload_channel.send(
                        content=f"📦 Generated image for `{title}` (Wiki Import)",
                        file=discord.File(buffer, filename=f"{title.replace(' ', '_')}.png")
                    )
                    image_url =msg.attachments[0].url
                    async with db_pool.acquire() as conn:
                        await conn.execute("""
                            UPDATE item_database
                            SET item_image = $1,
                                item_msg_id = $2
                            WHERE item_name = $3
                        """, msg.attachments[0].url, msg.id, item["item_name"])
                    print(f"✅ Updated DB with image for {title}: {image_url}")

        # --- Step 5: Combine DB + Wiki items for display ---
        # ✅ Re-fetch all slot items from DB so the new image URLs are included
        async with db_pool.acquire() as conn:
            refreshed_rows = await conn.fetch("""
                SELECT item_name, item_image, npc_image, npc_name, zone_name, zone_area,
                       item_slot, item_stats, description, quest_name, npc_level, source
                FROM item_database
                WHERE LOWER(item_slot) = LOWER($1)
                ORDER BY item_name ASC
            """, slot)
       
 
        # After fetching refreshed_rows
        if stat or classes:
            refreshed_rows = [r for r in refreshed_rows if matches_filters(r.get("item_stats") or "")]

        
        
        
        
        # --- Convert into WikiView-compatible format ---
        
        combined_items = [
            {
                "item_name": row["item_name"],
                "item_image": row["item_image"] or "",
                "npc_image": row["npc_image"] or "",
                "npc_name": row["npc_name"] or "",
                "zone_name": row["zone_name"] or "",
                "zone_area": row["zone_area"] or "",
                "slot_name": row["item_slot"],
                "item_stats": row["item_stats"] or "",
                "wiki_url": None,
                "description": row["description"] or "",
                "quest_name": row["quest_name"] or "",
                "npc_level": row["npc_level"] or "",
                "source": row["source"],
                "in_database": True,
            }
            for row in refreshed_rows
        ]

    
        
        if not combined_items:
            await interaction.edit_original_response(
                content=f"❌ No items found for `{slot}` in the database or wiki.",
                embeds=[], view=None
            )
            return


        # --- Step 6: Send combined results to WikiView ---
        view = WikiView(combined_items)
        await interaction.edit_original_response(content=None, embeds=view.build_embeds(0), view=view)


    except Exception as e:
        print(f"❌ Critical error in view_wiki_items: {e}")
        await interaction.followup.send(f"❌ Error running command: {e}")


#--------SEND TO CHANNEL-------

class ItemSelectMenu(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        options = self._build_options()
        super().__init__(
            placeholder="🔍 View details for an item...",
            min_values=1,
            max_values=1,
            options=options
        )

    def _build_options(self):
        """Generate dropdown options for the current page's items."""
        start = self.parent_view.current_page * self.parent_view.items_per_page
        end = start + self.parent_view.items_per_page
        current_items = self.parent_view.items[start:end]

        return [
            discord.SelectOption(
                label=item["item_name"][:100],
                description=(item.get("zone_name") or "Unknown Zone")[:80],
                value=str(start + i)
            )
            for i, item in enumerate(current_items)
        ]

    async def callback(self, interaction: discord.Interaction):
        """Show ephemeral item details when selected."""
        idx = int(self.values[0])
        item = self.parent_view.items[idx]
        linkback= "https://monstersandmemories.miraheze.org/wiki/"
        item_link =f"{linkback}{item['item_name'].replace(' ', '_')}"
        zone_link = f"{linkback}{item['zone_name'].replace(' ', '_')}"
        quest_link = f"{linkback}{item['quest_name'].replace(' ', '_')}"
        if any(char.isdigit() for char in item["npc_name"]):
            npc_name=item["npc_name"]
    
        else:    
            npc_string= item["npc_name"]
            # Split by comma and strip spaces
            npc_name = [name.strip() for name in npc_string.split(",") if name.strip()]
            # Build full wiki links
            linked_npc = []
            for name in npc_name:
                # Trash Mobs is not a real wiki page, so don't make it a link.
                if name.strip().lower() == "trash mobs":
                    linked_npc.append(name)
                else:
                    # Replace spaces with underscores for proper wiki URL formatting
                    npc_url = linkback + name.replace(" ", "_")
                    linked_npc.append(f"[{name}]({npc_url})")
            # Join with newlines for vertical display in embed
            npc_name = " \n ".join(linked_npc)

        
        level = item["npc_level"]
        level_number = re.search(r'\d', level)
        if level_number:
            npc_level = f"Level: ~{level[level_number.start():]}"
        else:
            npc_level=""
        

        embed = discord.Embed(
            title=item["item_name"],
            url=f"{item_link}",
            color=discord.Color.red()
        )

        if item["zone_name"] != "":
            embed.add_field(name="🗺️ Zone ", value=f"[{item['zone_name']}]({zone_link})" f"\n{item['zone_area']}", inline=True)
        if npc_name != "":
            embed.add_field(name="👹 Npc", value=f"{npc_name}" f"\n{npc_level}", inline=True)
            
        if item["item_image"] == "":
            embed.add_field(name="⚔️ Item Stats", value=item["item_stats"], inline=False)
        if item["item_image"] != "":
            embed.set_image(url=item["item_image"])
        if item["npc_image"] != "":
            embed.set_thumbnail(url=item["npc_image"])            
      

        await interaction.response.send_message(embed=embed, ephemeral=True)



# =========================================================
# UPDATE DB CONTROL VIEW
# =========================================================

class UpdateDBView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=900)
        self.stopped = False

    @discord.ui.button(
        label="Stop",
        style=discord.ButtonStyle.danger
    )
    async def stop_update(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        self.stopped = True

        button.disabled = True

        await interaction.response.edit_message(
            content=(
                "🛑 **Update stopped.**\n\n"
                "All updates that were already completed have been saved."
            ),
            view=self
        )



class UpdateDBTermModal(discord.ui.Modal, title="Enter Update Term"):

    update_term = discord.ui.TextInput(
        label="Item Name Search",
        placeholder="Enter part of an item name...",
        required=True,
        max_length=100
    )

    def __init__(self, original_interaction):
        super().__init__()
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):

        term = self.update_term.value.strip()

        if not term:
            await interaction.response.send_message(
                "⚠️ Please enter an update term.",
                ephemeral=True
            )
            return

        update_view = UpdateDBStopView()

        # Acknowledge the modal
        await interaction.response.defer()

        # Replace the ORIGINAL /update_db message.
        # Do NOT send a new message.
        await self.original_interaction.edit_original_response(
            content=(
                f"🔄 **Updating Database**\n\n"
                f"Searching for items matching:\n"
                f"**{term}**\n\n"
                f"Only matching item names will be checked."
            ),
            view=update_view
        )

        await run_update_db(
            self.original_interaction,
            update_term=term,
            update_view=update_view
        )


class UpdateDBAlphabeticalSelect(discord.ui.Select):

    def __init__(self, parent_view):

        self.parent_view = parent_view

        options = [
            discord.SelectOption(
                label="A–E",
                description="Update items beginning with A, B, C, D, or E",
                value="A-E",
                default=parent_view.selected_range == "A-E"
            ),
            discord.SelectOption(
                label="F–J",
                description="Update items beginning with F, G, H, I, or J",
                value="F-J",
                default=parent_view.selected_range == "F-J"
            ),
            discord.SelectOption(
                label="K–O",
                description="Update items beginning with K, L, M, N, or O",
                value="K-O",
                default=parent_view.selected_range == "K-O"
            ),
            discord.SelectOption(
                label="P–T",
                description="Update items beginning with P, Q, R, S, or T",
                value="P-T",
                default=parent_view.selected_range == "P-T"
            ),
            discord.SelectOption(
                label="U–Z",
                description="Update items beginning with U, V, W, X, Y, or Z",
                value="U-Z",
                default=parent_view.selected_range == "U-Z"
            )
        ]

        super().__init__(
            placeholder="Select alphabetical section...",
            options=options,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):

        ranges = {
            "A-E": ("A", "E"),
            "F-J": ("F", "J"),
            "K-O": ("K", "O"),
            "P-T": ("P", "T"),
            "U-Z": ("U", "Z")
        }

        selected_range = self.values[0]

        start_letter, end_letter = ranges[selected_range]

        self.parent_view.selected_range = selected_range
        self.parent_view.start_letter = start_letter
        self.parent_view.end_letter = end_letter

        # Rebuild the dropdown so the selected option remains selected
        new_view = UpdateDBView(
            selected_range=selected_range,
            start_letter=start_letter,
            end_letter=end_letter
        )

        await interaction.response.edit_message(
            content=(
                "📚 **Update Database**\n\n"
                "Select the alphabetical section you want to update.\n\n"
                "You can also use **Enter Update Term** to search for "
                "a partial item name."
            ),
            view=new_view
        )


class UpdateDBButton(discord.ui.Button):

    def __init__(self):

        super().__init__(
            label="Update",
            style=discord.ButtonStyle.success,
            emoji="🔄"
        )

    async def callback(self, interaction: discord.Interaction):

        view = self.view

        if not view.selected_range:
            await interaction.response.send_message(
                "⚠️ Please select an alphabetical section first.",
                ephemeral=True
            )
            return

        selected_range = view.selected_range
        start_letter = view.start_letter
        end_letter = view.end_letter
        update_view = UpdateDBStopView()

        await interaction.response.edit_message(
            content=(
                f"🔄 **Starting Database Update: {selected_range}**\n\n"
                f"Checking items beginning with "
                f"**{start_letter}–{end_letter}**."
            ),
            view=update_view
        )

        await run_update_db(
            interaction,
            start_letter=start_letter,
            end_letter=end_letter,
            update_view=update_view
        )


class UpdateDBTermButton(discord.ui.Button):

    def __init__(self):

        super().__init__(
            label="Enter Update Term",
            style=discord.ButtonStyle.primary,
            emoji="🔎"
        )

    async def callback(self, interaction: discord.Interaction):

        await interaction.response.send_modal(
            UpdateDBTermModal(interaction)
        )


class UpdateDBView(discord.ui.View):

    def __init__(
        self,
        selected_range=None,
        start_letter=None,
        end_letter=None
    ):

        super().__init__(timeout=120)

        self.selected_range = selected_range
        self.start_letter = start_letter
        self.end_letter = end_letter

        self.add_item(
            UpdateDBAlphabeticalSelect(self)
        )

        self.add_item(
            UpdateDBButton()
        )

        self.add_item(
            UpdateDBTermButton()
        )


class UpdateDBStopView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.stopped = False

        self.add_item(UpdateDBStopButton(self))


class UpdateDBStopButton(discord.ui.Button):

    def __init__(self, parent_view):
        super().__init__(
            label="Stop",
            style=discord.ButtonStyle.danger,
            emoji="🛑"
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):

        self.parent_view.stopped = True

        await interaction.response.edit_message(
            content="🛑 **Stopping database update...**\n\nThe update will stop after the current item finishes.",
            view=None
        )



@bot.tree.command(name="update_db", description="Compare existing DB items with the Wiki and update any changed fields.")
@app_commands.checks.has_permissions(administrator=True)
async def update_db(interaction: discord.Interaction):

    view = UpdateDBView()

    await interaction.response.send_message(
        "📚 **Update Database**\n\n"
        "Select the alphabetical section you want to update.\n\n"
        "You can also use **Enter Update Term** to search for "
        "a partial item name.",
        view=view,
        ephemeral=True
    )



async def run_update_db(
    interaction: discord.Interaction,
    start_letter=None,
    end_letter=None,
    update_term=None,
    update_view=None
):

    base_url = "https://monstersandmemories.miraheze.org/wiki"
    wiki_base = "https://monstersandmemories.miraheze.org"

    updated_count = 0
    checked_count = 0
    failed_items = []
    changes_log = []

    # ---------------------------------------------------------
    # Request settings
    # ---------------------------------------------------------

    REQUEST_DELAY = 1.0
    NPC_REQUEST_DELAY = 0.5
    MAX_RETRIES = 4


    async def fetch_with_retry(
        session,
        url,
        label="Wiki page"
    ):
        """
        Fetch a Wiki page while handling temporary rate limits
        and server errors.
        """

        for attempt in range(MAX_RETRIES):

            try:

                async with session.get(
                    url,
                    ssl=False,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:

                    # -----------------------------------------
                    # Successful request
                    # -----------------------------------------

                    if resp.status == 200:

                        return await resp.text(
                            errors="ignore"
                        )

                    # -----------------------------------------
                    # Rate limited
                    # -----------------------------------------

                    if resp.status == 429:

                        retry_after = resp.headers.get(
                            "Retry-After"
                        )

                        try:
                            wait_time = float(
                                retry_after
                            )
                        except (
                            TypeError,
                            ValueError
                        ):
                            wait_time = (
                                5 * (attempt + 1)
                            )

                        wait_time = min(
                            wait_time,
                            60
                        )

                        print(
                            f"⚠️ Wiki rate limit for "
                            f"{label}. "
                            f"Waiting {wait_time:.1f}s..."
                        )

                        await asyncio.sleep(
                            wait_time
                        )

                        continue

                    # -----------------------------------------
                    # Temporary server error
                    # -----------------------------------------

                    if resp.status in (
                        500,
                        502,
                        503,
                        504
                    ):

                        wait_time = (
                            3 * (attempt + 1)
                        )

                        print(
                            f"⚠️ Wiki HTTP "
                            f"{resp.status} for "
                            f"{label}. "
                            f"Retrying in "
                            f"{wait_time}s..."
                        )

                        await asyncio.sleep(
                            wait_time
                        )

                        continue

                    # -----------------------------------------
                    # Permanent failure
                    # -----------------------------------------

                    print(
                        f"⚠️ Wiki returned HTTP "
                        f"{resp.status} for "
                        f"{label}"
                    )

                    return None

            except (
                aiohttp.ClientError,
                asyncio.TimeoutError
            ) as e:

                wait_time = (
                    3 * (attempt + 1)
                )

                print(
                    f"⚠️ Request error for "
                    f"{label}: {e}. "
                    f"Retrying in "
                    f"{wait_time}s..."
                )

                await asyncio.sleep(
                    wait_time
                )

        print(
            f"❌ Failed after "
            f"{MAX_RETRIES} attempts: "
            f"{label}"
        )

        return None

    try:

        # -----------------------------------------------------
        # Get Item from the database
        # -----------------------------------------------------

        async with db_pool.acquire() as conn:
        
            # ---------------------------------------------------------
            # Enter Update Term
            # ---------------------------------------------------------
        
            if update_term:
        
                db_items = await conn.fetch(
                    """
                    SELECT id, item_name, zone_name, zone_area, npc_name,
                           item_stats, crafted_name, crafting_recipe,
                           quest_name, npc_image, npc_level, guild_id
                    FROM item_database
                    WHERE item_name ILIKE $1
                    ORDER BY item_name ASC
                    """,
                    f"%{update_term}%"
                )
        
            # ---------------------------------------------------------
            # Alphabetical Range
            # ---------------------------------------------------------
        
            elif start_letter and end_letter:
        
                db_items = await conn.fetch(
                    """
                    SELECT id, item_name, zone_name, zone_area, npc_name,
                           item_stats, crafted_name, crafting_recipe,
                           quest_name, npc_image, npc_level, guild_id
                    FROM item_database
                    WHERE LEFT(UPPER(TRIM(item_name)), 1)
                          BETWEEN $1 AND $2
                    ORDER BY item_name ASC
                    """,
                    start_letter,
                    end_letter
                )
        
            # ---------------------------------------------------------
            # Fallback - All Items
            # ---------------------------------------------------------
        
            else:
        
                db_items = await conn.fetch(
                    """
                    SELECT id, item_name, zone_name, zone_area, npc_name,
                           item_stats, crafted_name, crafting_recipe,
                           quest_name, npc_image, npc_level, guild_id
                    FROM item_database
                    ORDER BY item_name ASC
                    """
                )

        total_items = len(db_items)

        print(
            f"🔍 Starting Wiki update for "
            f"{total_items} database items."
        )

        # -----------------------------------------------------
        # Wiki session
        # -----------------------------------------------------

        headers = {
            "User-Agent": (
                "MonstersAndMemoriesDiscordBot/1.0 "
                "(Wiki database updater)"
            )
        }

        async with aiohttp.ClientSession(
            headers=headers
        ) as session:
        
            for db_item in db_items:
            
                # -------------------------------------------------
                # STOP CHECK
                # -------------------------------------------------
            
                if update_view and update_view.stopped:
                    print("🛑 Database update stopped by user.")
                    break
            
                item_name = (
                    db_item["item_name"]
                    or ""
                ).strip()

                checked_count += 1

                if not item_name:
                    continue

                print(
                    f"🔎 [{checked_count}/{total_items}] "
                    f"Checking {item_name}"
                )

                # -------------------------------------------------
                # Build item Wiki URL
                # -------------------------------------------------

                item_url = (
                    f"{base_url}/"
                    f"{item_name.replace(' ', '_')}"
                )

                # -------------------------------------------------
                # Fetch item page
                # -------------------------------------------------

                html = await fetch_with_retry(
                    session,
                    item_url,
                    f"item: {item_name}"
                )

                if not html:

                    failed_items.append(
                        item_name
                    )

                    await asyncio.sleep(
                        REQUEST_DELAY
                    )

                    continue

                soup = BeautifulSoup(
                    html,
                    "html.parser"
                )

                # =================================================
                # WIKI VALUES
                # =================================================

                wiki_item_stats = ""
                wiki_zone_name = ""
                wiki_npc_name = ""
                wiki_npc_image = ""
                wiki_npc_level = ""
                wiki_quest_name = ""

                # =================================================
                # ITEM STATS
                # =================================================

                item_stats_div = soup.find(
                    "div",
                    class_="item-stats"
                )

                if item_stats_div:

                    lines = [
                        line.strip()
                        for line
                        in item_stats_div.stripped_strings
                    ]

                    wiki_item_stats = "\n".join(
                        lines
                    ).strip()

                # =================================================
                # DROPS FROM
                # =================================================

                drops_section = soup.find(
                    "h2",
                    id="Drops_From"
                )

                if drops_section:

                    drops_heading_wrapper = (
                        drops_section.parent
                    )

                    if drops_heading_wrapper:

                        current_sibling = (
                            drops_heading_wrapper
                            .find_next_sibling()
                        )

                        # -----------------------------------------
                        # Zone
                        # -----------------------------------------

                        if (
                            current_sibling
                            and current_sibling.name == "p"
                        ):

                            wiki_zone_name = (
                                current_sibling
                                .get_text(
                                    " ",
                                    strip=True
                                )
                            )

                            current_sibling = (
                                current_sibling
                                .find_next_sibling()
                            )

                        # -----------------------------------------
                        # NPC list
                        # -----------------------------------------

                        if (
                            current_sibling
                            and current_sibling.name == "ul"
                        ):

                            npc_links = (
                                current_sibling
                                .find_all(
                                    "a",
                                    href=True
                                )
                            )

                            if npc_links:

                                npc_names = []

                                for link in npc_links:

                                    name = (
                                        link.get_text(
                                            " ",
                                            strip=True
                                        )
                                    )

                                    if (
                                        name
                                        and name
                                        not in npc_names
                                    ):
                                        npc_names.append(
                                            name
                                        )

                               
                                if len(npc_names) >= 3:
                                    wiki_npc_name = "Trash Mobs"
                                else:
                                    wiki_npc_name = ", ".join(npc_names)

                            else:

                                npc_items = (
                                    current_sibling
                                    .find_all("li")
                                )

                                npc_names = []

                                for li in npc_items:

                                    name = (
                                        li.get_text(
                                            " ",
                                            strip=True
                                        )
                                    )

                                    if (
                                        name
                                        and name
                                        not in npc_names
                                    ):
                                        npc_names.append(
                                            name
                                        )

                                if len(npc_names) >= 3:
                                    wiki_npc_name = "Trash Mobs"
                                else:
                                    wiki_npc_name = ", ".join(npc_names)

                # =================================================
                # RELATED QUEST
                # =================================================

                quest_section = soup.find(
                    "h2",
                    id="Related_quests"
                )

                if quest_section:

                    quest_heading_wrapper = (
                        quest_section.parent
                    )

                    if quest_heading_wrapper:

                        quest_list = (
                            quest_heading_wrapper
                            .find_next_sibling()
                        )

                        if (
                            quest_list
                            and quest_list.name == "ul"
                        ):

                            quest_links = (
                                quest_list.find_all(
                                    "a",
                                    href=True
                                )
                            )

                            if quest_links:

                                quest_names = []

                                for link in quest_links:

                                    name = (
                                        link.get_text(
                                            " ",
                                            strip=True
                                        )
                                    )

                                    if (
                                        name
                                        and name
                                        not in quest_names
                                    ):
                                        quest_names.append(
                                            name
                                        )

                                wiki_quest_name = (
                                    ", ".join(
                                        quest_names
                                    )
                                )

                # =================================================
                # NPC / QUEST CLEANUP
                # =================================================

                if (
                    wiki_quest_name
                    and wiki_npc_name
                    and (
                        wiki_npc_name.strip().lower()
                        ==
                        wiki_quest_name.strip().lower()
                    )
                ):
                    wiki_npc_name = ""

                # =================================================
                # NPC DETAILS / IMAGE
                # =================================================

                if wiki_npc_name and wiki_npc_name.strip().lower() != "trash mobs":

                    first_npc = (
                        wiki_npc_name
                        .split(",")[0]
                        .strip()
                    )

                    npc_page_name = (
                        first_npc.replace(
                            " ",
                            "_"
                        )
                    )

                    npc_url = (
                        f"{wiki_base}/wiki/"
                        f"{npc_page_name}"
                    )

                    # ---------------------------------------------
                    # Space out NPC request from item request
                    # ---------------------------------------------

                    await asyncio.sleep(
                        NPC_REQUEST_DELAY
                    )

                    npc_html = (
                        await fetch_with_retry(
                            session,
                            npc_url,
                            f"NPC: {first_npc}"
                        )
                    )

                    if npc_html:

                        npc_soup = BeautifulSoup(
                            npc_html,
                            "html.parser"
                        )

                        # -----------------------------------------
                        # NPC image
                        # -----------------------------------------

                        npc_img = None

                        image_selectors = [
                            'span[typeof="mw:File"] img',
                            'span[typeof="mw:Image"] img',
                            'figure img',
                            'table.infobox img',
                            'table.wikitable img',
                            'img'
                        ]

                        for selector in image_selectors:

                            candidate = (
                                npc_soup.select_one(
                                    selector
                                )
                            )

                            if candidate:

                                src = (
                                    candidate.get("src")
                                    or candidate.get(
                                        "data-src"
                                    )
                                    or candidate.get(
                                        "data-original"
                                    )
                                    or ""
                                )

                                if src:

                                    npc_img = src
                                    break

                        if npc_img:

                            if npc_img.startswith(
                                "//"
                            ):

                                wiki_npc_image = (
                                    f"https:{npc_img}"
                                )

                            elif npc_img.startswith(
                                "/"
                            ):

                                wiki_npc_image = (
                                    f"{wiki_base}"
                                    f"{npc_img}"
                                )

                            elif npc_img.startswith(
                                "http"
                            ):

                                wiki_npc_image = (
                                    npc_img
                                )

                            else:

                                wiki_npc_image = (
                                    f"{wiki_base}/"
                                    f"{npc_img.lstrip('/')}"
                                )

                        # -----------------------------------------
                        # NPC level
                        #
                        # Not currently written to the database
                        # by this updater, but we leave the
                        # scraping here for future use.
                        # -----------------------------------------

                        mob_stats = npc_soup.find(
                            "table",
                            class_="mobStatsBox"
                        )

                        if mob_stats:

                            tds = (
                                mob_stats.find_all(
                                    "td"
                                )
                            )

                            if len(tds) >= 3:

                                wiki_npc_level = (
                                    tds[2]
                                    .get_text(
                                        " ",
                                        strip=True
                                    )
                                )

                # =================================================
                # DETERMINE CHANGES
                # =================================================

                changes = {}

          
                # -------------------------------------------------
                # ITEM STATS
                #
                # Replace when different.
                # -------------------------------------------------
                
                current_item_stats = (
                    db_item["item_stats"]
                    or ""
                ).strip()
                
                stats_changed = (
                    wiki_item_stats
                    and wiki_item_stats != current_item_stats
                )
                
                regenerate_item_image = (
                    stats_changed
                    and bool(re.search(r"\d", current_item_stats))
                )
                
                if stats_changed:
                    changes["item_stats"] = wiki_item_stats

                
                # -------------------------------------------------
                # REGENERATE ITEM IMAGE
                #
                # If the existing stats contained numbers and
                # the Wiki stats changed, regenerate the image
                # using the NEW Wiki stats.
                # -------------------------------------------------

                if regenerate_item_image:

                    print(
                        f"🖼️ Regenerating item image for "
                        f"{item_name} because item stats changed."
                    )

                    try:

                        # ---------------------------------------------
                        # Create new image using the existing format
                        # ---------------------------------------------

                        image = Image.open(
                            "assets/backgrounds/itembg.png"
                        ).convert("RGBA")

                        draw = ImageDraw.Draw(image)

                        try:

                            font_title = ImageFont.truetype(
                                "assets/WinthorpeScB.ttf",
                                28
                            )

                            font_stats = ImageFont.truetype(
                                "assets/Winthorpe.ttf",
                                16
                            )

                        except Exception:

                            font_title = ImageFont.load_default()
                            font_stats = ImageFont.load_default()

                        # ---------------------------------------------
                        # Draw title
                        # ---------------------------------------------

                        draw.text(
                            (40, 3),
                            item_name,
                            font=font_title,
                            fill="white"
                        )

                        # ---------------------------------------------
                        # Draw NEW Wiki stats
                        # ---------------------------------------------

                        lines = []

                        for line in wiki_item_stats.split("\n"):

                            lines.extend(
                                wrap(
                                    line,
                                    width=70
                                )
                            )

                        y = 55

                        for line in lines:

                            draw.text(
                                (110, y),
                                line,
                                font=font_stats,
                                fill=(255, 255, 255)
                            )

                            y += 18 + 5

                        # ---------------------------------------------
                        # Convert image to PNG buffer
                        # ---------------------------------------------

                        buffer = io.BytesIO()

                        image.save(
                            buffer,
                            format="PNG"
                        )

                        buffer.seek(0)

                        # ---------------------------------------------
                        # Get upload channel
                        # ---------------------------------------------

                        guild = bot.get_guild(
                            UPLOAD_GUILD_ID
                        )

                        upload_channel = (
                            guild.get_channel(
                                UPLOAD_CHANNEL_ID
                            )
                            if guild
                            else None
                        )

                        if upload_channel:

                            # -----------------------------------------
                            # Delete old generated image
                            # -----------------------------------------

                            old_item_msg_id = (
                                db_item["item_msg_id"]
                            )

                            if old_item_msg_id:

                                try:

                                    old_msg = (
                                        await upload_channel.fetch_message(
                                            int(old_item_msg_id)
                                        )
                                    )

                                    await old_msg.delete()

                                    print(
                                        f"🗑️ Deleted old item image "
                                        f"for {item_name}"
                                    )

                                except discord.NotFound:

                                    pass

                                except Exception as e:

                                    print(
                                        f"⚠️ Could not delete old "
                                        f"item image for "
                                        f"{item_name}: {e}"
                                    )

                            # -----------------------------------------
                            # Upload regenerated image
                            # -----------------------------------------

                            msg = await upload_channel.send(
                                content=(
                                    f"📦 Generated image for "
                                    f"`{item_name}` "
                                    f"(Wiki Update)"
                                ),
                                file=discord.File(
                                    buffer,
                                    filename=(
                                        f"{item_name.replace(' ', '_')}.png"
                                    )
                                )
                            )

                            new_item_image_url = (
                                msg.attachments[0].url
                            )

                            new_item_msg_id = msg.id

                            # -----------------------------------------
                            # Save new image information
                            # -----------------------------------------

                            changes["item_image"] = (
                                new_item_image_url
                            )

                            changes["item_msg_id"] = (
                                new_item_msg_id
                            )

                            print(
                                f"✅ Generated new item image "
                                f"for {item_name}"
                            )

                        else:

                            print(
                                f"⚠️ Upload channel not found. "
                                f"Could not regenerate image "
                                f"for {item_name}"
                            )

                    except Exception as e:

                        print(
                            f"❌ Failed to regenerate item image "
                            f"for {item_name}: {e}"
                        )
                # -------------------------------------------------
                # ZONE
                #
                # Only fill if currently blank.
                # -------------------------------------------------

                current_zone = (
                    db_item["zone_name"]
                    or ""
                ).strip()

                if (
                    not current_zone
                    and wiki_zone_name
                ):

                    changes["zone_name"] = (
                        wiki_zone_name
                    )

                # -------------------------------------------------
                # NPC NAME
                #
                # Only fill if currently blank.
                # -------------------------------------------------

                current_npc = (
                    db_item["npc_name"]
                    or ""
                ).strip()

                if (
                    not current_npc
                    and wiki_npc_name
                ):

                    changes["npc_name"] = (
                        wiki_npc_name
                    )

                # -------------------------------------------------
                # NPC IMAGE
                #
                # Only fill if currently blank.
                # -------------------------------------------------

                current_npc_image = (
                    db_item["npc_image"]
                    or ""
                ).strip()

                if (
                    not current_npc_image
                    and wiki_npc_image
                ):

                    changes["npc_image"] = (
                        wiki_npc_image
                    )

                # -------------------------------------------------
                # QUEST
                #
                # Only fill if currently blank.
                # -------------------------------------------------

                current_quest = (
                    db_item["quest_name"]
                    or ""
                ).strip()

                if (
                    not current_quest
                    and wiki_quest_name
                ):

                    changes["quest_name"] = (
                        wiki_quest_name
                    )

                # =================================================
                # APPLY CHANGES
                # =================================================

                if changes:

                    async with db_pool.acquire() as conn:

                        set_clause = ", ".join(
                            f"{column} = ${index + 2}"
                            for index, column
                            in enumerate(
                                changes.keys()
                            )
                        )

                        values = list(
                            changes.values()
                        )

                        # IMPORTANT:
                        # Update this exact database row.
                        #
                        # This prevents a global item and a
                        # guild-specific item with the same name
                        # from accidentally updating each other.
                        await conn.execute(
                            f"""
                            UPDATE item_database
                            SET {set_clause}
                            WHERE id = $1
                            """,
                            db_item["id"],
                            *values
                        )

                    updated_count += 1

                    changed_fields = ", ".join(
                        changes.keys()
                    )

                    changes_log.append(
                        f"🛠️ `{item_name}` → "
                        f"{changed_fields}"
                    )

                    print(
                        f"✅ Updated {item_name}: "
                        f"{changed_fields}"
                    )

                # =================================================
                # POLITE DELAY
                # =================================================

                await asyncio.sleep(
                    REQUEST_DELAY
                )

                # =================================================
                # PROGRESS
                # =================================================

                if (
                    checked_count % 25 == 0
                    or checked_count == total_items
                ):

                    print(
                        f"📊 Update progress: "
                        f"{checked_count}/"
                        f"{total_items}"
                    )

        # =========================================================
        # FINAL SUMMARY
        # =========================================================

        summary = (
            f"✅ Sync complete!\n"
            f"🔍 Checked: `{checked_count}` items\n"
            f"🛠️ Updated: `{updated_count}` items\n"
        )

        if failed_items:

            summary += (
                f"⚠️ Failed: "
                f"`{len(failed_items)}` items\n"
            )

        if changes_log:

            summary += (
                "\n**Changes:**\n"
                + "\n".join(
                    changes_log[:30]
                )
            )

            if len(changes_log) > 30:

                summary += (
                    f"\n...and "
                    f"{len(changes_log) - 30} "
                    f"more changes."
                )

        if failed_items:

            summary += (
                "\n\n**Failed Items:**\n"
                + "\n".join(
                    f"• `{name}`"
                    for name in failed_items[:30]
                )
            )

            if len(failed_items) > 30:

                summary += (
                    f"\n...and "
                    f"{len(failed_items) - 30} "
                    f"more failed items."
                )

        await interaction.edit_original_response(
            content=summary,
            view=None
        )

    except Exception as e:

        print(
            f"❌ Update failed: {e}"
        )

        import traceback

        traceback.print_exc()

        try:

            await interaction.followup.send(
                f"❌ Update failed:\n"
                f"`{e}`",
                ephemeral=True
            )

        except Exception as followup_error:

            print(
                f"⚠️ Could not send error "
                f"followup: {followup_error}"
            )


# ============================================================
# ====================== MAP SYSTEM ==========================
# ============================================================

# All map data is global and shared by every Discord server.
# Every map row is stored with guild_id = 1.
GLOBAL_MAP_GUILD_ID = 1

async def ensure_maps_table():
    """
    Create/migrate the maps table.

    Supports multiple maps per zone using map_number.
    """

    async with db_pool.acquire() as conn:

        # ----------------------------------------------------
        # Create table if it does not exist
        # ----------------------------------------------------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS maps (
                id BIGSERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                zone_name TEXT NOT NULL,
                map_number INTEGER,
                map_image TEXT NOT NULL,
                map_msg_id BIGINT,
                map_upload_guild_id BIGINT,
                map_upload_channel_id BIGINT,
                added_by TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # ----------------------------------------------------
        # Add map_number to older maps table
        # ----------------------------------------------------
        await conn.execute("""
            ALTER TABLE maps
            ADD COLUMN IF NOT EXISTS map_number INTEGER
        """)


        # ----------------------------------------------------
        # Store the original wiki image URL
        # ----------------------------------------------------
        await conn.execute("""
            ALTER TABLE maps
            ADD COLUMN IF NOT EXISTS wiki_image_url TEXT
        """)

        # ----------------------------------------------------
        # Store where the Discord upload was created.
        # This is required because map data is global and the
        # upload may belong to a different Discord server.
        # ----------------------------------------------------
        await conn.execute("""
            ALTER TABLE maps
            ADD COLUMN IF NOT EXISTS map_upload_guild_id BIGINT
        """)

        await conn.execute("""
            ALTER TABLE maps
            ADD COLUMN IF NOT EXISTS map_upload_channel_id BIGINT
        """)

        # ----------------------------------------------------
        # GLOBALIZE ALL EXISTING MAPS
        #
        # Older versions stored the Discord guild ID in guild_id.
        # From now on every map belongs to GLOBAL_MAP_GUILD_ID.
        # ----------------------------------------------------
        await conn.execute("""
            DROP INDEX IF EXISTS maps_guild_zone_number_unique
        """)

        await conn.execute("""
            UPDATE maps
            SET guild_id = $1
        """, GLOBAL_MAP_GUILD_ID)

        # ----------------------------------------------------
        # Rebuild map numbers globally per zone.
        #
        # This prevents duplicate map numbers when maps from
        # multiple old guilds are merged into the global database.
        # Existing ordering is preserved as much as possible.
        # ----------------------------------------------------
        await conn.execute("""
            WITH numbered AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY zone_name
                        ORDER BY map_number ASC NULLS LAST, id ASC
                    ) AS new_map_number
                FROM maps
            )
            UPDATE maps AS m
            SET map_number = numbered.new_map_number,
                updated_at = NOW()
            FROM numbered
            WHERE m.id = numbered.id
        """)

        # ----------------------------------------------------
        # Make map numbers unique globally per zone.
        # ----------------------------------------------------
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            maps_guild_zone_number_unique
            ON maps (guild_id, zone_name, map_number)
        """)
        
        # ----------------------------------------------------
        # Give old maps map number 1
        # ----------------------------------------------------
        await conn.execute("""
            UPDATE maps
            SET map_number = 1
            WHERE map_number IS NULL
        """)


# ============================================================
# MAP EMBED
# ============================================================

def create_map_embed(zone_name, map_number, map_image):

    embed = discord.Embed(
        title=f"🗺️ {zone_name} - Map {map_number}",
        color=discord.Color.blurple()
    )

    embed.set_image(url=map_image)

    return embed


# ============================================================
# MAP ZONE SELECT
# ============================================================

class MapsZoneSelect(discord.ui.Select):

    def __init__(self, parent_view):

        self.parent_view = parent_view

        start = self.parent_view.current_page * 25
        end = start + 25

        page_zones = self.parent_view.zones[start:end]

        options = []

        for zone in page_zones:

            options.append(
                discord.SelectOption(
                    label=zone,
                    value=zone
                )
            )

        super().__init__(
            placeholder="Select a zone",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):

        selected_zone = self.values[0]

        self.parent_view.selected_zone = selected_zone

        # Immediately show ALL maps for the selected zone
        await self.parent_view.show_zone_maps(interaction)


# ============================================================
# MAP VIEW
# ============================================================

class MapsView(discord.ui.View):

    def __init__(self, interaction: discord.Interaction, zones):

        super().__init__(timeout=900)

        self.original_interaction = interaction

        self.zones = zones

        self.current_page = 0

        self.selected_zone = None

        # Add zone selector
        self.add_item(
            MapsZoneSelect(self)
        )

        self.update_buttons()

    # --------------------------------------------------------
    # Update navigation buttons
    # --------------------------------------------------------

    def update_buttons(self):

        total_pages = max(
            1,
            math.ceil(len(self.zones) / 25)
        )

        self.previous_button.disabled = (
            self.current_page <= 0
        )

        self.next_button.disabled = (
            self.current_page >= total_pages - 1
        )

    # --------------------------------------------------------
    # Refresh zone page
    # --------------------------------------------------------

    async def refresh_zone_page(self, interaction):

        # Remove old zone selector
        for child in list(self.children):

            if isinstance(child, MapsZoneSelect):
                self.remove_item(child)

        # Add new zone selector
        self.add_item(
            MapsZoneSelect(self)
        )

        self.update_buttons()

        await interaction.response.edit_message(
            content="🗺️ **Select a zone:**",
            embeds=[],
            view=self
        )

    # --------------------------------------------------------
    # Previous
    # --------------------------------------------------------

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if self.current_page > 0:

            self.current_page -= 1

        await self.refresh_zone_page(interaction)

    # --------------------------------------------------------
    # Next
    # --------------------------------------------------------

    @discord.ui.button(
        label="Next",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        max_page = max(
            0,
            math.ceil(len(self.zones) / 25) - 1
        )

        if self.current_page < max_page:

            self.current_page += 1

        await self.refresh_zone_page(interaction)

    # --------------------------------------------------------
    # Send Privately
    # --------------------------------------------------------

    @discord.ui.button(
        label="Send Privately",
        style=discord.ButtonStyle.primary,
        row=1
    )
    async def send_privately_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not self.selected_zone:

            await interaction.response.send_message(
                "❌ Please select a zone first.",
                ephemeral=True
            )

            return

        await ensure_maps_table()

        async with db_pool.acquire() as conn:

            rows = await conn.fetch("""
                SELECT
                    zone_name,
                    map_number,
                    map_image
                FROM maps
                WHERE guild_id = $1
                  AND zone_name = $2
                ORDER BY map_number ASC
            """,
            GLOBAL_MAP_GUILD_ID,
            self.selected_zone)

        if not rows:

            await interaction.response.send_message(
                f"❌ No maps were found for **{self.selected_zone}**.",
                ephemeral=True
            )

            return

        embeds = []

        for row in rows:

            embeds.append(
                create_map_embed(
                    row["zone_name"],
                    row["map_number"],
                    row["map_image"]
                )
            )

        # ----------------------------------------------------
        # Discord allows a maximum of 10 embeds per message.
        # Send the maps in batches of 10.
        # ----------------------------------------------------

        await interaction.response.send_message(
            content=(
                f"🗺️ **{self.selected_zone}**\n"
                f"Showing {len(embeds)} map(s)."
            ),
            embeds=embeds[:10],
            ephemeral=True
        )

        remaining = embeds[10:]

        while remaining:

            batch = remaining[:10]

            remaining = remaining[10:]

            await interaction.followup.send(
                embeds=batch,
                ephemeral=True
            )

    # --------------------------------------------------------
    # Show ALL maps for selected zone
    # --------------------------------------------------------

    async def show_zone_maps(
        self,
        interaction: discord.Interaction
    ):

        if not self.selected_zone:
            return

        await ensure_maps_table()

        async with db_pool.acquire() as conn:

            rows = await conn.fetch("""
                SELECT
                    zone_name,
                    map_number,
                    map_image
                FROM maps
                WHERE guild_id = $1
                  AND zone_name = $2
                ORDER BY map_number ASC
            """,
            GLOBAL_MAP_GUILD_ID,
            self.selected_zone)

        if not rows:

            await interaction.response.send_message(
                f"❌ No maps were found for **{self.selected_zone}**.",
                ephemeral=True
            )

            return

        embeds = []

        for row in rows:

            embeds.append(
                create_map_embed(
                    row["zone_name"],
                    row["map_number"],
                    row["map_image"]
                )
            )

        # ----------------------------------------------------
        # Discord allows a maximum of 10 embeds per message.
        # ----------------------------------------------------

        await interaction.response.edit_message(
            content=(
                f"🗺️ **{self.selected_zone}**\n"
                f"Showing {len(embeds)} map(s)."
            ),
            embeds=embeds[:10],
            view=self
        )

        remaining = embeds[10:]

        while remaining:

            batch = remaining[:10]

            remaining = remaining[10:]

            await interaction.followup.send(
                embeds=batch
            )

# ============================================================
# WIKI MAP UPDATE
# ============================================================

WIKI_BASE_URL = "https://monstersandmemories.miraheze.org"
WIKI_ZONES_URL = f"{WIKI_BASE_URL}/wiki/Zones"

async def fetch_wiki_page(url):
    """
    Download a wiki page and return its HTML.
    """

    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:

        headers = {
            "User-Agent": (
                "MonstersAndMemoriesDiscordBot/1.0 "
                "(map updater)"
            )
        }

        async with session.get(
            url,
            headers=headers
        ) as response:

            response.raise_for_status()

            return await response.text()

async def get_wiki_zones():
    """
    Read the Monsters & Memories Zones page.

    The page is organized into region tables. Each region
    contains three zone categories:

        Outdoors
        Cities
        Dungeons

    Collect every article link belonging to those categories.
    """

    html = await fetch_wiki_page(WIKI_ZONES_URL)

    soup = BeautifulSoup(html, "html.parser")

    zones = []

    valid_categories = {
        "outdoors",
        "cities",
        "dungeons"
    }

    # ========================================================
    # Process each region table
    # ========================================================

    for table in soup.find_all("table"):

        # ----------------------------------------------------
        # Find every cell in this table
        # ----------------------------------------------------

        for cell in table.find_all("td"):

            category = None

            # ------------------------------------------------
            # Look for category heading inside this cell
            # ------------------------------------------------

            for bold in cell.find_all(
                ["b", "strong"]
            ):

                text = bold.get_text(
                    " ",
                    strip=True
                ).lower()

                if text in valid_categories:

                    category = text

                    break

            if category is None:
                continue

            # ------------------------------------------------
            # Get all links in this category cell
            # ------------------------------------------------

            for link in cell.find_all(
                "a",
                href=True
            ):

                href = link.get(
                    "href",
                    ""
                ).strip()

                zone_name = link.get_text(
                    " ",
                    strip=True
                )

                if not zone_name:
                    continue

                if not href.startswith("/wiki/"):
                    continue

                article_path = href.split(
                    "/wiki/",
                    1
                )[1]

                # Ignore:
                # File:
                # Category:
                # Special:
                # Template:
                # etc.
                if ":" in article_path:
                    continue

                # ------------------------------------------------
                # Build URL
                # ------------------------------------------------

                zone_url = (
                    href
                    if href.startswith("http")
                    else f"{WIKI_BASE_URL}{href}"
                )

                zones.append({
                    "name": zone_name,
                    "url": zone_url,
                    "category": category
                })

    # ========================================================
    # Remove duplicate pages
    # ========================================================

    unique_zones = {}

    for zone in zones:

        key = zone["url"].lower()

        if key not in unique_zones:

            unique_zones[key] = zone

    zones = list(
        unique_zones.values()
    )

    # ========================================================
    # Sort alphabetically
    # ========================================================

    zones.sort(
        key=lambda zone: zone["name"].lower()
    )

    # ========================================================
    # Debug output
    # ========================================================

    print(
        f"🗺️ Found {len(zones)} wiki zones."
    )

    for zone in zones:

        print(
            f"   {zone['name']} "
            f"[{zone['category'].title()}]"
        )

    return zones
    

async def get_zone_maps(zone_url):
    """
    Get every map image from a zone page.

    IMPORTANT:
    The first image on every zone page is NOT a map.
    It is a random screenshot/concept image and must always
    be skipped.

    After skipping the first image, maps are identified by
    <figure> elements containing a MediaWiki File: link.
    """

    html = await fetch_wiki_page(zone_url)

    soup = BeautifulSoup(html, "html.parser")

    maps_found = []

    # ========================================================
    # Get ALL images on the page
    # ========================================================

    all_images = soup.find_all("img")

    if not all_images:
        return []

    # ========================================================
    # First image is ALWAYS the zone screenshot.
    # Do not process it.
    # ========================================================

    first_image = all_images[0]

    print(
        f"   ⏭️ Skipping first zone image: "
        f"{first_image.get('src', 'unknown')}"
    )

    # ========================================================
    # Find every figure containing a MediaWiki File link
    # ========================================================

    for figure in soup.find_all("figure"):

        image = figure.find("img")

        if image is None:
            continue

        # ----------------------------------------------------
        # Skip the first image even if it appears inside a
        # figure.
        # ----------------------------------------------------

        if image is first_image:
            continue

        # ----------------------------------------------------
        # Find the File: link associated with this image
        # ----------------------------------------------------

        file_link = None

        for link in figure.find_all(
            "a",
            href=True
        ):

            href = link.get(
                "href",
                ""
            ).strip()

            if "/wiki/File:" in href:

                file_link = link

                break

        # Not a MediaWiki file/map figure
        if file_link is None:
            continue

        # ----------------------------------------------------
        # Get image URL
        # ----------------------------------------------------

        image_url = (
            image.get("src")
            or image.get("data-src")
        )

        if not image_url:
            continue

        # ----------------------------------------------------
        # Convert protocol-relative URLs
        # ----------------------------------------------------

        if image_url.startswith("//"):

            image_url = (
                f"https:{image_url}"
            )

        elif image_url.startswith("/"):

            image_url = (
                f"{WIKI_BASE_URL}{image_url}"
            )

        # ----------------------------------------------------
        # Get wiki File URL
        # ----------------------------------------------------

        href = file_link.get(
            "href",
            ""
        ).strip()

        if href.startswith("//"):

            wiki_file_url = (
                f"https:{href}"
            )

        elif href.startswith("/"):

            wiki_file_url = (
                f"{WIKI_BASE_URL}{href}"
            )

        elif href.startswith("http"):

            wiki_file_url = href

        else:

            continue

        # ----------------------------------------------------
        # Get filename
        # ----------------------------------------------------

        from urllib.parse import unquote

        if "/wiki/File:" in href:

            file_name = href.split(
                "/wiki/File:",
                1
            )[1]

        else:

            continue

        file_name = unquote(
            file_name
        )

        # ----------------------------------------------------
        # Get caption
        # ----------------------------------------------------

        caption = ""

        figcaption = figure.find(
            "figcaption"
        )

        if figcaption:

            caption = figcaption.get_text(
                " ",
                strip=True
            )

        maps_found.append({
            "file_name": file_name,
            "wiki_file_url": wiki_file_url,
            "image_url": image_url,
            "caption": caption
        })

    # ========================================================
    # Remove duplicate File URLs
    # ========================================================

    unique_maps = {}

    for map_data in maps_found:

        key = map_data[
            "wiki_file_url"
        ].lower()

        if key not in unique_maps:

            unique_maps[key] = map_data

    maps_found = list(
        unique_maps.values()
    )

    # ========================================================
    # Debug
    # ========================================================

    print(
        f"   🗺️ Maps found: "
        f"{len(maps_found)}"
    )

    for map_data in maps_found:

        caption = (
            map_data["caption"]
            or "No caption"
        )

        print(
            f"      • "
            f"{map_data['file_name']} "
            f"({caption})"
        )

    return maps_found


async def download_wiki_image(image_data):
    """
    Download the full-resolution wiki image.

    Converts a MediaWiki thumbnail URL into the original
    static.wikitide image URL when possible.
    """

    image_url = image_data["image_url"]

    # --------------------------------------------------------
    # Try to convert thumbnail URL to original image
    # --------------------------------------------------------

    if "/thumb/" in image_url:

        parts = image_url.split("/thumb/", 1)

        if len(parts) == 2:

            base = parts[0]

            thumb_path = parts[1]

            thumb_parts = thumb_path.split("/")

            if len(thumb_parts) >= 4:

                # Example:
                #
                # f/f7/WyrmsbaneCombined_v0.91.png/
                # 600px-WyrmsbaneCombined_v0.91.png
                #
                original_path = "/".join(
                    thumb_parts[:-1]
                )

                image_url = (
                    f"{base}/{original_path}"
                )

    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        headers = {
            "User-Agent": (
                "MonstersAndMemoriesDiscordBot/1.0 "
                "(map updater)"
            )
        }

        async with session.get(
            image_url,
            headers=headers
        ) as response:

            response.raise_for_status()

            return await response.read()


async def wiki_map_exists(
    guild_id,
    zone_name,
    wiki_file_url
):
    """
    Check whether this exact wiki map has already been
    imported for this guild and zone.
    """

    async with db_pool.acquire() as conn:

        row = await conn.fetchrow("""
            SELECT id
            FROM maps
            WHERE guild_id = $1
              AND zone_name = $2
              AND wiki_image_url = $3
            LIMIT 1
        """,
        GLOBAL_MAP_GUILD_ID,
        zone_name,
        wiki_file_url)

    return row is not None


async def get_next_map_number(
    guild_id,
    zone_name
):
    """
    Get the next available map number for a zone.
    """

    async with db_pool.acquire() as conn:

        return await conn.fetchval("""
            SELECT COALESCE(
                MAX(map_number),
                0
            ) + 1
            FROM maps
            WHERE guild_id = $1
              AND zone_name = $2
        """,
        GLOBAL_MAP_GUILD_ID,
        zone_name)


# ============================================================
# ZONE MAP UPDATE SELECT
# ============================================================

class ZoneMapUpdateSelect(discord.ui.Select):

    def __init__(self, parent_view):

        self.parent_view = parent_view

        start = self.parent_view.current_page * 25
        end = start + 25

        page_zones = (
            self.parent_view.zones[start:end]
        )

        options = []

        for zone in page_zones:

            options.append(
                discord.SelectOption(
                    label=zone,
                    value=zone
                )
            )

        super().__init__(
            placeholder="Select a zone to update",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        selected_zone = self.values[0]

        await self.parent_view.update_selected_zone(
            interaction,
            selected_zone
        )

# ============================================================
# ZONE MAP UPDATE VIEW
# ============================================================

class ZoneMapUpdateView(discord.ui.View):

    def __init__(
        self,
        interaction: discord.Interaction,
        zones
    ):

        super().__init__(timeout=900)

        self.original_interaction = interaction

        self.zones = zones

        self.current_page = 0

        self.update_zone_select()

        self.update_buttons()

    # --------------------------------------------------------
    # Zone selector
    # --------------------------------------------------------

    def update_zone_select(self):

        # Remove old selector
        for child in list(self.children):

            if isinstance(
                child,
                ZoneMapUpdateSelect
            ):

                self.remove_item(child)

        # Add current page selector
        self.add_item(
            ZoneMapUpdateSelect(self)
        )

    # --------------------------------------------------------
    # Navigation buttons
    # --------------------------------------------------------

    def update_buttons(self):

        total_pages = max(
            1,
            math.ceil(
                len(self.zones) / 25
            )
        )

        self.previous_button.disabled = (
            self.current_page <= 0
        )

        self.next_button.disabled = (
            self.current_page >= total_pages - 1
        )

    # --------------------------------------------------------
    # Refresh menu
    # --------------------------------------------------------

    async def refresh_page(
        self,
        interaction
    ):

        self.update_zone_select()

        self.update_buttons()

        total_pages = max(
            1,
            math.ceil(
                len(self.zones) / 25
            )
        )

        await interaction.response.edit_message(
            content=(
                "🗺️ **Select a zone to update:**\n\n"
                f"Page **{self.current_page + 1}** "
                f"of **{total_pages}**"
            ),
            embeds=[],
            view=self
        )

    # --------------------------------------------------------
    # Previous
    # --------------------------------------------------------

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if self.current_page > 0:

            self.current_page -= 1

        await self.refresh_page(
            interaction
        )

    # --------------------------------------------------------
    # Next
    # --------------------------------------------------------

    @discord.ui.button(
        label="Next",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        max_page = max(
            0,
            math.ceil(
                len(self.zones) / 25
            ) - 1
        )

        if self.current_page < max_page:

            self.current_page += 1

        await self.refresh_page(
            interaction
        )

    # --------------------------------------------------------
    # Update selected zone
    # --------------------------------------------------------

    async def update_selected_zone(
        self,
        interaction,
        zone_name
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        try:

            result = await update_single_zone_maps(
                interaction.guild,
                interaction.user,
                zone_name
            )

            await interaction.edit_original_response(
                content=result,
                view=None
            )

        except Exception as e:

            print(
                f"❌ Zone map update error: {e}"
            )

            import traceback

            traceback.print_exc()

            await interaction.edit_original_response(
                content=(
                    "❌ **Failed to update the zone.**\n\n"
                    f"Error: `{e}`"
                ),
                view=None
            )


# ============================================================
# UPDATE ONE ZONE
# ============================================================

async def update_single_zone_maps(
    guild,
    user,
    zone_name
):
    """
    Check one zone's wiki page for maps and add any maps
    that are missing from the database.
    """

    await ensure_maps_table()

    # ========================================================
    # Find zone URL from the Zones page
    # ========================================================

    zones = await get_wiki_zones()

    selected_zone = None

    for zone in zones:

        if zone["name"].lower() == zone_name.lower():

            selected_zone = zone

            break

    if selected_zone is None:

        return (
            f"❌ **{zone_name}** could not be found "
            f"on the wiki Zones page."
        )

    zone_name = selected_zone["name"]

    zone_url = selected_zone["url"]

    print(
        f"🗺️ Updating zone: {zone_name}"
    )

    print(
        f"🔗 {zone_url}"
    )

    # ========================================================
    # Get maps from wiki
    # ========================================================

    wiki_maps = await get_zone_maps(
        zone_url
    )

    if not wiki_maps:

        return (
            f"🗺️ **{zone_name}**\n\n"
            f"No maps were found on the wiki page."
        )

    # ========================================================
    # Get upload channel
    # ========================================================

    upload_channel = await ensure_upload_channel1(
        guild
    )

    # ========================================================
    # Statistics
    # ========================================================

    maps_found = len(wiki_maps)

    existing_maps = 0

    new_maps = 0

    failed_maps = 0

    new_map_names = []

    failed_map_names = []

    # ========================================================
    # Process every wiki map
    # ========================================================

    for map_data in wiki_maps:

        wiki_file_url = map_data[
            "wiki_file_url"
        ]

        # ----------------------------------------------------
        # Check whether this exact wiki map already exists
        # ----------------------------------------------------

        async with db_pool.acquire() as conn:

            existing = await conn.fetchrow("""
                SELECT
                    id,
                    map_number
                FROM maps
                WHERE guild_id = $1
                  AND zone_name = $2
                  AND wiki_image_url = $3
                LIMIT 1
            """,
            GLOBAL_MAP_GUILD_ID,
            zone_name,
            wiki_file_url)

        if existing:

            existing_maps += 1

            print(
                f"   ✓ Already exists: "
                f"{map_data['file_name']}"
            )

            continue

        # ----------------------------------------------------
        # New map
        # ----------------------------------------------------

        try:

            print(
                f"   🆕 New map: "
                f"{map_data['file_name']}"
            )

            # ------------------------------------------------
            # Download image
            # ------------------------------------------------

            image_bytes = (
                await download_wiki_image(
                    map_data
                )
            )

            if not image_bytes:

                raise RuntimeError(
                    "Wiki returned an empty image."
                )

            # ------------------------------------------------
            # Determine next map number
            # ------------------------------------------------

            async with db_pool.acquire() as conn:

                next_map_number = await conn.fetchval("""
                    SELECT COALESCE(
                        MAX(map_number),
                        0
                    ) + 1
                    FROM maps
                    WHERE guild_id = $1
                      AND zone_name = $2
                """,
                GLOBAL_MAP_GUILD_ID,
                zone_name)

            # ------------------------------------------------
            # Create Discord file
            # ------------------------------------------------

            import io

            file_buffer = io.BytesIO(
                image_bytes
            )

            discord_file = discord.File(
                file_buffer,
                filename=map_data["file_name"]
            )

            # ------------------------------------------------
            # Upload image
            # ------------------------------------------------

            uploaded_message = (
                await upload_channel.send(
                    file=discord_file,
                    content=(
                        f"🗺️ Map upload\n"
                        f"Zone: **{zone_name}**\n"
                        f"Map Number: "
                        f"**{next_map_number}**\n"
                        f"Wiki: "
                        f"{wiki_file_url}\n"
                        f"Source: **/zonemap_update**\n"
                        f"Updated by: "
                        f"{user.mention}"
                    )
                )
            )

            if not uploaded_message.attachments:

                raise RuntimeError(
                    "Discord did not return "
                    "an uploaded attachment."
                )

            map_url = (
                uploaded_message
                .attachments[0]
                .url
            )

            map_msg_id = (
                uploaded_message.id
            )

            # ------------------------------------------------
            # Save database record
            # ------------------------------------------------

            async with db_pool.acquire() as conn:

                await conn.execute("""
                    INSERT INTO maps (
                        guild_id,
                        zone_name,
                        map_number,
                        map_image,
                        wiki_image_url,
                        map_msg_id,
                        map_upload_guild_id,
                        map_upload_channel_id,
                        added_by,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7,
                        $8,
                        $9,
                        NOW(),
                        NOW()
                    )
                """,
                GLOBAL_MAP_GUILD_ID,
                zone_name,
                next_map_number,
                map_url,
                wiki_file_url,
                map_msg_id,
                guild.id,
                upload_channel.id,
                str(user))

            new_maps += 1

            caption = (
                map_data["caption"]
                or map_data["file_name"]
            )

            new_map_names.append(
                f"Map {next_map_number}: "
                f"{caption}"
            )

            print(
                f"   ✅ Added "
                f"{zone_name} - "
                f"Map {next_map_number}"
            )

        except Exception as e:

            failed_maps += 1

            failed_map_names.append(
                map_data["file_name"]
            )

            print(
                f"   ❌ Failed: "
                f"{map_data['file_name']} - "
                f"{e}"
            )

            import traceback

            traceback.print_exc()

    # ========================================================
    # Build result
    # ========================================================

    result = (
        f"🗺️ **Zone Map Update Complete**\n\n"
        f"**Zone:** {zone_name}\n"
        f"**Maps found on wiki:** {maps_found}\n"
        f"**Already in database:** {existing_maps}\n"
        f"**New maps added:** {new_maps}\n"
        f"**Failed:** {failed_maps}"
    )

    # --------------------------------------------------------
    # New maps
    # --------------------------------------------------------

    if new_map_names:

        result += (
            "\n\n**🆕 Maps Added:**\n"
        )

        for name in new_map_names:

            result += f"• {name}\n"

    # --------------------------------------------------------
    # Failed maps
    # --------------------------------------------------------

    if failed_map_names:

        result += (
            "\n**❌ Maps That Failed:**\n"
        )

        for name in failed_map_names:

            result += f"• {name}\n"

    # --------------------------------------------------------
    # Nothing new
    # --------------------------------------------------------

    if (
        new_maps == 0
        and failed_maps == 0
    ):

        result += (
            "\n\n✅ The database already contains "
            "all maps found on the wiki."
        )

    return result



# ============================================================
# /zonemap_update
# ============================================================

@bot.tree.command(
    name="zonemap_update",
    description="Check a specific zone for new maps."
)
async def zonemap_update(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used in a server.",
            ephemeral=True
        )

        return

    await ensure_maps_table()

    # ========================================================
    # Get zones from the GLOBAL map database
    # ========================================================

    async with db_pool.acquire() as conn:

        rows = await conn.fetch("""
            SELECT DISTINCT zone_name
            FROM maps
            WHERE guild_id = $1
              AND zone_name IS NOT NULL
              AND TRIM(zone_name) <> ''
            ORDER BY zone_name ASC
        """,
        GLOBAL_MAP_GUILD_ID)

    zones = [
        row["zone_name"]
        for row in rows
    ]

    # ========================================================
    # No zones
    # ========================================================

    if not zones:

        await interaction.response.send_message(
            (
                "❌ There are no zones in the map database "
                "for this server yet."
            ),
            ephemeral=True
        )

        return

    # ========================================================
    # Create selector
    # ========================================================

    view = ZoneMapUpdateView(
        interaction=interaction,
        zones=zones
    )

    total_pages = max(
        1,
        math.ceil(len(zones) / 25)
    )

    await interaction.response.send_message(
        (
            "🗺️ **Select a zone to update:**\n\n"
            f"Page **1** of **{total_pages}**\n"
            f"Zones available: **{len(zones)}**"
        ),
        view=view,
        ephemeral=True
    )


# ============================================================
# /mapupdate
# ============================================================

@bot.tree.command(
    name="mapupdate",
    description="Check the wiki for new zone maps."
)
async def mapupdate(
    interaction: discord.Interaction
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used in a server.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

    guild = interaction.guild

    try:

        # ----------------------------------------------------
        # Make sure the maps table exists
        # ----------------------------------------------------

        await ensure_maps_table()

        # ----------------------------------------------------
        # Get all zones from the wiki
        # ----------------------------------------------------

        zones = await get_wiki_zones()

        if not zones:

            await interaction.edit_original_response(
                content=(
                    "❌ I couldn't find any zones on the "
                    "wiki Zones page."
                )
            )

            return

        # ----------------------------------------------------
        # Get upload channel
        # ----------------------------------------------------

        upload_channel = await ensure_upload_channel1(
            guild
        )

        # ----------------------------------------------------
        # Statistics
        # ----------------------------------------------------

        zones_checked = 0
        maps_found = 0
        existing_maps = 0
        new_maps = 0
        failed_maps = 0

        new_map_names = []
        failed_map_names = []

        # ----------------------------------------------------
        # Process every zone
        # ----------------------------------------------------

        for zone in zones:

            zone_name = zone["name"]
            zone_url = zone["url"]

            zones_checked += 1

            print(
                f"🗺️ Checking zone: {zone_name}"
            )

            try:

                zone_maps = await get_zone_maps(
                    zone_url
                )

            except Exception as e:

                print(
                    f"❌ Failed to read "
                    f"{zone_name}: {e}"
                )

                continue

            maps_found += len(zone_maps)

            # ------------------------------------------------
            # Process every map on this zone page
            # ------------------------------------------------

            for map_data in zone_maps:

                wiki_file_url = (
                    map_data["wiki_file_url"]
                )

                # --------------------------------------------
                # Already imported?
                # --------------------------------------------

                if await wiki_map_exists(
                    GLOBAL_MAP_GUILD_ID,
                    zone_name,
                    wiki_file_url
                ):

                    existing_maps += 1

                    continue

                try:

                    print(
                        f"🆕 New map found: "
                        f"{zone_name} - "
                        f"{map_data['file_name']}"
                    )

                    # ----------------------------------------
                    # Download image
                    # ----------------------------------------

                    image_bytes = (
                        await download_wiki_image(
                            map_data
                        )
                    )

                    if not image_bytes:

                        raise RuntimeError(
                            "Wiki returned an empty image."
                        )

                    # ----------------------------------------
                    # Determine map number
                    # ----------------------------------------

                    next_map_number = (
                        await get_next_map_number(
                            GLOBAL_MAP_GUILD_ID,
                            zone_name
                        )
                    )

                    # ----------------------------------------
                    # Create Discord file
                    # ----------------------------------------

                    import io

                    file_buffer = io.BytesIO(
                        image_bytes
                    )

                    discord_file = discord.File(
                        file_buffer,
                        filename=map_data[
                            "file_name"
                        ]
                    )

                    # ----------------------------------------
                    # Upload to map upload channel
                    # ----------------------------------------

                    uploaded_message = (
                        await upload_channel.send(
                            file=discord_file,
                            content=(
                                f"🗺️ Map upload\n"
                                f"Zone: **{zone_name}**\n"
                                f"Map Number: "
                                f"**{next_map_number}**\n"
                                f"Wiki: "
                                f"{wiki_file_url}\n"
                                f"Source: "
                                f"**/mapupdate**"
                            )
                        )
                    )

                    if not uploaded_message.attachments:

                        raise RuntimeError(
                            "Discord did not return "
                            "an uploaded attachment."
                        )

                    map_url = (
                        uploaded_message
                        .attachments[0]
                        .url
                    )

                    map_msg_id = (
                        uploaded_message.id
                    )

                    # ----------------------------------------
                    # Save to database
                    # ----------------------------------------

                    async with db_pool.acquire() as conn:

                        await conn.execute("""
                            INSERT INTO maps (
                                guild_id,
                                zone_name,
                                map_number,
                                map_image,
                                wiki_image_url,
                                map_msg_id,
                                map_upload_guild_id,
                                map_upload_channel_id,
                                added_by,
                                created_at,
                                updated_at
                            )
                            VALUES (
                                $1,
                                $2,
                                $3,
                                $4,
                                $5,
                                $6,
                                $7,
                                $8,
                                $9,
                                NOW(),
                                NOW()
                            )
                        """,
                        GLOBAL_MAP_GUILD_ID,
                        zone_name,
                        next_map_number,
                        map_url,
                        wiki_file_url,
                        map_msg_id,
                        guild.id,
                        upload_channel.id,
                        str(interaction.user))

                    new_maps += 1

                    new_map_names.append(
                        f"{zone_name} - "
                        f"Map {next_map_number}"
                    )

                    print(
                        f"✅ Added: "
                        f"{zone_name} - "
                        f"Map {next_map_number}"
                    )

                except Exception as e:

                    failed_maps += 1

                    failed_map_names.append(
                        f"{zone_name} - "
                        f"{map_data['file_name']}"
                    )

                    print(
                        f"❌ Failed to import "
                        f"{zone_name} / "
                        f"{map_data['file_name']}: "
                        f"{e}"
                    )

                    import traceback

                    traceback.print_exc()

        # ====================================================
        # FINAL REPORT
        # ====================================================

        result = (
            "🗺️ **Map Update Complete**\n\n"
            f"**Zones checked:** {zones_checked}\n"
            f"**Maps found:** {maps_found}\n"
            f"**Existing maps:** {existing_maps}\n"
            f"**New maps added:** {new_maps}\n"
            f"**Failed:** {failed_maps}"
        )

        # ----------------------------------------------------
        # New maps
        # ----------------------------------------------------

        if new_map_names:

            result += (
                "\n\n**🆕 New Maps:**\n"
            )

            for name in new_map_names:

                result += f"• {name}\n"

        # ----------------------------------------------------
        # Failed maps
        # ----------------------------------------------------

        if failed_map_names:

            result += (
                "\n**❌ Failed Maps:**\n"
            )

            for name in failed_map_names:

                result += f"• {name}\n"

        await interaction.edit_original_response(
            content=result
        )

    except Exception as e:

        print(
            f"❌ Map update error: {e}"
        )

        import traceback

        traceback.print_exc()

        await interaction.edit_original_response(
            content=(
                "❌ **Map update failed.**\n\n"
                f"Error: `{e}`"
            )
        )


# ============================================================
# /maps
# ============================================================

@bot.tree.command(
    name="maps",
    description="Browse zone maps."
)
async def maps(interaction: discord.Interaction):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used in a server.",
            ephemeral=True
        )

        return

    await ensure_maps_table()

    async with db_pool.acquire() as conn:

        rows = await conn.fetch("""
            SELECT DISTINCT zone_name
            FROM maps
            WHERE guild_id = $1
            ORDER BY zone_name ASC
        """,
        GLOBAL_MAP_GUILD_ID)

    zones = [
        row["zone_name"]
        for row in rows
    ]

    if not zones:

        await interaction.response.send_message(
            "❌ No maps have been added yet.",
            ephemeral=True
        )

        return

    view = MapsView(
        interaction=interaction,
        zones=zones
    )

    await interaction.response.send_message(
        "🗺️ **Select a zone:**",
        view=view
    )


# ============================================================
# /mapadd
# ============================================================

@bot.tree.command(
    name="mapadd",
    description="Add a map for a zone."
)
@app_commands.describe(
    zone_name="Name of the zone",
    map_image="Upload the map image"
)
async def mapadd(
    interaction: discord.Interaction,
    zone_name: str,
    map_image: discord.Attachment
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used in a server.",
            ephemeral=True
        )

        return

    # --------------------------------------------------------
    # Validate image
    # --------------------------------------------------------

    if not map_image:

        await interaction.response.send_message(
            "❌ A map image is required.",
            ephemeral=True
        )

        return

    if not map_image.content_type:

        await interaction.response.send_message(
            "❌ The uploaded file must be an image.",
            ephemeral=True
        )

        return

    if not map_image.content_type.startswith("image/"):

        await interaction.response.send_message(
            "❌ The uploaded file must be an image.",
            ephemeral=True
        )

        return

    zone_name = zone_name.strip()

    if not zone_name:

        await interaction.response.send_message(
            "❌ Zone name is required.",
            ephemeral=True
        )

        return

    zone_name = format_item_name(zone_name)

    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

    await ensure_maps_table()

    guild = interaction.guild

    upload_channel = await ensure_upload_channel1(guild)

    uploaded_message = None

    try:

        # ----------------------------------------------------
        # Determine next map number
        # ----------------------------------------------------

        async with db_pool.acquire() as conn:

            next_map_number = await conn.fetchval("""
                SELECT COALESCE(MAX(map_number), 0) + 1
                FROM maps
                WHERE guild_id = $1
                  AND zone_name = $2
            """,
            GLOBAL_MAP_GUILD_ID,
            zone_name)

        # ----------------------------------------------------
        # Upload image to item-database-upload-log
        # ----------------------------------------------------

        uploaded_message = await upload_channel.send(
            file=await map_image.to_file(),
            content=(
                f"🗺️ Map upload\n"
                f"Zone: **{zone_name}**\n"
                f"Map Number: **{next_map_number}**\n"
                f"Uploaded by: {interaction.user.mention}"
            )
        )

        if not uploaded_message.attachments:

            raise RuntimeError(
                "The uploaded map did not contain an attachment."
            )

        map_url = uploaded_message.attachments[0].url

        map_msg_id = uploaded_message.id

        # ----------------------------------------------------
        # Save database record
        # ----------------------------------------------------

        async with db_pool.acquire() as conn:

            await conn.execute("""
                INSERT INTO maps (
                    guild_id,
                    zone_name,
                    map_number,
                    map_image,
                    map_msg_id,
                    map_upload_guild_id,
                    map_upload_channel_id,
                    added_by,
                    created_at,
                    updated_at
                )
                VALUES (
                    $1,
                    $2,
                    $3,
                    $4,
                    $5,
                    $6,
                    $7,
                    $8,
                    NOW(),
                    NOW()
                )
            """,
            GLOBAL_MAP_GUILD_ID,
            zone_name,
            next_map_number,
            map_url,
            map_msg_id,
            guild.id,
            upload_channel.id,
            str(interaction.user))

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        embed = create_map_embed(
            zone_name,
            next_map_number,
            map_url
        )

        await interaction.edit_original_response(
            content=(
                f"✅ **{zone_name} - Map {next_map_number}** "
                f"was added."
            ),
            embed=embed
        )

    except discord.Forbidden:

        if uploaded_message:

            try:
                await uploaded_message.delete()
            except Exception:
                pass

        await interaction.edit_original_response(
            content=(
                "❌ I don't have permission to upload the map "
                "to the item database upload channel."
            )
        )

    except Exception as e:

        print(f"❌ Map add error: {e}")

        import traceback
        traceback.print_exc()

        if uploaded_message:

            try:
                await uploaded_message.delete()
            except Exception as cleanup_error:

                print(
                    f"⚠️ Failed to clean up map upload: "
                    f"{cleanup_error}"
                )

        await interaction.edit_original_response(
            content=(
                f"❌ Failed to add the map.\n"
                f"Error: `{e}`"
            )
        )


# ============================================================
# MAP REMOVE CONFIRMATION VIEW
# ============================================================

class ConfirmMapRemoveView(discord.ui.View):

    def __init__(
        self,
        guild_id,
        zone_name,
        map_number
    ):

        super().__init__(timeout=60)

        # Kept for compatibility with the existing view.
        # Map data itself is always GLOBAL_MAP_GUILD_ID.
        self.guild_id = GLOBAL_MAP_GUILD_ID
        self.zone_name = zone_name
        self.map_number = map_number

    # --------------------------------------------------------
    # Confirm
    # --------------------------------------------------------

    @discord.ui.button(
        label="Confirm Remove",
        style=discord.ButtonStyle.danger
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        try:

            await ensure_maps_table()

            # ------------------------------------------------
            # Find the GLOBAL map
            # ------------------------------------------------

            async with db_pool.acquire() as conn:

                row = await conn.fetchrow("""
                    SELECT
                        id,
                        zone_name,
                        map_number,
                        map_image,
                        map_msg_id,
                        map_upload_guild_id,
                        map_upload_channel_id
                    FROM maps
                    WHERE guild_id = $1
                      AND zone_name = $2
                      AND map_number = $3
                """,
                GLOBAL_MAP_GUILD_ID,
                self.zone_name,
                self.map_number)

            if not row:

                await interaction.response.edit_message(
                    content=(
                        f"❌ **{self.zone_name} - Map "
                        f"{self.map_number}** was not found."
                    ),
                    view=None
                )

                return

            # ------------------------------------------------
            # Delete uploaded Discord image
            #
            # New global records store the exact server/channel
            # where the upload was created.
            #
            # Old records may not have those fields, so we fall
            # back to the current server's upload channel.
            # ------------------------------------------------

            image_deleted = False
            upload_channel = None

            if row["map_msg_id"]:

                try:

                    upload_guild_id = row["map_upload_guild_id"]
                    upload_channel_id = row["map_upload_channel_id"]

                    if upload_channel_id:

                        upload_channel = bot.get_channel(
                            upload_channel_id
                        )

                        if upload_channel is None:

                            upload_channel = await bot.fetch_channel(
                                upload_channel_id
                            )

                    elif upload_guild_id:

                        upload_guild = bot.get_guild(
                            upload_guild_id
                        )

                        if upload_guild is not None:

                            upload_channel = (
                                await ensure_upload_channel1(
                                    upload_guild
                                )
                            )

                    else:

                        # Old map record with no upload location.
                        upload_channel = (
                            await ensure_upload_channel1(
                                interaction.guild
                            )
                        )

                    if upload_channel is not None:

                        uploaded_message = (
                            await upload_channel.fetch_message(
                                row["map_msg_id"]
                            )
                        )

                        await uploaded_message.delete()

                        image_deleted = True

                    else:

                        print(
                            f"⚠️ Could not locate upload channel "
                            f"for map message {row['map_msg_id']}"
                        )

                except discord.NotFound:

                    # Message was already deleted.
                    image_deleted = True

                except discord.Forbidden:

                    print(
                        f"❌ Missing permission to delete "
                        f"map message {row['map_msg_id']}"
                    )

                except Exception as e:

                    print(
                        f"⚠️ Error deleting map message "
                        f"{row['map_msg_id']}: {e}"
                    )

            # ------------------------------------------------
            # Delete database record and renumber global maps
            # ------------------------------------------------

            async with db_pool.acquire() as conn:

                async with conn.transaction():

                    await conn.execute("""
                        DELETE FROM maps
                        WHERE id = $1
                    """,
                    row["id"])

                    # ----------------------------------------
                    # Get remaining maps
                    # ----------------------------------------

                    remaining_maps = await conn.fetch("""
                        SELECT id
                        FROM maps
                        WHERE guild_id = $1
                          AND zone_name = $2
                        ORDER BY map_number ASC, id ASC
                    """,
                    GLOBAL_MAP_GUILD_ID,
                    self.zone_name)

                    # ----------------------------------------
                    # Renumber them 1, 2, 3...
                    # ----------------------------------------

                    new_number = 1

                    for remaining in remaining_maps:

                        await conn.execute("""
                            UPDATE maps
                            SET map_number = $1,
                                updated_at = NOW()
                            WHERE id = $2
                        """,
                        new_number,
                        remaining["id"])

                        new_number += 1

            # ------------------------------------------------
            # Success
            # ------------------------------------------------

            if image_deleted:

                image_status = (
                    "The uploaded image was also deleted."
                )

            else:

                image_status = (
                    "⚠️ The database entry was removed, "
                    "but the uploaded image could not be deleted."
                )

            await interaction.response.edit_message(
                content=(
                    f"🗑️ **{self.zone_name} - Map "
                    f"{self.map_number}** was removed.\n\n"
                    f"{image_status}\n"
                    f"Remaining maps were automatically renumbered."
                ),
                view=None
            )

        except Exception as e:

            import traceback
            traceback.print_exc()

            try:

                await interaction.response.edit_message(
                    content=(
                        f"❌ Error removing "
                        f"**{self.zone_name} - Map "
                        f"{self.map_number}**.\n\n"
                        f"Error: `{e}`"
                    ),
                    view=None
                )

            except Exception:
                pass

    # --------------------------------------------------------
    # Cancel
    # --------------------------------------------------------

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content=(
                f"❎ Removal of **{self.zone_name} - Map "
                f"{self.map_number}** cancelled."
            ),
            view=None
        )


# ============================================================
# /mapremove
# ============================================================

@bot.tree.command(
    name="mapremove",
    description="Remove a map from a zone."
)
@app_commands.describe(
    zone_name="Name of the zone",
    map_number="Map number to remove"
)
async def mapremove(
    interaction: discord.Interaction,
    zone_name: str,
    map_number: int
):

    if interaction.guild is None:

        await interaction.response.send_message(
            "❌ This command can only be used in a server.",
            ephemeral=True
        )

        return

    zone_name = zone_name.strip()

    if not zone_name:

        await interaction.response.send_message(
            "❌ Zone name is required.",
            ephemeral=True
        )

        return

    if map_number < 1:

        await interaction.response.send_message(
            "❌ Map number must be 1 or greater.",
            ephemeral=True
        )

        return

    zone_name = format_item_name(zone_name)

    await ensure_maps_table()

    # --------------------------------------------------------
    # Verify map exists
    # --------------------------------------------------------

    async with db_pool.acquire() as conn:

        row = await conn.fetchrow("""
            SELECT
                zone_name,
                map_number
            FROM maps
            WHERE guild_id = $1
              AND zone_name = $2
              AND map_number = $3
        """,
        GLOBAL_MAP_GUILD_ID,
        zone_name,
        map_number)

    if not row:

        await interaction.response.send_message(
            (
                f"❌ No map found for "
                f"**{zone_name} - Map {map_number}**."
            ),
            ephemeral=True
        )

        return

    # --------------------------------------------------------
    # Confirmation
    # --------------------------------------------------------

    view = ConfirmMapRemoveView(
        guild_id=GLOBAL_MAP_GUILD_ID,
        zone_name=zone_name,
        map_number=map_number
    )

    await interaction.response.send_message(
        (
            f"⚠️ Are you sure you want to remove "
            f"**{zone_name} - Map {map_number}**?\n\n"
            f"The uploaded image will also be deleted.\n"
            f"Any remaining maps will be automatically renumbered."
        ),
        view=view,
        ephemeral=True
    )


# ============================================================
# ==================== END MAP SYSTEM ========================
# ============================================================



# ============================================================
# SPELLS SYSTEM
# ============================================================

SPELL_CLASS_NAMES = {
    "ARC": "Archer",
    "BRD": "Bard",
    "BST": "Beastmaster",
    "CLR": "Cleric",
    "DRU": "Druid",
    "ELE": "Elementalist",
    "ENC": "Enchanter",
    "FTR": "Fighter",
    "INQ": "Inquisitor",
    "MNK": "Monk",
    "NEC": "Necromancer",
    "PAL": "Paladin",
    "RNG": "Ranger",
    "ROG": "Rogue",
    "SHD": "Shadow Knight",
    "SHM": "Shaman",
    "SPB": "Spellblade",
    "WIZ": "Wizard",
}


# ============================================================
# SPELL DATABASE
# ============================================================

async def ensure_spells_table():
    global db_pool

    async with db_pool.acquire() as conn:

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS class_spells (
                id BIGSERIAL PRIMARY KEY,
                class_code TEXT NOT NULL,
                class_name TEXT NOT NULL,
                spell_name TEXT NOT NULL,
                level INTEGER NOT NULL,
                description TEXT,
                spell_class TEXT,
                location TEXT,
                mana TEXT,
                wiki_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Add missing columns to older versions of the table.

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS class_code TEXT
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS class_name TEXT
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS spell_name TEXT
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS level INTEGER
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS description TEXT
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS spell_class TEXT
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS location TEXT
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS mana TEXT
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS wiki_url TEXT
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP
        """)

        await conn.execute("""
            ALTER TABLE class_spells
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_class_spells_class
            ON class_spells(class_code)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_class_spells_level
            ON class_spells(level)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_class_spells_class_level
            ON class_spells(class_code, level)
        """)

    print("[SPELLS] class_spells table verified.")


def clean_spell_text(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# WIKI FETCHING
#
# DO NOT CHANGE THIS SECTION
# ============================================================

async def fetch_spell_wiki_html(url: str) -> Optional[str]:
    """
    Fetch wiki HTML using a real browser first.
    """

    print(f"[SPELLS] Opening wiki page: {url}")

    # ---------------------------------------------------------
    # METHOD 1: Playwright / Chromium
    # ---------------------------------------------------------

    try:
        async with async_playwright() as p:

            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/138.0.0.0 Safari/537.36"
                )
            )

            print(
                f"[SPELLS] Navigating to {url}"
            )

            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            if response:

                print(
                    f"[SPELLS] Playwright HTTP status: "
                    f"{response.status}"
                )

            else:

                print(
                    "[SPELLS] Playwright returned "
                    "no response object"
                )

            await page.wait_for_timeout(
                3000
            )

            html = await page.content()

            print(
                f"[SPELLS] Playwright HTML received: "
                f"{len(html) if html else 0} bytes"
            )

            title = await page.title()

            print(
                f"[SPELLS] Page title: {title}"
            )

            if html and len(html) > 1000:

                await browser.close()

                return html

            await browser.close()

    except Exception as e:

        print(
            f"[SPELLS] Playwright fetch failed: "
            f"{type(e).__name__}: {e}"
        )

        import traceback

        traceback.print_exc()

    # ---------------------------------------------------------
    # METHOD 2: aiohttp fallback
    # ---------------------------------------------------------

    try:

        print(
            "[SPELLS] Trying aiohttp fallback..."
        )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": (
                "https://monstersandmemories.miraheze.org/"
            ),
        }

        timeout = aiohttp.ClientTimeout(
            total=60
        )

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=timeout
        ) as session:

            async with session.get(
                url,
                allow_redirects=True
            ) as response:

                print(
                    f"[SPELLS] aiohttp HTTP status: "
                    f"{response.status}"
                )

                html = await response.text(
                    errors="ignore"
                )

                print(
                    f"[SPELLS] aiohttp HTML received: "
                    f"{len(html) if html else 0} bytes"
                )

                if html and len(html) > 1000:

                    return html

    except Exception as e:

        print(
            f"[SPELLS] aiohttp fetch failed: "
            f"{type(e).__name__}: {e}"
        )

    print(
        f"[SPELLS] NO HTML RECEIVED FOR: {url}"
    )

    return None


async def scrape_class_spells(class_code: str):
    """
    Scrape all abilities/spells from the class's wiki page.

    DO NOT CHANGE THE WIKI SCRAPING LOGIC.
    """

    class_name = SPELL_CLASS_NAMES.get(
        class_code
    )

    if not class_name:

        print(
            f"[SPELLS] Unknown class code: "
            f"{class_code}"
        )

        return []

    wiki_url = (
        "https://monstersandmemories.miraheze.org/wiki/"
        + class_name.replace(" ", "_")
    )

    print("")
    print("=" * 70)

    print(
        f"[SPELLS] SCRAPING "
        f"{class_code} / {class_name}"
    )

    print(
        f"[SPELLS] URL: {wiki_url}"
    )

    print("=" * 70)

    html = await fetch_spell_wiki_html(
        wiki_url
    )

    if not html:

        print(
            f"[SPELLS] No HTML received for "
            f"{class_name}"
        )

        return []

    print(
        f"[SPELLS] Successfully received "
        f"{len(html):,} bytes of HTML"
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # ---------------------------------------------------------
    # Find the Class Abilities / Spells heading
    # ---------------------------------------------------------

    abilities_heading = None
    
    heading_ids = [
        f"{class_name}_Abilities",
        f"{class_name}_Spells",
        f"{class_name}_Spells_&_Abilities",
        f"{class_name}_Songs_&_Abilities",
    ]
    
    for heading_id in heading_ids:
    
        abilities_heading = soup.find(
            "h1",
            id=heading_id
        )
    
        if abilities_heading:
            break
    
    if not abilities_heading:
    
        abilities_heading = soup.find(
            lambda tag:
                tag.name == "h1"
                and tag.get_text(
                    " ",
                    strip=True
                ).lower()
                in [
                    f"{class_name.lower()} abilities",
                    f"{class_name.lower()} spells",
                    f"{class_name.lower()} spells & abilities",
                ]
        )
    
    if not abilities_heading:
    
        print(
            f"[SPELLS] Could not find "
            f"{class_name} Spells / Abilities heading"
        )
    
        h1s = soup.find_all(
            "h1"
        )
    
        print(
            f"[SPELLS] Found {len(h1s)} H1 headings:"
        )
    
        for h1 in h1s[:20]:
    
            print(
                "   ",
                h1.get("id"),
                repr(
                    h1.get_text(
                        " ",
                        strip=True
                    )
                )
            )
    
        return []
    
    print(
        f"[SPELLS] Found spells/abilities heading: "
        f"{abilities_heading.get_text(' ', strip=True)}"
    )

    # ---------------------------------------------------------
    # Walk through level sections
    # ---------------------------------------------------------

    spells = []

    seen = set()

    current = abilities_heading

    while True:

        current = current.find_next()

        if current is None:
            break

        # Stop at next major section.
        if current.name == "h1":
            break

        if current.name != "h2":
            continue

        heading_id = current.get(
            "id",
            ""
        )

        if not heading_id.startswith(
            "Level_"
        ):
            continue

        level_match = re.search(
            r"Level[_ ]+(\d+)",
            heading_id,
            re.IGNORECASE
        )

        if not level_match:

            level_match = re.search(
                r"Level\s+(\d+)",
                current.get_text(
                    " ",
                    strip=True
                ),
                re.IGNORECASE
            )

        if not level_match:
            continue

        level = int(
            level_match.group(1)
        )

        print(
            f"[SPELLS] Found Level {level}"
        )

        # -----------------------------------------------------
        # Find table belonging to this level
        # -----------------------------------------------------

        table = None

        parent = current.parent

        if parent:

            sibling = (
                parent.find_next_sibling()
            )

            while sibling:

                if (
                    getattr(
                        sibling,
                        "name",
                        None
                    ) == "table"
                ):

                    table = sibling

                    break

                if (
                    getattr(
                        sibling,
                        "name",
                        None
                    ) == "div"
                    and sibling.find("h2")
                ):

                    break

                sibling = (
                    sibling.find_next_sibling()
                )

        # Fallback table search.
        if table is None:

            node = current

            while True:

                node = node.find_next()

                if node is None:
                    break

                if node.name == "h2":
                    break

                if node.name == "table":

                    table = node

                    break

                if node.name == "h1":
                    break

        if table is None:

            print(
                f"[SPELLS] No table found "
                f"for Level {level}"
            )

            continue

        rows = table.find_all(
            "tr"
        )

        print(
            f"[SPELLS] Level {level}: "
            f"{len(rows)} table rows"
        )

        for row in rows:

            cells = row.find_all(
                ["td", "th"]
            )

            if len(cells) < 5:
                continue

            values = [
                clean_spell_text(
                    cell.get_text(
                        " ",
                        strip=True
                    )
                )
                for cell in cells[:5]
            ]

            spell_name = values[0]
            description = values[1]
            spell_class = values[2]
            location = values[3]
            mana = values[4]

            # Skip header.
            if spell_name.lower() == "spell name":
                continue

            if not spell_name:
                continue

            # -------------------------------------------------
            # Linked spell name
            # -------------------------------------------------

            link = cells[0].find(
                "a"
            )

            if link:

                linked_name = clean_spell_text(
                    link.get_text(
                        " ",
                        strip=True
                    )
                )

                if linked_name:

                    spell_name = linked_name

            # -------------------------------------------------
            # Deduplicate
            # -------------------------------------------------

            dedupe_key = (
                level,
                spell_name.strip().lower()
            )

            if dedupe_key in seen:
                continue

            seen.add(
                dedupe_key
            )

            spells.append({
                "class_code": class_code,
                "class_name": class_name,
                "spell_name": spell_name,
                "level": level,
                "description": description,
                "spell_class": spell_class,
                "location": location,
                "mana": mana,
                "wiki_url": wiki_url,
            })

            print(
                f"[SPELLS]   Level {level}: "
                f"{spell_name}"
            )

    spells.sort(
        key=lambda x: (
            x["level"],
            x["spell_name"].lower()
        )
    )

    print("")

    print(
        f"[SPELLS] COMPLETE: "
        f"{class_name} = "
        f"{len(spells)} abilities"
    )

    print("")

    return spells


# ============================================================
# REPLACE CLASS SPELLS
# ============================================================

async def replace_class_spells(
    class_code: str,
    spells
):

    await ensure_spells_table()

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            await conn.execute(
                """
                DELETE FROM class_spells
                WHERE class_code = $1
                """,
                class_code
            )

            for spell in spells:

                await conn.execute(
                    """
                    INSERT INTO class_spells (
                        class_code,
                        class_name,
                        spell_name,
                        level,
                        description,
                        spell_class,
                        location,
                        mana,
                        wiki_url,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        $1,
                        $2,
                        $3,
                        $4,
                        $5,
                        $6,
                        $7,
                        $8,
                        $9,
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    )
                    """,
                    spell["class_code"],
                    spell["class_name"],
                    spell["spell_name"],
                    spell["level"],
                    spell["description"],
                    spell["spell_class"],
                    spell["location"],
                    spell["mana"],
                    spell["wiki_url"]
                )

    print(
        f"[SPELLS] Replaced "
        f"{len(spells)} records for "
        f"{class_code}"
    )


# ============================================================
# /WIKISPELLS CLASS SELECT
# ============================================================

class WikiSpellsClassSelect(Select):

    def __init__(self):

        options = []

        for code, name in SPELL_CLASS_NAMES.items():

            options.append(
                SelectOption(
                    label=name,
                    value=code
                )
            )

        super().__init__(
            placeholder="Select a class...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: Interaction
    ):

        class_code = self.values[0]

        class_name = SPELL_CLASS_NAMES[
            class_code
        ]

        await interaction.response.defer(
            ephemeral=True
        )

        print(
            f"[SPELLS] Starting scrape for "
            f"{class_name}"
        )

        spells = await scrape_class_spells(
            class_code
        )

        if not spells:

            await interaction.followup.send(
                (
                    f"❌ No spells or abilities "
                    f"were found for **{class_name}**."
                ),
                ephemeral=True
            )

            return

        await replace_class_spells(
            class_code,
            spells
        )

        await interaction.followup.send(
            (
                f"✅ Successfully scraped and "
                f"saved **{len(spells)}** "
                f"spells/abilities for "
                f"**{class_name}**."
            ),
            ephemeral=True
        )


class WikiSpellsClassView(View):

    def __init__(self):

        super().__init__(
            timeout=300
        )

        self.add_item(
            WikiSpellsClassSelect()
        )


# ============================================================
# /WIKISPELLS
# ============================================================

@bot.tree.command(
    name="wikispells",
    description="Scrape and update class spells from the wiki."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def wikispells_command(
    interaction: Interaction
):

    await ensure_spells_table()

    embed = discord.Embed(
        title="📚 Update Wiki Spells",
        description=(
            "Select a class to scrape its "
            "spells and abilities from the wiki.\n\n"
            "The existing database records for "
            "that class will be replaced."
        )
    )

    await interaction.response.send_message(
        embed=embed,
        view=WikiSpellsClassView(),
        ephemeral=True
    )


# ============================================================
# SPELL LEVEL RANGES
# ============================================================

SPELL_LEVEL_RANGES = [
    ("All", 1, 60),
    ("1–10", 1, 10),
    ("10–20", 10, 20),
    ("20–30", 20, 30),
    ("30–40", 30, 40),
    ("40–50", 40, 50),
    ("50–60", 50, 60),
]


# ============================================================
# SPELL CLASS DROPDOWN
# ============================================================

class SpellsClassSelect(Select):

    def __init__(
        self,
        selected_class=None
    ):

        options = []

        for code, name in SPELL_CLASS_NAMES.items():

            options.append(
                SelectOption(
                    label=name,
                    value=code,
                    default=(
                        code == selected_class
                    )
                )
            )

        super().__init__(
            placeholder="Select Class",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: Interaction
    ):

        self.view.selected_class = (
            self.values[0]
        )

        # Keep the selected class highlighted.
        for option in self.options:

            option.default = (
                option.value
                == self.view.selected_class
            )

        # Do NOT query database.
        # Do NOT display results.
        await interaction.response.edit_message(
            content=self.view.get_content(),
            embed=None,
            view=self.view
        )


# ============================================================
# SPELL LEVEL RANGE DROPDOWN
# ============================================================

class SpellsLevelSelect(Select):

    def __init__(
        self,
        selected_range="all"
    ):

        options = []

        for label, min_level, max_level in SPELL_LEVEL_RANGES:

            if label == "All":

                value = "all"

                options.append(
                    SelectOption(
                        label="All",
                        value=value,
                        default=(
                            value == selected_range
                        )
                    )
                )

            else:

                value = (
                    f"{min_level}-{max_level}"
                )

                options.append(
                    SelectOption(
                        label=f"Level {label}",
                        value=value,
                        default=(
                            value == selected_range
                        )
                    )
                )

        super().__init__(
            placeholder="All Levels",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: Interaction
    ):

        selected = self.values[0]

        self.view.selected_range = selected

        if selected == "all":

            self.view.min_level = 1
            self.view.max_level = 60
            self.view.range_name = "All Levels"

        else:

            parts = selected.split("-")

            self.view.min_level = int(
                parts[0]
            )

            self.view.max_level = int(
                parts[1]
            )

            self.view.range_name = (
                f"Levels {parts[0]}–{parts[1]}"
            )

        # Keep the selected range highlighted.
        for option in self.options:

            option.default = (
                option.value == selected
            )

        # Do NOT query database.
        # Do NOT display results.
        await interaction.response.edit_message(
            content=self.view.get_content(),
            embed=None,
            view=self.view
        )


# ============================================================
# INITIAL SPELL SELECTION VIEW
# ============================================================

class SpellsSelectionView(View):

    def __init__(
        self,
        selected_class=None,
        selected_range="all",
        public=True
    ):

        super().__init__(
            timeout=300
        )

        self.selected_class = selected_class

        self.selected_range = (
            selected_range
        )

        self.public = public

        self.min_level = 1
        self.max_level = 60

        self.range_name = "All Levels"

        if selected_range != "all":

            parts = selected_range.split("-")

            self.min_level = int(
                parts[0]
            )

            self.max_level = int(
                parts[1]
            )

            self.range_name = (
                f"Levels {parts[0]}–{parts[1]}"
            )

        # ----------------------------------------------------
        # CLASS
        # ----------------------------------------------------

        self.class_select = (
            SpellsClassSelect(
                selected_class
            )
        )

        self.add_item(
            self.class_select
        )

        # ----------------------------------------------------
        # LEVEL RANGE
        # ----------------------------------------------------

        self.level_select = (
            SpellsLevelSelect(
                selected_range
            )
        )

        self.add_item(
            self.level_select
        )

        # ----------------------------------------------------
        # VIEW
        # ----------------------------------------------------

        view_button = Button(
            label="View",
            style=discord.ButtonStyle.success
        )

        
        async def view_callback(
            interaction: Interaction
        ):
        
            if not self.selected_class:
        
                await interaction.response.send_message(
                    "Please select a class first.",
                    ephemeral=True
                )
        
                return
        
            # --------------------------------------------------------
            # Get the results.
            # --------------------------------------------------------
        
            await interaction.response.defer()
        
            spells = await get_class_spells(
                self.selected_class,
                self.min_level,
                self.max_level
            )
        
            embed = create_spells_embed(
                self.selected_class,
                spells,
                self.range_name,
                0
            )
        
            # --------------------------------------------------------
            # REPLACE THE ORIGINAL /SPELLS MESSAGE.
            #
            # Do NOT followup.send().
            # This edits the existing public selection message.
            # --------------------------------------------------------
        
            await interaction.edit_original_response(
                content=embed,
                embed=None,
                view=SpellsResultsView(
                    self.selected_class,
                    spells,
                    self.range_name,
                    0,
                    public=self.public
                )
            )

        view_button.callback = (
            view_callback
        )

        self.add_item(
            view_button
        )

        # ----------------------------------------------------
        # SEND PRIVATELY
        # ----------------------------------------------------

        if self.public:
        
            private_button = Button(
                label="Send Privately",
                style=discord.ButtonStyle.primary
            )
        
            async def private_callback(
                interaction: Interaction
            ):

                if not self.selected_class:

                    await interaction.response.send_message(
                        "Please select a class first.",
                        ephemeral=True
                    )

                    return

                await interaction.response.defer(
                    ephemeral=True
                )

                spells = await get_class_spells(
                    self.selected_class,
                    self.min_level,
                    self.max_level
                )

                embed = create_spells_embed(
                    self.selected_class,
                    spells,
                    self.range_name,
                    0
                )

                # ------------------------------------------------
                # PRIVATE RESULT
                #
                # Original selection message is untouched.
                # ------------------------------------------------

                await interaction.followup.send(
                    content=embed,
                    view=SpellsResultsView(
                        self.selected_class,
                        spells,
                        self.range_name,
                        0,
                        public=False
                    ),
                    ephemeral=True
                )

            private_button.callback = (
                private_callback
            )

            self.add_item(
                private_button
            )

    # ========================================================
    # INITIAL MESSAGE TEXT
    # ========================================================

    def get_content(self):
    
        if self.public:
    
            return (
                "📖 **Spells & Abilities**\n\n"
                "Select a class and level range, then choose "
                "**View** to post the results publicly or "
                "**Send Privately** to receive them privately."
            )
    
        return (
            "📖 **Spells & Abilities**\n\n"
            "Select a class and level range, then choose "
            "**View** to display the results."
        )


# ============================================================
# GET SPELLS FROM DATABASE
# ============================================================

async def get_class_spells(
    class_code: str,
    min_level: int = 1,
    max_level: int = 60
):

    await ensure_spells_table()

    async with db_pool.acquire() as conn:

        rows = await conn.fetch(
            """
            SELECT
                id,
                class_code,
                class_name,
                spell_name,
                level,
                description,
                spell_class,
                location,
                mana,
                wiki_url
            FROM class_spells
            WHERE class_code = $1
              AND level >= $2
              AND level <= $3
            ORDER BY
                level ASC,
                spell_name ASC
            """,
            class_code,
            min_level,
            max_level
        )

    return rows

# ============================================================
# SPELL RESULTS MESSAGE
# ============================================================

def create_spells_embed(
    class_code,
    spells,
    range_name,
    page=0
):

    class_name = SPELL_CLASS_NAMES.get(
        class_code,
        class_code
    )

    # --------------------------------------------------------
    # BUILD INDIVIDUAL SPELL ENTRIES
    # --------------------------------------------------------

    entries = []

    current_level = None

    for spell in spells:

        spell_name = spell[
            "spell_name"
        ]

        level = spell[
            "level"
        ]

        description = (
            spell["description"]
            or "No description available."
        )

        spell_class = (
            spell["spell_class"]
            or "—"
        )

        location = (
            spell["location"]
            or "—"
        )

        mana = (
            spell["mana"]
            or "—"
        )

        # ----------------------------------------------------
        # LEVEL HEADER
        # ----------------------------------------------------

        if level != current_level:

            current_level = level

            entry = (
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"**LEVEL {level}**\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
            )

        else:

            entry = ""

        # ----------------------------------------------------
        # SPELL ENTRY
        # ----------------------------------------------------

     
        entry += (
            f"**[{spell_name}](https://monstersandmemories.miraheze.org/wiki/{spell_name.replace(' ', '_')})**\n"
            f"**Description:** {description}\n"
            f"**Class:** {spell_class}  |  "
            f"**Location:** {location}  |  "
            f"**Mana:** {mana}\n\n"
        )

        entries.append(entry)

    # --------------------------------------------------------
    # BUILD PAGES UNDER DISCORD'S 2000 CHARACTER LIMIT
    # --------------------------------------------------------

    pages = []

    current_page = (
        f"📖 **{class_name} — {range_name}**\n\n"
    )

    for entry in entries:

        # Reserve room for the footer.
        test_footer = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"*Page {len(pages) + 1}/999 • "
            f"{len(spells)} total abilities*"
        )

        if (
            len(current_page)
            + len(entry)
            + len(test_footer)
            > 1900
            and current_page.strip()
            != f"📖 **{class_name} — {range_name}**"
        ):

            pages.append(
                current_page
            )

            current_page = (
                f"📖 **{class_name} — {range_name}**\n\n"
                + entry
            )

        else:

            current_page += entry

    if current_page.strip():

        pages.append(
            current_page
        )

    # --------------------------------------------------------
    # NO RESULTS
    # --------------------------------------------------------

    if not pages:

        return (
            f"📖 **{class_name} — {range_name}**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "**No Spells Found**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "No spells or abilities were found "
            "for this level range."
        )

    # --------------------------------------------------------
    # PAGE SAFETY
    # --------------------------------------------------------

    total_pages = len(pages)

    if page >= total_pages:

        page = total_pages - 1

    if page < 0:

        page = 0

    message = pages[page]

    # --------------------------------------------------------
    # FOOTER
    # --------------------------------------------------------

    message += (
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"*Page {page + 1}/{total_pages} • "
        f"{len(spells)} total abilities*"
    )

    return message


# ============================================================
# SPELL RESULTS VIEW
# ============================================================

class SpellsResultsView(View):

    def __init__(
        self,
        class_code,
        spells,
        range_name,
        page=0,
        public=True
    ):

        super().__init__(
            timeout=300
        )

        self.class_code = class_code
        self.spells = spells
        self.range_name = range_name
        self.page = page
        self.public = public

        # ----------------------------------------------------
        # CALCULATE RESULT PAGES
        # ----------------------------------------------------

        pages = []

        header = (
            f"📖 **{SPELL_CLASS_NAMES.get(class_code, class_code)} — "
            f"{range_name}**\n\n"
        )

        current_page_length = len(header)

        current_level = None

        for spell in spells:

            level = spell["level"]

            if level != current_level:

                current_level = level

                entry = (
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"**LEVEL {level}**\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                )

            else:

                entry = ""

            description = (
                spell["description"]
                or "No description available."
            )

            spell_class = (
                spell["spell_class"]
                or "—"
            )

            location = (
                spell["location"]
                or "—"
            )

            mana = (
                spell["mana"]
                or "—"
            )

            entry += (
                f"**{spell['spell_name']}**\n\n"
                f"**Description:** {description}\n\n"
                f"**Class:** {spell_class}  |  "
                f"**Location:** {location}  |  "
                f"**Mana:** {mana}\n\n"
            )

            if (
                current_page_length
                + len(entry)
                + 100
                > 1900
                and current_page_length > len(header)
            ):

                pages.append(True)

                current_page_length = (
                    len(header)
                    + len(entry)
                )

            else:

                current_page_length += len(entry)

        if current_page_length > len(header):

            pages.append(True)

        total_pages = max(
            1,
            len(pages)
        )

        # ----------------------------------------------------
        # PREVIOUS
        # ----------------------------------------------------

        previous_button = Button(
            label="Previous",
            style=discord.ButtonStyle.secondary,
            disabled=(page <= 0)
        )

        async def previous_callback(
            interaction: Interaction
        ):

            self.page -= 1

            embed = create_spells_embed(
                self.class_code,
                self.spells,
                self.range_name,
                self.page
            )

            await interaction.response.edit_message(
                content=embed,
                embed=None,
                view=SpellsResultsView(
                    self.class_code,
                    self.spells,
                    self.range_name,
                    self.page,
                    self.public
                )
            )

        previous_button.callback = (
            previous_callback
        )

        self.add_item(
            previous_button
        )

        # ----------------------------------------------------
        # NEXT
        # ----------------------------------------------------

        next_button = Button(
            label="Next",
            style=discord.ButtonStyle.secondary,
            disabled=(
                page >= total_pages - 1
            )
        )

        async def next_callback(
            interaction: Interaction
        ):

            self.page += 1

            embed = create_spells_embed(
                self.class_code,
                self.spells,
                self.range_name,
                self.page
            )

            await interaction.response.edit_message(
                content=embed,
                embed=None,
                view=SpellsResultsView(
                    self.class_code,
                    self.spells,
                    self.range_name,
                    self.page,
                    self.public
                )
            )

        next_button.callback = (
            next_callback
        )

        self.add_item(
            next_button
        )

        # ----------------------------------------------------
        # CHANGE LEVEL RANGE
        # ----------------------------------------------------

        change_level_button = Button(
            label="Change Level Range",
            style=discord.ButtonStyle.primary
        )

        async def change_level_callback(
            interaction: Interaction
        ):

            # ------------------------------------------------
            # PUBLIC RESULTS
            # ------------------------------------------------

            if self.public:

                selection_view = (
                    SpellsSelectionView(
                        self.class_code
                    )
                )

                await interaction.response.edit_message(
                    content=selection_view.get_content(),
                    embed=None,
                    view=selection_view
                )

            # ------------------------------------------------
            # PRIVATE RESULTS
            # ------------------------------------------------

            else:
            
                class_name = SPELL_CLASS_NAMES.get(
                    self.class_code,
                    self.class_code
                )
            
                content = (
                    f"📖 **{class_name} Spells & Abilities**\n\n"
                    "Select a level range."
                )
            
                await interaction.response.edit_message(
                    content=content,
                    embed=None,
                    view=SpellsPrivateLevelView(
                        self.class_code
                    )
                )

        change_level_button.callback = (
            change_level_callback
        )

        self.add_item(
            change_level_button
        )

        # ----------------------------------------------------
        # CHANGE CLASSES
        # ----------------------------------------------------

        change_class_button = Button(
            label="Change Classes",
            style=discord.ButtonStyle.primary
        )

        async def change_class_callback(
            interaction: Interaction
        ):

            # ------------------------------------------------
            # PUBLIC RESULTS
            # ------------------------------------------------

            if self.public:

                selection_view = (
                    SpellsSelectionView()
                )

                await interaction.response.edit_message(
                    content=selection_view.get_content(),
                    embed=None,
                    view=selection_view
                )

            # ------------------------------------------------
            # PRIVATE RESULTS
            # ------------------------------------------------

            else:

                selection_view = SpellsSelectionView(
                    public=False
                )
            
                await interaction.response.edit_message(
                    content=selection_view.get_content(),
                    embed=None,
                    view=selection_view
                )

        change_class_button.callback = (
            change_class_callback
        )

        self.add_item(
            change_class_button
        )


# ============================================================
# PRIVATE CLASS SELECTION
# ============================================================

class SpellsPrivateClassSelect(Select):

    def __init__(self):

        options = []

        for code, name in SPELL_CLASS_NAMES.items():

            options.append(
                SelectOption(
                    label=name,
                    value=code
                )
            )

        super().__init__(
            placeholder="Select Class",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: Interaction
    ):

        class_code = self.values[0]

        embed = discord.Embed(
            title=(
                f"📖 "
                f"{SPELL_CLASS_NAMES[class_code]} "
                f"Spells & Abilities"
            ),
            description=(
                "Select a level range."
            )
        )

        await interaction.response.edit_message(
            content=embed,
            embed=None,
            view=SpellsPrivateLevelView(
                class_code
            )
        )


class SpellsPrivateClassView(View):

    def __init__(self):

        super().__init__(
            timeout=300
        )

        self.add_item(
            SpellsPrivateClassSelect()
        )


# ============================================================
# PRIVATE LEVEL SELECTION
# ============================================================

class SpellsPrivateLevelSelect(Select):

    def __init__(
        self,
        class_code
    ):

        self.class_code = class_code

        options = []

        for label, min_level, max_level in SPELL_LEVEL_RANGES:

            if label == "All":

                options.append(
                    SelectOption(
                        label="All",
                        value="all",
                        default=True
                    )
                )

            else:

                options.append(
                    SelectOption(
                        label=f"Level {label}",
                        value=(
                            f"{min_level}-{max_level}"
                        )
                    )
                )

        super().__init__(
            placeholder="All Levels",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: Interaction
    ):

        selected = self.values[0]

        if selected == "all":

            min_level = 1
            max_level = 60
            range_name = "All Levels"

        else:

            parts = selected.split("-")

            min_level = int(
                parts[0]
            )

            max_level = int(
                parts[1]
            )

            range_name = (
                f"Levels {parts[0]}–{parts[1]}"
            )

        await interaction.response.defer(
            ephemeral=True
        )

        spells = await get_class_spells(
            self.class_code,
            min_level,
            max_level
        )

        embed = create_spells_embed(
            self.class_code,
            spells,
            range_name,
            0
        )

        await interaction.edit_original_response(
            content=embed,
            embed=None,
            view=SpellsResultsView(
                self.class_code,
                spells,
                range_name,
                0,
                public=False
            )
        )


class SpellsPrivateLevelView(View):

    def __init__(
        self,
        class_code
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            SpellsPrivateLevelSelect(
                class_code
            )
        )


# ============================================================
# /SPELLS COMMAND
# ============================================================

@bot.tree.command(
    name="spells",
    description="View class spells and abilities."
)
async def spells_command(
    interaction: Interaction
):

    await ensure_spells_table()

    view = SpellsSelectionView()

    # --------------------------------------------------------
    # PUBLIC NON-EMBEDDED INITIAL MESSAGE
    # --------------------------------------------------------

    await interaction.response.send_message(
        content=view.get_content(),
        view=view,
        ephemeral=False
    )



# ---------------- Bot Setup ----------------

@bot.event
async def on_ready():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    try:
        synced = await bot.tree.sync()
        print(f"Logged in as {bot.user}")
        print(f"Synced {len(synced)} command(s)")
        for cmd in synced:
            print(f"  - {cmd.name}")
    except Exception as e:
        print(f"Error syncing commands: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def on_error(event, *args, **kwargs):
    import traceback
    traceback.print_exc()


bot.run(TOKEN)
