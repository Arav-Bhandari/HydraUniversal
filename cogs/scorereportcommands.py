import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from utils.config import get_server_config
from utils.permissions import can_use_command
from utils.logging import log_action

logger = logging.getLogger("bot.score_report")

class ScoreReportCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def channel_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete for channels including games log channels"""
        if not interaction.guild:
            return []
        
        config = get_server_config(interaction.guild.id)
        choices = []
        
        # Add games log channels
        games_channels = config.get("log_channels", {}).get("games", [])
        if isinstance(games_channels, int):
            games_channels = [games_channels]
        elif not isinstance(games_channels, list):
            games_channels = []
            
        for channel_id in games_channels:
            channel = interaction.guild.get_channel(channel_id)
            if channel and (not current or current.lower() in channel.name.lower()):
                choices.append(app_commands.Choice(name=f"#{channel.name} (Games Log)", value=str(channel.id)))
        
        # Add other text channels and threads
        for channel in interaction.guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                if not current or current.lower() in channel.name.lower():
                    if len(choices) < 25:  # Discord limit
                        channel_type = "Thread" if isinstance(channel, discord.Thread) else "Channel"
                        choices.append(app_commands.Choice(name=f"#{channel.name} ({channel_type})", value=str(channel.id)))
        
        return choices[:25]

    @app_commands.command(name="score_report", description="Report the score of a game with stat images")
    @app_commands.describe(
        team1="The first team",
        team2="The second team",
        score1="The score of team1",
        score2="The score of team2",
        stat_file_1="The first stat image (required)",
        stat_file_2="The second stat image (optional)",
        stat_file_3="The third stat image (optional)",
        stat_file_4="The fourth stat image (optional)",
        stat_file_5="The fifth stat image (optional)",
        stat_file_6="The sixth stat image (optional)",
        channel="Channel to send the report to (optional)"
    )
    @app_commands.autocomplete(channel=lambda self, interaction, current: self.channel_autocomplete(interaction, current))
    async def score_report(
        self,
        interaction: discord.Interaction,
        team1: str,
        team2: str,
        score1: int,
        score2: int,
        stat_file_1: discord.Attachment,
        stat_file_2: discord.Attachment = None,
        stat_file_3: discord.Attachment = None,
        stat_file_4: discord.Attachment = None,
        stat_file_5: discord.Attachment = None,
        stat_file_6: discord.Attachment = None,
        channel: str = None
    ):
        """Report the score of a game with stat images."""
        # Check permissions
        if not await can_use_command(interaction.user, "score_report"):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You don't have permission to use this command.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Validate inputs
        if score1 < 0 or score2 < 0:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Invalid Scores",
                    description="Scores cannot be negative.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if not stat_file_1.content_type.startswith("image/"):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Invalid Attachment",
                    description="The first stat file must be an image.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Collect all stat files
        stat_files = [stat_file_1]
        for stat_file in [stat_file_2, stat_file_3, stat_file_4, stat_file_5, stat_file_6]:
            if stat_file:
                if not stat_file.content_type.startswith("image/"):
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Invalid Attachment",
                            description=f"Stat file {stat_file.filename} must be an image.",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                    return
                stat_files.append(stat_file)

        if len(stat_files) > 6:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Too Many Attachments",
                    description="You can only upload up to 6 stat images.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Determine the winning team and fetch their emoji
        config = get_server_config(interaction.guild.id)
        winner_emoji = "🏆"  # Default for a win
        if score1 == score2:
            winner_emoji = "🤝"  # Tie emoji
        elif score1 > score2:
            winning_team = team1
        else:
            winning_team = team2

        # Fetch the winning team's emoji if not a tie
        if score1 != score2:
            team_data = config.get("team_data", {})
            if winning_team in team_data and "emoji" in team_data[winning_team]:
                winner_emoji = team_data[winning_team]["emoji"]
            else:
                logger.warning(f"No emoji found for team {winning_team} in guild {interaction.guild.id}")

        # Create the score report embed
        embed = discord.Embed(
            title="🏈 Game Score Report",
            description=f"**{team1}** vs **{team2}**\nScore: **{score1}** - **{score2}**",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Reported by", value=f"{interaction.user.mention} {winner_emoji}", inline=True)
        embed.add_field(name="Stat Images", value=f"{len(stat_files)} image(s) attached", inline=True)
        embed.set_footer(text=f"Game ID: GAME-{datetime.now().strftime('%Y%m%d%H%M%S')}")

        # Respond with the embed and attachments
        await interaction.response.send_message(embed=embed, files=[await f.to_file() for f in stat_files])

        # Log the action
        log_details = f"{team1} vs {team2}: {score1}-{score2}\nReported with {len(stat_files)} stat images."
        log_id = await log_action(
            interaction.guild,
            "SCORE_REPORT",
            interaction.user,
            log_details,
            "score_report"
        )

        # Send to specified channel or games log channels
        config = get_server_config(interaction.guild.id)
        target_channels = []
        
        if channel:
            # Send to specified channel
            target_channel = interaction.guild.get_channel(int(channel))
            if target_channel:
                target_channels.append(target_channel)
        else:
            # Send to games log channels
            games_channels = config.get("log_channels", {}).get("games", [])
            if isinstance(games_channels, int):
                games_channels = [games_channels]
            elif not isinstance(games_channels, list):
                games_channels = []
                
            for channel_id in games_channels:
                target_channel = interaction.guild.get_channel(channel_id)
                if target_channel:
                    target_channels.append(target_channel)
        
        # Send to target channels
        for target_channel in target_channels:
            try:
                if target_channel.permissions_for(interaction.guild.me).send_messages:
                    log_embed = embed.copy()
                    log_embed.add_field(name="Log ID", value=log_id, inline=True)
                    await target_channel.send(embed=log_embed, files=[await f.to_file() for f in stat_files])
            except Exception as e:
                logger.error(f"Failed to send score report to channel {target_channel.id} for guild {interaction.guild.id}: {e}")

        # Also send to transaction log channel if different from target channels
        if "log_channels" in config and "transactions" in config["log_channels"]:
            trans_channel_id = config["log_channels"]["transactions"]
            if trans_channel_id and trans_channel_id not in [ch.id for ch in target_channels]:
                try:
                    trans_channel = interaction.guild.get_channel(int(trans_channel_id))
                    if trans_channel:
                        log_embed = embed.copy()
                        log_embed.add_field(name="Log ID", value=log_id, inline=True)
                        await trans_channel.send(embed=log_embed, files=[await f.to_file() for f in stat_files])
                except Exception as e:
                    logger.error(f"Failed to send score report log for guild {interaction.guild.id}: {e}")

async def setup(bot):
    await bot.add_cog(ScoreReportCommands(bot))