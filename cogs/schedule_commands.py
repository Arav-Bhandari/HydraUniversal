import discord
import logging
from typing import Optional
from discord import app_commands
from discord.ext import commands
from utils.config import get_server_config
from utils.permissions import can_use_command
from utils.logging import log_action
from utils.embeds import EmbedBuilder

logger = logging.getLogger("bot.schedule_threads")

class ScheduleThreadCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def team_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete for registered team names"""
        config = get_server_config(interaction.guild_id)
        teams = config.get("team_data", {})
        team_choices = [
            app_commands.Choice(name=team_data["name"], value=team_data["name"])
            for team_id, team_data in teams.items()
            if current.lower() in team_data["name"].lower() or not current
        ]
        return team_choices[:25]  # Discord limit

    async def get_team_data(self, guild_id, team_name):
        """Get team data from configuration"""
        config = get_server_config(guild_id)
        for team_id, team_data in config.get("team_data", {}).items():
            if team_data["name"].lower() == team_name.lower():
                role_id = int(team_data.get("role_id", 0))
                team_role = None
                guild = self.bot.get_guild(guild_id)
                if guild and role_id > 0:
                    team_role = guild.get_role(role_id)
                if team_role:
                    return {
                        "id": team_id,
                        "name": team_data["name"],
                        "role": team_role,
                        "emoji": team_data.get("emoji", "🏆")
                    }
        return None

    @app_commands.command(name="schedulethread", description="Create a matchup thread for two teams")
    @app_commands.describe(
        team1="First team in the matchup",
        team2="Second team in the matchup",
        deadline="Optional deadline for the matchup"
    )
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete)
    async def schedulethread(
        self,
        interaction: discord.Interaction,
        team1: str,
        team2: str,
        deadline: Optional[str] = None
    ):
        from utils.permissions import is_admin, has_management_role
        
        if not (await is_admin(interaction.user) or await has_management_role(interaction.user)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You need admin or management permissions to assign awards.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Get team data
        team1_data = await self.get_team_data(interaction.guild_id, team1)
        team2_data = await self.get_team_data(interaction.guild_id, team2)

        # Check if both teams exist
        if not team1_data:
            embed = EmbedBuilder.error("Team Not Found", f"Team '{team1}' is not registered in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if not team2_data:
            embed = EmbedBuilder.error("Team Not Found", f"Team '{team2}' is not registered in the server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if team1_data["name"] == team2_data["name"]:
            embed = EmbedBuilder.error("Invalid Matchup", "A team cannot be matched against itself.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create thread
        await interaction.response.defer(ephemeral=False)
        try:
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Invalid Channel", "This command can only be used in text channels that support threads."),
                    ephemeral=True
                )
                return

            thread_name = f"📅 {team1_data['name']} vs {team2_data['name']}"
            thread = await interaction.channel.create_thread(
                name=thread_name,
                auto_archive_duration=10080,  # 7 days
                reason=f"Matchup thread created by {interaction.user}"
            )

            # Create embed
            embed = discord.Embed(
                title=f"{team1_data['emoji']} {team1_data['name']} vs {team2_data['name']} {team2_data['emoji']}",
                description="Please schedule your game.",
                color=discord.Color.blue()
            )
            if deadline:
                embed.add_field(name="Deadline", value=deadline, inline=False)

            # Send embed and ping
            thread_message = await thread.send(embed=embed)
            await thread.send(f"{team1_data['role'].mention} {team2_data['role'].mention}")

            # Response to user
            success_embed = discord.Embed(
                title="✅ Thread Created",
                description=f"Created matchup thread for {team1_data['name']} vs {team2_data['name']}",
                color=discord.Color.green()
            )
            success_embed.add_field(name="Thread", value=f"[Click to view]({thread_message.jump_url})")
            await interaction.followup.send(embed=success_embed)

        except Exception as e:
            logger.error(f"Error creating thread: {e}")
            await interaction.followup.send(
                embed=EmbedBuilder.error("Error Creating Thread", f"An error occurred while creating the thread: {str(e)}"),
                ephemeral=True
            )

    @app_commands.command(name="autoschedule", description="Automatically create matchup threads for multiple teams")
    @app_commands.describe(
        team1="First team",
        team2="Second team",
        team3="Third team (optional)",
        team4="Fourth team (optional)",
        team5="Fifth team (optional)",
        team6="Sixth team (optional)",
        team7="Seventh team (optional)",
        team8="Eighth team (optional)",
        deadline="Optional deadline for all matchups"
    )
    @app_commands.autocomplete(
        team1=team_autocomplete, team2=team_autocomplete, team3=team_autocomplete,
        team4=team_autocomplete, team5=team_autocomplete, team6=team_autocomplete,
        team7=team_autocomplete, team8=team_autocomplete
    )
    async def autoschedule(
        self,
        interaction: discord.Interaction,
        team1: str,
        team2: str,
        team3: Optional[str] = None,
        team4: Optional[str] = None,
        team5: Optional[str] = None,
        team6: Optional[str] = None,
        team7: Optional[str] = None,
        team8: Optional[str] = None,
        deadline: Optional[str] = None
    ):
        """Automatically create matchup threads for pairs of teams with a summary embed"""
        from utils.permissions import is_admin, has_management_role
        
        if not (await is_admin(interaction.user) or await has_management_role(interaction.user)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You need admin or management permissions to assign awards.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Collect provided teams
        teams = [team1, team2, team3, team4, team5, team6, team7, team8]
        teams = [t for t in teams if t is not None]

        # Check if number of teams is even and at least 2
        if len(teams) < 2 or len(teams) % 2 != 0:
            embed = EmbedBuilder.error("Invalid Number of Teams", "You must provide an even number of teams (at least 2).")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get team data
        team_data_list = []
        for team_name in teams:
            team_data = await self.get_team_data(interaction.guild_id, team_name)
            if not team_data:
                embed = EmbedBuilder.error("Team Not Found", f"Team '{team_name}' is not registered in the server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            team_data_list.append(team_data)

        # Create matchups
        matchups = [(team_data_list[i], team_data_list[i+1]) for i in range(0, len(team_data_list), 2)]

        # Create summary embed
        embed = discord.Embed(
            title="Automatic Matchups",
            description="\n".join(f"{team1['name']} vs {team2['name']}" for team1, team2 in matchups),
            color=discord.Color.blue()
        )
        if deadline:
            embed.add_field(name="Deadline", value=deadline, inline=False)

        # Send summary embed as response
        await interaction.response.send_message(embed=embed)

        # Create threads for each matchup
        for team1, team2 in matchups:
            thread_name = f"📅 {team1['name']} vs {team2['name']}"
            try:
                thread = await interaction.channel.create_thread(
                    name=thread_name,
                    auto_archive_duration=10080,  # 7 days
                    reason=f"Matchup thread created by {interaction.user}"
                )
                thread_embed = discord.Embed(
                    title=f"{team1['emoji']} {team1['name']} vs {team2['name']} {team2['emoji']}",
                    description="Please schedule your game.",
                    color=discord.Color.blue()
                )
                if deadline:
                    thread_embed.add_field(name="Deadline", value=deadline, inline=False)
                await thread.send(embed=thread_embed)
                await thread.send(f"{team1['role'].mention} {team2['role'].mention}")
            except Exception as e:
                logger.error(f"Error creating thread for {team1['name']} vs {team2['name']}: {e}")

                

    @app_commands.command(name="seriesthread", description="Create series threads for groups of teams")
    @app_commands.describe(
        group_size="Number of teams per group",
        team1="First team",
        team2="Second team",
        team3="Third team",
        team4="Fourth team (optional)",
        team5="Fifth team (optional)",
        team6="Sixth team (optional)",
        team7="Seventh team (optional)",
        team8="Eighth team (optional)",
        deadline="Optional deadline for the series"
    )
    @app_commands.autocomplete(
        team1=team_autocomplete, team2=team_autocomplete, team3=team_autocomplete,
        team4=team_autocomplete, team5=team_autocomplete, team6=team_autocomplete,
        team7=team_autocomplete, team8=team_autocomplete
    )
    async def seriesthread(
        self,
        interaction: discord.Interaction,
        group_size: int,
        team1: str,
        team2: str,
        team3: str,
        team4: Optional[str] = None,
        team5: Optional[str] = None,
        team6: Optional[str] = None,
        team7: Optional[str] = None,
        team8: Optional[str] = None,
        deadline: Optional[str] = None
    ):
        """Create series threads for groups of teams with a summary embed"""
        from utils.permissions import is_admin, has_management_role
        
        if not (await is_admin(interaction.user) or await has_management_role(interaction.user)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You need admin or management permissions to assign awards.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Collect provided teams
        teams = [team1, team2, team3, team4, team5, team6, team7, team8]
        teams = [t for t in teams if t is not None]

        # Check if number of teams is at least group_size
        if len(teams) < group_size:
            embed = EmbedBuilder.error("Not Enough Teams", f"You must provide at least {group_size} teams for the series.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get team data
        team_data_list = []
        for team_name in teams:
            team_data = await self.get_team_data(interaction.guild_id, team_name)
            if not team_data:
                embed = EmbedBuilder.error("Team Not Found", f"Team '{team_name}' is not registered in the server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            team_data_list.append(team_data)

        # Split into groups
        groups = [team_data_list[i:i + group_size] for i in range(0, len(team_data_list), group_size)]

        # Create summary embed
        embed = discord.Embed(
            title="Series Groups",
            description="\n".join(f"Group {i+1}: {', '.join(team['name'] for team in group)}" for i, group in enumerate(groups)),
            color=discord.Color.blue()
        )
        if deadline:
            embed.add_field(name="Deadline", value=deadline, inline=False)

        # Send summary embed as response
        await interaction.response.send_message(embed=embed)

        # Create threads for each group
        for i, group in enumerate(groups):
            group_name = f"Group {i+1}"
            thread_name = f"📅 Series: {group_name} - {', '.join(team['name'] for team in group)}"
            try:
                thread = await interaction.channel.create_thread(
                    name=thread_name,
                    auto_archive_duration=10080,  # 7 days
                    reason=f"Series thread created by {interaction.user}"
                )
                thread_embed = discord.Embed(
                    title=f"Series: {group_name}",
                    description=f"Teams: {', '.join(team['name'] for team in group)}",
                    color=discord.Color.blue()
                )
                if deadline:
                    thread_embed.add_field(name="Deadline", value=deadline, inline=False)
                await thread.send(embed=thread_embed)
                ping_message = " ".join(team["role"].mention for team in group)
                await thread.send(ping_message)
            except Exception as e:
                logger.error(f"Error creating thread for {group_name}: {e}")


    @app_commands.command(name="clearschedulingthreads", description="Clear all scheduling threads in this channel")
    async def clearschedulingthreads(self, interaction: discord.Interaction):
        from utils.permissions import is_admin, has_management_role
        
        if not (await is_admin(interaction.user) or await has_management_role(interaction.user)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You need admin or management permissions to assign awards.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            embed = EmbedBuilder.error("Invalid Channel", "This command can only be used in text channels.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Collect active and archived threads
        threads_to_delete = [t for t in channel.threads if t.name.startswith("📅")]
        async for thread in channel.archived_threads():
            if thread.name.startswith("📅"):
                threads_to_delete.append(thread)

        # Delete threads
        deleted_count = 0
        for thread in threads_to_delete:
            try:
                await thread.delete()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Error deleting thread {thread.name}: {e}")


        # Send confirmation
        embed = discord.Embed(
            title="✅ Scheduling Threads Cleared",
            description=f"Deleted {deleted_count} scheduling threads in this channel.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(ScheduleThreadCommands(bot))