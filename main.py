import discord
import asyncio
import os
import json
import logging
from discord.ext import commands
from utils.scheduler import setup_scheduler

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("discord.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("bot")

# Check if data directory exists
if not os.path.exists("data"):
    os.makedirs("data")
    logger.info("Created data directory")

# Default server config
DEFAULT_SERVER_CONFIG = {
    "log_channels": {},
    "notification_settings": {},
    "permission_settings": {},
    "announcement_channels": {},
    "enabled_commands": {},
    "statsheet_url": "",
    "template_url": ""
}

COMMAND_COUNTER_FILE = "data/command_counter.json"

def load_server_config():
    """Load server configuration from file"""
    try:
        if not os.path.exists("data/serverconfig.json"):
            with open("data/serverconfig.json", "w") as f:
                json.dump({}, f, indent=4)
            return {}
        with open("data/serverconfig.json", "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load server config: {e}")
        return {}

def save_server_config(config):
    """Save server configuration to file"""
    try:
        with open("data/serverconfig.json", "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save server config: {e}")

def load_tokens():
    """Return hardcoded bot tokens with their categories"""
# Accidentally posted once, have been rotated and are useless now. 
    if not tokens:
        logger.error("No tokens provided in hardcoded list")
        raise Exception("No tokens provided")
    if not all(isinstance(t, dict) and "token" in t and isinstance(t["token"], str) and t["token"].strip() and "category" in t and t["category"] in ["Universal", "Silver", "Gold"] for t in tokens):
        logger.error("All tokens must be dictionaries with valid token strings and categories (Universal, Silver, Gold)")
        raise Exception("Invalid token format")
    logger.info(f"Loaded {len(tokens)} hardcoded tokens")
    return tokens

# --- Command Counter Functions ---
def load_command_counts():
    """Load command execution counts from file."""
    try:
        if not os.path.exists(COMMAND_COUNTER_FILE):
            default_counts = {"total_commands_executed": 0, "individual_commands": {}}
            with open(COMMAND_COUNTER_FILE, "w") as f:
                json.dump(default_counts, f, indent=4)
            logger.info(f"Initialized {COMMAND_COUNTER_FILE}")
            return default_counts
        with open(COMMAND_COUNTER_FILE, "r") as f:
            counts = json.load(f)
            if "total_commands_executed" not in counts:
                counts["total_commands_executed"] = 0
            if "individual_commands" not in counts:
                counts["individual_commands"] = {}
            return counts
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding {COMMAND_COUNTER_FILE}: {e}. Resetting to default.")
        default_counts = {"total_commands_executed": 0, "individual_commands": {}}
        save_command_counts(default_counts)
        return default_counts
    except Exception as e:
        logger.error(f"Failed to load command counts: {e}. Returning default.")
        return {"total_commands_executed": 0, "individual_commands": {}}

def save_command_counts(counts):
    """Save command execution counts to file."""
    try:
        with open(COMMAND_COUNTER_FILE, "w") as f:
            json.dump(counts, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save command counts: {e}")

def increment_command_counter(command_name: str):
    """Increment the counter for the given command and the total."""
    counts = load_command_counts()
    counts["total_commands_executed"] = counts.get("total_commands_executed", 0) + 1
    counts["individual_commands"][command_name] = counts["individual_commands"].get(command_name, 0) + 1
    save_command_counts(counts)
    logger.debug(f"Command '{command_name}' executed. New total: {counts['total_commands_executed']}")
# --- End Command Counter Functions ---

async def setup_bot(token, category):
    """Set up a single bot instance with the given token and category"""
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True

    bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"), intents=intents)

    # Define separate cog lists for each category
    universal_cogs = [
        "cogs.setupcommands",
        "cogs.signing_commands",
        "cogs.appointment_commands",
        "cogs.trade_commands",
        "cogs.roster_commands",
        "cogs.game_commands",
        "cogs.suspension_commands",
        "cogs.schedule_commands",
        "cogs.general_commands",
        "cogs.moderation_commands",
        "cogs.betting",
        "cogs.fun",
        "cogs.mediacommands",
        "cogs.spamcommands",
        "cogs.scorereportcommands",
        "cogs.awardcommands",
        "cogs.applications",
        "cogs.tickets",
        "cogs.folist",
        "cogs.giveaways",
        "cogs.verification",
        "cogs.stats",
        "cogs.promotioncommands",
        "cogs.freeagency"
    ]

    silver_cogs = [
        "cogs.setupcommands",
        "cogs.signing_commands",
        "cogs.appointment_commands",
        "cogs.trade_commands",
        "cogs.roster_commands",
        "cogs.game_commands",
        "cogs.suspension_commands",
        "cogs.schedule_commands",
        "cogs.general_commands",
        "cogs.moderation_commands",
        "cogs.betting",
        "cogs.fun",
        "cogs.mediacommands",
        "cogs.spamcommands",
        "cogs.scorereportcommands",
        "cogs.awardcommands",
        "cogs.applications",
        "cogs.tickets",
        "cogs.folist",
        "cogs.self_edit",
        "cogs.silversecurity",
        "cogs.giveaways",
        "cogs.verification",
        "cogs.stats"
    ]

    gold_cogs = [
        "cogs.setupcommands",
        "cogs.signing_commands",
        "cogs.appointment_commands",
        "cogs.trade_commands",
        "cogs.roster_commands",
        "cogs.game_commands",
        "cogs.suspension_commands",
        "cogs.schedule_commands",
        "cogs.general_commands",
        "cogs.moderation_commands",
        "cogs.betting",
        "cogs.fun",
        "cogs.mediacommands",
        "cogs.spamcommands",
        "cogs.scorereportcommands",
        "cogs.awardcommands",
        "cogs.applications",
        "cogs.tickets",
        "cogs.folist",
        "cogs.self_edit",
        "cogs.goldsecuritycog",
        "cogs.giveaways",
        "cogs.verification",
        "cogs.stats",
        "cogs.promotioncommands",
        "cogs.freeagency"
    ]

    # Select cogs based on category
    if category == "Universal":
        cogs_to_load = universal_cogs
    elif category == "Silver":
        cogs_to_load = silver_cogs
    elif category == "Gold":
        cogs_to_load = gold_cogs
    else:
        logger.error(f"Invalid category {category} for bot with token ending in {token[-6:]}")
        return

    @bot.event
    async def on_ready():
        logger.info(f"Bot {bot.user.name} ({bot.user.id}) logged in with token ending in {token[-6:]} (Category: {category})")
        
        # Load cogs based on category
        for cog_name in cogs_to_load:
            try:
                await bot.load_extension(cog_name)
                logger.info(f"Bot {bot.user.name} loaded cog: {cog_name}")
            except commands.ExtensionAlreadyLoaded:
                logger.warning(f"Bot {bot.user.name} tried to load already loaded cog: {cog_name}")
            except commands.ExtensionNotFound:
                logger.error(f"Bot {bot.user.name} cog not found: {cog_name}. Ensure the path is correct.")
            except Exception as e:
                logger.error(f"Bot {bot.user.name} failed to load cog {cog_name}: {e}", exc_info=True)
        
        # Sync application commands
        try:
            # Load guild game types configuration
            guild_game_types = {}
            try:
                with open("data/guild_game_types.json", "r") as f:
                    guild_game_types = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            
            # Perform guild-specific syncing for stats commands
            stats_guilds_synced = 0
            for guild in bot.guilds:
                guild_id_str = str(guild.id)
                if guild_id_str in guild_game_types:
                    try:
                        # Only sync to guilds that have configured game types
                        synced_guild = await bot.tree.sync(guild=guild)
                        stats_guilds_synced += 1
                        logger.info(f"Bot {bot.user.name} synced {len(synced_guild)} command(s) to guild {guild.name} ({guild.id})")
                    except Exception as e:
                        logger.error(f"Bot {bot.user.name} failed to sync commands to guild {guild.name} ({guild.id}): {e}")
            
            # Global sync for non-stats commands
            synced = await bot.tree.sync()
            logger.info(f"Bot {bot.user.name} synced {len(synced)} global command(s) and {stats_guilds_synced} guild-specific syncs")
        except Exception as e:
            logger.error(f"Bot {bot.user.name} failed to sync commands: {e}")
        
        # Initialize scheduler for game reminders
        try:
            if asyncio.iscoroutinefunction(setup_scheduler):
                await setup_scheduler(bot)
            else:
                setup_scheduler(bot)
            logger.info(f"Bot {bot.user.name} game reminder scheduler initialized")
        except Exception as e:
            logger.error(f"Bot {bot.user.name} failed to initialize scheduler: {e}")

    @bot.event
    async def on_guild_join(guild):
        """Initialize configuration when bot joins a new server"""
        logger.info(f"Bot {bot.user.name} joined new guild: {guild.name} ({guild.id})")
        
        config = load_server_config()
        if str(guild.id) not in config:
            config[str(guild.id)] = DEFAULT_SERVER_CONFIG.copy()
            save_server_config(config)
            logger.info(f"Bot {bot.user.name} initialized config for guild {guild.id}")

    @bot.event
    async def on_command_completion(ctx: commands.Context):
        """Called when a prefix command is completed successfully."""
        if ctx.command:
            increment_command_counter(ctx.command.qualified_name)
            logger.info(f"Prefix command '{ctx.command.qualified_name}' executed by {ctx.author}.")

    @bot.event
    async def on_interaction(interaction: discord.Interaction):
        """Called when an interaction is created."""
        if interaction.type == discord.InteractionType.application_command:
            command_name = interaction.data.get("name")
            if command_name:
                increment_command_counter(f"/{command_name}")
                logger.info(f"App command '/{command_name}' invoked by {interaction.user}.")

    @bot.tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.errors.MissingPermissions):
            await interaction.response.send_message(
                "You don't have permission to use this command.", 
                ephemeral=True
            )
        elif isinstance(error, discord.app_commands.CommandInvokeError):
            logger.error(f"Bot {bot.user.name} app command '{interaction.command.name if interaction.command else 'UnknownCmd'}' error: {error.original}", exc_info=True)
            await interaction.response.send_message(
                f"An error occurred while executing this command: {error.original}", 
                ephemeral=True
            )
        else:
            logger.error(f"Bot {bot.user.name} app command error in '{interaction.command.name if interaction.command else 'UnknownCmd'}': {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"An unexpected error occurred: {error}", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)

    try:
        logger.info(f"Attempting to start bot with token ending in {token[-6:]} (Category: {category})")
        await bot.start(token)
    except discord.errors.LoginFailure:
        logger.error(f"Bot with token ending in {token[-6:]} failed to log in: Invalid token")
        raise
    except discord.errors.HTTPException as e:
        logger.error(f"Bot with token ending in {token[-6:]} failed to log in: HTTP error - {e}")
        raise
    except Exception as e:
        logger.error(f"Bot with token ending in {token[-6:]} failed to start: {e}", exc_info=True)
        raise
    finally:
        logger.info(f"Closing bot with token ending in {token[-6:]}")
        await bot.close()

async def main():
    """Run all bot instances concurrently"""
    load_command_counts()  # Initialize command counter file

    try:
        tokens = load_tokens()
    except Exception as e:
        logger.critical(f"Failed to load tokens, cannot start bots: {e}")
        return

    logger.info(f"Found {len(tokens)} tokens")
    tasks = []
    for i, token_info in enumerate(tokens):
        token = token_info["token"]
        category = token_info["category"]
        if not isinstance(token, str) or not token.strip():
            logger.warning(f"Token #{i+1} is invalid or empty, skipping")
            continue
        logger.info(f"Preparing to start bot with token #{i+1} ending in {token[-6:]} (Category: {category})")
        tasks.append(setup_bot(token, category))
    
    if not tasks:
        logger.critical("No valid tokens found to start any bot instances")
        return

    logger.info(f"Starting {len(tasks)} bot instances")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, (token_info, result) in enumerate(zip(tokens, results)):
        token = token_info["token"]
        category = token_info["category"]
        if isinstance(result, Exception):
            logger.error(f"Bot with token #{i+1} ending in {token[-6:]} (Category: {category}) failed: {result}", exc_info=result)
        else:
            logger.info(f"Bot with token #{i+1} ending in {token[-6:]} (Category: {category}) completed execution")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown initiated via keyboard interrupt")
    except Exception as e:
        logger.critical(f"Unhandled critical exception in main execution: {e}", exc_info=True)
    finally:
        logger.info("All bot processes have been shut down or attempted shutdown")
