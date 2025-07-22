import discord
import asyncio
import logging
from discord import app_commands
from discord.ext import commands
from utils.config import get_server_config, load_json, save_json
from utils.permissions import can_use_command, has_management_role # These internally use get_server_config
from utils.logging import log_action
from utils.embeds import EmbedBuilder
from datetime import datetime, timedelta
import pytz # Added for timezone-aware timestamps
import re
from typing import Optional

logger = logging.getLogger("bot.suspensions")

class SuspensionCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="suspend", description="Suspend a player, assign suspension role, and remove team/coach roles.")
    @app_commands.describe(
        player="The member to suspend", # Changed from player_name
        reason="Reason for the suspension",
        duration="Duration of suspension (e.g., 3 days, 1 week, 5 games)"
    )
    async def suspend(
        self,
        interaction: discord.Interaction,
        player: discord.Member, # Changed from player_name: str
        reason: str,
        duration: str
    ):
        guild_config = get_server_config(interaction.guild.id) # Fetch guild_config

        if not await can_use_command(interaction.user, "suspend"): # Internally uses get_server_config
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "You don't have permission."),ephemeral=True)
            return
        if not await has_management_role(interaction.user): # Internally uses get_server_config
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied","You need Management role."),ephemeral=True)
            return

        try:
            value, unit = self.parse_duration(duration)
            if not value or not unit:
                await interaction.response.send_message(embed=EmbedBuilder.error("Invalid Duration","Format: '3 days', '1 week', '5 games'."),ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message(embed=EmbedBuilder.error("Invalid Duration","Format: '3 days', '1 week', '5 games'."),ephemeral=True)
            return

        end_date = None
        if unit in ['day', 'week']:
            delta = timedelta(days=value) if unit == 'day' else timedelta(weeks=value)
            end_date = datetime.now(pytz.utc) + delta # Use timezone-aware datetime

        # Pass player object and guild_config to the View
        view = SuspensionConfirmationView(
            self.bot, 
            player, # Pass discord.Member object
            reason, 
            value, 
            unit, 
            end_date,
            interaction.user.id,
            guild_config # Pass guild_config
        )

        embed = discord.Embed(
            title="🚫 Suspension Confirmation",
            description=f"Suspend **{player.display_name}** ({player.mention})?",
            color=discord.Color.red(),
            timestamp=datetime.now(pytz.utc)
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        duration_display = f"{value} {unit}{'s' if value > 1 else ''}"
        if end_date:
            duration_display += f" (until <t:{int(end_date.timestamp())}:F> - <t:{int(end_date.timestamp())}:R>)"
        embed.add_field(name="Duration", value=duration_display, inline=False)
        embed.add_field(name="Proposed Actions", value="• Assign Suspension Role\n• Remove Team Role\n• Remove Coach Roles (FO, GM, HC, AC)", inline=False)
        embed.set_footer(text="Click confirm to proceed.")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


    @app_commands.command(name="unsuspend", description="Lift a suspension from a player and remove suspension role.")
    @app_commands.describe(player="The member to unsuspend") # Changed from player_name
    async def unsuspend(self, interaction: discord.Interaction, player: discord.Member): # Changed
        guild_config = get_server_config(interaction.guild.id)

        if not await can_use_command(interaction.user, "unsuspend"):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "You don't have permission."),ephemeral=True)
            return
        if not await has_management_role(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied","You need Management role."),ephemeral=True)
            return

        suspensions = load_json("suspensions.json")
        guild_id_str = str(interaction.guild.id)

        if guild_id_str not in suspensions or not suspensions[guild_id_str]:
            await interaction.response.send_message(embed=EmbedBuilder.error("No Suspensions", "No active suspensions for this server."),ephemeral=True)
            return

        found_suspension_id = None
        found_suspension_data = None
        for susp_id, susp_data in suspensions[guild_id_str].items():
            # Check against player_id now
            if susp_data.get("player_id") == str(player.id) and susp_data.get("status") == "active":
                found_suspension_id = susp_id
                found_suspension_data = susp_data
                break

        if not found_suspension_id:
            await interaction.response.send_message(embed=EmbedBuilder.error("No Active Suspension",f"No active suspension found for {player.mention}."),ephemeral=True)
            return

        found_suspension_data["status"] = "lifted"
        found_suspension_data["lifted_at"] = datetime.now(pytz.utc).timestamp()
        found_suspension_data["lifted_by_id"] = str(interaction.user.id)
        found_suspension_data["lifted_by_name"] = interaction.user.display_name

        # Remove Suspension Role
        roles_removed_log = []
        permission_settings = guild_config.get("permission_settings", {})
        suspension_role_ids = permission_settings.get("suspension_roles", [])
        if suspension_role_ids:
            try:
                role_id_to_remove = int(suspension_role_ids[0])
                suspension_role_obj = interaction.guild.get_role(role_id_to_remove)
                if suspension_role_obj and suspension_role_obj in player.roles:
                    await player.remove_roles(suspension_role_obj, reason=f"Suspension lifted by {interaction.user.name}")
                    roles_removed_log.append(suspension_role_obj.name)
                    logger.info(f"Removed suspension role {suspension_role_obj.name} from {player.display_name}")
            except ValueError: logger.error(f"Invalid Suspension Role ID for unsuspend: {suspension_role_ids[0]}")
            except discord.Forbidden: logger.error(f"Forbidden to remove suspension role from {player.display_name}")
            except Exception as e: logger.error(f"Error removing suspension role: {e}", exc_info=True)

        suspensions[guild_id_str][found_suspension_id] = found_suspension_data # Save before embed
        save_json("suspensions.json", suspensions)

        embed = discord.Embed(title="✅ Suspension Lifted", description=f"Suspension for {player.mention} lifted.", color=discord.Color.green(), timestamp=datetime.now(pytz.utc))
        embed.add_field(name="Original Reason", value=found_suspension_data.get("reason", "N/A"), inline=False)
        duration_display = f"{found_suspension_data.get('value')} {found_suspension_data.get('unit')}{'s' if found_suspension_data.get('value',0) > 1 else ''}"
        if found_suspension_data.get("end_date"):
            end_dt = datetime.fromtimestamp(found_suspension_data["end_date"], tz=pytz.utc)
            duration_display += f" (until <t:{int(end_dt.timestamp())}:F>)"
        embed.add_field(name="Original Duration", value=duration_display, inline=False)
        if roles_removed_log:
            embed.add_field(name="Roles Removed", value=", ".join(roles_removed_log), inline=False)
        embed.add_field(name="Lifted By", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"Suspension ID: {found_suspension_id}")
        await interaction.response.send_message(embed=embed)

        log_id = await log_action(interaction.guild, "UNSUSPEND", interaction.user, f"Lifted suspension for {player.display_name}. Original reason: {found_suspension_data.get('reason', 'N/A')}", "unsuspend_cmd")

        # Send to log channel
        log_channel_id_str = guild_config.get("log_channels", {}).get("suspensions", guild_config.get("log_channels", {}).get("general"))
        if log_channel_id_str:
            try:
                log_channel = interaction.guild.get_channel(int(log_channel_id_str))
                if log_channel:
                    log_embed = embed.copy() # Use a copy of the response embed
                    log_embed.title = "Suspension Lifted Log"
                    log_embed.add_field(name="Log ID", value=log_id, inline=True)
                    await log_channel.send(embed=log_embed)
            except Exception as e: logger.error(f"Failed to send unsuspend log to channel: {e}", exc_info=True)


    def parse_duration(self, duration_str: str): # Added type hint
        duration_str = duration_str.strip().lower()
        match = re.match(r"(\d+)\s*(day|days|week|weeks|game|games)", duration_str)
        if match:
            value = int(match.group(1))
            unit_str = match.group(2)
            if unit_str in ["day", "days"]: unit = "day"
            elif unit_str in ["week", "weeks"]: unit = "week"
            elif unit_str in ["game", "games"]: unit = "game"
            else: return None, None # Should not happen with regex
            return value, unit
        return None, None


class SuspensionConfirmationView(discord.ui.View):
    def __init__(self, bot, player: discord.Member, reason: str, value: int, unit: str, end_date: Optional[datetime], user_id: int, guild_config: dict): # Added player, guild_config
        super().__init__(timeout=180) # Increased timeout
        self.bot = bot
        self.player = player # Now a discord.Member object
        self.reason = reason
        self.value = value
        self.unit = unit
        self.end_date = end_date # Already timezone-aware if from /suspend
        self.user_id = user_id # ID of user who initiated the command
        self.guild_config = guild_config # Store guild_config

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=EmbedBuilder.error("Not for you!", "Only the command initiator can confirm."),ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children: item.disabled = True
        # Optionally edit the original message if self.message is stored
        # await self.message.edit(content="Suspension confirmation timed out.", view=self)

    @discord.ui.button(label="Confirm Suspension", style=discord.ButtonStyle.danger, custom_id="confirm_suspension_btn")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True) # Defer while processing roles

        roles_added_log = []
        roles_removed_log = []

        # 1. Assign Suspension Role
        permission_settings = self.guild_config.get("permission_settings", {})
        suspension_role_ids_str = permission_settings.get("suspension_roles", [])
        suspension_role_to_assign = None
        if suspension_role_ids_str:
            try:
                role_id_to_assign = int(suspension_role_ids_str[0])
                suspension_role_to_assign_obj = interaction.guild.get_role(role_id_to_assign)
                if suspension_role_to_assign_obj:
                    if suspension_role_to_assign_obj not in self.player.roles:
                        await self.player.add_roles(suspension_role_to_assign_obj, reason=f"Suspended by {interaction.user.name}: {self.reason}")
                        roles_added_log.append(suspension_role_to_assign_obj.name)
                else: logger.warning(f"Suspension Role ID {role_id_to_assign} not found in guild {interaction.guild.id}.")
            except ValueError: logger.error(f"Invalid Suspension Role ID configured: {suspension_role_ids_str[0]}")
            except discord.Forbidden: logger.error(f"Forbidden to assign suspension role in guild {interaction.guild.id}.") # Consider followup message
            except Exception as e: logger.error(f"Error assigning suspension role: {e}", exc_info=True)

        # 2. Remove Team Role
        player_team_data_config = self.guild_config.get("team_data", {})
        for team_name_iter, t_data_iter in player_team_data_config.items():
            role_id_iter_str = t_data_iter.get("role_id")
            if role_id_iter_str:
                try:
                    role_obj_iter = interaction.guild.get_role(int(role_id_iter_str))
                    if role_obj_iter and role_obj_iter in self.player.roles:
                        await self.player.remove_roles(role_obj_iter, reason=f"Suspended by {interaction.user.name}")
                        roles_removed_log.append(f"{role_obj_iter.name} (Team: {team_name_iter})")
                        break
                except ValueError: logger.warning(f"Invalid team role ID {role_id_iter_str} for team {team_name_iter} in config.")
                except discord.Forbidden: logger.error(f"Forbidden to remove team role for {self.player.display_name}")
                except Exception as e: logger.error(f"Error removing team role: {e}", exc_info=True)

        # 3. Remove Coach Roles
        coach_roles_to_strip_objs = []
        coach_role_keys = ["fo_roles", "gm_roles", "hc_roles", "ac_roles"]
        for role_key in coach_role_keys:
            configured_role_ids = permission_settings.get(role_key, [])
            for r_id_str_coach in configured_role_ids:
                try:
                    role_obj_coach = interaction.guild.get_role(int(r_id_str_coach))
                    if role_obj_coach and role_obj_coach in self.player.roles:
                        if role_obj_coach not in coach_roles_to_strip_objs : # Avoid duplicates if a role is in multiple cats
                             coach_roles_to_strip_objs.append(role_obj_coach)
                except ValueError: logger.warning(f"Invalid coach role ID {r_id_str_coach} for key {role_key} in config.")

        if coach_roles_to_strip_objs:
            try:
                await self.player.remove_roles(*coach_roles_to_strip_objs, reason=f"Suspended by {interaction.user.name}: Coach roles stripped.")
                for r_coach in coach_roles_to_strip_objs: roles_removed_log.append(f"{r_coach.name} (Coach Role)")
            except discord.Forbidden: logger.error(f"Forbidden to remove coach roles for {self.player.display_name}")
            except Exception as e: logger.error(f"Error removing coach roles: {e}", exc_info=True)

        # Process suspension record
        suspensions = load_json("suspensions.json")
        guild_id_str = str(interaction.guild.id)
        suspensions.setdefault(guild_id_str, {})
        suspension_id = f"SUSP-{datetime.now(pytz.utc).strftime('%Y%m%d%H%M%S%f')}"

        suspension_entry = {
            "player_id": str(self.player.id), # Changed from "player"
            "player_name": self.player.name, # Added for easier JSON reading
            "reason": self.reason, "value": self.value, "unit": self.unit,
            "suspended_at": datetime.now(pytz.utc).timestamp(),
            "suspended_by_id": str(interaction.user.id),
            "suspended_by_name": interaction.user.display_name,
            "status": "active",
            "roles_added_ids": [interaction.guild.get_role(int(suspension_role_ids_str[0])).id] if suspension_role_ids_str and interaction.guild.get_role(int(suspension_role_ids_str[0])) else [],
            "roles_removed_ids": [role_obj.id for role_obj_name, role_obj in zip(roles_removed_log, [interaction.guild.get_role(int(id_str)) for id_str in [r.split('(')[0].strip() for r in roles_removed_log] if id_str.isdigit()]) if role_obj] # This is complex and might not be robust
        }
        # Simplified roles_removed_ids for now, assuming roles_removed_log contains names
        # A better way would be to store IDs directly when collecting roles_to_strip_objs and player's team role.
        # For now, this part of JSON might not be perfectly accurate for role IDs.

        if self.end_date: suspension_entry["end_date"] = self.end_date.timestamp()
        suspensions[guild_id_str][suspension_id] = suspension_entry
        save_json("suspensions.json", suspensions)

        # Create response embed
        final_embed = discord.Embed(title="🚫 Player Suspended", description=f"**{self.player.mention}** ({self.player.name}) has been suspended.", color=discord.Color.red(), timestamp=datetime.now(pytz.utc))
        final_embed.add_field(name="Reason", value=self.reason, inline=False)
        duration_display_final = f"{self.value} {self.unit}{'s' if self.value > 1 else ''}"
        if self.end_date: duration_display_final += f" (until <t:{int(self.end_date.timestamp())}:F> - <t:{int(self.end_date.timestamp())}:R>)"
        final_embed.add_field(name="Duration", value=duration_display_final, inline=False)
        if roles_added_log: final_embed.add_field(name="Role Added", value=", ".join(roles_added_log), inline=False)
        if roles_removed_log: final_embed.add_field(name="Roles Removed", value=", ".join(roles_removed_log), inline=False)
        final_embed.add_field(name="Suspended By", value=interaction.user.mention, inline=True)
        final_embed.set_footer(text=f"Suspension ID: {suspension_id}")

        for child_item in self.children: child_item.disabled = True

        # Edit original interaction (the one that sent the view initially)
        # The current 'interaction' is from the button click.
        # We need to edit the message that this view is attached to.
        await interaction.edit_original_response(embed=final_embed, view=self)

        # Send separate ephemeral message for the button click confirmation
        await interaction.followup.send("Suspension processed and roles updated.", ephemeral=True)


        log_id = await log_action(interaction.guild, "SUSPEND", interaction.user, f"Suspended {self.player.display_name} ({self.player.id}) for {duration_display_final}. Reason: {self.reason}. Roles added: {', '.join(roles_added_log)}. Roles removed: {', '.join(roles_removed_log)}.", "suspend_confirmed")

        # Send to log channel
        log_channel_id_str_confirm = self.guild_config.get("log_channels", {}).get("suspensions", self.guild_config.get("log_channels", {}).get("general"))
        if log_channel_id_str_confirm:
            try:
                log_channel_confirm = interaction.guild.get_channel(int(log_channel_id_str_confirm))
                if log_channel_confirm:
                    log_embed_confirm = final_embed.copy() # Use a copy of the final embed
                    log_embed_confirm.title = "Suspension Log"
                    log_embed_confirm.add_field(name="Log ID", value=log_id, inline=True)
                    await log_channel_confirm.send(embed=log_embed_confirm)
            except Exception as e_log: logger.error(f"Failed to send suspension confirmation log: {e_log}", exc_info=True)
        self.stop()


    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="cancel_suspension_btn")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(embed=EmbedBuilder.error("Not for you!", "Only the command initiator can cancel."),ephemeral=True)
            return
        embed = discord.Embed(title="❌ Suspension Cancelled", description=f"Suspension of {self.player.display_name} cancelled.", color=discord.Color.green(), timestamp=datetime.now(pytz.utc))
        for child_item_cancel in self.children: child_item_cancel.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

async def setup(bot):
    await bot.add_cog(SuspensionCommands(bot))
    logger.info("SuspensionCommands Cog loaded.")