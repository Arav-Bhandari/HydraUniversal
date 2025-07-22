import discord
from discord import app_commands
from discord.ext import commands
import json
import logging
import aiohttp
# Removed: from utils.permissions import can_use_command
from utils.embeds import EmbedBuilder # Assuming EmbedBuilder handles COLORS, THUMBNAILS, EMOJI

logger = logging.getLogger('bot.self_edit')

SETTINGS_FILE = "data/self_edit.json"

def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Initialize with empty settings if file not found or invalid
        logger.warning(f"{SETTINGS_FILE} not found or invalid. Initializing empty settings.")
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump({}, f, indent=4)
        except Exception as e_create:
            logger.error(f"Failed to create {SETTINGS_FILE}: {e_create}")
        return {}

def save_settings(settings):
    try:
        import os
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save {SETTINGS_FILE}: {e}")

class CustomizeView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180) # Increased timeout slightly
        self.bot = bot
        self.user_id = user_id # User who initiated the command

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not for you!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Status", style=discord.ButtonStyle.primary, emoji="📡")
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StatusModal(self.bot))

    @discord.ui.button(label="PFP", style=discord.ButtonStyle.secondary, emoji="🖼️")
    async def pfp_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PFPModal(self.bot))

    @discord.ui.button(label="Nickname", style=discord.ButtonStyle.green, emoji="✍️") # Changed from secondary
    async def nickname_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NicknameModal(self.bot))

class StatusModal(discord.ui.Modal, title="Customize Bot Status"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.activity_type_select = discord.ui.Select( # Renamed for clarity
            placeholder="Select activity type",
            options=[
                discord.SelectOption(label="Playing", value="playing", description="Set status to 'Playing...'"),
                discord.SelectOption(label="Watching", value="watching", description="Set status to 'Watching...'"),
                discord.SelectOption(label="Listening to", value="listening", description="Set status to 'Listening to...'"), # Clarified label
            ]
        )
        self.activity_text_input = discord.ui.TextInput( # Renamed for clarity
            label="Activity Text",
            placeholder="e.g., 'the markets' or 'the game'",
            max_length=100,
            required=True
        )
        self.status_type_select = discord.ui.Select( # Renamed for clarity
            placeholder="Select online status",
            options=[
                discord.SelectOption(label="Online", value="online"),
                discord.SelectOption(label="Idle", value="idle"),
                discord.SelectOption(label="Do Not Disturb", value="dnd", emoji="⛔"),
            ]
        )
        self.add_item(self.activity_type_select)
        self.add_item(self.activity_text_input)
        self.add_item(self.status_type_select)

    async def on_submit(self, interaction: discord.Interaction):
        activity_type_val = self.activity_type_select.values[0]
        activity_text_val = self.activity_text_input.value
        status_type_val = self.status_type_select.values[0]

        activity = None
        if activity_type_val == "playing": activity = discord.Game(name=activity_text_val)
        elif activity_type_val == "watching": activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text_val)
        elif activity_type_val == "listening": activity = discord.Activity(type=discord.ActivityType.listening, name=activity_text_val)

        status = discord.Status.online # Default
        if status_type_val == "idle": status = discord.Status.idle
        elif status_type_val == "dnd": status = discord.Status.dnd

        try:
            await self.bot.change_presence(activity=activity, status=status)
            settings = load_settings()
            bot_id_str = str(self.bot.user.id) # Ensure bot_id is string for JSON keys
            settings[bot_id_str] = settings.get(bot_id_str, {}) # Initialize if not exist
            settings[bot_id_str].update({ # Use update for cleaner modification
                "activity_type": activity_type_val,
                "activity_text": activity_text_val,
                "status_type": status_type_val
            })
            save_settings(settings)
            embed = EmbedBuilder.success("Status Updated", f"Status: **{status_type_val.capitalize()}**\nActivity: **{activity_type_val.capitalize()} {activity_text_val}**")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to update status: {e}", exc_info=True)
            embed = EmbedBuilder.error("Status Update Failed", f"An error occurred: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

class PFPModal(discord.ui.Modal, title="Customize Bot PFP"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.pfp_url_input = discord.ui.TextInput( # Renamed
            label="PFP URL",
            placeholder="Enter direct image URL (PNG/JPG/GIF)",
            max_length=256 # Increased length
        )
        self.add_item(self.pfp_url_input)

    async def on_submit(self, interaction: discord.Interaction):
        pfp_url_val = self.pfp_url_input.value
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(pfp_url_val) as resp:
                    if resp.status != 200: raise ValueError(f"URL fetch failed (Status: {resp.status})")
                    if not resp.content_type.startswith('image/'): raise ValueError("URL is not a direct image link.")
                    image_data = await resp.read()

            await self.bot.user.edit(avatar=image_data)
            settings = load_settings()
            bot_id_str = str(self.bot.user.id)
            settings[bot_id_str] = settings.get(bot_id_str, {})
            settings[bot_id_str]["pfp_url"] = pfp_url_val # Save URL for persistence if needed
            save_settings(settings)
            embed = EmbedBuilder.success("PFP Updated", "Bot profile picture updated successfully.")
            embed.set_thumbnail(url=pfp_url_val) # Show new PFP
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to update PFP: {e}", exc_info=True)
            embed = EmbedBuilder.error("PFP Update Failed", f"An error occurred: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

class NicknameModal(discord.ui.Modal, title="Customize Bot Nickname"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.nickname_input = discord.ui.TextInput( # Renamed
            label="Nickname",
            placeholder="Enter new nickname (blank to reset)",
            max_length=32,
            required=False # Allow empty to reset
        )
        self.add_item(self.nickname_input)

    async def on_submit(self, interaction: discord.Interaction):
        nickname_val = self.nickname_input.value or None
        if not interaction.guild: # Should always have guild for this command
            await interaction.response.send_message(embed=EmbedBuilder.error("Error", "Guild context not found."),ephemeral=True)
            return
        try:
            await interaction.guild.me.edit(nick=nickname_val)
            settings = load_settings()
            bot_id_str = str(self.bot.user.id)
            settings[bot_id_str] = settings.get(bot_id_str, {})
            # Store nickname per guild if needed, or globally if that's the intent
            # For this example, assuming a global "default" nickname setting for the bot.
            # If per-guild, key should include guild.id: settings[bot_id_str]['nicknames'][str(interaction.guild.id)]
            settings[bot_id_str]["nickname_default"] = nickname_val
            save_settings(settings)
            embed = EmbedBuilder.success("Nickname Updated", f"Bot nickname set to **{nickname_val or 'Default'}** in this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = EmbedBuilder.error("Nickname Update Failed", "Bot lacks permission to change its nickname here.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to update nickname: {e}", exc_info=True)
            embed = EmbedBuilder.error("Nickname Update Failed", f"An error occurred: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

class SelfEdit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.wait_until_ready() # Ensure bot is fully ready
        settings = load_settings()
        bot_id_str = str(self.bot.user.id)
        bot_settings = settings.get(bot_id_str, {})

        if "activity_type" in bot_settings and "activity_text" in bot_settings:
            activity_type = bot_settings["activity_type"]
            activity_text = bot_settings["activity_text"]
            status_type = bot_settings.get("status_type", "online")

            activity = None
            if activity_type == "playing": activity = discord.Game(name=activity_text)
            elif activity_type == "watching": activity = discord.Activity(type=discord.ActivityType.watching, name=activity_text)
            elif activity_type == "listening": activity = discord.Activity(type=discord.ActivityType.listening, name=activity_text)

            status = discord.Status.online
            if status_type == "idle": status = discord.Status.idle
            elif status_type == "dnd": status = discord.Status.dnd

            if activity or status != discord.Status.online: # Apply only if there's something to change
                try:
                    await self.bot.change_presence(activity=activity, status=status)
                    logger.info(f"Applied saved status: {status_type}, Activity: {activity_type} {activity_text}")
                except Exception as e:
                    logger.error(f"Failed to apply saved status on cog_load: {e}", exc_info=True)

        # Applying PFP on load is complex due to rate limits and global nature.
        # Generally, PFP is set once and persists. Re-applying via URL on every load isn't typical.
        # Nickname is per-guild, also usually set manually or by other specific commands.
        # This cog_load primarily focuses on restoring presence (status/activity).

    # @app_commands.check(can_use_command) # REMOVED this decorator
    @app_commands.command(name="customize", description="Customize the bot's appearance and status (Server Owner Only)")
    async def customize(self, interaction: discord.Interaction):
        if not interaction.guild: # Should be redundant for guild commands
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Error", "This command can only be used in a server."),
                ephemeral=True
            )
            return

        # ADDED Server Owner Check
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Permission Denied", "Only the server owner can use this command."),
                ephemeral=True
            )
            return

        # Using more generic/appropriate EmbedBuilder keys
        embed_title = f"{EmbedBuilder.EMOJI.get('settings','⚙️')} Bot Customization" # Fallback emoji
        embed_color = discord.Color(EmbedBuilder.COLORS.get('info', 0x5865F2)) # Fallback color
        thumbnail_url = EmbedBuilder.THUMBNAILS.get('settings') # Use a generic settings icon

        embed = discord.Embed(
            title=embed_title,
            description="Choose an option to customize the bot's appearance or status.",
            color=embed_color
        )
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)

        view = CustomizeView(self.bot, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @customize.error
    async def customize_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # This handler might now be less frequently hit for this specific command's permission,
        # as the owner check is direct and returns early.
        # However, it's good for other potential errors or if other checks were ever added.
        if isinstance(error, app_commands.CheckFailure):
            # This message is generic. The direct owner check provides a more specific message.
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Permission Denied", "You do not have the required permissions to use this command."),
                ephemeral=True
            )
        # Handle other potential app command errors specifically if needed
        # elif isinstance(error, app_commands.CommandInvokeError) and isinstance(error.original, MyCustomException):
        #    # handle MyCustomException
        else:
            logger.error(f"Error in /customize command: {error} - Type: {type(error)}", exc_info=True)
            # Send a generic error message for other unhandled errors
            # Using error.original might expose too much detail in some cases.
            # For now, a simple message.
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Error", f"An unexpected error occurred. Please try again later."),
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(SelfEdit(bot))
    logger.info("SelfEdit Cog loaded.")