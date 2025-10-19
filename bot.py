import os
import math
import discord
from discord import app_commands, Interaction
from discord.ext import commands
from discord.ui import Modal, TextInput
from datetime import datetime
import asyncpg 
from discord.ui import View, Button
from discord.ui import View, Select
from discord import SelectOption, Interaction



import aiohttp
import io

active_views = {}

print("discord.py version:", discord.__version__)


TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")


intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)
db_pool: asyncpg.Pool = None

# ---------- DB Helpers ----------


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






async def add_item_db_bank(guild_id, upload_message_id, name, image=None, donated_by=None, qty=None, added_by=None, ):
    created_at1 = datetime.utcnow()
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO inventory1 (guild_id, upload_message_id, name, image, donated_by, qty, added_by, created_at1)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ''', guild_id, upload_message_id, name, image, donated_by, qty, added_by, created_at1)


async def get_all_items(guild_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, image, donated_by FROM inventory1 WHERE guild_id=$1 ORDER BY id", guild_id)
    return rows

async def get_item_by_name(guild_id, name):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM inventory1 WHERE guild_id=$1 AND name=$2", guild_id, name)
    return row

async def update_item_db(guild_id, item_id, **fields):
    """
    Update an item in the database.
    Only updates the fields provided.
    Automatically updates updated_at.
    """
    if not fields:
        return  # nothing to update

    set_clauses = []
    values = []
    i = 1
    for key, value in fields.items():
        set_clauses.append(f"{key}=${i}")
        values.append(value)
        i += 1
 
    values.append(guild_id)
    values.append(item_id)

    sql = f"""
        UPDATE inventory1
        SET {', '.join(set_clauses)}
        WHERE guild_id=${i} AND id=${i+1}
    """
    async with db_pool.acquire() as conn:
        await conn.execute(sql, *values)



async def delete_item_db(guild_id, item_id):
    # Reduce qty by 1
    item = await db.fetch_one("SELECT qty FROM items WHERE guild_id=? AND id=?", (guild_id, item_id))
    if not item:
        return
    if item['qty'] > 1:
        await db.execute("UPDATE items SET qty = qty - 1 WHERE id = ?", (item_id,))
    else:
        await db.execute("DELETE FROM items WHERE id = ?", (item_id,))





# ---------- UI Components ----------



#-----IMAGE UPLOAD ----

class ImageDetailsModal(discord.ui.Modal):
    def __init__(self, interaction: discord.Interaction, image_url: str = None, item_row: dict = None):
        """
        Modal for adding or editing an image item.
        """
        super().__init__(title="Image Item Details")
        self.interaction = interaction
        self.item_row = item_row
        self.is_edit = item_row is not None
        self.guild_id = interaction.guild.id
        self.image_url = image_url

        # Always define item_id, even if None
        self.item_id = item_row['id'] if self.is_edit else None

        # Default values
        default_name = item_row['name'] if self.is_edit else ""
        default_donor = item_row.get('donated_by') if self.is_edit else ""

        # Item Name input
        self.item_name = discord.ui.TextInput(
            label="Item Name",
            placeholder="Example: Flowing Black Silk Sash",
            default=default_name,
            required=True
        )
        self.add_item(self.item_name)

        # Donated By input
        self.donated_by = discord.ui.TextInput(
            label="Donated By",
            placeholder="Example: Thieron or Raid",
            default=default_donor,
            required=False
        )
        self.add_item(self.donated_by)

    async def on_submit(self, modal_interaction: discord.Interaction):
        item_name = self.item_name.value
        donated_by = self.donated_by.value or "Anonymous"
        added_by = str(modal_interaction.user)

        # Ensure upload channel exists
        upload_channel = await ensure_upload_channel(modal_interaction.guild)

        # Upload the image if provided
        if self.image_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.image_url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        file = discord.File(io.BytesIO(data), filename=f"{item_name}.png")
                        message = await upload_channel.send(content=f"Uploaded by {added_by}", file=file)
                        self.image_url = message.attachments[0].url
                    else:
                        await modal_interaction.response.send_message(
                            "❌ Failed to download the image.", ephemeral=True
                        )
                        return
        elif self.is_edit and self.item_row.get("image"):
            self.image_url = self.item_row["image"]
        else:
            await modal_interaction.response.send_message(
                "❌ No image provided. Please attach an image.", ephemeral=True
            )
            return

        # Save to database
        if self.is_edit:
            await update_item_db(
                guild_id=self.guild_id,
                item_id=self.item_id,
                name=item_name,
                donated_by=donated_by,
                image=self.image_url,
                added_by=added_by
            )
            await modal_interaction.response.send_message(f"✅ Updated **{item_name}**.", ephemeral=True)
        else:
            await add_item_db_bank(
                guild_id=self.guild_id,
                name=item_name,
                image=self.image_url,
                donated_by=donated_by,
                qty=1,
                added_by=added_by,
                upload_message_id=message.id
            )
            await modal_interaction.response.send_message(f"✅ Image item **{item_name}** added!", ephemeral=True)


class EditItemModal(discord.ui.Modal):
    def __init__(self, interaction: discord.Interaction, item_row: dict):
        """
        Modal to edit an existing item.
        """
        super().__init__(title="Edit Item Details")
        self.interaction = interaction
        self.item_row = item_row
        self.guild_id = item_row['guild_id']
        self.item_id = item_row['id']

        # Pre-fill the current values
        default_name = item_row['name']
        default_donor = item_row.get('donated_by') or "Anonymous"

        # Item Name
        self.item_name = discord.ui.TextInput(
            label="Item Name",
            placeholder="Example: Flowing Black Silk Sash",
            default=default_name,
            required=True
        )
        self.add_item(self.item_name)

        # Donated By
        self.donated_by = discord.ui.TextInput(
            label="Donated By",
            placeholder="Example: Thieron or Raid",
            default=default_donor,
            required=False
        )
        self.add_item(self.donated_by)

    async def on_submit(self, modal_interaction: discord.Interaction):
        item_name = self.item_name.value
        donated_by = self.donated_by.value or "Anonymous"
        added_by = str(modal_interaction.user)

        # Update DB without touching the image
        await update_item_db(
            guild_id=self.guild_id,
            item_id=self.item_id,
            name=item_name,
            donated_by=donated_by,
            image=self.item_row['image'],  # keep existing image
            added_by=added_by
        )

        await modal_interaction.response.send_message(
            f"✅ Updated **{item_name}**.", ephemeral=True
        )



class ItemHistoryModal(discord.ui.Modal):
    def __init__(self, guild_id, items):
        super().__init__(title="📜 Item Donation History")
        self.guild_id = guild_id
        self.items = items

        # Calculate total items donated
        total_donated = len(items)
        total_text = str(total_donated)

        # Build history string
        history_text = ""
        for i in items:
            donor = i['donated_by'] or "Anonymous"
            name = i['name']
            date = i['created_at1'].strftime("%m-%d-%y") if i['created_at1'] else "Unknown"
            history_text += f"{donor} | {name} | {date}\n"

        # Truncate if too long
        if len(history_text) > 4000:
            history_text = history_text[:3990] + "\n…"

        # Total Items Donated field
        self.total_input = discord.ui.TextInput(
            label="📦 Total Items Donated",
            style=discord.TextStyle.short,
            default=total_text,
            required=False
        )
        self.total_input.disabled = True
        self.add_item(self.total_input)

        # Donation History field
        self.history_input = discord.ui.TextInput(
            label="🧾 Items Donated History (Recent)",
            style=discord.TextStyle.paragraph,
            default=history_text or "No items donated yet.",
            required=False
        )
        self.history_input.disabled = True
        self.add_item(self.history_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Closed.", ephemeral=True)


class ItemHistoryButton(discord.ui.Button):
    def __init__(self, db_pool):
        super().__init__(label="Donation History", style=discord.ButtonStyle.secondary)
        self.db_pool = db_pool

    async def callback(self, interaction: discord.Interaction):
        async with self.db_pool.acquire() as conn:
            items = await conn.fetch(
                "SELECT name, donated_by, created_at1 FROM inventory1 WHERE guild_id=$1 ORDER BY created_at1 DESC",
                interaction.guild.id
            )

        if not items:
            await interaction.response.send_message("No items found for this guild.", ephemeral=True)
            return

        modal = ItemHistoryModal(interaction.guild.id, items)
        await interaction.response.send_modal(modal)


class RemovalHistoryModal(discord.ui.Modal):
    def __init__(self, guild_id, items):
        super().__init__(title="📜 Item Removal History")
        self.guild_id = guild_id
        self.items = items


        # Calculate total items removed
        total_removed = len(items)
        total_text = str(total_removed)

        # Build history string
        history_text = ""
        for i in items:
            name = i['name']
            removed_by = i['removed_by']
            removed_reason = i['removed_reason']
            date = i['removed_at'].strftime("%m-%d-%y") if i['removed_at'] else "Unknown"
            history_text += f"{name} | {removed_by} | {date}\n {removed_reason} \n"

        # Truncate if too long
        if len(history_text) > 4000:
            history_text = history_text[:3990] + "\n…"

        # Total Items Removed field
        self.total_input = discord.ui.TextInput(
            label="📦 Total Removed Donated",
            style=discord.TextStyle.short,
            default=total_text,
            required=False
        )
        self.total_input.disabled = True
        self.add_item(self.total_input)

        # Removal History field
        self.history_input = discord.ui.TextInput(
            label="🧾 Items Removed History (Recent)",
            style=discord.TextStyle.paragraph,
            default=history_text or "No items removed yet.",
            required=False
        )
        self.history_input.disabled = True
        self.add_item(self.history_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Closed.", ephemeral=True)




class RemovalHistoryButton(discord.ui.Button):
    def __init__(self, db_pool):
        super().__init__(label="Removal History", style=discord.ButtonStyle.secondary)
        self.db_pool = db_pool

    async def callback(self, interaction: discord.Interaction):
        async with self.db_pool.acquire() as conn:
            items = await conn.fetch(
                "SELECT name, removed_by, removed_at, removed_reason FROM inventory1 WHERE guild_id=$1 AND qty=0 ORDER BY removed_at DESC",
                interaction.guild.id
            )

        if not items:
            await interaction.response.send_message("No items found for this guild.", ephemeral=True)
            return

        modal = RemovalHistoryModal(interaction.guild.id, items)
        await interaction.response.send_modal(modal)




class RemoveItemModal(discord.ui.Modal):
    def __init__(self, item, db_pool):
        super().__init__(title="Remove Item")
        self.item = item
        self.db_pool = db_pool

        self.reason = discord.ui.TextInput(
            label="Reason for Removal",
            style=discord.TextStyle.paragraph,
            placeholder="Explain why this item is being removed...",
            required=True
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            async with self.db_pool.acquire() as conn:
                # 🔹 Try deleting uploaded image message if it exists
                if self.item.get("upload_message_id"):
                    upload_channel = discord.utils.get(
                        interaction.guild.text_channels, name="guild-bank-upload-log"
                    )
                    if upload_channel:
                        try:
                            msg = await upload_channel.fetch_message(self.item["upload_message_id"])
                            await msg.delete()
                        except discord.NotFound:
                            pass
                        except Exception as e:
                            print(f"Failed to delete uploaded image: {e}")

                # 🔹 Update DB record
                await conn.execute(
                    """
                    UPDATE inventory1
                    SET image=NULL,
                        upload_message_id=NULL,
                        qty=0,
                        removed_by=$2,
                        removed_reason=$3,
                        removed_at=NOW()
                    WHERE id=$1
                    """,
                    self.item["id"],
                    str(interaction.user),
                    self.reason.value
                )

            await interaction.response.send_message(
                f"🗑️ **{self.item['name']}** was removed from the Guild Bank.\n"
                f"📝 Reason: {self.reason.value}",
                ephemeral=True
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.response.send_message(f"❌ Error removing item: {e}", ephemeral=True)





@bot.tree.command(name="view_bank", description="View all image items in the guild bank.")
async def view_bank(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    # Fetch all items with qty=1 for this guild
    async with db_pool.acquire() as conn:
        items = await conn.fetch(
            "SELECT name, image, donated_by FROM inventory1 WHERE guild_id=$1 AND qty=1 ORDER BY name ASC",
            guild_id
        )

    if not items:
        await interaction.response.send_message("The guild bank is empty.", ephemeral=True)
        return

    embeds = []
    for item in items:
        embed = discord.Embed()
        embed.set_image(url=item["image"])
        if item.get("donated_by"):
            embed.set_footer(text=f"Donated by: {item['donated_by']} | {item['name']}")
        embeds.append(embed)

    # Discord limits to 10 embeds per message; send in chunks if needed
    for i in range(0, len(embeds), 10):
        await interaction.channel.send(embeds=embeds[i:i+10])

    await interaction.response.send_message("✅ Guild bank items displayed.", ephemeral=True)


# ---------- /add_item Command ----------

@bot.tree.command(name="add_bank", description="Add a new image item to the guild bank (image required).")
@app_commands.describe(image="Upload an image of the item.")
async def add_item(interaction: discord.Interaction, image: discord.Attachment):
    if not image:
        await interaction.response.send_message("❌ You must upload an image of the item.", ephemeral=True)
        return

    # Open modal with image URL
    await interaction.response.send_modal(ImageDetailsModal(interaction, image_url=image.url))


@bot.tree.command(name="edit_bank", description="Edit an existing item by name.")
@app_commands.describe(item_name="Name of the item to edit.")
async def edit_item(interaction: discord.Interaction, item_name: str):
    guild_id = interaction.guild.id
    # Fetch item from DB by name and guild
    item_row = await get_item_by_name(guild_id, item_name)
    if not item_row:
        await interaction.response.send_message(
            f"❌ No item named '{name}' found.", ephemeral=True
        )
        return

    await interaction.response.send_modal(EditItemModal(interaction, item_row=item_row))

@bot.tree.command(name="remove_bank", description="Remove an item from the guild bank by name.")
@app_commands.describe(item_name="Name of the item to remove.")
async def remove_item(interaction: discord.Interaction, item_name: str):
    guild_id = interaction.guild.id

    # Fetch the full item from DB by name + guild
    async with db_pool.acquire() as conn:
        item_row = await conn.fetchrow(
            "SELECT * FROM inventory1 WHERE guild_id=$1 AND name=$2 AND qty=1",
            guild_id,
            item_name
        )

    if not item_row:
        await interaction.response.send_message(
            f"❌ No item named '{name}' found.", ephemeral=True
        )
        return

    # Open the modal with the full item
    await interaction.response.send_modal(RemoveItemModal(item_row, db_pool))







@bot.tree.command(name="view_bankhistory", description="View guild item donation stats.")
async def view_itemhistory(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    async with db_pool.acquire() as conn:
        # Total donated (all items ever)
        total_donated = await conn.fetchval(
            "SELECT COUNT(*) FROM inventory1 WHERE guild_id = $1;",
            guild_id
        )

        # Total currently in bank
        total_in_bank = await conn.fetchval(
            "SELECT COUNT(*) FROM inventory1 WHERE guild_id = $1 AND qty = 1;",
            guild_id
        )

    # Embed summary
    embed = discord.Embed(
        title="📜 Item Donation Records",
        description=(
            f"**Total Items Donated:** {total_donated}\n"
            f"**Currently in Bank:** {total_in_bank}"
        ),
        color=discord.Color.green()
    )

    # Add the Item History button
    view = discord.ui.View()
    view.add_item(ItemHistoryButton(db_pool))

    view.add_item(RemovalHistoryButton(db_pool))

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)










# ---------- Funds DB Helpers ----------


# ----------------- Currency Helpers -----------------
# Convert from 4-part currency to total copper
def currency_to_copper(plat=0, gold=0, silver=0, copper=0):
    # 1 Platinum = 100 Gold = 10,000 Silver = 1,000,000 Copper
    # 1 Gold = 100 Silver = 10,000 Copper
    # 1 Silver = 100 Copper
    total_copper = (
        plat * 100 * 100 * 100 +  # Plat to Copper
        gold * 100 * 100 +        # Gold to Copper
        silver * 100 +            # Silver to Copper
        copper                     # Copper
    )
    return total_copper


# Convert total copper back to 4-part currency
def copper_to_currency(total_copper):
    plat = total_copper // (100*100*100)
    remainder = total_copper % (100*100*100)
    
    gold = remainder // (100*100)
    remainder = remainder % (100*100)
    
    silver = remainder // 100
    copper = remainder % 100
    
    return plat, gold, silver, copper


# ----------------- DB Helpers -----------------
async def add_funds_db(guild_id, type, total_copper, donated_by=None, donated_at=None):
    """Insert a donation or spend entry."""
    donated_at = donated_at or datetime.utcnow()  # Use current time if not provided
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO funds (guild_id, type, total_copper, donated_by, donated_at)
            VALUES ($1, $2, $3, $4, $5)
        ''', guild_id, type, total_copper, donated_by, donated_at)

async def get_fund_totals(guild_id):
    """Get total donated and spent copper."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT
                SUM(CASE WHEN type='donation' THEN total_copper ELSE 0 END) AS donated,
                SUM(CASE WHEN type='spend' THEN total_copper ELSE 0 END) AS spent
            FROM funds
            WHERE guild_id=$1
        ''', guild_id)
    return row

async def get_all_donations(guild_id):
    """Get all donations (type='donation')"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT donated_by, total_copper, donated_at
            FROM funds
            WHERE guild_id=$1 AND type='donation'
            ORDER BY donated_at DESC
        ''', guild_id)
    return rows

# ----------------- Modals -----------------
class AddFundsModal(Modal):
    def __init__(self):
        super().__init__(title="Add Donation")
        self.plat = TextInput(label="Platinum", default="0", required=False)
        self.gold = TextInput(label="Gold", default="0", required=False)
        self.silver = TextInput(label="Silver", default="0", required=False)
        self.copper = TextInput(label="Copper", default="0", required=False)
        self.donated_by = TextInput(label="Donated By", placeholder="Optional", required=False)
        self.add_item(self.plat)
        self.add_item(self.gold)
        self.add_item(self.silver)
        self.add_item(self.copper)
        self.add_item(self.donated_by)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            total = currency_to_copper(
                plat=int(self.plat.value or 0),
                gold=int(self.gold.value or 0),
                silver=int(self.silver.value or 0),
                copper=int(self.copper.value or 0)
            )
        except ValueError:
            await interaction.response.send_message("❌ Invalid number entered.", ephemeral=True)
            return

        await add_funds_db(
            guild_id=interaction.guild.id,
            type='donation',
            total_copper=total,
            donated_by=self.donated_by.value.strip() or None,
            donated_at=datetime.utcnow()
        )
        await interaction.response.send_message("✅ Donation added!", ephemeral=True)

class SpendFundsModal(Modal):
    def __init__(self):
        super().__init__(title="Spend Funds")
        self.plat = TextInput(label="Platinum", default="0", required=False)
        self.gold = TextInput(label="Gold", default="0", required=False)
        self.silver = TextInput(label="Silver", default="0", required=False)
        self.copper = TextInput(label="Copper", default="0", required=False)
        self.note = TextInput(label="Note", placeholder="Optional", required=False)
        self.add_item(self.plat)
        self.add_item(self.gold)
        self.add_item(self.silver)
        self.add_item(self.copper)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            total = currency_to_copper(
                plat=int(self.plat.value or 0),
                gold=int(self.gold.value or 0),
                silver=int(self.silver.value or 0),
                copper=int(self.copper.value or 0)
            )
        except ValueError:
            await interaction.response.send_message("❌ Invalid number entered.", ephemeral=True)
            return

        await add_funds_db(
            guild_id=interaction.guild.id,
            type='spend',
            total_copper=total,
            donated_by=self.note.value.strip() or None,
            donated_at=datetime.utcnow()
        )
        await interaction.response.send_message("✅ Funds spent recorded!", ephemeral=True)


# Modal to show full donation history

class DonationHistoryModal(discord.ui.Modal):
    def __init__(self, guild_id, donations):
        super().__init__(title="📜 Full Donation History")
        self.guild_id = guild_id
        self.donations = donations
        
        total_copper = sum(d['total_copper'] for d in donations)
        t_plat, t_gold, t_silver, t_copper = copper_to_currency(total_copper)
        total_text = f"{t_plat}p {t_gold}g {t_silver}s {t_copper}c"

        # Combine all donations into one string
      
        history_text = ""
      
        for d in donations:
            total_copper += d['total_copper']
            plat, gold, silver, copper = copper_to_currency(d['total_copper'])
            donor = d['donated_by'] or "Anonymous"
            date = d['donated_at'].strftime("%m-%d-%y")
            history_text += f"{donor} | {plat}p {gold}g {silver}s {copper}c | {date}\n"
        
        # Optional: truncate if too long
        if len(history_text) > 4000:
            history_text = history_text[:3990] + "\n…"
        
        
        self.total_input = discord.ui.TextInput(
            label="💰 Total Donated",
            style=discord.TextStyle.short,
            default=total_text,
            required=False
        )
        self.total_input.disabled = True
        self.add_item(self.total_input)

        
        self.history_input = discord.ui.TextInput(
            label="Donation History",
            style=discord.TextStyle.paragraph,
            default=history_text,
            required=False
        )
        self.history_input.disabled = True
        self.add_item(self.history_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Closed.", ephemeral=True)

class SpendingHistoryModal(discord.ui.Modal):
    def __init__(self, guild_id, spendings):
        super().__init__(title="📜 Full Spending History")
        self.guild_id = guild_id
        self.spendings = spendings
        

        total_copper = sum(s['total_copper'] for s in spendings)
        t_plat, t_gold, t_silver, t_copper = copper_to_currency(total_copper)
        total_text = f"{t_plat}p {t_gold}g {t_silver}s {t_copper}c"
        
        # Combine all spendings into one string
        history_text = ""
        total_copper = 0
        for s in spendings:
            total_copper += s['total_copper']
            plat, gold, silver, copper = copper_to_currency(s['total_copper'])
            spender = s['donated_by'] or "Unknown"
            date = s['donated_at'].strftime("%m-%d-%y")
            history_text += f"{spender} | {plat}p {gold}g {silver}s {copper}c | {date}\n"

        if len(history_text) > 4000:
            history_text = history_text[:3990] + "\n…"

        self.total_input = discord.ui.TextInput(
            label="💰 Total Spending",
            style=discord.TextStyle.short,
            default=total_text,
            required=False
        )
        self.total_input.disabled = True
        self.add_item(self.total_input)

        self.history_input = discord.ui.TextInput(
            label="Spending History",
            style=discord.TextStyle.paragraph,
            default=history_text,
            required=False
        )
        self.history_input.disabled = True
        self.add_item(self.history_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Closed.", ephemeral=True)



    # Button to view full history

class ViewFullHistoryButton(discord.ui.Button):
    def __init__(self, donations):
        super().__init__(label="Donation History", style=discord.ButtonStyle.secondary)
        self.donations = donations  # Already filtered by guild_id

    async def callback(self, interaction: discord.Interaction):
        if not self.donations:
            await interaction.response.send_message("No donations found for this guild.", ephemeral=True)
            return

        modal = DonationHistoryModal(interaction.guild.id, self.donations)
        await interaction.response.send_modal(modal)


class ViewSpendingHistoryButton(discord.ui.Button):
    def __init__(self, spendings):
        super().__init__(label="Spending History", style=discord.ButtonStyle.secondary)
        self.spendings = spendings  # Already filtered by guild_id

    async def callback(self, interaction: discord.Interaction):
        if not self.spendings:
            await interaction.response.send_message("No spending found for this guild.", ephemeral=True)
            return

        modal = SpendingHistoryModal(interaction.guild.id, self.spendings)
        await interaction.response.send_modal(modal)




# ----------------- Slash Commands -----------------
@bot.tree.command(name="add_funds", description="Add a donation to the guild bank.")
async def add_funds(interaction: discord.Interaction):
    await interaction.response.send_modal(AddFundsModal())

@bot.tree.command(name="spend_funds", description="Record spent guild funds.")
async def spend_funds(interaction: discord.Interaction):
    await interaction.response.send_modal(SpendFundsModal())

@bot.tree.command(name="view_funds", description="View current available funds.")
async def view_funds(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    async with db_pool.acquire() as conn:
        all_donations = await conn.fetch('''
            SELECT donated_by, total_copper, donated_at, guild_id
            FROM funds
            WHERE type='donation'
            ORDER BY donated_at DESC
        ''')
        all_spendings = await conn.fetch('''
            SELECT donated_by, total_copper, donated_at, guild_id
            FROM funds
            WHERE type='spend'
            ORDER BY donated_at DESC
        ''')

    # Filter by current guild
    donations = [d for d in all_donations if d['guild_id'] == guild_id]
    spendings = [s for s in all_spendings if s['guild_id'] == guild_id]

    donated = sum(d['total_copper'] for d in donations)
    spent = sum(s['total_copper'] for s in spendings)
    available = donated - spent
    plat, gold, silver, copper = copper_to_currency(available)

    embed = discord.Embed(title="💰 Available Funds", color=discord.Color.gold())
    embed.add_field(name="\u200b", value=f"{plat}p {gold}g {silver}s {copper}c")

    view = discord.ui.View()
    view.add_item(ViewFullHistoryButton(donations))
    view.add_item(ViewSpendingHistoryButton(spendings))

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)



@bot.tree.command(name="view_fundshistory", description="View all donations in the guild bank.")
async def view_donations(interaction: discord.Interaction):
    guild_id = interaction.guild.id

    async with db_pool.acquire() as conn:
        donations = await conn.fetch('''
            SELECT donated_by, total_copper, donated_at
            FROM funds
            WHERE type='donation' AND guild_id=$1
            ORDER BY donated_at DESC
        ''', guild_id)

    if not donations:
        await interaction.response.send_message("No donations found for this guild.", ephemeral=True)
        return

    total_copper = sum(d['total_copper'] for d in donations)
    t_plat, t_gold, t_silver, t_copper = copper_to_currency(total_copper)

    embed = discord.Embed(
        title="📜 Donation Records",
        description=f"**Total Funds:** {t_plat}p {t_gold}g {t_silver}s {t_copper}c",
        color=discord.Color.green()
    )

    view = discord.ui.View()
    view.add_item(ViewFullHistoryButton(donations))

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)





class ItemDatabaseModal(discord.ui.Modal):
    def __init__(self, item_image_url, npc_image_url, item_slot, db_pool, guild_id, item_msg_id=None, npc_msg_id=None):
        super().__init__(title="Add Item Database Entry")
        self.item_image_url = item_image_url
        self.npc_image_url = npc_image_url
        self.item_slot = item_slot
        self.db_pool = db_pool
        self.guild_id = guild_id
        self.item_msg_id = item_msg_id
        self.npc_msg_id = npc_msg_id

        self.item_name = discord.ui.TextInput(
            label="Item Name",
            placeholder="Example: Flowing Black Silk Sash",
            required=True
        )
        self.add_item(self.item_name)

        self.zone_name = discord.ui.TextInput(
            label="Zone Name",
            placeholder="Example: Shadowfang Keep",
            required=True
        )
        self.add_item(self.zone_name)

        self.zone_area = discord.ui.TextInput(
            label="Zone Area",
            placeholder="Example: Goblin Camp",
            required=False
        )
        self.add_item(self.zone_area)

        self.npc_name = discord.ui.TextInput(
            label="NPC Name",
            placeholder="Example: Silvermoon Sentinel",
            required=True
        )
        self.add_item(self.npc_name)
        
        self.item_slot_field = discord.ui.TextInput(label="Item Slot", default=self.item_slot, required=True)
        self.add_item(self.item_slot_field)

            

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        added_by = interaction.user.name
    
        async with self.db_pool.acquire() as conn:
            # Check if item already exists
            existing = await conn.fetchrow(
                """
                SELECT * FROM item_database
                WHERE guild_id=$1 AND LOWER(item_name)=LOWER($2) AND LOWER(npc_name)=LOWER($3)
                """,
                guild_id,
                self.item_name.value.strip(),
                self.npc_name.value.strip()
            )
    
            # ⚠️ If it exists, ask user before overwriting
            if existing:
                view = ConfirmUpdateView()
                await interaction.response.send_message(
                    f"⚠️ `{self.item_name.value}` for `{self.npc_name.value}` already exists.\n"
                    "Do you want to update this entry?",
                    view=view,
                    ephemeral=True
                )
                await view.wait()
    
                if view.value is None or not view.value:
                    return  # user canceled
    
            # ✅ Insert or update (UPSERT)
            await conn.execute(
                """
                INSERT INTO item_database (
                    guild_id,
                    item_name,
                    zone_name,
                    zone_area,
                    npc_name,
                    item_slot,
                    item_image,
                    npc_image,
                    added_by,
                    item_msg_id,
                    npc_msg_id
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (guild_id, item_name, npc_name)
                DO UPDATE SET
                    zone_name   = EXCLUDED.zone_name,
                    zone_area   = EXCLUDED.zone_area,
                    item_slot   = EXCLUDED.item_slot,
                    item_image  = EXCLUDED.item_image,
                    npc_image   = EXCLUDED.npc_image,
                    added_by    = EXCLUDED.added_by,
                    item_msg_id = EXCLUDED.item_msg_id,
                    npc_msg_id  = EXCLUDED.npc_msg_id,
                    updated_at  = NOW();
                """,
                self.guild_id,
                self.item_name.value.strip(),
                self.zone_name.value.strip() if self.zone_name.value else None,
                self.zone_area.value.strip() if self.zone_area.value else None,
                self.npc_name.value.strip(),
                self.item_slot_field.value.lower().strip() if self.item_slot_field.value else None,
                self.item_image_url.strip() if self.item_image_url else None,
                self.npc_image_url.strip() if self.npc_image_url else None,
                added_by,
                self.item_msg_id,
                self.npc_msg_id,
            )
    
        if not interaction.response.is_done():
            await interaction.response.send_message("✅ Item added successfully!", ephemeral=True)
        else:
            await interaction.followup.send("✅ Item added successfully!", ephemeral=True)


class ConfirmUpdateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        self.value = None  # store True/False

    @discord.ui.button(label="✅ Yes, Update", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        await interaction.response.send_message("🔄 Updating existing entry...", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        await interaction.response.send_message("❌ Update canceled.", ephemeral=True)




# --------------- Slash Command ----------------
@bot.tree.command(name="add_item_db", description="Add a new item to the database")
@app_commands.describe(
    item_image="Upload an image of the item",
    npc_image="Upload an image of the NPC that drops the item",
    item_slot="Select the item slot"
)
@app_commands.choices(item_slot=[
    app_commands.Choice(name="Ammo", value="Ammo"),
    app_commands.Choice(name="Back", value="Back"),
    app_commands.Choice(name="Chest", value="Chest"),
    app_commands.Choice(name="Ear", value="Ear"),
    app_commands.Choice(name="Feet", value="Feet"),
    app_commands.Choice(name="Finger", value="Finger"),
    app_commands.Choice(name="Hands", value="Hands"),
    app_commands.Choice(name="Head", value="Head"),
    app_commands.Choice(name="Legs", value="Legs"),
    app_commands.Choice(name="Primary", value="Primary"),
    app_commands.Choice(name="Primary 2h", value="Primary 2h"),
    app_commands.Choice(name="Range", value="Range"),
    app_commands.Choice(name="Secondary", value="Secondary"),
    app_commands.Choice(name="Shirt", value="Shirt"),
    app_commands.Choice(name="Shoulders", value="Shoulders"),
    app_commands.Choice(name="Waist", value="Waist"),
    app_commands.Choice(name="Wrist", value="Wrist"),
    
])


async def add_item_db(interaction: discord.Interaction, item_image: discord.Attachment, npc_image: discord.Attachment, item_slot: str):
    """Uploads images and opens modal for item info entry."""
    # ✅ Require both images
    if not item_image or not npc_image:
        await interaction.response.send_message("❌ Both item and NPC images are required.", ephemeral=True)
        return

    guild = interaction.guild
    upload_channel = await ensure_upload_channel1(guild)

    # ✅ Upload both images to hidden log
    try:
        item_msg = await upload_channel.send(
            file=await item_image.to_file(),
            content=f"📦 Uploaded item image by {interaction.user.mention}"
        )
        npc_msg = await upload_channel.send(
            file=await npc_image.to_file(),
            content=f"👹 Uploaded NPC image by {interaction.user.mention}"
        )
       
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to upload files in this server.", ephemeral=True)
        return
    except Exception as e:
        await interaction.response.send_message(f"❌ Upload failed: {e}", ephemeral=True)
        return

    # ✅ Open the modal for extra info entry
    await interaction.response.send_modal(ItemDatabaseModal(
        guild_id=guild.id,
        item_image_url=item_msg.attachments[0].url,
        npc_image_url=npc_msg.attachments[0].url,
        item_slot=item_slot.lower(),
        db_pool=db_pool,
        item_msg_id = item_msg.id,
        npc_msg_id = npc_msg.id
    ))




class EditDatabaseModal(discord.ui.Modal):
    def __init__(self, item_row, db_pool):
        super().__init__(title=f"Edit {item_row['item_name']}")
        self.item_row = item_row
        self.db_pool = db_pool

        self.item_name = discord.ui.TextInput(label="Item Name", default=item_row['item_name'])
        self.add_item(self.item_name)

        self.zone_name = discord.ui.TextInput(label="Zone Name", default=item_row['zone_name'])
        self.add_item(self.zone_name)

        self.zone_area = discord.ui.TextInput(label="Zone Area", default=item_row['zone_area'])
        self.add_item(self.zone_area)

        self.npc_name = discord.ui.TextInput(label="NPC Name", default=item_row['npc_name'])
        self.add_item(self.npc_name)

        self.item_slot = discord.ui.TextInput(label="Item Slot", default=item_row['item_slot'])
        self.add_item(self.item_slot)

    async def on_submit(self, interaction: discord.Interaction):
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE item_database
                SET item_name=$1, zone_name=$2, zone_area=$3, npc_name=$4, item_slot=$5, updated_at=NOW()
                WHERE id=$6 AND guild_id=$7
            """, self.item_name.value, self.zone_name.value, self.zone_area.value, self.npc_name.value, self.item_slot.value.lower(),
                 self.item_row['id'], interaction.guild.id)

        await interaction.response.send_message(f"✅ Updated **{self.item_name.value}**!", ephemeral=True)


@bot.tree.command(name="edit_item_db", description="Edit an existing item in the database by name.")
@app_commands.describe(item_name="The name of the item to edit.")
async def edit_database_item(interaction: discord.Interaction, item_name: str):
    async with db_pool.acquire() as conn:
        item_row = await conn.fetchrow(
            "SELECT * FROM item_database WHERE guild_id=$1 AND item_name ILIKE $2",
            interaction.guild.id, item_name
        )

    if not item_row:
        await interaction.response.send_message("❌ Item not found.", ephemeral=True)
        return

    await interaction.response.send_modal(EditDatabaseModal(item_row, db_pool))




class ConfirmRemoveItemView(View):
    def __init__(self, item_name, db_pool):
        super().__init__(timeout=60)
        self.item_name = item_name
        self.db_pool = db_pool

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        try:
            async with self.db_pool.acquire() as conn:
                # Fetch message IDs to delete the images
                row = await conn.fetchrow("""
                    SELECT item_msg_id, npc_msg_id 
                    FROM item_database 
                    WHERE item_name=$1 AND guild_id=$2
                """, self.item_name, interaction.guild_id)

                if not row:
                    await interaction.response.edit_message(
                        content=f"❌ Item **{self.item_name}** not found in the database.",
                        view=None
                    )
                    return

                # Delete the uploaded messages
                upload_channel = discord.utils.get(interaction.guild.text_channels, name="item-database-upload-log")
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
                    WHERE item_name=$1 AND guild_id=$2
                """, self.item_name, interaction.guild_id)

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
async def remove_itemdb(interaction: discord.Interaction, item_name: str):
    # Ask for confirmation first
    view = ConfirmRemoveItemView(item_name=item_name, db_pool=db_pool)
    await interaction.response.send_message(
        f"⚠️ Are you sure you want to remove **{item_name}** from the item database?",
        view=view,
        ephemeral=True
    )



class PaginatedResultsView(discord.ui.View):
    def __init__(self, items: list[dict], per_page: int = 5, author_id: int | None = None):
        super().__init__(timeout=None)
        self.items = items
        self.per_page = per_page
        self.current_page = 0
        self.max_page = max(0, math.ceil(len(items) / per_page) - 1)
        self.author_id = author_id  # optional: restrict button use to the command author

        self.previous_button = self.PreviousPageButton(self)
        self.next_button = self.NextPageButton(self)
        self.back_button = self.BackToFiltersButton(self)

        # Add buttons in order
        self.add_item(self.previous_button)
        self.add_item(self.next_button)
        self.add_item(self.back_button)

        self._last_message = None  # will store the sent message object

        self._update_button_states()

    def _update_button_states(self):
        self.previous_button.disabled = self.current_page <= 0
        self.next_button.disabled = self.current_page >= self.max_page

    def get_page_items(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        return self.items[start:end]

    def build_embeds_for_current_page(self) -> list[discord.Embed]:
        embeds = []
        page_items = self.get_page_items()
        for item in page_items:
            title = item.get("item_name") or item.get("name") or "Unknown Item"
            npc_name = item.get("npc_name") or "Unknown NPC"
            zone_name = item.get("zone_name") or "Unknown Zone"
            zone_area = item.get("zone_area") or ""
            raw_slot = item.get("item_slot") or item.get("slot") or ""
            item_image = item.get("item_image") or item.get("image")
            npc_image = item.get("npc_image") or None

            embed = discord.Embed(
                title=title,
                color=discord.Color.blue()
            )
            
            
            
                # Handle multi-slot entries like "chest, legs"
            slot = "\n".join([s.strip().capitalize() for s in raw_slot.split(",")])


            
            # Primary details in fields
            embed.add_field(name="NPC", value=npc_name, inline=True)
            embed.add_field(name="Zone", value=zone_name, inline=True)
            embed.add_field(name="Slot", value=slot, inline=True)

            # Add the main image (item) and thumbnail (npc)
            if item_image:
                embed.set_image(url=item_image)
            if npc_image:
                embed.set_thumbnail(url=npc_image)

            embeds.append(embed)

        # Add page footer to each embed so users know where they are
        for e in embeds:
            e.set_footer(text=f"Page {self.current_page + 1} of {self.max_page + 1} — Total results: {len(self.items)}")

        return embeds

    async def _edit_message_with_current_page(self, interaction: discord.Interaction):
        self._update_button_states()
        embeds = self.build_embeds_for_current_page()

        # If interaction hasn't been responded to yet, use response.edit_message/send_message accordingly
        try:
            if not interaction.response.is_done():
                # If the original interaction hasn't been answered, we edit the original deferred response (unlikely for nav buttons)
                await interaction.response.edit_message(embeds=embeds, view=self)
            else:
                # Most common: nav buttons after initial send -> use followup edit on the original message object
                if self._last_message:
                    await self._last_message.edit(embeds=embeds, view=self)
                else:
                    # fallback: send a followup and store message
                    msg = await interaction.followup.send(embeds=embeds, view=self)
                    self._last_message = msg
        except Exception:
            # fallback to editing via response if possible
            try:
                await interaction.response.edit_message(embeds=embeds, view=self)
            except Exception:
                # give up silently; caller should log if needed
                pass

    # Button classes



class PaginatedResultsView(discord.ui.View):
    def __init__(self, items: list[dict], db_pool, guild_id: int, *, per_page: int = 5, author_id: int | None = None):
        super().__init__(timeout=None)
        self.items = items
        self.db_pool = db_pool
        self.guild_id = guild_id
        self.per_page = per_page
        self.current_page = 0
        self.max_page = max(0, math.ceil(len(items) / per_page) - 1)
        self.author_id = author_id
        self._last_message = None

        # Initialize navigation + item select dropdown
        self._update_view()

    # -------------------------------
    # Page helpers
    # -------------------------------
    def _page_items(self):
        start = self.current_page * self.per_page
        return self.items[start:start + self.per_page]

    def _update_view(self):
        """Refresh buttons and dropdown contents."""
        self.clear_items()

        # Navigation buttons
        prev_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="⬅️")
        next_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="➡️")
        back_btn = discord.ui.Button(style=discord.ButtonStyle.danger, emoji="🔄", label="Back to Filters")

        prev_btn.callback = self._prev_page
        next_btn.callback = self._next_page
        back_btn.callback = self._back_to_filters

        prev_btn.disabled = self.current_page <= 0
        next_btn.disabled = self.current_page >= self.max_page

        # Add buttons
        self.add_item(prev_btn)
        self.add_item(next_btn)
        self.add_item(back_btn)

        # Dropdown menu for items on this page
        page_items = self._page_items()
        options = [
            discord.SelectOption(label=(i.get("item_name") or "Unknown Item")[:100], value=str(idx))
            for idx, i in enumerate(page_items)
        ]
        select = discord.ui.Select(
            placeholder="Select an item to send privately",
            options=options,
            min_values=1,
            max_values=1,
        )
        select.callback = self._send_item_ephemeral
        self.add_item(select)

    def _build_embeds(self):
        """Builds embeds for current page."""
        embeds = []
        page_items = self._page_items()
        for i in page_items:
            title = i.get("item_name") or "Unknown Item"
            npc_name = i.get("npc_name") or "Unknown NPC"
            zone_name = i.get("zone_name") or "Unknown Zone"
            zone_area = i.get("zone_area") or ""
            raw_slot = i.get("item_slot") or ""
            item_image = i.get("item_image")
            npc_image = i.get("npc_image")

            
                # Handle multi-slot entries like "chest, legs"
            slot = "\n".join([s.strip().capitalize() for s in raw_slot.split(",")])
            
            embed = discord.Embed(title=title, color=discord.Color.blurple())
            embed.add_field(name="NPC", value=npc_name, inline=True)
            embed.add_field(name="Zone", value=f"{zone_name} \n{zone_area}", inline=True)
            embed.add_field(name="Slot", value=slot, inline=True)
            if item_image:
                embed.set_image(url=item_image)
            if npc_image:
                embed.set_thumbnail(url=npc_image)
            embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_page + 1}")
            embeds.append(embed)
        return embeds

    # -------------------------------
    # Button Callbacks
    # -------------------------------
    async def _prev_page(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_view()
            await self._render(interaction)

    async def _next_page(self, interaction: discord.Interaction):
        if self.current_page < self.max_page:
            self.current_page += 1
            self._update_view()
            await self._render(interaction)

    async def _back_to_filters(self, interaction: discord.Interaction):
       
        await interaction.response.edit_message(
            content="Choose a filter type:",
            embeds=[],
            view=DatabaseView(self.db_pool, self.guild_id)
        )

    # -------------------------------
    # Dropdown callback
    # -------------------------------
    async def _send_item_ephemeral(self, interaction: discord.Interaction):
        """Sends an ephemeral message for the selected item."""
        try:
            index = int(interaction.data["values"][0])
            item = self._page_items()[index]
        except Exception:
            await interaction.response.send_message("⚠️ Something went wrong selecting that item.", ephemeral=True)
            return

        title = item.get("item_name") or "Unknown Item"
        npc_name = item.get("npc_name") or "Unknown NPC"
        zone_name = item.get("zone_name") or "Unknown Zone"
        zone_area = item.get("zone_area") or ""
        slot = item.get("item_slot") or ""
        item_image = item.get("item_image")
        npc_image = item.get("npc_image")

        embed = discord.Embed(title=title, color=discord.Color.green())
        embed.add_field(name="NPC", value=npc_name, inline=True)
        embed.add_field(name="Zone", value=f"{zone_name} \n{zone_area}", inline=True)
        embed.add_field(name="Slot", value=slot, inline=True)
        if item_image:
            embed.set_image(url=item_image)
        if npc_image:
            embed.set_thumbnail(url=npc_image)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -------------------------------
    # Rendering
    # -------------------------------
    async def _render(self, interaction: discord.Interaction):
        embeds = self._build_embeds()
        await interaction.response.edit_message(embeds=embeds, view=self)

    

# ---------- FILTER VIEW ----------
class DatabaseView(View):
    def __init__(self, db_pool, guild_id):
        super().__init__(timeout=None)
        self.db_pool = db_pool
        self.guild_id = guild_id

        self.filter_select = Select(
            placeholder="Choose filter type",
            options=[
                discord.SelectOption(label="Slot", value="item_slot"),
                discord.SelectOption(label="NPC Name", value="npc_name"),
                discord.SelectOption(label="Zone Name", value="zone_name"),
                discord.SelectOption(label="All", value="all")
            ]
        )
        self.filter_select.callback = self.filter_select_callback
        self.add_item(self.filter_select)


    async def filter_select_callback(self, interaction: discord.Interaction):
        filter_type = self.filter_select.values[0].lower()

        # 🧩 Handle "All" directly — no second dropdown
        if filter_type == "all":
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM item_database WHERE guild_id=$1 ORDER BY LOWER(item_name)",
                    self.guild_id,
                )

            rows = [dict(r) for r in rows]
            if not rows:
                await interaction.response.edit_message(content="❌ No results found.", view=None)
                return

            for r in rows:
                r["_db_pool"] = self.db_pool
                r["_guild_id"] = self.guild_id

            
            view = PaginatedResultsView(
                rows,
                self.db_pool,
                self.guild_id,
                per_page=5,
                author_id=interaction.user.id
            )
            embeds = view._build_embeds()
            await interaction.response.edit_message(content=None, embeds=embeds, view=view)


            return

        # 🧭 Otherwise, build second dropdown dynamically
        async with self.db_pool.acquire() as conn:
            query = f"SELECT DISTINCT {filter_type} FROM item_database WHERE guild_id=$1"
            rows = await conn.fetch(query, self.guild_id)

        options = []
        seen_values = set()

        for row in rows:
            value = (row[filter_type] or "").strip().lower()
            if not value:
                continue
            # Handle multi-slot entries
            if filter_type == "item_slot" and "," in value:
                for slot in value.split(","):
                    slot = slot.strip().lower()
                    if slot and slot not in seen_values:
                        seen_values.add(slot)
                        options.append(discord.SelectOption(label=slot.title(), value=slot))
            elif value not in seen_values:
                seen_values.add(value)
                options.append(discord.SelectOption(label=value.title(), value=value))

        # Add back/previous option
        options.append(discord.SelectOption(label="⬅️ Previous", value="previous"))

        # 🔄 Replace the current dropdown with the populated one
        self.clear_items()
        self.value_select = discord.ui.Select(
            placeholder=f"Select {filter_type.title()}",
            options=options,
            min_values=1,
            max_values=1,
        )

        self.value_select.callback = lambda i: self.value_select_callback(i, filter_type)
        self.add_item(self.value_select)

        await interaction.response.edit_message(content=f"Select a {filter_type}:", view=self)




    async def value_select_callback(self, interaction, filter_type):
        chosen_value = interaction.data["values"][0]

        # 🧭 If user selected "Previous"
        if chosen_value == "previous":
            await interaction.response.edit_message(
                content="Choose a filter type:",
                embeds=[],
                view=DatabaseView(self.db_pool, self.guild_id)
            )
            return

        async with self.db_pool.acquire() as conn:
            if filter_type == "all":
                query = "SELECT * FROM item_database WHERE guild_id=$1 ORDER BY LOWER(item_name)"
                rows = await conn.fetch(query, self.guild_id)
            else:
                query = f"""
                    SELECT * FROM item_database
                    WHERE guild_id=$1
                      AND LOWER({filter_type}) LIKE $2
                    ORDER BY LOWER(item_name)
                """
                rows = await conn.fetch(query, self.guild_id, f"%{chosen_value}%")

        # Convert immutable asyncpg.Record -> dict
        rows = [dict(r) for r in rows]

        if not rows:
            await interaction.response.edit_message(content="❌ No results found.", view=None)
            return

        for r in rows:
            r["_db_pool"] = self.db_pool
            r["_guild_id"] = self.guild_id

       
        view = PaginatedResultsView(
            rows,
            self.db_pool,
            self.guild_id,
            per_page=5,
            author_id=interaction.user.id
        )
        embeds = view._build_embeds()
        await interaction.response.edit_message(content=None, embeds=embeds, view=view)



        await show_results(interaction, rows, self.db_pool, self.guild_id)


# ---------- RESULTS DISPLAY ----------
async def show_results(interaction, items, db_pool=None, guild_id=None):
    """Safely show paginated embeds whether or not the interaction has already been responded to."""
    view = PaginatedResultsView(
        items,
        db_pool,
        guild_id,
        per_page=5,
        author_id=interaction.user.id
    )

    embeds = view._build_embeds()

    # ✅ Check whether we already responded to this interaction
    if not interaction.response.is_done():
        # first response
        await interaction.response.edit_message(content=None, embeds=embeds, view=view)
    else:
        # interaction already responded — edit the existing message instead
        try:
            msg = await interaction.original_response()
            await msg.edit(content=None, embeds=embeds, view=view)
        except Exception:
            # fallback: send a follow-up message (usually shouldn't happen)
            await interaction.followup.send(content=None, embeds=embeds, view=view)


            

@bot.tree.command(name="view_item_db", description="View the guild's item database with filters.")
async def view_item_db(interaction: discord.Interaction):
    # Ensure DB is connected
    async with db_pool.acquire() as conn:
        check = await conn.fetchval("SELECT COUNT(*) FROM item_database WHERE guild_id=$1", interaction.guild.id)

    if check == 0:
        await interaction.response.send_message("❌ No data found in the item database.", ephemeral=True)
        return

    # Start with the FIRST dropdown view (DatabaseView)
    view = DatabaseView(db_pool, interaction.guild.id)
    await interaction.response.send_message(
        content="Select a filter type to begin:",
        view=view,
        ephemeral=False  # make visible only to the user, remove if you want public
    )



from discord import app_commands, Attachment

@bot.tree.command(name="edit_item_image", description="Upload a new item or NPC image for an existing database entry.")
@app_commands.describe(
    item_name="The exact item name to update",
    npc_name="The NPC associated with this item",
    new_item_image="Upload new image for the item (optional)",
    new_npc_image="Upload new image for the NPC (optional)",
)
async def edit_item_image(
    interaction: discord.Interaction,
    item_name: str,
    npc_name: str,
    new_item_image: Attachment = None,
    new_npc_image: Attachment = None,
):
    guild_id = interaction.guild.id

    # --- Validate ---
    if not new_item_image and not new_npc_image:
        await interaction.response.send_message(
            "⚠️ You must upload at least one new image.", ephemeral=True
        )
        return

    async with db_pool.acquire() as conn:
        # --- Check if item exists ---
        existing = await conn.fetchrow(
            """
            SELECT item_image, npc_image FROM item_database
             WHERE guild_id = $1 AND LOWER(item_name) = LOWER($2) AND LOWER(npc_name) = LOWER($3)
            """,
            guild_id, item_name, npc_name
        )

        if not existing:
            await interaction.response.send_message(
                f"❌ No record found for `{item_name}` (NPC: `{npc_name}`).",
                ephemeral=True
            )
            return

        # --- Get uploaded image URLs ---
        new_item_image_url = new_item_image.url if new_item_image else None
        new_npc_image_url = new_npc_image.url if new_npc_image else None

        # --- Update the database ---
        await conn.execute(
            """
            UPDATE item_database
               SET item_image = COALESCE($1, item_image),
                   npc_image  = COALESCE($2, npc_image),
                   updated_at = NOW()
             WHERE guild_id = $3
               AND LOWER(item_name) = LOWER($4)
               AND LOWER(npc_name) = LOWER($5)
            """,
            new_item_image_url,
            new_npc_image_url,
            guild_id,
            item_name,
            npc_name
        )

    # --- Build confirmation embed ---
    embed = discord.Embed(
        title=f"✅ Updated Images for {item_name}",
        description=f"NPC: **{npc_name}**",
        color=discord.Color.green()
    )

    if new_item_image_url:
        embed.add_field(name="🖼️ New Item Image", value="Updated successfully", inline=False)
        embed.set_image(url=new_item_image_url)
    if new_npc_image_url:
        embed.add_field(name="👤 New NPC Image", value="Updated successfully", inline=False)
        if not new_item_image_url:
            embed.set_image(url=new_npc_image_url)

    await interaction.response.send_message(embed=embed, ephemeral=True)





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
