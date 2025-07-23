
import discord
from discord import app_commands
from discord.ext import commands
import logging
import datetime
import re
import json
import os
from typing import Optional, Union
from utils.config import get_server_config
from utils.permissions import is_admin

# Configure logging
logger = logging.getLogger("bot.moderation")

# --------------------------------------------------------------------------------
# Utility Functions
# --------------------------------------------------------------------------------
def load_json(filename: str) -> dict:
    """Load JSON data from file."""
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return json.load(f)
        return {}
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Error loading {filename}: {e}")
        return {}

def save_json(filename: str, data: dict) -> None:
    """Save JSON data to file."""
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {filename}: {e}")

# --------------------------------------------------------------------------------
# EmbedBuilder Utility
# --------------------------------------------------------------------------------
class EmbedBuilder:
    """Utility class for creating consistent Discord embeds."""
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        """Creates a success embed with green color and timestamp."""
        return discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        """Creates an error embed with red color and timestamp."""
        return discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        """Creates an info embed with blue color and timestamp."""
        return discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

# --------------------------------------------------------------------------------
# Confirmation UI View
# --------------------------------------------------------------------------------
class KickConfirmationView(discord.ui.View):
    """View for confirming or canceling a kick action."""
    def __init__(self, cog: commands.Cog, member: discord.Member, moderator: discord.Member, reason: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.member = member
        self.moderator = moderator
        self.reason = reason

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensures only the command initiator can use the buttons."""
        if interaction.user.id != self.moderator.id:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Denied",
                "Only the command initiator can use these buttons."
            ), ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        """Handles view timeout by disabling buttons and notifying the initiator."""
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(embed=EmbedBuilder.error(
                "Kick Timed Out",
                f"The kick confirmation for {self.member.mention} has timed out."
            ), view=self)
        except discord.HTTPException as e:
            logger.error(f"Error updating message on kick timeout: {e}")

    async def _handle_kick(self, interaction: discord.Interaction):
        """Executes the kick action and logs it."""
        for item in self.children:
            item.disabled = True

        try:
            dm_embed = EmbedBuilder.error(
                "You've Been Kicked",
                f"You have been kicked from **{interaction.guild.name}**.\n\n**Reason:** {self.reason}"
            )
            try:
                await self.member.send(embed=dm_embed)
            except discord.Forbidden:
                await interaction.followup.send(embed=EmbedBuilder.info(
                    "DM Failed",
                    f"Could not DM {self.member.mention} about their kick (DMs may be closed)."
                ), ephemeral=True)
            except Exception as e:
                logger.error(f"Failed to send kick DM to {self.member.name}: {e}")
                await interaction.followup.send(embed=EmbedBuilder.error(
                    "DM Error",
                    f"Failed to send DM to {self.member.mention}: {e}"
                ), ephemeral=True)

            await self.member.kick(reason=f"Kicked by {self.moderator.display_name}: {self.reason}")

            response_embed = EmbedBuilder.success(
                "Member Kicked",
                f"{self.member.mention} has been kicked from the server."
            )
            await interaction.response.edit_message(embed=response_embed, view=self)

            log_embed = EmbedBuilder.success(
                "Kick Log",
                f"{self.member.mention} was kicked by {self.moderator.mention}."
            )
            log_embed.add_field(name="Reason", value=self.reason, inline=False)
            log_embed.add_field(name="User ID", value=self.member.id, inline=True)
            await self.cog.send_log_message(interaction.guild, log_embed)

        except discord.Forbidden:
            await interaction.response.edit_message(embed=EmbedBuilder.error(
                "Permission Error",
                "I lack the permissions or role hierarchy to kick this member."
            ), view=self)
        except Exception as e:
            logger.error(f"Error during kick confirmation for {self.member.id}: {e}", exc_info=True)
            await interaction.response.edit_message(embed=EmbedBuilder.error(
                "An Error Occurred",
                f"Failed to kick member: {e}"
            ), view=self)

    @discord.ui.button(label="Confirm Kick", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_kick(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        embed = EmbedBuilder.info(
            "Action Cancelled",
            f"The kick for {self.member.mention} has been cancelled."
        )
        await interaction.response.edit_message(embed=embed, view=self)

# --------------------------------------------------------------------------------
# Moderation Cog
# --------------------------------------------------------------------------------
class ModerationCommands(commands.Cog, name="Moderation Commands"):
    """Commands for moderating server members, including warnings, kicks, and mutes."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log_message(self, guild: discord.Guild, embed: discord.Embed) -> None:
        """Sends a log message to the configured log channel or #general."""
        try:
            config = get_server_config(guild.id)
            log_channel_id = config.get("log_channels", {}).get("general")
            log_channel = guild.get_channel(int(log_channel_id)) if log_channel_id else discord.utils.get(guild.text_channels, name="general")
            if log_channel:
                await log_channel.send(embed=embed)
            else:
                logger.warning(f"No log channel found for guild {guild.id}")
        except discord.Forbidden:
            logger.error(f"Failed to send log to channel in {guild.name}: Missing permissions.")
        except Exception as e:
            logger.error(f"Error sending log message in guild {guild.id}: {e}")

    async def has_moderator_role(self, user: discord.Member) -> bool:
        """Check if the user has a moderator role based on server config."""
        # Check if user is admin first
        if await is_admin(user):
            return True
            
        config = get_server_config(user.guild.id)
        permission_settings = config.get("permission_settings", {})
        
        # Check for moderator_roles (list format from setup commands)
        moderator_role_ids = permission_settings.get("moderator_roles", [])
        if moderator_role_ids:
            user_role_ids = [role.id for role in user.roles]
            for role_id in moderator_role_ids:
                if int(role_id) in user_role_ids:
                    return True
        
        # Fallback to legacy single moderator_role
        moderator_role_id = permission_settings.get("moderator_role")
        if moderator_role_id:
            if discord.utils.get(user.roles, id=int(moderator_role_id)):
                return True
        
        # Fallback to role name check if role ID not set
        return any("mod" in role.name.lower() or "moderator" in role.name.lower() for role in user.roles)

    @staticmethod
    def parse_duration(duration_str: str) -> tuple[int, str]:
        """Parses a duration string (e.g., 1d12h) into seconds and a human-readable format."""
        if not duration_str or not isinstance(duration_str, str):
            raise ValueError("Duration must be a non-empty string.")

        parts = re.findall(r'(\d+)\s*([smhd])', duration_str.lower().strip())
        if not parts:
            raise ValueError("Invalid duration format. Use formats like '10m', '2h30m', '1d'.")

        total_seconds = 0
        texts = []
        unit_map = {'s': 'second', 'm': 'minute', 'h': 'hour', 'd': 'day'}
        multiplier = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}

        for value, unit in parts:
            value = int(value)
            if value <= 0:
                raise ValueError("Duration values must be positive.")
            total_seconds += value * multiplier[unit]
            texts.append(f"{value} {unit_map[unit]}{'s' if value != 1 else ''}")

        return total_seconds, ", ".join(texts)

    @app_commands.command(name="warn", description="Issue an official warning to a member.")
    @app_commands.describe(
        member="The member to warn.",
        reason="The reason for the warning."
    )
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        """Issues a warning, logs it, and notifies the member."""
        await interaction.response.defer(ephemeral=True)
        
        if not await self.has_moderator_role(interaction.user):
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Permission Denied",
                "You do not have the required permissions for this command."
            ))
            return

        if member.id == interaction.user.id:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Invalid Target",
                "You cannot warn yourself."
            ))
            return
        if member.bot:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Invalid Target",
                "You cannot warn a bot."
            ))
            return
        if member.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Hierarchy Error",
                "You cannot warn a member with an equal or higher role."
            ))
            return
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Hierarchy Error",
                "My role is not high enough to warn this member."
            ))
            return

        try:
            all_warnings = load_json("data/warnings.json")
        except Exception as e:
            logger.error(f"Error loading warnings.json: {e}")
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Configuration Error",
                "Failed to load warning data. Please try again later."
            ))
            return

        guild_id_str = str(interaction.guild.id)
        user_id_str = str(member.id)
        guild_warnings = all_warnings.setdefault(guild_id_str, {})
        user_warnings = guild_warnings.setdefault(user_id_str, [])

        warning_id = f"WARN-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"
        warning_entry = {
            "id": warning_id,
            "mod_id": str(interaction.user.id),
            "reason": reason,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).timestamp()
        }
        user_warnings.append(warning_entry)

        try:
            save_json("data/warnings.json", all_warnings)
        except Exception as e:
            logger.error(f"Error saving warnings.json: {e}")
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Configuration Error",
                "Failed to save warning data. Please try again later."
            ))
            return

        warning_count = len(user_warnings)

        response_embed = EmbedBuilder.success(
            "Member Warned",
            f"{member.mention} has been officially warned."
        )
        response_embed.add_field(name="Reason", value=reason, inline=False)
        response_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        response_embed.add_field(name="Total Warnings", value=f"**{warning_count}**", inline=True)
        response_embed.set_footer(text=f"Warning ID: {warning_id}")
        await interaction.followup.send(embed=response_embed)

        log_embed = EmbedBuilder.success(
            "Warning Log",
            f"{member.mention} was warned by {interaction.user.mention}."
        )
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="Total Warnings Now", value=str(warning_count), inline=True)
        log_embed.add_field(name="Warning ID", value=warning_id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

        try:
            dm_embed = EmbedBuilder.error(
                "You Have Received a Warning",
                f"You have been warned in **{interaction.guild.name}**."
            )
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_embed.set_footer(text="Please adhere to the server rules.")
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            await interaction.followup.send(embed=EmbedBuilder.info(
                "DM Failed",
                f"Could not DM {member.mention} about the warning (DMs may be closed)."
            ))
        except Exception as e:
            logger.error(f"Failed to send warning DM to {member.name}: {e}")
            await interaction.followup.send(embed=EmbedBuilder.error(
                "DM Error",
                f"Failed to send warning DM to {member.mention}: {e}"
            ))

    @app_commands.command(name="baninfo", description="Get ban information for a user ID or member.")
    @app_commands.describe(user="The user ID or member to check ban info for.")
    async def baninfo(self, interaction: discord.Interaction, user: str) -> None:
        """Check if a user is banned and show ban details. Open to everyone."""
        await interaction.response.defer()
        
        try:
            # Try to parse as user ID first
            if user.isdigit():
                user_id = int(user)
            else:
                # Try to parse as mention
                user_id = int(user.replace('<@', '').replace('>', '').replace('!', ''))
        except ValueError:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Invalid Input",
                "Please provide a valid user ID or mention."
            ))
            return

        try:
            ban_entry = await interaction.guild.fetch_ban(discord.Object(id=user_id))
            user_obj = ban_entry.user
            reason = ban_entry.reason or "No reason provided"
            
            embed = EmbedBuilder.info(
                "Ban Information",
                f"**{user_obj.display_name}** (`{user_obj.id}`) is banned from this server."
            )
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.set_thumbnail(url=user_obj.display_avatar.url)
            
        except discord.NotFound:
            embed = EmbedBuilder.info(
                "Ban Information", 
                f"User ID `{user_id}` is not banned from this server."
            )
        except discord.Forbidden:
            embed = EmbedBuilder.error(
                "Permission Error",
                "I don't have permission to view ban information."
            )
        except Exception as e:
            logger.error(f"Error checking ban info: {e}")
            embed = EmbedBuilder.error(
                "Error",
                f"An error occurred while checking ban information: {e}"
            )
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="memberinfo", description="Get detailed info and moderation history for a member.")
    @app_commands.describe(member="The member to check. Defaults to yourself.")
    async def memberinfo(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
        *,
        channel: Optional[discord.TextChannel] = None
    ) -> None:
        """Get member information. Open to everyone."""
        target_member = member or interaction.user
        is_programmatic_call = channel is not None

        await interaction.response.defer(ephemeral=is_programmatic_call, thinking=True)

        embed = EmbedBuilder.info(
            f"Member Information: {target_member.display_name}",
            ""
        )
        embed.set_thumbnail(url=target_member.display_avatar.url)
        embed.add_field(name="User", value=f"{target_member.mention} (`{target_member.id}`)", inline=False)
        embed.add_field(name="Account Created", value=f"<t:{int(target_member.created_at.timestamp())}:R>", inline=True)

        if isinstance(target_member, discord.Member) and target_member.joined_at:
            embed.add_field(name="Joined Server", value=f"<t:{int(target_member.joined_at.timestamp())}:R>", inline=True)
            roles = [role.mention for role in reversed(target_member.roles) if role.name != "@everyone"]
            if roles:
                role_text = " ".join(roles)
                if len(role_text) > 1024:
                    role_text = role_text[:1020] + "..."
                embed.add_field(name=f"Roles [{len(roles)}]", value=role_text, inline=False)

        try:
            all_warnings = load_json("data/warnings.json")
        except Exception as e:
            logger.error(f"Error loading warnings.json: {e}")
            all_warnings = {}

        try:
            all_mutes = load_json("data/mutes.json")
        except Exception as e:
            logger.error(f"Error loading mutes.json: {e}")
            all_mutes = {}

        guild_id, user_id = str(interaction.guild_id), str(target_member.id)
        user_warnings = all_warnings.get(guild_id, {}).get(user_id, [])
        warnings_text = f"**Total: {len(user_warnings)}**\n" + "\n".join([
            f"• <t:{int(w['timestamp'])}:R>: `{w['reason'][:60]}`" for w in user_warnings[-3:]
        ]) if user_warnings else "No warnings found."
        embed.add_field(name="⚠️ Recent Warnings", value=warnings_text, inline=False)

        user_mutes = all_mutes.get(guild_id, {}).get(user_id, [])
        mutes_text = f"**Total: {len(user_mutes)}**\n" + "\n".join([
            f"• <t:{int(m['timestamp'])}:R> for **{m['duration']}**" for m in user_mutes[-3:]
        ]) if user_mutes else "No mutes found."
        embed.add_field(name="🔇 Recent Mutes", value=mutes_text, inline=False)

        if is_programmatic_call:
            target_channel = channel
            try:
                await target_channel.send(embed=embed)
                await interaction.followup.send(embed=EmbedBuilder.success(
                    "Action Completed",
                    f"Member info for {target_member.display_name} sent to {target_channel.mention}."
                ), ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send(embed=EmbedBuilder.error(
                    "Permission Error",
                    f"I do not have permission to send messages in {target_channel.mention}."
                ), ephemeral=True)
            except Exception as e:
                logger.error(f"Error sending memberinfo to {target_channel.name}: {e}")
                await interaction.followup.send(embed=EmbedBuilder.error(
                    "Error",
                    f"Failed to send member info: {e}"
                ), ephemeral=True)
        else:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="kick", description="Kick a member from the server with confirmation.")
    @app_commands.describe(member="The member to kick.", reason="The reason for kicking.")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        """Kicks a member after confirmation via a button view."""
        await interaction.response.defer(ephemeral=True)
        
        if not await self.has_moderator_role(interaction.user):
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Permission Denied",
                "You do not have the required permissions for this command."
            ))
            return

        if member.id == interaction.user.id or member.id == self.bot.user.id or member.top_role >= interaction.guild.me.top_role:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Invalid Target",
                "You cannot kick this member due to hierarchy or because they are a bot/yourself."
            ))
            return

        view = KickConfirmationView(self, member, interaction.user, reason)
        embed = EmbedBuilder.info(
            "Kick Confirmation",
            f"Are you sure you want to kick {member.mention}?"
        )
        embed.add_field(name="Reason", value=reason)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="mute", description="Timeout a member for a specified duration.")
    @app_commands.describe(
        member="The member to mute.",
        duration="Duration of the mute (e.g., 1h30m).",
        reason="Reason for the mute."
    )
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str) -> None:
        """Times out a member for a specified duration and logs the action."""
        await interaction.response.defer(ephemeral=True)
        
        if not await self.has_moderator_role(interaction.user):
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Permission Denied",
                "You lack the permissions to mute members."
            ))
            return

        if member.top_role >= interaction.guild.me.top_role:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Hierarchy Error",
                "My role is not high enough to mute this member."
            ))
            return

        if member.is_timed_out():
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Already Muted",
                f"{member.mention} is already timed out."
            ))
            return

        try:
            seconds, text_duration = self.parse_duration(duration)
            if not (1 <= seconds <= 2419200):  # Max 28 days
                raise ValueError("Duration must be between 1 second and 28 days.")

            end_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
            await member.timeout(end_time, reason=f"Muted by {interaction.user.display_name}: {reason}")

            try:
                os.makedirs("data", exist_ok=True)
                mutes = load_json("data/mutes.json")
            except Exception as e:
                logger.error(f"Error loading mutes.json: {e}")
                await interaction.followup.send(embed=EmbedBuilder.error(
                    "Configuration Error",
                    "Failed to load mute data. Please try again later."
                ))
                return

            guild_mutes = mutes.setdefault(str(interaction.guild.id), {})
            user_mutes = guild_mutes.setdefault(str(member.id), [])
            user_mutes.append({
                "mod_id": str(interaction.user.id),
                "reason": reason,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).timestamp(),
                "end_time": end_time.timestamp(),
                "duration": text_duration,
                "active": True
            })

            try:
                save_json("data/mutes.json", mutes)
            except Exception as e:
                logger.error(f"Error saving mutes.json: {e}")
                await interaction.followup.send(embed=EmbedBuilder.error(
                    "Configuration Error",
                    "Failed to save mute data. Please try again later."
                ))
                return

            embed = EmbedBuilder.success(
                "Member Muted",
                f"{member.mention} has been timed out."
            )
            embed.add_field(name="Duration", value=text_duration, inline=True)
            embed.add_field(name="Expires", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
            await interaction.followup.send(embed=embed)

            log_embed = EmbedBuilder.success(
                "Mute Log",
                f"{member.mention} was muted by {interaction.user.mention}."
            )
            log_embed.add_field(name="Reason", value=reason, inline=False)
            log_embed.add_field(name="Duration", value=text_duration, inline=True)
            await self.send_log_message(interaction.guild, log_embed)

            try:
                dm_embed = EmbedBuilder.error(
                    "You Have Been Muted",
                    f"You have been muted in **{interaction.guild.name}**."
                )
                dm_embed.add_field(name="Reason", value=reason, inline=False)
                dm_embed.add_field(name="Duration", value=text_duration, inline=True)
                dm_embed.set_footer(text="Please adhere to the server rules.")
                await member.send(embed=dm_embed)
            except discord.Forbidden:
                await interaction.followup.send(embed=EmbedBuilder.info(
                    "DM Failed",
                    f"Could not DM {member.mention} about the mute (DMs may be closed)."
                ))
            except Exception as e:
                logger.error(f"Failed to send mute DM to {member.name}: {e}")
                await interaction.followup.send(embed=EmbedBuilder.error(
                    "DM Error",
                    f"Failed to send mute DM to {member.mention}: {e}"
                ))

        except ValueError as e:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Invalid Duration",
                str(e)
            ))
        except discord.Forbidden:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Permission Error",
                "I lack the permissions to mute this member."
            ))
        except Exception as e:
            logger.error(f"Error during mute command: {e}", exc_info=True)
            await interaction.followup.send(embed=EmbedBuilder.error(
                "An Error Occurred",
                f"Failed to mute member: {e}"
            ))

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        """Handles errors for all app commands in this cog."""
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=EmbedBuilder.error(
                    "Permission Denied",
                    "You do not have the required permissions for this command."
                ), ephemeral=True)
        else:
            logger.error(f"Unhandled error in ModerationCommands: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=EmbedBuilder.error(
                    "Unexpected Error",
                    "Something went wrong. This has been logged for the developers."
                ), ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    """Adds the ModerationCommands cog to the bot."""
    await bot.add_cog(ModerationCommands(bot))
