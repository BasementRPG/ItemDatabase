import os
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput
from datetime import datetime
import asyncpg 
from discord.ui import View, Button
from discord.ui import Select, View
from discord import SelectOption, Embed
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
            INSERT INTO inventory (guild_id, upload_message_id, name, image, donated_by, qty, added_by, created_at1)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ''', guild_id, upload_message_id, name, image, donated_by, qty, added_by, created_at1)


async def get_all_items(guild_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, image, donated_by FROM inventory WHERE guild_id=$1 ORDER BY id", guild_id)
    return rows

async def get_item_by_name(guild_id, name):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM inventory WHERE guild_id=$1 AND name=$2", guild_id, name)
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
        UPDATE inventory
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
                "SELECT name, donated_by, created_at1 FROM inventory WHERE guild_id=$1 ORDER BY created_at1 DESC",
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
                "SELECT name, removed_by, removed_at, removed_reason FROM inventory WHERE guild_id=$1 ORDER BY removed_at DESC",
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
                    UPDATE inventory
                    SET image=NULL,
                        created_images=NULL,
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
            "SELECT name, image, donated_by FROM inventory WHERE guild_id=$1 AND qty=1 ORDER BY name ASC",
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
            "SELECT * FROM inventory WHERE guild_id=$1 AND name=$2 AND qty=1",
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
            "SELECT COUNT(*) FROM inventory WHERE guild_id = $1;",
            guild_id
        )

        # Total currently in bank
        total_in_bank = await conn.fetchval(
            "SELECT COUNT(*) FROM inventory WHERE guild_id = $1 AND qty = 1;",
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







# --------------- Modal ----------------
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

        self.npc_name = discord.ui.TextInput(
            label="NPC Name",
            placeholder="Example: Silvermoon Sentinel",
            required=True
        )
        self.add_item(self.npc_name)
        
        self.npc_name = discord.ui.TextInput(
            label="NPC Name",
            placeholder="Example: Silvermoon Sentinel",
            required=True
        )
        self.item_slot_field = discord.ui.TextInput(label="Item Slot", default=self.item_slot, required=True)
        self.add_item(self.item_slot_field)

            

    async def on_submit(self, interaction: discord.Interaction):
        added_by = str(interaction.user)
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO item_database (guild_id, item_name, zone_name, npc_name, item_slot, item_image, npc_image, added_by, created_at, image_message_id, npc_message_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10)
                """,
                self.guild_id,
                self.item_name.value,
                self.zone_name.value,
                self.npc_name.value,
                self.item_slot_field.value.lower(),
                self.item_image_url,
                self.npc_image_url,
                added_by,
                self.item_msg_id,
                self.npc_msg_id
                
            )
        await interaction.response.send_message(
            f"✅ Item **{self.item_name.value}** added to the database!", ephemeral=True
        )

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
    app_commands.Choice(name="Finger", value="Finer"),
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




class ViewDatabaseSelect(View):
    def __init__(self, guild_id, db_pool):
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.db_pool = db_pool
        self.filter_type = None
        self.selected_value = None

        # Initial dropdown: filter type
        self.add_item(FilterTypeSelect(self))

    async def show_results(self, interaction: discord.Interaction, rows):
        embeds = []
        for row in rows:
            embed = Embed(title=row["item_name"])
            embed.set_image(url=row["item_image_url"])
            embed.set_thumbnail(url=row["npc_image_url"])
            embed.add_field(name="Slot", value=row["item_slot"], inline=True)
            embed.add_field(name="NPC", value=row["npc_name"], inline=True)
            embed.add_field(name="Zone", value=row["zone_name"], inline=True)
            embeds.append(embed)

        for i in range(0, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[i:i+10])


class FilterTypeSelect(Select):
    def __init__(self, parent_view):
        options = [
            SelectOption(label="Slot", value="slot"),
            SelectOption(label="NPC", value="npc"),
            SelectOption(label="Zone", value="zone"),
            SelectOption(label="Item Name", value="item_name"),
            SelectOption(label="All", value="all"),
        ]
        super().__init__(placeholder="Filter by...", min_values=1, max_values=1, options=options)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.filter_type = self.values[0]

        # Fetch possible values from DB
        async with self.parent_view.db_pool.acquire() as conn:
            if self.values[0] == "all":
                options = [SelectOption(label="All Items", value="all")]
            else:
                col_map = {
                    "slot": "item_slot",
                    "npc": "npc_name",
                    "zone": "zone_name",
                    "item_name": "item_name"
                }
                col = col_map[self.values[0]]
                rows = await conn.fetch(f"SELECT DISTINCT {col} FROM item_database WHERE guild_id=$1 ORDER BY {col} ASC", self.parent_view.guild_id)
                options = [SelectOption(label=row[col], value=row[col]) for row in rows]

        # Replace the dropdown in the view
        self.parent_view.clear_items()
        self.parent_view.add_item(FilterValueSelect(self.parent_view, options))
        await interaction.response.edit_message(view=self.parent_view)


class FilterValueSelect(Select):
    def __init__(self, parent_view, options):
        super().__init__(placeholder="Select a value...", min_values=1, max_values=1, options=options)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.selected_value = self.values[0]

        async with self.parent_view.db_pool.acquire() as conn:
            if self.values[0] == "all":
                rows = await conn.fetch("SELECT * FROM item_database WHERE guild_id=$1 ORDER BY item_name ASC", self.parent_view.guild_id)
            else:
                col_map = {
                    "slot": "item_slot",
                    "npc": "npc_name",
                    "zone": "zone_name",
                    "item_name": "item_name"
                }
                col = col_map[self.parent_view.filter_type]
                rows = await conn.fetch(
                    f"SELECT * FROM item_database WHERE guild_id=$1 AND {col} ILIKE $2 ORDER BY item_name ASC",
                    self.parent_view.guild_id, self.values[0]
                )

        await self.parent_view.show_results(interaction, rows)


@bot.tree.command(name="view_item_db", description="View and filter items in the database.")
async def view_database(interaction: discord.Interaction):
    view = ViewDatabaseSelect(db_pool=db_pool, guild_id=interaction.guild.id)
    await interaction.response.send_message("Select a filter to view items:", view=view, ephemeral=True)




class EditDatabaseModal(discord.ui.Modal):
    def __init__(self, item_row, db_pool):
        super().__init__(title=f"Edit {item_row['item_name']}")
        self.item_row = item_row
        self.db_pool = db_pool

        self.item_name = discord.ui.TextInput(label="Item Name", default=item_row['item_name'])
        self.add_item(self.item_name)

        self.zone_name = discord.ui.TextInput(label="Zone Name", default=item_row['zone_name'])
        self.add_item(self.zone_name)

        self.npc_name = discord.ui.TextInput(label="NPC Name", default=item_row['npc_name'])
        self.add_item(self.npc_name)

        self.item_slot = discord.ui.TextInput(label="Item Slot", default=item_row['item_slot'])
        self.add_item(self.item_slot)

    async def on_submit(self, interaction: discord.Interaction):
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE item_database
                SET item_name=$1, zone_name=$2, npc_name=$3, item_slot=$4, updated_at=NOW()
                WHERE id=$5 AND guild_id=$6
            """, self.item_name.value, self.zone_name.value, self.npc_name.value, self.item_slot.value.lower(),
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
                    SELECT image_message_id, npc_message_id 
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
                    for msg_id in [row["image_message_id"], row["npc_message_id"]]:
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
