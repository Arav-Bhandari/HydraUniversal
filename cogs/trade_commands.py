import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import logging
from datetime import datetime
from typing import Optional
import re # For parsing player lists

# --- Utility Imports ---
# Ensure your utils directory structure is correct for these imports.
from utils.config import get_server_config, load_json, save_json
from utils.permissions import can_use_command, detect_team
from utils.logging import log_action
from utils.embeds import EmbedBuilder
# --- End Utility Imports ---

logger = logging.getLogger("bot.trades")

# --- Player Management Placeholder Functions ---
# You WILL need to implement these functions based on your specific player data structure.
# These are essential for validating trades, checking roster caps, and updating player teams.

# Placeholder for fetching a player's record. Should return a dict with player info (name, Discord ID, team, etc.)
# or None if not found.
def _find_player_record(player_name: str, team_name: str, guild_id: int) -> Optional[dict]:
    """Conceptual: Find a player record by name and team. Returns player dict or None."""
    # Example structure: {"discord_id": "1234567890", "player_name": "Player One", "team": "TeamA"}
    # Implement logic to search your player database/file.
    logger.debug(f"Placeholder: Searching for player '{player_name}' on team '{team_name}' in guild {guild_id}")
    # Dummy implementation: Pretend the player exists if the name isn't "Invalid Player"
    if "Invalid Player" not in player_name:
        return {"discord_id": "DUMMY_USER_ID", "player_name": player_name, "team": team_name}
    return None

# Placeholder for updating a player's team assignment.
async def _update_player_team(player_name: str, current_team: str, target_team: str, guild_id: int):
    """Conceptual: Update player's team affiliation. Returns True on success."""
    logger.debug(f"Placeholder: Moving player '{player_name}' from '{current_team}' to '{target_team}' in guild {guild_id}")
    # Implement logic to update your player roster data.
    # This might involve finding the player's Discord ID, then updating their 'team' field.
    return True

# Placeholder for getting a team's roster cap from config.
def _get_player_roster_cap(team_name: str, guild_id: int) -> int:
    """Conceptual: Get the roster cap for a specific team or global default."""
    config = get_server_config(guild_id)
    team_data = config.get("team_data", {})
    team_specific_cap = team_data.get(team_name, {}).get("roster_cap")
    if team_specific_cap:
        return int(team_specific_cap)
    else: # Fallback to global cap
        return config.get("roster_cap", 53) # Default to 53 if not set

# Placeholder for getting the current number of players on a team.
def _get_team_roster_count(team_name: str, guild_id: int) -> int:
    """Conceptual: Count players currently assigned to a team."""
    logger.debug(f"Placeholder: Counting players for team '{team_name}' in guild {guild_id}")
    # Implement logic to count players assigned to team_name in your player data.
    # For simulation: Return a count, ensuring it doesn't exceed cap initially for tests.
    if team_name == "TeamA": return 3 # Dummy count
    if team_name == "TeamB": return 4 # Dummy count
    return 0 # Default count

# Placeholder for finding a Discord user ID associated with a player name and team.
# Crucial for DMing players.
def _find_discord_user_id_by_player_name(player_name: str, team_name: str, guild_id: int) -> Optional[int]:
    """Conceptual: Find the Discord user ID for a given player name on a team."""
    logger.debug(f"Placeholder: Finding Discord ID for player '{player_name}' on team '{team_name}' in guild {guild_id}")
    # Implement logic to look up player's linked Discord ID (e.g., from appointments.json or player DB).
    # Dummy implementation: Returns a fake ID if player exists conceptually.
    player_record = _find_player_record(player_name, team_name, guild_id)
    if player_record and "discord_id" in player_record and player_record["discord_id"] != "DUMMY_USER_ID":
        return int(player_record["discord_id"])
    elif player_record and player_record["discord_id"] == "DUMMY_USER_ID":
        return 1234567890 # Dummy ID for testing DM failure if needed, or replace with actual lookup.
    return None

# --- TradeCommands Cog ---
class TradeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="propose-trade", description="Propose a player trade with another team")
    @app_commands.describe(
        team="The team to trade with (select from autocomplete)",
        players_offered="Your player(s) to trade (comma-separated names)",
        players_wanted="The player(s) you want in return (comma-separated names)"
    )
    async def propose_trade(self, interaction: discord.Interaction, team: str, players_offered: str, players_wanted: str):
        """Propose a player trade with another team."""
        if not await can_use_command(interaction.user, "propose_trade"):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "You don't have permission to use this command."), ephemeral=True)
            return

        # Auto-detect user's team
        user_team = detect_team(interaction.user) # Assumes detect_team returns team name string or None
        if not user_team:
            await interaction.response.send_message(embed=EmbedBuilder.error("Team Not Found", "Could not detect your team. Ensure you have the correct team role."), ephemeral=True)
            return

        # Check if trading with own team
        if user_team.lower() == team.lower():
            await interaction.response.send_message(embed=EmbedBuilder.error("Invalid Trade", "You cannot trade with your own team."), ephemeral=True)
            return

        config = get_server_config(interaction.guild.id)
        # Verify target team exists using case-insensitive comparison
        target_team_actual_name = None
        if "team_roles" in config and config["team_roles"]:
            for team_name_in_config in config["team_roles"]:
                if team_name_in_config.lower() == team.lower():
                    target_team_actual_name = team_name_in_config
                    break

        if not target_team_actual_name:
            await interaction.response.send_message(embed=EmbedBuilder.error("Invalid Team", f"Team '{team}' does not exist in configuration."), ephemeral=True)
            return

        team = target_team_actual_name # Use the correctly capitalized name

        # Parse player names
        offered_players = [p.strip() for p in players_offered.split(',') if p.strip()]
        wanted_players = [p.strip() for p in players_wanted.split(',') if p.strip()]

        if not offered_players:
            await interaction.response.send_message(embed=EmbedBuilder.error("Invalid Input", "You must specify at least one player to offer."), ephemeral=True)
            return
        if not wanted_players:
            await interaction.response.send_message(embed=EmbedBuilder.error("Invalid Input", "You must specify at least one player you want in return."), ephemeral=True)
            return

        # --- Player and Roster Cap Validation (Conceptual) ---
        # This section requires access to your player roster data.
        # You need to implement the placeholder functions (_find_player_record, _get_player_roster_cap, etc.)

        # Check if offered players exist on the user's team and if swapping them keeps the team under cap
        # Check if wanted players exist on the target team and if swapping them keeps the target team under cap
        offered_player_records = []
        for player_name in offered_players:
            player_record = _find_player_record(player_name, user_team, interaction.guild.id)
            if not player_record:
                await interaction.response.send_message(embed=EmbedBuilder.error("Player Not Found", f"Could not find player '{player_name}' on your team '{user_team}'."), ephemeral=True)
                return
            if player_record.get("team") != user_team:
                await interaction.response.send_message(embed=EmbedBuilder.error("Invalid Player Assignment", f"'{player_name}' is not currently assigned to '{user_team}'."), ephemeral=True)
                return
            offered_player_records.append(player_record)

        wanted_player_records = []
        for player_name in wanted_players:
            player_record = _find_player_record(player_name, team, interaction.guild.id)
            if not player_record:
                await interaction.response.send_message(embed=EmbedBuilder.error("Player Not Found", f"Could not find player '{player_name}' on team '{team}'."), ephemeral=True)
                return
            if player_record.get("team") != team:
                await interaction.response.send_message(embed=EmbedBuilder.error("Invalid Player Assignment", f"'{player_name}' is not currently assigned to '{team}'."), ephemeral=True)
                return
            wanted_player_records.append(player_record)

        # Check roster caps BEFORE proposing
        user_team_cap = _get_player_roster_cap(user_team, interaction.guild.id)
        target_team_cap = _get_player_roster_cap(team, interaction.guild.id)

        current_user_roster_size = _get_team_roster_count(user_team, interaction.guild.id)
        current_target_roster_size = _get_team_roster_count(team, interaction.guild.id)

        players_moving_out_of_user_team = len(offered_players)
        players_moving_into_user_team = len(wanted_players)

        # Calculate hypothetical new roster sizes
        hypothetical_user_roster_size = current_user_roster_size - players_moving_out_of_user_team + players_moving_into_user_team
        hypothetical_target_roster_size = current_target_roster_size - players_moving_into_user_team + players_moving_out_of_user_team

        if hypothetical_user_roster_size > user_team_cap:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Roster Cap Exceeded", f"This trade would cause {user_team} to exceed its roster cap of {user_team_cap}. Current players after trade: {hypothetical_user_roster_size}."),
                ephemeral=True
            )
            return
        if hypothetical_target_roster_size > target_team_cap:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Roster Cap Exceeded", f"This trade would cause {team} to exceed its roster cap of {target_team_cap}. Current players after trade: {hypothetical_target_roster_size}."),
                ephemeral=True
            )
            return
        # --- End Player and Roster Cap Validation ---


        # Load trades
        trades = load_json("trades.json")
        guild_id = str(interaction.guild.id)

        if guild_id not in trades:
            trades[guild_id] = {}

        # Check for existing active trades between these teams to prevent double proposals
        for trade_id, trade in trades[guild_id].items():
            if trade["status"] == "pending" and (
                (trade["team1"] == user_team and trade["team2"] == team) or
                (trade["team1"] == team and trade["team2"] == user_team)
            ):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Trade Already Pending", 
                        f"There is already a pending trade between {user_team} and {team}. "
                        f"Wait for that trade to be resolved before proposing a new one."
                    ),
                    ephemeral=True
                )
                return

        # Create the trade proposal
        trade_id = f"TRADE-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        trade = {
            "team1": user_team, # The team initiating the trade
            "team2": team,      # The team receiving the proposal
            "players_offered_by_team1": offered_players,
            "players_offered_by_team2": wanted_players, # These are what team2 offers in return
            "status": "pending",
            "proposed_at": datetime.now().timestamp(),
            "proposed_by": str(interaction.user.id)
        }

        # Save the trade proposal
        trades[guild_id][trade_id] = trade
        save_json("trades.json", trades)

        # Create trade embed for the channel post
        embed = discord.Embed(
            title="🔄 Trade Proposal",
            description=f"{user_team} has proposed a trade with {team}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name=f"{user_team} offers", value=", ".join(offered_players), inline=True)
        embed.add_field(name=f"{team} offers", value=", ".join(wanted_players), inline=True)
        embed.set_footer(text=f"Trade ID: {trade_id}")

        # Respond to the user acknowledging the proposal submission
        await interaction.response.send_message(embed=EmbedBuilder.success("Trade Proposed", f"Your trade proposal has been sent to {team}'s front office."), ephemeral=True)

        # --- Notify Target Team's Front Office (GM, HC, FO) ---
        team_role_id = config.get("team_roles", {}).get(team) # Get role ID for target team
        if team_role_id:
            # Fetch FO users from appointments.json (GM, HC, FO)
            # Ensure appointments.json loading is safe and handles missing files/data.
            appointments = load_json("appointments.json") 
            team_fo_user_ids = set() # Use a set to store unique Discord User IDs

            if guild_id in appointments and team in appointments[guild_id]:
                team_appointments = appointments[guild_id][team]

                # Add GM
                gm_discord_id = team_appointments.get("gm")
                if gm_discord_id: team_fo_user_ids.add(int(gm_discord_id))

                # Add HC
                hc_discord_id = team_appointments.get("hc")
                if hc_discord_id: team_fo_user_ids.add(int(hc_discord_id))

                # Add all FO members
                for fo_discord_id_str in team_appointments.get("fo", []):
                    try:
                        team_fo_user_ids.add(int(fo_discord_id_str))
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid FO ID format '{fo_discord_id_str}' for team {team} in guild {guild_id}. Skipping.")

            # If no specific FO staff are found, we might fallback to members with the team role
            # For this example, we'll prioritize the FO staff list. If it's empty, no specific notification will be sent.
            # You might want to add a fallback to pinging the team role or owner if FO list is empty.

            if team_fo_user_ids:
                # Create the DM embed
                dm_embed = discord.Embed(
                    title="🔄 New Trade Proposal Received!",
                    description=f"**{user_team}** has proposed a trade with **{team}**.",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                dm_embed.add_field(name=f"{user_team} Offers", value=", ".join(offered_players), inline=True)
                dm_embed.add_field(name=f"{team} Offers", value=", ".join(wanted_players), inline=True)
                dm_embed.set_footer(text=f"Trade ID: {trade_id}")

                # Create the view with Accept/Deny buttons
                view = TradeResponseView(self.bot, trade_id, guild_id)

                for discord_id in team_fo_user_ids:
                    try:
                        user_obj = guild.get_member(discord_id) # Fetch member object
                        if user_obj:
                            await user_obj.send(embed=dm_embed, view=view)
                        else:
                            logger.warning(f"Could not find user {discord_id} to DM trade proposal for guild {guild_id}.")
                    except Exception as e:
                        logger.error(f"Failed to send trade proposal DM to user {discord_id}: {e}", exc_info=True)
            else:
                 logger.warning(f"No Front Office staff found for team '{team}' in guild {guild_id} via appointments.json for trade proposal {trade_id}.")
                 # Optional: Ping team role or owner as a fallback
                 await interaction.channel.send(f"Warning: Could not directly notify FO staff for {team} about the trade proposal.")

        # Post to transactions channel if configured
        config = get_server_config(interaction.guild.id)
        if "log_channels" in config and "transactions" in config["log_channels"]:
            log_channel_id = config["log_channels"]["transactions"]
            if log_channel_id:
                try:
                    log_channel = interaction.guild.get_channel(int(log_channel_id))
                    if log_channel:
                        log_embed = embed.copy()
                        log_embed.add_field(name="Proposed by", value=interaction.user.mention, inline=True)
                        log_embed.add_field(name="Proposer Team", value=user_team, inline=True)
                        log_embed.set_footer(text=f"Trade ID: {trade_id}") # Add Trade ID to log embed too
                        await log_channel.send(embed=log_embed)
                except Exception as e:
                    logger.error(f"Failed to send trade proposal to transactions log: {e}", exc_info=True)

# Trade Response View (for FO members to accept/deny)
class TradeResponseView(discord.ui.View):
    def __init__(self, bot, trade_id, guild_id):
        super().__init__(timeout=None) # View lives until manually disabled or message deleted
        self.bot = bot
        self.trade_id = trade_id
        self.guild_id = guild_id

    async def process_response(self, interaction: discord.Interaction, status: str):
        """Handles the accept/deny logic."""
        # Verify the user interacting has the correct permissions (e.g., is FO/GM/HC for the target team)
        # This check should be more robust. For now, assuming if they got the DM, they have some right to respond.
        # A proper check would involve looking up team appointments or roles.

        guild = self.bot.get_guild(int(self.guild_id))
        if not guild:
            await interaction.response.send_message(embed=EmbedBuilder.error("Error", "Could not find the server context for this trade."), ephemeral=True)
            return

        trades = load_json("trades.json")
        if self.guild_id not in trades or self.trade_id not in trades[self.guild_id]:
            await interaction.response.send_message(embed=EmbedBuilder.error("Trade Not Found", "This trade proposal has expired or been processed."), ephemeral=True)
            return

        trade = trades[self.guild_id][self.trade_id]

        # Check if the trade is still pending
        if trade["status"] != "pending":
            await interaction.response.send_message(embed=EmbedBuilder.error("Trade Already Processed", f"This trade has already been {trade['status']}."), ephemeral=True)
            return

        # --- Authorization Check for Responder ---
        # The DM should only go to legitimate FO members. A stricter check here would be:
        # Find the team the user IS FOR via their roles/appointments, check if it matches trade["team2"]
        # This logic is already partially implemented in propose_trade's DM lookup,
        # and it should ideally be checked here too if multiple users could respond.
        # For simplicity now, we trust that DMs went to the correct people.

        # --- Roster Cap & Player Validation for Acceptance ---
        trade_accepted_successfully = False
        if status == "accepted":
            logger.info(f"Trade {self.trade_id}: Accepted by user {interaction.user.id}")
            # --- Player & Roster Cap Validation ---
            offered_by_team1_names = trade.get("players_offered_by_team1", [])
            offered_by_team2_names = trade.get("players_offered_by_team2", [])
            team1_name = trade["team1"]
            team2_name = trade["team2"]

            valid_trade = True
            validation_messages = []

            # 1. Validate existence of players and correct team assignments
            offered_by_team1_records = []
            for p_name in offered_by_team1_names:
                record = _find_player_record(p_name, team1_name, self.guild_id)
                if not record:
                    valid_trade = False; validation_messages.append(f"Player '{p_name}' from {team1_name} not found.")
                    break
                if record.get("team") != team1_name:
                    valid_trade = False; validation_messages.append(f"'{p_name}' is not correctly assigned to {team1_name}.")
                    break
                offered_by_team1_records.append(record)

            if valid_trade:
                offered_by_team2_records = []
                for p_name in offered_by_team2_names:
                    record = _find_player_record(p_name, team2_name, self.guild_id)
                    if not record:
                        valid_trade = False; validation_messages.append(f"Player '{p_name}' from {team2_name} not found.")
                        break
                    if record.get("team") != team2_name:
                        valid_trade = False; validation_messages.append(f"'{p_name}' is not correctly assigned to {team2_name}.")
                        break
                    offered_by_team2_records.append(record)

            # 2. Validate roster caps if players were found correctly
            if valid_trade:
                # Check Team1's new roster size
                team1_cap = _get_player_roster_cap(team1_name, self.guild_id)
                current_team1_size = _get_team_roster_count(team1_name, self.guild_id)
                players_leaving_team1 = len(offered_by_team1_records)
                players_joining_team1 = len(offered_by_team2_records)

                hypothetical_team1_size = current_team1_size - players_leaving_team1 + players_joining_team1
                if hypothetical_team1_size > team1_cap:
                    valid_trade = False
                    validation_messages.append(f"{team1_name}'s roster would exceed cap ({hypothetical_team1_size}/{team1_cap}).")

                # Check Team2's new roster size
                team2_cap = _get_player_roster_cap(team2_name, self.guild_id)
                current_team2_size = _get_team_roster_count(team2_name, self.guild_id)
                players_leaving_team2 = len(offered_by_team2_records)
                players_joining_team2 = len(offered_by_team1_records)

                hypothetical_team2_size = current_team2_size - players_leaving_team2 + players_joining_team2
                if hypothetical_team2_size > team2_cap:
                    valid_trade = False
                    validation_messages.append(f"{team2_name}'s roster would exceed cap ({hypothetical_team2_size}/{team2_cap}).")

            # If trade is not valid, respond with error and do NOT update statuses
            if not valid_trade:
                logger.warning(f"Trade {self.trade_id} rejected due to validation failure: {', '.join(validation_messages)}")
                # Notify user who responded
                await interaction.response.send_message(embed=EmbedBuilder.error("Trade Rejected", "The trade could not be accepted due to the following issues:\n- " + "\n- ".join(validation_messages)), ephemeral=True)

                # Notify the original proposer about the rejection reason
                proposer_user_id_str = trade.get("proposed_by")
                proposer_user_id = int(proposer_user_id_str) if proposer_user_id_str and proposer_user_id_str.isdigit() else None
                if proposer_user_id:
                    proposer_member = guild.get_member(proposer_user_id)
                    if proposer_member:
                        try:
                            await proposer_member.send(embed=EmbedBuilder.warning("Trade Rejected", f"Your trade proposal ({self.trade_id}) with {trade['team2']} was rejected because:\n- " + "\n- ".join(validation_messages)))
                        except Exception as e: logger.error(f"Failed to DM proposer ({proposer_member.id}) about rejected trade validation: {e}", exc_info=True)

                # Log the rejection reason
                log_action(guild, "TRADE", interaction.user, f"Trade {self.trade_id} rejected due to validation: {', '.join(validation_messages)}", "trade_rejected_validation")

                # Optionally update original proposal message status? For now, just stop processing this response.
                trade["status"] = "rejected_validation" # Mark as rejected with reason
                trade["rejected_at"] = datetime.now().timestamp()
                trade["rejected_by"] = str(interaction.user.id)
                trades[self.guild_id][self.trade_id] = trade # Save updated status
                save_json("trades.json", trades)

                # Disable buttons to prevent further interaction with this outdated view
                for child in self.children: child.disabled = True
                await interaction.message.edit(view=self) # Update original message to show buttons are disabled

                return # Stop here, trade did not go through.

            else: # Trade validation passed
                # --- Execute Trade: Update Player Rosters ---
                trade_execution_success = True
                # This part is critical and requires your player management functions.
                # Example sequence:
                try:
                    # 1. For players offered by team1 (moving to team2):
                    for player_record in offered_by_team1_records:
                        player_name_for_update = player_record["player_name"]
                        player_discord_id = player_record.get("discord_id")

                        if not player_name_for_update or not player_discord_id:
                             raise ValueError(f"Player record incomplete for '{player_name}' ({player_record}). Cannot process.")

                        success = await _update_player_team(player_name_for_update, team1_name, team2_name, self.guild_id)
                        if not success: raise ValueError(f"Failed to update team for player '{player_name_for_update}'.")

                    # 2. For players offered by team2 (moving to team1):
                    for player_record in offered_by_team2_records:
                        player_name_for_update = player_record["player_name"]
                        player_discord_id = player_record.get("discord_id")

                        if not player_name_for_update or not player_discord_id:
                             raise ValueError(f"Player record incomplete for '{player_name}' ({player_record}). Cannot process.")

                        success = await _update_player_team(player_name_for_update, team2_name, team1_name, self.guild_id)
                        if not success: raise ValueError(f"Failed to update team for player '{player_name_for_update}'.")

                    logger.info(f"Trade {self.trade_id} execution: All player swaps successful.")

                except ValueError as ve: # Catch validation errors from placeholders
                    logger.error(f"Trade execution error for {self.trade_id}: {ve}")
                    trade_execution_success = False
                    status = "rejected_validation" # Set status to indicate failure
                    validation_messages.append(str(ve)) # Add error to messages

                    # Potentially revert any partial changes if something failed mid-way (complex)
                    # For simplicity, assuming atomic failure or that placeholders handle revert.
                except Exception as e_exec:
                    logger.error(f"Trade execution error for {self.trade_id}: {e_exec}", exc_info=True)
                    trade_execution_success = False
                    status = "rejected_execution_error"
                    validation_messages.append("An unexpected server error occurred during execution.")

                # If execution was successful (no exceptions)
                if trade_execution_success:
                    # --- DM Traded Players ---
                    for player_record in offered_by_team1_records:
                        discord_user_id = _find_discord_user_id_by_player_name(player_record["player_name"], team1_name, self.guild_id)
                        if discord_user_id:
                            await self._dm_player_about_trade(guild, discord_user_id, trade, team1_name, trade["players_offered_by_team1"], trade["players_offered_by_team2"])

                    for player_record in offered_by_team2_records:
                        discord_user_id = _find_discord_user_id_by_player_name(player_record["player_name"], team2_name, self.guild_id)
                        if discord_user_id:
                            await self._dm_player_about_trade(guild, discord_user_id, trade, team2_name, trade["players_offered_by_team2"], trade["players_offered_by_team1"]) # Pass args correctly

                    # --- Post to Transactions Channel ---
                    config = get_server_config(int(self.guild_id))
                    if "log_channels" in config and "transactions" in config["log_channels"]:
                        tx_channel_id = config["log_channels"]["transactions"]
                        if tx_channel_id:
                            tx_channel = guild.get_channel(int(tx_channel_id))
                            if tx_channel:
                                tx_embed = discord.Embed(
                                    title="✅ Trade Executed!",
                                    description=f"Trade between **{trade['team1']}** and **{trade['team2']}** has been successfully executed.",
                                    color=discord.Color.green(),
                                    timestamp=datetime.now()
                                )
                                tx_embed.add_field(name=f"{trade['team1']} sent", value=", ".join(offered_by_team1_names), inline=True)
                                tx_embed.add_field(name=f"{trade['team2']} sent", value=", ".join(offered_by_team2_names), inline=True)
                                tx_embed.set_footer(text=f"Trade ID: {self.trade_id}")
                                await tx_channel.send(embed=tx_embed)
                            else: logger.warning(f"Transactions channel {tx_channel_id} not found for trade completion log.")
                        else: logger.warning("Transactions channel ID not configured.")

                # Update trade status in JSON regardless of success to prevent reprocessing
                trade["status"] = status
                trade[f"{status}_at"] = datetime.now().timestamp()
                trade[f"{status}_by"] = str(interaction.user.id)
                if validation_messages: # Add rejection messages if applicable
                    trade["rejection_reason"] = ", ".join(validation_messages)

                trades[self.guild_id][self.trade_id] = trade
                save_json("trades.json", trades) # Save updated trade status

        else: # Trade was denied or failed validation
            logger.info(f"Trade {self.trade_id} denied or failed validation.")
            # Update trade status, log, notify proposer etc. as needed for denial cases.
            trade["status"] = status
            trade[f"{status}_at"] = datetime.now().timestamp()
            trade[f"{status}_by"] = str(interaction.user.id)
            if validation_messages: # Add failure messages
                trade["rejection_reason"] = ", ".join(validation_messages)

            trades[self.guild_id][self.trade_id] = trade # Save updated status
            save_json("trades.json", trades) # Save updated trade status

            # Notify the original proposer about the denial and reason
            proposer_user_id_str = trade.get("proposed_by")
            proposer_user_id = int(proposer_user_id_str) if proposer_user_id_str and proposer_user_id_str.isdigit() else None
            if proposer_user_id and guild:
                proposer_member = guild.get_member(proposer_user_id)
                if proposer_member:
                    try:
                        await proposer_member.send(embed=EmbedBuilder.warning(f"Trade {status.capitalize()}", f"Your proposed trade ({self.trade_id}) with {trade['team2']} was rejected because:\n- " + "\n- ".join(validation_messages)))
```python
                    except Exception as e: logger.error(f"Failed to DM proposer ({proposer_member.id}) about trade {self.trade_id} rejection: {e}", exc_info=True)

        # --- Common steps for accept/deny/reject ---
        # Create the response embed for the user who clicked the button
        if status == "accepted":
            response_embed = discord.Embed(title="✅ Trade Accepted", description=f"The trade has been accepted and is being processed.", color=discord.Color.green(), timestamp=datetime.now())
        elif status == "denied":
            response_embed = discord.Embed(title="❌ Trade Denied", description=f"The trade has been denied.", color=discord.Color.red(), timestamp=datetime.now())
        elif status == "rejected_validation" or status == "rejected_execution_error":
             response_embed = discord.Embed(title=f"❌ Trade Rejected", description=f"The trade could not be processed due to:\n- " + "\n- ".join(validation_messages), color=discord.Color.red(), timestamp=datetime.now())
        else: # Should not happen, but as a fallback
             response_embed = discord.Embed(title="Trade Status Update", description=f"Trade status updated to: {status.capitalize()}", color=discord.Color.blurple(), timestamp=datetime.now())

        response_embed.add_field(name=f"{trade['team1']} Offers", value=", ".join(trade.get("players_offered_by_team1", ["N/A"])), inline=True)
        response_embed.add_field(name=f"{trade['team2']} Offers", value=", ".join(trade.get("players_offered_by_team2", ["N/A"])), inline=True)
        response_embed.set_footer(text=f"Trade ID: {self.trade_id}")

        await interaction.response.edit_message(embed=response_embed, view=self) # Edit the DM message to show outcome

        # Log the final trade action (accepted, denied, or rejected)
        await log_action(
            guild,
            "TRADE",
            interaction.user,
            f"Trade {self.trade_id} between {trade['team1']} and {trade['team2']} resulted in: {status}.",
            f"trade_{status}"
        )
        self.stop() # Stop the view interaction

    async def _dm_player_about_trade(self, guild: discord.Guild, discord_user_id: int, trade: dict, player_team: str, players_leaving_team: List[str], players_joining_team: List[str]):
        """DMs a player about their trade outcome (accepted/rejected)."""
        member = guild.get_member(discord_user_id)
        if not member:
            logger.warning(f"Could not find member {discord_user_id} to DM trade outcome for trade {trade['trade_id']}.")
            return

        outcome = trade.get("status")
        if outcome not in ["accepted", "rejected_validation", "rejected_execution_error"]: return # Only DM for final outcomes

        dm_embed_title = ""
        dm_embed_color = discord.Color.default()
        dm_description_lines = []

        offering_team = trade["team1"] if player_team == trade["team1"] else trade["team2"]
        receiving_team = trade["team2"] if player_team == trade["team1"] else trade["team1"]

        players_traded_from_your_team = []
        players_traded_to_your_team = []

        if player_team == trade["team1"]: # Player belongs to team1
            players_traded_from_your_team = players_leaving_team
            players_traded_to_your_team = players_joining_team
        else: # Player belongs to team2
            players_traded_from_your_team = players_leaving_team
            players_traded_to_your_team = players_joining_team

        if outcome == "accepted":
            dm_embed_title = "Update on Your Trade!"
            dm_embed_color = discord.Color.green()
            dm_description_lines.append(f"Your team, **{player_team}**, has successfully traded players!")
            dm_description_lines.append(f"**You are moving:** {', '.join(players_traded_from_your_team)}")
            dm_description_lines.append(f"**Your team receives:** {', '.join(players_traded_to_your_team)}")
            dm_description_lines.append(f"\n**Transaction Complete.**")
        else: # Rejected or other statuses
            dm_embed_title = f"Trade Proposal Update ({outcome.capitalize()})"
            dm_embed_color = discord.Color.red()
            dm_description_lines.append(f"Your proposed trade ({trade.get('trade_id')}) did not go through.")
            reasons = trade.get("rejection_reason")
            if reasons: dm_description_lines.append(f"Reason(s): {reasons}")

        dm_embed = discord.Embed(
            title=dm_embed_title,
            description="\n".join(dm_description_lines),
            color=dm_embed_color,
            timestamp=datetime.now()
        )
        dm_embed.set_footer(text=f"Trade ID: {trade.get('trade_id')}")

        try:
            await member.send(embed=dm_embed)
        except Exception as e:
            logger.error(f"Failed to DM player {member.id} ({member.name}) about trade {trade.get('trade_id')}: {e}", exc_info=True)


async def setup(bot):
    """Registers the TradeCommands cog."""
    await bot.add_cog(TradeCommands(bot))
    logger.info("TradeCommands Cog loaded successfully.")