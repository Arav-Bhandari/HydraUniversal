import discord
import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from discord import app_commands
from discord.ext import commands, tasks
from difflib import SequenceMatcher
from typing import List, Dict, Optional, Union, Tuple
import json
import os
import re
import pytz # For timezone handling
from enum import Enum
from dataclasses import dataclass

# --- Assuming these utilities and cogs are correctly set up and imported ---

# --- Core Utilities Imports (adjust paths as necessary) ---
try:
    from utils.config import (
        get_server_config,
        load_json, save_json
    )
    from utils.permissions import detect_team
    from utils.logging import log_action
    # Assuming EmbedBuilder is your base embed class and PremiumEmbedBuilder is available from EnhancedSigningCommands or elsewhere.
    # If PremiumEmbedBuilder is defined within EnhancedSigningCommands, you might need to access it via `signing_cog.PremiumEmbedBuilder`.
    # For this example, we'll assume it's accessible like EmbedBuilder.
    from utils.embeds import EmbedBuilder
except ImportError as e:
    logging.error(f"Failed to import utility: {e}. Ensure your 'utils' directory is set up correctly.")
    # Provide mock or fallback implementations if these are critical and missing.
    # For this specific context, it's assumed they exist and work.

# --- Constants and Data Structures (likely from EnhancedSigningCommands) ---
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
    DECLINED = "declined"
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

# --- Embed Builder and View Classes (Assuming they are available from EnhancedSigningCommands) ---
# These are critical dependencies. Ensure they are correctly defined and accessible.
# If not, you'll need to provide them or adapt the code to use basic discord.Embed.

# Mock PremiumEmbedBuilder if not available. In a real setup, this would be imported.
class PremiumEmbedBuilder:
    COLORS = {
        'success': 0x00FF88, 'warning': 0xFFB800, 'error': 0xFF4757, 'info': 0x3742FA,
        'neutral': 0x747D8C, 'premium': 0x9C88FF, 'gold': 0xFFD700,
        'team': 0x2ECC71, 'transaction': 0xE67E22
    }
    @staticmethod
    def create_base_embed(title: str, description: str = None, color: int = None, timestamp: bool = True) -> discord.Embed:
        return discord.Embed(title=f"⚡ {title}", description=description, color=color or PremiumEmbedBuilder.COLORS['premium'], timestamp=datetime.now(pytz.utc) if timestamp else discord.Embed.Empty)
    @staticmethod
    def add_premium_footer(embed: discord.Embed, guild: discord.Guild, additional_text: str = None) -> discord.Embed:
        footer_text = f"🏆 {guild.name}"
        if additional_text: footer_text += f" • {additional_text}"
        embed.set_footer(text=footer_text, icon_url=guild.icon.url if guild.icon else discord.Embed.Empty)
        return embed
    @staticmethod
    def add_team_branding(embed: discord.Embed, guild: discord.Guild, team_data: dict, team_name: str) -> discord.Embed:
        embed.set_author(name=f"🏟️ {guild.name} • {team_name}", icon_url=guild.icon.url if guild.icon else discord.Embed.Empty)
        emoji_url = team_data.get("Image") or get_emoji_url(team_data.get("emoji"))
        if emoji_url: embed.set_thumbnail(url=emoji_url)
        return embed
    @staticmethod
    def error(title, description, color=None): return PremiumEmbedBuilder.create_base_embed(title, description, color or PremiumEmbedBuilder.COLORS['error'])
    @staticmethod
    def success(title, description, color=None): return PremiumEmbedBuilder.create_base_embed(title, description, color or PremiumEmbedBuilder.COLORS['success'])
    @staticmethod
    def warning(title, description, color=None): return PremiumEmbedBuilder.create_base_embed(title, description, color or PremiumEmbedBuilder.COLORS['warning'])
    @staticmethod
    def info(title, description, color=None): return PremiumEmbedBuilder.create_base_embed(title, description, color or PremiumEmbedBuilder.COLORS['info'])

# Mock get_emoji_url if it's not available from signing cog
def get_emoji_url(emoji_str: Optional[str]) -> Optional[str]:
    if not emoji_str: return None
    if emoji_str.startswith(("<:", "<a:")):
        match = re.match(r"<a?:[a-zA-Z0-9_]+:(\d+)>", emoji_str)
        if match:
            emoji_id = match.group(1)
            extension = "gif" if emoji_str.startswith("<a:") else "png"
            return f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}?size=128"
    return None

# Mock PremiumOfferView class if it's not properly imported or available.
# This mock needs to be replaced with the actual class from EnhancedSigningCommands.
class PremiumOfferView(discord.ui.View):
    def __init__(self, bot, offer_id: str, team_name: str, player: discord.Member, guild_config: dict):
        super().__init__(timeout=None) # Persistent view
        self.bot = bot
        self.offer_id = offer_id
        self.team_name = team_name
        self.player_id = player.id
        self.guild = player.guild
        self.guild_config = guild_config
        
        # Add placeholder buttons if the actual ones from EnhancedSigningCommands aren't accessible.
        # The actual view handles accept/decline/view logic.
        self.add_item(discord.ui.Button(label="Accept Offer", style=discord.ButtonStyle.success, emoji="✅", custom_id=f"contract_accept_{offer_id[:8]}", disabled=True))
        self.add_item(discord.ui.Button(label="Decline Offer", style=discord.ButtonStyle.danger, emoji="❌", custom_id=f"contract_decline_{offer_id[:8]}", disabled=True))
        self.add_item(discord.ui.Button(label="View Details", style=discord.ButtonStyle.secondary, emoji="📖", custom_id=f"contract_details_{offer_id[:8]}", disabled=True))
    # Actual callbacks would be needed for a functional view.


# --- Views and Modals for LFT/LFP Interaction ---

# --- View for /lft message ---
class FreeAgentView(discord.ui.View):
    """ View attached to the /lft message, containing the offer button. """
    def __init__(self, free_agent_user: discord.User, lft_details: str, lft_looking_for: str, 
                 guild_config: dict, bot, lft_guild: discord.Guild):
        super().__init__(timeout=None) # Persistent view
        self.fa_user = free_agent_user
        self.lft_details = lft_details
        self.lft_looking_for = lft_looking_for
        self.guild_config = guild_config
        self.bot = bot
        self.lft_guild = lft_guild # Store guild context
        self.add_item(OfferButton(self))

class OfferButton(discord.ui.Button):
    """ Button to initiate the offer process from an /lft post. """
    def __init__(self, parent_view: FreeAgentView):
        super().__init__(label="🚀 Make Offer", style=discord.ButtonStyle.primary, emoji="💸", custom_id="make_offer_from_lft")
        self.parent_view = parent_view # Reference to the FreeAgentView

    async def callback(self, interaction: discord.Interaction):
        # --- Delegate logic to the FreeAgencyManagerCog instance ---
        fa_manager_cog = self.parent_view.bot.get_cog("FreeAgencyManagerCog")
        if not fa_manager_cog:
            await interaction.response.send_message(embed=EmbedBuilder.error("Cog Missing", "FreeAgencyManagerCog not loaded. Cannot process offer."), ephemeral=True)
            return
        
        # Call the method that handles checks and displays the modal.
        await fa_manager_cog._initiate_offer_from_lft(interaction)

# --- Modal for Offer Details ---
class InitiateOfferModal(discord.ui.Modal):
    """ Modal to collect offer details from a team manager initiated via /lft. """
    def __init__(self, free_agent_user: discord.User, guild_config: dict, bot, lft_context_interaction: discord.Interaction):
        super().__init__(title="Send Contract Offer")
        self.fa_user = free_agent_user
        self.guild_config = guild_config
        self.bot = bot
        self.lft_interaction = lft_context_interaction # Store the original interaction that opened this modal

        self.contract_details_input = discord.ui.TextInput(label="Contract Details", placeholder="e.g., Salary, Role, Duration", required=True, default="Standard terms.")
        self.expiration_input = discord.ui.TextInput(label="Expiration Time (e.g., 24h, 7d, 1w)", placeholder="e.g., 24h", required=True, default="24h")
        self.salary_input = discord.ui.TextInput(label="Salary (Millions, optional)", placeholder="e.g., 10.5", required=False, style=discord.TextStyle.short)

        self.add_item(self.contract_details_input)
        self.add_item(self.expiration_input)
        self.add_item(self.salary_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Acknowledge modal submit

        contract_details = self.contract_details_input.value
        expiration_time_str = self.expiration_input.value
        salary_str = self.salary_input.value
        salary = float(salary_str) if salary_str and salary_str.replace('.', '', 1).isdigit() else None

        # Get context from the interaction that *opened* this modal.
        offering_manager_interaction = self.lft_interaction
        offering_manager = offering_manager_interaction.user
        
        # Delegate the core offer creation logic to the FreeAgencyManagerCog itself.
        fa_manager_cog = self.bot.get_cog("FreeAgencyManagerCog")
        if not fa_manager_cog:
            await interaction.followup.send(embed=EmbedBuilder.error("Cog Missing", "FreeAgencyManagerCog not loaded. Cannot process offer."), ephemeral=True)
            return

        success = await fa_manager_cog._send_offer_from_lft( # Call the internal method
            interaction=interaction, # The modal submission interaction, used for followup messages
            free_agent_user=self.fa_user,
            offering_manager=offering_manager,
            contract_details=contract_details,
            expiration_time_str=expiration_time_str,
            salary=salary
        )

        if success:
            await interaction.followup.send(embed=EmbedBuilder.success("Offer Sent!", "The contract offer has been sent to the free agent."), ephemeral=True)
        else:
            await interaction.followup.send(embed=EmbedBuilder.error("Offer Failed", "Could not send the offer. Please check logs or try again."), ephemeral=True)

# --- New View and Button for /lfp posts ---
class TeamLookingForPlayersView(discord.ui.View):
    """ View attached to the /lfp message, containing the 'Apply to Team' button. """
    def __init__(self, team_name: str, team_manager_user_ids: List[int], lfp_details: str, 
                 lfp_player_needs: str, guild_config: dict, bot, lfp_guild: discord.Guild):
        super().__init__(timeout=None) # Persistent view
        self.team_name = team_name
        self.team_manager_user_ids = team_manager_user_ids # Store manager IDs for notification
        self.lfp_details = lft_details
        self.lfp_player_needs = lfp_player_needs
        self.guild_config = guild_config
        self.bot = bot
        self.lfp_guild = lfp_guild # Store guild context for branding etc.
        self.add_item(ApplyButton(self))

class ApplyButton(discord.ui.Button):
    """ Button to initiate the application process from a team's /lfp post. """
    def __init__(self, parent_view: TeamLookingForPlayersView):
        super().__init__(label="🌟 Apply to Team", style=discord.ButtonStyle.primary, emoji="✍️", custom_id="apply_to_team_from_lfp")
        self.parent_view = parent_view # Reference to the TeamLookingForPlayersView

    async def callback(self, interaction: discord.Interaction):
        fa_manager_cog = self.parent_view.bot.get_cog("FreeAgencyManagerCog")
        if not fa_manager_cog:
            await interaction.response.send_message(embed=EmbedBuilder.error("Cog Missing", "FreeAgencyManagerCog not loaded. Cannot process application."), ephemeral=True)
            return

        # --- Perform validity checks on the player applying ---
        applying_player = interaction.user
        try:
            # Check if player is already signed or on the team posting
            player_team_name = await detect_team(applying_player) # Assumes detect_team is available
            if player_team_name and player_team_name == self.parent_view.team_name:
                await interaction.response.send_message(embed=EmbedBuilder.warning("Already on Team", f"You are already part of **{self.parent_view.team_name}**."), ephemeral=True)
                return
            if player_team_name and player_team_name != self.parent_view.team_name:
                await interaction.response.send_message(embed=EmbedBuilder.warning("Already Signed Elsewhere", f"You are currently signed to **{player_team_name}**."), ephemeral=True)
                return

            # Check player suspension status
            is_suspended, suspension_reason = self._is_player_suspended(interaction.guild.id, applying_player.id)
            if is_suspended:
                error_embed = EmbedBuilder.error(
                    "Player is Suspended", f"{applying_player.mention} cannot apply due to an active suspension.",
                    color=EmbedBuilder.COLORS['error']
                )
                error_embed.add_field(name="Reason", value=suspension_reason, inline=False)
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
                return

        except Exception as e:
            logging.error(f"Error checking player status for application: {e}", exc_info=True)
            await interaction.response.send_message(embed=EmbedBuilder.error("Error checking player status", "An issue occurred. Please try again."), ephemeral=True)
            return

        # --- Open the modal to collect player application details ---
        modal = PlayerApplyModal(
            team_name=self.parent_view.team_name,
            team_manager_ids=self.parent_view.team_manager_user_ids,
            lfp_details=self.parent_view.lft_details,
            lfp_player_needs=self.parent_view.lfp_player_needs,
            applying_player=applying_player,
            bot=self.parent_view.bot
        )
        await interaction.response.send_modal(modal)

    def _is_player_suspended(self, guild_id: int, player_id: int) -> Tuple[bool, str]:
        """Helper to check player's suspension status."""
        # Delegate to the method in FreeAgencyManagerCog or EnhancedSigningCommands if it exists there.
        fa_manager_cog = self.parent_view.bot.get_cog("FreeAgencyManagerCog")
        if fa_manager_cog:
            return fa_manager_cog._is_player_suspended(guild_id, player_id)
        else:
            logging.error("FreeAgencyManagerCog not found for suspension check in ApplyButton.")
            return False, "Cannot check suspension status." # Fallback

# --- Modal for Player Application Details ---
class PlayerApplyModal(discord.ui.Modal):
    """ Modal to collect application details from a player responding to an /lfp post. """
    def __init__(self, team_name: str, team_manager_ids: List[int], lfp_details: str, 
                 lfp_player_needs: str, applying_player: discord.User, bot):
        super().__init__(title=f"Apply to {team_name}")
        self.team_name = team_name
        self.team_manager_ids = team_manager_ids
        self.lfp_details = lft_details
        self.lfp_player_needs = lfp_player_needs
        self.applying_player = applying_player
        self.bot = bot

        self.player_role_input = discord.ui.TextInput(label="Your Primary Role/Position", placeholder="e.g., QB, OL, Playmaker", required=True)
        self.player_experience_input = discord.ui.TextInput(label="Your Experience/Skillset", placeholder="e.g., 'Great pocket presence', 'Fast receiver'", required=False, style=discord.TextStyle.long)
        self.player_availability_input = discord.ui.TextInput(label="Your Availability", placeholder="e.g., 'Weekends', 'Evenings GMT'", required=False)

        self.add_item(self.player_role_input)
        self.add_item(self.player_experience_input)
        self.add_item(self.player_availability_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Acknowledge modal submit

        player_role = self.player_role_input.value
        player_experience = self.player_experience_input.value or "N/A"
        player_availability = self.player_availability_input.value or "N/A"
        
        app_details = f"Seeking Role: {player_role}\nExperience/Skills: {player_experience}\nAvailability: {player_availability}"

        # --- Core Application Logic ---
        # This should be handled by a dedicated method in FreeAgencyManagerCog.
        fa_manager_cog = self.bot.get_cog("FreeAgencyManagerCog")
        if not fa_manager_cog:
            await interaction.followup.send(embed=EmbedBuilder.error("Cog Missing", "FreeAgencyManagerCog not loaded. Cannot process application."), ephemeral=True)
            return

        success = await fa_manager_cog._process_player_application(
            interaction=interaction, # The modal submission interaction
            team_name=self.team_name,
            team_manager_ids=self.team_manager_ids,
            applying_player=self.applying_player,
            application_details=app_details
        )

        if success:
            await interaction.followup.send(embed=EmbedBuilder.success("Application Sent!", f"Your application to **{self.team_name}** has been sent."), ephemeral=True)
        else:
            await interaction.followup.send(embed=EmbedBuilder.error("Application Failed", "Could not send your application. Please check logs or try again."), ephemeral=True)

# --- New Cog Definition ---
logger = logging.getLogger("bot.freeagency")

class FreeAgencyManagerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Ensure dependencies are checked on load or initialization.
        self.signing_cog = self._get_signing_cog()
        if not self.signing_cog:
            logger.error("FreeAgencyManagerCog initialized but EnhancedSigningCommands cog is missing. Functionality will be limited.")

    # --- Dependency Accessors ---
    def _get_signing_cog(self):
        """Safely retrieves the EnhancedSigningCommands cog."""
        signing_cog = self.bot.get_cog("EnhancedSigningCommands")
        if not signing_cog:
            logger.error("EnhancedSigningCommands cog not found. FreeAgencyManagerCog cannot function correctly.")
        return signing_cog

    # --- Delegate critical methods to EnhancedSigningCommands ---
    # These ensure logic is centralized and consistent.

    async def _can_manage_team_signings(self, interaction: discord.Interaction, guild_config: dict) -> bool:
        signing_cog = self._get_signing_cog()
        if not signing_cog: return interaction.user.guild_permissions.administrator # Fallback
        return await signing_cog._can_manage_team_signings(interaction, guild_config)

    def _get_team_stats(self, guild: discord.Guild, team_name: str, guild_config: dict) -> TeamStats:
        signing_cog = self._get_signing_cog()
        if not signing_cog:
            logger.warning("EnhancedSigningCommands cog not found for team stats.")
            return TeamStats(current_size=0, roster_cap=DEFAULT_ROSTER_CAP)
        return signing_cog._get_team_stats(guild, team_name, guild_config)

    async def _log_transaction(self, guild: discord.Guild, transaction_type: TransactionType,
                             player: Optional[discord.Member], team_name: str,
                             action_by: Optional[discord.Member] = None, details: str = None,
                             roster_info: Optional[TeamStats] = None) -> None:
        signing_cog = self._get_signing_cog()
        if not signing_cog:
            logger.warning("EnhancedSigningCommands cog not found for logging.")
            return
        await signing_cog._log_transaction(guild, transaction_type, player, team_name, action_by, details, roster_info)

    async def load_offers(self) -> Dict:
        signing_cog = self._get_signing_cog()
        if not signing_cog: return {}
        return await signing_cog.load_offers()

    async def save_offers(self, offers: Dict):
        signing_cog = self._get_signing_cog()
        if not signing_cog: return
        await signing_cog.save_offers(offers)

    async def _update_team_salary(self, guild_id: int, team_name: str, salary_change: float) -> bool:
        signing_cog = self._get_signing_cog()
        if not signing_cog: return False
        return await signing_cog._update_team_salary(guild_id, team_name, salary_change)
    
    def _is_player_suspended(self, guild_id: int, player_id: int) -> Tuple[bool, str]:
        """Helper to check player's suspension status."""
        # Assumes suspension data is managed by EnhancedSigningCommands or accessible via utils.
        suspensions = load_json(SUSPENSIONS_FILE)
        guild_id_str = str(guild_id)
        guild_suspensions = suspensions.get(guild_id_str, {})
        for susp_data in guild_suspensions.values():
            if susp_data.get("player_id") == str(player_id) and susp_data.get("status") == "active":
                return True, susp_data.get("reason", "No reason provided.")
        return False, "No reason provided."
    
    def _get_user_max_role_level(self, user: discord.Member, guild_config: dict, hierarchy: Dict[str, int]) -> int:
        """Delegate role level check to EnhancedSigningCommands."""
        signing_cog = self._get_signing_cog()
        if not signing_cog: return 0 # Default to no special role
        return signing_cog._get_user_max_role_level(user, guild_config, hierarchy)

    # --- Offer Creation Logic (Delegated to EnhancedSigningCommands) ---
    async def _send_offer_from_lft(self, interaction: discord.Interaction, # Modal submission interaction
                                 free_agent_user: discord.User,
                                 offering_manager: discord.User,
                                 contract_details: str,
                                 expiration_time_str: str,
                                 salary: Optional[float]) -> bool:
        """
        Creates and sends an offer using the signing cog's offer functionality.
        This is called by the InitiateOfferModal's submit action.
        """
        signing_cog = self._get_signing_cog()
        if not signing_cog:
            await interaction.followup.send(embed=EmbedBuilder.error("Cog Missing", "EnhancedSigningCommands cog not loaded. Cannot process offer."), ephemeral=True)
            return False

        try:
            # Get the free agent as a member object
            fa_member = interaction.guild.get_member(free_agent_user.id)
            if not fa_member:
                await interaction.followup.send(embed=EmbedBuilder.error("Member Not Found", "Free agent is not a member of this server."), ephemeral=True)
                return False
            
            # Create a mock interaction for the signing cog's offer command
            # We'll use the offer command directly but bypass the decorator checks
            guild_config = get_server_config(interaction.guild.id)
            
            # Call the signing cog's internal offer creation logic
            await signing_cog.offer.callback(
                signing_cog,
                interaction,
                fa_member,
                contract_details,
                expiration_time_str,
                salary
            )
            return True
        except Exception as e:
            logger.error(f"Error sending offer from LFT: {e}", exc_info=True)
            await interaction.followup.send(embed=EmbedBuilder.error("Offer Failed", "An error occurred while sending the offer."), ephemeral=True)
            return False
    
    # --- Method to process player applications (for /lfp) ---
    async def _process_player_application(self, interaction: discord.Interaction, 
                                        team_name: str, team_manager_ids: List[int],
                                        applying_player: discord.User, application_details: str) -> bool:
        """
        Handles the submission of a player's application from the /lfp post.
        It will typically DM the team manager(s).
        """
        if not team_manager_ids:
            logger.warning(f"No managers found for team '{team_name}' to send application to in guild {interaction.guild.id}.")
            # Optionally post in a general bot log or return False.
            # We will proceed but note that managers won't be notified.
            # For user feedback, it's better to let them know if no notification occurred.

        app_embed = EmbedBuilder.create_base_embed(
            title="🌟 Player Application Received",
            description=f"**{applying_player.display_name}** has applied to **{team_name}**!",
            color=EmbedBuilder.COLORS['gold']
        )
        app_embed.set_author(name=f"{applying_player.display_name}", icon_url=applying_player.display_avatar.url)
        app_embed.add_field(name="Application Details", value=f"```\n{application_details}\n```", inline=False)
        app_embed.add_field(name="Player Mention", value=f"{applying_player.mention}", inline=True)
        app_embed.add_field(name="Player ID", value=f"`{applying_player.id}`", inline=True)
        
        success_count = 0
        failed_notifications = []
        guild = interaction.guild
        guild_config = get_server_config(guild.id) # Get config for branding
        team_specific_data = guild_config.get("team_data", {}).get(team_name, {})

        if not team_manager_ids:
            # If no managers were found, inform the player that the application could not be sent.
            await interaction.followup.send(embed=EmbedBuilder.warning("Application Sent (No Managers Found)", "Your application details have been recorded, but no team managers were found to notify directly. Please reach out to your team leadership through other means."), ephemeral=True)
            # Log this as an informational event rather than failure.
            await _log_transaction(
                self.bot, guild, TransactionType.OFFER, # Using OFFER type as a general "recruitment/application" log
                applying_player, team_name,
                action_by=applying_player,
                details=f"Application submitted: '{application_details}'. No managers found to notify.",
                roster_info=None
            )
            return True # Processed, but with a note

        for manager_id in team_manager_ids:
            manager = guild.get_member(manager_id)
            if manager:
                try:
                    application_embed_with_branding = PremiumEmbedBuilder.add_team_branding(app_embed, guild, team_specific_data, team_name)
                    await manager.send(embed=application_embed_with_branding)
                    success_count += 1
                except discord.Forbidden:
                    failed_notifications.append(f"{manager.mention} (DMs disabled)")
                    logger.warning(f"Could not DM manager {manager.id} about application from {applying_player.id} for team {team_name}.")
                except Exception as e:
                    failed_notifications.append(f"{manager.mention} (Error: {e})")
                    logger.error(f"Failed to DM manager {manager.id} for application: {e}", exc_info=True)
            else:
                failed_notifications.append(f"Manager ID `{manager_id}` (User not found)")

        # Log the application process
        log_details = f"Application submitted: '{application_details}'. Notified {success_count} manager(s)."
        if failed_notifications:
            log_details += f" Failed notifications for: {', '.join(failed_notifications)}."
            logger.warning(f"Failed to notify {len(failed_notifications)} manager(s) for application from {applying_player.id} to team {team_name}.")
        
        await _log_transaction(
            self.bot, guild, TransactionType.OFFER, # Using OFFER type for recruitment/application logs
            applying_player, team_name,
            action_by=applying_player,
            details=log_details,
            roster_info=None
        )

        return True # Indicate that the application process was initiated


    # --- `/lft` Command (Modified slightly for guild context) ---
    @app_commands.command(name="lft", description="Announce you are looking for a team")
    @app_commands.describe(
        looking_for="What kind of role or team you're looking for (e.g., 'starting QB', 'backup winger', 'any team')",
        details="Any additional details about yourself or what you seek (e.g., 'great comms', 'active player')"
    )
    async def lft(self, interaction: discord.Interaction, looking_for: str = "Any team", details: str = "Ready to play!"):
        await interaction.response.defer(ephemeral=True) # Respond privately first

        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            return await interaction.followup.send(embed=EmbedBuilder.error("Configuration Error", "Server configuration not found. Please ensure bot setup is complete."), ephemeral=True)

        fa_user = interaction.user
        
        # --- Pre-checks ---
        current_team = await detect_team(fa_user) # Assumes detect_team is available
        if current_team:
            return await interaction.followup.send(embed=EmbedBuilder.warning("Already on a Team", f"You are currently on **{current_team}**. Please use `/demand` to become a free agent first."), ephemeral=True)

        # Check if user has free agent role
        permission_settings = guild_config.get("permission_settings", {})
        free_agent_role_ids = permission_settings.get("free_agent_roles", [])
        has_free_agent_role = any(role.id in free_agent_role_ids for role in fa_user.roles)
        
        if not has_free_agent_role:
            return await interaction.followup.send(embed=EmbedBuilder.error("Not a Free Agent", "You must have the free agent role to use this command. Contact staff if you believe this is an error."), ephemeral=True)

        is_suspended, suspension_reason = self._is_player_suspended(interaction.guild.id, fa_user.id)
        if is_suspended:
            error_embed = EmbedBuilder.error(
                "Player is Suspended", f"{fa_user.mention} cannot post 'Looking For Team' due to an active suspension.",
                color=EmbedBuilder.COLORS['error']
            )
            error_embed.add_field(name="Reason", value=suspension_reason, inline=False)
            return await interaction.followup.send(embed=error_embed, ephemeral=True)

        # Get free agency channel
        announcement_channels = guild_config.get("announcement_channels", {})
        free_agency_channel_id = announcement_channels.get("free_agency")
        if not free_agency_channel_id:
            return await interaction.followup.send(embed=EmbedBuilder.error("Channel Not Configured", "Free agency channel is not configured. Please contact an administrator."), ephemeral=True)
        
        free_agency_channel = interaction.guild.get_channel(free_agency_channel_id)
        if not free_agency_channel:
            return await interaction.followup.send(embed=EmbedBuilder.error("Channel Not Found", "Free agency channel could not be found. Please contact an administrator."), ephemeral=True)

        # --- Create the LFT Embed ---
        fa_embed = EmbedBuilder.create_base_embed(
            title="💨 Free Agent Looking For Team",
            description=f"{fa_user.mention} is actively looking for a team!",
            color=EmbedBuilder.COLORS['gold']
        )
        fa_embed.set_author(name=f"{fa_user.display_name}", icon_url=fa_user.display_avatar.url)
        fa_embed.add_field(name="Seeking", value=looking_for, inline=False)
        if details and details != "Ready to play!":
            fa_embed.add_field(name="Details", value=details, inline=False)
        fa_embed.add_field(name="Status", value="✅ Currently Free Agent", inline=True)
        fa_embed.set_footer(text=f"Posted by {fa_user.display_name} | Use the button to make an offer.", icon_url=fa_user.display_avatar.url)

        # --- Create the View with the Offer Button ---
        view = FreeAgentView(fa_user, details, looking_for, guild_config, self.bot, interaction.guild)
        
        # Post to free agency channel
        try:
            await free_agency_channel.send(embed=fa_embed, view=view)
            await interaction.followup.send(embed=EmbedBuilder.success("LFT Posted", f"Your LFT post has been sent to {free_agency_channel.mention}."), ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send(embed=EmbedBuilder.error("Permission Error", f"Bot lacks permission to send messages in {free_agency_channel.mention}."), ephemeral=True)

        # --- Log the LFT post ---
        await self._log_transaction(
            interaction.guild, TransactionType.OFFER, fa_user, None, # Player is FA, no team yet
            action_by=fa_user,
            details=f"Looking for: '{looking_for}'. Details: '{details}'. Post made by {fa_user.display_name}.",
            roster_info=None
        )
    
    # --- `/lfp` Command ---
    @app_commands.command(name="lfp", description="Announce your team is looking for players")
    @app_commands.describe(
        player_needs="What player positions/roles your team needs (e.g., '1 QB', '2 OL', 'Any active player')",
        details="Any additional details about the team or what you're looking for (e.g., 'must have mic', 'competitive league')"
    )
    async def lfp(self, interaction: discord.Interaction, player_needs: str = "Any players", details: str = "Join our competitive league!"):
        await interaction.response.defer(ephemeral=True) # Respond privately first

        guild_config = get_server_config(interaction.guild.id)
        if not guild_config:
            return await interaction.followup.send(embed=EmbedBuilder.error("Configuration Error", "Server configuration not found. Please ensure bot setup is complete."), ephemeral=True)

        # Check if user has coaching permissions
        permission_settings = guild_config.get("permission_settings", {})
        coach_role_ids = (permission_settings.get("gm_roles", []) + 
                         permission_settings.get("fo_roles", []) + 
                         permission_settings.get("hc_roles", []) + 
                         permission_settings.get("ac_roles", []) +
                         permission_settings.get("manage_teams_roles", []))
        
        has_coach_role = any(role.id in coach_role_ids for role in interaction.user.roles)
        
        if not has_coach_role and not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send(embed=EmbedBuilder.error("Permission Denied", "You must have a coaching role to use this command."), ephemeral=True)

        # Infer team name from the user posting the command
        team_name = await detect_team(interaction.user)
        if not team_name:
            return await interaction.followup.send(embed=EmbedBuilder.error("Team Error", "You are not associated with a configured team. Please use setup commands to define your team or ensure your role is correctly assigned."), ephemeral=True)

        # Get free agency channel
        announcement_channels = guild_config.get("announcement_channels", {})
        free_agency_channel_id = announcement_channels.get("free_agency")
        if not free_agency_channel_id:
            return await interaction.followup.send(embed=EmbedBuilder.error("Channel Not Configured", "Free agency channel is not configured. Please contact an administrator."), ephemeral=True)
        
        free_agency_channel = interaction.guild.get_channel(free_agency_channel_id)
        if not free_agency_channel:
            return await interaction.followup.send(embed=EmbedBuilder.error("Channel Not Found", "Free agency channel could not be found. Please contact an administrator."), ephemeral=True)

        # Get manager role IDs and then manager user IDs from config
        team_data = guild_config.get("team_data", {}).get(team_name, {})
        manager_role_ids_from_team_data = team_data.get("manager_roles", []) # If team-specific manager roles are configured in team_data
        manager_role_ids_from_permissions = guild_config.get("permission_settings", {}).get("gm_roles", []) + \
                                             guild_config.get("permission_settings", {}).get("fo_roles", []) + \
                                             guild_config.get("permission_settings", {}).get("hc_roles", []) + \
                                             guild_config.get("permission_settings", {}).get("manage_teams_roles", [])
        
        all_manager_role_ids = list(set(manager_role_ids_from_team_data + manager_role_ids_from_permissions))

        # Find actual manager user IDs from these role IDs
        team_manager_user_ids = []
        if all_manager_role_ids:
            for role_id in all_manager_role_ids:
                role = interaction.guild.get_role(int(role_id))
                if role:
                    # Add members who have this role
                    for member in role.members:
                        team_manager_user_ids.append(member.id)
        team_manager_user_ids = list(set(team_manager_user_ids)) # Ensure unique IDs

        if not team_manager_user_ids:
            logger.warning(f"No managers found for team '{team_name}' in guild {interaction.guild.id} to notify for LFP post.")
            # It's okay if no managers are found; the post can still be made.

        # --- Create the LFP Embed ---
        lfp_embed = EmbedBuilder.create_base_embed(
            title=f"📣 {team_name} is Looking For Players!",
            description=f"**{team_name}** is actively recruiting new talent!",
            color=EmbedBuilder.COLORS['gold']
        )
        # Add team branding
        team_specific_data = guild_config.get("team_data", {}).get(team_name, {})
        lfp_embed = PremiumEmbedBuilder.add_team_branding(lfp_embed, interaction.guild, team_specific_data, team_name)

        lfp_embed.add_field(name="Player Needs", value=player_needs, inline=False)
        if details and details != "Join our competitive league!":
            lfp_embed.add_field(name="Team Details/Requirements", value=details, inline=False)
        
        # Add manager contact info if available
        if team_manager_user_ids:
            manager_mentions = ", ".join([f"<@{uid}>" for uid in team_manager_user_ids[:5]]) # Limit mentions
            lfp_embed.add_field(name="Team Managers", value=f"Contact: {manager_mentions}" + ("..." if len(team_manager_user_ids) > 5 else ""), inline=False)
        else:
            lfp_embed.add_field(name="Team Managers", value="No specific manager roles configured or found. DM your team leadership!", inline=False)

        lfp_embed.set_footer(text=f"Post by {interaction.user.display_name} | Players: Use the button to apply!", icon_url=interaction.user.display_avatar.url)

        # --- Create the View with the Apply Button ---
        view = TeamLookingForPlayersView(
            team_name=team_name,
            team_manager_user_ids=team_manager_user_ids, # Pass manager IDs for notification
            lfp_details=details,
            lfp_player_needs=player_needs,
            guild_config=guild_config,
            bot=self.bot,
            lfp_guild=interaction.guild # Pass guild context
        )
        
        # Post to free agency channel
        try:
            await free_agency_channel.send(embed=lfp_embed, view=view)
            await interaction.followup.send(embed=EmbedBuilder.success("LFP Posted", f"Your LFP post has been sent to {free_agency_channel.mention}."), ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send(embed=EmbedBuilder.error("Permission Error", f"Bot lacks permission to send messages in {free_agency_channel.mention}."), ephemeral=True)

        # --- Log this action ---
        await self._log_transaction(
            interaction.guild, TransactionType.OFFER, # Using OFFER type for recruitment log
            None, team_name, # Player is None for LFP, Team is the posting team
            action_by=interaction.user,
            details=f"Team '{team_name}' posted LFP: Needs='{player_needs}', Details='{details}'. Managers notified: {len(team_manager_user_ids)}.",
            roster_info=None
        )
    
    async def _initiate_offer_from_lft(self, interaction: discord.Interaction):
        """Handle the offer button click from LFT posts"""
        # Get the free agent from the view context
        fa_user = self._get_fa_user_from_view_context(interaction)
        if not fa_user:
            await interaction.response.send_message(embed=EmbedBuilder.error("Error", "Could not find the free agent user from this post."), ephemeral=True)
            return
        
        guild_config = get_server_config(interaction.guild.id)
        
        # Check if the user making the offer can manage team signings
        if not await self._can_manage_team_signings(interaction, guild_config):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "You don't have permission to make offers."), ephemeral=True)
            return
        
        # Check if user is on a team
        offering_team = await detect_team(interaction.user)
        if not offering_team:
            await interaction.response.send_message(embed=EmbedBuilder.error("Team Error", "You are not associated with a team."), ephemeral=True)
            return
        
        # Open the offer modal
        modal = InitiateOfferModal(fa_user, guild_config, self.bot, interaction)
        await interaction.response.send_modal(modal)

    # --- Helper method to retrieve FA User from View Context (Crucial for Button Callback) ---
    def _get_fa_user_from_view_context(self, interaction: discord.Interaction) -> Optional[discord.User]:
        """
        Retrieves the free agent's user object from the context,
        assuming the FreeAgentView stores it correctly. This is needed by the modal.
        """
        if hasattr(interaction, 'message') and interaction.message:
            for view in interaction.message.views:
                if isinstance(view, FreeAgentView):
                    return view.fa_user # Access the FA user stored in the view
        logging.error("Could not retrieve FreeAgentView or FA User from interaction context.")
        return None # Cannot retrieve FA user
    
    # --- Helper for ApplyButton to get suspension status ---
    # It's better if this method is also delegated to EnhancedSigningCommands if it manages suspensions,
    # otherwise, it can live here if FreeAgencyManagerCog manages suspension data directly.
    def _is_player_suspended(self, guild_id: int, player_id: int) -> Tuple[bool, str]:
        """Helper to check player's suspension status."""
        # Assumes suspension data is managed by EnhancedSigningCommands or accessible via utils.
        suspensions = load_json(SUSPENSIONS_FILE) # Assumes load_json is available
        guild_id_str = str(guild_id)
        guild_suspensions = suspensions.get(guild_id_str, {})
        for susp_data in guild_suspensions.values():
            if susp_data.get("player_id") == str(player_id) and susp_data.get("status") == "active":
                return True, susp_data.get("reason", "No reason provided.")
        return False, "No reason provided."


# --- Cog Setup Function ---
async def setup(bot):
    """Adds the FreeAgencyManagerCog to the bot."""
    # Ensure EnhancedSigningCommands is loaded FIRST. This cog heavily relies on it.
    if not bot.get_cog("EnhancedSigningCommands"):
        logger.error("--- CRITICAL DEPENDENCY MISSING ---")
        logger.error("EnhancedSigningCommands cog is NOT loaded.")
        logger.error("FreeAgencyManagerCog requires EnhancedSigningCommands to function.")
        logger.error("Please ensure EnhancedSigningCommands is loaded BEFORE FreeAgencyManagerCog.")
        # Consider raising an error or preventing cog load if this dependency is essential.
    else:
        logger.info("EnhancedSigningCommands cog found. Proceeding to load FreeAgencyManagerCog.")
    
    await bot.add_cog(FreeAgencyManagerCog(bot))
    logger.info("FreeAgencyManagerCog loaded successfully.")