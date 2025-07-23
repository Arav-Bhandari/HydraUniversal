import logging
import discord
import json
import os
import re
import pytz
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from discord import app_commands
from discord.ext import commands, tasks
from utils.config import get_server_config, save_guild_config, load_json, save_json
from utils.permissions import detect_team

logger = logging.getLogger("bot.signing")

# Constants and Configuration
OFFERS_FILE = "offers.json"
TRANSACTIONS_FILE = "transactions_history.json"
SUSPENSIONS_FILE = "suspensions.json"
GUILDS_FILE = "guilds.json"
DEFAULT_ROSTER_CAP = 53

class TransactionType(Enum):
    SIGNING = "signing"
    RELEASE = "release"
    OFFER = "offer"
    DEMAND = "demand"
    TRADE = "trade"

class OfferStatus(Enum):
    ACTIVE = "active"
    ACCEPTED = "accepted"
    DECLINED = "declINED"
    EXPIRED = "expired"
    RESCINDED = "rescinded"

@dataclass
class TeamStats:
    current_size: int
    roster_cap: int
    available_slots: int
    utilization_percent: float
    salary_cap: float = 0.0
    current_salary: float = 0.0

ROLE_HIERARCHY = {
    "fo_roles": 4,
    "gm_roles": 3,
    "hc_roles": 2,
    "ac_roles": 1
}

class PremiumEmbedBuilder:
    COLORS = {
        'success': 0x00FF88,
        'warning': 0xFFB800,
        'error': 0xFF4757,
        'info': 0x3742FA,
        'neutral': 0x747D8C,
        'premium': 0x9C88FF,
        'gold': 0xFFD700,
        'team': 0x2ECC71,
        'transaction': 0xE67E22
    }

    @staticmethod
    def create_base_embed(title: str, description: str = None, 
                         color: int = None, timestamp: bool = True) -> discord.Embed:
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
        footer_text = f"🏆 {guild.name}"
        if additional_text:
            footer_text += f" • {additional_text}"
        embed.set_footer(text=footer_text, icon_url=guild.icon.url if guild.icon else discord.Embed.Empty)
        return embed

    @staticmethod
    def add_team_branding(embed: discord.Embed, guild: discord.Guild, 
                         team_data: dict, team_name: str) -> discord.Embed:
        embed.set_author(name=f"🏟️ {guild.name} • {team_name}", icon_url=guild.icon.url if guild.icon else discord.Embed.Empty)
        emoji_url = team_data.get("Image") or get_emoji_url(team_data.get("emoji"))
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)
        return embed

    @staticmethod
    def create_roster_field(current_size: int, cap: int, salary: float = 0.0, 
                          salary_cap: float = 0.0, show_visual: bool = True) -> Tuple[str, str]:
        percentage = (current_size / cap) * 100 if cap > 0 else 0
        filled_blocks = int(percentage / 10)
        empty_blocks = 10 - filled_blocks
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
        type_config = {
            TransactionType.SIGNING: {
                'title': 'Player Signed', 'emoji': '✍️', 'default_color': PremiumEmbedBuilder.COLORS['success'],
                'description': f"{player.mention if player else 'A player'} has joined **{team_name}**!"
            },
            TransactionType.RELEASE: {
                'title': 'Player Released', 'emoji': '🚪', 'default_color': PremiumEmbedBuilder.COLORS['warning'],
                'description': f"{player.mention if player else 'A player'} has been released from **{team_name}**."
            },
            TransactionType.OFFER: {
                'title': 'Contract Offer Sent', 'emoji': '📋', 'default_color': PremiumEmbedBuilder.COLORS['info'],
                'description': f"Contract offer sent to {player.mention if player else 'a player'} by **{team_name}**."
            },
            TransactionType.DEMAND: {
                'title': 'Player Resigned', 'emoji': '👋', 'default_color': PremiumEmbedBuilder.COLORS['transaction'],
                'description': f"{player.mention if player else 'A player'} has resigned from **{team_name}**."
            },
            TransactionType.TRADE: {
                'title': 'Player Traded', 'emoji': '🔄', 'default_color': PremiumEmbedBuilder.COLORS['transaction'],
                'description': f"{player.mention if player else 'A player'} has been traded to **{team_name}**."
            }
        }
        config = type_config[transaction_type]

        guild_config = get_server_config(guild.id)
        team_data = guild_config.get("team_data", {}).get(team_name, {})
        team_role_id = team_data.get("role_id")
        embed_color = config['default_color']
        if team_role_id:
            team_role = guild.get_role(int(team_role_id))
            if team_role and team_role.color:
                embed_color = team_role.color

        embed = PremiumEmbedBuilder.create_base_embed(
            title=f"{config['emoji']} {config['title']}",
            description=config['description'],
            color=embed_color
        )
        if player:
            embed.add_field(name="👤 Player", value=f"**{player.display_name}**\n{player.mention}", inline=True)
        else:
            embed.add_field(name="👤 Player", value="*Player not found or has left the server*", inline=True)
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
            embed.add_field(name="📝 Details", value=f"```\n{details}\n```" if len(details) > 50 else f"`{details}`", inline=False)

        return PremiumEmbedBuilder.add_premium_footer(embed, guild)

def get_emoji_url(emoji_str: Optional[str]) -> Optional[str]:
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

class SalaryCapModal(discord.ui.Modal, title="Set Salary Cap"):
    def __init__(self, team_name: str, scope: str):
        super().__init__()
        self.team_name = team_name
        self.scope = scope
        self.salary_input = discord.ui.TextInput(
            label="Salary Cap (in millions)",
            placeholder="e.g., 100.5",
            style=discord.TextStyle.short
        )
        self.add_item(self.salary_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            salary_cap = float(self.salary_input.value)
            if salary_cap < 0:
                await interaction.response.send_message(embed=PremiumEmbedBuilder.create_base_embed(
                    "Invalid Input", "Salary cap cannot be negative.", 
                    PremiumEmbedBuilder.COLORS['error']
                ), ephemeral=True)
                return

            guild_data = load_json(GUILDS_FILE)
            guild_key = str(interaction.guild.id)
            if guild_key not in guild_data:
                guild_data[guild_key] = {"team_data": {}}

            if self.scope == "team":
                if self.team_name not in guild_data[guild_key]["team_data"]:
                    guild_data[guild_key]["team_data"][self.team_name] = {}
                guild_data[guild_key]["team_data"][self.team_name]["salary_cap"] = salary_cap
                embed = PremiumEmbedBuilder.create_base_embed(
                    "Success", f"Salary cap for **{self.team_name}** set to ${salary_cap:,.2f}M.",
                    PremiumEmbedBuilder.COLORS['success']
                )
            else:
                for team in guild_data[guild_key].get("team_data", {}).keys():
                    guild_data[guild_key]["team_data"][team]["salary_cap"] = salary_cap
                guild_data[guild_key]["default_salary_cap"] = salary_cap
                embed = PremiumEmbedBuilder.create_base_embed(
                    "Success", f"Global salary cap set to ${salary_cap:,.2f}M.",
                    PremiumEmbedBuilder.COLORS['success']
                )

            save_json(GUILDS_FILE, guild_data)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            await interaction.response.send_message(embed=PremiumEmbedBuilder.create_base_embed(
                "Invalid Input", "Please enter a valid number.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

class PanelView(discord.ui.View):
    def __init__(self, bot, guild_config: dict, team_name: str = None, scope: str = "team", interaction: discord.Interaction = None):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_config = guild_config
        self.team_name = team_name
        self.scope = scope
        self.guild_data = load_json(GUILDS_FILE)
        self.guild_key = str(interaction.guild.id) if interaction else str(bot.guilds[0].id if bot.guilds else "0")
        team_data = self.guild_data.get(self.guild_key, {}).get("team_data", {})
        self.team_options = [
            discord.SelectOption(label=team, default=team == self.team_name)
            for team in team_data.keys()
        ] + [discord.SelectOption(label="Global", default=self.scope == "server")]
        if not self.team_options:
            self.team_options = [discord.SelectOption(label="No teams configured", default=True, value="none")]
            self.team_select.disabled = True

    @discord.ui.select(options=[discord.SelectOption(label="Loading teams...")], placeholder="Select Scope/Team")
    async def team_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        selected = select.values[0]
        if selected == "none":
            embed = PremiumEmbedBuilder.create_base_embed(
                "No Teams Available", "No teams are configured for this server.", 
                PremiumEmbedBuilder.COLORS['error']
            )
            await interaction.response.edit_message(embed=embed, view=self)
            return
        if selected == "Global":
            self.scope = "server"
            self.team_name = None
        else:
            self.scope = "team"
            self.team_name = selected
        select.options = self.team_options
        for option in select.options:
            option.default = option.label == selected
        embed = PremiumEmbedBuilder.create_base_embed(
            "Scope Updated", f"Configuring settings for: **{selected}**", 
            PremiumEmbedBuilder.COLORS['info']
        )
        await interaction.response.edit_message(embed=embed, view=self)

class PremiumOfferView(discord.ui.View):
    def __init__(self, bot, offer_id: str, team_name: str, player: discord.Member, guild_config: dict):
        super().__init__(timeout=None)
        self.bot = bot
        self.offer_id = offer_id
        self.team_name = team_name
        self.player_id = player.id
        self.guild = player.guild
        self.guild_config = guild_config

    @discord.ui.button(label="Accept Offer", style=discord.ButtonStyle.success, emoji="✅", custom_id="contract_accept_persistent")
    async def accept_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        member = self.guild.get_member(interaction.user.id)
        if not member:
            error_embed = PremiumEmbedBuilder.create_base_embed(
                "Member Not Found", "Could not find you in the server.", 
                PremiumEmbedBuilder.COLORS['error']
            )
            return await interaction.followup.send(embed=error_embed, ephemeral=True)

        try:
            offers = load_json(OFFERS_FILE)
            guild_offers = offers.get(str(self.guild.id), {})
            offer_data = guild_offers.get(self.offer_id)
            if not offer_data or offer_data.get("status") != OfferStatus.ACTIVE.value:
                error_embed = PremiumEmbedBuilder.create_base_embed(
                    "Offer Unavailable", "This offer is no longer active or has expired.", 
                    PremiumEmbedBuilder.COLORS['error']
                )
                return await interaction.followup.send(embed=error_embed, ephemeral=True)

            team_data = self.guild_config.get("team_data", {}).get(self.team_name, {})
            current_team_name = await detect_team(member)
            if current_team_name:
                error_embed = PremiumEmbedBuilder.create_base_embed(
                    "Already Signed", f"You are already signed to **{current_team_name}**. Please get released first.", 
                    PremiumEmbedBuilder.COLORS['error']
                )
                return await interaction.followup.send(embed=error_embed, ephemeral=True)

            team_role_id = team_data.get("role_id")
            if not team_role_id:
                error_embed = PremiumEmbedBuilder.create_base_embed(
                    "Configuration Error", f"Team role not configured for **{self.team_name}**.", 
                    PremiumEmbedBuilder.COLORS['error']
                )
                return await interaction.followup.send(embed=error_embed, ephemeral=True)

            team_role = self.guild.get_role(int(team_role_id))
            if not team_role:
                error_embed = PremiumEmbedBuilder.create_base_embed(
                    "Role Not Found", f"Team role for **{self.team_name}** no longer exists.", 
                    PremiumEmbedBuilder.COLORS['error']
                )
                return await interaction.followup.send(embed=error_embed, ephemeral=True)

            await member.add_roles(team_role, reason=f"Accepted contract offer - {self.offer_id}")

            # Remove free agent role if they have it
            guild_config = get_server_config(self.guild.id)
            permission_settings = guild_config.get("permission_settings", {})
            free_agent_role_ids = permission_settings.get("free_agent_roles", [])

            roles_to_remove = []
            for role_id in free_agent_role_ids:
                fa_role = self.guild.get_role(role_id)
                if fa_role and fa_role in member.roles:
                    roles_to_remove.append(fa_role)

            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason=f"Signed to team - removing free agent status")
                except Exception as e:
                    logger.warning(f"Failed to remove free agent role from {member.id}: {e}")

            offer_data["status"] = OfferStatus.ACCEPTED.value
            offer_data["accepted_at"] = datetime.now(pytz.utc).timestamp()
            save_json(OFFERS_FILE, offers)

            success_embed = PremiumEmbedBuilder.create_base_embed(
                "🎉 Welcome to the Team!",
                f"Congratulations! You have successfully joined **{self.team_name}**!",
                PremiumEmbedBuilder.COLORS['success']
            )
            team_info = team_data
            success_embed = PremiumEmbedBuilder.add_team_branding(success_embed, self.guild, team_info, self.team_name)
            success_embed.add_field(name="📝 Contract Details", value=f"```\n{offer_data.get('details', 'Standard terms')}\n```", inline=False)
            success_embed.add_field(name="🏆 Next Steps", value="• Check team channels\n• Contact team management\n• Review guidelines", inline=False)
            await interaction.edit_original_response(embed=success_embed, view=None)

            cog = self.bot.get_cog("EnhancedSigningCommands")
            if cog:
                team_stats = cog._get_team_stats(self.guild, self.team_name, self.guild_config)
                await cog._log_transaction(
                    self.guild, TransactionType.SIGNING, member, self.team_name,
                    details=f"Accepted offer: {offer_data.get('details', 'N/A')}", roster_info=team_stats
                )
        except Exception as e:
            logger.error(f"Error accepting offer {self.offer_id}: {e}", exc_info=True)
            error_embed = PremiumEmbedBuilder.create_base_embed(
                "Signing Failed", "An unexpected error occurred while processing your signing.", 
                PremiumEmbedBuilder.COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

    @discord.ui.button(label="Decline Offer", style=discord.ButtonStyle.danger, emoji="❌", custom_id="contract_decline_persistent")
    async def decline_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        member = self.guild.get_member(interaction.user.id)
        if not member:
            error_embed = PremiumEmbedBuilder.create_base_embed(
                "Member Not Found", "Could not find you in the server.", 
                PremiumEmbedBuilder.COLORS['error']
            )
            return await interaction.followup.send(embed=error_embed, ephemeral=True)

        try:
            offers = load_json(OFFERS_FILE)
            guild_offers = offers.get(str(self.guild.id), {})
            offer_data = guild_offers.get(self.offer_id)
            if not offer_data:
                error_embed = PremiumEmbedBuilder.create_base_embed(
                    "Offer Not Found", "This offer could not be found.", 
                    PremiumEmbedBuilder.COLORS['error']
                )
                return await interaction.followup.send(embed=error_embed, ephemeral=True)

            offer_data["status"] = OfferStatus.DECLINED.value
            offer_data["declined_at"] = datetime.now(pytz.utc).timestamp()
            save_json(OFFERS_FILE, offers)

            decline_embed = PremiumEmbedBuilder.create_base_embed(
                "📋 Offer Declined",
                f"You have declined the contract offer from **{self.team_name}**.",
                PremiumEmbedBuilder.COLORS['neutral']
            )
            team_info = self.guild_config.get("team_data", {}).get(self.team_name, {})
            decline_embed = PremiumEmbedBuilder.add_team_branding(decline_embed, self.guild, team_info, self.team_name)
            decline_embed.add_field(name="📝 Original Offer", value=f"```\n{offer_data.get('details', 'Standard terms')}\n```", inline=False)
            decline_embed.add_field(name="💡 Future Opportunities", value="You may receive additional offers from other teams.", inline=False)
            await interaction.edit_original_response(embed=decline_embed, view=None)

            cog = self.bot.get_cog("EnhancedSigningCommands")
            if cog:
                await cog._log_transaction(
                    self.guild, TransactionType.OFFER, member, self.team_name,
                    details=f"Offer declined: {offer_data.get('details', 'N/A')}"
                )
        except Exception as e:
            logger.error(f"Error declining offer {self.offer_id}: {e}", exc_info=True)
            error_embed = PremiumEmbedBuilder.create_base_embed(
                "Decline Failed", "An error occurred while declining the offer.", 
                PremiumEmbedBuilder.COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

    @discord.ui.button(label="View Details", style=discord.ButtonStyle.secondary, emoji="📖")
    async def view_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            offers = load_json(OFFERS_FILE)
            guild_offers = offers.get(str(self.guild.id), {})
            offer_data = guild_offers.get(self.offer_id)
            if not offer_data:
                error_embed = PremiumEmbedBuilder.create_base_embed(
                    "Offer Not Found", "This offer could not be found.", 
                    PremiumEmbedBuilder.COLORS['error']
                )
                return await interaction.followup.send(embed=error_embed, ephemeral=True)

            details_embed = PremiumEmbedBuilder.create_base_embed(
                "📊 Detailed Offer Information",
                f"Details for your contract offer from **{self.team_name}**",
                PremiumEmbedBuilder.COLORS['info']
            )
            cog = self.bot.get_cog("EnhancedSigningCommands")
            if cog:
                team_stats = cog._get_team_stats(self.guild, self.team_name, self.guild_config)
                roster_name, roster_value = PremiumEmbedBuilder.create_roster_field(
                    team_stats.current_size, team_stats.roster_cap,
                    team_stats.current_salary, team_stats.salary_cap
                )
                details_embed.add_field(name=roster_name, value=roster_value, inline=False)

            created_time = int(offer_data.get("created_at", 0))
            expires_time = int(offer_data.get("expires_at", 0))
            details_embed.add_field(
                name="⏰ Timeline",
                value=f"**Sent:** <t:{created_time}:F>\n**Expires:** <t:{expires_time}:F>\n**Status:** `{offer_data.get('status', 'Unknown').title()}`",
                inline=False
            )
            details_embed.add_field(
                name="📋 Full Contract Terms",
                value=f"```\n{offer_data.get('details', 'No additional details provided')}\n```",
                inline=False
            )
            offered_by_name = offer_data.get("offerer_name", "Unknown")
            details_embed.add_field(name="👨‍💼 Offered By", value=f"**{offered_by_name}**\n*{self.team_name} Management*", inline=True)
            details_embed.add_field(name="🆔 Offer ID", value=f"`{self.offer_id}`", inline=True)
            details_embed = PremiumEmbedBuilder.add_premium_footer(details_embed, self.guild, "Confidential Offer Details")
            await interaction.followup.send(embed=details_embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error viewing offer details {self.offer_id}: {e}", exc_info=True)
            error_embed = PremiumEmbedBuilder.create_base_embed(
                "Details Unavailable", "Could not retrieve offer details.", 
                PremiumEmbedBuilder.COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

class SignConfirmationView(discord.ui.View):
    def __init__(self, bot, cmd_user: discord.Member, team_name: str, player_to_sign: discord.Member,
                 details: str, cap: int, current_size: int, guild_config: dict):
        super().__init__(timeout=120)
        self.bot = bot
        self.cmd_user = cmd_user
        self.team_name = team_name
        self.player_to_sign = player_to_sign
        self.details = details
        self.cap = cap
        self.current_size = current_size
        self.guild_config = guild_config

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.cmd_user.id:
            return True
        await interaction.response.send_message(embed=PremiumEmbedBuilder.create_base_embed(
            "Permission Denied", "Not your confirmation.", PremiumEmbedBuilder.COLORS['error']
        ), ephemeral=True)
        return False

    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Confirm Sign", style=discord.ButtonStyle.success, emoji="✅", custom_id="sign_confirm_direct")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        team_data = self.guild_config.get("team_data", {}).get(self.team_name, {})
        team_role_id = team_data.get("role_id")
        if not team_role_id:
            await interaction.response.edit_message(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", f"Role for {self.team_name} not set.", 
                PremiumEmbedBuilder.COLORS['error']
            ), view=None)
            return

        team_role = interaction.guild.get_role(int(team_role_id))
        if not team_role:
            await interaction.response.edit_message(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Error", f"Role for {self.team_name} not found.", 
                PremiumEmbedBuilder.COLORS['error']
            ), view=None)
            return

        if len(team_role.members) >= self.cap:
            await interaction.response.edit_message(embed=PremiumEmbedBuilder.create_base_embed(
                "Roster Full", f"{self.team_name} roster is full ({self.cap}).", 
                PremiumEmbedBuilder.COLORS['error']
            ), view=None)
            return

        try:
            await self.player_to_sign.add_roles(team_role, reason=f"Signed by {self.cmd_user.name}")

            # Remove free agent role if they have it
            guild_config = get_server_config(interaction.guild.id)
            permission_settings = guild_config.get("permission_settings", {})
            free_agent_role_ids = permission_settings.get("free_agent_roles", [])

            roles_to_remove = []
            for role_id in free_agent_role_ids:
                fa_role = interaction.guild.get_role(role_id)
                if fa_role and fa_role in self.player_to_sign.roles:
                    roles_to_remove.append(fa_role)

            if roles_to_remove:
                try:
                    await self.player_to_sign.remove_roles(*roles_to_remove, reason=f"Signed to team - removing free agent status")
                except Exception as e:
                    logger.warning(f"Failed to remove free agent role from {self.player_to_sign.id}: {e}")

        except Exception as e:
            logger.error(f"Direct sign role add failed: {e}")
            await interaction.response.edit_message(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Error", "Failed to assign role.", PremiumEmbedBuilder.COLORS['error']
            ), view=None)
            return

        dm_embed = PremiumEmbedBuilder.create_base_embed(
            title="🎉 You've Been Signed!",
            description=f"Congratulations! You have been signed to **{self.team_name}** in **{interaction.guild.name}**.",
            color=team_role.color if team_role.color else PremiumEmbedBuilder.COLORS['success']
        )
        dm_embed = PremiumEmbedBuilder.add_team_branding(dm_embed, interaction.guild, team_data, self.team_name)
        dm_embed.add_field(name="📝 Contract Details", value=f"```\n{self.details}\n```", inline=False)
        dm_embed.add_field(name="🏆 Next Steps", value="• Check team channels\n• Contact team management\n• Review team guidelines", inline=False)
        dm_embed = PremiumEmbedBuilder.add_premium_footer(dm_embed, interaction.guild, "Welcome to the Team!")

        try:
            await self.player_to_sign.send(embed=dm_embed)
        except discord.Forbidden:
            logger.warning(f"Could not DM {self.player_to_sign.id} for signing notification (DMs disabled).")
        except Exception as e:
            logger.error(f"Failed to send signing DM to {self.player_to_sign.id}: {e}")

        self.disable_all_items()
        cog = self.bot.get_cog("EnhancedSigningCommands")
        team_stats = cog._get_team_stats(interaction.guild, self.team_name, self.guild_config)
        final_embed = PremiumEmbedBuilder.create_transaction_embed(
            TransactionType.SIGNING, self.player_to_sign, self.team_name, interaction.guild,
            details=self.details, action_by=self.cmd_user, roster_info=team_stats
        )
        await interaction.response.edit_message(embed=final_embed, view=self)

        if cog:
            await cog._log_transaction(
                interaction.guild, TransactionType.SIGNING, self.player_to_sign, self.team_name,
                action_by=self.cmd_user, details=self.details, roster_info=team_stats
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="sign_cancel_direct")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.disable_all_items()
        cancel_embed = PremiumEmbedBuilder.create_base_embed(
            "Signing\n{offer_data.get('details', 'Standard terms')}\n```", inline=False)
            embed.add_field(name="🆔 Offer ID", value=f"`{offer_id}`", inline=True)

            if offer_data.get("dm_message_id") and player:
                try:
                    dm_channel = await player.create_dm()
                    original_dm = await dm_channel.fetch_message(int(offer_data["dm_message_id"]))
                    if original_dm and original_dm.author == self.bot.user:
                        await original_dm.edit(embed=embed, view=None)
                except Exception as e:
                    logger.warning(f"Could not edit player DM {offer_data['dm_message_id']} for expired offer {offer_id}: {e}")

            member = guild.get_member(int(player_id)) if player_id else None
            await self._log_transaction(guild, TransactionType.OFFER, member,
                                       team_name, details=f"Offer expired: {offer_data.get('details', 'N/A')}")
        except Exception as e:
            logger.error(f"Error handling offer expiration {offer_id}: {e}", exc_info=True)

    @tasks.loop(hours=24)
    async def cleanup_old_transactions(self):
        try:
            history = load_json(TRANSACTIONS_FILE)
            current_time = datetime.now(pytz.utc).timestamp()
            thirty_days_ago = current_time - (30 * 24 * 60 * 60)
            changes_made = False
            for guild_id_str, transactions in list(history.items()):
                if not isinstance(transactions, list): continue
                original_count = len(transactions)
                history[guild_id_str] = [
                    txn for txn in transactions
                    if txn.get("timestamp", 0) > thirty_days_ago
                ]
                if len(history[guild_id_str]) != original_count:
                    changes_made = True
            if changes_made:
                save_json(TRANSACTIONS_FILE, history)
        except Exception as e:
            logger.error(f"Error in cleanup_old_transactions: {e}", exc_info=True)

    @check_expired_offers.before_loop
    @cleanup_old_transactions.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="panel", description="Open an interactive panel to configure team or server settings")
    @app_commands.describe(team_name="The team to configure (optional, defaults to your team)")
    async def panel(self, interaction: discord.Interaction, team_name: str = None):
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", "Server configuration not found.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        guild_data = load_json(GUILDS_FILE)
        guild_key = str(interaction.guild.id)
        if guild_key not in guild_data:
            guild_data[guild_key] = {"team_data": {}}
            save_json(GUILDS_FILE, guild_data)

        if team_name:
            if team_name not in guild_data[guild_key]["team_data"]:
                return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                    "Team Not Found", f"Team {team_name} is not configured.", 
                    PremiumEmbedBuilder.COLORS['error']
                ), ephemeral=True)
            scope = "team"
        else:
            detected_team = await detect_team(interaction.user)
            if detected_team and await self._can_manage_team_signings(interaction, guild_config):
                team_name = detected_team
                scope = "team"
            else:
                scope = "server"
                team_name = None

        view = PanelView(self.bot, guild_config, team_name, scope, interaction=interaction)
        embed = PremiumEmbedBuilder.create_base_embed(
            "Settings Panel", "Use the buttons and dropdown to configure settings.", 
            PremiumEmbedBuilder.COLORS['info']
        )
        view.team_select.options = view.team_options
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="demand", description="Resign from your team and relinquish all associated roles")
    async def demand(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", "Server configuration not found.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        player = interaction.user
        player_team_name = await detect_team(player)
        if not player_team_name:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Error", "You are not currently signed to any team.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        team_stats_before = self._get_team_stats(interaction.guild, player_team_name, guild_config)
        team_role_id = guild_config.get("team_data", {}).get(player_team_name, {}).get("role_id")
        team_role = interaction.guild.get_role(int(team_role_id)) if team_role_id else None

        roles_to_remove = {team_role} if team_role else set()
        permission_settings = guild_config.get("permission_settings", {})
        for role_key in ROLE_HIERARCHY.keys():
            for r_id_str in permission_settings.get(role_key, []):
                coach_role = player.get_role(int(r_id_str))
                if coach_role:
                    roles_to_remove.add(coach_role)

        roles_to_remove = {r for r in roles_to_remove if r is not None}
        if not roles_to_remove:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Error", "Could not find any team or staff roles to remove.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        try:
            await player.remove_roles(*roles_to_remove, reason=f"Player self-demanded removal from {player_team_name}")
        except discord.Forbidden:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permissions Error", "I lack permissions to remove your roles.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)
        except discord.HTTPException as e:
            logger.error(f"HTTP error during self-removal for {player.id}: {e}", exc_info=True)
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Discord API Error", f"An error occurred while removing your roles: {e}", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        team_stats_after = self._get_team_stats(interaction.guild, player_team_name, guild_config)
        details_text = f"Roles removed: {', '.join(r.mention for r in roles_to_remove)}"
        response_embed = PremiumEmbedBuilder.create_transaction_embed(
            TransactionType.DEMAND, player, player_team_name, interaction.guild,
            action_by=player, roster_info=team_stats_before, details=details_text
        )
        await interaction.followup.send(embed=response_embed, ephemeral=True)

        await self._log_transaction(
            interaction.guild, TransactionType.DEMAND, player, player_team_name,
            action_by=player, 
            details=f"Resigned and removed roles: {', '.join(r.name for r in roles_to_remove)}",
            roster_info=team_stats_after
        )

    @app_commands.command(name="offer", description="Send a contract offer to a player")
    @app_commands.describe(
        player="Player to offer",
        contract_details="Offer details",
        expiration_time="Expire time (e.g., 24h, 7d, 1w)",
        salary="The salary for the contract (in millions, e.g., 10.5 for $10.5M, optional)"
    )
    async def offer(self, interaction: discord.Interaction, player: discord.Member, 
                   contract_details: str = "Standard terms.", expiration_time: str = "24h",
                   salary: float = None):
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", "Server configuration not found.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        guild_data = load_json(GUILDS_FILE)
        guild_key = str(interaction.guild.id)
        if guild_key not in guild_data or guild_data[guild_key].get("whitelisted", True):
            pass  # Guild is whitelisted if not in file or explicitly whitelisted
        else:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Guild Not Whitelisted", "This guild is not authorized to use this command.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        offering_team_name = await detect_team(interaction.user)
        if not offering_team_name:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Error", "You are not in a team.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        if not await self._can_manage_team_signings(interaction, guild_config):
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permission Denied", "You lack the necessary roles to make contract offers.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        team_data = guild_data.get(guild_key, {}).get("team_data", {}).get(offering_team_name, {})
        if not team_data.get("offering_enabled", True):
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Offering Disabled", f"Contract offers are currently disabled for {offering_team_name}.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        team_stats = self._get_team_stats(interaction.guild, offering_team_name, guild_config)
        if team_stats.available_slots <= 0:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Roster Full", f"{offering_team_name} has no available roster spots.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        suspensions = load_json(SUSPENSIONS_FILE)
        guild_id_str = str(interaction.guild.id)
        guild_suspensions = suspensions.get(guild_id_str, {})
        is_suspended = False
        suspension_reason = "No reason provided"
        for susp_data in guild_suspensions.values():
            if susp_data.get("player_id") == str(player.id) and susp_data.get("status") == "active":
                is_suspended = True
                suspension_reason = susp_data.get("reason", "No reason provided.")
                break

        if is_suspended:
            error_embed = PremiumEmbedBuilder.create_base_embed(
                "Player is Suspended",
                f"{player.mention} cannot be offered a contract because they have an active suspension.",
                PremiumEmbedBuilder.COLORS['error']
            )
            error_embed.add_field(name="Reason", value=suspension_reason, inline=False)
            return await interaction.followup.send(embed=error_embed, ephemeral=True)

        offers = await self.load_offers()
        guild_offers = offers.get(guild_id_str, {})
        for _, existing_offer in guild_offers.items():
            if (existing_offer.get("team") == offering_team_name and 
                existing_offer.get("player_id") == str(player.id) and 
                existing_offer.get("status") == OfferStatus.ACTIVE.value):
                return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                    "Offer Exists", f"An active offer to {player.mention} from your team already exists.", 
                    PremiumEmbedBuilder.COLORS['error']
                ), ephemeral=True)

        if salary is not None:
            if salary < 0:
                return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                    "Invalid Salary", "Salary cannot be negative.", 
                    PremiumEmbedBuilder.COLORS['error']
                ), ephemeral=True)
            salary_cap = team_data.get("salary_cap", 0.0)
            current_salary = team_data.get("current_salary", 0.0)
            if salary_cap > 0 and (current_salary + salary) > salary_cap:
                return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                    "Salary Cap Exceeded", 
                    f"Offer of ${salary:,.2f}M exceeds {offering_team_name}'s salary cap of ${salary_cap:,.2f}M (current: ${current_salary:,.2f}M).", 
                    PremiumEmbedBuilder.COLORS['error']
                ), ephemeral=True)

        match = re.match(r"(\d+)([hdw])", expiration_time.lower())
        if match:
            val, unit = int(match.group(1)), match.group(2)
            delta = timedelta(hours=val) if unit == 'h' else timedelta(days=val) if unit == 'd' else timedelta(weeks=val)
            expires_at_timestamp = (datetime.now(pytz.utc) + delta).timestamp()
        else:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Invalid Expiration", "Use formats like `24h`, `3d`, or `1w`.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        new_offer_id = f"OFFER-{datetime.now(pytz.utc).strftime('%Y%m%d%H%M%S%f')}"
        details = contract_details
        if salary is not None:
            details += f" | Salary: ${salary:,.2f}M"
            if not await self._update_team_salary(interaction.guild.id, offering_team_name, salary):
                return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                    "Error", "Failed to update team salary.", 
                    PremiumEmbedBuilder.COLORS['error']
                ), ephemeral=True)
            team_stats.current_salary += salary

        offer_payload = {
            "team": offering_team_name,
            "player_id": str(player.id),
            "player_name": player.display_name,
            "details": contract_details,
            "salary": salary,
            "status": OfferStatus.ACTIVE.value,
            "created_at": datetime.now(pytz.utc).timestamp(),
            "expires_at": expires_at_timestamp,
            "offered_by_id": str(interaction.user.id),
            "offerer_name": interaction.user.display_name,
            "guild_id": guild_id_str,
            "dm_message_id": None
        }

        team_specific_data = guild_config.get("team_data", {}).get(offering_team_name, {})
        dm_embed = PremiumEmbedBuilder.create_base_embed(
            title=f"You've Received a Contract Offer!",
            description=f"**{offering_team_name}** from **{interaction.guild.name}** has sent you a contract offer.",
            color=PremiumEmbedBuilder.COLORS['gold']
        )
        dm_embed = PremiumEmbedBuilder.add_team_branding(dm_embed, interaction.guild, team_specific_data, offering_team_name)
        dm_embed.add_field(name="📝 Details", value=f"```\n{details}\n", inline=False)
        dm_embed.add_field(name="⏰ Expires", value=f"This offer expires <t:{int(expires_at_timestamp)}:R>.", inline=False)
        dm_embed.set_footer(text=f"Offer ID: {new_offer_id}")

        view = PremiumOfferView(self.bot, new_offer_id, offering_team_name, player, guild_config)
        try:
            dm_msg = await player.send(embed=dm_embed, view=view)
            offer_payload["dm_message_id"] = str(dm_msg.id)
            success_embed = PremiumEmbedBuilder.create_base_embed(
                "Offer Sent", f"An offer has been successfully sent to {player.mention} via DM.", 
                PremiumEmbedBuilder.COLORS['success']
            )
            await interaction.followup.send(embed=success_embed, ephemeral=True)
        except discord.Forbidden:
            warning_embed = PremiumEmbedBuilder.create_base_embed(
                "Offer Logged (DM Failed)", 
                f"Could not DM {player.mention} (they may have DMs disabled), but the offer is still logged.", 
                PremiumEmbedBuilder.COLORS['warning']
            )
            await interaction.followup.send(embed=warning_embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Offer DM to {player.id} failed: {e}", exc_info=True)
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Failed to Send Offer", "An unexpected error occurred while sending the offer.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        if guild_id_str not in offers:
            offers[guild_id_str] = {}
        offers[guild_id_str][new_offer_id] = offer_payload
        await self.save_offers(offers)
        await self._log_transaction(
            interaction.guild, TransactionType.OFFER, player, offering_team_name,
            action_by=interaction.user, details=details, roster_info=team_stats
        )

    @app_commands.command(name="sign", description="Sign a player directly to your team")
    @app_commands.describe(player="Player to sign", contract_details="Signing details")
    async def sign(self, interaction: discord.Interaction, player: discord.Member, 
                  contract_details: str = "Standard terms."):
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", "Server configuration not found.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        guild_data = load_json(GUILDS_FILE)
        guild_key = str(interaction.guild.id)
        if guild_key not in guild_data or guild_data[guild_key].get("whitelisted", True):
            pass
        else:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Guild Not Whitelisted", "This guild is not authorized to use this command.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        if not await self._can_manage_team_signings(interaction, guild_config):
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permission Denied", "You lack the necessary roles to sign players.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        signing_team_name = await detect_team(interaction.user)
        if not signing_team_name:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Error", "You are not in a team.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        team_data = guild_data.get(guild_key, {}).get("team_data", {}).get(signing_team_name, {})
        if not team_data.get("signing_enabled", True):
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Signing Disabled", f"Direct signings are currently disabled for {signing_team_name}.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        suspensions = load_json(SUSPENSIONS_FILE)
        guild_id_str = str(interaction.guild.id)
        guild_suspensions = suspensions.get(guild_id_str, {})
        is_suspended = False
        suspension_reason = "No reason provided"
        for susp_data in guild_suspensions.values():
            if susp_data.get("player_id") == str(player.id) and susp_data.get("status") == "active":
                is_suspended = True
                suspension_reason = susp_data.get("reason", "No reason provided.")
                break

        if is_suspended:
            error_embed = PremiumEmbedBuilder.create_base_embed(
                "Player is Suspended",
                f"{player.mention} cannot be signed due to an active suspension.",
                PremiumEmbedBuilder.COLORS['error']
            )
            error_embed.add_field(name="Reason", value=suspension_reason, inline=False)
            return await interaction.followup.send(embed=error_embed, ephemeral=True)

        player_team_name = await detect_team(player)
        if player_team_name:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Player Signed", f"{player.mention} is already signed to {player_team_name}.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        team_stats = self._get_team_stats(interaction.guild, signing_team_name, guild_config)
        if team_stats.available_slots <= 0:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Roster Full", f"{signing_team_name} roster is full ({team_stats.roster_cap}).", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        confirm_embed = PremiumEmbedBuilder.create_transaction_embed(
            TransactionType.SIGNING, player, signing_team_name, interaction.guild,
            details=contract_details, action_by=interaction.user, roster_info=team_stats
        )
        view = SignConfirmationView(self.bot, interaction.user, signing_team_name, player, 
                                   contract_details, team_stats.roster_cap, team_stats.current_size, guild_config)
        await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)

    @app_commands.command(name="release", description="Release a player from your team")
    @app_commands.describe(player="The player to release from your team")
    async def release(self, interaction: discord.Interaction, player: discord.Member):
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", "Server configuration not found.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        if not await self._can_manage_team_signings(interaction, guild_config):
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permission Denied", "You lack the necessary roles to release players.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        releasing_team_name = await detect_team(interaction.user)
        if not releasing_team_name:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Error", "You are not in a team.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        player_team_name = await detect_team(player)
        if player_team_name != releasing_team_name:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Mismatch", f"{player.mention} is not on your team.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        if interaction.user.id != player.id:
            user_level = self._get_user_max_role_level(interaction.user, guild_config, ROLE_HIERARCHY)
            player_level = self._get_user_max_role_level(player, guild_config, ROLE_HIERARCHY)
            if player_level > 0 and player_level >= user_level and not interaction.user.guild_permissions.administrator:
                return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                    "Permission Denied", "You cannot release staff of equal or higher rank.", 
                    PremiumEmbedBuilder.COLORS['error']
                ), ephemeral=True)

        team_role_id = guild_config.get("team_data", {}).get(releasing_team_name, {}).get("role_id")
        roles_to_remove = {interaction.guild.get_role(int(team_role_id))} if team_role_id else set()
        for role_key in ROLE_HIERARCHY.keys():
            for r_id_str in guild_config.get("permission_settings", {}).get(role_key, []):
                staff_role = player.get_role(int(r_id_str))
                if staff_role:
                    roles_to_remove.add(staff_role)

        roles_to_remove = {r for r in roles_to_remove if r is not None}
        try:
            await player.remove_roles(*roles_to_remove, reason=f"Released by {interaction.user.display_name}")
        except Exception as e:
            logger.error(f"Role removal failed for {player.id} from {releasing_team_name}: {e}")
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Role Error", "Failed to remove roles.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        team_stats = self._get_team_stats(interaction.guild, releasing_team_name, guild_config)
        details_text = f"Roles removed: {', '.join(r.mention for r in roles_to_remove)}"
        resp_embed = PremiumEmbedBuilder.create_transaction_embed(
            TransactionType.RELEASE, player, releasing_team_name, interaction.guild,
            action_by=interaction.user, roster_info=team_stats, details=details_text
        )
        await interaction.followup.send(embed=resp_embed, ephemeral=True)

        await self._log_transaction(
            interaction.guild, TransactionType.RELEASE, player, releasing_team_name,
            action_by=interaction.user, details=f"Roles removed: {', '.join(r.name for r in roles_to_remove)}",
            roster_info=team_stats
        )

    @app_commands.command(name="rescindoffer", description="Withdraw an active contract offer")
    @app_commands.describe(player="The player whose offer you want to rescind")
    async def rescindoffer(self, interaction: discord.Interaction, player: discord.Member):
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Configuration Error", "Server configuration not found.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        if not await self._can_manage_team_signings(interaction, guild_config):
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Permission Denied", "You lack the necessary roles to rescind offers.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        offering_team_name = await detect_team(interaction.user)
        if not offering_team_name:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "Team Error", "You are not in a team.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        offers = await self.load_offers()
        guild_id_str = str(interaction.guild.id)
        guild_offers = offers.get(guild_id_str, {})
        found_offer_id, found_offer_data = None, None
        for off_id, off_data in guild_offers.items():
            if (off_data.get("team") == offering_team_name and 
                off_data.get("player_id") == str(player.id) and 
                off_data.get("status") == OfferStatus.ACTIVE.value):
                found_offer_id, found_offer_data = off_id, off_data
                break

        if not found_offer_id:
            return await interaction.followup.send(embed=PremiumEmbedBuilder.create_base_embed(
                "No Offer Found", f"There is no active offer from {offering_team_name} to {player.mention}.", 
                PremiumEmbedBuilder.COLORS['error']
            ), ephemeral=True)

        offer_salary = found_offer_data.get("salary")
        if offer_salary:
            await self._update_team_salary(interaction.guild.id, offering_team_name, -offer_salary)
        found_offer_data["status"] = OfferStatus.RESCINDED.value
        found_offer_data["rescinded_at"] = datetime.now(pytz.utc).timestamp()
        team_data = guild_config.get("team_data", {}).get(offering_team_name, {})
        resp_embed = PremiumEmbedBuilder.create_base_embed(
            "Offer Rescinded",
            f"The offer from **{offering_team_name}** to {player.mention} has been rescinded by {interaction.user.mention}.",
            PremiumEmbedBuilder.COLORS['warning']
        )
        resp_embed = PremiumEmbedBuilder.add_team_branding(resp_embed, interaction.guild, team_data, offering_team_name)

        if found_offer_data.get("dm_message_id"):
            try:
                dm_channel = await player.create_dm()
                original_dm = await dm_channel.fetch_message(int(found_offer_data["dm_message_id"]))
                if original_dm and original_dm.author == self.bot.user:
                    await original_dm.edit(embed=resp_embed, view=None)
            except Exception as e:
                logger.warning(f"Could not edit player DM for rescinded offer {found_offer_id}: {e}")

        await self.save_offers(offers)
        await interaction.followup.send(embed=resp_embed, ephemeral=True)
        await self._log_transaction(
            interaction.guild, TransactionType.OFFER, player, offering_team_name,
            action_by=interaction.user, details=f"Offer rescinded: {found_offer_data.get('details', 'N/A')}"
        )

    @app_commands.command(name="viewoffers", description="View all active offers for this server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def view_offers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_config = get_server_config(interaction.guild.id)
        all_offers = (await self.load_offers()).get(str(interaction.guild.id), {})
        active_embeds = []

        for offer_id, offer_data in all_offers.items():
            if offer_data.get("status") == OfferStatus.ACTIVE.value:
                team_name = offer_data.get("team", "N/A")
                player_mention = f"<@{offer_data.get('player_id')}>"
                team_info = guild_config.get("team_data", {}).get(team_name, {})
                team_stats = self._get_team_stats(interaction.guild, team_name, guild_config)

                embed = PremiumEmbedBuilder.create_base_embed(
                    title=f"Offer: {team_name} to {offer_data.get('player_name', 'Player')}",
                    color=PremiumEmbedBuilder.COLORS['info']
                )
                embed = PremiumEmbedBuilder.add_team_branding(embed, interaction.guild, team_info, team_name)
                roster_name, roster_value = PremiumEmbedBuilder.create_roster_field(
                    team_stats.current_size, team_stats.roster_cap,
                    team_stats.current_salary, team_stats.salary_cap
                )
                embed.add_field(name=roster_name, value=roster_value, inline=False)
                embed.add_field(name="Player", value=player_mention, inline=True)
                embed.add_field(name="Offered By", value=f"<@{offer_data.get('offered_by_id')}>", inline=True)
                embed.add_field(name="Expires", value=f"<t:{int(offer_data.get('expires_at', 0))}:R>", inline=True)
                embed.add_field(name="Details", value=f"```\n{offer_data.get('details', 'N/A')}\n