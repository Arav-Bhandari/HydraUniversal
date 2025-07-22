import discord
import logging
import json
import os
import uuid
from datetime import datetime
from utils.config import get_server_config, load_json, save_json

logger = logging.getLogger("bot.logging")

# Ensure logs directory exists
if not os.path.exists("data/logs"):
    os.makedirs("data/logs")
    logger.info("Created logs directory")

# Action types
ACTION_TYPES = {
    "SETUP": "🔧 Setup",
    "SIGN": "✍️ Contract",
    "OFFER": "📝 Offer",
    "RESCIND": "❌ Rescind",
    "APPOINT": "👔 Appointment",
    "DEMOTE": "⬇️ Demotion",
    "DISBAND": "💣 Disband",
    "TRADE": "🔄 Trade",
    "GAME": "🏈 Game",
    "STREAM": "🎥 Stream",
    "SUSPEND": "🚫 Suspension",
    "UNSUSPEND": "✅ Unsuspend",
    "SCHEDULE": "📅 Schedule",
    "STATS": "📊 Stats",
    "DASHBOARD": "📈 Dashboard",
    "OTHER": "ℹ️ Other"
}

def generate_log_id():
    """Generate a unique ID for logging."""
    return str(uuid.uuid4())[:8]

async def log_action(guild, action_type, user, details, command_name=None):
    """Log an action to the appropriate channel and save to disk."""
    try:
        config = get_server_config(guild.id)
        log_id = generate_log_id()
        timestamp = datetime.now().isoformat()
        
        # Create log entry
        log_entry = {
            "log_id": log_id,
            "timestamp": timestamp,
            "action_type": action_type,
            "user_id": str(user.id),
            "user_name": str(user),
            "details": details,
            "command": command_name
        }
        
        # Save to disk
        logs = load_json("logs.json")
        if str(guild.id) not in logs:
            logs[str(guild.id)] = []
        
        logs[str(guild.id)].append(log_entry)
        save_json("logs.json", logs)
        
        # Send to log channel if configured
        if "log_channels" in config:
            log_channel_id = None
            
            # Find the appropriate log channel
            if action_type in ["SIGN", "OFFER", "RESCIND"]:
                log_channel_id = config["log_channels"].get("transactions")
            elif action_type in ["GAME", "SCHEDULE"]:
                log_channel_id = config["log_channels"].get("games")
            elif action_type in ["SUSPEND", "UNSUSPEND"]:
                log_channel_id = config["log_channels"].get("suspensions")
            else:
                log_channel_id = config["log_channels"].get("general")
            
            if log_channel_id:
                try:
                    channel = guild.get_channel(int(log_channel_id))
                    if channel:
                        # Create embed for log
                        embed = discord.Embed(
                            title=f"{ACTION_TYPES.get(action_type, 'Action')} | ID: {log_id}",
                            description=details,
                            color=get_color_for_action(action_type),
                            timestamp=datetime.now()
                        )
                        embed.set_footer(text=f"Executed by {user}")
                        await channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Failed to send log to channel: {e}")
        
        return log_id
    except Exception as e:
        logger.error(f"Failed to log action: {e}")
        return None

def get_color_for_action(action_type):
    """Get color for action type."""
    colors = {
        "SETUP": discord.Color.blue(),
        "SIGN": discord.Color.green(),
        "OFFER": discord.Color.gold(),
        "RESCIND": discord.Color.orange(),
        "APPOINT": discord.Color.purple(),
        "DEMOTE": discord.Color.from_rgb(128, 0, 128),  # Purple
        "DISBAND": discord.Color.red(),
        "TRADE": discord.Color.from_rgb(0, 255, 255),  # Cyan
        "GAME": discord.Color.from_rgb(0, 128, 0),  # Green
        "STREAM": discord.Color.from_rgb(255, 0, 255),  # Magenta
        "SUSPEND": discord.Color.red(),
        "UNSUSPEND": discord.Color.green(),
        "SCHEDULE": discord.Color.blue(),
        "STATS": discord.Color.from_rgb(255, 165, 0),  # Orange
        "DASHBOARD": discord.Color.from_rgb(75, 0, 130),  # Indigo
        "OTHER": discord.Color.light_grey()
    }
    return colors.get(action_type, discord.Color.default())

async def find_log_by_id(guild_id, log_id):
    """Find a log entry by its ID."""
    logs = load_json("logs.json")
    guild_logs = logs.get(str(guild_id), [])
    
    for log in guild_logs:
        if log.get("log_id") == log_id:
            return log
    
    return None

async def get_recent_logs(guild_id, limit=10, action_type=None):
    """Get recent logs, optionally filtered by action type."""
    logs = load_json("logs.json")
    guild_logs = logs.get(str(guild_id), [])
    
    # Sort by timestamp (newest first)
    guild_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    # Filter by action type if provided
    if action_type:
        guild_logs = [log for log in guild_logs if log.get("action_type") == action_type]
    
    return guild_logs[:limit]
