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
    tokens = [
        {"token": "MTM3MDE0NjY3NjYzMDg4MDI1Ng.GqxSA9.rMezfeiffqODskgi1wwwHQ6-Ey25R8Tn_sJi5c", "category": "Universal"},  # Universal
        {"token": "MTM4MjA5ODU5NTIwOTAxOTQ5Mw.GHKYfn.3N3PZSmBe6Xu6i1JMEqAHueZAGvpW4Vcv_P2OU", "category": "Gold"},  # HVFL-FF (Paid)
        {"token": "MTM4NTc5NDQ4MzYzOTAyOTg1MQ.GZ18Md.HasBT7Qxbn4a9HZO6tSc0_mjsmQNQJZD_twWwc", "category": "Gold"},  # NGBA Bot (Partnership)
        {"token": "MTM3MTUzODc0MTA5Njc0NzA4MA.G5irSg.wWQgrmaFFyW3k4JNxh8cLC45ZYgt2p_CjfbZds", "category": "Gold"},  # NFA Utilities (partner)
		{"token": "MTM3ODE1OTEwMjk3ODU1NTk3NQ.GuksTJ.NoaVH7zGVOzHrzBXTOXcb-g62ztCtFvrPF_WeA", "category": "Gold"},	# CFFL Bot, Lifetime
        {"token": "MTM4MDM3MzkyNTk5NzA1MTk2NQ.G5SWgM.aYWs1Oh-yvRKB6D-XrvlMQBEtgxgBQp9gbQ7WA", "category": "Gold"},	# AFD Utilties, (paid)
        {"token": "MTM4MTAxNzczNDk5Njk1NTI2OA.GP9-eg.DhMx2Q_HLxf-vilYY4ZTVkNRqPr6U_zTueKtww", "category": "Gold"},   # MVP
        {"token": "MTM4OTc4ODA3MDkwNzIxOTk3OQ.GlP8Mw.5p1obH6_YaeIAUSSFVBlc0lR2WIqFRRUoQIruo", "category": "Gold"},  # EFL Bot (Paid)
        {"token": "MTM5NTQ1NjIyNjA5MDk0NjU5MA.G5NgaN.gUzZ4ciMV3_qEvHyNdh5YwaRfGa0EtWWIXKcvU", "category":"Gold"},   # DBA league bot
        {"token": "MTM4NTI4MzQxMDQxODk5MTE5NA.GDeXor.GudjgOgLOD6rwf6Vdad5CK-cKVneHCM6ZsmX5Q", "category":"Gold"},   # FGA/Genus Bot
        {"token": "MTM5NzAxOTU0MTg1NDQ4NjU4OA.GyCQ2x.boDDOnZy0JyFU7AY8cAqefLcbsTNn4tcw1j734", "category":"Gold"},   # UBL Bot
        {"token": "MTM5NzAyMDE4OTg0NTA5NDQyMA.Ghs0o7.ba5yKF2o2_AHQHqEc04GC-FPAlk1riQeGY4EgQ", "category":"Gold"}   # MBL Bot

        
    ]
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
            synced = await bot.tree.sync()
            logger.info(f"Bot {bot.user.name} synced {len(synced)} application command(s)")
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
