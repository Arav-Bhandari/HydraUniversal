import logging
import discord
import json
import os
import re  # Imported re for get_emoji_url
from datetime import datetime, timedelta
import pytz
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from discord import app_commands
from discord.ext import commands
from utils.config import get_server_config, save_guild_config, load_json, save_json
from utils.permissions import detect_team

logger = logging.getLogger("bot.promotion")

# Constants
TRANSACTIONS_FILE = "transactions_history.json"
GUILDS_FILE = "guilds.json"
DEFAULT_ROSTER_CAP = 53

class TransactionType(Enum):
    PROMOTION = "promotion"
    DEMOTION = "demotion"

@dataclass
class TeamStats:
    current_size: int
    roster_cap: int
    available_slots: int
    utilization_percent: float
    salary_cap: float = 0.0
    current_salary: float = 0.0

ROLE_HIERARCHY = {
    "fo_roles": 4,  # Front Office
    "gm_roles": 3,  # General Manager
    "hc_roles": 2,  # Head Coach
    "ac_roles": 1,  # Assistant Coach
    # If you add lower roles like "player" or "staff", they'd be 0 or negative
}

class PremiumEmbedBuilder:
    """Enhanced embed builder with premium visual styling"""
    COLORS = {
        'success': 0x00FF88,      # Vibrant green
        'warning': 0xFFB800,      # Golden amber
        'error': 0xFF4757,        # Modern red
        'info': 0x3742FA,        # Electric blue
        'neutral': 0x747D8C,      # Sophisticated gray
        'premium': 0x9C88FF,      # Premium purple
        'gold': 0xFFD700,         # Gold accent
        'team': 0x2ECC71,         # Team green
        'transaction': 0xE67E22   # Transaction orange
    }

    @staticmethod
    def create_base_embed(title: str, description: str = None,
                         color: int = None, timestamp: bool = True) -> discord.Embed:
        """Create a base embed with premium styling"""
        embed = discord.Embed(
            title=f"⚡ {title}",
            description=description,
            color=color or PremiumEmbedBuilder.COLORS['premium'],
            timestamp=datetime.now(pytz.utc) if timestamp else discord.Embed.Empty
        )
        return embed

    @staticmethod
    def add_premium_footer(embed: discord.Embed, guild: discord.Guild,
                          additional_text: str = None) -> discord.Embed:
        """Add premium footer with guild branding"""
        footer_text = f"🏆 {guild.name}"
        if additional_text:
            footer_text += f" • {additional_text}"
        # Use discord.Embed.Empty for icon_url if guild.icon is None to avoid potential issues
        icon_url = guild.icon.url if guild.icon else discord.Embed.Empty
        embed.set_footer(text=footer_text, icon_url=icon_url)
        return embed

    @staticmethod
    def add_team_branding(embed: discord.Embed, guild: discord.Guild,
                         team_data: dict, team_name: str) -> discord.Embed:
        """Add team-specific branding to embed"""
        embed.set_author(name=f"🏟️ {guild.name} • {team_name}", icon_url=guild.icon.url if guild.icon else discord.Embed.Empty)
        emoji_url = team_data.get("Image") or get_emoji_url(team_data.get("emoji"))
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)
        return embed

    @staticmethod
    def create_roster_field(current_size: int, cap: int, salary: float = 0.0,
                          salary_cap: float = 0.0, show_visual: bool = True) -> Tuple[str, str]:
        """Create visually appealing roster and salary display"""
        percentage = (current_size / cap) * 100 if cap > 0 else 0
        # Ensure percentage is within a reasonable range for progress bar blocks
        blocks_per_10_percent = 10
        filled_blocks = min(blocks_per_10_percent, int(percentage / (100 / blocks_per_10_percent)))
        empty_blocks = blocks_per_10_percent - filled_blocks
        progress_bar = "█" * filled_blocks + "░" * empty_blocks
        field_name = "📊 Roster & Salary Status"
        salary_info = f"Salary: ${salary:,.2f} / ${salary_cap:,.2f}" if salary_cap > 0 else "Salary: Not tracked"
        if show_visual:
            field_value = f"```\nRoster: {progress_bar}\n{current_size}/{cap} players ({percentage:.1f}%)\n{salary_info}\n```"
        else:
            field_value = f"`{current_size}/{cap}` players • `{percentage:.1f}%` full\n{salary_info}"
        return field_name, field_value

    @staticmethod
    def create_transaction_embed(transaction_type: TransactionType,
                               player: Optional[discord.Member], team_name: str,
                               guild: discord.Guild, details: str = None,
                               action_by: Optional[discord.Member] = None,
                               roster_info: Optional[TeamStats] = None) -> discord.Embed:
        """Create standardized transaction embeds"""
        type_config = {
            TransactionType.PROMOTION: {
                'title': 'Staff Promoted', 'emoji': '⬆️', 'color': PremiumEmbedBuilder.COLORS['success'],
                'description': f"{player.mention if player else 'A staff member'} has been promoted in **{team_name}**!"
            },
            TransactionType.DEMOTION: {
                'title': 'Staff Demoted', 'emoji': '⬇️', 'color': PremiumEmbedBuilder.COLORS['warning'],
                'description': f"{player.mention if player else 'A staff member'} has been demoted in **{team_name}**."
            }
        }
        config = type_config[transaction_type]

        embed = PremiumEmbedBuilder.create_base_embed(
            title=f"{config['emoji']} {config['title']}",
            description=config['description'],
            color=config['color']
        )
        if player:
            embed.add_field(name="👤 Staff Member", value=f"**{player.display_name}**\n{player.mention}", inline=True)
        else:
            embed.add_field(name="👤 Staff Member", value="*Member not found or has left the server*", inline=True)
        embed.add_field(name="🏟️ Team", value=f"**{team_name}**", inline=True)
        if action_by:
            embed.add_field(name="⚡ Action By", value=f"**{action_by.display_name}**\n{action_by.mention}", inline=True)
        if roster_info:
            roster_name, roster_value = PremiumEmbedBuilder.create_roster_field(
                roster_info.current_size, roster_info.roster_cap,
                roster_info.current_salary, roster_info.salary_cap, show_visual=False
            )
            embed.add_field(name=roster_name, value=roster_value, inline=False)
        if details:
            # Truncate details if they are too long for a single field
            max_detail_length = 1024 # Discord embed field value limit
            if len(details) > max_detail_length - 10: # Leave some buffer for formatting
                details = details[:max_detail_length - 10] + "..."
            embed.add_field(name="📝 Details", value=f"```\n{details}\n```" if len(details) > 50 else f"`{details}`", inline=False)

        return PremiumEmbedBuilder.add_premium_footer(embed, guild)

def get_emoji_url(emoji_str: Optional[str]) -> Optional[str]:
    """Enhanced emoji URL extraction"""
    if not emoji_str:
        return None
    try:
        if emoji_str.startswith(("<:", "<a:")):
            match = re.match(r"<a?:[a-zA-Z0-9_]+:(\d+)>", emoji_str)
            if match:
                emoji_id = match.group(1)
                extension = "gif" if emoji_str.startswith("<a:") else "png"
                return f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}?size=128"
    except Exception as e:
        logger.warning(f"Failed to parse emoji URL: {e}")
    return None

class EnhancedPromotionCommands(commands.Cog):
    """Premium promotion and demotion system with role hierarchy and team checks"""
    def __init__(self, bot):
        self.bot = bot
        # self.transaction_cache = {} # Not used in current implementation, can be removed if not needed elsewhere.

    def _get_team_stats(self, guild: discord.Guild, team_name: str,
                       guild_config: dict) -> TeamStats:
        """Get team statistics including roster and salary info"""
        if not team_name: # Handle case where team_name might be None or empty
            team_data = {}
            roster_cap = guild_config.get("roster_cap", DEFAULT_ROSTER_CAP)
            team_role_id = None
            salary_cap = 0.0
            current_salary = 0.0
        else:
            team_data = guild_config.get("team_data", {}).get(team_name, {})
            roster_cap = team_data.get("roster_cap", guild_config.get("roster_cap", DEFAULT_ROSTER_CAP))
            team_role_id = team_data.get("role_id")
            salary_cap = team_data.get("salary_cap", 0.0)
            current_salary = team_data.get("current_salary", 0.0)

        current_size = 0
        if team_role_id:
            try:
                team_role = guild.get_role(int(team_role_id))
                if team_role:
                    current_size = len(team_role.members)
            except ValueError: # Handle cases where role_id might not be a valid integer
                logger.warning(f"Guild {guild.id}: Invalid team_role_id for team {team_name}: {team_role_id}")
            except discord.ObjectNotFound:
                 logger.warning(f"Guild {guild.id}: Team role not found for team {team_name}, role ID: {team_role_id}")


        available_slots = max(0, roster_cap - current_size)
        utilization_percent = (current_size / roster_cap * 100) if roster_cap > 0 else 0
        return TeamStats(
            current_size=current_size,
            roster_cap=roster_cap,
            available_slots=available_slots,
            utilization_percent=utilization_percent,
            salary_cap=salary_cap,
            current_salary=current_salary
        )

    async def _can_manage_team(self, interaction: discord.Interaction,
                             guild_config: dict) -> bool:
        """Check if user can manage team promotions/demotions"""
        if interaction.user.guild_permissions.administrator:
            return True
        permission_settings = guild_config.get("permission_settings", {})
        # Dynamically check all levels defined in ROLE_HIERARCHY for managing permissions
        allowed_role_keys = ["fo_roles", "gm_roles", "hc_roles", "ac_roles"] + \
                           [key for key in permission_settings if "roles" in key and key not in ["fo_roles", "gm_roles", "hc_roles", "ac_roles"]]
        user_role_ids = {str(role.id) for role in interaction.user.roles}

        for role_key in allowed_role_keys:
            configured_role_ids = permission_settings.get(role_key, [])
            if any(str(conf_id) in user_role_ids for conf_id in configured_role_ids):
                return True
        return False

    def _get_user_highest_staff_role_level(self, user: discord.Member, guild_config: dict,
                                           hierarchy: Dict[str, int]) -> Tuple[int, Optional[str]]:
        """Get user's highest staff role level and the role key"""
        if not user or not hasattr(user, 'roles'):
            return 0, None
        permission_settings = guild_config.get("permission_settings", {})
        max_level = 0
        highest_role_key = None
        user_role_ids = {str(r.id) for r in user.roles}

        # Iterate through the hierarchy in reverse order to find the highest role
        for role_key, level in sorted(hierarchy.items(), key=lambda item: item[1], reverse=True):
            configured_role_ids = permission_settings.get(role_key, [])
            if any(str(conf_id) in user_role_ids for conf_id in configured_role_ids):
                max_level = level
                highest_role_key = role_key
                break # Found the highest role, no need to check lower ones
        return max_level, highest_role_key

    async def _send_dm(self, member: discord.Member, embed: discord.Embed) -> None:
        """Attempt to send a DM to a member"""
        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            logger.warning(f"Could not send DM to {member.name} ({member.id}): User has DMs disabled or is not in the server.")
        except discord.HTTPException as e:
            logger.error(f"Failed to send DM to {member.name} ({member.id}): {e}")

    async def _log_transaction(self, guild: discord.Guild, transaction_type: TransactionType,
                             member: Optional[discord.Member], team_name: str,
                             action_by: Optional[discord.Member] = None, details: str = None,
                             roster_info: Optional[TeamStats] = None) -> None:
        """Log transactions with premium embeds and attempt to DM the member"""
        guild_config = get_server_config(guild.id)
        if not guild_config:
            logger.warning(f"Guild {guild.id}: No guild config found for logging transaction.")
            return

        log_channels = guild_config.get("log_channels", {})
        log_channel_id = log_channels.get("transactions", log_channels.get("general"))
        if not log_channel_id:
            logger.info(f"Guild {guild.id}: No transaction log channel configured.")
            return

        log_channel = guild.get_channel(int(log_channel_id))
        if not log_channel or not isinstance(log_channel, discord.TextChannel):
            logger.warning(f"Guild {guild.id}: Invalid or inaccessible log channel {log_channel_id}.")
            return

        embed = PremiumEmbedBuilder.create_transaction_embed(
            transaction_type, member, team_name, guild, details, action_by, roster_info
        )
        if team_name: # Only add team branding if team_name is valid
            team_data = guild_config.get("team_data", {}).get(team_name, {})
            if team_data:
                embed = PremiumEmbedBuilder.add_team_branding(embed, guild, team_data, team_name)

        # Send to log channel
        try:
            await log_channel.send(embed=embed)
            logger.info(f"Logged transaction for {member.name if member else 'N/A'} in guild {guild.id}")
        except discord.Forbidden:
            logger.error(f"Missing permissions to send messages in log channel {log_channel_id} of guild {guild.id}.")
        except discord.HTTPException as e:
            logger.error(f"Failed to send transaction log message in guild {guild.id}: {e}", exc_info=True)


        # Store history and send DM if member exists
        if member:
            await self._store_transaction_history(guild.id, transaction_type, member,
                                                team_name, action_by, details)
            await self._send_dm(member, embed)

    async def _store_transaction_history(self, guild_id: int, transaction_type: TransactionType,
                                       member: discord.Member, team_name: str,
                                       action_by: Optional[discord.Member] = None, details: str = None) -> None:
        """Store transaction in persistent history"""
        try:
            history = load_json(TRANSACTIONS_FILE)
            guild_key = str(guild_id)
            if guild_key not in history:
                history[guild_key] = []

            transaction = {
                "id": f"TXN-{datetime.now(pytz.utc).strftime('%Y%m%d%H%M%S%f')}",
                "type": transaction_type.value,
                "member_id": str(member.id),
                "member_name": member.display_name,
                "team_name": team_name,
                "action_by_id": str(action_by.id) if action_by else None,
                "action_by_name": action_by.display_name if action_by else None,
                "details": details,
                "timestamp": datetime.now(pytz.utc).timestamp(),
                "guild_id": guild_key
            }
            history[guild_key].append(transaction)
            # Keep only the last 1000 transactions to prevent file bloat
            if len(history[guild_key]) > 1000:
                history[guild_key] = history[guild_key][-1000:]
            save_json(TRANSACTIONS_FILE, history)
        except Exception as e:
            logger.error(f"Failed to store transaction history: {e}", exc_info=True)

    @app_commands.command(name="promote", description="Promote a member to a higher staff role within a team")
    @app_commands.describe(
        member="The member to promote",
        role_key="The role level to promote to (e.g., FO, GM, HC, AC)",
        details="Additional promotion details"
    )
    @app_commands.choices(role_key=[
        app_commands.Choice(name="Front Office (FO)", value="fo_roles"),
        app_commands.Choice(name="General Manager (GM)", value="gm_roles"),
        app_commands.Choice(name="Head Coach (HC)", value="hc_roles"),
        app_commands.Choice(name="Assistant Coach (AC)", value="ac_roles")
    ])
    async def promote(self, interaction: discord.Interaction, member: discord.Member,
                    role_key: str, details: str = "No additional details provided."):
        """Promote a member to a specified staff role based on hierarchy and team affiliation."""
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", "Server configuration not found. Please contact a server administrator.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        if not await self._can_manage_team(interaction, guild_config):
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permission Denied", "You lack the necessary roles to promote members.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Detect teams for context
        issuer_team_name = await detect_team(interaction.user)
        member_team_name = await detect_team(member)

        if not issuer_team_name:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Mismatch", f"{interaction.user.mention} is not assigned to any team.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        if not member_team_name:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Mismatch", f"{member.mention} is not assigned to any team.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        if issuer_team_name != member_team_name:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Mismatch", f"{member.mention} must be on your team ({issuer_team_name}). Current: {member_team_name}",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Get role levels
        target_level, target_role_key = self._get_user_highest_staff_role_level(member, guild_config, ROLE_HIERARCHY)
        issuer_level, issuer_role_key = self._get_user_highest_staff_role_level(interaction.user, guild_config, ROLE_HIERARCHY)
        new_role_level = ROLE_HIERARCHY.get(role_key)

        if new_role_level is None:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Invalid Role", f"The specified role key '{role_key}' is invalid.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Hierarchical checks
        if issuer_level <= new_role_level and not interaction.user.guild_permissions.administrator:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permission Denied", "You cannot promote to a role equal to or higher than your own.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        if target_level >= new_role_level:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Error", f"{member.mention} already has a staff role equal to or higher than the target ({target_role_key if target_role_key else 'None'}).",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Get the Discord role object for the promotion
        permission_settings = guild_config.get("permission_settings", {})
        new_role_id_list = permission_settings.get(role_key)

        if not new_role_id_list or not isinstance(new_role_id_list, list) or not new_role_id_list:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", f"No Discord role is configured for '{role_key}'. Please configure it in server settings.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        new_role_id = new_role_id_list[0] # Assuming only one role per key
        new_role = interaction.guild.get_role(int(new_role_id))

        if not new_role:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Not Found", f"The Discord role for '{role_key}' (ID: {new_role_id}) no longer exists in this server.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Prepare role modifications
        roles_to_remove = []
        # Find all current staff roles the member has to remove them
        for current_role_key, current_level in ROLE_HIERARCHY.items():
            if current_level <= target_level: # Remove all roles lower or equal to current rank, except if the target role is lower
                if current_role_key != role_key: # Don't remove the role they are being promoted to if they already have it (unlikely due to check above but safe)
                    for configured_role_id_str in permission_settings.get(current_role_key, []):
                        role_to_remove = discord.utils.get(member.roles, id=int(configured_role_id_str))
                        if role_to_remove:
                            roles_to_remove.append(role_to_remove)

        # Ensure we don't add the new role to roles_to_remove if it's already there
        roles_to_remove = [r for r in roles_to_remove if r.id != new_role.id]


        try:
            if roles_to_remove:
                # Only attempt removal if there are roles to remove
                await member.remove_roles(*roles_to_remove, reason=f"Promotion to {role_key} by {interaction.user.display_name}")
            await member.add_roles(new_role, reason=f"Promoted to {role_key} by {interaction.user.display_name}")
        except discord.Forbidden:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permissions Error", "I lack the necessary permissions to manage roles. Please ensure I have 'Manage Roles' permission and my role is higher than the roles I'm trying to assign/remove.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return
        except discord.HTTPException as e:
            logger.error(f"Role modification failed for {member.id} in guild {interaction.guild.id}: {e}")
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Discord API Error", f"An error occurred while modifying roles: {e}",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Create final details and log/DM
        details_text = f"Promoted to **{role_key.replace('_roles', '').upper()}**. {details}"
        team_stats = self._get_team_stats(interaction.guild, issuer_team_name, guild_config)

        await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
            "Promotion Successful", f"Successfully promoted {member.mention} to {role_key.replace('_roles', '').upper()} in {issuer_team_name}.",
            PremiumEmbedBuilder.COLORS['success']
        ), ephemeral=True)

        await self._log_transaction(
            interaction.guild, TransactionType.PROMOTION, member, issuer_team_name,
            action_by=interaction.user, details=details_text, roster_info=team_stats
        )

    @app_commands.command(name="demote", description="Demote a member from their current staff role within a team")
    @app_commands.describe(
        member="The member to demote",
        details="Additional demotion details"
    )
    async def demote(self, interaction: discord.Interaction, member: discord.Member,
                   details: str = "No additional details provided."):
        """Demote a member from their current staff role based on hierarchy and team affiliation."""
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", "Server configuration not found. Please contact a server administrator.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        if not await self._can_manage_team(interaction, guild_config):
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permission Denied", "You lack the necessary roles to demote members.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Detect teams for context
        issuer_team_name = await detect_team(interaction.user)
        member_team_name = await detect_team(member)

        if not issuer_team_name:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Mismatch", f"{interaction.user.mention} is not assigned to any team.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        if not member_team_name:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Mismatch", f"{member.mention} is not assigned to any team.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        if issuer_team_name != member_team_name:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Mismatch", f"{member.mention} must be on your team ({issuer_team_name}). Current: {member_team_name}",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Get role levels
        target_level, target_role_key = self._get_user_highest_staff_role_level(member, guild_config, ROLE_HIERARCHY)
        issuer_level, issuer_role_key = self._get_user_highest_staff_role_level(interaction.user, guild_config, ROLE_HIERARCHY)

        if target_level == 0:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Error", f"{member.mention} does not have any assigned staff roles to demote.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Hierarchical checks
        if issuer_level <= target_level and not interaction.user.guild_permissions.administrator:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permission Denied", f"You cannot demote a member with equal or higher rank (Your level: {issuer_level}, Member's level: {target_level}).",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Determine the role to demote FROM
        # Find the role key for the target_level. If target_level is 0, this is problematic.
        # Let's assume any assigned role has a level > 0 as per ROLE_HIERARCHY structure
        if target_level == 0: # Should not happen based on previous check, but for safety
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Error", f"{member.mention} has an unclassified role level.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Find the role_key for the target_level
        demote_from_role_key = None
        for rk, lvl in ROLE_HIERARCHY.items():
            if lvl == target_level:
                demote_from_role_key = rk
                break
        # If target_level is 1 (AC), we still need to remove that role.

        # Get all current staff roles the member has to remove them
        permission_settings = guild_config.get("permission_settings", {})
        roles_to_remove = []
        for role_key_to_check in ROLE_HIERARCHY.keys(): # Iterate through all possible staff role keys
            for configured_role_id_str in permission_settings.get(role_key_to_check, []):
                role_to_remove = discord.utils.get(member.roles, id=int(configured_role_id_str))
                if role_to_remove:
                    # Ensure we only remove roles strictly lower than the issuer or lower than the member's current rank,
                    # and we don't demote to a rank higher than or equal to issuer's rank.
                    # For demotion, we are removing ALL of their current staff roles.
                    roles_to_remove.append(role_to_remove)

        if not roles_to_remove:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Error", f"{member.mention} has no staff roles configured to be removed.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        try:
            # Attempt to remove all of the member's current staff roles
            await member.remove_roles(*roles_to_remove, reason=f"Demoted by {interaction.user.display_name}")
        except discord.Forbidden:
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permissions Error", "I lack the necessary permissions to manage roles. Please ensure I have 'Manage Roles' permission and my role is higher than the roles I'm trying to assign/remove.",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return
        except discord.HTTPException as e:
            logger.error(f"Role removal failed for {member.id} in guild {interaction.guild.id}: {e}")
            await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Discord API Error", f"An error occurred while removing roles: {e}",
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
            return

        # Create final details and log/DM
        removed_role_names = [r.name for r in roles_to_remove]
        details_text = f"Demoted, roles removed: {', '.join(removed_role_names)}. {details}"
        team_stats = self._get_team_stats(interaction.guild, issuer_team_name, guild_config)

        await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
            "Demotion Successful", f"Successfully demoted {member.mention} in {issuer_team_name}.",
            PremiumEmbedBuilder.COLORS['success']
        ), ephemeral=True)

        await self._log_transaction(
            interaction.guild, TransactionType.DEMOTION, member, issuer_team_name,
            action_by=interaction.user, details=details_text, roster_info=team_stats
        )


async def setup(bot):
    await bot.add_cog(EnhancedPromotionCommands(bot))