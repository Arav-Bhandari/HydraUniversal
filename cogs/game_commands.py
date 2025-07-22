import discord
import logging
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone
import pytz
from PIL import Image, ImageDraw, ImageFont
import io
import os
import csv
import asyncio

# --- Utility Imports ---
from utils.config import get_server_config, load_json, save_json
from utils.permissions import has_referee_role, has_streamer_role, is_admin, has_statistician_role
from utils.logging import log_action
from utils.embeds import EmbedBuilder

logger = logging.getLogger("bot.games")

# --- Constants and File Paths ---
GAMES_DATA_FILE = "data/games.json"
os.makedirs("data", exist_ok=True)
if not os.path.exists(GAMES_DATA_FILE):
    save_json(GAMES_DATA_FILE, {})
    logger.info(f"Created empty games data file: {GAMES_DATA_FILE}")

GAME_TIMEZONE = pytz.timezone("America/New_York")

# --- GameCommands Cog ---
class GameCommands(commands.Cog):
    """
    Manages game scheduling, cancellation, streaming information, and role assignments
    for referees and streamers within the league. Provides intuitive autocompletion
    and confirmation prompts for robust game management.
    """
    def __init__(self, bot):
        self.bot = bot

    async def has_game_command_permission(self, user: discord.Member, guild_id: int) -> bool:
        """Check if the user has permission to use game commands (Franchise Owner, GM, HC, AC, or generic staff/commissioner roles)."""
        config = get_server_config(guild_id)
        permission_settings = config.get("permission_settings", {})
        authorized_role_keys = ["fo_roles", "gm_roles", "hc_roles", "ac_roles"]
        authorized_role_ids = [str(rid) for role_key in authorized_role_keys for rid in permission_settings.get(role_key, []) if rid]
        
        user_role_ids = [str(role.id) for role in user.roles]
        has_authorized_role = any(role_id in user_role_ids for role_id in authorized_role_ids)
        
        if not has_authorized_role:
            for role in user.roles:
                if any(term in role.name.lower() for term in ["staff", "commissioner"]):
                    return True
        return has_authorized_role

    async def team_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id: return []
        config = get_server_config(interaction.guild_id)
        team_data_new = config.get("team_data", {}).keys()
        team_roles_legacy = config.get("team_roles", {}).keys()
        all_teams = sorted(list(set(team_data_new) | set(team_roles_legacy)))
        return [
            app_commands.Choice(name=team, value=team)
            for team in all_teams
            if current.lower() in team.lower()
        ][:25]

    async def day_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        days = ["Today", "Tomorrow", "In 2 days", "In 3 days", "In 4 days", "In 5 days", "In 6 days", "In 7 days"]
        return [
            app_commands.Choice(name=day, value=day)
            for day in days
            if current.lower() in day.lower()
        ][:25]

    async def time_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        times = [f"{h:01d}:{m:02d} {'AM' if h < 12 else 'PM'}" for h in range(1, 13) for m in [0, 15, 30, 45]]
        times = [t.replace('0:00 AM', '12:00 AM').replace('12:00 PM', '12:00 PM') if '0:00' in t else t for t in times]
        formatted_times = []
        for t in times:
            parts = t.split()
            hour_minute = parts[0]
            am_pm = parts[1]
            h, m = map(int, hour_minute.split(':'))
            if h == 0: h = 12
            formatted_times.append(f"{h}:{m:02d} {am_pm}")
        return [
            app_commands.Choice(name=time, value=time)
            for time in formatted_times
            if current.lower() in time.lower()
        ][:25]

    def hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        try:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        except (ValueError, TypeError):
            logger.error(f"Invalid hex color format provided: {hex_color}. Returning black.")
            return (0, 0, 0)

    def generate_clash_gif(self, team1_color_hex: str, team2_color_hex: str, team1_emoji: str, team2_emoji: str):
        width, height = 200, 100
        duration_ms = 300
        frames = []
        try:
            try:
                font = ImageFont.truetype("arial.ttf", 30)
            except IOError:
                logger.warning("Arial font not found. Using default PIL font.")
                font = ImageFont.load_default()
        except Exception as e:
            logger.error(f"Critical error loading font for GIF generation: {e}")
            font = ImageFont.load_default()

        team1_rgb = self.hex_to_rgb(team1_color_hex)
        team2_rgb = self.hex_to_rgb(team2_color_hex)
        fallback_emoji1 = "T1" if not team1_emoji or len(team1_emoji) > 5 else team1_emoji
        fallback_emoji2 = "T2" if not team2_emoji or len(team2_emoji) > 5 else team2_emoji

        for frame_index in range(10):
            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            progress = frame_index / 9.0
            mid_x, mid_y = width // 2, height // 2
            t1_scale = 1 - (progress * 0.6) if progress < 0.5 else 1 - (0.3 + (progress - 0.5) * 0.8)
            t1_offset_x = 0.3 * progress if progress < 0.5 else 0.15 + (progress-0.5)*0.6
            t1_offset_y = 0.3 * (1-progress) if progress < 0.5 else 0.15 + (progress-0.5)*0.4
            draw.polygon([
                (mid_x - width * t1_offset_x, mid_y - height * t1_offset_y),
                (mid_x - width * t1_offset_x - width*0.15, mid_y + height * t1_offset_y),
                (mid_x + width * t1_offset_x, mid_y - height * t1_offset_y)
            ], fill=team1_rgb)
            t2_scale = 1 - (progress * 0.6) if progress < 0.5 else 1 - (0.3 + (progress - 0.5) * 0.8)
            t2_offset_x = 0.3 * progress if progress < 0.5 else 0.15 + (progress-0.5)*0.6
            t2_offset_y = 0.3 * (1-progress) if progress < 0.5 else 0.15 + (progress-0.5)*0.4
            draw.polygon([
                (mid_x + width * t2_offset_x, mid_y - height * t2_offset_y),
                (mid_x + width * t2_offset_x + width*0.15, mid_y + height * t2_offset_y),
                (mid_x - width * t2_offset_x, mid_y - height * t2_offset_y)
            ], fill=team2_rgb)
            emoji_x_offset_factor = 0.25
            emoji_y_offset = -15
            current_emoji_x_offset = width * emoji_x_offset_factor * (1 - progress*2) if progress < 0.5 else width * emoji_x_offset_factor * (max(0, 1 - (progress-0.5)*2))
            if current_emoji_x_offset < 5: current_emoji_x_offset = 5
            try:
                draw.text((mid_x - current_emoji_x_offset - font.getlength(fallback_emoji1)/2, mid_y + emoji_y_offset), fallback_emoji1, font=font, fill=(255, 255, 255))
            except Exception as e:
                logger.warning(f"Could not draw emoji '{fallback_emoji1}': {e}")
            try:
                draw.text((mid_x + current_emoji_x_offset - font.getlength(fallback_emoji2)/2, mid_y + emoji_y_offset), fallback_emoji2, font=font, fill=(255, 255, 255))
            except Exception as e:
                logger.warning(f"Could not draw emoji '{fallback_emoji2}': {e}")
            frames.append(img)

        img_buffer = io.BytesIO()
        try:
            frames[0].save(img_buffer, format="GIF", append_images=frames[1:], save_all=True, duration=duration_ms, loop=0)
            img_buffer.seek(0)
            return img_buffer
        except Exception as e:
            logger.error(f"Failed to save GIF animation: {e}", exc_info=True)
            return None

    @app_commands.command(name="gametime", description="Schedule a game between two teams.")
    @app_commands.describe(
        team1="First team (select using autocomplete)",
        team2="Second team (select using autocomplete)",
        day="Day of the game (e.g., Today, Tomorrow)",
        time="Time of the game (e.g., 7:30 PM)"
    )
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete, day=day_autocomplete, time=time_autocomplete)
    async def gametime(
        self,
        interaction: discord.Interaction,
        team1: str,
        team2: str,
        day: str,
        time: str
    ):
        if not await self.has_game_command_permission(interaction.user, interaction.guild.id):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("🚫 Permission Denied", "You must have a role like Franchise Owner, GM, Head Coach, Assistant Coach, Staff, or Commissioner to schedule games."),
                ephemeral=True
            )
            return

        config = get_server_config(interaction.guild.id)
        if not config or not config.get("team_roles"):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("⚠️ No Teams Configured", "Please configure your league teams first using `/addteam` or `/setup`."),
                ephemeral=True
            )
            return

        valid_team1 = next((t for t in list(config.get("team_data", {}).keys()) + list(config.get("team_roles", {}).keys()) if t.lower() == team1.lower()), None)
        valid_team2 = next((t for t in list(config.get("team_data", {}).keys()) + list(config.get("team_roles", {}).keys()) if t.lower() == team2.lower()), None)

        if not valid_team1 or not valid_team2:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Team Not Found", "Please select valid teams using the autocomplete options."),
                ephemeral=True
            )
            return
        team1, team2 = valid_team1, valid_team2

        if team1 == team2:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Matchup", "A team cannot play against itself."),
                ephemeral=True
            )
            return

        day_map = {"Today": 0, "Tomorrow": 1, "In 2 days": 2, "In 3 days": 3, "In 4 days": 4, "In 5 days": 5, "In 6 days": 6, "In 7 days": 7}
        day_offset = day_map.get(day)
        if day_offset is None:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Day", "Please select a valid day using the autocomplete."),
                ephemeral=True
            )
            return

        try:
            time_input_normalized = time.strip().upper()
            if not time_input_normalized.endswith((" AM", " PM")):
                if time_input_normalized.endswith("AM"): time_input_normalized = time_input_normalized[:-2] + " AM"
                elif time_input_normalized.endswith("PM"): time_input_normalized = time_input_normalized[:-2] + " PM"
            game_time_obj = datetime.strptime(time_input_normalized, "%I:%M %p")
        except ValueError:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Time Format", "Please enter time in HH:MM AM/PM format (e.g., 7:30 PM, 11:00 AM). Use autocomplete."),
                ephemeral=True
            )
            return

        current_date_localized = datetime.now(GAME_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        game_schedule_date = current_date_localized + timedelta(days=day_offset)
        game_schedule_datetime = game_schedule_date.replace(hour=game_time_obj.hour, minute=game_time_obj.minute)

        if game_schedule_datetime <= datetime.now(GAME_TIMEZONE):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Future Time Required", "The scheduled game time must be in the future."),
                ephemeral=True
            )
            return

        formatted_datetime_display = game_schedule_datetime.strftime('%A, %B %d, %Y at %I:%M %p %Z')
        unix_timestamp = int(game_schedule_datetime.timestamp())
        discord_timestamp_tag = f"<t:{unix_timestamp}:F>"
        internal_datetime_str = game_schedule_datetime.strftime("%Y-%m-%d %H:%M")

        team1_role_id = config.get("team_data", {}).get(team1, {}).get("role_id") or config.get("team_roles", {}).get(team1)
        team2_role_id = config.get("team_data", {}).get(team2, {}).get("role_id") or config.get("team_roles", {}).get(team2)
        team1_emoji_data = config.get("team_data", {}).get(team1, {}).get("emoji", ":soccer:")
        team2_emoji_data = config.get("team_data", {}).get(team2, {}).get("emoji", ":football:")
        team1_color_hex, team2_color_hex = "#000080", "#FF0000"
        guild_obj = interaction.guild
        if guild_obj:
            if team1_role_id:
                team1_role_obj = discord.utils.get(guild_obj.roles, id=int(team1_role_id))
                if team1_role_obj and team1_role_obj.color != discord.Color.default():
                    team1_color_hex = f"#{team1_role_obj.color.to_rgb()[0]:02x}{team1_role_obj.color.to_rgb()[1]:02x}{team1_role_obj.color.to_rgb()[2]:02x}"
            if team2_role_id:
                team2_role_obj = discord.utils.get(guild_obj.roles, id=int(team2_role_id))
                if team2_role_obj and team2_role_obj.color != discord.Color.default():
                    team2_color_hex = f"#{team2_role_obj.color.to_rgb()[0]:02x}{team2_role_obj.color.to_rgb()[1]:02x}{team2_role_obj.color.to_rgb()[2]:02x}"

        clash_gif_bytes = self.generate_clash_gif(team1_color_hex, team2_color_hex, team1_emoji_data, team2_emoji_data)

        games_data = load_json(GAMES_DATA_FILE)
        if not isinstance(games_data, dict):
            logger.warning(f"{GAMES_DATA_FILE} content invalid. Resetting games data.")
            games_data = {}
        guild_id_str = str(interaction.guild.id)
        if guild_id_str not in games_data: games_data[guild_id_str] = {}

        game_unique_id = f"GAME-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        game_entry = {
            "id": game_unique_id,
            "guild_id": guild_id_str,
            "team1": team1, "team1_emoji": team1_emoji_data, "team1_role_id": team1_role_id, "team1_color": team1_color_hex,
            "team2": team2, "team2_emoji": team2_emoji_data, "team2_role_id": team2_role_id, "team2_color": team2_color_hex,
            "scheduled_datetime": internal_datetime_str,
            "scheduled_timestamp": unix_timestamp,
            "scheduled_discord_timestamp": discord_timestamp_tag,
            "status": "scheduled",
            "scheduled_by_user_id": str(interaction.user.id),
            "scheduled_at": datetime.now().timestamp(),
            "stream_url": None, "stream_set_by": None, "stream_set_at": None,
            "referee_id": None, "referee_username": None, "referee_claimed_at": None,
            "streamer_id": None, "streamer_username": None, "streamer_claimed_at": None,
            "referee_role_ids": config.get("permission_settings", {}).get("referee_roles", []),
            "streamer_role_ids": config.get("permission_settings", {}).get("streamer_roles", []),
            "team1_owner_id": None,
            "team2_owner_id": None
        }

        # Find Franchise Owners for both teams
        fo_role_ids = config.get("permission_settings", {}).get("fo_roles", [])
        for member in guild_obj.members:
            member_role_ids = [str(role.id) for role in member.roles]
            if any(str(fo_role_id) in member_role_ids for fo_role_id in fo_role_ids):
                if str(team1_role_id) in member_role_ids:
                    game_entry["team1_owner_id"] = str(member.id)
                if str(team2_role_id) in member_role_ids:
                    game_entry["team2_owner_id"] = str(member.id)

        games_data[guild_id_str][game_unique_id] = game_entry
        save_json(GAMES_DATA_FILE, games_data)

        embed = discord.Embed(
            title=f"🏈 New Game Scheduled! | {guild_obj.name}",
            description=f"{team1_emoji_data} **{team1}** vs **{team2}** {team2_emoji_data}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.set_author(name=guild_obj.name, icon_url=guild_obj.icon.url if guild_obj.icon else None)
        embed.add_field(name="📅 Date & Time", value=discord_timestamp_tag, inline=False)
        embed.add_field(name="👤 Scheduled By", value=interaction.user.mention, inline=True)
        team1_role_mention = f"<@&{team1_role_id}>" if team1_role_id else team1
        team2_role_mention = f"<@&{team2_role_id}>" if team2_role_id else team2
        embed.add_field(name="🔔 Teams", value=f"{team1_role_mention} vs {team2_role_mention}", inline=True)
        embed.add_field(name="👮 Referee", value="Unclaimed", inline=True)
        embed.add_field(name="📺 Streamer", value="Unclaimed", inline=True)
        embed.set_footer(text=f"Game ID: {game_unique_id}")
        file_attachment = discord.File(clash_gif_bytes, filename="clash.gif") if clash_gif_bytes else None
        if file_attachment:
            embed.set_image(url="attachment://clash.gif")

        target_channel = None
        channel_config_keys = config.get("log_channels", {}).get("games", None) or config.get("notification_settings", {}).get("reminders_channel_id", None)
        if channel_config_keys:
            target_channel = interaction.guild.get_channel(int(channel_config_keys))

        if target_channel and isinstance(target_channel, discord.TextChannel):
            sent_message = await target_channel.send(
                embed=embed,
                file=file_attachment,
                view=GameManagementView(self.bot, game_unique_id, guild_id_str, str(interaction.user.id))
            )
            await interaction.response.send_message(
                embed=EmbedBuilder.success(
                    "🎉 Game Scheduled Successfully",
                    f"A new game between **{team1}** and **{team2}** has been scheduled in {target_channel.mention}."
                ),
                ephemeral=True
            )

            # DM Franchise Owners
            for owner_id in [game_entry.get("team1_owner_id"), game_entry.get("team2_owner_id")]:
                if owner_id:
                    try:
                        owner = await self.bot.fetch_user(int(owner_id))
                        if owner:
                            dm_embed = discord.Embed(
                                title=f"Game Scheduled in {guild_obj.name}",
                                description=f"A game has been confirmed for **{team1}** vs **{team2}** on {discord_timestamp_tag} in {guild_obj.name}.",
                                color=discord.Color.blue(),
                                timestamp=datetime.now()
                            )
                            dm_embed.set_author(name=guild_obj.name, icon_url=guild_obj.icon.url if guild_obj.icon else None)
                            await owner.send(embed=dm_embed)
                    except Exception as e:
                        logger.error(f"Failed to DM owner ID {owner_id}: {e}")

            await log_action(
                interaction.guild,
                "GAME_SCHEDULING",
                interaction.user,
                f"Scheduled game: {team1} vs {team2} for {formatted_datetime_display} (Msg ID: {sent_message.id})",
                "gametime"
            )
        else:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Configuration Error",
                    "Could not determine where to post the game announcement. Please ensure a game log or reminders channel is configured via `/setup` or `/setchannel`."
                ),
                ephemeral=True
            )

    @app_commands.command(name="cancel-game", description="Cancel a previously scheduled game.")
    @app_commands.describe(
        team1="First team involved in the game",
        team2="Second team involved in the game",
        day="Day the game was scheduled (e.g., Today, Tomorrow)",
        time="Time the game was scheduled (e.g., 7:30 PM)"
    )
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete, day=day_autocomplete, time=time_autocomplete)
    async def cancel_game(self, interaction: discord.Interaction, team1: str, team2: str, day: str, time: str):
        if not await self.has_game_command_permission(interaction.user, interaction.guild.id):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("🚫 Permission Denied", "You must have a role like Franchise Owner, GM, Head Coach, Assistant Coach, Staff, or Commissioner to cancel games."),
                ephemeral=True
            )
            return

        config = get_server_config(interaction.guild.id)
        if not config or not config.get("team_roles"):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("⚠️ No Teams Configured", "Cannot find games if teams are not configured."),
                ephemeral=True
            )
            return

        valid_team1 = next((t for t in list(config.get("team_data", {}).keys()) + list(config.get("team_roles", {}).keys()) if t.lower() == team1.lower()), None)
        valid_team2 = next((t for t in list(config.get("team_data", {}).keys()) + list(config.get("team_roles", {}).keys()) if t.lower() == team2.lower()), None)

        if not valid_team1 or not valid_team2:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Team Not Found", "Please select valid teams using the autocomplete options."),
                ephemeral=True
            )
            return
        team1, team2 = valid_team1, valid_team2

        day_map = {"Today": 0, "Tomorrow": 1, "In 2 days": 2, "In 3 days": 3, "In 4 days": 4, "In 5 days": 5, "In 6 days": 6, "In 7 days": 7}
        day_offset = day_map.get(day)
        if day_offset is None:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Day", "Please select a valid day using the autocomplete."),
                ephemeral=True
            )
            return

        try:
            time_input_normalized = time.strip().upper()
            if not time_input_normalized.endswith((" AM", " PM")):
                if time_input_normalized.endswith("AM"): time_input_normalized = time_input_normalized[:-2] + " AM"
                elif time_input_normalized.endswith("PM"): time_input_normalized = time_input_normalized[:-2] + " PM"
            game_time_obj = datetime.strptime(time_input_normalized, "%I:%M %p")
        except ValueError:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Time Format", "Please use HH:MM AM/PM format (e.g., 7:30 PM). Use autocomplete."),
                ephemeral=True
            )
            return

        current_date_localized = datetime.now(GAME_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        game_schedule_date = current_date_localized + timedelta(days=day_offset)
        game_schedule_datetime = game_schedule_date.replace(hour=game_time_obj.hour, minute=game_time_obj.minute)
        internal_datetime_str_to_find = game_schedule_datetime.strftime("%Y-%m-%d %H:%M")

        games_data = load_json(GAMES_DATA_FILE)
        guild_id_str = str(interaction.guild.id)

        found_game_id = None
        found_game_entry = None

        if guild_id_str in games_data and games_data[guild_id_str]:
            for g_id, game in games_data[guild_id_str].items():
                teams_match = ((game["team1"] == team1 and game["team2"] == team2) or
                               (game["team1"] == team2 and game["team2"] == team1))
                if teams_match and game.get("scheduled_datetime") == internal_datetime_str_to_find and game.get("status") == "scheduled":
                    found_game_id = g_id
                    found_game_entry = game
                    break

        if not found_game_id:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Game Not Found",
                    f"Could not locate a **scheduled** game between **{team1}** and **{team2}** at the specified time. It might already be cancelled, processed, or the details don't match."
                ),
                ephemeral=True
            )
            return

        is_authorized = await self.has_game_command_permission(interaction.user, interaction.guild.id)
        if not is_authorized and found_game_entry and found_game_entry.get("scheduled_by_user_id") == str(interaction.user.id):
            is_authorized = True

        if not is_authorized:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "🚫 Permission Denied",
                    "You must have a role like Franchise Owner, GM, Head Coach, Assistant Coach, Staff, Commissioner, or be the scheduler to cancel this game."
                ),
                ephemeral=True
            )
            return

        view = GameCancelConfirmationView(self.bot, found_game_id, guild_id_str, str(interaction.user.id), found_game_entry)
        embed = discord.Embed(
            title="❓ Confirm Game Cancellation",
            description=f"**Are you sure you want to cancel the game:**\n"
                        f"{found_game_entry.get('team1_emoji', '❓')} **{found_game_entry.get('team1', 'Team 1')}** vs **{found_game_entry.get('team2', 'Team 2')}** {found_game_entry.get('team2_emoji', '❓')}\n"
                        f"Scheduled for: {found_game_entry.get('scheduled_discord_timestamp', 'Unknown Time')}\n\n"
                        f"This action cannot be undone.",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Game ID: {found_game_id}")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="stream", description="Post a streaming URL.")
    @app_commands.describe(
        team1="First team of the game",
        team2="Second team of the game",
        stream_url="The URL of the live stream (e.g., https://twitch.tv/yourchannel)"
    )
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete)
    async def stream(self, interaction: discord.Interaction, team1: str, team2: str, stream_url: str):
        if not await self.has_game_command_permission(interaction.user, interaction.guild.id):
            has_streamer = has_streamer_role(interaction.user, interaction.guild.id)
            if not has_streamer:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("🚫 Permission Denied", "You need a role like Franchise Owner, GM, Head Coach, Assistant Coach, Streamer, Staff, or Commissioner to update stream information."),
                    ephemeral=True
                )
                return

        config = get_server_config(interaction.guild.id)
        if not config or not config.get("team_roles"):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("⚠️ No Teams Configured", "Please configure your league teams first."),
                ephemeral=True
            )
            return

        valid_team1 = next((t for t in list(config.get("team_data", {}).keys()) + list(config.get("team_roles", {}).keys()) if t.lower() == team1.lower()), None)
        valid_team2 = next((t for t in list(config.get("team_data", {}).keys()) + list(config.get("team_roles", {}).keys()) if t.lower() == team2.lower()), None)

        if not valid_team1 or not valid_team2:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Team Not Found", "Please select valid teams using the autocomplete options."),
                ephemeral=True
            )
            return
        team1, team2 = valid_team1, valid_team2

        if not (stream_url.startswith("http://") or stream_url.startswith("https://")):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid URL", "The stream URL must start with `http://` or `https://`."),
                ephemeral=True
            )
            return

        games_data = load_json(GAMES_DATA_FILE)
        guild_id_str = str(interaction.guild.id)
        found_game_id = None
        found_game_entry = None

        if guild_id_str in games_data and games_data[guild_id_str]:
            for g_id, game in games_data[guild_id_str].items():
                teams_match = ((game["team1"] == team1 and game["team2"] == team2) or
                               (game["team1"] == team2 and game["team2"] == team1))
                if teams_match and game.get("status") == "scheduled":
                    found_game_id = g_id
                    found_game_entry = game
                    break

        if not found_game_id:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Game Not Found",
                    f"Could not find a scheduled game between **{team1}** and **{team2}** that is still pending."
                ),
                ephemeral=True
            )
            return

        found_game_entry["stream_url"] = stream_url
        found_game_entry["stream_set_by"] = str(interaction.user.id)
        found_game_entry["stream_set_at"] = datetime.now().timestamp()
        games_data[guild_id_str][found_game_id] = found_game_entry
        save_json(GAMES_DATA_FILE, games_data)

        team1_role_id = found_game_entry.get("team1_role_id")
        team2_role_id = found_game_entry.get("team2_role_id")
        team1_emoji_data = found_game_entry.get("team1_emoji", ":soccer:")
        team2_emoji_data = found_game_entry.get("team2_emoji", ":football:")
        team1_color_hex = found_game_entry.get("team1_color", "#000080")
        team2_color_hex = found_game_entry.get("team2_color", "#FF0000")

        clash_gif_bytes = self.generate_clash_gif(team1_color_hex, team2_color_hex, team1_emoji_data, team2_emoji_data)

        embed = discord.Embed(
            title=f"📺 Stream URL Updated! | {interaction.guild.name}",
            description=f"A stream has been added for the game between {team1_emoji_data} **{team1}** and **{team2}** {team2_emoji_data}",
            color=discord.Color.purple(),
            timestamp=datetime.now()
        )
        embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.add_field(name="📅 Game Schedule", value=found_game_entry.get("scheduled_discord_timestamp", "Unknown Time"), inline=False)
        embed.add_field(name="🌐 Stream URL", value=stream_url, inline=False)
        embed.add_field(name="Stream Set By", value=interaction.user.mention, inline=True)
        if found_game_entry.get("referee_id"):
            referee_user = interaction.guild.get_member(int(found_game_entry["referee_id"]))
            embed.add_field(name="👮 Referee", value=f"{referee_user.mention} `{referee_user.name}`" if referee_user else "Unknown", inline=True)
        else:
            embed.add_field(name="👮 Referee", value="Unclaimed", inline=True)
        if found_game_entry.get("streamer_id"):
            streamer_user = interaction.guild.get_member(int(found_game_entry["streamer_id"]))
            embed.add_field(name="📺 Streamer", value=f"{streamer_user.mention} `{streamer_user.name}`" if streamer_user else "Unknown", inline=True)
        else:
            embed.add_field(name="📺 Streamer", value="Unclaimed", inline=True)
        embed.set_footer(text=f"Game ID: {found_game_id}")
        if clash_gif_bytes:
            embed.set_image(url="attachment://clash.gif")

        class StreamLinkView(discord.ui.View):
            def __init__(self, url):
                super().__init__(timeout=None)
                self.add_item(discord.ui.Button(label="Watch Live", style=discord.ButtonStyle.link, url=url))

        view = StreamLinkView(stream_url)

        target_channel = None
        channel_config_keys = config.get("log_channels", {}).get("games", None) or config.get("notification_settings", {}).get("reminders_channel_id", None)
        if channel_config_keys:
            target_channel = interaction.guild.get_channel(int(channel_config_keys))

        if target_channel and isinstance(target_channel, discord.TextChannel):
            await target_channel.send(embed=embed, file=discord.File(clash_gif_bytes, filename="clash.gif") if clash_gif_bytes else None, view=view)
            await interaction.response.send_message(
                embed=EmbedBuilder.success(
                    "🌐 Stream URL Updated",
                    f"The stream URL for the game between **{team1}** and **{team2}** has been updated in {target_channel.mention}."
                ),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Channel Not Set",
                    "The stream update notification could not be posted as no relevant channel is configured. Please set one using `/setup`."
                ),
                ephemeral=True
            )

        log_id = await log_action(
            interaction.guild,
            "GAME_STREAM_UPDATE",
            interaction.user,
            f"Set stream URL for {team1} vs {team2} game: {stream_url}",
            "stream"
        )

        try:
            log_channel_id_specific = config.get("log_channels", {}).get("games")
            if log_channel_id_specific:
                specific_log_channel = interaction.guild.get_channel(int(log_channel_id_specific))
                if specific_log_channel:
                    log_embed_specific = embed.copy()
                    log_embed_specific.add_field(name="Action Log ID", value=log_id, inline=True)
                    await specific_log_channel.send(embed=log_embed_specific, file=discord.File(clash_gif_bytes, filename="clash.gif") if clash_gif_bytes else None)
        except Exception as e:
            logger.error(f"Failed to send stream update to games log channel: {e}", exc_info=True)

        # DM Franchise Owners about stream update
        for owner_id in [found_game_entry.get("team1_owner_id"), found_game_entry.get("team2_owner_id")]:
            if owner_id:
                try:
                    owner = await self.bot.fetch_user(int(owner_id))
                    if owner:
                        dm_embed = discord.Embed(
                            title=f"Stream Updated for Game in {interaction.guild.name}",
                            description=f"The stream URL for **{team1}** vs **{team2}** on {found_game_entry.get('scheduled_discord_timestamp')} has been set to {stream_url} by {interaction.user.mention} `{interaction.user.name}`.",
                            color=discord.Color.purple(),
                            timestamp=datetime.now()
                        )
                        dm_embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
                        await owner.send(embed=dm_embed)
                except Exception as e:
                    logger.error(f"Failed to DM owner ID {owner_id} about stream update: {e}")

# View for interactive confirmation/management of game actions
class GameManagementView(discord.ui.View):
    def __init__(self, bot, game_id: str, guild_id: str, user_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.game_id = game_id
        self.guild_id = guild_id
        self.user_id = user_id
        self.add_item(discord.ui.Button(label="Claim Referee", style=discord.ButtonStyle.primary, custom_id=f"claim_referee_{game_id}"))
        self.add_item(discord.ui.Button(label="Claim Streamer", style=discord.ButtonStyle.primary, custom_id=f"claim_streamer_{game_id}"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message("This interaction is only valid within a server.", ephemeral=True)
            return False
        custom_id = interaction.data.get("custom_id", "")
        games_data = load_json(GAMES_DATA_FILE)
        guild_id_str = str(self.guild_id)
        game = games_data.get(guild_id_str, {}).get(self.game_id)

        if not game or game.get("status") != "scheduled":
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Game Not Available", "This game is no longer available for claiming."),
                ephemeral=True
            )
            return False

        if custom_id.startswith("claim_referee"):
            if not has_referee_role(interaction.user, interaction.guild.id):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Permission Denied", "You need a Referee role to claim this position."),
                    ephemeral=True
                )
                return False
            if game.get("referee_id"):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Position Taken", "The referee position for this game has already been claimed."),
                    ephemeral=True
                )
                return False
        elif custom_id.startswith("claim_streamer"):
            if not has_streamer_role(interaction.user, interaction.guild.id):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Permission Denied", "You need a Streamer role to claim this position."),
                    ephemeral=True
                )
                return False
            if game.get("streamer_id"):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Position Taken", "The streamer position for this game has already been claimed."),
                    ephemeral=True
                )
                return False
        return True

    @discord.ui.button(label="Claim Referee", style=discord.ButtonStyle.primary, custom_id="claim_referee_dynamic")
    async def claim_referee_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        games_data = load_json(GAMES_DATA_FILE)
        guild_id_str = str(self.guild_id)
        game = games_data.get(guild_id_str, {}).get(self.game_id)
        if not game:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Game Not Found", "The game could not be found."),
                ephemeral=True
            )
            return

        game["referee_id"] = str(interaction.user.id)
        game["referee_username"] = interaction.user.name
        game["referee_claimed_at"] = datetime.now().timestamp()
        games_data[guild_id_str][self.game_id] = game
        save_json(GAMES_DATA_FILE, games_data)

        # Update the original embed
        original_message = interaction.message
        embed = original_message.embeds[0] if original_message.embeds else discord.Embed()
        for i, field in enumerate(embed.fields):
            if field.name == "👮 Referee":
                embed.set_field_at(i, name="👮 Referee", value=f"{interaction.user.mention} `{interaction.user.name}`", inline=True)
                break
        else:
            embed.add_field(name="👮 Referee", value=f"{interaction.user.mention} `{interaction.user.name}`", inline=True)

        await original_message.edit(embed=embed, view=self)

        await interaction.response.send_message(
            embed=EmbedBuilder.success(
                "Referee Claimed",
                f"You have successfully claimed the referee position for the game (ID: {self.game_id})."
            ),
            ephemeral=True
        )

        # DM Franchise Owners
        config = get_server_config(interaction.guild.id)
        for owner_id in [game.get("team1_owner_id"), game.get("team2_owner_id")]:
            if owner_id:
                try:
                    owner = await self.bot.fetch_user(int(owner_id))
                    if owner:
                        dm_embed = discord.Embed(
                            title=f"Referee Claimed in {interaction.guild.name}",
                            description=f"{interaction.user.mention} `{interaction.user.name}` has claimed the referee position for the game between **{game['team1']}** and **{game['team2']}** on {game['scheduled_discord_timestamp']}.",
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        )
                        dm_embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
                        await owner.send(embed=dm_embed)
                except Exception as e:
                    logger.error(f"Failed to DM owner ID {owner_id} about referee claim: {e}")

        await log_action(
            interaction.guild,
            "GAME_REFEREE_CLAIM",
            interaction.user,
            f"Claimed referee for game: {game['team1']} vs {game['team2']} (ID: {self.game_id})",
            "claim_referee"
        )

    @discord.ui.button(label="Claim Streamer", style=discord.ButtonStyle.primary, custom_id="claim_streamer_dynamic")
    async def claim_streamer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        games_data = load_json(GAMES_DATA_FILE)
        guild_id_str = str(self.guild_id)
        game = games_data.get(guild_id_str, {}).get(self.game_id)
        if not game:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Game Not Found", "The game could not be found."),
                ephemeral=True
            )
            return

        game["streamer_id"] = str(interaction.user.id)
        game["streamer_username"] = interaction.user.name
        game["streamer_claimed_at"] = datetime.now().timestamp()
        games_data[guild_id_str][self.game_id] = game
        save_json(GAMES_DATA_FILE, games_data)

        # Update the original embed
        original_message = interaction.message
        embed = original_message.embeds[0] if original_message.embeds else discord.Embed()
        for i, field in enumerate(embed.fields):
            if field.name == "📺 Streamer":
                embed.set_field_at(i, name="📺 Streamer", value=f"{interaction.user.mention} `{interaction.user.name}`", inline=True)
                break
        else:
            embed.add_field(name="📺 Streamer", value=f"{interaction.user.mention} `{interaction.user.name}`", inline=True)

        await original_message.edit(embed=embed, view=self)

        await interaction.response.send_message(
            embed=EmbedBuilder.success(
                "Streamer Claimed",
                f"You have successfully claimed the streamer position for the game (ID: {self.game_id})."
            ),
            ephemeral=True
        )

        # DM Franchise Owners
        config = get_server_config(interaction.guild.id)
        for owner_id in [game.get("team1_owner_id"), game.get("team2_owner_id")]:
            if owner_id:
                try:
                    owner = await self.bot.fetch_user(int(owner_id))
                    if owner:
                        dm_embed = discord.Embed(
                            title=f"Streamer Claimed in {interaction.guild.name}",
                            description=f"{interaction.user.mention} `{interaction.user.name}` has claimed the streamer position for the game between **{game['team1']}** and **{game['team2']}** on {game['scheduled_discord_timestamp']}.",
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        )
                        dm_embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
                        await owner.send(embed=dm_embed)
                except Exception as e:
                    logger.error(f"Failed to DM owner ID {owner_id} about streamer claim: {e}")

        await log_action(
            interaction.guild,
            "GAME_STREAMER_CLAIM",
            interaction.user,
            f"Claimed streamer for game: {game['team1']} vs {game['team2']} (ID: {self.game_id})",
            "claim_streamer"
        )

# View for confirming game cancellation prompt
class GameCancelConfirmationView(discord.ui.View):
    def __init__(self, bot, game_id: str, guild_id: str, user_id: str, game_data: dict):
        super().__init__(timeout=120)
        self.bot = bot
        self.game_id = game_id
        self.guild_id = guild_id
        self.user_id = user_id
        self.game_data = game_data

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Permission Denied", "Only the person who initiated this cancellation process can confirm or abort it."),
                ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        embed = discord.Embed(
            title="⏳ Confirmation Timed Out",
            description="The cancellation request timed out. The game remains scheduled. Please try again if you still wish to cancel.",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        for child in self.children: child.disabled = True
        logger.info(f"Game cancellation confirmation timed out for Game ID: {self.game_id} by User ID: {self.user_id}")

    @discord.ui.button(label="Confirm Cancellation", style=discord.ButtonStyle.danger, row=0)
    async def confirm_cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        games_data = load_json(GAMES_DATA_FILE)
        guild_id_str = str(self.guild_id)
        game_still_exists_and_scheduled = (
            guild_id_str in games_data and
            self.game_id in games_data[guild_id_str] and
            games_data[guild_id_str][self.game_id]["status"] == "scheduled"
        )

        if not game_still_exists_and_scheduled:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Game Not Found or Already Processed", "The game could not be found or its status has changed."),
                ephemeral=True
            )
            for child in self.children: child.disabled = True
            await interaction.message.edit(view=self)
            self.stop()
            return

        game_to_update = games_data[guild_id_str][self.game_id]
        game_to_update["status"] = "cancelled"
        game_to_update["cancelled_at"] = datetime.now().timestamp()
        game_to_update["cancelled_by"] = str(interaction.user.id)
        games_data[guild_id_str][self.game_id] = game_to_update
        save_json(GAMES_DATA_FILE, games_data)

        confirmation_embed = discord.Embed(
            title="✅ Game Successfully Cancelled",
            description=f"The game between **{game_to_update['team1']}** and **{game_to_update['team2']}** has been cancelled.",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        confirmation_embed.add_field(name="Cancelled by", value=interaction.user.mention, inline=True)
        confirmation_embed.set_footer(text=f"Game ID: {self.game_id}")

        for child in self.children: child.disabled = True
        await interaction.response.edit_message(embed=confirmation_embed, view=self)

        guild_obj = self.bot.get_guild(int(self.guild_id))
        config_current = get_server_config(guild_obj.id) if guild_obj else None

        await log_action(
            guild_obj,
            "GAME_ACTION",
            interaction.user,
            f"Cancelled game: {game_to_update['team1']} vs {game_to_update['team2']} ({game_to_update['scheduled_discord_timestamp']})",
            "cancel_game_confirmation"
        )

        try:
            if config_current:
                log_channel_id = config_current.get("log_channels", {}).get("games")
                if log_channel_id and guild_obj:
                    log_channel = guild_obj.get_channel(int(log_channel_id))
                    if log_channel:
                        log_channel_embed = confirmation_embed.copy()
                        log_channel_embed.add_field(name="Log Type", value="Game Cancellation", inline=True)
                        await log_channel.send(embed=log_channel_embed)
        except Exception as e:
            logger.error(f"Error sending game cancellation notification to log channel: {e}", exc_info=True)

        try:
            if config_current:
                reminders_channel_id = config_current.get("notification_settings", {}).get("reminders_channel_id")
                if reminders_channel_id and guild_obj:
                    announcement_channel = guild_obj.get_channel(int(reminders_channel_id))
                    if announcement_channel:
                        await announcement_channel.send(embed=confirmation_embed)
        except Exception as e:
            logger.error(f"Error sending game cancellation announcement: {e}", exc_info=True)

        # DM Franchise Owners about cancellation
        for owner_id in [game_to_update.get("team1_owner_id"), game_to_update.get("team2_owner_id")]:
            if owner_id:
                try:
                    owner = await self.bot.fetch_user(int(owner_id))
                    if owner:
                        dm_embed = discord.Embed(
                            title=f"Game Cancelled in {guild_obj.name}",
                            description=f"The game between **{game_to_update['team1']}** and **{game_to_update['team2']}** on {game_to_update['scheduled_discord_timestamp']} has been cancelled by {interaction.user.mention}.",
                            color=discord.Color.red(),
                            timestamp=datetime.now()
                        )
                        dm_embed.set_author(name=guild_obj.name, icon_url=guild_obj.icon.url if guild_obj.icon else None)
                        await owner.send(embed=dm_embed)
                except Exception as e:
                    logger.error(f"Failed to DM owner ID {owner_id} about game cancellation: {e}")

        self.stop()

    @discord.ui.button(label="Cancel Action", style=discord.ButtonStyle.secondary, row=0)
    async def abort_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Action Aborted",
            description="Game cancellation process has been cancelled. The game remains scheduled.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

async def setup(bot):
    await bot.add_cog(GameCommands(bot))
    logger.info("GameCommands Cog loaded successfully.")