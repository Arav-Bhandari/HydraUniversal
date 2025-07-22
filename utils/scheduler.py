import discord
import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from utils.config import get_server_config, load_json
from utils.embeds import EmbedBuilder

logger = logging.getLogger("bot.scheduler")

# Global scheduler instance
scheduler = AsyncIOScheduler()

async def setup_scheduler(bot):
    """Set up the scheduler with tasks"""
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")
    
    # Add scheduled tasks
    scheduler.add_job(
        check_upcoming_games,
        IntervalTrigger(minutes=15),  # Check every 15 minutes
        id="check_upcoming_games",
        replace_existing=True,
        args=[bot]
    )
    
    # Add more scheduled tasks here as needed
    logger.info("Scheduler jobs set up")

async def check_upcoming_games(bot):
    """Check for upcoming games and send reminders"""
    logger.info("Checking for upcoming games...")
    
    # Skip if bot is not fully ready
    if not bot.is_ready():
        logger.info("Bot not ready, skipping game reminder check")
        return
    
    try:
        # Load games data
        games = load_json("games.json")
        
        # Current time
        now = datetime.now()
        
        # Check each server's games
        for guild_id, guild_games in games.items():
            # Get the guild
            guild = bot.get_guild(int(guild_id))
            if not guild:
                continue
            
            # Get server config
            config = get_server_config(guild.id)
            notification_settings = config.get("notification_settings", {})
            
            # Check if game notifications are enabled
            if not notification_settings.get("game_reminders", True):
                continue
            
            # Get announcement channel
            announcement_channel_id = config.get("announcement_channels", {}).get("public")
            games_channel_id = config.get("log_channels", {}).get("games")
            
            # Determine which channel to use - prefer announcement channel but fall back to games log channel
            channel_id = announcement_channel_id or games_channel_id
            if not channel_id:
                logger.warning(f"No suitable notification channel found for guild {guild.id}")
                continue
                
            channel = guild.get_channel(int(channel_id))
            if not channel:
                logger.warning(f"Could not find channel {channel_id} in guild {guild.id}")
                continue
            
            # Get team roles configuration
            team_roles = config.get("team_roles", {})
            
            # Check each game
            for game_id, game_data in guild_games.items():
                # Skip games that have already been played
                if game_data.get("score1") is not None:
                    continue
                
                # Parse game time
                try:
                    game_time = datetime.fromisoformat(game_data.get("datetime"))
                    
                    # Check if game is within reminder thresholds
                    time_until_game = game_time - now
                    
                    # Get reminder flags
                    reminder_flags = game_data.get("reminders_sent", {})
                    if not isinstance(reminder_flags, dict):
                        reminder_flags = {}
                    
                    # Check each reminder threshold
                    # 48-hour reminder
                    if (timedelta(hours=47) < time_until_game <= timedelta(hours=48) and 
                        not reminder_flags.get("48h", False)):
                        await send_game_reminder(bot, guild, channel, game_data, game_id, "48 hours", "48h")
                    
                    # 24-hour reminder
                    elif (timedelta(hours=23) < time_until_game <= timedelta(hours=24) and 
                          not reminder_flags.get("24h", False)):
                        await send_game_reminder(bot, guild, channel, game_data, game_id, "24 hours", "24h")
                    
                    # 3-hour reminder
                    elif (timedelta(hours=2, minutes=55) < time_until_game <= timedelta(hours=3) and 
                          not reminder_flags.get("3h", False)):
                        await send_game_reminder(bot, guild, channel, game_data, game_id, "3 hours", "3h")
                    
                    # 1-hour reminder
                    elif (timedelta(minutes=55) < time_until_game <= timedelta(hours=1) and 
                          not reminder_flags.get("1h", False)):
                        await send_game_reminder(bot, guild, channel, game_data, game_id, "1 hour", "1h")
                    
                    # 30-minute reminder
                    elif (timedelta(minutes=25) < time_until_game <= timedelta(minutes=30) and 
                          not reminder_flags.get("30m", False)):
                        await send_game_reminder(bot, guild, channel, game_data, game_id, "30 minutes", "30m")
                    
                    # 10-minute "Starting Soon" reminder
                    elif (timedelta(minutes=5) < time_until_game <= timedelta(minutes=10) and 
                          not reminder_flags.get("10m", False)):
                        await send_game_reminder(bot, guild, channel, game_data, game_id, "10 minutes", "10m")
                        
                except Exception as e:
                    logger.error(f"Error processing game {game_id}: {e}")
                    continue
    
    except Exception as e:
        logger.error(f"Error checking upcoming games: {e}")

async def send_game_reminder(bot, guild, channel, game_data, game_id, time_text, reminder_key):
    """Send a game reminder to the announcement channel and team members
    
    Args:
        bot: The Discord bot instance
        guild: The guild/server where the game is scheduled
        channel: The channel to send the public reminder to
        game_data: The game data dictionary
        game_id: The unique game identifier
        time_text: Human-readable time until the game (e.g. "1 hour")
        reminder_key: Key to mark this specific reminder as sent in the game data (e.g. "1h")
    """
    try:
        team1 = game_data.get("team1", "Unknown Team")
        team2 = game_data.get("team2", "Unknown Team")
        game_time = datetime.fromisoformat(game_data.get("datetime"))
        stream_url = game_data.get("stream_url", "")
        
        # Get formatted timestamp for Discord
        unix_timestamp = int(game_time.timestamp())
        discord_timestamp = f"<t:{unix_timestamp}:F>"
        relative_timestamp = f"<t:{unix_timestamp}:R>"
        
        # Get server config for notification settings
        config = get_server_config(guild.id)
        notification_settings = config.get("notification_settings", {})
        
        # Create professional embed for channel notification using EmbedBuilder
        referee_id = game_data.get("referee_id")
        streamer_id = game_data.get("streamer_id")
        
        embed = EmbedBuilder.reminder(
            title="Game Reminder",
            time_text=time_text,
            team1=team1,
            team2=team2,
            game_time=relative_timestamp,
            stream_url=stream_url,
            type="channel"
        )
        
        # Add referee and streamer info if assigned
        if referee_id:
            embed.add_field(
                name="🧑‍⚖️ Referee",
                value=f"<@{referee_id}>",
                inline=True
            )
        
        if streamer_id:
            embed.add_field(
                name="🎥 Streamer",
                value=f"<@{streamer_id}>",
                inline=True
            )
        
        # Format game time in a more detailed field
        embed.add_field(
            name="📅 Exact Time",
            value=f"{discord_timestamp}",
            inline=False
        )
        
        # Add game ID to footer
        embed.set_footer(text=f"Hydra League Bot • Game ID: {game_id}", 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        
        # Get team roles
        team_roles = config.get("team_roles", {})
        team1_role_id = team_roles.get(team1)
        team2_role_id = team_roles.get(team2)
        
        # Add team mentions if they're configured as roles
        mentions = ""
        if team1_role_id:
            mentions += f"<@&{team1_role_id}> "
        if team2_role_id:
            mentions += f"<@&{team2_role_id}>"
        
        # Send channel reminder
        if notification_settings.get("channel_notifications", True):
            try:
                await channel.send(content=mentions if mentions else None, embed=embed)
                logger.info(f"Sent {time_text} channel reminder for game {game_id} in {guild.name}")
            except Exception as e:
                logger.error(f"Error sending channel reminder for game {game_id}: {e}")
        
        # Send DM reminders if enabled
        if notification_settings.get("dm_notifications", True):
            # Create professional DM embed using our EmbedBuilder
            dm_embed = EmbedBuilder.reminder(
                title="Game Reminder",
                time_text=time_text,
                team1=team1,
                team2=team2,
                game_time=relative_timestamp,
                stream_url=stream_url,
                type="player"
            )
            
            # Add server and exact time information
            dm_embed.add_field(
                name="📍 Server",
                value=f"{guild.name}",
                inline=True
            )
            
            dm_embed.add_field(
                name="📅 Exact Time",
                value=f"{discord_timestamp}",
                inline=True
            )
            
            # Add game ID to footer
            dm_embed.set_footer(text=f"Hydra League Bot • Game ID: {game_id}", 
                               icon_url="https://i.imgur.com/uZIlRnK.png")
            
            # Send DMs to team members based on team roles
            if team1_role_id:
                team1_role = guild.get_role(int(team1_role_id))
                if team1_role:
                    for member in team1_role.members:
                        try:
                            # Don't DM bots
                            if member.bot:
                                continue
                                
                            await member.send(embed=dm_embed)
                            logger.debug(f"Sent {time_text} DM reminder to {member.name} for game {game_id}")
                        except Exception as e:
                            logger.debug(f"Could not send DM to {member.name}: {e}")
            
            if team2_role_id:
                team2_role = guild.get_role(int(team2_role_id))
                if team2_role:
                    for member in team2_role.members:
                        try:
                            # Skip if already sent (player has both team roles)
                            if team1_role_id and member in guild.get_role(int(team1_role_id)).members:
                                continue
                            
                            # Don't DM bots
                            if member.bot:
                                continue
                                
                            await member.send(embed=dm_embed)
                            logger.debug(f"Sent {time_text} DM reminder to {member.name} for game {game_id}")
                        except Exception as e:
                            logger.debug(f"Could not send DM to {member.name}: {e}")
        
        # Send DMs to referee and streamer if assigned
        if notification_settings.get("staff_notifications", True):
            if referee_id:
                referee = guild.get_member(int(referee_id))
                if referee and not referee.bot:
                    # Create professional referee reminder embed
                    referee_embed = EmbedBuilder.reminder(
                        title="Referee Assignment",
                        time_text=time_text,
                        team1=team1,
                        team2=team2,
                        game_time=relative_timestamp,
                        stream_url=stream_url,
                        type="referee"
                    )
                    
                    # Add server and exact time information
                    referee_embed.add_field(
                        name="📍 Server",
                        value=f"{guild.name}",
                        inline=True
                    )
                    
                    referee_embed.add_field(
                        name="📅 Exact Time",
                        value=f"{discord_timestamp}",
                        inline=True
                    )
                    
                    # Add game ID to footer
                    referee_embed.set_footer(text=f"Hydra League Bot • Game ID: {game_id}", 
                                           icon_url="https://i.imgur.com/uZIlRnK.png")
                    
                    try:
                        await referee.send(embed=referee_embed)
                        logger.debug(f"Sent referee reminder to {referee.name} for game {game_id}")
                    except Exception as e:
                        logger.debug(f"Could not send DM to referee {referee.name}: {e}")
            
            if streamer_id:
                streamer = guild.get_member(int(streamer_id))
                if streamer and not streamer.bot:
                    # Create professional streamer reminder embed
                    streamer_embed = EmbedBuilder.reminder(
                        title="Streamer Assignment",
                        time_text=time_text,
                        team1=team1,
                        team2=team2,
                        game_time=relative_timestamp,
                        stream_url=stream_url,
                        type="streamer"
                    )
                    
                    # Add server and exact time information
                    streamer_embed.add_field(
                        name="📍 Server",
                        value=f"{guild.name}",
                        inline=True
                    )
                    
                    streamer_embed.add_field(
                        name="📅 Exact Time",
                        value=f"{discord_timestamp}",
                        inline=True
                    )
                    
                    # Add stream URL if available as a dedicated field
                    if stream_url:
                        streamer_embed.add_field(
                            name="📺 Your Stream URL",
                            value=f"{stream_url}",
                            inline=False
                        )
                    
                    # Add game ID to footer
                    streamer_embed.set_footer(text=f"Hydra League Bot • Game ID: {game_id}", 
                                           icon_url="https://i.imgur.com/uZIlRnK.png")
                    
                    try:
                        await streamer.send(embed=streamer_embed)
                        logger.debug(f"Sent streamer reminder to {streamer.name} for game {game_id}")
                    except Exception as e:
                        logger.debug(f"Could not send DM to streamer {streamer.name}: {e}")
        
        # Mark this specific reminder as sent by updating the game data
        games = load_json("games.json")
        if str(guild.id) in games and game_id in games[str(guild.id)]:
            # Initialize or update reminders_sent dictionary
            if "reminders_sent" not in games[str(guild.id)][game_id]:
                games[str(guild.id)][game_id]["reminders_sent"] = {}
            
            games[str(guild.id)][game_id]["reminders_sent"][reminder_key] = True
            
            # Save the updated games data
            with open(os.path.join("data", "games.json"), "w") as f:
                json.dump(games, f, indent=4)
        
        logger.info(f"Completed {time_text} reminders for game {game_id} in {guild.name}")
    
    except Exception as e:
        logger.error(f"Error sending game reminder: {e}")
        # Log the full traceback for debugging
        import traceback
        logger.error(traceback.format_exc())