import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

# Configure logging
logger = logging.getLogger("bot.media")

class EmbedBuilder:
    """Utility class for creating consistent Discord embeds."""
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        """Creates a success embed with green color and timestamp."""
        return discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )

    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        """Creates an error embed with red color and timestamp."""
        return discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        """Creates an info embed with blue color and timestamp."""
        return discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

class MediaCommands(commands.Cog, name="Media Commands"):
    """Commands for creating and managing temporary, permission-based media channels."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config_file = "mediaconfig.json"
        self.ping_limit = 2  # Max pings per channel per day
        self.config = self.load_config()

    def load_config(self) -> dict:
        """Loads the media configuration from a JSON file."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {self.config_file}: {e}")
                return {}
        return {}

    def save_config(self) -> None:
        """Saves the current media configuration to its JSON file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving {self.config_file}: {e}")

    def get_guild_config(self, guild_id: int) -> dict:
        """Gets or creates the configuration for a specific guild."""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.config:
            self.config[guild_id_str] = {
                'media_channel': None,
                'media_owner': None,
                'cohosts': [],
                'ping_role': None,
                'ping_log': {}
            }
            self.save_config()
        return self.config[guild_id_str]

    def is_media_owner(self, user: discord.Member, guild_config: dict) -> bool:
        """Checks if a user is the designated media owner."""
        return guild_config.get('media_owner') == str(user.id)

    def is_media_owner_or_cohost(self, user: discord.Member, guild_config: dict) -> bool:
        """Checks if a user is the media owner or a cohost."""
        return self.is_media_owner(user, guild_config) or str(user.id) in guild_config.get('cohosts', [])

    def clean_ping_log(self, guild_config: dict) -> None:
        """Removes ping records older than 24 hours from the config dictionary."""
        now = datetime.now(timezone.utc)
        for channel_id in list(guild_config.get('ping_log', {})):
            valid_pings = [
                ts for ts in guild_config['ping_log'][channel_id]
                if now - datetime.fromisoformat(ts) < timedelta(days=1)
            ]
            if valid_pings:
                guild_config['ping_log'][channel_id] = valid_pings
            else:
                del guild_config['ping_log'][channel_id]
        self.save_config()

    async def send_log_message(self, guild: discord.Guild, embed: discord.Embed) -> None:
        """Sends a log message to the configured log channel or #general."""
        try:
            # Attempt to get log channel from server config (if available)
            try:
                from utils.config import get_server_config
                config = get_server_config(guild.id)
                log_channel_id = config.get("log_channels", {}).get("general")
            except ImportError:
                log_channel_id = None

            log_channel = guild.get_channel(int(log_channel_id)) if log_channel_id else discord.utils.get(guild.text_channels, name="general")
            if log_channel:
                await log_channel.send(embed=embed)
            else:
                logger.warning(f"No log channel found for guild {guild.id}")
        except Exception as e:
            logger.error(f"Error sending log message in guild {guild.id}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Restricts messages in the media channel to authorized users."""
        if message.author.bot or not message.guild:
            return

        guild_config = self.get_guild_config(message.guild.id)
        media_channel_id = guild_config.get('media_channel')

        if media_channel_id and str(message.channel.id) == media_channel_id:
            if not message.author.guild_permissions.administrator and not self.is_media_owner_or_cohost(message.author, guild_config):
                try:
                    await message.delete()
                    await message.author.send(embed=EmbedBuilder.error(
                        "Message Not Allowed",
                        f"Only the media host, co-hosts, or administrators can send messages in {message.channel.mention}."
                    ))
                except discord.Forbidden:
                    logger.warning(f"Failed to delete message or DM {message.author.id}: Missing permissions")
                except discord.HTTPException as e:
                    logger.error(f"Error handling media channel message: {e}")
                return

        await self.bot.process_commands(message)

    @app_commands.command(name="setmedia", description="Set a media channel and its host.")
    @app_commands.describe(channel="The channel to designate for media.", host="The member who will host.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setmedia(self, interaction: discord.Interaction, channel: discord.TextChannel, host: discord.Member) -> None:
        """Sets a media channel and its host, restricting messages to the host and bot."""
        if not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Missing Permissions",
                "I don't have permission to manage channels."
            ), ephemeral=True)
            return

        guild_config = self.get_guild_config(interaction.guild.id)
        guild_config.update({
            'media_channel': str(channel.id),
            'media_owner': str(host.id),
            'cohosts': [],
            'ping_role': None,
            'ping_log': {}
        })

        try:
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=True),
                host: discord.PermissionOverwrite(send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(send_messages=True, manage_messages=True)
            }
            await channel.edit(overwrites=overwrites, reason=f"Media channel setup by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Error",
                "I lack permissions to edit channel permissions."
            ), ephemeral=True)
            return
        except Exception as e:
            logger.error(f"Error setting channel permissions: {e}")
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Error",
                f"Failed to set channel permissions: {e}"
            ), ephemeral=True)
            return

        self.save_config()
        embed = EmbedBuilder.success(
            "Media Channel Set",
            f"Media channel set to {channel.mention} with {host.mention} as the host."
        )
        embed.add_field(name="Set by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        log_embed = EmbedBuilder.success(
            "Media Channel Set",
            f"Media channel set to {channel.mention} with {host.mention} as host by {interaction.user.mention}."
        )
        log_embed.add_field(name="Channel ID", value=channel.id, inline=True)
        log_embed.add_field(name="Host ID", value=host.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="addcohost", description="Add a cohost to the media channel.")
    @app_commands.describe(cohost="The member to add as a cohost.")
    async def addcohost(self, interaction: discord.Interaction, cohost: discord.Member) -> None:
        """Adds a cohost with speaking permissions in the media channel."""
        guild_config = self.get_guild_config(interaction.guild.id)
        if not self.is_media_owner(interaction.user, guild_config) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Denied",
                "Only the media owner or an administrator can add cohosts."
            ), ephemeral=True)
            return

        media_channel = interaction.guild.get_channel(int(guild_config['media_channel'])) if guild_config['media_channel'] else None
        if not media_channel:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Configuration Error",
                "The media channel is not configured or has been deleted."
            ), ephemeral=True)
            return

        if str(cohost.id) in guild_config['cohosts']:
            await interaction.response.send_message(embed=EmbedBuilder.info(
                "Already Cohost",
                f"{cohost.mention} is already a cohost."
            ), ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Missing Permissions",
                "I don't have permission to manage channels."
            ), ephemeral=True)
            return

        guild_config['cohosts'].append(str(cohost.id))
        try:
            await media_channel.set_permissions(cohost, send_messages=True, reason=f"Added as cohost by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Error",
                "I lack permissions to edit channel permissions for the cohost."
            ), ephemeral=True)
            return
        except Exception as e:
            logger.error(f"Error setting cohost permissions: {e}")
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Error",
                f"Failed to set cohost permissions: {e}"
            ), ephemeral=True)
            return

        self.save_config()
        embed = EmbedBuilder.success(
            "Cohost Added",
            f"{cohost.mention} has been added as a cohost."
        )
        embed.add_field(name="Added by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        log_embed = EmbedBuilder.success(
            "Cohost Added",
            f"{cohost.mention} was added as a cohost by {interaction.user.mention}."
        )
        log_embed.add_field(name="Channel", value=media_channel.mention, inline=True)
        log_embed.add_field(name="Cohost ID", value=cohost.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="removecohost", description="Remove a cohost from the media channel.")
    @app_commands.describe(cohost="The member to remove as a cohost.")
    async def removecohost(self, interaction: discord.Interaction, cohost: discord.Member) -> None:
        """Removes a cohost from the media channel."""
        guild_config = self.get_guild_config(interaction.guild.id)
        if not self.is_media_owner(interaction.user, guild_config) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Denied",
                "Only the media owner or an administrator can remove cohosts."
            ), ephemeral=True)
            return

        media_channel = interaction.guild.get_channel(int(guild_config['media_channel'])) if guild_config['media_channel'] else None
        if not media_channel:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Configuration Error",
                "The media channel is not configured or has been deleted."
            ), ephemeral=True)
            return

        if str(cohost.id) not in guild_config['cohosts']:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Not a Cohost",
                f"{cohost.mention} is not a cohost."
            ), ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Missing Permissions",
                "I don't have permission to manage channels."
            ), ephemeral=True)
            return

        guild_config['cohosts'].remove(str(cohost.id))
        try:
            await media_channel.set_permissions(cohost, overwrite=None, reason=f"Removed as cohost by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Error",
                "I lack permissions to edit channel permissions for the cohost."
            ), ephemeral=True)
            return
        except Exception as e:
            logger.error(f"Error removing cohost permissions: {e}")
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Error",
                f"Failed to remove cohost permissions: {e}"
            ), ephemeral=True)
            return

        self.save_config()
        embed = EmbedBuilder.success(
            "Cohost Removed",
            f"{cohost.mention} has been removed as a cohost."
        )
        embed.add_field(name="Removed by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        log_embed = EmbedBuilder.success(
            "Cohost Removed",
            f"{cohost.mention} was removed as a cohost by {interaction.user.mention}."
        )
        log_embed.add_field(name="Channel", value=media_channel.mention, inline=True)
        log_embed.add_field(name="Cohost ID", value=cohost.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="deletemedia", description="Delete the media channel configuration and reset permissions.")
    @app_commands.describe(channel="The media channel to delete and reset.")
    @app_commands.checks.has_permissions(administrator=True)
    async def deletemedia(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        """Deletes the media channel configuration and resets its permissions."""
        guild_config = self.get_guild_config(interaction.guild.id)
        if guild_config.get('media_channel') != str(channel.id):
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Invalid Channel",
                "This channel is not the configured media channel."
            ), ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Missing Permissions",
                "I don't have permission to manage channels."
            ), ephemeral=True)
            return

        try:
            await channel.edit(overwrites={}, reason=f"Media channel deleted by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Error",
                "I lack permissions to reset the channel's permissions."
            ), ephemeral=True)
            return
        except Exception as e:
            logger.error(f"Error resetting channel permissions: {e}")
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Error",
                f"Failed to reset channel permissions: {e}"
            ), ephemeral=True)
            return

        guild_config.update({
            'media_channel': None,
            'media_owner': None,
            'cohosts': [],
            'ping_role': None,
            'ping_log': {}
        })
        self.save_config()

        embed = EmbedBuilder.success(
            "Media Channel Deleted",
            f"The media configuration for {channel.mention} has been deleted and its permissions reset."
        )
        embed.add_field(name="Deleted by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        log_embed = EmbedBuilder.success(
            "Media Channel Deleted",
            f"Media channel {channel.mention} was deleted by {interaction.user.mention}."
        )
        log_embed.add_field(name="Channel ID", value=channel.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="mediatransfer", description="Transfer media channel ownership to a new host.")
    @app_commands.describe(new_host="The member to transfer ownership to.")
    async def mediatransfer(self, interaction: discord.Interaction, new_host: discord.Member) -> None:
        """Transfers media channel ownership to a new host."""
        guild_config = self.get_guild_config(interaction.guild.id)
        if not self.is_media_owner(interaction.user, guild_config) and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Denied",
                "Only the current media owner or an administrator can transfer ownership."
            ), ephemeral=True)
            return

        media_channel = interaction.guild.get_channel(int(guild_config['media_channel'])) if guild_config['media_channel'] else None
        if not media_channel:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Configuration Error",
                "The media channel is not configured or has been deleted."
            ), ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.manage_channels:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Missing Permissions",
                "I don't have permission to manage channels."
            ), ephemeral=True)
            return

        old_host = interaction.user
        guild_config['media_owner'] = str(new_host.id)
        if str(new_host.id) in guild_config['cohosts']:
            guild_config['cohosts'].remove(str(new_host.id))

        try:
            await media_channel.set_permissions(old_host, overwrite=None, reason="Ownership transferred")
            await media_channel.set_permissions(new_host, send_messages=True, reason="Ownership transferred")
            for cohost_id in guild_config['cohosts']:
                cohost = interaction.guild.get_member(int(cohost_id))
                if cohost:
                    await media_channel.set_permissions(cohost, send_messages=True, reason="Reapplied cohost permissions")
        except discord.Forbidden:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Error",
                "I lack permissions to update channel permissions for the ownership transfer."
            ), ephemeral=True)
            return
        except Exception as e:
            logger.error(f"Error updating channel permissions: {e}")
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Error",
                f"Failed to update channel permissions: {e}"
            ), ephemeral=True)
            return

        self.save_config()
        embed = EmbedBuilder.success(
            "Ownership Transferred",
            f"Media channel ownership has been transferred to {new_host.mention}."
        )
        embed.add_field(name="Transferred by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        log_embed = EmbedBuilder.success(
            "Media Ownership Transferred",
            f"Media channel ownership transferred from {interaction.user.mention} to {new_host.mention}."
        )
        log_embed.add_field(name="Channel", value=media_channel.mention, inline=True)
        log_embed.add_field(name="New Host ID", value=new_host.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="setmediaping", description="Set the role to be used for media pings.")
    @app_commands.describe(role="The role to ping for media announcements.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setmediaping(self, interaction: discord.Interaction, role: discord.Role) -> None:
        """Sets the role to be used for media pings."""
        guild_config = self.get_guild_config(interaction.guild.id)
        guild_config['ping_role'] = str(role.id)
        self.save_config()

        embed = EmbedBuilder.success(
            "Media Ping Role Set",
            f"The media ping role has been set to {role.mention}."
        )
        embed.add_field(name="Set by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        log_embed = EmbedBuilder.success(
            "Media Ping Role Set",
            f"Media ping role set to {role.mention} by {interaction.user.mention}."
        )
        log_embed.add_field(name="Role ID", value=role.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="mediaping", description="Ping the media role in the media channel.")
    async def mediaping(self, interaction: discord.Interaction) -> None:
        """Pings the media role in the media channel, with a limit of 2 pings per day."""
        guild_config = self.get_guild_config(interaction.guild.id)
        if str(interaction.channel_id) != guild_config.get('media_channel'):
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Invalid Channel",
                "This command can only be used in the designated media channel."
            ), ephemeral=True)
            return

        if not self.is_media_owner_or_cohost(interaction.user, guild_config):
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Denied",
                "Only the media owner or cohosts can use this command."
            ), ephemeral=True)
            return

        self.clean_ping_log(guild_config)
        ping_log = guild_config.get('ping_log', {}).setdefault(str(interaction.channel_id), [])

        if len(ping_log) >= self.ping_limit:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Ping Limit Reached",
                f"The ping limit for this channel ({self.ping_limit} per day) has been reached. Try again tomorrow."
            ), ephemeral=True)
            return

        ping_role_id = guild_config.get('ping_role')
        ping_role = interaction.guild.get_role(int(ping_role_id)) if ping_role_id else None
        if not ping_role:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Ping Role Not Found",
                "A media ping role has not been set or was deleted. An admin can set one with `/setmediaping`."
            ), ephemeral=True)
            return

        ping_log.append(datetime.now(timezone.utc).isoformat())
        self.save_config()

        allowed_mentions = discord.AllowedMentions(roles=True)
        await interaction.response.send_message(f"📢 {ping_role.mention}", allowed_mentions=allowed_mentions)

        log_embed = EmbedBuilder.success(
            "Media Ping",
            f"Media ping triggered by {interaction.user.mention} in {interaction.channel.mention}."
        )
        log_embed.add_field(name="Role", value=ping_role.mention, inline=True)
        log_embed.add_field(name="User ID", value=interaction.user.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        """Handles errors for all app commands in this cog."""
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "Permission Denied",
                "You do not have the required permissions (e.g., Administrator) for this command."
            ), ephemeral=True)
        else:
            logger.error(f"Unhandled error in MediaCommands: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=EmbedBuilder.error(
                    "Unexpected Error",
                    "Something went wrong. This has been logged for the developers."
                ), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MediaCommands(bot))