import os
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput
from datetime import datetime
import asyncpg 
from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io

active_views = {}

print("discord.py version:", discord.__version__)


TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")


BG_FILES = {
    "Weapon": "assets/backgrounds/bgweapon.png",
    "Equipment": "assets/backgrounds/bgarmor.png",
    "Consumable": "assets/backgrounds/bgconsumable.png",
    "Crafting": "assets/backgrounds/bgcrafting.png",
    "Misc": "assets/backgrounds/bgmisc.png",
    
}



TYPE = ["Equipment", "Crafting", "Consumable", "Equipment", "Misc", "Weapon"]
WEAPON_TYPES = ["Axe", "Battle Axe", "Bow", "Dagger", "Great Scythe", "Great Sword", "Long Sword", "Mace", "Maul", "Scimitar", "Scythe", "Short Sword", "Spear", "Trident", "Warhammer" ]
ARMORTYPES_SUBTYPES = ["Chain", "Cloth", "Leather", "Plate", "Shield"]
CONSUMABLE_SUBTYPES = ["Drink", "Food", "Other", "Potion", "Scroll"]
CRAFTING_SUBTYPES = ["Unknown", "Raw", "Refined"]
MISC_SUBTYPES = ["Quest Item", "Unknown"]
EQUIPMENT_SUBTYPES = ["Ammo","Back","Chest","Ear","Face","Feet","Finger","Hands","Head","Legs","Neck","Primary","Range","Secondary","Shirt","Shoulders","Waist","Wrist"]
WEAPON_SUBTYPES = ["Ammo","Primary", "Range","Secondary"]
WEAPON_SKILLTYPE = ["One Handed", "Two Handed"]
WEAPON_SKILL = ["ARC","BLG","SLA","STA","THR"]

SIZE = ["Large","Medium","Small"]

RACE_OPTIONS = ["DDF","DEF","DGN","DWF","ELF","GNM","GOB","HFL","HIE","HUM","ORG","TRL"]
CLASS_OPTIONS = ["ARC", "BRD", "BST", "CLR", "DRU", "ELE", "ENC", "FTR", "INQ", "MNK", "NEC", "PAL", "RNG", "ROG", "SHD", "SHM", "SPB", "WIZ"]



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





async def add_item_db(guild_id, upload_message_id, name, type, subtype=None, size=None, slot=None, stats=None, weight=None,classes=None, race=None, image=None, donated_by=None, qty=None, added_by=None, attack=None, delay=None,effects=None, ac=None, created_images=None):
    created_at1 = datetime.utcnow()
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO inventory (guild_id, upload_message_id, name, size, type, subtype, slot, stats, weight, classes, race, image, donated_by, qty, added_by, attack, delay, effects, ac, created_images, created_at1)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21)
        ''', guild_id, upload_message_id, name, size, type, subtype, slot, stats, weight, classes, race, image, donated_by, qty, added_by, attack, delay, effects, ac, created_images, created_at1)
        

async def get_all_items(guild_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, type, subtype, slot, size, stats, weight, classes, race, image, donated_by FROM inventory WHERE guild_id=$1 ORDER BY id", guild_id)
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



async def generate_item_image(item_name, type, subtype, slot, stats, effects, donated_by):
    # Create a base image
    width, height = 512, 256
    background_color = (30, 30, 30)  # dark gray
    text_color = (255, 255, 255)     # white

    img = Image.new('RGB', (width, height), color=background_color)
    draw = ImageDraw.Draw(img)

    # Optional: load a TTF font
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except:
        font = ImageFont.load_default()

    # Draw text
    y = 10
    line_spacing = 28
    for line in [
        f"Name: {item_name}",
        f"Type: {type} | Subtype: {subtype}",
        f"Stats: {stats}",
        f"Effects: {effects}",
        f"Donated by: {donated_by}"
    ]:
        draw.text((10, y), line, fill=text_color, font=font)
        y += line_spacing

    # Save image to BytesIO
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


# ---------- UI Components ----------

class SubtypeSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        
        # Add debugging
        print(f"DEBUG: SubtypeSelect init - type: {self.parent_view.type}")
        
        # Add safety check
        if not self.parent_view.type:
            print("ERROR: type is None!")
            options = [discord.SelectOption(label="Error", value="error")]
        elif self.parent_view.type == "Crafting":
            options = [discord.SelectOption(label=s, value=s) for s in CRAFTING_SUBTYPES]
        elif self.parent_view.type == "Consumable":
            options = [discord.SelectOption(label=s, value=s) for s in CONSUMABLE_SUBTYPES]
        else:
            options = [discord.SelectOption(label=s, value=s) for s in MISC_SUBTYPES]

        # ✅ Mark selected subtype as default
        for opt in options:
            if opt.label == self.parent_view.subtype:
                opt.default = True

        super().__init__(placeholder="Select Subtype", options=options)

    async def callback(self, interaction: discord.Interaction):
            try:
                print(f"DEBUG: SubtypeSelect callback - values: {self.values}")
                self.parent_view.subtype = self.values[0]
                # update which option is default so it stays highlighted
                for opt in self.options:
                    opt.default = (opt.label == self.values[0])
                await interaction.response.edit_message(view=self.parent_view)
            except Exception as e:
                print(f"ERROR in SubtypeSelect callback: {e}")
                import traceback
                traceback.print_exc()
                try:
                    await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
                except:
                    pass

class SlotSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        
        print(f"DEBUG: SlotSelect init - type: {self.parent_view.type}")
        
        if not self.parent_view.type:
            print("ERROR: type is None!")
            options = [discord.SelectOption(label="Error", value="error")]
        elif self.parent_view.type in ["Equipment", "Armor"]:
            options = [discord.SelectOption(label=s, value=s) for s in EQUIPMENT_SUBTYPES]
        elif self.parent_view.type in ["Weapon"]:
            options = [discord.SelectOption(label=s, value=s) for s in WEAPON_SUBTYPES]
        else:
            options = [discord.SelectOption(label="N/A", value="N/A")]
        
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
    
class RaceSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
    
        # Always show all options
        options = [discord.SelectOption(label="All")] + [discord.SelectOption(label=r) for r in RACE_OPTIONS]

        for opt in options:
            if self.parent_view.usable_race and opt.label in self.parent_view.usable_race:
                opt.default = True
		
        super().__init__(
            placeholder="Select usable race (multi)",
            options=options,
            min_values=0,
            max_values=len(options)
        )
    

    
    async def callback(self, interaction: discord.Interaction):
        # If All is selected, ignore other selections
        if "All" in self.values:
            self.view.usable_race = ["All"]
        else:
            # If other race selected while All is in previous selection, remove All
            self.view.usable_race = self.values
    
        # Update the dropdown so selections are visible
        for option in self.options:
            option.default = option.label in self.view.usable_race
    
        await interaction.response.edit_message(view=self.view)


class SizeSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        
        # Use the global SIZE list
        options = [discord.SelectOption(label=s, value=s) for s in SIZE]

        # ✅ Mark selected size as default
        for opt in options:
            if opt.label == self.parent_view.size:
                opt.default = True

        super().__init__(placeholder="Select Size", options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            print(f"DEBUG: SizeSelect callback - values: {self.values}")
            # Save to size column
            self.parent_view.size = self.values[0]

            # Update which option is default so it stays highlighted
            for opt in self.options:
                opt.default = (opt.label == self.values[0])

            await interaction.response.edit_message(view=self.parent_view)
        except Exception as e:
            print(f"ERROR in SizeSelect callback: {e}")
            import traceback
            traceback.print_exc()
            try:
                await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            except:
                pass
                
class ItemEntryView(discord.ui.View):
    def __init__(self, author, db_pool=None, type=None, item_id=None, existing_data=None, is_edit=False):
        super().__init__(timeout=None)
        self.db_pool = db_pool     
        self.author = author
        self.type = type
        self.subtype = None
        self.slot = []
        self.size=""
        self.usable_classes = []
        self.usable_race = []
        self.item_name = ""
        self.stats = ""
        self.weight = ""
        self.item_id = item_id
        self.donated_by = ""
        self.attack = ""
        self.delay = ""
        self.effects = ""
        self.ac = ""
        self.is_edit=is_edit

        # preload existing if editing
        if existing_data:
            self.item_name = existing_data['name']
            self.type = existing_data['type']
            self.subtype = existing_data['subtype']
            self.size = existing_data['size']
            self.slot = existing_data['slot'].split(" ") if existing_data['slot'] else []
            self.stats = existing_data['stats']
            self.weight = existing_data['weight']
            self.ac = existing_data['ac']
            self.attack = existing_data['attack']
            self.delay = existing_data['delay']
            self.effects = existing_data['effects']
            self.donated_by = existing_data['donated_by']
            self.usable_classes = existing_data['classes'].split(" ") if existing_data['classes'] else []
            self.usable_race = existing_data['race'].split(" ") if existing_data['race'] else []

        if self.type in ["Crafting","Consumable","Misc"]:
            self.subtype_select = SubtypeSelect(self)
            self.add_item(self.subtype_select)

        
        if self.type in ["Weapon", "Equipment"]:

			
            self.slot_select = SlotSelect(self)
            self.add_item(self.slot_select)
            
            self.classes_select = ClassesSelect(self)
            self.add_item(self.classes_select)
            
            self.race_select = RaceSelect(self)
            self.add_item(self.race_select)

        self.size_select = SizeSelect(self)
        self.add_item(self.size_select)
     
        self.details_button = discord.ui.Button(label="Required Details", style=discord.ButtonStyle.secondary)
        self.details_button.callback = self.open_item_details
        self.add_item(self.details_button)
        
        if self.type in ["Weapon", "Equipment"]:
            self.details_button1 = discord.ui.Button(label="Stat Details", style=discord.ButtonStyle.secondary)
            self.details_button1.callback = self.open_item_details1
            self.add_item(self.details_button1)
        
        self.submit_button = discord.ui.Button(label="Submit", style=discord.ButtonStyle.success)
        self.submit_button.callback = self.submit_item
        self.add_item(self.submit_button)


        self.reset_button = discord.ui.Button(label="Reset", style=discord.ButtonStyle.danger)
        self.reset_button.callback = self.reset_entry
        self.add_item(self.reset_button)
        
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.author
    
    async def open_item_details(self, interaction: discord.Interaction):
        modal = ItemDetailsModal(parent_view=self)
        await interaction.response.send_modal(modal)

    async def open_item_details1(self, interaction: discord.Interaction):
        modal1 = ItemDetailsModal2(parent_view=self)
        await interaction.response.send_modal(modal1)
        
    async def reset_entry(self, interaction: discord.Interaction):
        """Cancel the item entry and close the view."""
        await interaction.response.send_message("❌ Item entry canceled.", ephemeral=True)
        self.stop()    




    async def submit_item(self, interaction: discord.Interaction):
	    # Convert lists to space-separated strings
	    classes_str = " ".join(self.usable_classes)
	    race_str = " ".join(self.usable_race)
	    slot_str = " ".join(self.slot)
	    donor = self.donated_by or "Anonymous"
	    added_by = str(interaction.user)
	
	    # Base fields to update/add
	    fields_to_update = {
	        "name": self.item_name,
	        "type": self.type,
	        "subtype": self.subtype,
	        "slot": slot_str,
	        "size": self.size,
	        "stats": self.stats,
	        "weight": self.weight,
	        "classes": classes_str,
	        "race": race_str,
	        "donated_by": donor,
	        "added_by": added_by
	    }
	
	    # Only include relevant fields per item type
	    if self.type == "Weapon":
	        fields_to_update.update({"attack": self.attack, "delay": self.delay, "effects": self.effects})
	    elif self.type == "Equipment":
	        fields_to_update.update({"ac": self.ac, "effects": self.effects})
	    elif self.type == "Consumable":
	        fields_to_update.update({"effects": self.effects})
	
	    def draw_item_text(background, item_name, type, subtype, size, slot, stats, weight, effects, donated_by):
	        draw = ImageDraw.Draw(background)
	
	        # Load fonts
	        font_title = ImageFont.truetype("assets/WinthorpeScB.ttf", 28)
	        font_type = ImageFont.truetype("assets/Winthorpe.ttf", 20)
	        font_slot = ImageFont.truetype("assets/Winthorpe.ttf", 16)
	        font_size = ImageFont.truetype("assets/Winthorpe.ttf", 16)
	        font_stats = ImageFont.truetype("assets/Winthorpe.ttf", 16)
	        font_weight = ImageFont.truetype("assets/Winthorpe.ttf", 16)
	        font_effects = ImageFont.truetype("assets/Winthorpe.ttf", 16)
	        font_ac = ImageFont.truetype("assets/WinthorpeB.ttf", 16)
	        font_attack = ImageFont.truetype("assets/Winthorpe.ttf", 16)
	        font_class = ImageFont.truetype("assets/WinthorpeB.ttf", 16)
	        font_race = ImageFont.truetype("assets/WinthorpeB.ttf", 16)
	
	        width, height = background.size
	        x_margin = 40
	        y = 3
	        x = 110
	
	        draw.text((x_margin, y), f"{item_name}", fill=(255, 255, 255), font=font_title)
	        y += 50
	
	        if self.type in ("Equipment"):
	            slot = " ".join(sorted(self.slot))
	            draw.text((x, y), f"Slot: {slot}", fill=(255, 255, 255), font=font_ac)
	            y += 25
	
	            if self.ac != "":
	                ac = self.ac
	                draw.text((x, y), f"AC: {ac}", fill=(255, 255, 255), font=font_ac)
	                y += 25
	
	        if self.type in ("Weapon"):
	            slot = " ".join(sorted(self.slot)).upper()
	            draw.text((x, y), f"Slot: {slot}", fill=(255, 255, 255), font=font_ac)
	            y += 25
	
	            if self.attack != "":
	                attack = self.attack
	                delay = self.delay
	                draw.text((x, y), f"Weapon DMG: {attack} ATK Delay: {delay}", fill=(255, 255, 255), font=font_attack)
	                y += 25
	
	        if self.type in ("Equipment", "Weapon"):
	            if self.stats != "":
	                stats_text = stats
	                draw.text((x, y), stats_text, fill=(255, 255, 255), font=font_stats)
	                bbox = draw.textbbox((x, y), stats_text, font=font_stats)
	                text_height = bbox[3] - bbox[1]
	                y += text_height + 15
	
	            if self.effects != "":
	                effects_text = effects
	                draw.text((x, y), effects_text, fill=(255, 255, 255), font=font_effects)
	                bbox = draw.textbbox((x, y), effects_text, font=font_effects)
	                text_height = bbox[3] - bbox[1]
	                y += text_height + 15
	
	        if self.type in ("Consumable"):
	            if self.stats != "":
	                stats_text = stats
	                draw.text((x, y), stats_text, fill=(255, 255, 255), font=font_stats)
	                bbox = draw.textbbox((x, y), stats_text, font=font_stats)
	                text_height = bbox[3] - bbox[1]
	                y += text_height + 15
	
	        if self.subtype in ("Potion", "Scroll"):
	            if self.effects != "":
	                draw.text((x, y), f"Effects: {effects}", fill=(255, 255, 255), font=font_effects)
	                y += 25
	
	        if self.subtype in ("Drink", "Food", "Other"):
	            if self.effects != "":
	                effects_text = effects
	                draw.text((x, y), effects_text, fill=(255, 255, 255), font=font_effects)
	                bbox = draw.textbbox((x, y), effects_text, font=font_effects)
	                text_height = bbox[3] - bbox[1]
	                y += text_height + 15
	
	        if self.type in ("Crafting", "Misc"):
	            if self.effects != "":
	                effects_text = effects
	                draw.text((x, y), effects_text, fill=(255, 255, 255), font=font_effects)
	                bbox = draw.textbbox((x, y), effects_text, font=font_effects)
	                text_height = bbox[3] - bbox[1]
	                y += text_height + 15
	
	            if self.size != "" and self.weight != "":
	                draw.text((x, y), f"Weight:Size: {size.upper()}", fill=(255, 255, 255), font=font_size)
	                y += 25
	
	            if self.size != "" and self.weight == "":
	                draw.text((x, y), f"Size: {size.upper()}", fill=(255, 255, 255), font=font_size)
	                y += 25
	
	            if self.size == "" and self.weight != "":
	                draw.text((x, y), f"Weight: {weight}", fill=(255, 255, 255), font=font_size)
	                y += 25
	
	        if self.type in ("Crafting", "Misc"):
	            if self.stats != "":
	                stats_text = stats
	                draw.text((x, y), stats_text, fill=(255, 255, 255), font=font_stats)
	                bbox = draw.textbbox((x, y), stats_text, font=font_stats)
	                text_height = bbox[3] - bbox[1]
	                y += text_height + 15
	
	        if self.type in ("Equipment", "Weapon"):
	            if self.usable_classes:
	                classes = " ".join(sorted(self.usable_classes))
	                draw.text((x, y), f"Class: {classes.upper()}", fill=(255, 255, 255), font=font_effects)
	                y += 25
	
	            if self.usable_race:
	                race = " ".join(sorted(self.usable_race))
	                draw.text((x, y), f"Race: {race.upper()}", fill=(255, 255, 255), font=font_effects)
	                y += 25
	
	        return background
	
	    async with self.db_pool.acquire() as conn:
	        if self.item_id:
	            old_item = await conn.fetchrow(
	                "SELECT id, created_images, upload_message_id FROM inventory WHERE id=$1",
	                self.item_id
	            )
	
	            if old_item and old_item['upload_message_id']:
	                try:
	                    upload_channel = await ensure_upload_channel(interaction.guild)
	                    old_msg = await upload_channel.fetch_message(old_item['upload_message_id'])
	                    await old_msg.delete()
	                except discord.NotFound:
	                    pass
	
	            bg_path = BG_FILES.get(self.type, BG_FILES["Misc"])
	            background = Image.open(bg_path).convert("RGBA")
	
	            background = draw_item_text(
	                background,
	                self.item_name,
	                self.type,
	                self.subtype,
	                self.size,
	                self.slot,
	                self.stats,
	                self.weight,
	                self.effects,
	                self.donated_by
	            )
	            created_images = io.BytesIO()
	            background.save(created_images, format="PNG")
	            created_images.seek(0)
	
	            upload_channel = await ensure_upload_channel(interaction.guild)
	            file = discord.File(created_images, filename=f"{self.item_name}.png")
	            message = await upload_channel.send(file=file, content=f"Created by {added_by}")
	            cdn_url = message.attachments[0].url
	
	            fields_to_update["created_images"] = cdn_url
	            fields_to_update["upload_message_id"] = message.id
	            fields_to_update["created_at1"] = datetime.utcnow()
	
	            await update_item_db(
	                guild_id=interaction.guild.id,
	                item_id=self.item_id,
	                **fields_to_update
	            )
	
	            embed = discord.Embed(title=f"{self.item_name}", color=discord.Color.blue())
	            embed.set_image(url=cdn_url)
	
	            await interaction.response.send_message(
	                content=f"✅ Updated **{self.item_name}**.",
	                embed=embed,
	                ephemeral=True
	            )
	
	        else:
	            bg_path = BG_FILES.get(self.type, BG_FILES["Misc"])
	            background = Image.open(bg_path).convert("RGBA")
	
	            background = draw_item_text(
	                background,
	                self.item_name,
	                self.type,
	                self.subtype,
	                self.size,
	                self.slot,
	                self.stats,
	                self.weight,
	                self.effects,
	                self.donated_by
	            )
	
	            created_images = io.BytesIO()
	            background.save(created_images, format="PNG")
	            created_images.seek(0)
	
	            upload_channel = await ensure_upload_channel(interaction.guild)
	            file = discord.File(created_images, filename=f"{self.item_name}.png")
	            message = await upload_channel.send(file=file, content=f"Created by {added_by}")
	            cdn_url = message.attachments[0].url
	
	            await add_item_db(
	                guild_id=interaction.guild.id,
	                name=self.item_name,
	                type=self.type,
	                size=self.size,
	                subtype=self.subtype,
	                slot=" ".join(self.slot),
	                stats=self.stats,
	                weight=self.weight,
	                classes=" ".join(self.usable_classes),
	                race=" ".join(self.usable_race),
	                image=None,
	                created_images=cdn_url,
	                donated_by=self.donated_by,
	                qty=1,
	                added_by=str(interaction.user),
	                attack=self.attack,
	                delay=self.delay,
	                effects=self.effects,
	                ac=self.ac,
	                upload_message_id=message.id
	            )
	
	            embed = discord.Embed(title=f"{self.item_name}", color=discord.Color.blue())
	            embed.set_image(url=cdn_url)
	
	            await interaction.response.send_message(
	                content=f"✅ Added **{self.item_name}** to the Guild Bank (manual image created).",
	                embed=embed,
	                ephemeral=True
	            )
	
	    self.stop()


#-----IMAGE UPLOAD ----

class ImageDetailsModal(discord.ui.Modal):
    def __init__(self, interaction: discord.Interaction, view=None, item_row=None, is_edit: bool = False):
        """
        Unified modal for adding or editing an image item.
        """
        super().__init__(title="Image Item Details")
        self.interaction = interaction
        self.view = view
        self.is_edit = item_row is not None
        self.item_row = item_row

        if self.is_edit:
            self.item_id = item_row['id']
            self.guild_id = item_row['guild_id']
            default_name = item_row['name']
            default_donor = item_row.get('donated_by') or "Anonymous"
        else:
            self.item_id = None
            self.guild_id = interaction.guild.id
            default_name = ""
            default_donor = ""

        # Item Name
        self.item_name = discord.ui.TextInput(label="Item Name", placeholder="Example: Flowing Black Silk Sash", default=default_name, required=True)
        self.add_item(self.item_name)

        # Donated By
        self.donated_by = discord.ui.TextInput(label="Donated By", placeholder="Example: Thieron or Raid", default=default_donor, required=False)
        self.add_item(self.donated_by)

    async def on_submit(self, modal_interaction: discord.Interaction):
        item_name = self.item_name.value
        donated_by = self.donated_by.value or "Anonymous"
        added_by = str(modal_interaction.user)

        upload_channel = await ensure_upload_channel(modal_interaction.guild)
          
        # Handle the image
        image_url = None
        if self.view and getattr(self.view, "image", None):
            # If image is bytes, upload directly
            if isinstance(self.view.image, (bytes, bytearray)):
                file = discord.File(io.BytesIO(self.view.image), filename=f"{item_name}.png")
                message = await upload_channel.send(file=file, content=f"Uploaded by {added_by}")
                image_url = message.attachments[0].url
        
            # If image is already a URL (string)
            elif isinstance(self.view.image, str):
                # Download and re-upload so it’s permanent in your upload-log
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.view.image) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            file = discord.File(io.BytesIO(data), filename=f"{item_name}.png")
                            message = await upload_channel.send(file=file, content=f"Uploaded by {added_by}")
                            image_url = message.attachments[0].url
                        else:
                            await modal_interaction.response.send_message(
                                f"❌ Failed to download image from provided URL.", ephemeral=True
                            )
                            return
        
        elif modal_interaction.message and modal_interaction.message.attachments:
            # If user uploaded a Discord attachment directly
            attachment = modal_interaction.message.attachments[0]
            message = await upload_channel.send(
                content=f"Uploaded by {added_by}",
                file=await attachment.to_file()
            )
            image_url = message.attachments[0].url

        if self.is_edit and not image_url:
            image_url = self.item_row["image"] 
			
        if not self.is_edit and not image_url:
            await modal_interaction.response.send_message(
                "❌ No image provided. Please attach or send an image.", ephemeral=True
            )
            return

        # Save to database
        if self.is_edit:
            await update_item_db(
                guild_id=self.guild_id,
                item_id=self.item_id,
                name=item_name,
                donated_by=donated_by,
                image=image_url,
                added_by=added_by
            )
            await modal_interaction.response.send_message(f"✅ Updated **{item_name}**.", ephemeral=True)
        else:
            await add_item_db(
                guild_id=self.guild_id,
                name=item_name,
                type="Image",
                subtype="Image",
                size="",
                slot="",
                stats="",
                weight="",
                classes="",
                race="",
                image=image_url,
                donated_by=donated_by,
                qty=1,
                added_by=added_by,
                upload_message_id=message.id
            )
            await modal_interaction.response.send_message(
                f"✅ Image item **{item_name}** added to the guild bank!", ephemeral=True
            )



# ------ITEM DETAILS ----
class ItemDetailsModal(discord.ui.Modal):
    def __init__(self, parent_view):
        super().__init__(title=f"{parent_view.type} Details")
        
        self.parent_view = parent_view
        
        self.item_name = discord.ui.TextInput(
                label="Item Name", placeholder="Example: Flowing Black Silk Sash", default=parent_view.item_name, required=True
        )
        self.add_item(self.item_name)
        
        # Weapon ATTACK/DELAY
        if parent_view.type == "Weapon":

            self.attack = discord.ui.TextInput(
                label="Damage", placeholder="Example: 7", default=parent_view.attack, required=False
            )
            self.delay = discord.ui.TextInput(
                label="Delay", placeholder="Example: 28", default=parent_view.delay, required=False
            )
            self.add_item(self.attack)
            self.add_item(self.delay)


        # Equipment AC
        if parent_view.type == "Equipment":

            self.ac = discord.ui.TextInput(
                label="Armor Class", placeholder="Example: 15", default=parent_view.ac, required=True
            )
            self.add_item(self.ac)

         
        if parent_view.type == "Consumable":
         # STATS
            self.stats = discord.ui.TextInput(
                label="Stats", default=parent_view.stats, placeholder="Example: STR:+1 STA:+3 CHA:-1", required=False, style=discord.TextStyle.paragraph
            )
    
        #  EFFECTS

            self.effects = discord.ui.TextInput(
                label="Effects", default=parent_view.effects, placeholder="Minor Serum of Dexerity: increases dex by 5 for 1 hour", required=False, style=discord.TextStyle.paragraph
            )  

            self.add_item(self.stats)
            self.add_item(self.effects)

        if self.parent_view.type in ("Crafting","Misc"):
        # STATS
            self.stats = discord.ui.TextInput(
                label="Info", default=parent_view.stats, placeholder="Basic information about the item", required=False, style=discord.TextStyle.paragraph
            )
    
        #  EFFECTS

            self.effects = discord.ui.TextInput(
                label="Effects", default=parent_view.effects, placeholder="Basic information if the item has an effect", required=False, style=discord.TextStyle.paragraph
            )
                        
            self.add_item(self.stats)
            self.add_item(self.effects)

        

        self.weight = discord.ui.TextInput(
                    label="Weight", default=parent_view.weight, placeholder="Example: 1.0", required=False
        )
        self.donated_by = discord.ui.TextInput(
                label="Donated By", default=parent_view.donated_by, placeholder="Example:Thieron or Raid", required=False
        )

       
        self.add_item(self.weight)
        self.add_item(self.donated_by)


    async def on_submit(self, interaction: discord.Interaction):
        # Save values back to the view
        self.parent_view.item_name = self.item_name.value
        self.parent_view.weight = self.weight.value
        self.parent_view.donated_by = self.donated_by.value or "Anonymous"

        if self.parent_view.type == "Weapon":
            self.parent_view.attack = self.attack.value
            self.parent_view.delay = self.delay.value
        if self.parent_view.type == "Equipment":
            self.parent_view.ac = self.ac.value
        
        if self.parent_view.type in ("Crafting", "Consumable","Misc"):
      
            self.parent_view.stats = self.stats.value
            self.parent_view.effects = self.effects.value


        await interaction.response.send_message(
            "✅ Details saved. Click Submit when ready or Stat Details.", ephemeral=True
        )

            
class ItemDetailsModal2(discord.ui.Modal):
    def __init__(self, parent_view):
        super().__init__(title=f"{parent_view.type} Details")
        
        self.parent_view = parent_view

         #  STATS
        if parent_view.type == "Weapon" or "Equipment" or "Consumable":

            self.stats = discord.ui.TextInput(
                label="Stats", default=parent_view.stats, placeholder="Example: STR:+3 WIS:+4 INT:-1", required=False, style=discord.TextStyle.paragraph
            )
    
        #  EFFECTS

            self.effects = discord.ui.TextInput(
                label="Effects", default=parent_view.effects, placeholder="Example: Lesser Spellshield, ", required=False, style=discord.TextStyle.paragraph
            )

            
            self.add_item(self.stats)
            self.add_item(self.effects)



    async def on_submit(self, interaction: discord.Interaction):
        # Save values back to the view   
        if self.parent_view.type == "Weapon" or "Equipment" or"Consumable":
            self.parent_view.stats = self.stats.value
            self.parent_view.effects = self.effects.value

        await interaction.response.send_message(
            "✅ Details saved. Click Submit when ready, or Add Required Details.", ephemeral=True
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




class RemoveItemModal(discord.ui.Modal, title="Remove Item"):
    def __init__(self, item, db_pool):
        super().__init__()
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







# ---------- /view_bank Command ----------

@bot.tree.command(name="view_bank", description="View all items in the guild bank.")
async def view_bank(interaction: discord.Interaction):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM inventory WHERE guild_id=$1 AND qty >= 1 ORDER BY name",
            interaction.guild.id
        )

    if not rows:
        await interaction.response.send_message("Guild bank is empty.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    TYPE_COLORS = {
        "weapon": discord.Color.red(),
        "equipment": discord.Color.blue(),
        "consumable": discord.Color.gold(),
        "crafting": discord.Color.green(),
        "misc": discord.Color.dark_gray(),
    }

    def code_block(text: str) -> str:
        text = (text or "").strip()
        return f"```{text}```" if text else "```None```"

    async def build_embed_with_file(row):
        type = (row.get('type') or "Misc").lower()
        name = row.get('name')

        donated_by = row.get('donated_by') or "Anonymous"


        embed = discord.Embed(
            color=TYPE_COLORS.get(type, discord.Color.blurple())
        )
        embed.set_footer(text=f"Donated by: {donated_by} | {name}")
                            
        # Handle uploaded images (URL)
        if row.get('image'):
            embed.set_image(url=row['image'])
            return embed, None

              # Handle uploaded created_images (URL)
        if row.get('created_images'):
            embed.set_image(url=row['created_images'])
            return embed, None

    # Send embeds
    for row in rows:
        embed, files = await build_embed_with_file(row)
        if isinstance(files, list):
            await interaction.channel.send(embed=embed, files=files)
        elif isinstance(files, discord.File):
            await interaction.channel.send(embed=embed, file=files)
        else:
            await interaction.channel.send(embed=embed)

    await interaction.followup.send(f"✅ Sent {len(rows)} items.", ephemeral=True)



# ---------- /add_item Command ----------

@bot.tree.command(name="add_item", description="Add a new item to the guild bank.")
@app_commands.describe(type="Type of the item", image="Optional image upload")
@app_commands.choices(type=[
    app_commands.Choice(name="Equipment", value="Equipment"),
    app_commands.Choice(name="Crafting", value="Crafting"),
    app_commands.Choice(name="Consumable", value="Consumable"),
    app_commands.Choice(name="Misc", value="Misc"),
    app_commands.Choice(name="Weapon", value="Weapon")
])
async def add_item(interaction: discord.Interaction, type: str, image: discord.Attachment = None):
    view = ItemEntryView(interaction.user, type=type, db_pool=db_pool)
    active_views[interaction.user.id] = view  # Track this view

    # If an image was uploaded, attach it to the view
    if image:
        view.image = image.url
        view.waiting_for_image = False
        # Optional: open the minimal modal for donated_by and item name
        await interaction.response.send_modal(ImageDetailsModal(interaction, view=view))
    else:
        # Just show the view with dropdowns for subtype/classes
        await interaction.response.send_message(f"Adding a new {type}:", view=view, ephemeral=True)



@bot.tree.command(name="edit_item", description="Edit an existing item in the guild bank.")
@app_commands.describe(item_name="Name of the item to edit")
async def edit_item(interaction: discord.Interaction, item_name: str):
    
    guild_id = interaction.guild.id

    # 1️⃣ Fetch the item record
    item = await get_item_by_name(guild_id, item_name)
    if not item:
        await interaction.followup.send("❌ Item not found.", ephemeral=True)
        return

    # 2️⃣ Uploaded image item — open simple modal
    if item.get("image") and not item.get("created_images"):
        modal = ImageDetailsModal(interaction, item_row=item, is_edit=True)
        await interaction.response.send_modal(modal)
        return

    # 3️⃣ Created/generated item — reopen full ItemEntryView flow
    if item.get("created_images"):
        await interaction.response.defer(ephemeral=True)
        view = ItemEntryView(
	        db_pool=db_pool,
	        author=interaction.user,
	        type=type,
	        item_id=item["id"],
	        existing_data=item,
	        is_edit=True
	    )

    # Let the user know this is edit mode
    await interaction.followup.send(
        content=f"🛠 Editing **{item['name']}**. You can adjust fields and re-submit to update the item.",
        view=view,
        ephemeral=True
    )





@bot.tree.command(name="remove_item", description="Remove an item from the guild bank.")
@app_commands.describe(item_name="Name of the item to remove")
async def remove_item(interaction: discord.Interaction, item_name: str):
    async with db_pool.acquire() as conn:
        item = await conn.fetchrow(
            "SELECT * FROM inventory WHERE guild_id=$1 AND name=$2 AND qty=1",
            interaction.guild.id,
            item_name
        )

    if not item:
        await interaction.response.send_message(
            "❌ Item not found or already removed.", ephemeral=True
        )
        return

    # 🧾 Open modal to capture removal reason
    modal = RemoveItemModal(item=item, db_pool=db_pool)
    await interaction.response.send_modal(modal)





@bot.tree.command(name="view_itemhistory", description="View guild item donation stats.")
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
    donated_at = donated_at or date.today.datetime()  # Use today if not provided
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO funds (guild_id, type, total_copper, donated_by, donated_at)
            VALUES ($1, $2, $3, $4, $5)
        ''',guild_id, type, total_copper, donated_by, donated_at)

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
            donated_at=datetime.date.today()
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
            donated_at=datetime.date.today()
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





