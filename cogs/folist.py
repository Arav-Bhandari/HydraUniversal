import discord
import logging
from discord import app_commands
from discord.ext import commands
from utils.config import get_server_config
from utils.permissions import can_use_command
from datetime import datetime

logger = logging.getLogger("bot.transactions")

class folist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="franchiselist", description="Display a list of all Franchise Owners and their teams")
    @app_commands.check(lambda inter: can_use_command(inter, "franchiselist"))
    async def franchiselist(self, interaction: discord.Interaction):
        """Display a list of all Franchise Owners and their teams in the owners channel"""
        guild = interaction.guild
        config = get_server_config(guild.id)

        # Get the owners channel from config
        owners_channel_id = config.get("log_channels", {}).get("owners")
        if not owners_channel_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Error",
                    description="Owners channel not configured. Please set it up using /setup or /setchannel.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        owners_channel = guild.get_channel(int(owners_channel_id))
        if not owners_channel:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Error",
                    description="Owners channel not found. Please check the configuration.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        try:
            # Get FO role IDs from config (note: it's fo_roles, not franchise_owner_role)
            fo_role_ids = config.get("permission_settings", {}).get("fo_roles", [])
            if not fo_role_ids:
                raise ValueError("Franchise Owner roles not configured in server settings")

            # Get roster cap from config
            team_data = config.get("team_data", {})
            default_roster_cap = config.get("roster_cap", 53)

            # Find all franchise owners and their team roles
            franchise_owners = []
            for team_name, team_info in team_data.items():
                team_role_id = team_info.get("role_id")
                if not team_role_id:
                    continue
                    
                team_role = guild.get_role(team_role_id)
                if not team_role:
                    continue
                
                # Find franchise owners for this team
                team_owners = []
                for member in guild.members:
                    if (team_role in member.roles and 
                        any(guild.get_role(fo_role_id) in member.roles for fo_role_id in fo_role_ids if guild.get_role(fo_role_id))):
                        team_owners.append(member)
                
                if team_owners:
                    team_emoji = team_info.get("emoji", "🏆")
                    roster_cap = team_info.get("roster_cap", default_roster_cap)
                    roster_count = len([m for m in guild.members if team_role in m.roles])
                    roster_status = f"{roster_count}/{roster_cap}"
                    if roster_count > roster_cap:
                        roster_status += " **(Over Cap!)**"
                    
                    owners_text = ", ".join([owner.mention for owner in team_owners])
                    franchise_owners.append((team_emoji, team_role.name, owners_text, roster_status))

            if not franchise_owners:
                embed = discord.Embed(
                    title="No Franchise Owners Found",
                    description="No users with the Franchise Owner role are currently assigned to teams.",
                    color=discord.Color.orange()
                )
            else:
                title = f"{guild.name} Franchise Owners"
                if guild.icon:
                    title = f"{guild.name} Franchise Owners"
                    embed = discord.Embed(
                        title=title,
                        description="**Franchise Owner List**",
                        color=discord.Color.blue()
                    )
                    embed.set_thumbnail(url=guild.icon.url)
                else:
                    embed = discord.Embed(
                        title=title,
                        description="**Franchise Owner List**",
                        color=discord.Color.blue()
                    )

                for team_emoji, team_role, owner, roster in franchise_owners:
                    embed.add_field(
                        name=f"{team_emoji} {team_role}",
                        value=f"{owner}\nRoster: {roster}",
                        inline=False
                    )

            # Set footer with timestamp
            embed.timestamp = datetime.now()
            embed.set_footer(text=f"Generated by {interaction.user.name}")

            # Send the embed to the owners channel
            await owners_channel.send(embed=embed)
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Success",
                    description="Franchise Owner list has been sent to the owners channel.",
                    color=discord.Color.green()
                ),
                ephemeral=True
            )

        except ValueError as ve:
            logger.error(f"ValueError in /franchiselist for guild {guild.id}: {ve}")
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Configuration Error",
                    description=str(ve),
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Unexpected error in /franchiselist for guild {guild.id}: {e}")
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Error",
                    description=f"An unexpected error occurred: {str(e)}",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )

    @franchiselist.error
    async def franchiselist_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            embed = discord.Embed(
                title="Permission Denied",
                description="You don't have permission to use this command.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            logger.error(f"Error in franchiselist command: {error}")
            embed = discord.Embed(
                title="Error",
                description=f"An error occurred: {error}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(folist(bot))