import discord
import logging
import os
from discord import app_commands
from discord.ext import commands
from utils.config import get_server_config, load_json, save_json
from utils.permissions import is_admin
from utils.logging import log_action
from utils.embeds import EmbedBuilder

logger = logging.getLogger("bot.general")

# Font conversion utility function
def convert_font(text, style):
    styles = {
        'bold': {
            "a": "𝗮", "b": "𝗯", "c": "𝗰", "d": "𝗱", "e": "𝗲", "f": "𝗳", "g": "𝗴", "h": "𝗵", "i": "𝗶",
            "j": "𝗷", "k": "𝗸", "l": "𝗹", "m": "𝗺", "n": "𝗻", "o": "𝗼", "p": "𝗽", "q": "𝗾", "r": "𝗿",
            "s": "𝘀", "t": "𝘁", "u": "𝘂", "v": "𝘃", "w": "𝘄", "x": "𝘅", "y": "𝘆", "z": "𝘇"
        },
        'cursive': {
            "a": "𝒶", "b": "𝒷", "c": "𝒸", "d": "𝒹", "e": "𝑒", "f": "𝒻", "g": "𝑔", "h": "𝒽", "i": "𝒾",
            "j": "𝒿", "k": "𝓀", "l": "𝓁", "m": "𝓂", "n": "𝓃", "o": "𝑜", "p": "𝓅", "q": "𝓆", "r": "𝓇",
            "s": "𝓈", "t": "𝓉", "u": "𝓊", "v": "𝓋", "w": "𝓌", "x": "𝓍", "y": "𝓎", "z": "𝓏"
        },
        'gothic': {
            "a": "𝖆", "b": "𝖇", "c": "𝖈", "d": "𝖑", "e": "𝖊", "f": "𝖋", "g": "𝖌", "h": "𝖍", "i": "𝖎",
            "j": "𝖏", "k": "𝖐", "l": "𝖑", "m": "𝖒", "n": "𝖓", "o": "𝖔", "p": "𝖕", "q": "𝖖", "r": "𝖗",
            "s": "𝖘", "t": "𝖙", "u": "𝖚", "v": "𝖛", "w": "𝖜", "x": "𝖝", "y": "𝖞", "z": "𝖟"
        },
        'sans_bold': {
            "a": "𝗮", "b": "𝗯", "c": "𝗰", "d": "𝗱", "e": "𝗲", "f": "𝗳", "g": "𝗴", "h": "𝗵", "i": "𝗶",
            "j": "𝗷", "k": "𝗸", "l": "𝗹", "m": "𝗺", "n": "𝗻", "o": "𝗼", "p": "𝗽", "q": "𝗾", "r": "𝗿",
            "s": "𝘀", "t": "𝘁", "u": "𝘂", "v": "𝘃", "w": "𝘄", "x": "𝘅", "y": "𝘆", "z": "𝘇"
        },
        'circled': {
            "a": "🅐", "b": "🅑", "c": "🅒", "d": "🅓", "e": "🅔", "f": "🅕", "g": "🅖", "h": "🅗", "i": "🅘",
            "j": "🅙", "k": "🅚", "l": "🅛", "m": "🅜", "n": "🅝", "o": "🅞", "p": "🅟", "q": "🅠", "r": "🅡",
            "s": "🅢", "t": "🅣", "u": "🅤", "v": "🅥", "w": "🅦", "x": "🅧", "y": "🅨", "z": "🅩"
        },
        'squared': {
            "a": "🄰", "b": "🄱", "c": "🄲", "d": "🄳", "e": "🄴", "f": "🄵", "g": "🄶", "h": "🄷", "i": "🄸",
            "j": "🄹", "k": "🄺", "l": "🄻", "m": "🄼", "n": "🄽", "o": "🄾", "p": "🄿", "q": "🅀", "r": "🅁",
            "s": "🅂", "t": "🅃", "u": "🅄", "v": "🅅", "w": "🅆", "x": "🅇", "y": "🅈", "z": "🅉"
        },
        'italic': {
            "a": "𝑎", "b": "𝑏", "c": "𝑐", "d": "𝑑", "e": "𝑒", "f": "𝑓", "g": "𝑔", "h": "ℎ", "i": "𝑖",
            "j": "𝑗", "k": "𝑘", "l": "𝑙", "m": "𝑚", "n": "𝑛", "o": "𝑜", "p": "𝑝", "q": "𝑞", "r": "𝑟",
            "s": "𝑠", "t": "𝑡", "u": "𝑢", "v": "𝑣", "w": "𝑤", "x": "𝑥", "y": "𝑦", "z": "𝑧"
        }
    }

    chosen_style = styles.get(style, {})
    converted_text = []

    for char in text:
        if char.lower() in chosen_style:
            if char.isupper():
                converted_text.append(chosen_style[char.lower()].upper())
            else:
                converted_text.append(chosen_style[char.lower()])
        else:
            converted_text.append(char)

    return "".join(converted_text)

class GeneralCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Get help with bot commands")
    @app_commands.describe(
        command="Specific command to get help with (optional)"
    )
    async def help(self, interaction: discord.Interaction, command: str = None):
        """Get help with bot commands"""
        # Load server config to check for enabled commands
        config = get_server_config(interaction.guild.id)
        enabled_commands = config.get("enabled_commands", {})

        if command:
            # Specific command help
            await self.show_command_help(interaction, command.lower(), enabled_commands)
        else:
            # General help with command categories
            await self.show_general_help(interaction, enabled_commands)

    async def show_command_help(self, interaction, command_name, enabled_commands):
        """Show help for a specific command"""
        # Command info with details
        command_info = {
            "setup": {
                "description": "Configure the bot for your server",
                "usage": "/setup",
                "examples": ["/setup"],
                "category": "Configuration",
                "permissions": "Administrator"
            },
            "offer": {
                "description": "Send a contract offer to a player",
                "usage": "/offer [player_name] [contract_details] [optional: expiration_time]",
                "examples": [
                    "/offer Player 2-year contract at $5M per year",
                    "/offer Player 1-year contract with team option 24h"
                ],
                "category": "Signing",
                "permissions": "Team Staff"
            },
            "sign": {
                "description": "Sign a player directly (bypassing offer)",
                "usage": "/sign [player_name] [contract_details]",
                "examples": ["/sign Player 3-year max contract"],
                "category": "Signing",
                "permissions": "Team Staff"
            },
            "rescind_offer": {
                "description": "Withdraw a contract offer",
                "usage": "/rescind-offer [player_name]",
                "examples": ["/rescind-offer Player"],
                "category": "Signing",
                "permissions": "Team Staff"
            },
            "view_offers": {
                "description": "View contract offers",
                "usage": "/view-offers [filter_type] [status] [optional: player_name]",
                "examples": [
                    "/view-offers team active",
                    "/view-offers all accepted",
                    "/view-offers all all Player"
                ],
                "category": "Signing",
                "permissions": "Team Staff"
            },
            "appoint": {
                "description": "Appoint a user to a Front Office role",
                "usage": "/appoint [user] [optional: team]",
                "examples": [
                    "/appoint @User",
                    "/appoint @User Lakers"
                ],
                "category": "Appointments",
                "permissions": "Management"
            },
            "demote": {
                "description": "Demote a user from their current role",
                "usage": "/demote [user]",
                "examples": ["/demote @User"],
                "category": "Appointments",
                "permissions": "Management"
            },
            "disband": {
                "description": "Disband a team, removing all players and staff",
                "usage": "/disband [team]",
                "examples": ["/disband Lakers"],
                "category": "Appointments",
                "permissions": "Management"
            },
            "propose_trade": {
                "description": "Propose a one-for-one player trade with another team",
                "usage": "/propose-trade [team] [player_one] [player_two]",
                "examples": ["/propose-trade Lakers Player JaneDoe"],
                "category": "Trading",
                "permissions": "Team Staff"
            },
            "roster": {
                "description": "View a team's roster",
                "usage": "/roster [team] [optional: role] [optional: sort]",
                "examples": [
                    "/roster Lakers",
                    "/roster Lakers player",
                    "/roster Lakers all alphabetical"
                ],
                "category": "Roster",
                "permissions": "Everyone"
            },
            "gametime": {
                "description": "Schedule a game between two teams",
                "usage": "/gametime [team1] [team2] [date_time] [optional: timezone]",
                "examples": [
                    "/gametime Lakers Celtics 2023-07-15 18:00",
                    "/gametime Lakers Celtics 2023-07-15 18:00 EST"
                ],
                "category": "Games",
                "permissions": "Team Staff"
            },
            "cancel_game": {
                "description": "Cancel a scheduled game",
                "usage": "/cancel-game [team1] [team2] [date_time]",
                "examples": ["/cancel-game Lakers Celtics 2023-07-15 18:00"],
                "category": "Games",
                "permissions": "Team Staff"
            },
            "stream": {
                "description": "Set or update the stream URL for a scheduled game",
                "usage": "/stream [team1] [team2] [stream_url]",
                "examples": ["/stream Lakers Celtics https://twitch.tv/example"],
                "category": "Games",
                "permissions": "Team Staff"
            },
            "suspend": {
                "description": "Suspend a player from league activities",
                "usage": "/suspend [player_name] [reason] [duration]",
                "examples": [
                    "/suspend Player Unsportsmanlike conduct 3 days",
                    "/suspend JaneDoe Missed games 2 weeks"
                ],
                "category": "Discipline",
                "permissions": "Management"
            },
            "unsuspend": {
                "description": "Lift a suspension from a player",
                "usage": "/unsuspend [player_name]",
                "examples": ["/unsuspend Player"],
                "category": "Discipline",
                "permissions": "Management"
            },
            "auto_schedule": {
                "description": "Automatically generate a schedule",
                "usage": "/auto-schedule [optional: season] [optional: week]",
                "examples": [
                    "/auto-schedule",
                    "/auto-schedule 2",
                    "/auto-schedule 2 3"
                ],
                "category": "Scheduling",
                "permissions": "Management"
            },
            "feedback": {
                "description": "Submit feedback or bug reports",
                "usage": "/feedback [category] [message]",
                "examples": [
                    "/feedback bug Command isn't working",
                    "/feedback feature Please add this feature",
                    "/feedback suggestion This could be improved"
                ],
                "category": "General",
                "permissions": "Everyone"
            },
            "createembed": {
                "description": "Create a custom embed for announcements or information",
                "usage": "/createembed [title] [description] [color] [optional: field_name] [optional: field_value] [optional: image_url]",
                "examples": [
                    "/createembed Welcome Hello everyone! red",
                    "/createembed Announcement Join us today! #00FF00 Info Details here https://example.com/image.png"
                ],
                "category": "General",
                "permissions": "Administrator"
            },
            "fancyfont": {
                "description": "Change the font style of channel names",
                "usage": "/fancyfont [scope] [font_type]",
                "examples": [
                    "/fancyfont this bold",
                    "/fancyfont all cursive"
                ],
                "category": "General",
                "permissions": "Administrator"
            },
            "add_qb_stats": {
                "description": "Add quarterback stats to the statsheet",
                "usage": "/add_qb_stats [player] [comp] [att] [yards] [tds] [ints] [sacks]",
                "examples": ["/add_qb_stats Player 15 25 250 2 1 3"],
                "category": "Statistics",
                "permissions": "Stat Manager"
            },
            "add_wr_stats": {
                "description": "Add wide receiver stats to the statsheet",
                "usage": "/add_wr_stats [player] [catches] [targets] [tds] [yac] [yards]",
                "examples": ["/add_wr_stats Player 5 7 1 45 85"],
                "category": "Statistics",
                "permissions": "Stat Manager"
            },
            "add_cb_stats": {
                "description": "Add cornerback stats to the statsheet",
                "usage": "/add_cb_stats [player] [ints] [targets] [swats] [tds] [comp_allowed]",
                "examples": ["/add_cb_stats Player 1 5 2 0 2"],
                "category": "Statistics",
                "permissions": "Stat Manager"
            },
            "add_de_stats": {
                "description": "Add defensive end stats to the statsheet",
                "usage": "/add_de_stats [player] [tackles] [misses] [sacks] [safeties]",
                "examples": ["/add_de_stats Player 4 1 2 0"],
                "category": "Statistics",
                "permissions": "Stat Manager"
            },
            "linksheet": {
                "description": "Link Google Sheets for stats tracking",
                "usage": "/linksheet",
                "examples": ["/linksheet"],
                "category": "Statistics",
                "permissions": "Stat Manager/Admin"
            },
            "teamview": {
                "description": "View team performance dashboard with scores and stats",
                "usage": "/teamview [team] [optional: period]",
                "examples": [
                    "/teamview Tigers",
                    "/teamview Tigers period:week",
                    "/teamview Tigers period:month"
                ],
                "category": "Dashboard",
                "permissions": "Everyone"
            }
        }

        # Validate if command exists
        cmd_name = command_name.replace("-", "_")  # Normalize command name
        if cmd_name not in command_info:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Command Not Found",
                    f"The command `/{command_name}` was not found."
                ),
                ephemeral=True
            )
            return

        # Check if the command is enabled
        is_enabled = enabled_commands.get(cmd_name, True)

        # Fetch command information
        cmd = command_info[cmd_name]

        # Construct help embed
        embed = discord.Embed(
            title=f"Help: /{command_name}",
            description=cmd["description"],
            color=discord.Color.blue() if is_enabled else discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(name="Usage", value=f"`{cmd['usage']}`", inline=False)

        if cmd["examples"]:
            embed.add_field(
                name="Examples",
                value="\n".join([f"`{ex}`" for ex in cmd["examples"]]),
                inline=False
            )

        embed.add_field(name="Category", value=cmd["category"], inline=True)
        embed.add_field(name="Permissions", value=cmd["permissions"], inline=True)
        embed.add_field(name="Status", value="✅ Enabled" if is_enabled else "❌ Disabled", inline=True)

        embed.set_footer(text="Hydra League Bot • Help System")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def show_general_help(self, interaction, enabled_commands):
        """Show general help with command categories"""
        # Command category organization
        categories = {
            "Configuration": ["setup"],
            "Signing": ["offer", "sign", "rescind_offer", "view_offers"],
            "Appointments": ["appoint", "demote", "disband"],
            "Trading": ["propose_trade"],
            "Roster": ["roster"],
            "Games": ["gametime", "cancel_game", "stream"],
            "Discipline": ["suspend", "unsuspend"],
            "Scheduling": ["auto_schedule"],
            "Dashboard": ["teamview"],
            "General": ["help", "feedback", "createembed", "fancyfont"],
            "Statistics": ["add_qb_stats", "add_wr_stats", "add_cb_stats", "add_de_stats", "linksheet"]
        }

        # Initialize help embed
        embed = discord.Embed(
            title="Hydra League Bot Help",
            description="Below are the available commands categorized by function. "
                        "Use `/help [command]` to get detailed help for a specific command.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        # Append categories and commands
        for category, commands in categories.items():
            # Build list of commands with their status
            command_list = []
            for cmd in commands:
                is_enabled = enabled_commands.get(cmd, True)
                cmd_display = cmd.replace("_", "-")
                status = "✅" if is_enabled else "❌"
                command_list.append(f"{status} `/{cmd_display}`")

            if command_list:
                embed.add_field(
                    name=category,
                    value="\n".join(command_list),
                    inline=False
                )

        embed.set_footer(text="✅ Enabled | ❌ Disabled")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="createembed", description="Create a custom embed for announcements or information")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        title="The title of the embed",
        description="The main content of the embed",
        color="The color of the embed (e.g., red, #FF0000, or a hex code)",
        field_name="Name of the first field (optional)",
        field_value="Value of the first field (optional)",
        image_url="URL of an image to attach (optional)"
    )
    async def createembed(self, interaction: discord.Interaction, title: str, description: str, color: str, 
                         field_name: str = None, field_value: str = None, image_url: str = None):
        """Create a custom embed with specified details"""
        # Defer the response to avoid timeout
        await interaction.response.defer(ephemeral=True)

        # Validate and convert color
        try:
            if color.lower() in ["red", "green", "blue", "yellow", "purple", "orange"]:
                color_map = {
                    "red": 0xFF0000,
                    "green": 0x00FF00,
                    "blue": 0x0000FF,
                    "yellow": 0xFFFF00,
                    "purple": 0x800080,
                    "orange": 0xFFA500
                }
                embed_color = color_map[color.lower()]
            elif color.startswith("#") and len(color) == 7:
                embed_color = int(color[1:], 16)
            else:
                raise ValueError("Invalid color format. Use 'red', 'green', 'blue', 'yellow', 'purple', 'orange', or a hex code (e.g., #FF0000).")
        except ValueError as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Invalid Color", str(e)),
                ephemeral=True
            )
            return

        # Create the embed
        embed = discord.Embed(
            title=title,
            description=description,
            color=embed_color,
            timestamp=discord.utils.utcnow()
        )

        # Add field if provided
        if field_name and field_value:
            embed.add_field(name=field_name, value=field_value, inline=False)

        # Add image if provided and valid URL
        if image_url:
            if not image_url.startswith(("http://", "https://")):
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Invalid Image URL", "Please provide a valid URL starting with http:// or https://."),
                    ephemeral=True
                )
                return
            embed.set_image(url=image_url)

        embed.set_footer(text="Hydra League Bot • Custom Embed")

        # Send the embed to the channel
        try:
            await interaction.channel.send(embed=embed)
            await interaction.followup.send(
                embed=EmbedBuilder.success("Embed Created", "The embed has been successfully posted to the channel."),
                ephemeral=True
            )

            # Log the action
            await log_action(
                interaction.guild,
                "OTHER",
                interaction.user,
                f"Created a custom embed with title: {title}",
                "createembed"
            )
        except Exception as e:
            logger.error(f"Failed to send embed: {e}")
            await interaction.followup.send(
                embed=EmbedBuilder.error("Error", f"Failed to send embed: {str(e)}"),
                ephemeral=True
            )

    @app_commands.command(name="fancyfont", description="Change the font style of channel names")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        scope="Scope of change (all channels or current channel)",
        font_type="Font style to apply"
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="All Channels", value="all"),
            app_commands.Choice(name="This Channel", value="this")
        ],
        font_type=[
            app_commands.Choice(name="Bold", value="bold"),
            app_commands.Choice(name="Cursive", value="cursive"),
            app_commands.Choice(name="Gothic", value="gothic"),
            app_commands.Choice(name="Sans Bold", value="sans_bold"),
            app_commands.Choice(name="Circled", value="circled"),
            app_commands.Choice(name="Squared", value="squared"),
            app_commands.Choice(name="Italic", value="italic")
        ]
    )
    async def fancyfont(self, interaction: discord.Interaction, scope: str, font_type: str):
        """Changes the font style of the channel names based on the scope and font_type. Warning: this cannot be undone/reverted to the original by the bot"""
        # Defer the response to avoid timeout for potentially long operations
        await interaction.response.defer(ephemeral=True)

        if not await is_admin(interaction.user):
            await interaction.followup.send(
                embed=EmbedBuilder.error("Permission Denied", "Only administrators can use this command."),
                ephemeral=True
            )
            return

        font = font_type.lower()

        try:
            if scope == "this":
                new_name = convert_font(interaction.channel.name, font)
                await interaction.channel.edit(name=new_name)
                await interaction.followup.send(
                    embed=EmbedBuilder.success(
                        "Channel Font Updated",
                        f"This channel's name has been changed to: {new_name}"
                    ),
                    ephemeral=True
                )
                await log_action(
                    interaction.guild,
                    "OTHER",
                    interaction.user,
                    f"Changed font of channel {interaction.channel.name} to {font_type}",
                    "fancyfont"
                )

            elif scope == "all":
                changed_channels = []
                for channel in interaction.guild.text_channels:
                    try:
                        new_name = convert_font(channel.name, font)
                        await channel.edit(name=new_name)
                        changed_channels.append(channel.name)
                    except Exception as e:
                        logger.warning(f"Failed to rename channel {channel.name}: {e}")
                        continue
                await interaction.followup.send(
                    embed=EmbedBuilder.success(
                        "All Channels Updated",
                        f"Updated {len(changed_channels)} text channels with the selected font."
                    ),
                    ephemeral=True
                )
                await log_action(
                    interaction.guild,
                    "OTHER",
                    interaction.user,
                    f"Changed font of {len(changed_channels)} channels to {font_type}: {', '.join(changed_channels)}",
                    "fancyfont"
                )

        except Exception as e:
            logger.error(f"Error in fancyfont command: {e}")
            await interaction.followup.send(
                embed=EmbedBuilder.error("Error", f"An error occurred: {str(e)}"),
                ephemeral=True
            )

    @app_commands.command(name="feedback", description="Submit feedback or bug reports")
    @app_commands.describe(
        category="Type of feedback",
        message="Your feedback message"
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Bug Report", value="bug"),
            app_commands.Choice(name="Feature Request", value="feature"),
            app_commands.Choice(name="Suggestion", value="suggestion")
        ]
    )
    async def feedback(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        message: str
    ):
        """Submit feedback or bug reports"""
        # Defer the response to avoid timeout
        await interaction.response.defer(ephemeral=True)

        # Load server config to find admin feedback channel
        config = get_server_config(interaction.guild.id)
        admin_feedback_channel_id = None

        if "log_channels" in config and "general" in config["log_channels"]:
            admin_feedback_channel_id = config["log_channels"]["general"]

        # Create feedback entry
        feedback_id = f"FEEDBACK-{discord.utils.utcnow().strftime('%Y%m%d%H%M%S')}"

        # Load existing feedback
        feedback_data = load_json("feedback.json")
        guild_id = str(interaction.guild.id)

        if guild_id not in feedback_data:
            feedback_data[guild_id] = {}

        # Store feedback
        feedback_data[guild_id][feedback_id] = {
            "category": category.value,
            "message": message,
            "user_id": str(interaction.user.id),
            "user_name": str(interaction.user),
            "submitted_at": discord.utils.utcnow().timestamp(),
            "status": "open"
        }

        save_json("feedback.json", feedback_data)

        # Create feedback confirmation embed
        embed = discord.Embed(
            title=f"📝 {category.name} Submitted",
            description="Your feedback has been submitted. Thank you!",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Message", value=message, inline=False)
        embed.add_field(name="Feedback ID", value=feedback_id, inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

        # Send to admin channel if configured
        if admin_feedback_channel_id:
            try:
                admin_channel = interaction.guild.get_channel(int(admin_feedback_channel_id))
                if admin_channel:
                    admin_embed = discord.Embed(
                        title=f"📬 New {category.name}",
                        description=f"Feedback submitted by {interaction.user.mention}",
                        color=discord.Color.gold(),
                        timestamp=discord.utils.utcnow()
                    )
                    admin_embed.add_field(name="Message", value=message, inline=False)
                    admin_embed.add_field(name="Category", value=category.name, inline=True)
                    admin_embed.add_field(name="Feedback ID", value=feedback_id, inline=True)
                    admin_embed.set_footer(text=f"From: {interaction.user.name} ({interaction.user.id})")

                    await admin_channel.send(embed=admin_embed)
            except Exception as e:
                logger.error(f"Failed to send feedback to admin channel: {e}")

        # Log the feedback
        await log_action(
            interaction.guild,
            "OTHER",
            interaction.user,
            f"Submitted {category.name}: {message}",
            "feedback"
        )


async def setup(bot):
    await bot.add_cog(GeneralCommands(bot))