import discord
from discord.ext import commands
from discord import app_commands
# Explicitly import necessary UI components for clarity and to resolve the SelectOption error
# Note: SelectOption is not directly imported from discord.ui in newer versions.
from discord.ui import (
    Select, Modal, TextInput, Button, ChannelSelect, RoleSelect, View
)
import asyncio
import logging
import random
import time
from datetime import datetime
from typing import List, Dict, Optional, Union, Tuple # Added Tuple
import json

# Assuming these utils are in a 'utils' directory relative to this cog
# If not, adjust the import paths accordingly
from utils.config import (
    get_server_config,
    update_server_config, # Not directly used in this cog, but good to have if utils uses it internally
    save_guild_config,
    get_default_config
)
from utils.permissions import is_admin
from utils.logging import log_action
from utils.embeds import EmbedBuilder # Assuming EmbedBuilder is defined elsewhere
from utils.team_detection import (
    detect_team_roles,
    generate_team_name_from_role,
    find_team_emoji
)

logger = logging.getLogger("bot.setup")

DEFAULT_ROSTER_CAP = 53
OWNER_USER_ID = 1099798391535439913 # Hardcoded User ID for /update command

# --- Autocomplete Functions ---
async def addteam_role_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    if not interaction.guild:
        return []
    # Ensure guild is available and bot has permissions to view roles
    # A simple check might be to see if the bot can see its own roles or guild roles.
    # Guild insights permission isn't strictly necessary for role listing in many cases.

    guild_roles = sorted(
        interaction.guild.roles, key=lambda r: r.position, reverse=True
    )
    # Filter out @everyone and match current input, limit to 24 choices
    filtered_roles = [
        r for r in guild_roles
        if r.name != "@everyone" and
        (current.lower() in r.name.lower() if current else True)
    ]
    role_matches = [
        app_commands.Choice(name=r.name, value=str(r.id))
        for r in filtered_roles[:24]
    ]
    # Add "Create New Role" option at the beginning
    return [app_commands.Choice(name="✨ Create New Role", value="new")] + role_matches

async def log_type_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    default_conf = get_default_config()
    log_channel_keys = list(default_conf.get("log_channels", {}).keys())
    ann_channel_keys = list(default_conf.get("announcement_channels", {}).keys())
    # Consolidate all configurable channel types
    all_configurable_types = sorted(
        list(set(log_channel_keys + ann_channel_keys + ["reminders_channel_id"]))
    )
    choices = []
    for key_val in all_configurable_types:
        # Create a user-friendly display name
        display_name = key_val.replace("_channel_id", "") \
                              .replace("_channel", "") \
                              .replace("_", " ").title()
        # Check against both the display name and the raw key value
        if current.lower() in display_name.lower() or \
           current.lower() in key_val.lower():
            choices.append(app_commands.Choice(name=display_name, value=key_val))
    return choices[:25] # Discord limit

async def role_type_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    default_perms = get_default_config().get("permission_settings", {})
    choices = []
    for key_val in default_perms.keys():
        simple_key = key_val.replace("_roles", "") # e.g., admin_roles -> admin
        # e.g., manage_teams -> Manage Teams
        display_name = simple_key.replace("_", " ").title()
        if current.lower() in display_name.lower() or \
           current.lower() in simple_key.lower():
            choices.append(app_commands.Choice(name=display_name, value=simple_key))
    return sorted(choices, key=lambda c: c.name)[:25] # Sort alphabetically & limit

async def team_autocomplete(
    interaction: discord.Interaction, current: str
) -> List[app_commands.Choice[str]]:
    if not interaction.guild_id:
        logger.warning("team_autocomplete called without guild_id in interaction.")
        return []
    config = get_server_config(interaction.guild_id)
    team_data_new = config.get("team_data", {}) # New structure
    team_roles_legacy = config.get("team_roles", {}) # Legacy structure
    # Combine keys from both, ensuring uniqueness and sorting
    all_teams = sorted(list(team_data_new.keys()) + list(team_roles_legacy.keys()))
    choices = [
        app_commands.Choice(name=team, value=team)
        for team in all_teams if current.lower() in team.lower() or not current
    ]
    # Add an option for global roster cap configuration
    if not current or "all" in current.lower(): # Allow "all" or empty for this option
        choices.insert(
            0, app_commands.Choice(name="All Teams (Global Default)",
                                   value="all_teams_global_cap")
        )
    return choices[:25] # Discord limit


# --- Setup Commands Cog ---
class SetupCommands(commands.Cog):
    """Cog for handling server setup and configuration commands."""
    def __init__(self, bot):
        self.bot = bot
        # Stores active interactive setup sessions for users
        # Format: {user_id: {"config": dict, "timestamp": float, "current_page": int, "interaction_proxy": discord.Interaction, "setup_pages": list, "total_pages": int, "key_mapping": dict}}
        self.active_setup_sessions: Dict[int, Dict] = {}

    # --- Helper methods for /setup command ---

    def cleanup_sessions(self):
        """Removes expired setup sessions from active_setup_sessions."""
        current_time = time.time()
        # Sessions expire after 30 minutes (1800 seconds)
        expired_user_ids = [
            user_id for user_id, session in self.active_setup_sessions.items()
            if current_time - session.get("timestamp", 0) > 1800
        ]
        for user_id in expired_user_ids:
            self.active_setup_sessions.pop(user_id, None)
            logger.info(f"Cleaned up expired setup session for user {user_id}")

    async def send_setup_page(self, interaction: discord.Interaction, page_index: int):
        """Sends a specific page of the interactive setup UI."""
        if interaction.user.id not in self.active_setup_sessions:
            # If the session is no longer active, edit the original response or send a new one.
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=EmbedBuilder.error("⚠️ Session Expired", "Your setup session has expired or was closed. Please run `/setup` again."), view=None)
            else: # Fallback if the interaction hasn't been responded to yet (unlikely if called from /setup)
                await interaction.response.send_message(embed=EmbedBuilder.error("⚠️ Session Expired", "Your setup session has expired. Run `/setup` again."), ephemeral=True)
            return

        session = self.active_setup_sessions[interaction.user.id]
        session["current_page"] = page_index # Update current page in session
        setup_pages_list = session["setup_pages"]

        # Validate page index
        if not 0 <= page_index < len(setup_pages_list):
            logger.warning(f"Invalid page index {page_index} requested for setup session by user {interaction.user.id} in guild {interaction.guild.id}")
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=EmbedBuilder.error("❌ Invalid Page", "The requested setup page does not exist."), view=None)
            else:
                 await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Page", "The requested setup page does not exist."), ephemeral=True)
            return

        page_data_dict = setup_pages_list[page_index]
        embed = discord.Embed(title=f"{page_data_dict.get('icon','❓')} {page_data_dict.get('title','Setup Page')}",
                              description=page_data_dict.get("description",""),
                              color=page_data_dict.get("color", discord.Color.blue().value)) # Use default color if missing

        guild_config_live = session["config"] # Live config from the session
        key_mapping_dict = session.get("key_mapping", {})

        # Populate embed fields with current settings
        for field_item in page_data_dict.get("fields", []):
            field_key_page = field_item["key"]
            current_display_value = "`Not set`" # Default display if no value found

            if field_item["type"] == "role":
                # Key for permission_settings, e.g., "admin_roles"
                role_list_key_in_perms = f"{field_key_page.replace('_role', '').strip()}_roles"
                permission_settings_dict = guild_config_live.get("permission_settings", {})
                role_ids_list = permission_settings_dict.get(role_list_key_in_perms, [])
                if role_ids_list:
                    # Get mentions for roles that exist in the guild
                    roles_mentions_list = [interaction.guild.get_role(rid).mention for rid in role_ids_list if interaction.guild.get_role(rid)]
                    if roles_mentions_list: current_display_value = "\n".join([f"• {r}" for r in roles_mentions_list])

            elif field_item["type"] == "channel":
                actual_config_key = key_mapping_dict.get(field_key_page) # Map UI key to actual config key
                channel_id_val = None
                if actual_config_key:
                    if field_key_page == "reminders_channel": # Special handling for reminders_channel (notification_settings)
                        channel_id_val = guild_config_live.get("notification_settings", {}).get(actual_config_key)
                    elif field_key_page in ["announcements_channel", "free_agency_channel"]: # Announcement channels
                        channel_id_val = guild_config_live.get("announcement_channels", {}).get(actual_config_key)
                    else: # Log channels
                        channel_id_val = guild_config_live.get("log_channels", {}).get(actual_config_key)

                    if channel_id_val:
                        # Special handling for games_channel which can have multiple channels
                        if field_key_page == "games_channel" and isinstance(channel_id_val, list):
                            channel_mentions = []
                            for ch_id in channel_id_val:
                                channel_obj = interaction.guild.get_channel(ch_id)
                                if channel_obj:
                                    channel_mentions.append(channel_obj.mention)
                            if channel_mentions:
                                current_display_value = "\n".join([f"• {mention}" for mention in channel_mentions])
                        else:
                            # Single channel (handle both int and list with single item)
                            single_id = channel_id_val if isinstance(channel_id_val, int) else (channel_id_val[0] if channel_id_val else None)
                            if single_id:
                                channel_obj = interaction.guild.get_channel(single_id)
                                if channel_obj: current_display_value = channel_obj.mention

            elif field_item["type"] == "text": # For fields like global roster cap
                if field_key_page == "global_roster_cap":
                    current_display_value = f"`{str(guild_config_live.get('roster_cap', DEFAULT_ROSTER_CAP))}`"

            elif field_item["type"] == "team":  # For team-specific configurations like roster caps
                team_data_dict = guild_config_live.get("team_data", {})
                global_cap_val = guild_config_live.get("roster_cap", DEFAULT_ROSTER_CAP)
                display_parts = [f"**Global Default Cap:** `{global_cap_val}`\n\n**Team Specific Caps:**"]
                sorted_teams = sorted(list(team_data_dict.keys()))
                if sorted_teams:
                    for team_n in sorted_teams[:10]: # Show first 10 teams
                        team_info = team_data_dict[team_n]
                        team_specific_cap_val = team_info.get('roster_cap')
                        if team_specific_cap_val is None or team_specific_cap_val == global_cap_val:
                            cap_display = f"Uses Global (`{global_cap_val}`)"
                        else:
                            cap_display = f"`{team_specific_cap_val}`"
                        team_emoji = team_info.get('emoji','🔹')
                        display_parts.append(f"• {team_emoji} **{team_n}**: {cap_display}")
                    if len(sorted_teams) > 10: display_parts.append(f"... and {len(sorted_teams) - 10} more teams.")
                else:
                    display_parts.append("No teams configured for specific caps. Use `/addteam` first.")
                current_display_value = "\n".join(display_parts)
            else: # Fallback for unknown types
                current_display_value = str(guild_config_live.get(field_key_page, '`Not set`'))

            embed.add_field(name=field_item.get('name', 'Unnamed Field'),
                            value=f"{field_item.get('description','')}\n\n**Current:** {current_display_value}",
                            inline=field_item.get("inline", True))

        embed.set_footer(text=f"Page {page_index + 1}/{len(setup_pages_list)} • Session active for this user only.")
        # Create the view for this page, passing necessary context
        view = SetupPageView(self, page_data_dict, session, interaction.guild, interaction.user.id)

        # Respond to the interaction: edit original message if already responded, otherwise send a followup.
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else: # Should only happen on initial /setup call after defer
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)


    @app_commands.command(
        name="addteam",
        description="Add a new team to the league (creates role or uses existing)"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.autocomplete(role_id_or_new=addteam_role_autocomplete)
    async def addteam(
        self,
        interaction: discord.Interaction,
        team_name: str,
        role_id_or_new: str,
        emoji: str = "🏆"
    ):
        """
        Adds a new team, optionally creating a Discord role or using an existing one.
        """
        if not await is_admin(interaction.user):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "🚫 Permission Denied",
                    "Only server administrators can use this command."
                ),
                ephemeral=True
            )
            return

        # Ensure guild and user are available for the command context
        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        config = get_server_config(interaction.guild.id)
        team_data = config.setdefault("team_data", {})
        team_roles_legacy = config.setdefault("team_roles", {}) # For backward compatibility

        # Check if team name already exists in either configuration structure
        if team_name in team_data or team_name in team_roles_legacy:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "⚠️ Team Exists",
                    f"A team named **{team_name}** already exists in the configuration."
                ),
                ephemeral=True
            )
            return

        role_obj: Optional[discord.Role] = None
        try:
            if role_id_or_new.lower() == "new":
                # Check bot permissions for role management
                if not interaction.guild.me.guild_permissions.manage_roles:
                    raise ValueError(
                        "The bot lacks the 'Manage Roles' permission "
                        "to create a new role."
                    )
                # Check if a role with the same name already exists
                if discord.utils.get(interaction.guild.roles, name=team_name):
                     raise ValueError(f"A role named '{team_name}' already exists. Please choose a different name or assign an existing role.")

                # Create the new role
                role_obj = await interaction.guild.create_role(
                    name=team_name,
                    color=discord.Color.random(),
                    reason=(
                        f"Team role for {team_name} created by "
                        f"{interaction.user.display_name}"
                    )
                )
            else:
                # Process existing role selection
                role_id_int = int(role_id_or_new)
                role_obj = interaction.guild.get_role(role_id_int)

                if not role_obj:
                    raise ValueError(
                        "The selected role could not be found. "
                        "It might have been deleted or the ID is invalid."
                    )
                # Security checks: prevent assigning admin roles as team roles
                if role_obj.permissions.administrator:
                    raise ValueError(
                        "Cannot use a role with administrator permissions as a "
                        "team role for security reasons."
                    )
                # Hierarchy check: ensure the role is not above the user's highest role
                user_top_role_position = interaction.user.top_role.position if interaction.user.top_role else -1
                if interaction.user.id != interaction.guild.owner_id and \
                   role_obj.position >= user_top_role_position:
                    raise ValueError(
                        "You cannot assign a team role that is higher than or equal "
                        "to your own highest role (unless you are the server owner)."
                    )

            # If role creation/selection was successful, update configuration
            global_roster_cap = config.get("roster_cap", DEFAULT_ROSTER_CAP)
            # Store in the new team_data structure
            team_data[team_name] = {
                "role_id": role_obj.id,
                "emoji": emoji,
                "roster_cap": global_roster_cap, # Apply global cap initially
                "name": team_name
            }
            # Also update legacy structure for compatibility
            team_roles_legacy[team_name] = role_obj.id

            save_guild_config(interaction.guild.id, config) # Save the updated configuration
            log_message = (
                f"Team '{team_name}' added. Role: {role_obj.name if role_obj else 'N/A'}, "
                f"Emoji: {emoji}, Cap: Global ({global_roster_cap})"
            )
            await log_action(
                interaction.guild, "SETUP", interaction.user,
                log_message, "addteam_cmd"
            )

            # Send success message
            embed = EmbedBuilder.success(
                "🎉 Team Added Successfully!",
                f"Team **{team_name}** {emoji} has been added with role "
                f"{role_obj.mention if role_obj else '`Role not found/assigned`'}.\n"
                f"The global default roster cap of `{global_roster_cap}` has been applied."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except ValueError as ve: # Handle input validation errors
            await interaction.response.send_message(
                embed=EmbedBuilder.error("🚫 Invalid Input", str(ve)),
                ephemeral=True
            )
        except discord.Forbidden: # Handle permission errors
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "🔒 Permissions Error",
                    "The bot encountered a permissions issue while trying to "
                    "manage roles. Ensure it has the 'Manage Roles' permission "
                    "and that its role is high enough in the hierarchy."
                ),
                ephemeral=True
            )
        except discord.HTTPException as e: # Handle potential API errors
            logger.error(f"HTTP Exception in /addteam for guild {interaction.guild.id}: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=EmbedBuilder.error("❌ API Error", f"An API error occurred: {str(e)}"),
                ephemeral=True
            )
        except Exception as e: # Catch any other unexpected errors
            logger.error(
                f"Error in /addteam for guild {interaction.guild.id}: {e}",
                exc_info=True
            )
            await interaction.response.send_message(
                embed=EmbedBuilder.error("❌ Unexpected Error",
                                         f"An error occurred: {str(e)}"),
                ephemeral=True
            )

    @app_commands.command(
        name="configureteam",
        description="Configure an existing team's role, emoji, or roster cap"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.autocomplete(
        team_name=team_autocomplete,
        role_id_or_new=addteam_role_autocomplete # Reuse autocomplete for role selection
    )
    async def configureteam(
        self,
        interaction: discord.Interaction,
        team_name: str,
        role_id_or_new: Optional[str] = None, # Make optional
        emoji: Optional[str] = None,
        roster_cap: Optional[int] = None
    ):
        """
        Configures settings for an existing team, such as its role, emoji,
        or roster limit.
        """
        if not await is_admin(interaction.user):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "🚫 Permission Denied",
                    "Only server administrators can use this command."
                ),
                ephemeral=True
            )
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        config = get_server_config(interaction.guild.id)
        team_data = config.setdefault("team_data", {})
        team_roles_legacy = config.setdefault("team_roles", {})

        # Check if team exists in either the new or legacy structure
        team_entry_exists = team_name in team_data
        team_legacy_entry_exists = team_name in team_roles_legacy

        if not team_entry_exists and not team_legacy_entry_exists:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "❓ Team Not Found",
                    f"Team **{team_name}** was not found in the configuration."
                ),
                ephemeral=True
            )
            return

        # Migrate from legacy structure to new structure if needed
        if not team_entry_exists and team_legacy_entry_exists:
            legacy_role_id = team_roles_legacy.get(team_name)
            team_data[team_name] = {
                "role_id": legacy_role_id,
                "emoji": "🏆", # Default emoji for migration
                "name": team_name,
                "roster_cap": config.get("roster_cap", DEFAULT_ROSTER_CAP) # Use global cap if not specified
            }
            logger.info(
                f"Migrated team '{team_name}' from legacy team_roles to "
                f"team_data during /configureteam for guild {interaction.guild.id}."
            )
            team_entry_exists = True # Mark as existing in new structure now

        # Retrieve current team info, ensuring it's a dictionary
        current_team_info = team_data.get(team_name)
        if not isinstance(current_team_info, dict):
            logger.error(
                f"Team '{team_name}' data is corrupted or missing in team_data for guild {interaction.guild.id}. Value: {current_team_info}"
            )
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "❌ Data Error",
                    f"Team **{team_name}** has inconsistent data. "
                    "Try removing and re-adding it, or consult logs."
                ),
                ephemeral=True
            )
            return

        changes_made = []
        new_role_obj: Optional[discord.Role] = None # To hold the role object if created/changed

        # --- Handle Role Configuration ---
        if role_id_or_new:
            try:
                target_role_id = None
                if role_id_or_new.lower() == "new":
                    # Check bot permissions and role name uniqueness
                    if not interaction.guild.me.guild_permissions.manage_roles:
                        raise ValueError("Bot lacks 'Manage Roles' permission to create a new role.")
                    if discord.utils.get(interaction.guild.roles, name=team_name):
                        raise ValueError(f"A role named '{team_name}' already exists. Please choose a different name or assign an existing role.")

                    new_role_obj = await interaction.guild.create_role(
                        name=team_name, color=discord.Color.random(),
                        reason=(f"Role for {team_name} by {interaction.user.display_name} via /configureteam")
                    )
                    target_role_id = new_role_obj.id
                else:
                    # Process existing role selection by ID
                    role_id_int = int(role_id_or_new)
                    temp_role_obj = interaction.guild.get_role(role_id_int)
                    if not temp_role_obj:
                        raise ValueError("Selected role not found. It might have been deleted.")

                    # Security checks
                    if temp_role_obj.permissions.administrator:
                        raise ValueError("Cannot assign a role with administrator permissions as a team role.")

                    # Hierarchy check
                    user_top_role_position = interaction.user.top_role.position if interaction.user.top_role else -1
                    if interaction.user.id != interaction.guild.owner_id and \
                       temp_role_obj.position >= user_top_role_position:
                        raise ValueError("Cannot assign a role that is higher than or equal to your own highest role (unless server owner).")

                    new_role_obj = temp_role_obj # Assign found role
                    target_role_id = temp_role_obj.id

                # If a valid role ID was obtained and it's different from the current one
                if target_role_id is not None and target_role_id != current_team_info.get("role_id"):
                    current_team_info["role_id"] = target_role_id
                    team_roles_legacy[team_name] = target_role_id # Sync legacy structure
                    changes_made.append(f"Role updated to {new_role_obj.mention if new_role_obj else f'ID `{target_role_id}`'}")

            except ValueError as ve: # Handle input validation errors
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("🚫 Role Configuration Error", str(ve)),
                    ephemeral=True
                )
                return # Stop processing if role update failed
            except discord.Forbidden: # Handle permission errors
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "🔒 Permissions Error",
                        "Bot lacks permissions for role operation. Ensure 'Manage Roles' is enabled and its role is high enough."
                    ),
                    ephemeral=True
                )
                return # Stop if permissions denied
            except discord.HTTPException as e: # Handle API errors
                logger.error(f"HTTP Exception during role config for guild {interaction.guild.id}: {e}", exc_info=True)
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("❌ API Error", f"An API error occurred during role update: {str(e)}"),
                    ephemeral=True
                )
                return # Stop if API error

        # --- Handle Emoji Configuration ---
        if emoji and emoji != current_team_info.get("emoji"):
            current_team_info["emoji"] = emoji
            changes_made.append(f"Emoji updated to {emoji}")

        # --- Handle Roster Cap Configuration ---
        if roster_cap is not None:
            # Validate roster cap value
            if not 1 <= roster_cap <= 999:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "🚫 Invalid Cap",
                        "Roster cap must be between 1 and 999."
                    ),
                    ephemeral=True
                )
                # Continue processing other valid changes if they exist
            elif roster_cap != current_team_info.get("roster_cap"):
                current_team_info["roster_cap"] = roster_cap
                changes_made.append(f"Roster cap updated to `{roster_cap}`")

        # --- Finalize Changes ---
        # Ensure all necessary keys exist with sensible defaults after updates
        current_team_info.setdefault("name", team_name)
        current_team_info.setdefault("emoji", emoji if emoji else current_team_info.get("emoji", "🏆")) # Use provided emoji, then existing, else default
        # Set roster cap: use provided value, then existing, then global default
        current_team_info.setdefault("roster_cap", roster_cap if roster_cap is not None else current_team_info.get("roster_cap", config.get("roster_cap", DEFAULT_ROSTER_CAP)))

        # If no valid changes were specified or applied
        if not changes_made:
            await interaction.response.send_message(
                embed=EmbedBuilder.info(
                    "ℹ️ No Changes",
                    f"No valid changes were specified or applied for team **{team_name}**."
                ),
                ephemeral=True
            )
            return

        # Update the team data in the configuration
        team_data[team_name] = current_team_info
        save_guild_config(interaction.guild.id, config) # Save the updated config

        # Log the configuration changes
        log_msg = f"Team '{team_name}' configured: {', '.join(changes_made)}."
        await log_action(
            interaction.guild, "SETUP", interaction.user,
            log_msg, "configureteam_cmd"
        )

        # Prepare and send the success message
        final_role_mention = "`Not set`"
        if current_team_info.get('role_id'):
            role = interaction.guild.get_role(current_team_info['role_id'])
            if role: final_role_mention = role.mention

        final_emoji = current_team_info.get('emoji', '🏆')
        final_cap = current_team_info.get('roster_cap', DEFAULT_ROSTER_CAP)

        success_message_lines = [
            "The following updates have been applied:",
            "\n".join(f"• {change}" for change in changes_made),
            "\n**Current Status:**",
            f"Role: {final_role_mention}",
            f"Emoji: {final_emoji}",
            f"Cap: `{final_cap}`"
        ]
        success_embed = EmbedBuilder.success(
            f"⚙️ Team {team_name} Configured!",
            "\n".join(success_message_lines)
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

    @app_commands.command(
        name="removeteam",
        description="Remove a team from the league configuration"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.autocomplete(team_name=team_autocomplete)
    async def removeteam(self, interaction: discord.Interaction, team_name: str):
        """
        Removes a team from the bot's configuration, with an option
        to delete the associated Discord role.
        """
        if not await is_admin(interaction.user):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "🚫 Permission Denied",
                    "Only server administrators can use this command."
                ),
                ephemeral=True
            )
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        config = get_server_config(interaction.guild.id)
        team_data_entry = config.get("team_data", {}).get(team_name)
        team_role_legacy_entry = config.get("team_roles", {}).get(team_name)

        # Determine the associated role ID, checking new structure first
        role_id_to_check = None
        if team_data_entry and isinstance(team_data_entry, dict):
            role_id_to_check = team_data_entry.get("role_id")
        elif team_role_legacy_entry: # Fallback to legacy structure if team not in new structure
            role_id_to_check = team_role_legacy_entry

        # If team not found in either structure, inform the user
        if not team_data_entry and not team_role_legacy_entry:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "❓ Team Not Found",
                    f"Team **{team_name}**** was not found in the configuration."
                ),
                ephemeral=True
            )
            return

        # Create confirmation view
        view = TeamRemoveConfirmationView(
            self, config, interaction.guild.id, team_name, role_id_to_check
        )
        embed_description = (
            f"Are you sure you want to remove team **{team_name}** from the "
            "bot's configuration?\nThis action will also affect its entry "
            "in team lists and commands."
        )
        embed_msg = discord.Embed(
            title=f"🗑️ Confirm Removal: {team_name}",
            description=embed_description,
            color=discord.Color.orange()
        )
        role_obj = interaction.guild.get_role(role_id_to_check) if role_id_to_check else None
        role_info = (
            f"Associated Role: {role_obj.mention} (`{role_obj.name}`)"
            if role_obj else "Associated Role: `None found or ID invalid`"
        )
        embed_msg.add_field(
            name="Impact Details",
            value=f"{role_info}\nYou can choose to delete this role or keep it.",
            inline=False
        )
        await interaction.response.send_message(
            embed=embed_msg, view=view, ephemeral=True
        )

    @app_commands.command(
        name="setrole",
        description="Assign a role to a permission type (e.g., admin, gm)"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.autocomplete(role_type=role_type_autocomplete)
    async def setrole(
        self,
        interaction: discord.Interaction,
        role_type: str, # Corresponds to the base name like 'admin', 'gm'
        role: discord.Role,
        action: str = "add" # Default action is 'add'
    ):
        """
        Assigns or removes a Discord role for a specific bot permission category
        (e.g., Admin, GM). Allows adding multiple roles for certain types.
        """
        if not await is_admin(interaction.user):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "🚫 Permission Denied",
                    "Only server administrators can use this command."
                ),
                ephemeral=True
            )
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        default_perm_settings = get_default_config().get("permission_settings", {})
        # Construct the expected key format (e.g., "admin_roles") from the role_type
        role_list_key_actual = f"{role_type.lower()}_roles" 

        # Validate the provided role_type against the default configuration keys
        if role_list_key_actual not in default_perm_settings:
            valid_simple_types = sorted(
                [k.replace("_roles", "") for k in default_perm_settings.keys()]
            )
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "🚫 Invalid Role Type",
                    f"Role type must be one of: {', '.join(valid_simple_types)}"
                ),
                ephemeral=True
            )
            return

        action_clean = action.lower()
        if action_clean not in ["add", "remove"]:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "🚫 Invalid Action", "Action must be 'add' or 'remove'."
                ),
                ephemeral=True
            )
            return

        config = get_server_config(interaction.guild.id)
        permission_settings = config.setdefault("permission_settings", {})
        # Get the list of role IDs for this permission type, defaulting to an empty list
        role_list_for_type = permission_settings.setdefault(role_list_key_actual, [])

        response_message = ""
        log_detail = ""
        role_type_title = role_type.replace("_", " ").title() # User-friendly title

        if action_clean == "add":
            # Add role if it's not already in the list
            if role.id not in role_list_for_type:
                role_list_for_type.append(role.id)
                role_list_for_type.sort() # Keep the list sorted
                response_message = f"Added {role.mention} to **{role_type_title}** roles."
                log_detail = f"Added role {role.name} ({role.id}) to {role_list_key_actual}"
            else:
                response_message = f"{role.mention} is already in **{role_type_title}** roles."
        elif action_clean == "remove":
            # Remove role if it exists in the list
            if role.id in role_list_for_type:
                role_list_for_type.remove(role.id)
                response_message = f"Removed {role.mention} from **{role_type_title}** roles."
                log_detail = f"Removed role {role.name} ({role.id}) from {role_list_key_actual}"
            else:
                response_message = f"{role.mention} was not found in **{role_type_title}** roles."

        # Save configuration and log action only if a change occurred
        if log_detail: 
            save_guild_config(interaction.guild.id, config)
            await log_action(
                interaction.guild, "SETUP", interaction.user,
                log_detail, "setrole_cmd"
            )
            await interaction.response.send_message(
                embed=EmbedBuilder.success(
                    f"✅ Role Update: {role_type_title}", response_message
                ),
                ephemeral=True
            )
        else: # If no change was made (e.g., role already present/absent)
            await interaction.response.send_message(
                embed=EmbedBuilder.info(
                    f"ℹ️ No Change: {role_type_title}", response_message
                ),
                ephemeral=True
            )

    @app_commands.command(
        name="setup",
        description="Configure the bot for your server (interactive)"
    )
    @app_commands.default_permissions(administrator=True)
    async def setup_command(self, interaction: discord.Interaction): # Renamed method to avoid conflict with helper
        """Initiates an interactive setup process to configure various bot settings for the server."""
        if not await is_admin(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Permission Denied", "Only server administrators can use this command."), ephemeral=True)
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        self.cleanup_sessions() # Clean up any expired sessions

        try:
            live_config_from_db = get_server_config(interaction.guild.id)
        except Exception as e:
            logger.error(f"Failed to load server config for guild {interaction.guild.id} in /setup: {e}", exc_info=True)
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Config Load Error", "Failed to load server configuration. Please try again."), ephemeral=True)
            return

        # Initialize session data for the interactive setup
        session_data = {
            "config": live_config_from_db, # Store a mutable reference to the config
            "timestamp": time.time(),
            "current_page": 0,
            "interaction_proxy": interaction, # Store initial interaction for editing later
            # Maps UI field keys to actual configuration dictionary keys
            "key_mapping": { 
                "transactions_channel": "transactions", "games_channel": "games",
                "suspensions_channel": "suspensions", "general_channel": "general",
                "results_channel": "results", "owners_channel": "owners",
                "announcements_channel": "announcements",
                "free_agency_channel": "free_agency",
                "reminders_channel": "reminders_channel_id", # Special case for notification_settings
            }
        }

        # Define the structure for the setup wizard pages
        setup_pages = [
            {"title": "👑 Core Roles", "description": "Essential roles for bot operation and league management.","icon": "👑","color": discord.Color.gold().value,"fields": [
                {"name": "Admin Role", "description": "Full administrative privileges for bot commands.", "type": "role", "key": "admin"},
                {"name": "Moderator Role", "description": "Moderation privileges for bot commands.", "type": "role", "key": "moderator"},
            ]},
            {"title": "🛠️ Team Staff Roles", "description": "Roles for team management personnel.","icon": "🛠️","color": discord.Color.teal().value,"fields": [
                {"name": "General Manager Role", "description": "Role for General Managers.", "type": "role", "key": "gm"},
                {"name": "Head Coach Role", "description": "Role for Head Coaches.", "type": "role", "key": "hc"},
                {"name": "Assistant Coach Role", "description": "Role for Assistant Coaches.", "type": "role", "key": "ac"},
                {"name": "Franchise Owner Role", "description": "Role for Franchise Owners.", "type": "role", "key": "fo"},
                {"name": "Manage Teams Role", "description": "Users with this role can manage multiple teams (e.g. commissioners).", "type": "role", "key": "manage_teams"},
            ]},
            {"title": "👤 Player & Community Roles", "description": "Roles for players and community engagement.","icon": "👤","color": discord.Color.green().value,"fields": [
                {"name": "Candidate Role", "description": "Role for prospective players or candidates.", "type": "role", "key": "candidate"},
                {"name": "Referee Role", "description": "Role for official Referees.", "type": "role", "key": "referee"},
                {"name": "Streamer Role", "description": "Role for official league Streamers.", "type": "role", "key": "streamer"},
                {"name": "Statistician Role", "description": "Role for official league Statisticians.", "type": "role", "key": "statistician"},
                {"name": "Blacklisted Role", "description": "Users with this role are excluded from certain bot interactions.", "type": "role", "key": "blacklisted"},
            ]},
            {"title": "🚦 Player Status Roles", "description": "Roles related to specific player statuses like suspension or free agency.","icon": "🚦","color": discord.Color.dark_orange().value,"fields": [
                {"name": "Suspension Role", "description": "Role assigned to suspended users.", "type": "role", "key": "suspension"},
                {"name": "Free Agent Role", "description": "Role designating a player as a Free Agent.", "type": "role", "key": "free_agent"},
            ]},
            {"title": "📝 Log Channels Setup", "description": "Channels for various bot and league activity logs.","icon": "📝","color": discord.Color.light_grey().value,"fields": [
                {"name": "Transactions Log", "description": "Logs signings, releases, trades.", "type": "channel", "key": "transactions_channel"},
                {"name": "Games Log", "description": "Logs game scheduling, score reports.", "type": "channel", "key": "games_channel"},
                {"name": "Suspensions Log", "description": "Logs player suspensions and appeals.", "type": "channel", "key": "suspensions_channel"},
                {"name": "General Log", "description": "General bot operational logs.", "type": "channel", "key": "general_channel"},
            ]},
            {"title": "📢 Results & Announcements Channels", "description": "Channels for game results and league news.","icon": "📢","color": discord.Color.blurple().value,"fields": [
                {"name": "Results Log/Channel", "description": "Channel where game results are posted.", "type": "channel", "key": "results_channel"},
                {"name": "Free Agency Announcements", "description": "Channel for free agency news.", "type": "channel", "key": "free_agency_channel"},
                {"name": "Main Announcements Channel", "description": "Primary channel for bot-related announcements.", "type": "channel", "key": "announcements_channel"},
                {"name": "Game Reminders Channel", "description": "Channel for automated game reminders.", "type": "channel", "key": "reminders_channel"},
            ]},
            {"title": "🔒 Specialized Channels","description": "Channel for a list of your team owners.","icon": "🔒","color": discord.Color.dark_grey().value,"fields": [ 
                {"name": "Owners Channel", "description": "Private channel for team owners/GMs.", "type": "channel", "key": "owners_channel"},
            ]},
            {"title": "🧢 Team Roster Caps", "description": "Global and team-specific maximum player limits.","icon": "🧢","color": discord.Color.orange().value,"fields": [
                {"name": "Global Roster Cap", "description": "Set the global default roster cap for all teams.", "type": "text", "key": "global_roster_cap"},
                {"name": "Team Specific Caps", "description": "Set roster caps for individual teams. Select a team to edit its cap.", "type": "team", "key": "team_roster_caps_config"},
            ]},
        ]
        session_data["setup_pages"] = setup_pages
        session_data["total_pages"] = len(setup_pages)

        self.active_setup_sessions[interaction.user.id] = session_data

        await interaction.response.defer(ephemeral=True) # Defer response as sending page is next
        await self.send_setup_page(interaction, 0) # Send the first page

    @app_commands.command(name="setchannel", description="Assign a channel to a specific function (log, announcement, etc.)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.autocomplete(log_type=log_type_autocomplete)
    async def setchannel(self, interaction: discord.Interaction, log_type: str, channel: discord.TextChannel):
        """Assigns a text channel for a specific bot function, like logging or announcements."""
        if not await is_admin(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Permission Denied", "Only server administrators can use this command."), ephemeral=True)
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        default_conf = get_default_config()
        valid_log_channel_keys = list(default_conf.get("log_channels", {}).keys())
        valid_ann_channel_keys = list(default_conf.get("announcement_channels", {}).keys())
        is_reminders_channel = log_type == "reminders_channel_id"

        # Validate the provided log_type against known configurable channel types
        if not (log_type in valid_log_channel_keys or log_type in valid_ann_channel_keys or is_reminders_channel):
            all_valid = sorted(list(set(valid_log_channel_keys + valid_ann_channel_keys + ["reminders_channel_id"]))) # Ensure unique and sorted list of valid types
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Invalid Type", f"Channel type must be one of: {', '.join(all_valid)}"), ephemeral=True)
            return

        # Check bot permissions for sending messages in the selected channel
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message(embed=EmbedBuilder.error("🔒 Permissions Missing", f"The bot lacks 'Send Messages' permission in {channel.mention}. Please grant it and try again."), ephemeral=True)
            return

        config = get_server_config(interaction.guild.id)
        old_channel_id = None
        action_description = ""
        # Generate a user-friendly title for the channel type
        log_type_title = log_type.replace("_channel_id","").replace("_channel","").replace("_", " ").title()

        # Update the correct configuration section based on the log_type
        if is_reminders_channel:
            notif_settings = config.setdefault("notification_settings", {})
            old_channel_id = notif_settings.get(log_type)
            notif_settings[log_type] = channel.id
            action_description = f"**Game Reminders** channel to {channel.mention}"
        elif log_type in valid_ann_channel_keys: # Check if it's an announcement channel key
            ann_channels = config.setdefault("announcement_channels", {})
            old_channel_id = ann_channels.get(log_type)
            ann_channels[log_type] = channel.id
            action_description = f"**{log_type_title}** channel to {channel.mention}"
        else: # Assume it's a log channel
            log_channels = config.setdefault("log_channels", {})
            old_channel_id = log_channels.get(log_type)
            log_channels[log_type] = channel.id
            action_description = f"**{log_type_title}** Log channel to {channel.mention}"

        # Provide feedback if the channel was already set or if it's being changed
        if old_channel_id and old_channel_id != channel.id:
            old_ch_obj = interaction.guild.get_channel(old_channel_id)
            action_description += f" (was {old_ch_obj.mention if old_ch_obj else '`Not set or invalid ID`'})"
        elif old_channel_id == channel.id:
            await interaction.response.send_message(embed=EmbedBuilder.info("ℹ️ No Change", f"The {action_description} was already set to this channel."), ephemeral=True)
            return # Exit if no actual change occurred

        save_guild_config(interaction.guild.id, config) # Save changes to config
        # Log the action performed
        await log_action(interaction.guild, "SETUP", interaction.user, f"Set {action_description}", "setchannel_cmd")
        await interaction.response.send_message(embed=EmbedBuilder.success("✅ Channel Assigned", f"Successfully set {action_description}."), ephemeral=True)


    @app_commands.command(name="gamealerts", description="Configure game reminder settings and notifications")
    @app_commands.default_permissions(administrator=True)
    async def gamealerts(self, interaction: discord.Interaction):
        """Allows administrators to configure game reminder notifications and related settings."""
        if not await is_admin(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Permission Denied", "Only server administrators can use this command."), ephemeral=True)
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        guild_id = interaction.guild.id
        config = get_server_config(guild_id) # Get the server's current configuration

        embed = discord.Embed(title="🎮 Game Alerts & Notifications",
                              description="Manage settings for game reminders, DMs, and channel notifications.",
                              color=discord.Color.blue())

        # Ensure notification_settings dictionary exists, copying defaults if necessary
        notification_settings = config.setdefault("notification_settings", get_default_config()["notification_settings"].copy())
        settings_text_parts = []
        default_notification_config_template = get_default_config().get("notification_settings",{})

        # Iterate through default keys to display current settings and ensure all are shown
        for key, default_val in default_notification_config_template.items():
            current_val = notification_settings.get(key, default_val) # Get current value or default
            display_name = key.replace("_", " ").title()
            if key == "reminders_channel_id":
                channel_obj = interaction.guild.get_channel(current_val) if current_val else None
                settings_text_parts.append(f"• **{display_name}:** {channel_obj.mention if channel_obj else '`Not set`'}")
            elif isinstance(default_val, bool): # Check if the default value is a boolean for toggle settings
                settings_text_parts.append(f"• **{display_name}:** {'✅ Enabled' if current_val else '❌ Disabled'}")

        embed.add_field(name="📊 Current Settings", value="\n".join(settings_text_parts) or "Default notification settings are active.", inline=False)

        # Create and send the view for managing these settings
        view = GameAlertsView(self.bot, guild_id, config) # Pass the config reference
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="autosetup", description="Automatically configure bot with detected items")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(threshold="Similarity threshold for matching (0.0 to 1.0, default 0.7)")
    async def autosetup(self, interaction: discord.Interaction, threshold: float = 0.7):
        """Attempts to automatically detect and configure roles and channels based on common naming patterns."""
        if not await is_admin(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Permission Denied", "Only server administrators can use this command."), ephemeral=True)
            return
        if not 0.0 <= threshold <= 1.0:
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Invalid Threshold", "Similarity threshold must be between 0.0 and 1.0."), ephemeral=True)
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True) # Defer response as this operation can take time

        # Get default configurations to map keys and find potential matches
        default_permission_settings = get_default_config().get("permission_settings", {})
        role_type_map = {key: key.replace("_roles", "").replace("_", " ").title() for key in default_permission_settings.keys()}

        default_log_channels = get_default_config().get("log_channels", {}).keys()
        default_ann_channels = get_default_config().get("announcement_channels", {}).keys()
        # Combine all channel types that can be configured via setchannel or setup
        channel_config_keys_for_autosetup = list(default_log_channels) + list(default_ann_channels) + ["reminders_channel_id"]

        # Detect team roles using utility functions
        detected_team_roles = detect_team_roles(interaction.guild) # Assumes this util function exists
        team_matches = [{"name": generate_team_name_from_role(r), "role_id": r.id, "emoji": find_team_emoji(interaction.guild, generate_team_name_from_role(r)) or "🏆"} for r in detected_team_roles]

        # Find potential role matches based on similarity threshold
        role_matches = {}
        for role_config_key, display_name_generic in role_type_map.items():
            role_matches[role_config_key] = sorted(
                [{"role_id": r.id, "name": r.name, "similarity": SequenceMatcher(None, r.name.lower(), display_name_generic.lower()).ratio()}
                 for r in interaction.guild.roles if r.name != "@everyone" and SequenceMatcher(None, r.name.lower(), display_name_generic.lower()).ratio() >= threshold],
                key=lambda x: x["similarity"], reverse=True
            )

        # Find potential channel matches based on similarity threshold
        channel_matches = {}
        for channel_config_key in channel_config_keys_for_autosetup:
            # Generate a user-friendly name for matching against channel names
            display_name_generic = channel_config_key.replace("_roles","").replace("_channel_id","").replace("_channel","").replace("_", " ").title()
            channel_matches[channel_config_key] = sorted(
                [{"channel_id": c.id, "name": c.name, "similarity": SequenceMatcher(None, c.name.lower(), display_name_generic.lower()).ratio()}
                 for c in interaction.guild.text_channels if SequenceMatcher(None, c.name.lower(), display_name_generic.lower()).ratio() >= threshold],
                key=lambda x: x["similarity"], reverse=True
            )

        # If no potential matches were found for teams, roles, or channels
        if not team_matches and not any(role_matches.values()) and not any(channel_matches.values()):
            await interaction.followup.send(embed=EmbedBuilder.warning("⚠️ No Items Detected", "Could not detect any potential teams, roles, or channels based on common patterns or your threshold. Please use manual setup commands like `/addteam`, `/setrole`, `/setchannel`, or the interactive `/setup`."), ephemeral=True)
            return

        # Create and send the confirmation view
        view = AutoSetupConfirmationView(self.bot, self.guild_id, team_matches, role_matches, channel_matches, role_type_map, channel_config_keys_for_autosetup, threshold, self)
        embed = discord.Embed(title="🚀 Auto-Setup Confirmation",
                              description="Review the bot's auto-detected roles and channels. Select items you wish to configure and confirm your choices to apply them.",
                              color=discord.Color.blue())

        # Summarize detected teams
        team_summary_val = "\n".join([f"• {team['emoji']} **{team['name']}** ({interaction.guild.get_role(team['role_id']).mention if interaction.guild.get_role(team['role_id']) else 'Role N/A'})" for team in team_matches[:5]])
        if len(team_matches) > 5: team_summary_val += f"\n... and {len(team_matches)-5} more teams."
        embed.add_field(name=f"🛡️ Found Teams ({len(team_matches)})", value=team_summary_val or "No teams detected based on role patterns.", inline=False)

        # Summarize top role matches
        role_summary_parts = []
        for r_key, r_matches_list in role_matches.items():
            if r_matches_list: role_summary_parts.append(f"• **{role_type_map[r_key]}**: {r_matches_list[0]['name']} ({r_matches_list[0]['similarity']:.0%})")
        embed.add_field(name="👑 Top Role Matches (by type)", value="\n".join(role_summary_parts) or "No matching roles found based on threshold.", inline=False)

        # Summarize top channel matches
        chan_summary_parts = []
        for c_key, c_matches_list in channel_matches.items():
            if c_matches_list: chan_summary_parts.append(f"• **{c_key.replace('_',' ').title()}**: #{c_matches_list[0]['name']} ({c_matches_list[0]['similarity']:.0%})")
        embed.add_field(name="📢 Top Channel Matches (by type)", value="\n".join(chan_summary_parts) or "No matching channels found based on threshold.", inline=False)

        embed.set_footer(text=f"Using similarity threshold: {threshold:.0%}. Adjust selections or cancel if matches are poor.")
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="settings", description="View the current bot configuration for this server")
    @app_commands.default_permissions(administrator=True)
    async def settings(self, interaction: discord.Interaction):
        """Displays an overview of the current bot configuration for the server."""
        if not await is_admin(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Permission Denied", "Only server administrators can use this command."), ephemeral=True)
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        config = get_server_config(interaction.guild.id)
        embed = discord.Embed(title="📊 Server Bot Configuration Overview",
                              description="Current bot settings for this server. Use `/setup` or specific commands to modify.",
                              color=discord.Color.dark_blue())

        # --- Permission Roles Section ---
        permission_settings = config.get("permission_settings", {})
        roles_text_parts = []
        # Use default config keys to ensure all categories are shown, even if not configured
        default_permission_keys = get_default_config().get("permission_settings", {}).keys()
        for key in sorted(list(default_permission_keys)):
            display_name = key.replace("_roles", "").replace("_", " ").title() + " Roles"
            role_ids = permission_settings.get(key, []) # Get list of role IDs, default to empty list
            # Get mentions for roles that exist in the guild
            role_mentions = [interaction.guild.get_role(rid).mention for rid in role_ids if interaction.guild.get_role(rid)]
            roles_text_parts.append(f"• **{display_name}:** {', '.join(role_mentions) if role_mentions else '`Not set`'}")
        embed.add_field(name="👑 Permission Roles", value="\n".join(roles_text_parts) or "No permission roles configured.", inline=False)

        # --- Configured Channels Section ---
        log_channels = config.get("log_channels", {})
        ann_channels = config.get("announcement_channels", {})
        notif_settings = config.get("notification_settings", {})
        channels_text_parts = []
        # Define a consistent order for displaying channels using default config keys
        channel_keys_ordered = list(get_default_config().get("log_channels",{}).keys()) + \
                               list(get_default_config().get("announcement_channels",{}).keys()) + \
                               ["reminders_channel_id"]
        # Ensure unique keys and process in sorted order for consistency
        for key in sorted(list(set(channel_keys_ordered))): 
            channel_id = None
            # Create a user-friendly display name for the channel type
            display_key_name = key.replace("_channel_id","").replace("_channel","").replace("_", " ").title()
            # Append " Channel" if the name doesn't already imply it
            if "_channel" in key and not display_key_name.lower().endswith("channel"): display_key_name += " Channel" 

            # Retrieve the channel ID from the appropriate config section
            if key == "reminders_channel_id": channel_id = notif_settings.get(key)
            elif key in ann_channels: channel_id = ann_channels.get(key) # Check announcement channels first if key matches
            elif key in log_channels: channel_id = log_channels.get(key) # Fallback to log channels

            channel = interaction.guild.get_channel(channel_id) if channel_id else None
            channels_text_parts.append(f"• **{display_key_name}:** {channel.mention if channel else '`Not set`'}")
        embed.add_field(name="📢 Configured Channels", value="\n".join(channels_text_parts) or "No specialized channels configured.", inline=False)

        # --- Teams & Roster Caps Section ---
        team_data = config.get("team_data", {})
        default_roster_cap_val = config.get("roster_cap", DEFAULT_ROSTER_CAP)
        teams_text_parts = [f"**Global Roster Cap:** `{default_roster_cap_val}`"]
        sorted_team_names = sorted(list(team_data.keys()))
        # Display up to 10 teams for brevity
        for team_name in sorted_team_names[:10]: 
            data = team_data[team_name]
            role = interaction.guild.get_role(data.get("role_id"))
            # Show specific cap if set, otherwise indicate it uses the global cap
            roster_cap_display = data.get("roster_cap")
            if roster_cap_display is None or roster_cap_display == default_roster_cap_val:
                 roster_cap_display = f"Global (`{default_roster_cap_val}`)"
            else:
                 roster_cap_display = f"`{roster_cap_display}`"

            teams_text_parts.append(f"• {data.get('emoji','')} **{team_name}**: {role.mention if role else '`Role N/A`'} (Cap: {roster_cap_display})")

        if len(sorted_team_names) > 10: # Indicate if more teams exist
            teams_text_parts.append(f"... and {len(sorted_team_names) - 10} more teams.")
        if not team_data: # Message if no teams are configured
            teams_text_parts.append("No teams configured. Use `/addteam` or `/autosetup`.")
        embed.add_field(name=f"🏆 Teams & Roster Caps (Total: {len(team_data)})", value="\n".join(teams_text_parts), inline=False)

        # --- Game Notification Preferences Section ---
        notif_display = config.get("notification_settings", {})
        notif_text_parts = []
        # Iterate through default notification keys to show all boolean toggles
        default_notif_keys = get_default_config().get("notification_settings",{}).keys()
        for k in default_notif_keys:
            # Only display boolean toggles here
            if isinstance(get_default_config()["notification_settings"][k], bool): 
                 current_val = notif_display.get(k, get_default_config()["notification_settings"][k]) # Get current or default value
                 notif_text_parts.append(f"• **{k.replace('_',' ').title()}:** {'✅ Enabled' if current_val else '❌ Disabled'}")
        embed.add_field(name="🔔 Game Notification Preferences", value="\n".join(notif_text_parts) or "Default preferences active. Use `/gamealerts` to configure.", inline=False)

        embed.set_footer(text=f"Server ID: {interaction.guild.id} • Use /setup or specific commands to modify.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="update", description="Sends a message to all announcement channels (Bot Owner only).")
    @app_commands.describe(message="The message to send.")
    async def update_command(self, interaction: discord.Interaction, message: str):
        """Sends a provided message to all configured announcement channels. Restricted to bot owner."""
        if interaction.user.id != OWNER_USER_ID:
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Permission Denied", "This command is restricted to the bot owner."), ephemeral=True)
            return

        if not interaction.guild or not interaction.user:
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Invalid Context", "This command requires a server context."), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        config = get_server_config(interaction.guild.id)
        announcement_channels_dict = config.get("announcement_channels", {})

        if not announcement_channels_dict:
            await interaction.followup.send(embed=EmbedBuilder.warning("📢 No Channels Configured", "There are no announcement channels configured for this server. Use `/setchannel` or `/setup`."), ephemeral=True)
            return

        sent_to_count = 0
        failed_channels = []

        # Iterate through configured announcement channels
        for channel_key, channel_id in announcement_channels_dict.items():
            if not channel_id: continue # Skip if channel ID is not set

            channel = interaction.guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    # Check if bot has permissions to send messages in this channel
                    if channel.permissions_for(interaction.guild.me).send_messages:
                        await channel.send(message)
                        sent_to_count += 1
                    else:
                        failed_channels.append(f"#{channel.name} (Missing Send Permissions)")
                        logger.warning(f"Update command: Missing send permissions in channel {channel.id} ({channel.name}) for guild {interaction.guild.id}")
                except discord.Forbidden:
                    failed_channels.append(f"#{channel.name} (Forbidden)")
                    logger.warning(f"Update command: Forbidden to send to channel {channel.id} ({channel.name}) for guild {interaction.guild.id}")
                except discord.HTTPException as e:
                    failed_channels.append(f"#{channel.name} (API Error: {e.status})")
                    logger.error(f"Update command: HTTPException sending to channel {channel.id} ({channel.name}) for guild {interaction.guild.id}: {e}", exc_info=True)
            else:
                failed_channels.append(f"ID {channel_id} (Not a TextChannel or Not Found)")
                logger.warning(f"Update command: Channel ID {channel_id} (key: {channel_key}) is not a valid text channel or not found in guild {interaction.guild.id}")

        # Provide feedback based on the results
        if sent_to_count > 0:
            success_message = f"📣 Message successfully sent to **{sent_to_count}** announcement channel(s)."
            if failed_channels:
                success_message += f"\n\n⚠️ **Could not send to:**\n• " + "\n• ".join(failed_channels)
            await interaction.followup.send(embed=EmbedBuilder.success("✅ Update Sent", success_message), ephemeral=True)
        else:
            error_message = "📢 Message could not be sent to any announcement channels."
            if failed_channels:
                error_message += f"\n\n⚠️ **Reasons:**\n• " + "\n• ".join(failed_channels)
            else: # No channels configured or no failures, but sent to 0 channels
                error_message += " Please ensure announcement channels are configured correctly and the bot has permissions."
            await interaction.followup.send(embed=EmbedBuilder.error("❌ Update Failed", error_message), ephemeral=True)


# --- Modals for Setup Command ---

class GoToPageModal(Modal, title="Go to Page"):
    """Modal for navigating to a specific page in the setup process."""
    def __init__(self, cog_ref: SetupCommands, session_ref: Dict, parent_interaction: discord.Interaction):
        super().__init__()
        self.cog = cog_ref
        self.session = session_ref
        self.parent_interaction = parent_interaction # Interaction that opened this modal (e.g., button click)

        total_pages = self.session.get("total_pages", 1)
        self.page_input = TextInput(
            label=f"Enter Page Number (1-{total_pages})",
            placeholder=f"e.g., 3",
            min_length=1,
            max_length=len(str(total_pages)) # Max length based on number of digits in total_pages
        )
        self.add_item(self.page_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            page_num_str = self.page_input.value
            if not page_num_str.isdigit():
                raise ValueError("Page number must be a number.")

            page_num = int(page_num_str)
            total_pages = self.session.get("total_pages", 1)

            if not 1 <= page_num <= total_pages:
                raise ValueError(f"Page number must be between 1 and {total_pages}.")

            target_page_index = page_num - 1 # Convert to 0-based index

            # Defer the modal's interaction first
            await interaction.response.send_message(f"Navigating to page {page_num}...", ephemeral=True, delete_after=2)

            # Use the parent_interaction (from the button click) to update the original setup message
            await self.cog.send_setup_page(self.parent_interaction, target_page_index)

        except ValueError as ve:
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Invalid Page Number", str(ve)), ephemeral=True, delete_after=5)
        except Exception as e:
            logger.error(f"Error in GoToPageModal on_submit for guild {self.parent_interaction.guild.id}: {e}", exc_info=True)
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Navigation Error", "An unexpected error occurred."), ephemeral=True, delete_after=5)

class RosterCapModal(Modal, title="Edit Roster Cap"):
    """Modal for editing global or team-specific roster caps during interactive setup."""
    def __init__(self, cog_ref: SetupCommands, session_config_live_ref: Dict, guild_obj: discord.Guild, user_id_init: int, target_team_key: str, current_cap_value: Optional[int] = None):
        super().__init__()
        self.cog = cog_ref # Reference to the main cog for accessing active_setup_sessions
        self.session_config = session_config_live_ref # Direct reference to the session's config
        self.guild = guild_obj
        self.user_id = user_id_init # User ID of the person who initiated the setup
        self.target_key_or_global = target_team_key # 'all_teams_global_cap' or team name

        self.cap_input = TextInput(label="New Roster Cap (1-999)", placeholder="Enter a number, e.g., 53")
        # Set default value in the input field
        default_display_cap = current_cap_value if current_cap_value is not None else self.session_config.get("roster_cap", DEFAULT_ROSTER_CAP)
        self.cap_input.default = str(default_display_cap)

        if self.target_key_or_global != "all_teams_global_cap":
            self.cap_input.label = f"Cap for Team: {self.target_key_or_global}"
        else:
            self.cap_input.label = "Global Default Roster Cap"

        self.add_item(self.cap_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cap_value_str = self.cap_input.value
            if not cap_value_str or not cap_value_str.isdigit():
                raise ValueError("Roster cap must be a whole number.")
            cap_value_int = int(cap_value_str)
            if not 1 <= cap_value_int <= 999: 
                raise ValueError("Roster cap must be between 1 and 999.")

            log_detail_msg = ""
            success_user_msg = ""

            if self.target_key_or_global == "all_teams_global_cap":
                old_cap = self.session_config.get("roster_cap", "`Not set`")
                self.session_config["roster_cap"] = cap_value_int
                log_detail_msg = f"Global roster cap to {cap_value_int} (was {old_cap})."
                success_user_msg = f"Global default roster cap staged to be **{cap_value_int}**."
            else:
                team_data_dict = self.session_config.setdefault("team_data", {})
                # Ensure team entry exists if configuring for a specific team
                team_specific_conf = team_data_dict.setdefault(self.target_key_or_global, {"name": self.target_key_or_global, "emoji": "🏆"})
                old_cap = team_specific_conf.get("roster_cap", f"Global ({self.session_config.get('roster_cap', DEFAULT_ROSTER_CAP)})")
                team_specific_conf["roster_cap"] = cap_value_int
                log_detail_msg = f"Roster cap for team '{self.target_key_or_global}' to {cap_value_int} (was {old_cap})."
                success_user_msg = f"Roster cap for team **{self.target_key_or_global}** staged to be **{cap_value_int}**."

            # Log the staged change
            await log_action(self.guild, "SETUP (IN-SESSION)", interaction.user, f"Staged: {log_detail_msg}", "roster_cap_modal_submit")
            await interaction.response.send_message(embed=EmbedBuilder.success("📝 Roster Cap Staged", success_user_msg + "\nChanges will apply when the main setup is saved."), ephemeral=True)

            # Attempt to refresh the main setup page if the cog and session are accessible
            if self.cog and self.user_id in self.cog.active_setup_sessions:
                active_session = self.cog.active_setup_sessions[self.user_id]
                original_interaction_proxy = active_session.get("interaction_proxy") 
                if original_interaction_proxy:
                    try:
                        await self.cog.send_setup_page(original_interaction_proxy, active_session['current_page'])
                        logger.debug(f"RosterCapModal: Successfully refreshed setup page {active_session['current_page']} for user {self.user_id} in guild {self.guild.id}")
                    except Exception as e_refresh:
                        logger.warning(f"RosterCapModal: Failed to auto-refresh main setup page for user {self.user_id} in guild {self.guild.id}: {e_refresh}")
                else:
                    logger.debug(f"RosterCapModal: No interaction_proxy found in session to refresh main setup page for user {self.user_id} in guild {self.guild.id}.")

        except ValueError as ve:
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 Invalid Input", str(ve)), ephemeral=True)
        except Exception as e:
            logger.error(f"Error in RosterCapModal on_submit for guild {self.guild.id}: {e}", exc_info=True)
            await interaction.response.send_message(embed=EmbedBuilder.error("❌ Error", "An unexpected error occurred while processing the roster cap."), ephemeral=True)

# --- Views for Setup Command ---

class SetupPageView(View): # Use imported View
    """View for a single page within the interactive server setup (/setup)."""
    def __init__(self, cog_ref: SetupCommands, page_data_dict: Dict, session_ref: Dict, guild_obj: discord.Guild, user_id_init: int):
        super().__init__(timeout=1800)  # 30-minute timeout for the view
        self.cog = cog_ref
        self.page_data = page_data_dict  # Data for the current page (title, fields, etc.)
        self.session = session_ref  # Reference to the user's active setup session
        self.guild = guild_obj
        self.user_id = user_id_init  # The user ID this session belongs to

        # Mapping of config keys to user-friendly display names (used for logging, etc.)
        self.config_display_names = {
            "admin": "Admin Role", "moderator": "Moderator Role",
            "gm": "General Manager Role", "hc": "Head Coach Role", "ac": "Assistant Coach Role",
            "fo": "Franchise Owner Role", "candidate": "Candidate Role", "referee": "Referee Role",
            "streamer": "Streamer Role", "manage_teams": "Manage Teams Role",
            "blacklisted": "Blacklisted Role", "suspension": "Suspension Role",
            "free_agent": "Free Agent Role", 
            "transactions_channel": "Transactions Log", "games_channel": "Games Log",
            "suspensions_channel": "Suspensions Log", "general_channel": "General Log",
            "results_channel": "Results Log/Channel", "free_agency_channel": "Free Agency Announcements",
            "announcements_channel": "Main Announcements Channel", "reminders_channel": "Game Reminders Channel",
            "owners_channel": "Owners Channel",
            "global_roster_cap": "Global Roster Cap",
            "team_roster_caps_config": "Team Specific Caps",
        }
        self.create_dynamic_selects()  # Add role/channel selects or buttons for this page
        self.add_navigation_buttons()  # Add navigation select menu

    def create_dynamic_selects(self):
        """Creates select menus or buttons for each configurable field on the current page."""
        # Allow up to 4 interactive elements (rows 0-3), leaving row 4 for navigation
        for i, field_item in enumerate(self.page_data.get("fields", [])[:4]): 
            select_custom_id = f"setup_select_{self.session['current_page']}_{field_item['key']}"

            if field_item["type"] == "role":
                # Key for permission_settings, e.g., "admin_roles"
                # Construct the actual config key expected in permission_settings
                role_config_key_for_perms = f"{field_item['key'].replace('_role', '').strip()}_roles"

                # Determine max values allowed based on role type (some allow multiple)
                max_vals = 1
                if field_item["key"] in ["manage_teams", "admin", "moderator"]: # Roles that might allow multiple admins/mods/managers
                    max_vals = 5

                select = RoleSelect( # Use imported RoleSelect
                    placeholder=f"Select {field_item['name']}",
                    min_values=0,  # Allow clearing the role
                    max_values=max_vals, 
                    custom_id=select_custom_id,
                    row=i  # Place each select on rows 0-3
                )
                # Pass the correct config key for permission settings to the callback handler
                select.callback = lambda inter, s=select, k=field_item['key'], rk=role_config_key_for_perms: self.select_callback_handler(inter, s, k, "role", rk)
                self.add_item(select)

            elif field_item["type"] == "channel":
                # Special handling for Games Log to allow multiple channels including threads
                if field_item["key"] == "games_channel":
                    max_values = 5  # Allow up to 5 channels for games log
                    channel_types = [discord.ChannelType.text, discord.ChannelType.public_thread, discord.ChannelType.private_thread]
                else:
                    max_values = 1
                    channel_types = [discord.ChannelType.text]
                    
                select = ChannelSelect( # Use imported ChannelSelect
                    placeholder=f"Select {field_item['name']}",
                    min_values=0, max_values=max_values,
                    channel_types=channel_types,
                    custom_id=select_custom_id,
                    row=i
                )
                select.callback = lambda inter, s=select, k=field_item['key']: self.select_callback_handler(inter, s, k, "channel")
                self.add_item(select)

            elif field_item["type"] == "text":  # For fields like global_roster_cap
                button = Button(label=f"✏️ Set {field_item['name']}", style=discord.ButtonStyle.primary, custom_id=select_custom_id, row=i) # Use imported Button
                button.callback = lambda inter, k=field_item['key']: self.text_input_modal_launcher(inter, k)
                self.add_item(button)

            elif field_item["type"] == "team":  # For team-specific roster caps
                team_data = self.session["config"].get("team_data", {})
                teams = sorted(list(team_data.keys()))
                select = Select( # Use imported Select
                    placeholder="Configure Team Roster Caps",
                    min_values=1, max_values=1,  # Select one team (or global) at a time
                    custom_id=select_custom_id,
                    row=i
                )
                select.add_option(discord.SelectOption(label="🌍 Global Default Roster Cap", value="all_teams_global_cap", emoji="🌍")) # Use discord.SelectOption
                for team_n in teams[:23]:  # Limit options to fit Discord's max (25, minus global)
                    team_info = team_data.get(team_n, {})
                    team_emoji = team_info.get('emoji','🔹')
                    select.add_option(discord.SelectOption(label=f"{team_emoji} {team_n}", value=team_n)) # Use discord.SelectOption
                if len(teams) > 23:  # Indicate if more teams exist
                    select.add_option(discord.SelectOption(label="More teams exist...", value="disabled_placeholder", emoji="..." )) # Use discord.SelectOption

                select.callback = self.roster_cap_team_select_modal_launcher
                self.add_item(select)

    async def text_input_modal_launcher(self, interaction: discord.Interaction, field_key: str):
        """Launches a modal for text input, e.g., global roster cap."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your active setup session.", ephemeral=True)
            return

        if field_key == "global_roster_cap":
            current_cap_val = self.session["config"].get("roster_cap", DEFAULT_ROSTER_CAP)
            modal = RosterCapModal(self.cog, self.session["config"], self.guild, self.user_id, "all_teams_global_cap", current_cap_val)
            await interaction.response.send_modal(modal)
        else:
            # Generic modal for other text inputs (if any are added)
            modal = Modal(title=f"Set {self.config_display_names.get(field_key, field_key.title())}") # Use imported Modal
            text_input_field = TextInput(label="Enter Value", placeholder="Enter the new value", required=True) # Use imported TextInput
            modal.add_item(text_input_field)

            async def generic_modal_submit(modal_interaction: discord.Interaction):
                value = text_input_field.value
                # Store the value directly in the session config
                self.session["config"][field_key] = value
                await log_action(self.guild, "SETUP (IN-SESSION)", modal_interaction.user, f"Set {field_key} to '{value}'", "setup_text_input")
                await modal_interaction.response.send_message(embed=EmbedBuilder.success("Value Staged", f"{field_key.title()} set to **{value}**. Save setup to apply."), ephemeral=True)
                # Refresh the current page after modal submission
                await self.cog.send_setup_page(self.session["interaction_proxy"], self.session["current_page"]) 

            modal.on_submit = generic_modal_submit
            await interaction.response.send_modal(modal)

    async def roster_cap_team_select_modal_launcher(self, interaction: discord.Interaction):
        """Callback for the team select menu on the roster cap page."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your active setup session.", ephemeral=True)
            return

        selected_target_key = interaction.data.get("values", [None])[0]
        if not selected_target_key or selected_target_key == "disabled_placeholder":
            await interaction.response.defer() # Defer if it's a disabled placeholder or no value
            return

        current_cap_val = None
        if selected_target_key == "all_teams_global_cap":
            current_cap_val = self.session["config"].get("roster_cap", DEFAULT_ROSTER_CAP)
        else:
            team_conf = self.session["config"].get("team_data", {}).get(selected_target_key, {})
            # If team specific cap exists, use it. Otherwise, fall back to global cap.
            current_cap_val = team_conf.get("roster_cap", self.session["config"].get("roster_cap", DEFAULT_ROSTER_CAP))

        modal = RosterCapModal(self.cog, self.session["config"], self.guild, self.user_id, selected_target_key, current_cap_val)
        await interaction.response.send_modal(modal)

    async def select_callback_handler(self, interaction: discord.Interaction, select_obj: Union[RoleSelect, ChannelSelect], field_ui_key: str, item_type: str, role_config_key_for_perms: Optional[str] = None):
        """Handles submissions from RoleSelect and ChannelSelect menus."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your active setup session.", ephemeral=True)
            return

        live_config = self.session["config"]
        log_entry_detail = ""
        display_name_for_log = self.config_display_names.get(field_ui_key, field_ui_key.replace("_"," ").title())

        if item_type == "role":
            # Ensure role_config_key_for_perms is provided for role selections
            if not role_config_key_for_perms:
                logger.error(f"Role config key missing for field '{field_key}' in setup page.")
                return await interaction.response.send_message(embed=EmbedBuilder.error("Setup Error", "Internal error processing role selection."), ephemeral=True)

            perm_settings_dict = live_config.setdefault("permission_settings", {})
            role_list_for_type = perm_settings_dict.setdefault(role_config_key_for_perms, [])

            selected_values = select_obj.values # This is a list of Role objects

            if not selected_values: # If the selection is empty (e.g., "None" or cleared)
                role_list_for_type.clear()
                log_entry_detail = f"Cleared **{display_name_for_log}**."
            else:
                # Store IDs as a list, even if only one is selected
                selected_role_ids = [role.id for role in selected_values]
                role_list_for_type.clear() # Clear existing and replace
                role_list_for_type.extend(selected_role_ids)
                mentions = ", ".join([r.mention for r in selected_values])
                log_entry_detail = f"Set **{display_name_for_log}** to: {mentions}"

        elif item_type == "channel":
            actual_config_key_mapped = self.session["key_mapping"].get(field_ui_key)
            selected_channels = select_obj.values if select_obj.values else []

            if actual_config_key_mapped:
                target_dict_for_channel = None
                if field_ui_key == "reminders_channel": # Special key mapped to notification_settings
                    target_dict_for_channel = live_config.setdefault("notification_settings", {})
                elif field_ui_key in ["announcements_channel","free_agency_channel"]: # Check against keys defined for announcement_channels
                    target_dict_for_channel = live_config.setdefault("announcement_channels", {})
                else: # Assume it's a log channel key
                    target_dict_for_channel = live_config.setdefault("log_channels", {})

                if selected_channels:
                    # Special handling for games_channel to support multiple channels
                    if field_ui_key == "games_channel":
                        # Store as list of channel IDs for games log
                        target_dict_for_channel[actual_config_key_mapped] = [ch.id for ch in selected_channels]
                        channel_mentions = [ch.mention for ch in selected_channels]
                        log_entry_detail = f"Set **{display_name_for_log}** to {', '.join(channel_mentions)}"
                    else:
                        # Single channel for other types
                        target_dict_for_channel[actual_config_key_mapped] = selected_channels[0].id
                        log_entry_detail = f"Set **{display_name_for_log}** to {selected_channels[0].mention}"
                else:
                    # Remove the key if no channel is selected (cleared)
                    target_dict_for_channel.pop(actual_config_key_mapped, None)
                    log_entry_detail = f"Cleared **{display_name_for_log}**."
            else:
                logger.warning(f"Setup: No key mapping found for UI field '{field_ui_key}'. Cannot save selection for guild {self.guild.id}.")
                log_entry_detail = f"Error: No mapping for '{field_ui_key}'. Selection not saved."

        if log_entry_detail:
            await log_action(self.guild, "SETUP (IN-SESSION)", interaction.user, log_entry_detail, "setup_select_change")

        # Defer the response to allow time for logging and page refresh
        await interaction.response.defer() 
        # Refresh the current page to show updated 'Current' values
        await self.cog.send_setup_page(self.session["interaction_proxy"], self.session["current_page"])

    def add_navigation_buttons(self):
        """Adds a navigation select menu to the view."""
        # Determine the row for navigation buttons, ensuring it's below other selects. Max row is 4.
        max_used_row = 0
        for item in self.children:
            if hasattr(item, 'row') and item.row is not None:
                max_used_row = max(max_used_row, item.row)
        nav_button_row = min(max_used_row + 1, 4) # Place on next available row, max row 4.

        self.nav_select = Select( # Use imported Select
            placeholder="Navigation & Actions",
            custom_id="setup_nav_select",
            row=nav_button_row,
            options=[
                discord.SelectOption(label="Go to First Page", value="first", emoji="⏪"), # Use discord.SelectOption
                discord.SelectOption(label="Previous Page", value="prev", emoji="◀️"), # Use discord.SelectOption
                discord.SelectOption(label="Next Page", value="next", emoji="▶️"), # Use discord.SelectOption
                discord.SelectOption(label="Go to Last Page", value="last", emoji="⏩"), # Use discord.SelectOption
                discord.SelectOption(label="Go to Page...", value="goto", emoji="🔢"), # Use discord.SelectOption
                discord.SelectOption(label="Save & Exit", value="save", emoji="💾"), # Use discord.SelectOption
            ]
        )
        self.nav_select.callback = self.nav_select_callback
        self.add_item(self.nav_select) # Add the navigation select menu

        self._update_nav_select_states() # Update states based on current page

    def _update_nav_select_states(self):
        """Updates the state of navigation options (e.g., disabling Prev/Next on boundaries)."""
        current_pg = self.session.get("current_page", 0)
        total_pgs = self.session.get("total_pages", 1)

        is_on_first_page = (current_pg == 0)
        is_on_last_page = (current_pg >= total_pgs - 1)

        new_options = []

        # Option: Go to First Page
        if is_on_first_page:
            new_options.append(discord.SelectOption(label="Go to First Page (Current)", value="nav_disabled_first", emoji="⏪")) # Use discord.SelectOption
        else:
            new_options.append(discord.SelectOption(label="Go to First Page", value="first", emoji="⏪")) # Use discord.SelectOption

        # Option: Previous Page
        if is_on_first_page:
            new_options.append(discord.SelectOption(label="Previous Page", description="You are on the first page.", value="nav_disabled_prev", emoji="◀️")) # Use discord.SelectOption
        else:
            new_options.append(discord.SelectOption(label="Previous Page", value="prev", emoji="◀️")) # Use discord.SelectOption

        # Option: Next Page
        if is_on_last_page:
            new_options.append(discord.SelectOption(label="Next Page", description="You are on the last page.", value="nav_disabled_next", emoji="▶️")) # Use discord.SelectOption
        else:
            new_options.append(discord.SelectOption(label="Next Page", value="next", emoji="▶️")) # Use discord.SelectOption

        # Option: Go to Last Page
        if is_on_last_page:
            new_options.append(discord.SelectOption(label="Go to Last Page (Current)", value="nav_disabled_last", emoji="⏩")) # Use discord.SelectOption
        else:
            new_options.append(discord.SelectOption(label="Go to Last Page", value="last", emoji="⏩")) # Use discord.SelectOption

        # Add the static, always-enabled options
        new_options.append(discord.SelectOption(label="Go to Page...", value="goto", emoji="🔢")) # Use discord.SelectOption
        new_options.append(discord.SelectOption(label="Save & Exit", value="save", emoji="💾")) # Use discord.SelectOption

        # Replace the old options list with the new one
        self.nav_select.options = new_options


    async def nav_select_callback(self, interaction: discord.Interaction):
        """Handles navigation select menu interactions."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your active setup session.", ephemeral=True)
            return

        selected_action = interaction.data["values"][0]

        # If the value contains "nav_disabled", it's a disabled option. Defer and do nothing.
        if "nav_disabled" in selected_action:
            await interaction.response.defer() 
            return

        current_pg = self.session.get("current_page", 0)
        total_pgs = self.session.get("total_pages", 1)

        if selected_action == "first":
            await interaction.response.defer()
            await self.cog.send_setup_page(self.session["interaction_proxy"], 0)
        elif selected_action == "prev" and current_pg > 0:
            await interaction.response.defer()
            await self.cog.send_setup_page(self.session["interaction_proxy"], current_pg - 1)
        elif selected_action == "next" and current_pg < total_pgs - 1:
            await interaction.response.defer()
            await self.cog.send_setup_page(self.session["interaction_proxy"], current_pg + 1)
        elif selected_action == "last":
            await interaction.response.defer()
            await self.cog.send_setup_page(self.session["interaction_proxy"], total_pgs - 1)
        elif selected_action == "goto":
            modal = GoToPageModal(self.cog, self.session, self.session["interaction_proxy"])
            await interaction.response.send_modal(modal)
        elif selected_action == "save":
            await self.save_and_exit_callback(interaction)
        else:
            # Defer any other unexpected selections
            await interaction.response.defer()

    async def save_and_exit_callback(self, interaction: discord.Interaction):
        """Saves the entire configuration and ends the setup session."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your active setup session.", ephemeral=True)
            return

        try:
            save_guild_config(self.guild.id, self.session["config"])
            await log_action(self.guild, "SETUP COMPLETE", interaction.user, "Server configuration saved via interactive /setup.", "setup_save_exit")

            embed = EmbedBuilder.success("💾 Configuration Saved!", "Server configuration has been successfully saved.")
            perm_settings = self.session["config"].get("permission_settings", {})
            # Count the total number of roles assigned across all permission categories
            roles_set_count = sum(len(r_list) for r_list in perm_settings.values() if isinstance(r_list, list) and r_list)

            # Count configured channels
            log_ch_count = sum(1 for _ in self.session["config"].get("log_channels", {}).values() if _)
            ann_ch_count = sum(1 for _ in self.session["config"].get("announcement_channels", {}).values() if _)
            rem_ch_set = 1 if self.session["config"].get("notification_settings", {}).get("reminders_channel_id") else 0
            total_channels_set = log_ch_count + ann_ch_count + rem_ch_set
            teams_configured = len(self.session["config"].get("team_data", {}))

            summary_text = (f"• **{roles_set_count}** permission roles assigned.\n"
                            f"• **{total_channels_set}** specialized channels assigned.\n"
                            f"• **{teams_configured}** teams are set up (manage caps via `/configureteam` or relevant setup page).\n")
            embed.add_field(name="📊 Configuration Summary", value=summary_text, inline=False)
            embed.add_field(name="🚀 Next Steps", 
                            value=("• Use `/addteam` or `/configureteam` for detailed team management.\n"
                                   "• View all current settings anytime with `/settings`.\n"
                                   "• Explore other commands like `/gamealerts` for more specific configurations."), 
                            inline=False)

            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            logger.error(f"Failed to save config for guild {self.guild.id} via /setup: {e}", exc_info=True)
            error_embed = EmbedBuilder.error("❌ Save Error", "Failed to save configuration. Please try again or contact support if the issue persists.")
            await interaction.response.edit_message(embed=error_embed, view=None)
        finally:
            self.cog.active_setup_sessions.pop(self.user_id, None) # Remove session regardless of save success
            self.stop()

class AutoSetupConfirmationView(View): # Use imported View
    """View for confirming auto-detected setup items from /autosetup."""
    def __init__(self, bot, guild_id: int, team_matches: List[Dict], role_matches: Dict,
                 channel_matches: Dict, role_type_map: Dict, channel_config_keys: List[str],
                 threshold: float, setup_cog_ref: SetupCommands):
        super().__init__(timeout=600) # 10-minute timeout
        self.bot, self.guild_id = bot, guild_id
        self.team_matches, self.role_matches = team_matches, role_matches
        self.channel_matches, self.role_type_map = channel_matches, role_type_map
        self.channel_config_keys, self.threshold, self.cog = channel_config_keys, threshold, setup_cog_ref

        # Store user selections
        self.selected_teams_by_role_id: Dict[int, Dict] = {} # role_id: team_info (for teams)
        # Stores list of role IDs for each permission type (e.g., "admin": [123, 456])
        self.selected_roles_by_type: Dict[str, List[int]] = {} 
        # Stores list of channel IDs for each channel type (e.g., "transactions": [789])
        self.selected_channels_by_type: Dict[str, List[int]] = {} 

        self._add_team_select()
        self._add_role_selects()
        self._add_channel_selects()
        self._add_control_buttons()

    def _add_team_select(self):
        if not self.team_matches: return
        select = Select(placeholder="Select Teams to Add/Update (Max 25)", min_values=0, max_values=min(len(self.team_matches), 25), custom_id="autosetup_teams", row=0) # Use imported Select
        for team_info in self.team_matches[:25]: # Show top 25 matches
            select.add_option(discord.SelectOption(label=f"{team_info['emoji']} {team_info['name']}", value=str(team_info["role_id"]))) # Use discord.SelectOption
        select.callback = self._team_select_callback
        self.add_item(select)

    def _add_role_selects(self):
        current_row = 1
        items_in_row = 0
        # Iterate through role types defined in default config for consistency
        for role_config_key, display_name in self.role_type_map.items():
            role_specific_matches = self.role_matches.get(role_config_key, [])
            if not role_specific_matches: continue # Skip if no matches for this type

            top_match = role_specific_matches[0]
            placeholder_text = f"{display_name}"
            if top_match: placeholder_text += f" (Best: {top_match['name']})"

            if items_in_row >= 2: # Max 2 role selects per row
                current_row +=1; items_in_row = 0
            if current_row > 3: # Limit to 3 rows of role selects
                logger.info(f"AutoSetup: Too many role types for guild {self.guild_id}. Stopping role selects at row {current_row-1}.")
                break

            select = Select(placeholder=placeholder_text, min_values=0, max_values=min(len(role_specific_matches), 5), custom_id=f"autosetup_role_{role_config_key}", row=current_row) # Use imported Select
            select.add_option(discord.SelectOption(label="None (Do not set this role)", value="none_role_option")) # Use discord.SelectOption
            # Add top few matches for this role type
            guild = self.bot.get_guild(self.guild_id)
            added_role_ids = set()
            for match_info in role_specific_matches[:5]: # Show top 5 + None
                role_obj = guild.get_role(match_info["role_id"]) if guild else None
                if role_obj and match_info["role_id"] not in added_role_ids:
                    select.add_option(discord.SelectOption(label=f"{role_obj.name} ({match_info['similarity']:.0%})", value=str(match_info["role_id"]))) # Use discord.SelectOption
                    added_role_ids.add(match_info["role_id"])

            select.callback = lambda inter, rck=role_config_key: self._role_select_callback(inter, rck)
            self.add_item(select)
            items_in_row +=1

    def _add_channel_selects(self):
        current_row = 4 # Start channel selects on a new row below roles
        items_in_row = 0
        guild = self.bot.get_guild(self.guild_id)
        # Iterate through channel types defined in default config for consistency
        for channel_config_key in self.channel_config_keys:
            channel_specific_matches = self.channel_matches.get(channel_config_key, [])
            if not channel_specific_matches: continue

            top_match = channel_specific_matches[0]
            display_name_placeholder = channel_config_key.replace("_roles","").replace("_channel_id","").replace("_channel","").replace("_", " ").title()
            placeholder_text = f"{display_name_placeholder} Ch."
            if top_match and top_match.get('name'): placeholder_text += f" (Best: #{top_match['name']})"

            if items_in_row >= 2: # Max 2 channel selects per row
                current_row +=1; items_in_row = 0
            if current_row > 6: # Limit to 3 rows of channel selects (rows 4, 5, 6)
                logger.info(f"AutoSetup: Too many channel types for guild {self.guild_id}. Stopping channel selects at row {current_row-1}.")
                break

            select = Select(placeholder=placeholder_text, min_values=0, max_values=1, custom_id=f"autosetup_chan_{channel_config_key}", row=current_row) # Use imported Select
            select.add_option(discord.SelectOption(label="None (Do not set this channel)", value="none_channel_option")) # Use discord.SelectOption
            added_channel_ids_for_select = set()
            for match_info in channel_specific_matches[:5]: # Top 5 matches
                channel_obj = guild.get_channel(match_info["channel_id"]) if guild else None
                if channel_obj and match_info["channel_id"] not in added_channel_ids_for_select:
                    select.add_option(discord.SelectOption(label=f"#{channel_obj.name} ({match_info['similarity']:.0%})", value=str(match_info["channel_id"]))) # Use discord.SelectOption
                    added_channel_ids_for_select.add(match_info["channel_id"])
            # Option to add other channels if space permits
            if guild and len(select.options) < 25:
                for chan in sorted(guild.text_channels, key=lambda c: c.name):
                    if chan.id not in added_channel_ids_for_select:
                        select.add_option(discord.SelectOption(label=f"#{chan.name} (Other)", value=str(chan.id))) # Use discord.SelectOption
                        if len(select.options) >= 25: break # Cap options at 25

            select.callback = lambda inter, cck=channel_config_key: self._channel_select_callback(inter, cck)
            self.add_item(select)
            items_in_row +=1

    def _add_control_buttons(self):
        # Determine row for controls, ensuring it's below other selects. Max row is 4.
        max_used_row = 0
        for item in self.children:
            if hasattr(item, 'row') and item.row is not None:
                max_used_row = max(max_used_row, item.row)
        control_button_row = min(max_used_row + 1, 4) # Place on next available row, max row 4.

        confirm = Button(label="✅ Confirm & Save Selected", style=discord.ButtonStyle.success, custom_id="autosetup_confirm", row=control_button_row) # Use imported Button
        confirm.callback = self._confirm_callback
        self.add_item(confirm)

        cancel = Button(label="❌ Cancel Auto-Setup", style=discord.ButtonStyle.danger, custom_id="autosetup_cancel", row=control_button_row) # Use imported Button
        cancel.callback = self._cancel_callback
        self.add_item(cancel)

    async def _team_select_callback(self, interaction: discord.Interaction):
        # Store selected team role IDs and their full match info
        self.selected_teams_by_role_id.clear()
        selected_role_ids_str = interaction.data.get("values", [])
        for role_id_str in selected_role_ids_str:
            for team_match in self.team_matches: # Find the full team_match dict
                if str(team_match["role_id"]) == role_id_str:
                    self.selected_teams_by_role_id[int(role_id_str)] = team_match
                    break
        await interaction.response.defer()

    async def _role_select_callback(self, interaction: discord.Interaction, role_config_key: str):
        selected_values_str = interaction.data.get("values", [])
        selected_role_ids = []

        if selected_values_str and "none_role_option" not in selected_values_str:
            # Convert selected IDs to integers
            selected_role_ids = [int(val) for val in selected_values_str]

        # Store the list of selected role IDs for this configuration key
        self.selected_roles_by_type[role_config_key] = selected_role_ids

        await interaction.response.defer()

    async def _channel_select_callback(self, interaction: discord.Interaction, channel_config_key: str):
        selected_values_str = interaction.data.get("values", [])
        selected_channel_ids = []

        if selected_values_str and "none_channel_option" not in selected_values_str:
            # Get the single selected channel ID (max_values=1 for channels)
            selected_channel_ids = [int(selected_values_str[0])]

        # Store the list of selected channel IDs (will contain 0 or 1 element)
        self.selected_channels_by_type[channel_config_key] = selected_channel_ids

        await interaction.response.defer()

    async def _confirm_callback(self, interaction: discord.Interaction):
        # Check if any selections were actually made
        if not self.selected_teams_by_role_id and \
           all(not v for v in self.selected_roles_by_type.values()) and \
           all(not v for v in self.selected_channels_by_type.values()):
            await interaction.response.send_message(embed=EmbedBuilder.warning("⚠️ No Selections", "Please select items to configure or cancel the auto-setup."), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True) # Acknowledge, then process
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            await interaction.followup.send(embed=EmbedBuilder.error("❌ Guild Error", "Could not retrieve guild information."), ephemeral=True)
            return

        config = get_server_config(self.guild_id)
        log_summary = ["Auto-Setup Confirmed:"]

        # Apply selected teams
        if self.selected_teams_by_role_id:
            team_data_dict = config.setdefault("team_data", {})
            team_roles_legacy_dict = config.setdefault("team_roles", {}) # For compatibility
            global_cap = config.get("roster_cap", DEFAULT_ROSTER_CAP)
            for role_id, team_info in self.selected_teams_by_role_id.items():
                team_name = team_info["name"]
                team_data_dict[team_name] = {"role_id": role_id, "emoji": team_info["emoji"], "roster_cap": global_cap, "name": team_name}
                team_roles_legacy_dict[team_name] = role_id # Sync legacy
                log_summary.append(f"• Team: {team_info['emoji']} **{team_name}** (Role ID: {role_id})")

        # Apply selected permission roles
        perm_settings_dict = config.setdefault("permission_settings", {})
        for role_conf_key, selected_role_ids in self.selected_roles_by_type.items():
            if selected_role_ids: # Only apply if list is not empty
                perm_settings_dict[role_conf_key] = selected_role_ids # Assign the list of IDs
                role_objs = [guild.get_role(rid) for rid in selected_role_ids if guild.get_role(rid)]
                role_names = [r.name for r in role_objs] if role_objs else []
                if role_names:
                    log_summary.append(f"• Role **{self.role_type_map.get(role_conf_key, role_conf_key.title())}**: {', '.join(role_names)}")

        # Apply selected channels
        log_ch_dict = config.setdefault("log_channels", {})
        ann_ch_dict = config.setdefault("announcement_channels", {})
        notif_set_dict = config.setdefault("notification_settings", {})
        for chan_conf_key, selected_channel_ids in self.selected_channels_by_type.items():
            if selected_channel_ids: # Only apply if list is not empty
                chan_id_val = selected_channel_ids[0] # Take the first (and likely only) channel ID
                chan_obj = guild.get_channel(chan_id_val)
                chan_mention_log = chan_obj.name if chan_obj else f'ID {chan_id_val}'

                if chan_conf_key == "reminders_channel_id": # Special key for notification_settings
                    notif_set_dict[chan_conf_key] = chan_id_val
                # Check against keys defined in default config for announcement channels
                elif chan_conf_key in get_default_config().get("announcement_channels", {}): 
                    ann_ch_dict[chan_conf_key] = chan_id_val
                else: # Assume it's a log channel key
                    log_ch_dict[chan_conf_key] = chan_id_val
                log_summary.append(f"• Channel **{chan_conf_key.replace('_',' ').title()}**: #{chan_mention_log}")

        save_guild_config(self.guild_id, config)
        await log_action(guild, "SETUP (AUTO)", interaction.user, "\n".join(log_summary), "autosetup_confirmed")

        final_embed = EmbedBuilder.success("✨ Auto-Setup Complete!", "Selected configurations have been automatically applied and saved to the server's settings.")
        # Edit the original message (which was deferred)
        await interaction.edit_original_response(embed=final_embed, view=None) 
        self.stop()

    async def _cancel_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=EmbedBuilder.info("ℹ️ Auto-Setup Cancelled", "No changes were applied to the configuration."), view=None)
        self.stop()

class TeamRemoveConfirmationView(View): # Use imported View
    """Confirmation view for removing a team, with an option to delete the associated role."""
    def __init__(self, setup_cog_ref: SetupCommands, guild_config_live_ref: Dict, guild_id_val: int, team_name_to_remove: str, role_id_associated: Optional[int]):
        super().__init__(timeout=180) # 3-minute timeout
        self.cog = setup_cog_ref
        self.guild_config = guild_config_live_ref # Direct reference to the live config
        self.guild_id = guild_id_val
        self.team_name = team_name_to_remove
        self.role_id = role_id_associated
        # Default to deleting role if it exists, otherwise false. User can toggle.
        self.should_delete_role_flag = bool(self.role_id) 

        # Button to toggle role deletion
        self.toggle_role_delete_button = Button( # Use imported Button
            label=f"Delete Associated Role: {'✅ Yes' if self.should_delete_role_flag else '❌ No'}",
            style=discord.ButtonStyle.success if self.should_delete_role_flag else discord.ButtonStyle.secondary,
            custom_id="toggle_delete_role_on_remove", row=0,
            disabled=not self.role_id # Disable if no role is associated
        )
        self.toggle_role_delete_button.callback = self.toggle_delete_role_callback
        self.add_item(self.toggle_role_delete_button)

        # Confirmation and cancel buttons
        confirm = Button(label="Confirm Removal", style=discord.ButtonStyle.danger, custom_id="confirm_remove_final", row=1) # Use imported Button
        confirm.callback = self.confirm_remove_callback
        self.add_item(confirm)

        cancel = Button(label="Cancel", style=discord.ButtonStyle.grey, custom_id="cancel_remove_final", row=1) # Use imported Button
        cancel.callback = self.cancel_remove_callback
        self.add_item(cancel)

    async def toggle_delete_role_callback(self, interaction: discord.Interaction):
        """Toggles the flag for deleting the associated role."""
        self.should_delete_role_flag = not self.should_delete_role_flag
        self.toggle_role_delete_button.label = f"Delete Associated Role: {'✅ Yes' if self.should_delete_role_flag else '❌ No'}"
        self.toggle_role_delete_button.style = discord.ButtonStyle.success if self.should_delete_role_flag else discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self) # Update the button appearance

    async def confirm_remove_callback(self, interaction: discord.Interaction):
        """Confirms team removal and optionally deletes the role."""
        await interaction.response.defer(ephemeral=True) # Acknowledge interaction
        try:
            team_data_dict = self.guild_config.setdefault("team_data", {})
            team_roles_legacy_dict = self.guild_config.setdefault("team_roles", {})

            removed_from_data = self.team_name in team_data_dict
            removed_from_legacy = self.team_name in team_roles_legacy_dict

            # Remove from configurations
            team_data_dict.pop(self.team_name, None)
            team_roles_legacy_dict.pop(self.team_name, None)

            role_delete_status_log = ""
            role_delete_status_msg = ""

            # Handle role deletion if requested and role exists
            if self.should_delete_role_flag and self.role_id:
                role_obj_to_delete = interaction.guild.get_role(self.role_id)
                if role_obj_to_delete:
                    try:
                        await role_obj_to_delete.delete(reason=f"Team '{self.team_name}' removed by {interaction.user.name}")
                        role_delete_status_log = f"Associated role '{role_obj_to_delete.name}' was DELETED."
                        role_delete_status_msg = " The associated role was also deleted."
                    except discord.Forbidden:
                        role_delete_status_log = f"FAILED to delete role '{role_obj_to_delete.name}' (Bot lacks permissions)."
                        role_delete_status_msg = " Failed to delete the associated role: Bot lacks permissions."
                    except discord.HTTPException as e_http:
                        role_delete_status_log = f"FAILED to delete role '{role_obj_to_delete.name}' (Discord API Error: {e_http.status})."
                        role_delete_status_msg = f" Failed to delete the associated role: Discord API error ({e_http.status})."
                else: # Role ID was configured but role not found on server
                    role_delete_status_log = "Role ID was configured but role not found on server."
                    role_delete_status_msg = " The associated role ID was found in config, but the role itself was not found on the server."
            elif self.role_id: # Role exists but user chose not to delete
                role_delete_status_log = "Associated role was explicitly PRESERVED."
                role_delete_status_msg = " The associated role was not deleted as per your choice."
            # No specific log needed if no role_id was associated or deletion wasn't requested.

            if removed_from_data or removed_from_legacy: # If the team was actually found and removed from config
                save_guild_config(self.guild_id, self.guild_config) # Save changes to file/DB
                final_log_msg = f"Removed team '{self.team_name}'. {role_delete_status_log}"
                await log_action(interaction.guild, "SETUP", interaction.user, final_log_msg, "removeteam_confirmed")

                final_user_msg = f"Team **{self.team_name}** has been removed from the configuration.{role_delete_status_msg}"
                await interaction.edit_original_response(embed=EmbedBuilder.success("🗑️ Team Removed", final_user_msg), view=None)
            else: # If team wasn't found in config initially
                await interaction.edit_original_response(embed=EmbedBuilder.error("❓ Not Found", f"Team **{self.team_name}** was not found in the configuration. No changes were made."), view=None)

            self.stop() # Stop the view
        except Exception as e:
            logger.error(f"Error confirming team removal for guild {self.guild_id}, team {self.team_name}: {e}", exc_info=True)
            await interaction.edit_original_response(embed=EmbedBuilder.error("❌ Error", f"An unexpected error occurred: {str(e)}"), view=None)
            self.stop()

    async def cancel_remove_callback(self, interaction: discord.Interaction):
        """Cancels the team removal process."""
        await interaction.response.edit_message(embed=EmbedBuilder.info("ℹ️ Cancelled", "Team removal has been cancelled. No changes were made."), view=None)
        self.stop()


# --- Cog Setup Function ---
async def setup(bot: commands.Bot):
    """Standard setup function to add the Cog to the bot."""
    await bot.add_cog(SetupCommands(bot))
    logger.info("SetupCommands Cog loaded successfully.")