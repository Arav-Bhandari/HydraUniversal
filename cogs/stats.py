import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import logging
import json
import os
import csv
import io
from datetime import datetime, timezone
from typing import List, Dict, Optional, Union
import uuid

# --- Utility Imports ---
try:
    from utils.config import (
        get_server_config,
        update_server_config,
        save_guild_config,
        get_default_config
    )
    from utils.permissions import is_admin, has_statistician_role
    from utils.logging import log_action
except ImportError as e:
    print(f"Warning: Could not import utility module: {e}. Ensure utils directory is structured correctly.")
    async def log_action(*args, **kwargs): pass
    async def has_statistician_role(ctx): return False
    async def is_admin(user): return False
    async def get_server_config(guild_id): return {}
    async def update_server_config(guild_id, config): pass
    async def save_guild_config(): pass
    def get_default_config(): return {}

logger = logging.getLogger("bot.stats")

# --- Game Type Configuration ---
GAME_TYPES = {
    "7v7": {
        "categories": ["QB", "WR", "CB", "DE"],
        "stat_templates": {
            "QB": {"comp": 0, "att": 0, "yards": 0, "tds": 0, "ints": 0, "sacks": 0, "comp_pct": 0.0, "int_pct": 0.0, "qbr": 0.0},
            "WR": {"catches": 0, "targets": 0, "tds": 0, "yac": 0, "yards": 0, "catch_pct": 0.0, "ypc": 0.0},
            "CB": {"ints": 0, "targets": 0, "swats": 0, "tds": 0, "comp_allowed": 0, "deny_pct": 0.0, "comp_pct": 0.0},
            "DE": {"tackles": 0, "misses": 0, "sacks": 0, "safeties": 0}
        },
        "leaderboard_sort_keys": {"QB": "qbr", "WR": "yards", "CB": "deny_pct", "DE": "sacks"},
        "display_names": {
            "QB": "Quarterback", "WR": "Wide Receiver", "CB": "Cornerback", "DE": "Defensive End"
        },
        "add_stat_params": {
            "QB": ["player", "comp", "att", "yards", "tds", "ints", "sacks"],
            "WR": ["player", "catches", "targets", "tds", "yac", "yards"],
            "CB": ["player", "ints", "targets", "swats", "tds", "comp_allowed"],
            "DE": ["player", "tackles", "misses", "sacks", "safeties"]
        },
        "derived_stats": {
            "QB": ["qbr", "comp_pct", "int_pct"],
            "WR": ["catch_pct", "ypc"],
            "CB": ["deny_pct", "comp_pct"],
            "DE": []
        },
        "legendary_players": {
            "TheZypherious": {
                "QB": {"qbr": 158.3, "comp": 400, "att": 500, "comp_pct": 80.0, "yards": 5000, "tds": 50, "ints": 2, "sacks": 5, "int_pct": 0.4},
                "WR": {"catches": 150, "targets": 180, "tds": 20, "yac": 1000, "yards": 2000, "catch_pct": 83.3, "ypc": 13.3},
                "CB": {"ints": 15, "targets": 100, "swats": 30, "tds": 5, "comp_allowed": 20, "deny_pct": 80.0, "comp_pct": 20.0},
                "DE": {"tackles": 100, "misses": 5, "sacks": 20, "safeties": 3}
            }
        }
    },
    "11v11": {
        "categories": ["QB", "RB", "WR", "CB", "LB", "DE"],
        "stat_templates": {
            "QB": {"comp": 0, "att": 0, "yards": 0, "tds": 0, "ints": 0, "sacks": 0, "comp_pct": 0.0, "int_pct": 0.0, "qbr": 0.0},
            "RB": {"rushes": 0, "yards": 0, "tds": 0, "fumbles": 0, "ypr": 0.0},
            "WR": {"catches": 0, "targets": 0, "tds": 0, "yac": 0, "yards": 0, "catch_pct": 0.0, "ypc": 0.0},
            "CB": {"ints": 0, "targets": 0, "swats": 0, "tds": 0, "comp_allowed": 0, "deny_pct": 0.0, "comp_pct": 0.0},
            "LB": {"tackles": 0, "misses": 0, "sacks": 0, "ints": 0},
            "DE": {"tackles": 0, "misses": 0, "sacks": 0, "safeties": 0}
        },
        "leaderboard_sort_keys": {"QB": "qbr", "RB": "yards", "WR": "yards", "CB": "deny_pct", "LB": "tackles", "DE": "sacks"},
        "display_names": {
            "QB": "Quarterback", "RB": "Running Back", "WR": "Wide Receiver",
            "CB": "Cornerback", "LB": "Linebacker", "DE": "Defensive End"
        },
        "add_stat_params": {
            "QB": ["player", "comp", "att", "yards", "tds", "ints", "sacks"],
            "RB": ["player", "rushes", "yards", "tds", "fumbles"],
            "WR": ["player", "catches", "targets", "tds", "yac", "yards"],
            "CB": ["player", "ints", "targets", "swats", "tds", "comp_allowed"],
            "LB": ["player", "tackles", "misses", "sacks", "ints"],
            "DE": ["player", "tackles", "misses", "sacks", "safeties"]
        },
        "derived_stats": {
            "QB": ["qbr", "comp_pct", "int_pct"],
            "RB": ["ypr"],
            "WR": ["catch_pct", "ypc"],
            "CB": ["deny_pct", "comp_pct"],
            "LB": [],
            "DE": []
        },
        "legendary_players": {}
    },
    "baseball": {
        "categories": ["P", "B"],
        "stat_templates": {
            "P": {"innings": 0.0, "strikeouts": 0, "walks": 0, "hits": 0, "runs": 0, "era": 0.0, "whip": 0.0},
            "B": {"at_bats": 0, "hits": 0, "home_runs": 0, "rbis": 0, "stolen_bases": 0, "avg": 0.0}
        },
        "leaderboard_sort_keys": {"P": "era", "B": "avg"},
        "display_names": {
            "P": "Pitcher", "B": "Batter"
        },
        "add_stat_params": {
            "P": ["player", "innings", "strikeouts", "walks", "hits", "runs"],
            "B": ["player", "at_bats", "hits", "home_runs", "rbis", "stolen_bases"]
        },
        "derived_stats": {
            "P": ["era", "whip"],
            "B": ["avg"]
        },
        "legendary_players": {}
    },
    "soccer": {
        "categories": ["ST", "MF", "GK"],
        "stat_templates": {
            "ST": {"goals": 0, "shots": 0, "assists": 0, "shots_on_target": 0, "goal_pct": 0.0},
            "MF": {"passes": 0, "completions": 0, "assists": 0, "tackles": 0, "goals": 0, "pass_pct": 0.0},
            "GK": {"saves": 0, "shots_faced": 0, "goals_allowed": 0, "clean_sheets": 0, "save_pct": 0.0}
        },
        "leaderboard_sort_keys": {
            "ST": "goals",
            "MF": "assists",
            "GK": "save_pct"
        },
        "display_names": {
            "ST": "Striker",
            "MF": "Midfielder",
            "GK": "Goalkeeper"
        },
        "add_stat_params": {
            "ST": ["player", "goals", "shots", "assists", "shots_on_target"],
            "MF": ["player", "passes", "completions", "assists", "tackles", "goals"],
            "GK": ["player", "saves", "shots_faced", "goals_allowed", "clean_sheets"]
        },
        "derived_stats": {
            "ST": ["goal_pct"],
            "MF": ["pass_pct"],
            "GK": ["save_pct"]
        },
        "legendary_players": {}
    }
}

# --- Stat Key Display Names ---
STAT_KEY_DISPLAY_NAMES = {
    "comp": "Completions", "att": "Attempts", "yards": "Yards", "tds": "Touchdowns",
    "ints": "Interceptions", "sacks": "Sacks", "comp_pct": "Completion %",
    "int_pct": "Interception %", "qbr": "QBR", "catches": "Catches",
    "targets": "Targets", "yac": "Yards After Catch", "catch_pct": "Catch %",
    "ypc": "Yards Per Catch", "swats": "Pass Breakups",
    "comp_allowed": "Completions Allowed", "deny_pct": "Deny %", "tackles": "Tackles",
    "misses": "Missed Tackles", "safeties": "Safeties", "rushes": "Rushes",
    "fumbles": "Fumbles", "ypr": "Yards Per Rush", "innings": "Innings Pitched",
    "strikeouts": "Strikeouts", "walks": "Walks", "hits": "Hits", "runs": "Runs",
    "era": "ERA", "whip": "WHIP", "at_bats": "At-Bats", "home_runs": "Home Runs",
    "rbis": "RBIs", "stolen_bases": "Stolen Bases", "avg": "Batting Average",
    "goals": "Goals", "shots": "Shots", "assists": "Assists",
    "shots_on_target": "Shots on Target", "goal_pct": "Goal %",
    "passes": "Passes", "completions": "Pass Completions", "pass_pct": "Pass %",
    "saves": "Saves", "shots_faced": "Shots Faced", "goals_allowed": "Goals Allowed",
    "clean_sheets": "Clean Sheets", "save_pct": "Save %"
}

# --- Constants and File Paths ---
def get_stat_file_path(game_type, category):
    """Generate file path for game-type-specific stat files."""
    return f"data/{game_type.lower()}_{category.lower()}_stats.json"

# Ensure data directory and stat files exist
os.makedirs("data", exist_ok=True)
for game_type, config in GAME_TYPES.items():
    for category in config["categories"]:
        file_path = get_stat_file_path(game_type, category)
        if not os.path.exists(file_path):
            try:
                with open(file_path, "w") as f:
                    json.dump({}, f, indent=4)
                logger.info(f"Created empty stat file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to create stat file {file_path}: {e}")

json_lock = asyncio.Lock()

# --- Helper Functions ---
def safe_int(value, default=0):
    """Safely convert value to integer."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        if isinstance(value, str) and "%" in value:
            try:
                return int(float(value.strip("%")))
            except (ValueError, TypeError):
                return default
        return default

def format_float(value, decimal_places=2, default=0.0):
    """Format float with specified decimal places."""
    if value is None or not isinstance(value, (int, float)) or value != value or value in (float('inf'), float('-inf')):
        return f"{default:.{decimal_places}f}"
    try:
        return f"{float(value):.{decimal_places}f}"
    except (ValueError, TypeError):
        return f"{default:.{decimal_places}f}"

def format_percentage(value, default=0.0):
    """Format float as percentage."""
    if value is None or not isinstance(value, (int, float)) or value != value or value in (float('inf'), float('-inf')):
        return f"{default:.2f}%"
    try:
        numeric_value = float(value)
        clamped_value = max(0.0, min(100.0, numeric_value))
        return f"{clamped_value:.2f}%"
    except (ValueError, TypeError):
        return f"{default:.2f}%"

def calculate_qbr(comp, att, yards, tds, ints):
    """Calculate NFL Passer Rating."""
    if att <= 0:
        return 0.0
    try:
        comp, att, yards, tds, ints = safe_int(comp), safe_int(att), safe_int(yards), safe_int(tds), safe_int(ints)
        a = max(0, min(2.375, ((comp / att * 100) - 30) / 20))
        b = max(0, min(2.375, ((yards / att) - 3) / 4))
        c = max(0, min(2.375, (tds / att) * 20))
        d = max(0, min(2.375, 2.375 - ((ints / att) * 25)))
        rating = ((a + b + c + d) / 6) * 100
        return max(0.0, rating)
    except Exception as e:
        logger.error(f"Error calculating QBR: {e}")
        return 0.0

def calculate_baseball_era(runs, innings):
    """Calculate Earned Run Average."""
    if innings <= 0:
        return 0.0
    try:
        return (safe_int(runs) * 9) / float(innings)
    except Exception as e:
        logger.error(f"Error calculating ERA: {e}")
        return 0.0

def calculate_baseball_avg(hits, at_bats):
    """Calculate Batting Average."""
    if at_bats <= 0:
        return 0.0
    try:
        return safe_int(hits) / safe_int(at_bats)
    except Exception as e:
        logger.error(f"Error calculating AVG: {e}")
        return 0.0

def calculate_whip(walks, hits, innings):
    """Calculate WHIP."""
    if innings <= 0:
        return 0.0
    try:
        return (safe_int(walks) + safe_int(hits)) / float(innings)
    except Exception as e:
        logger.error(f"Error calculating WHIP: {e}")
        return 0.0

def calculate_goal_pct(goals, shots):
    """Calculate Soccer Goal Percentage."""
    if shots <= 0:
        return 0.0
    try:
        return (safe_int(goals) / safe_int(shots)) * 100
    except Exception as e:
        logger.error(f"Error calculating goal_pct: {e}")
        return 0.0

def calculate_pass_pct(passes, completions):
    """Calculate Soccer Pass Percentage."""
    if passes <= 0:
        return 0.0
    try:
        return (safe_int(completions) / safe_int(passes)) * 100
    except Exception as e:
        logger.error(f"Error calculating pass_pct: {e}")
        return 0.0

async def load_stats(file_path):
    """Load statistics from JSON file."""
    async with json_lock:
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Stat file not found: {file_path}. Creating empty.")
            with open(file_path, "w") as f:
                json.dump({}, f, indent=4)
            return {}
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in stat file: {file_path}")
            return {}
        except Exception as e:
            logger.error(f"Failed to load stats from {file_path}: {e}")
            return {}

async def save_stats(file_path, data):
    """Save statistics to JSON file."""
    async with json_lock:
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save stats to {file_path}: {e}")

async def update_stat_entry(file_path, guild_id, player, stats_to_add, derived_stat_keys, game_type, category):
    """Update player stats with derived calculations."""
    stats_data = await load_stats(file_path)
    guild_id_str = str(guild_id)

    if guild_id_str not in stats_data:
        stats_data[guild_id_str] = {"Stats": {}}
    if "Stats" not in stats_data[guild_id_str]:
        stats_data[guild_id_str]["Stats"] = {}

    if player not in stats_data[guild_id_str]["Stats"]:
        stats_data[guild_id_str]["Stats"][player] = GAME_TYPES[game_type]["stat_templates"].get(category, {}).copy()

    player_stats = stats_data[guild_id_str]["Stats"][player]

    for key, value in stats_to_add.items():
        player_stats[key] = player_stats.get(key, 0) + safe_int(value)

    for key in derived_stat_keys:
        if key == "qbr":
            att = player_stats.get("att", 0)
            player_stats[key] = calculate_qbr(
                player_stats.get("comp", 0), att, player_stats.get("yards", 0),
                player_stats.get("tds", 0), player_stats.get("ints", 0)
            ) if att > 0 else 0.0
        elif key in ["comp_pct", "catch_pct"]:
            total = player_stats.get("att" if game_type in ["7v7", "11v11"] and category == "QB" else "targets", 0)
            if total > 0:
                if game_type in ["7v7", "11v11"] and category == "QB":
                    player_stats[key] = (player_stats.get("comp", 0) / total * 100)
                elif game_type in ["7v7", "11v11"] and category in ["WR", "CB"]:
                    player_stats[key] = (player_stats.get("catches" if category == "WR" else "comp_allowed", 0) / total * 100)
                else:
                    player_stats[key] = 0.0
        elif key == "int_pct":
            att = player_stats.get("att", 0)
            player_stats[key] = (player_stats.get("ints", 0) / att * 100) if att > 0 else 0.0
        elif key == "ypc":
            catches = player_stats.get("catches", 0)
            player_stats[key] = (player_stats.get("yards", 0) / catches) if catches > 0 else 0.0
        elif key == "deny_pct":
            player_stats[key] = (100.0 - player_stats.get("comp_pct", 0.0)) if player_stats.get("targets", 0) > 0 else 0.0
        elif key == "ypr":
            rushes = player_stats.get("rushes", 0)
            player_stats[key] = (player_stats.get("yards", 0) / rushes) if rushes > 0 else 0.0
        elif key == "era":
            player_stats[key] = calculate_baseball_era(player_stats.get("runs", 0), player_stats.get("innings", 0))
        elif key == "whip":
            player_stats[key] = calculate_whip(
                player_stats.get("walks", 0), player_stats.get("hits", 0), player_stats.get("innings", 0)
            )
        elif key == "avg":
            player_stats[key] = calculate_baseball_avg(player_stats.get("hits", 0), player_stats.get("at_bats", 0))
        elif key == "goal_pct":
            player_stats[key] = calculate_goal_pct(player_stats.get("goals", 0), player_stats.get("shots", 0))
        elif key == "pass_pct":
            player_stats[key] = calculate_pass_pct(player_stats.get("passes", 0), player_stats.get("completions", 0))

    await save_stats(file_path, stats_data)
    return player_stats

# --- Stats Cog ---
class Stats(commands.Cog):
    """A cog for managing game statistics with game-type-specific commands."""
    def __init__(self, bot):
        self.bot = bot
        self.stat_key_display_names = STAT_KEY_DISPLAY_NAMES
        self.game_types = GAME_TYPES

    async def cog_check(self, ctx):
        """Check for Statistician role."""
        # Get the member object properly
        if hasattr(ctx, 'user'):
            member = ctx.guild.get_member(ctx.user.id) if ctx.guild else None
        elif hasattr(ctx, 'author'):
            member = ctx.author if hasattr(ctx.author, 'roles') else ctx.guild.get_member(ctx.author.id)
        else:
            return False
            
        if not member or not await has_statistician_role(member):
            embed = self.create_enhanced_embed(
                "🚫 Access Denied",
                "Only users with the **Statistician** role can use these commands.\n\nContact an administrator to get the required role.",
                discord.Color.red(),
                ctx
            )
            if hasattr(ctx, 'response'):
                await ctx.response.send_message(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, ephemeral=True)
            return False
        return True

    def create_beautiful_embed(self, ctx, title, description, color):
        """Create a styled embed."""
        embed = discord.Embed(
            title=f"{self.get_title_emoji(title)} {title}",
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        guild_name = "Unknown Server"
        requestor_name = "Unknown User"
        requestor_avatar_url = None

        if hasattr(ctx, 'guild') and ctx.guild:
            guild_name = ctx.guild.name
            if ctx.guild.icon:
                embed.set_thumbnail(url=ctx.guild.icon.url)

        if hasattr(ctx, 'user'):
            requestor_name = ctx.user.display_name
            requestor_avatar_url = ctx.user.avatar.url if ctx.user.avatar else None
        elif hasattr(ctx, 'author'):
            requestor_name = ctx.author.display_name
            requestor_avatar_url = ctx.author.avatar.url if ctx.author.avatar else None

        footer_parts = [guild_name] if guild_name != "Unknown Server" else []
        if requestor_name != "Unknown User":
            footer_parts.append(f"Requested by {requestor_name}")
        footer_text = " • ".join(footer_parts)
        if footer_text:
            embed.set_footer(text=footer_text, icon_url=requestor_avatar_url)
        return embed

    def create_enhanced_embed(self, title, description, color, interaction):
        """Create an enhanced styled embed with better visual design."""
        # Add decorative elements to description
        if description and not description.startswith("━"):
            description = f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{description}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        embed = discord.Embed(
            title=f"{self.get_title_emoji(title)} {title}",
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Set thumbnail based on guild icon
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        # Enhanced footer with better formatting
        guild_name = interaction.guild.name if interaction.guild else "Unknown Server"
        requestor_name = interaction.user.display_name if interaction.user else "Unknown User"
        requestor_avatar = interaction.user.avatar.url if interaction.user and interaction.user.avatar else None
        
        footer_text = f"🏟️ {guild_name} • 👤 Requested by {requestor_name}"
        embed.set_footer(text=footer_text, icon_url=requestor_avatar)
        
        return embed

    def get_title_emoji(self, title):
        """Return emoji for embed title."""
        title_lower = title.lower()
        if "updated" in title_lower or "merged" in title_lower:
            return "✨"
        if "leaderboard" in title_lower:
            return "🏆"
        if "view" in title_lower or "stats for" in title_lower:
            return "📄"
        if "cleared" in title_lower:
            return "🧹"
        if "exported" in title_lower:
            return "📤"
        if "denied" in title_lower or "error" in title_lower:
            return "🚫"
        if "invalid" in title_lower or "warning" in title_lower:
            return "⚠️"
        if "config" in title_lower:
            return "⚙️"
        return "📊"

    def format_player_stats_for_embed(self, game_type, category, player_stats):
        """Format player stats for embed display."""
        fields = []
        config = self.game_types.get(game_type, {})
        stat_template = config.get("stat_templates", {}).get(category, {})
        display_names = self.stat_key_display_names

        primary_stats = []
        secondary_stats = []

        for key, value in player_stats.items():
            display_name = display_names.get(key, key.replace("_", " ").title())
            if key in config.get("derived_stats", {}).get(category, []):
                if key in ["qbr", "ypc", "era", "whip", "avg", "goal_pct", "pass_pct"]:
                    formatted_value = format_float(value, 2)
                else:
                    formatted_value = format_percentage(value)
            else:
                formatted_value = str(value)
            stat_line = f"**{display_name}**: {formatted_value}"
            if key in ["comp", "att", "catches", "targets", "rushes", "innings", "at_bats", "shots", "passes"]:
                primary_stats.append(stat_line)
            else:
                secondary_stats.append(stat_line)

        if primary_stats:
            fields.append(("Key Metrics", "\n".join(primary_stats), True))
        if secondary_stats:
            fields.append(("Additional Stats", "\n".join(secondary_stats), True))

        return fields

    async def register_commands_for_guild(self, guild_id):
        """Register commands for a specific guild based on its game type."""
        config = get_server_config(guild_id)
        game_type = config.get("game_type", "7v7")  # Default to 7v7 if not set
        if game_type not in self.game_types:
            logger.warning(f"Invalid game type {game_type} for guild {guild_id}. Using default.")
            game_type = "7v7"

        guild = discord.Object(id=guild_id)
        try:
            self.bot.tree.clear_commands(guild=guild)
        except Exception as e:
            logger.warning(f"Could not clear commands for guild {guild_id}: {e}")

        game_config = self.game_types.get(game_type, self.game_types["7v7"])

        # Register statview and statleaderboard
        self.bot.tree.add_command(self.statview, guild=guild)
        self.bot.tree.add_command(self.statleaderboard, guild=guild)

        # Register admin commands
        self.bot.tree.add_command(self.statmerge, guild=guild)
        self.bot.tree.add_command(self.statclear, guild=guild)
        self.bot.tree.add_command(self.statexport, guild=guild)
        self.bot.tree.add_command(self.stat_config, guild=guild)

        # Add static position-specific commands
        self._register_position_commands(guild, game_type)

        try:
            await self.bot.tree.sync(guild=guild)
            logger.info(f"Commands synced for guild {guild_id} with game type {game_type}")
        except Exception as e:
            logger.error(f"Failed to sync commands for guild {guild_id}: {e}")

    def _register_position_commands(self, guild, game_type):
        """Register position-specific stat commands."""
        game_config = self.game_types.get(game_type, self.game_types["7v7"])
        
        for category in game_config["categories"]:
            if category == "QB":
                self.bot.tree.add_command(self.add_qb_stats, guild=guild)
            elif category == "WR":
                self.bot.tree.add_command(self.add_wr_stats, guild=guild)
            elif category == "CB":
                self.bot.tree.add_command(self.add_cb_stats, guild=guild)
            elif category == "DE":
                self.bot.tree.add_command(self.add_de_stats, guild=guild)
            elif category == "RB":
                self.bot.tree.add_command(self.add_rb_stats, guild=guild)
            elif category == "LB":
                self.bot.tree.add_command(self.add_lb_stats, guild=guild)
            elif category == "P":
                self.bot.tree.add_command(self.add_p_stats, guild=guild)
            elif category == "B":
                self.bot.tree.add_command(self.add_b_stats, guild=guild)
            elif category == "ST":
                self.bot.tree.add_command(self.add_st_stats, guild=guild)
            elif category == "MF":
                self.bot.tree.add_command(self.add_mf_stats, guild=guild)
            elif category == "GK":
                self.bot.tree.add_command(self.add_gk_stats, guild=guild)

    @app_commands.command(name="stat_config", description="Configure the game type for this server (Admin only).")
    @app_commands.describe(game_type="The type of game for this server.")
    @app_commands.choices(game_type=[
        app_commands.Choice(name="7v7 Football", value="7v7"),
        app_commands.Choice(name="11v11 Football", value="11v11"),
        app_commands.Choice(name="Baseball", value="baseball"),
        app_commands.Choice(name="Soccer", value="soccer")
    ])
    async def stat_config(self, interaction: discord.Interaction, game_type: str):
        """Configure game type for the guild."""
        try:
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                embed = self.create_enhanced_embed(
                    "🚫 Access Denied",
                    "Only server **Administrators** can configure game types.",
                    discord.Color.red(),
                    interaction
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            if game_type not in self.game_types:
                embed = self.create_enhanced_embed(
                    "⚠️ Invalid Game Type",
                    f"Game type **{game_type}** is not supported.\n\nSupported types: {', '.join(self.game_types.keys())}",
                    discord.Color.orange(),
                    interaction
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Get current config
            config = get_server_config(interaction.guild_id)
            if not isinstance(config, dict):
                config = get_default_config()
            
            # Update game type
            config["game_type"] = game_type
            update_server_config(interaction.guild_id, "game_type", game_type)
            save_guild_config(interaction.guild_id, config)

            # Register new commands for this game type
            await self.register_commands_for_guild(interaction.guild_id)

            # Create success embed with enhanced styling
            embed = self.create_enhanced_embed(
                "⚙️ Game Type Configured Successfully",
                f"✅ Game type set to **{game_type}** for **{interaction.guild.name}**\n\n🔄 Commands have been updated and synced automatically.",
                discord.Color.green(),
                interaction
            )
            
            # Add configuration details
            game_config = self.game_types[game_type]
            categories_text = ", ".join([f"**{cat}**" for cat in game_config["categories"]])
            embed.add_field(
                name="📊 Available Categories",
                value=categories_text,
                inline=False
            )
            
            embed.add_field(
                name="🎯 Next Steps",
                value="• Use `/statview` to view player statistics\n• Use `/statleaderboard` to see top performers\n• Use position-specific commands to add stats",
                inline=False
            )

            await interaction.response.send_message(embed=embed)
            
            # Log the action
            await log_action(
                interaction.guild, "CONFIG", interaction.user,
                f"Set game type to {game_type}", "stat_config"
            )
            
        except Exception as e:
            logger.error(f"Error configuring game type for guild {interaction.guild_id}: {e}")
            embed = self.create_enhanced_embed(
                "🚫 Configuration Error",
                f"Failed to configure game type. Please try again.\n\n**Error:** {str(e)}",
                discord.Color.red(),
                interaction
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="statview", description="View a player's statistics.")
    @app_commands.describe(category="The position category.", player="The name of the player.")
    async def statview(self, interaction: discord.Interaction, category: str, player: str):
        """View player stats for the guild's game type."""
        config = get_server_config(interaction.guild_id)
        game_type = config.get("game_type", "7v7")
        game_config = self.game_types.get(game_type, self.game_types["7v7"])

        if category not in game_config["categories"]:
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "⚠️ Invalid Category",
                f"Category **{category}** is not valid for game type **{game_type}**.",
                discord.Color.orange()
            ), ephemeral=True)
            return

        if game_type in ["7v7", "11v11"] and player.lower() == "thezypherious":
            description = "Behold the legendary statistics of **TheZypherious**!"
            color = discord.Color.from_rgb(148, 0, 211)
            player_stats = game_config.get("legendary_players", {}).get(player, {}).get(category, {})
            embed = self.create_beautiful_embed(interaction, f"{player}'s {category} Stats", description, color)
            for name, value, inline in self.format_player_stats_for_embed(game_type, category, player_stats):
                embed.add_field(name=name, value=value, inline=inline)
            await interaction.response.send_message(embed=embed)
            return

        file_path = get_stat_file_path(game_type, category)
        stats_data = await load_stats(file_path)
        guild_id_str = str(interaction.guild_id)

        player_data = stats_data.get(guild_id_str, {}).get("Stats", {}).get(player)
        if not player_data:
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "❓ Player Not Found",
                f"No stats found for **{player}** in category **{game_config['display_names'].get(category, category)}**.",
                discord.Color.orange()
            ), ephemeral=True)
            return

        embed = self.create_beautiful_embed(
            interaction, f"{player}'s {game_config['display_names'].get(category, category)} Stats",
            f"Statistics for **{player}** as a **{game_config['display_names'].get(category, category)}**.",
            discord.Color.blurple()
        )
        for name, value, inline in self.format_player_stats_for_embed(game_type, category, player_data):
            embed.add_field(name=name, value=value, inline=inline)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="statleaderboard", description="View the top players for a category.")
    @app_commands.describe(category="The position category.")
    async def statleaderboard(self, interaction: discord.Interaction, category: str):
        """Display leaderboard for a category."""
        config = get_server_config(interaction.guild_id)
        game_type = config.get("game_type", "7v7")
        game_config = self.game_types.get(game_type, self.game_types["7v7"])

        if category not in game_config["categories"]:
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "⚠️ Invalid Category",
                f"Category **{category}** is not valid for game type **{game_type}**.",
                discord.Color.orange()
            ), ephemeral=True)
            return

        file_path = get_stat_file_path(game_type, category)
        sort_key = game_config["leaderboard_sort_keys"].get(category)
        if not sort_key:
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "⚠️ Invalid Category",
                f"No leaderboard sort key defined for category **{category}**.",
                discord.Color.orange()
            ), ephemeral=True)
            return

        stats_data = await load_stats(file_path)
        guild_id_str = str(interaction.guild_id)
        players_data = stats_data.get(guild_id_str, {}).get("Stats", {})

        if not players_data:
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, f"{category} Leaderboard - No Data",
                f"No stats recorded for **{game_config['display_names'].get(category, category)}**.",
                discord.Color.orange()
            ), ephemeral=True)
            return

        valid_players = []
        for player, stats in players_data.items():
            sort_stat_value = stats.get(sort_key, 0)
            if sort_stat_value != 0 or (game_type in ["7v7", "11v11"] and category == "QB" and stats.get("att", 0) > 0):
                valid_players.append((player, stats))

        valid_players.sort(key=lambda x: x[1].get(sort_key, 0), reverse=True)
        top_players = valid_players[:10]

        if not top_players:
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, f"{category} Leaderboard - No Qualifying Players",
                f"No players with sufficient stats for **{game_config['display_names'].get(category, category)}**.",
                discord.Color.orange()
            ), ephemeral=True)
            return

        leaderboard_lines = []
        for rank, (player, stats) in enumerate(top_players, 1):
            stat_value = stats.get(sort_key)
            formatted_stat_value = format_float(stat_value, 2) if sort_key in ["qbr", "ypc", "era", "whip", "avg", "goal_pct", "pass_pct"] else str(stat_value or 0)
            player_display = f"**{player}**"
            if game_type in ["7v7", "11v11"] and player.lower() == "thezypherious":
                player_display = f"👑 {player_display} 👑"
            leaderboard_lines.append(f"{rank}. {player_display} — **{formatted_stat_value}**")

        embed = self.create_enhanced_embed(
            f"🏆 {game_config['display_names'].get(category, category)} Leaderboard",
            f"**Top performers for {game_config['display_names'].get(category, category)}**\n📊 **Ranked by:** {self.stat_key_display_names.get(sort_key, sort_key.replace('_', ' ').title())}",
            discord.Color.gold(),
            interaction
        )
        
        # Split leaderboard into multiple fields for better readability
        if len(leaderboard_lines) > 5:
            mid_point = len(leaderboard_lines) // 2
            embed.add_field(
                name="🥇 Top Performers", 
                value="\n".join(leaderboard_lines[:mid_point]), 
                inline=True
            )
            embed.add_field(
                name="🏅 More Leaders", 
                value="\n".join(leaderboard_lines[mid_point:]), 
                inline=True
            )
        else:
            embed.add_field(
                name="📈 Leaderboard Standings", 
                value="\n".join(leaderboard_lines), 
                inline=False
            )
        
        # Add summary field
        embed.add_field(
            name="📊 Summary",
            value=f"**Total Players:** {len(top_players)}\n**Metric:** {self.stat_key_display_names.get(sort_key, sort_key.replace('_', ' ').title())}\n**Game Type:** {game_type.title()}",
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    async def _update_stats_command_handler(self, interaction: discord.Interaction, category: str, player: str, stats_to_add: dict, derived_stat_keys: list, success_message_prefix: str):
        """Handle stat updates."""
        config = get_server_config(interaction.guild_id)
        game_type = config.get("game_type", "7v7")
        file_path = get_stat_file_path(game_type, category)

        for key, value in stats_to_add.items():
            if safe_int(value) < 0:
                await interaction.response.send_message(embed=self.create_beautiful_embed(
                    interaction, "Invalid Input",
                    f"Stat value for **{self.stat_key_display_names.get(key, key)}** cannot be negative.",
                    discord.Color.orange()
                ), ephemeral=True)
                return

        if game_type in ["7v7", "11v11"]:
            if category == "QB" and safe_int(stats_to_add.get("comp", 0)) > safe_int(stats_to_add.get("att", 0)):
                await interaction.response.send_message(embed=self.create_beautiful_embed(
                    interaction, "Invalid Input",
                    "Completions cannot exceed Attempts.",
                    discord.Color.orange()
                ), ephemeral=True)
                return
            if category == "WR" and safe_int(stats_to_add.get("catches", 0)) > safe_int(stats_to_add.get("targets", 0)):
                await interaction.response.send_message(embed=self.create_beautiful_embed(
                    interaction, "Invalid Input",
                    "Receptions cannot exceed Targets.",
                    discord.Color.orange()
                ), ephemeral=True)
                return
            if category == "CB" and safe_int(stats_to_add.get("comp_allowed", 0)) > safe_int(stats_to_add.get("targets", 0)):
                await interaction.response.send_message(embed=self.create_beautiful_embed(
                    interaction, "Invalid Input",
                    "Completions Allowed cannot exceed Targets.",
                    discord.Color.orange()
                ), ephemeral=True)
                return
        elif game_type == "baseball":
            if category == "P" and safe_int(stats_to_add.get("runs", 0)) < 0:
                await interaction.response.send_message(embed=self.create_beautiful_embed(
                    interaction, "Invalid Input",
                    "Runs cannot be negative.",
                    discord.Color.orange()
                ), ephemeral=True)
                return
        elif game_type == "soccer":
            if category in ["ST", "MF"] and safe_int(stats_to_add.get("goals", 0)) > safe_int(stats_to_add.get("shots", 0)):
                await interaction.response.send_message(embed=self.create_beautiful_embed(
                    interaction, "Invalid Input",
                    "Goals cannot exceed Shots.",
                    discord.Color.orange()
                ), ephemeral=True)
                return

        try:
            stats = await update_stat_entry(file_path, interaction.guild_id, player, stats_to_add, derived_stat_keys, game_type, category)
            embed = self.create_add_stat_embed(interaction, game_type, category, player, stats, success_message_prefix)
            await interaction.response.send_message(embed=embed)
            action_desc = ", ".join(f"{self.stat_key_display_names.get(k, k)}: {v}" for k, v in stats_to_add.items())
            await log_action(
                interaction.guild, "STATS", interaction.user,
                f"Updated {category} stats for {player}. {action_desc}",
                f"add_{category.lower()}_stats"
            )
        except Exception as e:
            logger.error(f"Error updating stats for {category}/{player}: {e}")
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "Error",
                f"An unexpected error occurred: {e}",
                discord.Color.red()
            ), ephemeral=True)

    def create_add_stat_embed(self, interaction, game_type, category, player, stats, title_suffix):
        """Create embed for stat updates."""
        embed = self.create_beautiful_embed(
            interaction,
            f"{title_suffix} • {player} ({self.game_types[game_type]['display_names'].get(category, category)})",
            f"Stats updated for **{player}** in **{self.game_types[game_type]['display_names'].get(category, category)}**.",
            discord.Color.green()
        )
        for name, value, inline in self.format_player_stats_for_embed(game_type, category, stats):
            embed.add_field(name=name, value=value, inline=inline)
        return embed

    @app_commands.command(name="statmerge", description="Merge two players' stats (Admin only).")
    @app_commands.describe(
        category="Position category.",
        player1="First player's name.",
        player2="Second player's name.",
        new_player="Name for merged stats."
    )
    async def statmerge(self, interaction: discord.Interaction, category: str, player1: str, player2: str, new_player: str):
        """Merge stats of two players."""
        config = get_server_config(interaction.guild_id)
        game_type = config.get("game_type", "7v7")
        game_config = self.game_types.get(game_type, self.game_types["7v7"])

        if not interaction.user.guild_permissions.administrator:
            embed = self.create_enhanced_embed(
                "🚫 Permission Denied",
                "Only **Administrators** can perform stat merges.\n\nThis action requires administrative privileges.",
                discord.Color.red(),
                interaction
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if player1.lower() == player2.lower():
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "⚠️ Invalid Input",
                "Player names must be different.",
                discord.Color.orange()
            ), ephemeral=True)
            return
        if new_player.lower() in [player1.lower(), player2.lower()]:
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "⚠️ Invalid Input",
                "New player name cannot match merged players.",
                discord.Color.orange()
            ), ephemeral=True)
            return
        if category not in game_config["categories"]:
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "⚠️ Invalid Category",
                f"Category **{category}** is not valid for game type **{game_type}**.",
                discord.Color.orange()
            ), ephemeral=True)
            return

        file_path = get_stat_file_path(game_type, category)
        stats_data = await load_stats(file_path)
        guild_id_str = str(interaction.guild_id)

        if guild_id_str not in stats_data:
            stats_data[guild_id_str] = {"Stats": {}}

        p1_stats = stats_data[guild_id_str]["Stats"].get(player1, game_config["stat_templates"].get(category, {}).copy())
        p2_stats = stats_data[guild_id_str]["Stats"].get(player2, game_config["stat_templates"].get(category, {}).copy())

        if not (p1_stats or p2_stats):
            await interaction.response.send_message(embed=self.create_beautiful_embed(
                interaction, "❓ Players Not Found",
                f"No stats found for **{player1}** or **{player2}** in category **{category}**.",
                discord.Color.orange()
            ), ephemeral=True)
            return

        merged_stats = {}
        all_keys = set(game_config["stat_templates"].get(category, {}).keys()) | set(p1_stats.keys()) | set(p2_stats.keys())

        for key in all_keys:
            val1 = p1_stats.get(key, 0)
            val2 = p2_stats.get(key, 0)
            merged_stats[key] = safe_int(val1) + safe_int(val2)

        for key in game_config["derived_stats"].get(category, []):
            if key == "qbr":
                att = merged_stats.get("att", 0)
                merged_stats[key] = calculate_qbr(
                    merged_stats.get("comp", 0), att, merged_stats.get("yards", 0),
                    merged_stats.get("tds", 0), merged_stats.get("ints", 0)
                ) if att > 0 else 0.0
            elif key in ["comp_pct", "catch_pct"]:
                total = merged_stats.get("att" if category == "QB" else "targets", 0)
                if total > 0:
                    if category == "QB":
                        merged_stats[key] = (merged_stats.get("comp", 0) / total * 100)
                    elif category in ["WR", "CB"]:
                        merged_stats[key] = (merged_stats.get("catches" if category == "WR" else "comp_allowed", 0) / total * 100)
                else:
                    merged_stats[key] = 0.0
            elif key == "int_pct":
                att = merged_stats.get("att", 0)
                merged_stats[key] = (merged_stats.get("ints", 0) / att * 100) if att > 0 else 0.0
            elif key == "ypc":
                catches = merged_stats.get("catches", 0)
                merged_stats[key] = (merged_stats.get("yards", 0) / catches) if catches > 0 else 0.0
            elif key == "deny_pct":
                merged_stats[key] = (100.0 - merged_stats.get("comp_pct", 0.0)) if merged_stats.get("targets", 0) > 0 else 0.0
            elif key == "ypr":
                rushes = merged_stats.get("rushes", 0)
                merged_stats[key] = (merged_stats.get("yards", 0) / rushes) if rushes > 0 else 0.0
            elif key == "era":
                merged_stats[key] = calculate_baseball_era(merged_stats.get("runs", 0), merged_stats.get("innings", 0))
            elif key == "whip":
                merged_stats[key] = calculate_whip(
                    merged_stats.get("walks", 0), merged_stats.get("hits", 0), merged_stats.get("innings", 0)
                )
            elif key == "avg":
                merged_stats[key] = calculate_baseball_avg(merged_stats.get("hits", 0), merged_stats.get("at_bats", 0))
            elif key == "goal_pct":
                merged_stats[key] = calculate_goal_pct(merged_stats.get("goals", 0), merged_stats.get("shots", 0))
            elif key == "pass_pct":
                merged_stats[key] = calculate_pass_pct(merged_stats.get("passes", 0), merged_stats.get("completions", 0))

        stats_data[guild_id_str]["Stats"][new_player] = merged_stats
        if player1 in stats_data[guild_id_str]["Stats"]:
            del stats_data[guild_id_str]["Stats"][player1]
        if player2 in stats_data[guild_id_str]["Stats"]:
            del stats_data[guild_id_str]["Stats"][player2]

        await save_stats(file_path, stats_data)

        embed = self.create_beautiful_embed(
            interaction, "✅ Stats Merged Successfully",
            f"Stats for **{player1}** and **{player2}** merged into **{new_player}** ({game_config['display_names'].get(category, category)}).",
            discord.Color.blue()
        )
        for name, value, inline in self.format_player_stats_for_embed(game_type, category, merged_stats):
            embed.add_field(name=name, value=value, inline=inline)

        await interaction.response.send_message(embed=embed)
        await log_action(
            interaction.guild, "ADMIN_ACTION", interaction.user,
            f"Merged {category} stats for {player1} & {player2} into {new_player}.",
            "statmerge"
        )

    @app_commands.command(name="statclear", description="Clear all stats for this server (Admin only).")
    async def statclear(self, interaction: discord.Interaction):
        """Clear all stats for the guild."""
        config = get_server_config(interaction.guild_id)
        game_type = config.get("game_type", "7v7")
        game_config = self.game_types.get(game_type, self.game_types["7v7"])

        if not interaction.user.guild_permissions.administrator:
            embed = self.create_enhanced_embed(
                "🚫 Permission Denied",
                "Only **Administrators** can clear stats.\n\n⚠️ This is a destructive action that requires admin privileges.",
                discord.Color.red(),
                interaction
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        guild_id_str = str(interaction.guild_id)
        total_entries_cleared = 0

        for category in game_config["categories"]:
            file_path = get_stat_file_path(game_type, category)
            stats_data = await load_stats(file_path)
            if guild_id_str in stats_data and "Stats" in stats_data[guild_id_str]:
                total_entries_cleared += len(stats_data[guild_id_str]["Stats"])
                stats_data[guild_id_str] = {"Stats": {}}
                await save_stats(file_path, stats_data)

        embed = self.create_beautiful_embed(
            interaction, "✅ Stats Cleared",
            f"Cleared **{total_entries_cleared}** stat entries for **{interaction.guild.name}**.",
            discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
        await log_action(
            interaction.guild, "ADMIN_ACTION", interaction.user,
            f"Cleared {total_entries_cleared} stat entries.",
            "statclear"
        )

    @app_commands.command(name="statexport", description="Export stats to CSV.")
    async def statexport(self, interaction: discord.Interaction):
        """Export stats to CSV file."""
        config = get_server_config(interaction.guild_id)
        game_type = config.get("game_type", "7v7")
        game_config = self.game_types.get(game_type, self.game_types["7v7"])

        guild_id_str = str(interaction.guild_id)
        output_buffer = io.StringIO()
        csv_writer = csv.writer(output_buffer)

        all_stat_keys = set()
        for cat_template in game_config["stat_templates"].values():
            all_stat_keys.update(cat_template.keys())

        key_sort_priority = {
            "comp": 0, "att": 1, "yards": 2, "yac": 3, "tds": 4, "ints": 5, "sacks": 6, "safeties": 7,
            "rushes": 8, "fumbles": 9, "ypr": 10, "catches": 11, "targets": 12, "catch_pct": 13,
            "ypc": 14, "swats": 15, "comp_allowed": 16, "deny_pct": 17, "qbr": 18, "comp_pct": 19,
            "int_pct": 20, "tackles": 21, "misses": 22, "innings": 23, "strikeouts": 24, "walks": 25,
            "hits": 26, "runs": 27, "era": 28, "whip": 29, "at_bats": 30, "home_runs": 31,
            "rbis": 32, "stolen_bases": 33, "avg": 34, "goals": 35, "shots": 36, "assists": 37,
            "shots_on_target": 38, "goal_pct": 39, "passes": 40, "pass_pct": 41
        }
        sorted_stat_keys = sorted(all_stat_keys, key=lambda k: key_sort_priority.get(k, 99))

        headers = ["Category", "Player"] + [self.stat_key_display_names.get(k, k.replace("_", " ").title()) for k in sorted_stat_keys]
        csv_writer.writerow(headers)

        total_players_found = 0
        for category in game_config["categories"]:
            file_path = get_stat_file_path(game_type, category)
            stats_data = await load_stats(file_path)
            guild_players_data = stats_data.get(guild_id_str, {}).get("Stats", {})

            for player, player_stats in guild_players_data.items():
                total_players_found += 1
                row = [category, player]
                for key in sorted_stat_keys:
                    value = player_stats.get(key)
                    formatted_value = format_float(value, 2) if key in ["qbr", "ypc", "era", "whip", "avg", "goal_pct", "pass_pct"] else str(value or 0)
                    row.append(formatted_value)
                csv_writer.writerow(row)

        csv_content = output_buffer.getvalue().encode()
        output_buffer.close()

        if total_players_found:
            file_name = f"stats_export_{interaction.guild.name.replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d')}.csv"
            file = discord.File(fp=io.BytesIO(csv_content), filename=file_name)
            embed = self.create_enhanced_embed(
                "📤 Stats Export Complete",
                f"Successfully exported **{total_players_found}** player stat entries.\n\n📊 **Game Type:** {game_type.title()}\n📅 **Export Date:** {datetime.now().strftime('%B %d, %Y')}",
                discord.Color.blue(),
                interaction
            )
            embed.add_field(
                name="📁 File Details",
                value=f"**Filename:** `{file_name}`\n**Format:** CSV (Comma Separated Values)\n**Categories:** {len(game_config['categories'])} position types",
                inline=False
            )
            await interaction.response.send_message(embed=embed, file=file)
        else:
            embed = self.create_enhanced_embed(
                "📄 No Stats Available",
                f"No statistics have been recorded for **{interaction.guild.name}** yet.\n\n💡 **Tip:** Start recording stats using the position-specific commands!",
                discord.Color.orange(),
                interaction
            )
            embed.add_field(
                name="🎯 Getting Started",
                value="• Use `/statconfig` to set your game type\n• Use position commands like `/add_qb_stats`\n• View results with `/statview` and `/statleaderboard`",
                inline=False
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # Position-specific stat commands
    @app_commands.command(name="add_qb_stats", description="Record or update Quarterback statistics.")
    @app_commands.describe(
        player="Player name",
        comp="Completions",
        att="Attempts", 
        yards="Passing yards",
        tds="Touchdowns",
        ints="Interceptions",
        sacks="Sacks taken"
    )
    async def add_qb_stats(self, interaction: discord.Interaction, player: str, comp: int = 0, att: int = 0, yards: int = 0, tds: int = 0, ints: int = 0, sacks: int = 0):
        """Add QB stats."""
        stats_to_add = {"comp": comp, "att": att, "yards": yards, "tds": tds, "ints": ints, "sacks": sacks}
        await self._update_stats_command_handler(
            interaction, "QB", player, stats_to_add,
            ["qbr", "comp_pct", "int_pct"], "QB Stats Updated"
        )

    @app_commands.command(name="add_wr_stats", description="Record or update Wide Receiver statistics.")
    @app_commands.describe(
        player="Player name",
        catches="Receptions",
        targets="Targets",
        tds="Touchdowns",
        yac="Yards after catch",
        yards="Receiving yards"
    )
    async def add_wr_stats(self, interaction: discord.Interaction, player: str, catches: int = 0, targets: int = 0, tds: int = 0, yac: int = 0, yards: int = 0):
        """Add WR stats."""
        stats_to_add = {"catches": catches, "targets": targets, "tds": tds, "yac": yac, "yards": yards}
        await self._update_stats_command_handler(
            interaction, "WR", player, stats_to_add,
            ["catch_pct", "ypc"], "WR Stats Updated"
        )

    @app_commands.command(name="add_cb_stats", description="Record or update Cornerback statistics.")
    @app_commands.describe(
        player="Player name",
        ints="Interceptions",
        targets="Targets",
        swats="Pass breakups",
        tds="Touchdowns",
        comp_allowed="Completions allowed"
    )
    async def add_cb_stats(self, interaction: discord.Interaction, player: str, ints: int = 0, targets: int = 0, swats: int = 0, tds: int = 0, comp_allowed: int = 0):
        """Add CB stats."""
        stats_to_add = {"ints": ints, "targets": targets, "swats": swats, "tds": tds, "comp_allowed": comp_allowed}
        await self._update_stats_command_handler(
            interaction, "CB", player, stats_to_add,
            ["deny_pct", "comp_pct"], "CB Stats Updated"
        )

    @app_commands.command(name="add_de_stats", description="Record or update Defensive End statistics.")
    @app_commands.describe(
        player="Player name",
        tackles="Tackles",
        misses="Missed tackles",
        sacks="Sacks",
        safeties="Safeties"
    )
    async def add_de_stats(self, interaction: discord.Interaction, player: str, tackles: int = 0, misses: int = 0, sacks: int = 0, safeties: int = 0):
        """Add DE stats."""
        stats_to_add = {"tackles": tackles, "misses": misses, "sacks": sacks, "safeties": safeties}
        await self._update_stats_command_handler(
            interaction, "DE", player, stats_to_add, [], "DE Stats Updated"
        )

    @app_commands.command(name="add_rb_stats", description="Record or update Running Back statistics.")
    @app_commands.describe(
        player="Player name",
        rushes="Rush attempts",
        yards="Rushing yards",
        tds="Touchdowns",
        fumbles="Fumbles"
    )
    async def add_rb_stats(self, interaction: discord.Interaction, player: str, rushes: int = 0, yards: int = 0, tds: int = 0, fumbles: int = 0):
        """Add RB stats."""
        stats_to_add = {"rushes": rushes, "yards": yards, "tds": tds, "fumbles": fumbles}
        await self._update_stats_command_handler(
            interaction, "RB", player, stats_to_add, ["ypr"], "RB Stats Updated"
        )

    @app_commands.command(name="add_lb_stats", description="Record or update Linebacker statistics.")
    @app_commands.describe(
        player="Player name",
        tackles="Tackles",
        misses="Missed tackles",
        sacks="Sacks",
        ints="Interceptions"
    )
    async def add_lb_stats(self, interaction: discord.Interaction, player: str, tackles: int = 0, misses: int = 0, sacks: int = 0, ints: int = 0):
        """Add LB stats."""
        stats_to_add = {"tackles": tackles, "misses": misses, "sacks": sacks, "ints": ints}
        await self._update_stats_command_handler(
            interaction, "LB", player, stats_to_add, [], "LB Stats Updated"
        )

    @app_commands.command(name="add_p_stats", description="Record or update Pitcher statistics.")
    @app_commands.describe(
        player="Player name",
        innings="Innings pitched",
        strikeouts="Strikeouts",
        walks="Walks",
        hits="Hits allowed",
        runs="Runs allowed"
    )
    async def add_p_stats(self, interaction: discord.Interaction, player: str, innings: float = 0.0, strikeouts: int = 0, walks: int = 0, hits: int = 0, runs: int = 0):
        """Add Pitcher stats."""
        stats_to_add = {"innings": innings, "strikeouts": strikeouts, "walks": walks, "hits": hits, "runs": runs}
        await self._update_stats_command_handler(
            interaction, "P", player, stats_to_add, ["era", "whip"], "Pitcher Stats Updated"
        )

    @app_commands.command(name="add_b_stats", description="Record or update Batter statistics.")
    @app_commands.describe(
        player="Player name",
        at_bats="At-bats",
        hits="Hits",
        home_runs="Home runs",
        rbis="RBIs",
        stolen_bases="Stolen bases"
    )
    async def add_b_stats(self, interaction: discord.Interaction, player: str, at_bats: int = 0, hits: int = 0, home_runs: int = 0, rbis: int = 0, stolen_bases: int = 0):
        """Add Batter stats."""
        stats_to_add = {"at_bats": at_bats, "hits": hits, "home_runs": home_runs, "rbis": rbis, "stolen_bases": stolen_bases}
        await self._update_stats_command_handler(
            interaction, "B", player, stats_to_add, ["avg"], "Batter Stats Updated"
        )

    @app_commands.command(name="add_st_stats", description="Record or update Striker statistics.")
    @app_commands.describe(
        player="Player name",
        goals="Goals scored",
        shots="Shots taken",
        assists="Assists",
        shots_on_target="Shots on target"
    )
    async def add_st_stats(self, interaction: discord.Interaction, player: str, goals: int = 0, shots: int = 0, assists: int = 0, shots_on_target: int = 0):
        """Add Striker stats."""
        stats_to_add = {"goals": goals, "shots": shots, "assists": assists, "shots_on_target": shots_on_target}
        await self._update_stats_command_handler(
            interaction, "ST", player, stats_to_add, ["goal_pct"], "Striker Stats Updated"
        )

    @app_commands.command(name="add_mf_stats", description="Record or update Midfielder statistics.")
    @app_commands.describe(
        player="Player name",
        passes="Passes attempted",
        completions="Pass completions",
        assists="Assists",
        tackles="Tackles",
        goals="Goals scored"
    )
    async def add_mf_stats(self, interaction: discord.Interaction, player: str, passes: int = 0, completions: int = 0, assists: int = 0, tackles: int = 0, goals: int = 0):
        """Add Midfielder stats."""
        stats_to_add = {"passes": passes, "completions": completions, "assists": assists, "tackles": tackles, "goals": goals}
        await self._update_stats_command_handler(
            interaction, "MF", player, stats_to_add, ["pass_pct"], "Midfielder Stats Updated"
        )

    @app_commands.command(name="add_gk_stats", description="Record or update Goalkeeper statistics.")
    @app_commands.describe(
        player="Player name",
        saves="Saves made",
        shots_faced="Shots faced",
        goals_allowed="Goals allowed",
        clean_sheets="Clean sheets"
    )
    async def add_gk_stats(self, interaction: discord.Interaction, player: str, saves: int = 0, shots_faced: int = 0, goals_allowed: int = 0, clean_sheets: int = 0):
        """Add Goalkeeper stats."""
        stats_to_add = {"saves": saves, "shots_faced": shots_faced, "goals_allowed": goals_allowed, "clean_sheets": clean_sheets}
        await self._update_stats_command_handler(
            interaction, "GK", player, stats_to_add, ["save_pct"], "Goalkeeper Stats Updated"
        )

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Register commands when joining a guild."""
        await self.register_commands_for_guild(guild.id)

    @commands.Cog.listener()
    async def on_ready(self):
        """Register commands for all guilds on startup."""
        for guild in self.bot.guilds:
            await self.register_commands_for_guild(guild.id)
        logger.info("Stats Cog initialized and commands registered for all guilds.")

async def setup(bot: commands.Bot):
    """Add Stats cog to bot."""
    await bot.add_cog(Stats(bot))
    logger.info("Stats Cog loaded successfully.")