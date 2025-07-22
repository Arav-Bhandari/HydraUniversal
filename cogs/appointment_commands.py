import discord
import logging
from discord import app_commands
from discord.ext import commands
from utils.config import get_server_config
from utils.logging import log_action
from utils.embeds import EmbedBuilder
from datetime import datetime
import re

logger = logging.getLogger("bot.appointments")

def get_emoji_url(emoji_str: str | None) -> str | None:
    """Extracts a usable URL from a custom emoji string."""
    if not emoji_str:
        return None
    match = re.match(r'<a?:[a-zA-Z0-9_]+:(\d+)>', emoji_str)
    if match:
        emoji_id = match.group(1)
        extension = "gif" if emoji_str.startswith("<a:") else "png"
        return f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}?size=128"
    return None


class AppointmentCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_member_team(self, member: discord.Member, config: dict) -> str | None:
        """Correctly and efficiently checks a member's roles to find their team."""
        team_roles = config.get("team_roles", {})
        member_role_ids = {role.id for role in member.roles}
        for team_name, role_id in team_roles.items():
            if int(role_id) in member_role_ids:
                return team_name
        return None

    async def _perform_appointment(self, interaction: discord.Interaction, user: discord.Member, team: str) -> str:
        """
        Core helper function to handle the full appointment process.
        Assigns Team + FO roles, removes candidate roles, and sends a styled DM.
        Returns a warning message string on DM failure, otherwise an empty string.
        """
        guild = interaction.guild
        config = get_server_config(guild.id)
        bot_member = guild.me

        # --- Pre-appointment validation ---
        # Get roles needed for validation first
        permission_settings = config.get("permission_settings", {})
        team_roles_config = config.get("team_roles", {})
        
        # Using the corrected configuration key "fo_roles"
        fo_role_ids = permission_settings.get("fo_roles", [])
        if not fo_role_ids:
            raise ValueError("The 'Franchise Owner' role is not configured.")
        fo_role = guild.get_role(int(fo_role_ids[0]))
        if not fo_role:
             raise ValueError("The main 'Franchise Owner' role could not be found in the server.")

        # NEW: Check if the user is already on a team.
        existing_team = await self.get_member_team(user, config)
        if existing_team:
            raise ValueError(f"{user.mention} is already assigned to the **{existing_team}**.")

        # NEW: Check if the destination team already has an owner.
        team_role_id = team_roles_config.get(team)
        if not team_role_id:
            raise ValueError(f"Configuration for team '{team}' not found.")
        team_role = guild.get_role(int(team_role_id))
        if not team_role:
            raise ValueError(f"The role for team '{team}' could not be found in the server.")

        for member in team_role.members:
            if fo_role in member.roles:
                raise ValueError(f"The **{team}** already has a Franchise Owner ({member.mention}). Disband or remove them first if you wish to make a change.")

        # --- Bot Permission & Role Hierarchy Checks ---
        if not bot_member.guild_permissions.manage_roles:
            raise ValueError("Bot lacks the 'Manage Roles' permission.")
        if team_role >= bot_member.top_role or fo_role >= bot_member.top_role:
            raise ValueError("Cannot assign roles that are higher than or equal to the bot's highest role.")

        # --- Get Candidate Roles to Remove ---
        candidate_role_ids = permission_settings.get("candidate_roles", [])
        candidate_roles_to_remove = [role for role_id in candidate_role_ids if (role := guild.get_role(int(role_id))) and role in user.roles]

        # --- Perform Role Operations ---
        await user.add_roles(team_role, fo_role, reason=f"Appointed as FO for {team} by {interaction.user.display_name}")
        if candidate_roles_to_remove:
            await user.remove_roles(*candidate_roles_to_remove, reason=f"Candidate role removed upon FO appointment.")

        # --- Send Styled DM Notification ---
        dm_warning_message = ""
        team_data = config.get("team_data", {}).get(team, {})
        team_emoji_str = team_data.get("emoji", "")
        emoji_url = get_emoji_url(team_emoji_str)
        dm_embed = discord.Embed(
            title="Congratulations on Your Appointment!",
            description=f"You have been appointed as the Franchise Owner for {team_emoji_str} **{team_role.name}**!\n\nIf you find any bugs or have ideas for improvement, join the Hydra Discord server and let us know!\nhttps://discord.gg/jcyP5qKKmp",
            color=team_role.color if team_role.color != discord.Color.default() else discord.Color.green(),
            timestamp=datetime.now()
        ).set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None).set_footer(text=f"Appointed by {interaction.user.display_name}")
        if emoji_url:
            dm_embed.set_thumbnail(url=emoji_url)
        try:
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            dm_warning_message = f"\n\n**Warning**: Could not send a DM to {user.mention}. Their DMs may be disabled."
        except discord.HTTPException as e:
            logger.error(f"Failed to send DM to {user.display_name} ({user.id}): {e}")
            dm_warning_message = f"\n\n**Warning**: An error occurred while trying to DM {user.mention}."

        # --- Log the action ---
        log_message = f"{user.mention} was appointed as Franchise Owner for {team_emoji_str} **{team}** by {interaction.user.mention}."
        await log_action(guild, "APPOINT_FO", interaction.user, log_message)
        return dm_warning_message

    @app_commands.command(name="appoint", description="Appoint a user as a Franchise Owner for a team.")
    @app_commands.describe(user="The user to appoint.", team="The team to appoint the user to.")
    @app_commands.checks.has_permissions(administrator=True)
    async def appoint(self, interaction: discord.Interaction, user: discord.Member, team: str):
        await interaction.response.defer(ephemeral=True)
        try:
            warning_message = await self._perform_appointment(interaction, user, team)
            success_description = f"{user.mention} has been successfully appointed as Franchise Owner of **{team}**."
            if warning_message:
                success_description += warning_message
            await interaction.followup.send(embed=EmbedBuilder.success("Appointment Successful", success_description), ephemeral=True)
        except ValueError as e:
            await interaction.followup.send(embed=EmbedBuilder.error("Appointment Failed", str(e)), ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.followup.send(embed=EmbedBuilder.error("Appointment Failed", f"A Discord API error occurred: {e}"), ephemeral=True)
        except Exception as e:
            logger.error(f"Unexpected error in /appoint command for guild {interaction.guild.id}: {e}", exc_info=True)
            await interaction.followup.send(embed=EmbedBuilder.error("An Unexpected Error Occurred", "Please check the bot's console for details."), ephemeral=True)

    @appoint.autocomplete("team")
    async def appoint_team_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        try:
            config = get_server_config(interaction.guild.id)
            team_roles = config.get("team_roles", {})
            # Also show teams that might not be in the text yet
            return [
                app_commands.Choice(name=team_name, value=team_name)
                for team_name in team_roles.keys() if current.lower() in team_name.lower()
            ][:25]
        except Exception as e:
            logger.error(f"Error in appoint_team_autocomplete: {e}")
            return []

    @app_commands.command(name="waitlist", description="Show a list of candidates waiting for a team.")
    @app_commands.checks.has_permissions(administrator=True)
    async def waitlist(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        config = get_server_config(guild.id)
        try:
            permission_settings = config.get("permission_settings", {})
            candidate_role_ids = permission_settings.get("candidate_roles", [])
            if not candidate_role_ids:
                raise ValueError("Candidate roles are not configured for this server.")
            candidates = {member for role_id in candidate_role_ids if (role := guild.get_role(int(role_id))) for member in role.members}
            if not candidates:
                embed = EmbedBuilder.info("Waitlist is Empty", "No users with the candidate role are currently waiting.")
            else:
                sorted_candidates = sorted(list(candidates), key=lambda m: m.display_name.lower())
                description = "\n".join(f"• {member.mention} (`{member.id}`)" for member in sorted_candidates)
                embed = discord.Embed(
                    title=f"👥 Candidate Waitlist ({len(sorted_candidates)} waiting)",
                    description=description, color=discord.Color.blue(), timestamp=datetime.now()
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except ValueError as e:
            await interaction.followup.send(embed=EmbedBuilder.error("Configuration Error", str(e)), ephemeral=True)
        except Exception as e:
            logger.error(f"Error in /waitlist: {e}", exc_info=True)
            await interaction.followup.send(embed=EmbedBuilder.error("An Unexpected Error Occurred", "Please check the logs."), ephemeral=True)

    @app_commands.command(name="appointall", description="Appoint candidates to teams without a Franchise Owner.")
    @app_commands.checks.has_permissions(administrator=True)
    async def appointall(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        config = get_server_config(guild.id)
        try:
            permission_settings = config.get("permission_settings", {})
            fo_role_ids = permission_settings.get("fo_roles", [])
            candidate_role_ids = permission_settings.get("candidate_roles", [])
            if not fo_role_ids or not candidate_role_ids:
                raise ValueError("Franchise Owner or Candidate roles are not configured.")
            fo_role = guild.get_role(int(fo_role_ids[0]))
            if not fo_role:
                raise ValueError("The main Franchise Owner role could not be found.")

            # Find teams without an FO
            all_teams = config.get("team_roles", {}).keys()
            teams_with_fo = {await self.get_member_team(member, config) for member in fo_role.members}
            open_teams = [team for team in all_teams if team and team not in teams_with_fo]
            if not open_teams:
                return await interaction.followup.send(embed=EmbedBuilder.success("All Teams Filled", "Every configured team already has a Franchise Owner."), ephemeral=True)

            # Get all candidates
            all_candidates = {member for role_id in candidate_role_ids if (role := guild.get_role(int(role_id))) for member in role.members}
            # Filter out anyone who is already an FO or on a team
            eligible_candidates = [c for c in all_candidates if fo_role not in c.roles and not await self.get_member_team(c, config)]
            if not eligible_candidates:
                return await interaction.followup.send(embed=EmbedBuilder.info("No Eligible Candidates", "There are candidates on the waitlist, but none are available or all teams are full."), ephemeral=True)

            # Perform appointments
            appointments_made = 0
            appointment_details = []
            for team_name in open_teams:
                if not eligible_candidates: break
                candidate = eligible_candidates.pop(0)
                try:
                    await self._perform_appointment(interaction, candidate, team_name)
                    appointments_made += 1
                    team_data = config.get("team_data", {}).get(team_name, {})
                    team_emoji = team_data.get("emoji", "•")
                    appointment_details.append(f"{team_emoji} **{team_name}** → {candidate.mention}")
                except Exception as e:
                    logger.error(f"Failed to auto-appoint to {team_name}: {e}")

            if appointments_made == 0:
                return await interaction.followup.send(embed=EmbedBuilder.error("No Appointments Made", "Could not appoint any candidates due to errors or lack of open spots."), ephemeral=True)
            
            embed = discord.Embed(
                title="✅ Mass Appointment Complete",
                description=f"Successfully appointed **{appointments_made}** new Franchise Owners:\n\n" + "\n".join(appointment_details),
                color=discord.Color.green(), timestamp=datetime.now()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except ValueError as e:
            await interaction.followup.send(embed=EmbedBuilder.error("Appointment Failed", str(e)), ephemeral=True)
        except Exception as e:
            logger.error(f"Unexpected error in /appointall: {e}", exc_info=True)
            await interaction.followup.send(embed=EmbedBuilder.error("An Unexpected Error Occurred", "Check the bot logs for more information."), ephemeral=True)

    @app_commands.command(name="disband", description="Disband a team, removing all associated roles.")
    @app_commands.describe(team="The team to disband.")
    @app_commands.checks.has_permissions(administrator=True)
    async def disband(self, interaction: discord.Interaction, team: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        config = get_server_config(guild.id)
        try:
            team_role_id = config.get("team_roles", {}).get(team)
            if not team_role_id or not (team_role := guild.get_role(int(team_role_id))):
                raise ValueError(f"The role for team '{team}' could not be found.")

            permission_settings = config.get("permission_settings", {})
            fo_role_ids = permission_settings.get("fo_roles", [])
            fo_role = guild.get_role(int(fo_role_ids[0])) if fo_role_ids else None

            affected_members = list(team_role.members)
            if not affected_members:
                return await interaction.followup.send(embed=EmbedBuilder.info("Team Already Empty", f"No members were found with the **{team_role.name}** role."), ephemeral=True)

            roles_to_remove = {team_role}
            if fo_role:
                roles_to_remove.add(fo_role)
            for member in affected_members:
                await member.remove_roles(*(r for r in roles_to_remove if r), reason=f"Team {team} disbanded by {interaction.user.display_name}")
            
            embed = discord.Embed(
                title="💣 Team Disbanded",
                description=f"**{team_role.name}** has been disbanded. All associated roles were removed from **{len(affected_members)}** member(s).",
                color=discord.Color.red(), timestamp=datetime.now()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            await log_action(guild, "DISBAND", interaction.user, f"Disbanded team **{team}**.")
        except ValueError as e:
            await interaction.followup.send(embed=EmbedBuilder.error("Disband Failed", str(e)), ephemeral=True)
        except Exception as e:
            logger.error(f"Error in /disband: {e}", exc_info=True)
            await interaction.followup.send(embed=EmbedBuilder.error("An Unexpected Error Occurred", "Please check the logs."), ephemeral=True)

    @disband.autocomplete("team")
    async def disband_team_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self.appoint_team_autocomplete(interaction, current)

    @appoint.error
    @waitlist.error
    @appointall.error
    @disband.error
    async def on_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Generic error handler for check failures."""
        if isinstance(error, app_commands.CheckFailure) or isinstance(error, app_commands.MissingPermissions):
            embed = EmbedBuilder.error("Permission Denied", "You do not have the required permissions to use this command.")
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            logger.error(f"An unhandled error occurred in AppointmentCommands: {error}", exc_info=True)


async def setup(bot):
    await bot.add_cog(AppointmentCommands(bot))