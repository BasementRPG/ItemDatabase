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
ITEM_SLOTS = ["Ammo","Back","Bag","Chest","Ear","Face","Feet","Finger","Hands","Head","Legs","Neck","Primary","Range","Secondary","Shirt","Shoulders","Waist","Wrist",
              "1H Bludgeoning","2H Bludgeoning","1H Piercing","2H Piercing","1H Slashing","2H Slashing"]
ITEM_STATS = ["AGI","CHA","DEX","INT","STA","STR","WIS","HP","Mana","Hp Regeneration","Mana Regeneration","Haste","Ranged Haste","Spell Haste","SV Cold","SV Corruption","SV Disease","SV Electricity","SV Fire","SV Holy","SV Magic","SV Poison"]

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
            "• All links point to the Wiki (zones, NPCs, quests, tradeskills, recipes)\n\n"
             
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

            "🔧 **Recipe Icons:**\n\n"
            "⚒️ Crafted 💀 Dropped 💰 Bought ⛏️ Mined"
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
            # ✅ Store as a list of slots instead of single string
            self.parent_view.slot = self.values  
            
            # Keep selections highlighted
            for opt in self.options:
                opt.default = (opt.value in self.values)
            
            await interaction.response.edit_message(view=self.parent_view)
        except Exception as e:
            print(f"ERROR in SlotSelect callback: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass
              
 
class TypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Dropped", value="dropped", default=True),
            discord.SelectOption(label="Crafted", value="crafted"),
            discord.SelectOption(label="Quested", value="quested"),
            discord.SelectOption(label="All", value="all"),
        ]
        super().__init__(placeholder="Select item type", options=options, min_values=1, max_values=1)

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



class SlotStatClassSelectView(discord.ui.View):
    def __init__(self, db_pool, guild_id, added_by, item_image_url, npc_image_url, item_msg_id, npc_msg_id, upload_channel_id):
        super().__init__(timeout=900)
        self.db_pool = db_pool
        self.guild_id = guild_id
        self.added_by = added_by
        self.item_image_url = item_image_url
        self.npc_image_url = npc_image_url
        self.item_msg_id = item_msg_id
        self.npc_msg_id = npc_msg_id
        self.upload_channel_id = upload_channel_id

        self.slot = None
        self.usable_classes = []
        self.all_stats = []

        self._finalized = False
        
        self.add_item(SlotSelect(self))
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
            item_stats += f"\nStats: {', '.join(self.all_stats)}"
        
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
                origin_message=self.origin_message
               
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
    def __init__(self, db_pool, guild_id, added_by, item_image_url=None, npc_image_url=None, item_msg_id=None, npc_msg_id=None, item_stats=None, item_slot=None, upload_channel_id=None, origin_message=None):

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

        # Fields
        self.item_name = discord.ui.TextInput(label="Item Name", placeholder="Example: Flowing Black Silk Sash")
        self.zone_field = discord.ui.TextInput(
            label="Zone Name - Zone Area (Optional)",
            placeholder="Eamples: Shaded Dunes - Ashira Camp", required=False,
        )
        self.npc_name = discord.ui.TextInput(label="NPC Name", placeholder="Example: Fippy Darkpaw", required=False)

        self.npc_level = discord.ui.TextInput(
            label="NPC Level",
            placeholder="Example: 15-17 (Estimate/Optional)",
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
async def add_item_db(interaction: discord.Interaction, item_image: discord.Attachment, npc_image: Optional[discord.Attachment] = None):
    """Uploads images and opens dropdown view for slot/race/class before modal."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if not item_image:
        await interaction.edit_original_response(content=f"❌ Item image is required.",view=None)
        return

    added_by = str(interaction.user)
    guild = interaction.guild
    upload_channel = await ensure_upload_channel1(guild)

    try:
        # Upload images to the designated channel
        item_msg = await upload_channel.send(
            file=await item_image.to_file(),
            content=f"📦 Uploaded item image by {interaction.user.mention}"
        )

        npc_msg = None
        if npc_image:
            npc_msg = await upload_channel.send(
                file=await npc_image.to_file(),
                content=f"👹 Uploaded NPC image by {interaction.user.mention}"
            )


    
        # Extract URLs and message IDs for later
        item_url = item_msg.attachments[0].url
        npc_url = npc_msg.attachments[0].url if npc_msg else ""
        item_msg_id = item_msg.id
        npc_msg_id = npc_msg.id if npc_msg else None
    
        # Launch Slot/Stat/Class view
        view = SlotStatClassSelectView(
            db_pool=db_pool,
            guild_id=guild.id,
            added_by=added_by,
            item_image_url=item_url,
            npc_image_url=npc_url if npc_msg else None,
            item_msg_id=item_msg_id,
            npc_msg_id=npc_msg_id if npc_msg else None,
            upload_channel_id=upload_channel.id
        )
    
       
        sent = await interaction.followup.send(
            "Select the **Slot**, **Classes**, and **Stats** for this item:",
            view=view,
            ephemeral=True
        )

        # store the interaction message ID for the modal to edit later
        view.origin_message = sent

    
    except discord.Forbidden:
        await interaction.edit_original_response(content=f"❌ I don't have permission to upload files here.",view=None)
        return

    except Exception as e:
        # 🧹 Cleanup uploaded messages on error
        try:
            if upload_channel:
                for msg_id in (locals().get("item_msg", None), locals().get("npc_msg", None)):
                    if msg_id and isinstance(msg_id, discord.Message):
                        await msg_id.delete()
        except Exception as cleanup_err:
            print(f"⚠️ Cleanup failed after upload error: {cleanup_err}")

        await interaction.edit_original_response(content=f"❌ Upload failed: {e}",view=None)
        return




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
    type_filter:Optional[str] = "dropped",
    search_query = None,
    source_command="db",
    show_search = True
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
      # Special handling for Primary / Secondary / Range to search item_stats instead
      slot_lower = slot.lower()
      if slot_lower in ("primary", "secondary", "range"):

          where_clauses.append("(item_stats ILIKE $%d OR item_slot ILIKE $%d OR item_slot ILIKE $%d)" % (len(params)+1, len(params)+2, len(params)+3))
          params.append(f"%{slot}%")
          params.append(f"%{slot}%")
          params.append(f"%{slot}%")
      else:
          where_clauses.append("LOWER(item_slot) = LOWER($%d)" % (len(params)+1))
          params.append(slot)


    # Only this guild and global entries
    where_clauses.append("(guild_id = $%d OR guild_id IS NULL)" % (len(params)+1))
    params.append(interaction.guild.id)

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    query = f"""
        SELECT item_name, item_image, npc_image, npc_name, zone_name, zone_area,
               item_slot, item_stats, description, quest_name, crafted_name, crafting_recipe,
               npc_level, source
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
        
        # ✅ apply type filter **FIRST**
        tf = (type_filter or "dropped").lower()
        
        if tf == "dropped":
            db_rows = [r for r in db_rows if has_value(r["npc_name"])]
        elif tf == "crafted":
            db_rows = [r for r in db_rows if has_value(r["crafted_name"])]
        elif tf == "quested":
            db_rows = [r for r in db_rows if has_value(r["quest_name"])]
        # "all" = keep everything

      
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
      
              # ❌ Exclude "Skill: STA", "Skill: STR", etc.
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
                "crafted_name": row["crafted_name"] or "",
                "crafting_recipe":row["crafting_recipe"] or "",
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
        super().__init__(label="🔍 Enter Search Term", style=discord.ButtonStyle.primary)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SearchModal(self.parent_view))


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
        # stash the query back on the filter view
        self.parent_view.search_query = (self.query.value or "").strip()
        await interaction.response.send_message(
            f"✅ Search set to: `{self.parent_view.search_query or '— (cleared) —'}`",
            ephemeral=True
        )






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
                    # Replace spaces with underscores for proper wiki URL formatting
                    npc_url = linkback + name.replace(" ", "_")
                    linked_npc.append(f"[{name}]({npc_url})")
                # Join with newlines for vertical display in embed
                npc_name = " \n ".join(linked_npc)


           
            zone_name= format_item_name(item["zone_name"])
            
            item_link =f"{linkback}{item['item_name'].replace(' ', '_')}"
            zone_link = f"{linkback}{zone_name.replace(' ', '_')}"
            
            quest_link = f"{linkback}{item['quest_name'].replace(' ', '_')}"
            
            crafted_name = item["crafted_name"]

            
            crafted_index = crafted_name.find('(')
            if crafted_index != -1:
                crafted_name = crafted_name[:crafted_index]
            else:
                # If no space is found, the original string is returned
                crafted_name = crafted_name
            crafted_link = f"{linkback}{crafted_name}"

            # Show recipe if expanded
            item_key = item["item_name"]


            crafting_recipe = item.get("crafting_recipe") or ""

           
            yield_text = ""
            re_crafting_recipe = []
            
            if crafting_recipe:
                for line in crafting_recipe.split("\n"):
                    if line.lower().startswith("yield"):
                        yield_text = line.strip()
                    else:
                        re_crafting_recipe.append(line)
            
            crafting_recipe_clean = "\n".join(re_crafting_recipe)


            def recipe_with_emojis(crafting_recipe_text: str) -> str:
              if not crafting_recipe_text:
                  return crafting_recipe_text
          
              # ✅ Added " Mined": " ⛏️"
              replacements = {
                  " Crafted": " ⚒️",
                  " Dropped": " 💀",
                  " Drop": " 💀",
                  " Bought": " 💰",
                  " Vendor": " 💰",
                  " Mined": " ⛏️",
              }
          
              out_lines = []
              for line in crafting_recipe_text.split("\n"):
                  # Emoji replacements on the line
                  for key, emoji in replacements.items():
                      line = line.replace(key, emoji)
          
                  # Cut everything from "with" onward (case-insensitive)
                  low = line.lower()
                  # match ' with ' or starting with 'with '
                  if " with " in low or low.startswith("with "):
                      cut = low.find(" with ") if " with " in low else 0
                      if cut >= 0:
                          line = line[:cut].rstrip()
          
                  out_lines.append(line)
          
              return "\n".join(out_lines)
                
            display_recipe = recipe_with_emojis(crafting_recipe_clean)
           
            
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
            
            if item["item_image"] == "":
                embed.add_field(name="⚔️ Item Stats", value=item["item_stats"], inline=False)
            if item["item_image"] != "":
                embed.set_image(url=item["item_image"])
            if item["npc_image"] != "":
                embed.set_thumbnail(url=item["npc_image"])            
            if item["quest_name"] != "":
                embed.add_field(name="🧩 Related Quest", value=f"[{item['quest_name']}]({quest_link})", inline=False)
            if item["crafted_name"] != "":
                embed.add_field(name="⚒️ Crafted Item", value=f"[{crafted_name}]({crafted_link})", inline=True)
            if item["crafting_recipe"] !="":
                embed.add_field(name=f"📜 Recipe: {yield_text}", value=f"{display_recipe}", inline=True)
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
       Uses Playwright first (for JS-rendered pages), falls back to aiohttp if that fails.
    """
    base_url = "https://monstersandmemories.miraheze.org"
    category_url = f"{base_url}/wiki/Category:{slot_name}"
    items = []

    # ✅ Cache check
    if slot_name in wiki_cache:
        print(f"📦 Using cached results for {slot_name}")
        return wiki_cache[slot_name]

    print(f"🌐 Fetching {category_url} ...")

    # ✅ Ensure Chromium exists
    chromium_path = "/root/.cache/ms-playwright/chromium-1140/chrome-linux/chrome"
    if not os.path.exists(chromium_path):
        print("⚙️ Playwright Chromium not found — installing it...")
        os.system("python -m playwright install-deps && python -m playwright install chromium")

    # -----------------------------
    # 🧠 Try Playwright first
    # -----------------------------
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()

            await page.goto(category_url, timeout=60000)
            await asyncio.sleep(1.5)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")

    except Exception as e:
        print(f"⚠️ Playwright failed: {e}")
        print("🔁 Retrying with aiohttp fallback...")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(category_url, headers=headers, ssl=False) as resp:
                if resp.status != 200:
                    print(f"❌ Fallback request failed ({resp.status})")
                    return []
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")

    # -----------------------------
    # 🔎 Parse item links
    # -----------------------------
    links = soup.select("div.mw-category a")

    async with aiohttp.ClientSession() as session:
        for link in links[:25]:
            item_url = f"{base_url}{link['href']}"
            item_name = link.text.strip()

            try:
                async with session.get(item_url, ssl=False) as resp:
                    if resp.status != 200:
                        continue
                    page_html = await resp.text()

                s2 = BeautifulSoup(page_html, "html.parser")

                # --- Item Name ---
                title = s2.find("h1", id="firstHeading")
                item_name = title.text.strip() if title else name
    
                # --- Image ---
                image_url = None
                img_tag = s2.select_one(".infobox img, .pi-image img, .mainPageInnerBox img")
                if img_tag:
                    src = img_tag.get("src", "")
                    image_url = f"https:{src}" if src.startswith("//") else src
    
         
       
          
                # --- Extract NPC and Zone (more tolerant of malformed HTML) ---
             
              
                npc_name, zone_name = "", ""
                
                drops_section = s2.find("h2", id="Drops_From")
                if drops_section:
                    # The next <p> tag should hold the zone name
                    zone_tag = drops_section.find_next("p")
                    if zone_tag:
                        zone_name = zone_tag.get_text(strip=True)
                
                    # Then look for <ul><li> list of NPCs
                    npc_list = drops_section.find_next("ul")
                    if npc_list:
                        npc_links = npc_list.find_all("a")
                        if npc_links:
                            npc_name = ", ".join(a.get_text(strip=True) for a in npc_links)
                        else:
                            # Fallback: plain text <li>
                            npc_items = npc_list.find_all("li")
                            npc_name = ", ".join(li.get_text(strip=True) for li in npc_items)


              
                # --- Extract Quest (more tolerant of malformed HTML) ---
                quest_name = ""
                
                drops_section = s2.find("h2", id="Related_quests")
                if drops_section:        
                    # Then look for <ul><li> list of Quest
                    quest_list = drops_section.find_next("ul")
                    if quest_list:
                        quest_links = quest_list.find_all("a")
                        if quest_links:
                            quest_name = ", ".join(a.get_text(strip=True) for a in quest_links)
                        else:
                            # Fallback: plain text <li>
                            quest_items = quest_list.find_all("li")
                            quest_name = ", ".join(li.get_text(strip=True) for li in quest_items)            
    
               
                # --- 1️⃣ If npc_name and quest_name are the same, clear npc_name
                if npc_name.strip().lower() == quest_name.strip().lower() and npc_name:
                    npc_name = ""                


                # --- Fetch NPC details ---
                npc_image = ""
                npc_level = ""
                
                # Only proceed if npc_name exists
                if npc_name:
                    for npc in npc_name.split(","):
                        npc_clean = npc.strip().replace(" ", "_")
                        npc_url = f"https://monstersandmemories.miraheze.org/wiki/{npc_clean}"
                
                        async with session.get(npc_url, headers={"User-Agent": "Mozilla/5.0"}) as npc_resp:
                            if npc_resp.status != 200:
                                print(f"⚠️ Failed to fetch NPC page: {npc_url}")
                                continue
                
                            npc_html = await npc_resp.text()
                            npc_soup = BeautifulSoup(npc_html, "html.parser")
                
                            # --- NPC Image (inside <span typeof="mw:File">) ---
                            file_span = npc_soup.select_one('span[typeof="mw:File"] img')
                            if file_span:
                                src = file_span.get("src", "")
                                npc_image = f"https:{src}" if src.startswith("//") else src
                
                            # --- NPC Level (3rd <td> inside mobStatsBox) ---
                            mob_stats_table = npc_soup.find("table", class_="mobStatsBox")
                            if mob_stats_table:
                                tds = mob_stats_table.find_all("td")
                                if len(tds) >= 3:
                                    npc_level = tds[2].get_text(strip=True)
                
                            # (Optional) Stop after first NPC to avoid multiple fetches
                            break
                
                
               
                
                # --- Extract Crafted  ---
  
                crafted_name = ""
                crafting_recipe = ""  # final formatted block for DB
                
                crafted_section = None
                for pid in ("Player_crafted", "Player_crafter"):
                    crafted_section = s2.find("h2", id=pid)
                    if crafted_section:
                        break
                
                if crafted_section:
                    ul = crafted_section.find_next("ul")
                    if ul:
                        li = ul.find("li")
                        if li:
                            # --- Crafted name ---
                            direct_bits = []
                            for node in li.contents:
                                if isinstance(node, NavigableString):
                                    text = str(node).strip()
                                    if text:
                                        direct_bits.append(text)
                                elif getattr(node, "name", None) != "ul":
                                    text = node.get_text(" ", strip=True)
                                    if text:
                                        direct_bits.append(text)
                
                            if direct_bits:
                                crafted_name = " ".join(direct_bits)
                            else:
                                nested_ul = li.find("ul")
                                if nested_ul:
                                    nested_ul.extract()
                                crafted_name = li.get_text(" ", strip=True) or ""
                
                            # --- Yield & Station ---
                            wiki_base = "https://monstersandmemories.miraheze.org"
                            yield_qty = None
                            station_line = None
                
                            inner_ul = li.find("ul")
                            if inner_ul:
                                for sub_li in inner_ul.find_all("li", recursive=False):
                                    text = sub_li.get_text(" ", strip=True)
                                    if not text:
                                        continue
                
                                    # Yield
                                    if text.lower().startswith("yield"):
                                        m = re.search(r"x\s*(\d+)\s*$", text, flags=re.IGNORECASE)
                                        if m:
                                            yield_qty = m.group(1)
                                        else:
                                            m2 = re.search(r"(\d+)\s*$", text)
                                            yield_qty = m2.group(1) if m2 else "1"
                
                                    # Crafting station link
                                    if text.lower().startswith("in "):
                                        a = sub_li.find("a", href=True)
                                        if a:
                                            href = a["href"]
                                            if href.startswith("//"):
                                                href = "https:" + href
                                            elif href.startswith("/"):
                                                href = wiki_base + href
                                            station_name = a.get_text(" ", strip=True)
                                            station_line = f"In [{station_name}]({href}):"
                                        else:
                                            station_line = text if text.endswith(":") else (text + ":")
                
                            # --- Ingredient list (linked, unique, no nesting) ---
                            recipe_lines = []
                            dl_block = li.find_next("dl")
                            if dl_block:
                                for dd in dl_block.find_all("dd"):
                                    if dd.find("dl"):
                                        continue  # skip parents
                                    dd_text = dd.get_text(" ", strip=True)
                                    if not dd_text:
                                        continue
                
                                    qty_match = re.match(r"^x\s*(\d+)\s+", dd_text, flags=re.IGNORECASE)
                                    qty_str = None
                                    line = ""
                
                                    if qty_match:
                                        qty_str = qty_match.group(1)
                                        a = dd.find("a", href=True)
                                        if a:
                                            ingredient_name = a.get_text(" ", strip=True)
                                            href = a["href"]
                                            if href.startswith("//"):
                                                href = "https:" + href
                                            elif href.startswith("/"):
                                                href = wiki_base + href
                                            else:
                                                href = href
                                            # preserve all text after the item name
                                            tail_text = dd_text[qty_match.end():].replace(ingredient_name, "").strip()
                                            if tail_text:
                                                line = f"- x{qty_str} [{ingredient_name}]({href}) {tail_text}"
                                            else:
                                                line = f"- x{qty_str} [{ingredient_name}]({href})"
                                        else:
                                            line = f"- {dd_text}"
                                    else:
                                        a = dd.find("a", href=True)
                                        if a:
                                            ingredient_name = a.get_text(" ", strip=True)
                                            href = a["href"]
                                            if href.startswith("//"):
                                                href = "https:" + href
                                            elif href.startswith("/"):
                                                href = wiki_base + href
                                            line = f"- [{ingredient_name}]({href})"
                                        else:
                                            line = f"- {dd_text}"
                
                                    recipe_lines.append(line)
                
                            # --- Deduplicate cleanly ---
                            seen = set()
                            recipe_lines_cleaned = []
                            for line in recipe_lines:
                                if line not in seen:
                                    recipe_lines_cleaned.append(line)
                                    seen.add(line)
                
                            # --- Final save block ---
                            block_lines = []
                            if yield_qty is not None:
                                block_lines.append(f"Yield: {yield_qty}")
                            if station_line:
                                block_lines.append(station_line)
                            if recipe_lines_cleaned:
                                block_lines.extend(recipe_lines_cleaned)
                
                            crafting_recipe = "\n".join(block_lines)



               
    
    
                
                # --- Item Stats ---
                item_stats_div = s2.find("div", class_="item-stats")
                item_stats = "None listed"
                if item_stats_div:
                    lines = [line.strip() for line in item_stats_div.stripped_strings]
                    item_stats = "\n".join(lines)
    
                # --- Description ---
                desc_tag = s2.select_one("div.mw-parser-output > p")
                description = desc_tag.text.strip() if desc_tag else "No description available."
    
                def clean_case(s):
                    if not s or s == "Unknown":
                        return "Unknown"
                    return " ".join(word.capitalize() for word in s.split())
    
                items.append({
                    "item_name": format_item_name(item_name),
                    "item_image": image_url,
                    "npc_name": npc_name,
                    "zone_name": zone_name,
                    "slot_name": slot_name,
                    "item_stats": item_stats,
                    "wiki_url": item_url,
                    "description": description,
                    "quest_name": quest_name,
                    "crafted_name": crafted_name,
                    "npc_level": npc_level,
                    "npc_image": npc_image,
                    "crafting_recipe": crafting_recipe,
                    
                    
                    "source": "Wiki"
                })
                

                await asyncio.sleep(1.0)  # polite delay

            except Exception as e:
                print(f"⚠️ Failed to parse {item_url}: {e}")
                continue

    wiki_cache[slot_name] = items
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
                discord.SelectOption(label="1H Bludgeoning", value="1H Bludgeoning"),
                discord.SelectOption(label="2H Bludgeoning", value="2H Bludgeoning"),
                discord.SelectOption(label="1H Piercing", value="1H Piercing"),
                discord.SelectOption(label="2H Piercing", value="2H Piercing"),
                discord.SelectOption(label="1H Slashing", value="1H Slashing"),
                discord.SelectOption(label="2H Slashing", value="2H Slashing"),
            ]
        )
        self.slot_select.callback = self.select_slot
        self.add_item(self.slot_select)

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

        if source_command in ("db", "dbp"):
            self.add_item(TypeSelect())  # <-- your new dropdown
      
        if show_search:
            self.add_item(SearchButton(self))
        # Confirm button
        confirm_button = discord.ui.Button(label="✅ Search", style=discord.ButtonStyle.green)
        confirm_button.callback = self.confirm_selection
        self.add_item(confirm_button)

        self.value = None

    async def select_slot(self, interaction: discord.Interaction):
        self.slot = self.slot_select.values[0]
        await interaction.response.defer()

    async def select_stat(self, interaction: discord.Interaction):
        self.stat = self.stat_select.values[0] if self.stat_select.values else None
        await interaction.response.defer()
        
    async def select_classes(self, interaction: discord.Interaction):
        self.classes = self.classes_select.values[0] if self.classes_select.values else None
        await interaction.response.defer()
    
   
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
        type_filter = getattr(self, "type_filter", "dropped")
        if self.source_command in ("db", "dbp"):
            search_query = self.search_query or ""  # ✅ MAKE SURE WE PASS THE QUERY
            return await run_item_db(
                interaction,
                self.slot,
                self.stat,
                self.classes,
                getattr(self, "type_filter", "dropped"),
                search_query,
                self.source_command,  # source_command param
              
            )

        
        
        # If the handler isn’t attached, fall back to auto-detect based on command
        if self.on_submit is None:
            if hasattr(self, "source_command"):
                source = self.source_command
                if source == "wiki":
                    await run_wiki_items(interaction, self.slot, self.stat, self.classes)
                    return
                elif source == "db":
                    await run_item_db(interaction, self.slot, self.stat, self.classes, search_query, self.type_filter, self.type_filter)
                    return
                elif source == "dbp":
                    await run_item_db(interaction, self.slot, self.stat, self.classes, search_query, self.type_filter, self.type_filter)
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
                       description, quest_name, crafted_name, crafting_recipe, npc_image, npc_level
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
                            item_stats, description, crafted_name, crafting_recipe, quest_name, npc_level,
                            added_by, source
                        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,'Wiki')
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
                    item.get("crafted_name") or "",
                    item.get("crafting_recipe") or "",                  
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
                       item_slot, item_stats, description, quest_name, crafted_name, crafting_recipe,
                       npc_level, source
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
                "crafted_name": row["crafted_name"] or "",
                "crafting_recipe": row["crafting_recipe"] or "",
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
        crafted_name = item["crafted_name"]
        crafting_recipe = item["crafting_recipe"]
        crafted_index = crafted_name.find('(')
        if any(char.isdigit() for char in item["npc_name"]):
            npc_name=item["npc_name"]
    
        else:    
            npc_string= item["npc_name"]
            # Split by comma and strip spaces
            npc_name = [name.strip() for name in npc_string.split(",") if name.strip()]
            # Build full wiki links
            linked_npc = []
            for name in npc_name:
                # Replace spaces with underscores for proper wiki URL formatting
                npc_url = linkback + name.replace(" ", "_")
                linked_npc.append(f"[{name}]({npc_url})")
            # Join with newlines for vertical display in embed
            npc_name = " \n ".join(linked_npc)

        if crafted_index != -1:
            crafted_name = crafted_name[:crafted_index]
        else:
            # If no space is found, the original string is returned
            crafted_name = crafted_name
        crafted_link = f"{linkback}{crafted_name}"
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
        if item["quest_name"] != "":
            embed.add_field(name="🧩 Related Quest", value=f"[{item['quest_name']}]({quest_link})", inline=False)
        if item["crafted_name"] != "":
            embed.add_field(name="⚒️ Crafted Item", value=f"[{crafted_name}]({crafted_link})", inline=False)  

        await interaction.response.send_message(embed=embed, ephemeral=True)






@bot.tree.command(name="update_db", description="Compare existing DB items with the Wiki and update any changed fields.")
@app_commands.checks.has_permissions(administrator=True)
async def update_db(interaction: discord.Interaction):
    await interaction.response.send_message("🔍 Starting database update from Wiki... this may take a few minutes.", ephemeral=True)
    await run_update_db(interaction)

async def run_update_db(interaction: discord.Interaction):
    base_url = "https://monstersandmemories.miraheze.org/wiki"
    wiki_base = "https://monstersandmemories.miraheze.org"
    updated_count = 0
    checked_count = 0
    changes_log = []
    failed_items = []

    await interaction.followup.send("🔄 Fetching wiki data, please wait...", ephemeral=True)

    try:
        async with db_pool.acquire() as conn:
            db_items = await conn.fetch("""
                SELECT id, item_name, zone_name, zone_area, npc_name,
                       item_stats, crafted_name, crafting_recipe,
                       quest_name, npc_image, npc_level, guild_id
                FROM item_database
            """)

        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
            for db_item in db_items:
                item_name = db_item["item_name"].strip()
                item_url = f"{base_url}/{item_name.replace(' ', '_')}"
                checked_count += 1

                try:
                    async with session.get(item_url, ssl=False) as resp:
                        if resp.status != 200:
                            print(f"⚠️ Skipping missing page: {item_url}")
                            failed_items.append(item_name)
                            continue
                        html = await resp.text()
                except Exception as e:
                    print(f"⚠️ Error fetching {item_name}: {e}")
                    failed_items.append(item_name)
                    continue

                soup = BeautifulSoup(html, "html.parser")

                # --- Drop Info ---
                npc_name, zone_name = "", ""
                if (drops_section := soup.find("h2", id="Drops_From")):
                    zone_tag = drops_section.find_next("p")
                    if zone_tag:
                        zone_name = zone_tag.get_text(strip=True)

                    npc_list = drops_section.find_next("ul")
                    if npc_list:
                        npc_links = npc_list.find_all("a")
                        npc_name = ", ".join(a.get_text(strip=True) for a in npc_links) if npc_links else \
                                    ", ".join(li.get_text(strip=True) for li in npc_list.find_all("li"))

                # --- Quest Info ---
                quest_name = ""
                if (quest_section := soup.find("h2", id="Related_quests")):
                    quest_list = quest_section.find_next("ul")
                    if quest_list:
                        quest_links = quest_list.find_all("a")
                        quest_name = ", ".join(a.get_text(strip=True) for a in quest_links) if quest_links else \
                                     ", ".join(li.get_text(strip=True) for li in quest_list.find_all("li"))

                if npc_name.strip().lower() == quest_name.strip().lower():
                    npc_name = ""

                # --- NPC Details ---
                new_npc_image = ""
                npc_level = ""
                if npc_name:
                    first_npc = npc_name.split(",")[0].strip().replace(" ", "_")
                    npc_url = f"{wiki_base}/wiki/{first_npc}"
                    try:
                        async with session.get(npc_url, ssl=False) as npc_resp:
                            if npc_resp.status == 200:
                                npc_html = await npc_resp.text()
                                npc_soup = BeautifulSoup(npc_html, "html.parser")

                                file_span = npc_soup.select_one('span[typeof="mw:File"] img')
                                if file_span:
                                    src = file_span.get("src", "")
                                    new_npc_image = f"https:{src}" if src.startswith("//") else src

                                mob_stats = npc_soup.find("table", class_="mobStatsBox")
                                if mob_stats:
                                    tds = mob_stats.find_all("td")
                                    if len(tds) >= 3:
                                        npc_level = tds[2].get_text(strip=True)
                    except Exception as e:
                        print(f"⚠️ Failed NPC fetch {npc_url}: {e}")

           
                # --- Crafted Item ---
      
  
                crafted_name = ""
                crafting_recipe = ""  # final formatted block for DB
                
                crafted_section = None
                for pid in ("Player_crafted", "Player_crafter"):
                    crafted_section = soup.find("h2", id=pid)
                    if crafted_section:
                        break
                
                if crafted_section:
                    ul = crafted_section.find_next("ul")
                    if ul:
                        li = ul.find("li")
                        if li:
                            # --- Crafted name ---
                            direct_bits = []
                            for node in li.contents:
                                if isinstance(node, NavigableString):
                                    text = str(node).strip()
                                    if text:
                                        direct_bits.append(text)
                                elif getattr(node, "name", None) != "ul":
                                    text = node.get_text(" ", strip=True)
                                    if text:
                                        direct_bits.append(text)
                
                            if direct_bits:
                                crafted_name = " ".join(direct_bits)
                            else:
                                nested_ul = li.find("ul")
                                if nested_ul:
                                    nested_ul.extract()
                                crafted_name = li.get_text(" ", strip=True) or ""
                
                            # --- Yield & Station ---
                            wiki_base = "https://monstersandmemories.miraheze.org"
                            yield_qty = None
                            station_line = None
                
                            inner_ul = li.find("ul")
                            if inner_ul:
                                for sub_li in inner_ul.find_all("li", recursive=False):
                                    text = sub_li.get_text(" ", strip=True)
                                    if not text:
                                        continue
                
                                    # Yield
                                    if text.lower().startswith("yield"):
                                        m = re.search(r"x\s*(\d+)\s*$", text, flags=re.IGNORECASE)
                                        if m:
                                            yield_qty = m.group(1)
                                        else:
                                            m2 = re.search(r"(\d+)\s*$", text)
                                            yield_qty = m2.group(1) if m2 else "1"
                
                                    # Crafting station link
                                    if text.lower().startswith("in "):
                                        a = sub_li.find("a", href=True)
                                        if a:
                                            href = a["href"]
                                            if href.startswith("//"):
                                                href = "https:" + href
                                            elif href.startswith("/"):
                                                href = wiki_base + href
                                            station_name = a.get_text(" ", strip=True)
                                            station_line = f"In [{station_name}]({href}):"
                                        else:
                                            station_line = text if text.endswith(":") else (text + ":")
                
                            # --- Ingredient list (linked, unique, no nesting) ---
                            recipe_lines = []
                            dl_block = li.find_next("dl")
                            if dl_block:
                                for dd in dl_block.find_all("dd"):
                                    if dd.find("dl"):
                                        continue  # skip parents
                                    dd_text = dd.get_text(" ", strip=True)
                                    if not dd_text:
                                        continue
                
                                    qty_match = re.match(r"^x\s*(\d+)\s+", dd_text, flags=re.IGNORECASE)
                                    qty_str = None
                                    line = ""
                
                                    if qty_match:
                                        qty_str = qty_match.group(1)
                                        a = dd.find("a", href=True)
                                        if a:
                                            ingredient_name = a.get_text(" ", strip=True)
                                            href = a["href"]
                                            if href.startswith("//"):
                                                href = "https:" + href
                                            elif href.startswith("/"):
                                                href = wiki_base + href
                                            else:
                                                href = href
                                            # preserve all text after the item name
                                            tail_text = dd_text[qty_match.end():].replace(ingredient_name, "").strip()
                                            if tail_text:
                                                line = f"- x{qty_str} [{ingredient_name}]({href}) {tail_text}"
                                            else:
                                                line = f"- x{qty_str} [{ingredient_name}]({href})"
                                        else:
                                            line = f"- {dd_text}"
                                    else:
                                        a = dd.find("a", href=True)
                                        if a:
                                            ingredient_name = a.get_text(" ", strip=True)
                                            href = a["href"]
                                            if href.startswith("//"):
                                                href = "https:" + href
                                            elif href.startswith("/"):
                                                href = wiki_base + href
                                            line = f"- [{ingredient_name}]({href})"
                                        else:
                                            line = f"- {dd_text}"
                
                                    recipe_lines.append(line)
                
                            # --- Deduplicate cleanly ---
                            seen = set()
                            recipe_lines_cleaned = []
                            for line in recipe_lines:
                                if line not in seen:
                                    recipe_lines_cleaned.append(line)
                                    seen.add(line)
                
                            # --- Final save block ---
                            block_lines = []
                            if yield_qty is not None:
                                block_lines.append(f"Yield: {yield_qty}")
                            if station_line:
                                block_lines.append(station_line)
                            if recipe_lines_cleaned:
                                block_lines.extend(recipe_lines_cleaned)
                
                            crafting_recipe = "\n".join(block_lines)


                   # --- Item Stats ---
                item_stats_div = soup.find("div", class_="item-stats")
                item_stats = "None listed"
                if item_stats_div:
                    lines = [line.strip() for line in item_stats_div.stripped_strings]
                    item_stats = "\n".join(lines)
              
                # --- Swap zone <-> npc if number in zone
                if any(char.isdigit() for char in zone_name):
                    npc_name, zone_name = zone_name, ""

                # --- Detect changes ---
                changes = {}
                def maybe_update(key, new_value):
                    if new_value and new_value != db_item[key]:
                        changes[key] = new_value

                maybe_update("zone_name", zone_name)
                maybe_update("npc_name", npc_name)
                maybe_update("item_stats", item_stats)
                maybe_update("crafted_name", crafted_name)
                maybe_update("crafting_recipe", crafting_recipe)
                maybe_update("quest_name", quest_name)
                maybe_update("npc_level", npc_level)

                current_img = db_item["npc_image"] or ""
                if new_npc_image and not current_img.startswith("https://cdn.discordapp.com/"):
                    maybe_update("npc_image", new_npc_image)

                # --- Apply updates ---
                if changes:
                    updated_count += 1
                    changes_log.append(f"🛠️ `{item_name}` → {', '.join(changes.keys())}")
                    set_clause = ", ".join([f"{col} = ${i+3}" for i, col in enumerate(changes.keys())])
                    values = list(changes.values())

                    async with db_pool.acquire() as conn:
                        # Update both global and guild versions
                        await conn.execute(
                            f"""
                            UPDATE item_database
                            SET {set_clause}
                            WHERE LOWER(item_name) = LOWER($1)
                              AND (guild_id = $2 OR guild_id IS NULL)
                            """,
                            item_name, db_item["guild_id"] or interaction.guild.id, *values
                        )

                await asyncio.sleep(0.3)  # ✅ polite wiki crawl delay

        summary = (
            f"✅ Wiki sync complete!\n"
            f"🔍 Checked: `{checked_count}` items\n"
            f"🛠️ Updated: `{updated_count}` items\n"
        )
        if changes_log:
            summary += "\n\n" + "\n".join(changes_log[:20])
            if len(changes_log) > 20:
                summary += f"\n...and {len(changes_log) - 20} more changes."

        await interaction.followup.send(summary, ephemeral=True)

    except Exception as e:
        print(f"❌ Wiki update failed: {e}")
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)




# ============================================================
# ====================== MAP SYSTEM ==========================
# ============================================================

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
        # Give old maps map number 1
        # ----------------------------------------------------
        await conn.execute("""
            UPDATE maps
            SET map_number = 1
            WHERE map_number IS NULL
        """)

        # ----------------------------------------------------
        # Remove old one-map-per-zone constraint
        # ----------------------------------------------------
        await conn.execute("""
            ALTER TABLE maps
            DROP CONSTRAINT IF EXISTS maps_guild_id_zone_name_key
        """)

        # ----------------------------------------------------
        # Make map numbers unique per guild/zone
        # ----------------------------------------------------
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            maps_guild_zone_number_unique
            ON maps (guild_id, zone_name, map_number)
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
                WHERE (
                    guild_id = $1
                    OR guild_id = 1
                )
                  AND zone_name = $2
                ORDER BY map_number ASC
            """,
            interaction.guild.id,
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
                WHERE (
                    guild_id = $1
                    OR guild_id = 1
                )
                  AND zone_name = $2
                ORDER BY map_number ASC
            """,
            interaction.guild.id,
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
               OR guild_id = 1
            ORDER BY zone_name ASC
        """,
        interaction.guild.id)

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
            guild.id,
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
                    NOW(),
                    NOW()
                )
            """,
            guild.id,
            zone_name,
            next_map_number,
            map_url,
            map_msg_id,
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

        self.guild_id = guild_id
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
            # Find map
            # ------------------------------------------------

            async with db_pool.acquire() as conn:

                row = await conn.fetchrow("""
                    SELECT
                        id,
                        zone_name,
                        map_number,
                        map_image,
                        map_msg_id
                    FROM maps
                    WHERE (
                        guild_id = $1
                        OR guild_id = 1
                    )
                      AND zone_name = $2
                      AND map_number = $3
                """,
                self.guild_id,
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
            # ------------------------------------------------

            upload_channel = await ensure_upload_channel1(
                interaction.guild
            )

            image_deleted = False

            if row["map_msg_id"]:

                try:

                    uploaded_message = (
                        await upload_channel.fetch_message(
                            row["map_msg_id"]
                        )
                    )

                    await uploaded_message.delete()

                    image_deleted = True

                except discord.NotFound:

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
            # Delete database record and renumber maps
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
                    self.guild_id,
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
            WHERE (
                guild_id = $1
                OR guild_id = 1
            )
              AND zone_name = $2
              AND map_number = $3
        """,
        interaction.guild.id,
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
        guild_id=interaction.guild.id,
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
