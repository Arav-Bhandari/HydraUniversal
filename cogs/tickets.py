import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
import uuid
import io
# Assuming utils are in a 'utils' directory and accessible
# from utils.permissions import can_use_command # Not used in this snippet
# from utils.embeds import EmbedBuilder # Defined locally, so no need to import

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('bot.tickets')

# --- Utility Functions & Classes ---
def format_user(user: discord.User) -> str:
    """Formats a user object for display without pinging."""
    return f"**{user.display_name}** (`{user.id}`)"

def log_action(guild_id: int, user_id: int, action: str):
    """Log actions to console (placeholder for database/file logging)."""
    logger.info(f"[Action Log] Guild: {guild_id}, User: {user_id}, Action: {action}")

class EmbedBuilder:
    """A helper class to build standardized embeds."""
    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        return discord.Embed(title=f"✅ {title}", description=description, color=discord.Color.green())

    @staticmethod
    def error(title: str, description: str) -> discord.Embed:
        return discord.Embed(title=f"❌ {title}", description=description, color=discord.Color.red())

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        return discord.Embed(title=f"ℹ️ {title}", description=description, color=discord.Color.blue())

    @staticmethod
    def warning(title: str, description: str) -> discord.Embed:
        return discord.Embed(title=f"⚠️ {title}", description=description, color=discord.Color.gold())

# ----------------------------------------------------------------------------------
# 1. TICKET MANAGER
# ----------------------------------------------------------------------------------
class TicketManager:
    """Handles loading and saving ticket data from a JSON file."""
    def __init__(self):
        self.tickets_data_file = "data/tickets.json"
        os.makedirs(os.path.dirname(self.tickets_data_file), exist_ok=True)
        self.tickets_data = self.load_data()
        self._lock = asyncio.Lock()  # For concurrency safety

    def load_data(self) -> Dict:
        """Loads ticket data from the JSON file. Returns an empty dict if file is missing or invalid."""
        try:
            if os.path.exists(self.tickets_data_file):
                with open(self.tickets_data_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content: # Handle empty file
                        logger.warning(f"Ticket data file '{self.tickets_data_file}' is empty. Initializing with empty data.")
                        return {}
                    return json.loads(content)
            else:
                logger.info(f"Ticket data file '{self.tickets_data_file}' not found. Initializing with empty data.")
                return {}
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Error loading ticket data from '{self.tickets_data_file}': {e}", exc_info=True)
            # Return empty dict to prevent further errors, but log the issue.
            return {}

    def _default_guild_config(self) -> Dict:
        """Provides a default configuration structure for a guild."""
        return {
            "panel_channel_id": None,
            "panel_message_id": None,
            "transcripts_channel_id": None,
            "panel_color": 0x3498db,
            "categories": {},
            "active_tickets": {}, # This is where active ticket data is stored
            "counter": 0,
            "inactive_close_after_days": 3,
            "inactive_warning_enabled": True,
            "welcome_message_type": "standard",  # New: standard or custom
            "custom_welcome_message": None      # New: stores custom message
        }

    async def save_data(self) -> None:
        """Saves the current ticket data to the JSON file atomically."""
        async with self._lock:
            logger.debug(f"Attempting to save ticket data to {self.tickets_data_file}")
            for attempt in range(3):
                try:
                    with open(self.tickets_data_file, 'w', encoding='utf-8') as f:
                        json.dump(self.tickets_data, f, indent=4)
                    logger.debug("Ticket data saved successfully")
                    return
                except OSError as e:
                    logger.warning(f"Failed to save ticket data (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(1) # Wait before retrying
            logger.error(f"Failed to save ticket data after 3 attempts to '{self.tickets_data_file}'")

    def get_guild_config(self, guild_id: str) -> Dict:
        """Retrieves or initializes the configuration for a specific guild."""
        guild_id = str(guild_id) # Ensure guild_id is a string
        if guild_id not in self.tickets_data:
            logger.info(f"Initializing config for new guild: {guild_id}")
            self.tickets_data[guild_id] = self._default_guild_config()
        else:
            # Ensure all default keys exist, even if the file was partially updated or corrupted
            for key, value in self._default_guild_config().items():
                self.tickets_data[guild_id].setdefault(key, value)
        
        # Ensure active_tickets is a dictionary, even if it was loaded as something else
        if not isinstance(self.tickets_data[guild_id].get("active_tickets"), dict):
            logger.warning(f"Correcting invalid 'active_tickets' structure for guild {guild_id}.")
            self.tickets_data[guild_id]["active_tickets"] = {}
            # No need to save here, save_data is called after modifications.
            # If this is the first load, it will be saved later.

        return self.tickets_data[guild_id]

# ----------------------------------------------------------------------------------
# 2. UI VIEWS & MODALS
# (Keep existing UI classes as they are, they interact with TicketManager correctly)
# ----------------------------------------------------------------------------------
class CloseReasonModal(discord.ui.Modal, title="Close Ticket with Reason"):
    reason = discord.ui.TextInput(label="Reason for Closing", style=discord.TextStyle.paragraph, required=True)
    
    def __init__(self, ticket_cog):
        super().__init__()
        self.ticket_cog = ticket_cog
    
    async def on_submit(self, interaction: discord.Interaction):
        await self.ticket_cog.handle_close_ticket(interaction, self.reason.value)

class CloseRequestView(discord.ui.View):
    def __init__(self, ticket_cog, requester: discord.Member, creator_id: int):
        super().__init__(timeout=86400)
        self.ticket_cog = ticket_cog
        self.requester = requester
        self.creator_id = creator_id
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if await self.ticket_cog.is_support_or_creator(interaction):
            return True
        await interaction.response.send_message("Only the ticket creator or staff can interact.", ephemeral=True)
        return False

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="confirm_close_ticket")
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.ticket_cog.handle_close_ticket(interaction, f"Closed by {interaction.user.display_name} via close request.")

    @discord.ui.button(label="Keep Open", style=discord.ButtonStyle.secondary, custom_id="deny_close_ticket")
    async def deny_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        await interaction.response.send_message(
            f"{interaction.user.mention} has marked this ticket to be kept open.",
            allowed_mentions=discord.AllowedMentions.none()
        )
        self.stop()

class PersistentTicketView(discord.ui.View):
    def __init__(self, ticket_cog):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensures only the game owner or staff can interact with the buttons."""
        if interaction.channel and isinstance(interaction.channel, discord.Thread):
            if await self.ticket_cog.is_support_or_creator(interaction):
                return True
        await interaction.response.send_message("You cannot interact with this ticket's controls.", ephemeral=True)
        return False

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="persistent_close_ticket")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CloseReasonModal(self.ticket_cog))

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="persistent_claim_ticket")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.ticket_cog.is_staff_member(interaction, in_ticket_channel=True):
            return await interaction.response.send_message("Only designated staff can claim tickets.", ephemeral=True)
        
        await interaction.response.defer()
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.message.edit(view=self)
        
        guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(interaction.guild_id))
        # Ensure active_tickets is a dict before accessing
        if not isinstance(guild_config.get("active_tickets"), dict):
            guild_config["active_tickets"] = {}
        guild_config["active_tickets"][str(interaction.channel.id)]["claimed_by"] = str(interaction.user.id)
        await self.ticket_cog.ticket_manager.save_data()

        embed = EmbedBuilder.success("Ticket Claimed", f"{interaction.user.mention} will be assisting with this ticket.")
        await interaction.followup.send(embed=embed)

    @discord.ui.button(label="User Info", style=discord.ButtonStyle.secondary, custom_id="persistent_user_info")
    async def user_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.ticket_cog.is_staff_member(interaction, in_ticket_channel=True):
            return await interaction.response.send_message("Only staff can view user info.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(interaction.guild_id))
        # Ensure active_tickets is a dict before accessing
        if not isinstance(guild_config.get("active_tickets"), dict):
            await interaction.followup.send("Ticket data is not properly initialized.", ephemeral=True)
            return
        ticket_data = guild_config["active_tickets"].get(str(interaction.channel.id))
        
        if not ticket_data:
            await interaction.followup.send("Could not find ticket data for this channel.", ephemeral=True)
            return

        try:
            member = interaction.guild.get_member(int(ticket_data["user_id"]))
            if not member:
                member = await self.bot.fetch_user(int(ticket_data["user_id"]))
        except (ValueError, discord.NotFound):
            await interaction.followup.send("Could not find the ticket creator.", ephemeral=True)
            return
        except discord.HTTPException as e:
            logger.error(f"HTTPException fetching user {ticket_data['user_id']}: {e}")
            await interaction.followup.send("An error occurred while fetching user information.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"User Info: {member.display_name}",
            color=member.color if isinstance(member, discord.Member) else discord.Color.blue()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Username", value=f"`{member.name}`", inline=True)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Created Account", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=False)
        
        if isinstance(member, discord.Member):
            embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:R>", inline=False)
            roles = [role.mention for role in member.roles[1:]]  # Exclude @everyone
            if roles:
                embed.add_field(
                    name=f"Roles [{len(roles)}]",
                    value=" ".join(reversed(roles)) if len(roles) < 10 else "Too many to show.",
                    inline=False
                )
            else:
                embed.add_field(name="Roles", value="None", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

class TicketPanelView(discord.ui.View):
    def __init__(self, ticket_cog):
        super().__init__(timeout=None)
        self.ticket_cog = ticket_cog
        # Add the select menu here, it will be populated in cog_load or when panel is updated
        self.add_item(self.CategorySelect(self.ticket_cog))

    class CategorySelect(discord.ui.Select):
        def __init__(self, ticket_cog):
            self.ticket_cog = ticket_cog
            # Placeholder will be set dynamically
            super().__init__(placeholder="Select a category to open a ticket...", custom_id="ticket_panel_category_select", row=0)
        
        async def populate(self, guild_id: str):
            """Populates the select menu options based on guild categories."""
            guild_config = self.ticket_cog.ticket_manager.get_guild_config(guild_id)
            categories = guild_config.get("categories", {})
            
            self.options = [
                discord.SelectOption(
                    label=data['name'],
                    description=data.get('description', 'No description provided')[:100],  # Truncate to 100 chars
                    value=cat_id,
                    emoji=data.get('emoji', '🎫')
                )
                for cat_id, data in categories.items()
            ]
            logger.info(f"Populated {len(self.options)} categories for ticket panel in guild {guild_id}")
            
            if not self.options:
                self.disabled = True
                self.placeholder = "No categories available."
            else:
                self.disabled = False
                self.placeholder = "Select a category to open a ticket..."

        async def callback(self, interaction: discord.Interaction):
            """Handles the selection of a category."""
            if not interaction.guild:
                await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
                return
            category_id = self.values[0]
            await self.ticket_cog.handle_ticket_creation(interaction, category_id)

class CategoryModal(discord.ui.Modal):
    def __init__(self, ticket_cog, category_id: str = None, current_data: dict = None):
        super().__init__(title="Add Category" if category_id is None else "Edit Category")
        self.ticket_cog = ticket_cog
        self.category_id = category_id
        
        self.name = discord.ui.TextInput(
            label="Category Name",
            default=current_data.get("name") if current_data else None,
            required=True,
            max_length=50
        )
        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=current_data.get("description", "")[:100] if current_data else None,  # Truncate to 100 chars
            required=False,
            max_length=100
        )
        self.emoji = discord.ui.TextInput(
            label="Emoji (Optional)",
            default=current_data.get("emoji") if current_data else None,
            required=False,
            max_length=50
        )
        self.add_item(self.name)
        self.add_item(self.description)
        self.add_item(self.emoji)

    async def on_submit(self, interaction: discord.Interaction):
        logger.info(f"CategoryModal submitted by {interaction.user.id} with name: {self.name.value}")
        if not interaction.guild:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Error", "This command must be used in a server."),
                ephemeral=True
            )
            return
        
        guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(interaction.guild_id))
        
        # Prevent duplicate category names (case-insensitive)
        if not self.category_id:  # Only check for new categories
            if any(data["name"].lower() == self.name.value.lower() for cat_id, data in guild_config["categories"].items()):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Category Exists", f"A category named '{self.name.value}' already exists."),
                    ephemeral=True
                )
                return
        
        # Validate emoji
        if self.emoji.value:
            import re
            # Regex to check for Unicode emoji or Discord custom emoji format
            emoji_pattern = re.compile(r"^(?:[\U0001F000-\U0001FFFF]|<:[a-zA-Z0-9]+:[0-9]+>)$")
            if not emoji_pattern.match(self.emoji.value):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Invalid Emoji", "Please use a valid Unicode emoji or Discord custom emoji (e.g., <:emoji_name:1234567890>)."),
                    ephemeral=True
                )
                return

        await interaction.response.defer(ephemeral=True, thinking=True)
        view = RoleSelectView(
            ticket_cog=self.ticket_cog,
            category_id=self.category_id,
            temp_data={"name": self.name.value, "description": self.description.value, "emoji": self.emoji.value or "🎫"}
        )
        await view.populate_roles(interaction.guild)
        await interaction.followup.send("Select the staff roles for this category and click save.", view=view, ephemeral=True)

class RoleSelectView(discord.ui.View):
    def __init__(self, ticket_cog, temp_data: dict, category_id: str = None):
        super().__init__(timeout=180)
        self.ticket_cog = ticket_cog
        self.temp_data = temp_data
        self.category_id = category_id
        self.role_select = discord.ui.RoleSelect(placeholder="Select staff roles...", min_values=0, max_values=25, row=0)
        self.add_item(self.role_select)

    async def populate_roles(self, guild: discord.Guild):
        """Populates the role select menu with existing roles and pre-selects assigned roles."""
        if not guild:
            logger.error("No guild provided for RoleSelectView.populate_roles")
            return
        if self.category_id:
            guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(guild.id))
            category = guild_config["categories"].get(self.category_id, {})
            role_ids = category.get("staff_role_ids", [])
            # Ensure roles are valid and exist in the guild
            self.role_select.default_values = [guild.get_role(int(r_id)) for r_id in role_ids if guild.get_role(int(r_id))]
        logger.info(f"Populated roles for category '{self.temp_data['name']}' in guild {guild.id}")

    @discord.ui.button(label="Save Category", style=discord.ButtonStyle.success, row=1)
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info(f"Saving category '{self.temp_data['name']}' for guild {interaction.guild_id}, category_id: {self.category_id}")
        if not interaction.guild:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Error", "This command must be used in a server."),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        guild_config = self.ticket_cog.ticket_manager.get_guild_config(guild_id)
        
        self.temp_data["staff_role_ids"] = [str(role.id) for role in self.role_select.values]
        cat_id = self.category_id or str(uuid.uuid4())
        guild_config["categories"][cat_id] = self.temp_data
        await self.ticket_cog.ticket_manager.save_data()
        logger.info(f"Category '{self.temp_data['name']}' saved with ID {cat_id}")
        
        # Update the ticket panel to reflect the new category
        await self.ticket_cog.update_ticket_panel(interaction.guild)
        
        embed = EmbedBuilder.success("Category Saved", f"Category **{self.temp_data['name']}** has been successfully saved with {len(self.temp_data['staff_role_ids'])} staff roles.")
        await interaction.followup.send(embed=embed, ephemeral=True)
        
        # Disable the view after saving
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(content="Saved!", view=self)

class CustomWelcomeMessageModal(discord.ui.Modal, title="Set Custom Welcome Message"):
    message = discord.ui.TextInput(
        label="Custom Welcome Message",
        style=discord.TextStyle.paragraph,
        placeholder="Enter the welcome message. Use {user_mention} to mention the ticket creator.\nExample: 'Hello {user_mention}, thanks for reaching out!'",
        required=True,
        max_length=1000
    )

    def __init__(self, ticket_cog):
        super().__init__()
        self.ticket_cog = ticket_cog

    async def on_submit(self, interaction: discord.Interaction):
        message_content = self.message.value.strip()
        if not message_content:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Input", "The custom message cannot be empty."),
                ephemeral=True
            )
            return
        
        guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(interaction.guild_id))
        guild_config["custom_welcome_message"] = message_content
        guild_config["welcome_message_type"] = "custom"
        await self.ticket_cog.ticket_manager.save_data()
        
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Custom Message Set", "The custom welcome message has been saved."),
            ephemeral=True
        )

class WelcomeMessageConfigView(discord.ui.View):
    def __init__(self, ticket_cog):
        super().__init__(timeout=60)
        self.ticket_cog = ticket_cog
        self.add_item(self.WelcomeMessageSelect(self.ticket_cog))

    class WelcomeMessageSelect(discord.ui.Select):
        def __init__(self, ticket_cog):
            self.ticket_cog = ticket_cog
            options = [
                discord.SelectOption(label="Standard Message", value="standard", description="Use the default welcome message."),
                discord.SelectOption(label="Custom Message", value="custom", description="Set a custom welcome message.")
            ]
            super().__init__(placeholder="Choose a welcome message type...", options=options, row=0)

        async def callback(self, interaction: discord.Interaction):
            value = self.values[0]
            guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(interaction.guild_id))
            
            if value == "standard":
                guild_config["welcome_message_type"] = "standard"
                guild_config["custom_welcome_message"] = None # Clear custom message
                await self.ticket_cog.ticket_manager.save_data()
                await interaction.response.send_message(
                    embed=EmbedBuilder.success("Message Type Set", "The welcome message is now set to standard."),
                    ephemeral=True
                )
            elif value == "custom":
                # Open the modal to set the custom message
                await interaction.response.send_modal(CustomWelcomeMessageModal(self.ticket_cog))

class CategoryManagementView(discord.ui.View):
    def __init__(self, ticket_cog):
        super().__init__(timeout=180)
        self.ticket_cog = ticket_cog

    async def refresh(self, interaction: discord.Interaction):
        """Clears existing items and re-adds them based on current guild config."""
        logger.info(f"Refreshing CategoryManagementView for guild {interaction.guild_id}")
        self.clear_items()
        self.add_item(self.AddCategoryButton(self.ticket_cog)) # Always add the add button
        
        guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(interaction.guild_id))
        categories = guild_config.get("categories", {})
        
        if categories:
            # Add Edit Select Menu
            edit_select = self.CategorySelect(self.ticket_cog, "edit", "Select a category to EDIT...", row=1)
            await edit_select.populate(str(interaction.guild_id))
            if edit_select.options: # Only add if there are categories to edit
                self.add_item(edit_select)
            
            # Add Delete Select Menu
            delete_select = self.CategorySelect(self.ticket_cog, "delete", "Select a category to DELETE...", row=2)
            await delete_select.populate(str(interaction.guild_id))
            if delete_select.options: # Only add if there are categories to delete
                self.add_item(delete_select)
            
            logger.info(f"CategoryManagementView refreshed with {len(self.children)} components for guild {interaction.guild_id}")
        else:
            logger.info("No categories found; only AddCategoryButton added.")
        
        # Update the message with the new view
        embed = await self.generate_embed(str(interaction.guild_id))
        await interaction.message.edit(embed=embed, view=self)

    async def generate_embed(self, guild_id: str):
        """Generates the embed for the category management view."""
        guild_config = self.ticket_cog.ticket_manager.get_guild_config(guild_id)
        embed = EmbedBuilder.info("Manage Categories", "Use the buttons and dropdowns below to manage ticket categories.")
        
        categories = guild_config.get("categories", {})
        if categories:
            desc_lines = []
            for cat_id, data in categories.items():
                roles = [f"<@&{role_id}>" for role_id in data.get("staff_role_ids", [])]
                desc_lines.append(f"**{data.get('emoji', '🎫')} {data['name']}**\n> Staff: {', '.join(roles) if roles else 'None'}")
            embed.description = "\n".join(desc_lines)
        else:
            embed.description = "No categories created yet. Use the 'Add Category' button to get started."
        return embed

    class AddCategoryButton(discord.ui.Button):
        def __init__(self, ticket_cog):
            super().__init__(label="Add Category", style=discord.ButtonStyle.success, row=0)
            self.ticket_cog = ticket_cog

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_modal(CategoryModal(self.ticket_cog))

    class CategorySelect(discord.ui.Select):
        def __init__(self, ticket_cog, action: str, placeholder: str, row: int):
            self.ticket_cog = ticket_cog
            self.action = action
            super().__init__(placeholder=placeholder, row=row)

        async def populate(self, guild_id: str):
            """Populates the select menu options for editing or deleting categories."""
            guild_config = self.ticket_cog.ticket_manager.get_guild_config(guild_id)
            categories = guild_config.get("categories", {})
            self.options = [
                discord.SelectOption(label=data['name'], value=cat_id, emoji=data.get('emoji', '🎫'))
                for cat_id, data in categories.items()
            ]
            logger.info(f"Populated {len(self.options)} categories for {self.action} select in guild {guild_id}, row {self.row}")
            if not self.options:
                self.disabled = True

        async def callback(self, interaction: discord.Interaction):
            """Handles the selection of a category for editing or deletion."""
            cat_id = self.values[0]
            guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(interaction.guild_id))
            category_data = guild_config["categories"].get(cat_id)
            
            if not category_data:
                await interaction.response.send_message("This category no longer exists.", ephemeral=True)
                # Refresh the view to remove this option
                await self.view.refresh(interaction)
                return

            if self.action == "edit":
                await interaction.response.send_modal(CategoryModal(self.ticket_cog, cat_id, category_data))
            elif self.action == "delete":
                await interaction.response.defer(ephemeral=True)
                del guild_config["categories"][cat_id]
                await self.ticket_cog.ticket_manager.save_data()
                # Update the ticket panel to reflect the deletion
                await self.ticket_cog.update_ticket_panel(interaction.guild)
                # Refresh the management view
                await self.view.refresh(interaction)
                await interaction.followup.send(embed=EmbedBuilder.success("Category Deleted", f"Category **{category_data['name']}** has been deleted."), ephemeral=True)

class TicketSetupView(discord.ui.View):
    def __init__(self, ticket_cog):
        super().__init__(timeout=180)
        self.ticket_cog = ticket_cog

    async def _open_channel_select(self, interaction: discord.Interaction, channel_type: str):
        """Helper to open a channel select menu for setting panel or transcripts channels."""
        placeholder = f"Select a channel for ticket {channel_type}s"
        select_view = discord.ui.View(timeout=60)
        channel_select = discord.ui.ChannelSelect(placeholder=placeholder, channel_types=[discord.ChannelType.text])
        
        async def callback(inter: discord.Interaction):
            """Callback for when a channel is selected."""
            await inter.response.defer(ephemeral=True)
            selected_channel_id = inter.data['values'][0]
            channel = inter.guild.get_channel(int(selected_channel_id))
            
            if not channel:
                await inter.followup.send("Could not find the selected channel.", ephemeral=True)
                return

            guild_config = self.ticket_cog.ticket_manager.get_guild_config(str(inter.guild_id))
            guild_config[f"{channel_type}_channel_id"] = str(channel.id)
            await self.ticket_cog.ticket_manager.save_data()
            
            embed_title = f"{channel_type.capitalize()} Channel Set"
            embed_description = f"The {channel_type} channel is now {channel.mention}."
            embed_color = discord.Color.green()

            if channel_type == "panel":
                # If panel channel is set, try to create/update the panel message
                if not guild_config.get("categories"):
                    embed_description += "\n\n**Note:** No categories are configured yet. Add categories using 'Manage Categories' to enable the ticket panel."
                    embed_color = discord.Color.gold()
                else:
                    try:
                        await self.ticket_cog.create_ticket_panel(inter.guild)
                        embed_description += "\nThe ticket panel has been created/updated in the panel channel."
                    except discord.Forbidden as e:
                        embed_color = discord.Color.red()
                        embed_description = f"Set panel channel to {channel.mention}, but failed to create ticket panel: {e}. Check bot permissions."
                        logger.error(f"Permission error creating ticket panel: {e}")
                    except Exception as e:
                        embed_color = discord.Color.red()
                        embed_description = f"An unexpected error occurred while creating the ticket panel: {e}. Please check logs."
                        logger.error(f"Unexpected error creating ticket panel: {e}", exc_info=True)
            
            embed = EmbedBuilder.info(embed_title, embed_description)
            embed.color = embed_color
            await inter.followup.send(embed=embed, ephemeral=True)
            
            # Disable the select menu after selection
            for item in select_view.children:
                item.disabled = True
            await inter.edit_original_response(view=select_view)
        
        channel_select.callback = callback
        select_view.add_item(channel_select)
        await interaction.response.send_message(f"Please select the channel for **{channel_type}s**.", view=select_view, ephemeral=True)

    @discord.ui.button(label="Set Panel Channel", style=discord.ButtonStyle.primary, row=0)
    async def set_panel_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_channel_select(interaction, "panel")

    @discord.ui.button(label="Set Transcripts Channel", style=discord.ButtonStyle.primary, row=0)
    async def set_transcripts_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_channel_select(interaction, "transcripts")

    @discord.ui.button(label="Manage Categories", style=discord.ButtonStyle.secondary, row=1)
    async def manage_categories(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Error", "This command must be used in a server."),
                ephemeral=True
            )
            return
        
        # Create and refresh the CategoryManagementView
        view = CategoryManagementView(self.ticket_cog)
        await view.refresh(interaction) # This will send the initial message with categories

    @discord.ui.button(label="Configure Welcome Message", style=discord.ButtonStyle.secondary, row=2)
    async def configure_welcome_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = WelcomeMessageConfigView(self.ticket_cog)
        await interaction.response.send_message(
            "Select the welcome message type:",
            view=view,
            ephemeral=True
        )

# ----------------------------------------------------------------------------------
# 3. MAIN COG (TicketCommands)
# ----------------------------------------------------------------------------------
class TicketCommands(commands.Cog, name="Tickets"):
    def __init__(self, bot):
        self.bot = bot
        self.ticket_manager = TicketManager()
        self.persistent_views_added = False
        self.close_request_identifier = "[CLOSE_REQUEST]" # Identifier for close request messages

    async def cog_load(self):
        """Called when the cog is loaded. Sets up persistent views and starts the inactivity loop."""
        if not self.persistent_views_added:
            self.bot.add_view(PersistentTicketView(self))
            self.bot.add_view(TicketPanelView(self))
            self.persistent_views_added = True
            logger.info("Persistent Ticket Views added.")
        
        # Ensure active_tickets structure is valid for all guilds after loading data
        # This helps recover from potential data corruption or incomplete saves.
        for guild_id, guild_config in list(self.ticket_manager.tickets_data.items()):
            if "active_tickets" not in guild_config or not isinstance(guild_config["active_tickets"], dict):
                logger.warning(f"Correcting invalid 'active_tickets' structure for guild {guild_id}.")
                guild_config["active_tickets"] = {}
        # Save any corrections made to the structure
        await self.ticket_manager.save_data()

        # Start the loop to check for inactive tickets
        # Changed loop interval to 1 hour (from 6 hours) to be more responsive after restarts.
        self.check_inactive_tickets.start()
        logger.info("Tickets cog loaded and inactivity check started.")

    def cog_unload(self):
        """Called when the cog is unloaded. Cancels the inactivity loop."""
        self.check_inactive_tickets.cancel()
        logger.info("Tickets cog unloaded and inactivity check stopped.")

    async def is_staff_member(self, interaction: discord.Interaction, in_ticket_channel: bool = False) -> bool:
        """Checks if the user is a staff member, either globally or for a specific ticket."""
        if not isinstance(interaction.user, discord.Member):
            return False # Not a member (e.g., bot user)
        if interaction.user.guild_permissions.administrator:
            return True # Admins are always staff
        
        guild_config = self.ticket_manager.get_guild_config(str(interaction.guild_id))
        user_role_ids = {str(role.id) for role in interaction.user.roles}
        
        if in_ticket_channel:
            # Check if the user has staff roles for the specific ticket category
            ticket_data = guild_config.get("active_tickets", {}).get(str(interaction.channel.id))
            if ticket_data:
                category = guild_config.get("categories", {}).get(ticket_data.get("category_id"), {})
                staff_roles = set(category.get("staff_role_ids", []))
                return not staff_roles.isdisjoint(user_role_ids)
        
        # If not checking within a ticket, check if user has any staff role assigned to any category
        all_staff_roles = {role_id for cat in guild_config.get("categories", {}).values() for role_id in cat.get("staff_role_ids", [])}
        return not all_staff_roles.isdisjoint(user_role_ids)

    async def is_support_or_creator(self, interaction: discord.Interaction) -> bool:
        """Checks if the user is staff for the ticket or the ticket creator."""
        if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
            return False # Not in a thread
        
        if await self.is_staff_member(interaction, in_ticket_channel=True):
            return True # User is staff for this ticket
        
        guild_config = self.ticket_manager.get_guild_config(str(interaction.guild_id))
        # Ensure active_tickets is a dict before accessing
        if not isinstance(guild_config.get("active_tickets"), dict):
            return False # Cannot verify if data structure is invalid
            
        ticket_data = guild_config.get("active_tickets", {}).get(str(interaction.channel.id))
        
        # Check if the user is the creator of the ticket
        return ticket_data and str(interaction.user.id) == ticket_data.get("user_id")

    async def create_ticket_panel(self, guild: discord.Guild):
        """Creates or updates the ticket panel message in the configured panel channel."""
        guild_id = str(guild.id)
        guild_config = self.ticket_manager.get_guild_config(guild_id)
        panel_channel_id = guild_config.get("panel_channel_id")
        
        if not panel_channel_id:
            logger.warning(f"No panel channel ID configured for guild {guild_id}. Cannot create ticket panel.")
            return

        channel = guild.get_channel(int(panel_channel_id))
        if not channel or not isinstance(channel, discord.TextChannel):
            logger.warning(f"Panel channel {panel_channel_id} not found or invalid in guild {guild_id}. Clearing panel config.")
            guild_config["panel_channel_id"] = None
            guild_config["panel_message_id"] = None
            await self.ticket_manager.save_data()
            return

        # Ensure categories exist before trying to create the panel
        categories = guild_config.get("categories", {})
        if not categories:
            logger.info(f"No categories configured for guild {guild_id}. Skipping ticket panel creation.")
            # Optionally clear old panel message if no categories exist
            if panel_message_id := guild_config.get("panel_message_id"):
                try:
                    msg = await channel.fetch_message(int(panel_message_id))
                    await msg.edit(content="Ticket panel is disabled as no categories are configured.", embed=None, view=None)
                except (discord.NotFound, discord.Forbidden):
                    pass # Ignore if message is gone or bot lacks permissions
            guild_config["panel_message_id"] = None # Clear message ID if panel is effectively disabled
            await self.ticket_manager.save_data()
            return

        # Create or get the view for the panel
        view = TicketPanelView(self)
        # Populate the select menu with current categories
        for item in view.children:
            if isinstance(item, TicketPanelView.CategorySelect):
                await item.populate(guild_id)
        
        # Build the embed for the ticket panel
        embed = EmbedBuilder.info("Support Tickets", "Select a category below to create a ticket.")
        embed.color = guild_config.get("panel_color", 0x3498db)
        
        if categories:
            desc_lines = []
            for cat_id, data in categories.items():
                # Truncate description to fit embed field limits
                short_desc = data.get('description', 'No description provided')[:100]
                desc_lines.append(f"**{data.get('emoji', '🎫')} {data['name']}**: {short_desc}")
            embed.add_field(name="Categories", value="\n".join(desc_lines), inline=False)
        
        # Handle creating or editing the panel message
        try:
            message_id = guild_config.get("panel_message_id")
            if message_id:
                # Try to edit the existing message
                try:
                    msg = await channel.fetch_message(int(message_id))
                    await msg.edit(embed=embed, view=view)
                    logger.info(f"Edited existing panel message {message_id} in guild {guild_id}")
                except discord.NotFound:
                    logger.warning(f"Panel message {message_id} not found in guild {guild_id}. Creating a new one.")
                    guild_config["panel_message_id"] = None # Clear invalid ID
                    await self.ticket_manager.save_data()
                    msg = await channel.send(embed=embed, view=view)
                    guild_config["panel_message_id"] = str(msg.id)
                    await self.ticket_manager.save_data()
                except discord.Forbidden as e:
                    logger.error(f"Permission error editing panel message {message_id} in guild {guild_id}: {e}")
                    # Attempt to send a new message if editing fails due to permissions
                    guild_config["panel_message_id"] = None
                    await self.ticket_manager.save_data()
                    msg = await channel.send(embed=embed, view=view)
                    guild_config["panel_message_id"] = str(msg.id)
                    await self.ticket_manager.save_data()
            else:
                # Create a new message if no message ID is stored
                msg = await channel.send(embed=embed, view=view)
                guild_config["panel_message_id"] = str(msg.id)
                await self.ticket_manager.save_data()
                logger.info(f"Created new panel message {msg.id} in guild {guild_id}")
        except discord.HTTPException as e:
            logger.error(f"HTTPException while creating/editing ticket panel in guild {guild_id}: {e}")
            error_msg = f"Failed to create/edit ticket panel: {e.text}. Check category descriptions (must be ≤100 chars)."
            if transcript_channel_id := guild_config.get("transcripts_channel_id"):
                log_channel = guild.get_channel(int(transcript_channel_id))
                if log_channel:
                    await log_channel.send(embed=EmbedBuilder.error("Panel Update Failed", error_msg))
            guild_config["panel_message_id"] = None # Clear message ID if creation failed
            await self.ticket_manager.save_data()
        except discord.Forbidden as e:
            logger.error(f"Permission error creating/editing ticket panel in guild {guild_id}: {e}")
            if transcript_channel_id := guild_config.get("transcripts_channel_id"):
                log_channel = guild.get_channel(int(transcript_channel_id))
                if log_channel:
                    await log_channel.send(embed=EmbedBuilder.error("Panel Update Failed", f"Could not create/edit ticket panel due to permissions: {e}. Check bot permissions in <#{panel_channel_id}>."))
            guild_config["panel_message_id"] = None
            await self.ticket_manager.save_data()
        except Exception as e:
            logger.error(f"Unexpected error creating ticket panel in guild {guild_id}: {e}", exc_info=True)
            if transcript_channel_id := guild_config.get("transcripts_channel_id"):
                log_channel = guild.get_channel(int(transcript_channel_id))
                if log_channel:
                    await log_channel.send(embed=EmbedBuilder.error("Panel Update Failed", f"Unexpected error creating ticket panel: {e}. Please contact support."))
            guild_config["panel_message_id"] = None
            await self.ticket_manager.save_data()

    async def update_ticket_panel(self, guild: discord.Guild):
        """Helper to trigger the creation/update of the ticket panel."""
        logger.info(f"Updating ticket panel for guild {guild.id}")
        await self.create_ticket_panel(guild)

    async def handle_ticket_creation(self, interaction: discord.Interaction, category_id: str):
        """Handles the process of creating a new ticket thread."""
        await interaction.response.defer(ephemeral=True)
        guild_config = self.ticket_manager.get_guild_config(str(interaction.guild_id))
        category_data = guild_config.get("categories", {}).get(category_id)
        
        if not category_data:
            await interaction.followup.send("This category no longer exists or is invalid.", ephemeral=True)
            return
        
        # Increment ticket counter and save
        guild_config["counter"] += 1
        ticket_num = guild_config["counter"]
        await self.ticket_manager.save_data()

        ticket_name = f"{category_data['name']}-{ticket_num}"
        try:
            # Create a private thread for the ticket
            thread = await interaction.channel.create_thread(name=ticket_name, type=discord.ChannelType.private_thread)
            await interaction.followup.send(embed=EmbedBuilder.success("Ticket Created", f"Your ticket is ready: {thread.mention}"), ephemeral=True)
            
            # Store active ticket data
            guild_config["active_tickets"][str(thread.id)] = {
                "user_id": str(interaction.user.id),
                "ticket_number": ticket_num,
                "category_id": category_id,
                "category_name": category_data["name"],
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            await self.ticket_manager.save_data()

            # Add the user who created the ticket to the thread
            await thread.add_user(interaction.user)
            
            # Mention staff roles and send welcome message
            staff_mentions = " ".join([f"<@&{role_id}>" for role_id in category_data.get("staff_role_ids", [])])
            
            welcome_message_content = ""
            if guild_config.get("welcome_message_type") == "custom" and guild_config.get("custom_welcome_message"):
                welcome_message_content = guild_config["custom_welcome_message"].format(user_mention=interaction.user.mention)
            else: # Default to standard message
                welcome_message_content = f"Thank you for creating a ticket, {interaction.user.mention}! Our staff will assist you shortly."
            
            welcome_embed = EmbedBuilder.info(f"Welcome to {category_data['name']}", welcome_message_content)
            
            # Send the welcome message with persistent buttons
            await thread.send(content=staff_mentions, embed=welcome_embed, view=PersistentTicketView(self))

            # Optionally, run moderation command to show user info
            moderation_cog = self.bot.get_cog("ModerationCommands")
            if moderation_cog and isinstance(moderation_cog, ModerationCommands):
                # Pass the interaction user as the member to get info for
                await moderation_cog.memberinfo(interaction, member=interaction.user, channel=thread)
            else:
                logger.warning("ModerationCommands cog not found or not properly loaded; memberinfo not executed.")

        except discord.Forbidden as e:
            await interaction.followup.send(f"I don't have permission to create threads or manage users here: {e}", ephemeral=True)
        except KeyError as e:
            logger.error(f"KeyError during ticket creation: {e}. Likely an issue with custom welcome message placeholder.")
            await interaction.followup.send(
                embed=EmbedBuilder.error("Invalid Custom Message", "The custom welcome message contains an invalid placeholder. Please update it."),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"An unexpected error occurred during ticket creation: {e}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred while creating your ticket. Please try again or contact support.", ephemeral=True)

    async def handle_close_ticket(self, interaction: discord.Interaction, reason: str):
        """Handles the closing of a ticket thread, including logging and DMing the user."""
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        
        if not isinstance(channel, discord.Thread):
            await interaction.followup.send("This command can only be used within a ticket thread.", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        guild_config = self.ticket_manager.get_guild_config(guild_id)
        
        # Ensure active_tickets is a dict before accessing
        if not isinstance(guild_config.get("active_tickets"), dict):
            logger.warning(f"Active tickets data is not a dictionary for guild {guild_id}. Cannot process close.")
            await interaction.followup.send("Ticket data is not properly initialized. Cannot close ticket.", ephemeral=True)
            return
            
        ticket_data = guild_config.get("active_tickets", {}).get(str(channel.id))
        if not ticket_data:
            await interaction.followup.send("This channel is not recognized as an active ticket.", ephemeral=True)
            return

        # Get user and staff info for logging
        closer = interaction.user
        closer_id = closer.id
        creator_id = ticket_data.get("user_id")
        
        try:
            creator = await self.bot.fetch_user(int(creator_id))
        except (discord.NotFound, ValueError):
            logger.warning(f"Could not fetch ticket creator {creator_id} for ticket {channel.id}.")
            creator = None # Set creator to None if not found
        except Exception as e:
            logger.error(f"Error fetching ticket creator {creator_id}: {e}", exc_info=True)
            creator = None

        # Prepare transcript embed
        transcript_embed = EmbedBuilder.info(
            f"Ticket #{ticket_data['ticket_number']} Closed",
            f"[View Thread](https://discord.com/channels/{guild_id}/{channel.id})"
        )
        transcript_embed.add_field(name="Category", value=ticket_data["category_name"], inline=True)
        transcript_embed.add_field(name="Closed By", value=format_user(closer), inline=True)
        transcript_embed.add_field(name="Reason", value=reason, inline=False)
        
        claimed_by_id = ticket_data.get("claimed_by")
        if claimed_by_id:
            try:
                claimed_by_user = await self.bot.fetch_user(int(claimed_by_id))
                transcript_embed.add_field(name="Claimed By", value=format_user(claimed_by_user), inline=True)
            except (discord.NotFound, ValueError):
                logger.warning(f"Could not fetch claimed_by user {claimed_by_id} for ticket {channel.id}.")
            except Exception as e:
                logger.error(f"Error fetching claimed_by user {claimed_by_id}: {e}", exc_info=True)

        # Create a view with a link to the thread
        class ViewThreadView(discord.ui.View):
            def __init__(self):
                super().__init__()
                self.add_item(discord.ui.Button(
                    label="View Thread",
                    url=f"https://discord.com/channels/{guild_id}/{channel.id}",
                    style=discord.ButtonStyle.link
                ))
        view = ViewThreadView()

        # Log transcript to the transcripts channel if configured
        if transcript_channel_id := guild_config.get("transcripts_channel_id"):
            try:
                log_channel = interaction.guild.get_channel(int(transcript_channel_id))
                if log_channel:
                    await log_channel.send(embed=transcript_embed, view=view)
                else:
                    logger.warning(f"Transcripts channel {transcript_channel_id} not found in guild {guild_id}. Cannot log transcript.")
            except discord.Forbidden as e:
                logger.error(f"Permission error logging transcript for ticket {channel.id}: {e}")
            except Exception as e:
                logger.error(f"Error logging transcript for ticket {channel.id}: {e}", exc_info=True)

        # DM the user about the ticket closure
        if creator:
            try:
                await creator.send(embed=transcript_embed, view=view)
            except discord.Forbidden:
                logger.warning(f"Could not DM user {creator.id} about ticket closure.")
            except Exception as e:
                logger.error(f"Error DMing user {creator.id} about ticket closure: {e}", exc_info=True)

        # Remove ticket from active tickets and save
        del guild_config["active_tickets"][str(channel.id)]
        await self.ticket_manager.save_data()
        
        await interaction.followup.send("Ticket has been closed and archived.", ephemeral=True)
        
        # Archive and lock the thread
        try:
            await channel.edit(archived=True, locked=True)
        except discord.Forbidden:
            logger.warning(f"Could not archive/lock thread {channel.id} due to permissions.")
        except Exception as e:
            logger.error(f"Error archiving/locking thread {channel.id}: {e}", exc_info=True)
        
        # Log the action
        log_action(
            guild_id=interaction.guild_id,
            user_id=closer_id,
            action=f"Closed ticket #{ticket_data['ticket_number']} (Category: {ticket_data['category_name']}) with reason: {reason}"
        )

    # Changed loop interval to 1 hour (from 6 hours) to be more responsive after restarts.
    @tasks.loop(hours=1)
    async def check_inactive_tickets(self):
        """Periodically checks for inactive tickets and prompts for closure if enabled."""
        logger.info("Running hourly check for inactive tickets...")
        
        # Iterate over a copy of the items to allow modification during iteration
        for guild_id, guild_config in list(self.ticket_manager.tickets_data.items()):
            inactive_days = guild_config.get("inactive_close_after_days", 3)
            # Skip if inactivity warning is disabled or days are set to 0 or less
            if not guild_config.get("inactive_warning_enabled", True) or inactive_days <= 0:
                continue
            
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                logger.warning(f"Guild {guild_id} not found. Skipping inactivity check for this guild.")
                continue
            
            now = datetime.now(timezone.utc)
            inactive_threshold = now - timedelta(days=inactive_days)
            
            # Iterate over a copy of active_tickets to allow modification
            active_tickets = guild_config.get("active_tickets", {})
            if not isinstance(active_tickets, dict): # Defensive check
                logger.warning(f"Invalid 'active_tickets' structure for guild {guild_id}. Resetting.")
                guild_config["active_tickets"] = {}
                continue

            for ticket_id, ticket_data in list(active_tickets.items()):
                try:
                    # Fetch the thread object using the ticket_id (which is the thread ID)
                    channel = guild.get_thread(int(ticket_id))
                    
                    if not channel:
                        # If the thread is no longer found, remove it from active tickets
                        logger.warning(f"Thread {ticket_id} for ticket in guild {guild_id} not found. Removing from active tickets.")
                        del guild_config["active_tickets"][ticket_id]
                        continue
                    
                    # Determine the last activity time in the thread
                    last_message = await channel.fetch_message(channel.last_message_id) if channel.last_message_id else None
                    last_activity_time = last_message.created_at if last_message else channel.created_at
                    
                    # Check if the ticket is inactive
                    if last_activity_time < inactive_threshold:
                        # Check if a close request is already pending
                        is_close_request_pending = False
                        async for msg in channel.history(limit=10): # Check recent messages for the identifier
                            if msg.author == self.bot.user and self.close_request_identifier in msg.content:
                                is_close_request_pending = True
                                break
                        
                        # If no close request is pending, send one
                        if not is_close_request_pending:
                            logger.info(f"Ticket {ticket_id} in guild {guild_id} is inactive. Sending close request.")
                            # Use the bot's user as the requester for inactivity prompts
                            await self._send_close_request(channel, self.bot.user, from_inactivity=True)
                            
                except discord.NotFound:
                    # This exception is already handled by the 'if not channel:' check, but good to have as a fallback.
                    logger.warning(f"Thread {ticket_id} for ticket in guild {guild_id} not found (discord.NotFound). Cleaning up.")
                    del guild_config["active_tickets"][ticket_id]
                except discord.Forbidden as e:
                    logger.error(f"Permission error checking inactivity for ticket {ticket_id} in guild {guild_id}: {e}")
                except Exception as e:
                    logger.error(f"Error checking inactivity for ticket {ticket_id} in guild {guild_id}: {e}", exc_info=True)
        
        # Save any changes made to active_tickets (e.g., removed stale entries)
        await self.ticket_manager.save_data()

    async def _send_close_request(self, channel: discord.Thread, requester: discord.Member, from_inactivity: bool = False):
        """Sends a close request message to the ticket thread and DMs the creator."""
        guild_id = str(channel.guild.id)
        guild_config = self.ticket_manager.get_guild_config(guild_id)
        
        # Ensure active_tickets is a dict before accessing
        if not isinstance(guild_config.get("active_tickets"), dict):
            logger.warning(f"Active tickets data is not a dictionary for guild {guild_id}. Cannot send close request.")
            return
            
        ticket_data = guild_config.get("active_tickets", {}).get(str(channel.id))
        if not ticket_data:
            logger.warning(f"Ticket data not found for channel {channel.id} when sending close request.")
            return
        
        creator_id = ticket_data.get("user_id")
        try:
            creator = await self.bot.fetch_user(int(creator_id))
        except (discord.NotFound, ValueError):
            logger.warning(f"Could not fetch ticket creator {creator_id} for ticket {channel.id}.")
            creator = None
        except Exception as e:
            logger.error(f"Error fetching ticket creator {creator_id}: {e}", exc_info=True)
            creator = None

        # Prepare embed for DM and transcript log
        embed_title = f"Ticket #{ticket_data['ticket_number']} Closure Request"
        embed_description = ""
        if from_inactivity:
            embed_description = "This ticket has been marked as inactive. If you still need assistance, please click 'Keep Ticket Open' in the channel."
        else:
            embed_description = f"A request to close this ticket has been made by {requester.mention}."
        
        dm_embed = EmbedBuilder.info(embed_title, embed_description)
        dm_embed.add_field(name="Ticket", value=channel.mention, inline=False)
        
        # Prepare embed for the ticket channel
        channel_embed_title = "Ticket Closure Request"
        channel_embed_description = ""
        if from_inactivity:
            channel_embed_description = "This ticket has been marked for closure due to inactivity. If you still require assistance, please click **Keep Ticket Open**."
        else:
            channel_embed_description = f"{requester.mention} has requested to close this ticket. Please confirm the action below."
        
        channel_embed = EmbedBuilder.warning(channel_embed_title, channel_embed_description)
        
        # Add link to thread in DM embed
        dm_embed.add_field(name="Ticket", value=channel.mention, inline=False)

        # Send DM to the creator
        if creator:
            try:
                await creator.send(embed=dm_embed)
            except discord.Forbidden:
                logger.warning(f"Could not DM user {creator.id} about ticket closure request.")
            except Exception as e:
                logger.error(f"Error DMing user {creator.id} about ticket closure request: {e}", exc_info=True)

        # Send the close request message in the ticket channel
        view = CloseRequestView(self, requester, creator_id)
        try:
            await channel.send(
                content=f"{creator.mention} {self.close_request_identifier}" if creator else f"{self.close_request_identifier}",
                embed=channel_embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(users=[creator]) if creator else discord.AllowedMentions.none()
            )
        except discord.Forbidden:
            logger.warning(f"Could not send close request message in channel {channel.id} due to permissions.")
        except Exception as e:
            logger.error(f"Error sending close request message in channel {channel.id}: {e}", exc_info=True)

    # --- Ticket Commands Group ---
    ticket_group = app_commands.Group(name="ticket", description="Ticket management commands")

    @ticket_group.command(name="setup", description="Initiate the interactive ticket system setup.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_setup(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Error", "This command must be used in a server."),
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=EmbedBuilder.info(
                "Ticket System Setup",
                "Use the buttons below to configure the ticket system."
            ),
            view=TicketSetupView(self),
            ephemeral=True
        )

    @ticket_group.command(name="request_close", description="Manually ask the user to confirm if the ticket can be closed.")
    @app_commands.checks.has_permissions(manage_channels=True) # Staff can request close
    async def ticket_request_close(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Channel", "This must be used in a ticket thread."),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        # Send the close request, indicating it's from a staff member
        await self._send_close_request(interaction.channel, interaction.user)
        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Request Sent",
                "A close request has been sent to the ticket creator."
            ),
            ephemeral=True
        )

    @ticket_group.command(name="close", description="Close the current ticket thread.")
    @app_commands.describe(reason="The reason for closing this ticket.")
    @app_commands.checks.has_permissions(manage_channels=True) # Allow staff to close directly
    async def ticket_close(self, interaction: discord.Interaction, reason: str = "No reason provided."):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This can only be used in a ticket thread.", ephemeral=True)
            return
        
        # Check if the user is staff or the ticket creator
        if await self.is_support_or_creator(interaction):
            await self.handle_close_ticket(interaction, reason)
        else:
            await interaction.response.send_message(
                "You do not have permission to close this ticket.", ephemeral=True)

    @ticket_group.command(name="add", description="Add a user to this ticket thread.")
    @app_commands.describe(user="The user to add to the ticket.")
    @app_commands.checks.has_permissions(manage_channels=True) # Staff can add users
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Invalid Channel",
                    "This command must be used inside a ticket thread."
                ),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        # Check if the user has permission to add users
        if await self.is_support_or_creator(interaction):
            try:
                await interaction.channel.add_user(user)
                await interaction.followup.send(
                    embed=EmbedBuilder.success(
                        "User Added",
                        f"{user.mention} has been added to the ticket."
                    ),
                    ephemeral=True
                )
                # Notify in the ticket thread
                await interaction.channel.send(
                    embed=EmbedBuilder.info(
                        "Ticket Update",
                        f"{user.mention} was added to the ticket by {interaction.user.mention}."
                    )
                )
                log_action(
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    action=f"Added {user.name} to ticket in channel {interaction.channel.id}"
                )
            except discord.Forbidden:
                await interaction.followup.send("I don't have permission to add users to this thread.", ephemeral=True)
            except Exception as e:
                logger.error(f"Error adding user to ticket: {e}", exc_info=True)
                await interaction.followup.send("An error occurred while adding the user.", ephemeral=True)
        else:
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "Permission Denied",
                    "You do not have permission to add users to this ticket."
                ),
                ephemeral=True
            )

    @ticket_group.command(name="closerequest", description="Request to close the current ticket thread.")
    @app_commands.checks.has_permissions(manage_channels=True) # Allow staff to request close
    async def closerequest(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            return await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Channel", "This must be used in a ticket thread."),
                ephemeral=True
            )
        
        guild_config = self.ticket_manager.get_guild_config(str(interaction.guild_id))
        # Ensure active_tickets is a dict before accessing
        if not isinstance(guild_config.get("active_tickets"), dict):
            logger.warning(f"Active tickets data is not a dictionary for guild {interaction.guild_id}. Cannot process closerequest.")
            return await interaction.response.send_message("Ticket data is not properly initialized. Cannot request close.", ephemeral=True)

        if str(interaction.channel.id) not in guild_config.get("active_tickets", {}):
            return await interaction.response.send_message(
                embed=EmbedBuilder.error("Invalid Channel", "This is not an active ticket."),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        # Send the close request, indicating it's from a staff member
        await self._send_close_request(interaction.channel, interaction.user)
        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Request Sent",
                "A close request has been sent to the ticket creator."
            ),
            ephemeral=True
        )

    @ticket_group.command(name="remove", description="Remove a user from this ticket thread.")
    @app_commands.describe(user="The user to remove from the ticket.")
    @app_commands.checks.has_permissions(manage_channels=True) # Staff can remove users
    async def ticket_remove(self, interaction: discord.Interaction, user: discord.Member):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Invalid Channel",
                    "This command must be used inside a ticket thread."
                ),
                ephemeral=True
            )
            return
        
        guild_config = self.ticket_manager.get_guild_config(str(interaction.guild_id))
        # Ensure active_tickets is a dict before accessing
        if not isinstance(guild_config.get("active_tickets"), dict):
            logger.warning(f"Active tickets data is not a dictionary for guild {interaction.guild_id}. Cannot process remove.")
            return await interaction.response.send_message("Ticket data is not properly initialized. Cannot remove user.", ephemeral=True)

        ticket_data = guild_config.get("active_tickets", {}).get(str(interaction.channel.id))
        
        # Prevent removing the ticket creator
        if ticket_data and str(user.id) == ticket_data.get("user_id"):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Invalid Action",
                    "You cannot remove the ticket creator."
                ),
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        # Check if the user has permission to remove users
        if await self.is_support_or_creator(interaction):
            try:
                await interaction.channel.remove_user(user)
                await interaction.followup.send(
                    embed=EmbedBuilder.success(
                        "User Removed",
                        f"{user.mention} has been removed from the ticket."
                    ),
                    ephemeral=True
                )
                # Notify in the ticket thread
                await interaction.channel.send(
                    embed=EmbedBuilder.info(
                        "Ticket Update",
                        f"{user.mention} was removed from the ticket by {interaction.user.mention}."
                    )
                )
                log_action(
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    action=f"Removed {user.name} from ticket in channel {interaction.channel.id}"
                )
            except discord.Forbidden:
                await interaction.followup.send("I don't have permission to remove users from this thread.", ephemeral=True)
            except Exception as e:
                logger.error(f"Error removing user from ticket: {e}", exc_info=True)
                await interaction.followup.send("An error occurred while removing the user.", ephemeral=True)
        else:
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "Permission Denied",
                    "You do not have permission to remove users from this ticket."
                ),
                ephemeral=True
            )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handles errors for commands within this cog."""
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Permission Denied",
                        "You do not have the required permissions (e.g., Administrator or Manage Channels) for this command."
                    ),
                    ephemeral=True
                )
        elif isinstance(error, app_commands.CommandInvokeError):
            # Log the original exception
            logger.error(f"Command invoke error in TicketCommands: {error.original_error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Unexpected Error",
                        "An unexpected error occurred while executing the command. This has been logged."
                    ),
                    ephemeral=True
                )
        else:
            # Handle other potential errors
            logger.error(f"Unhandled error in TicketCommands: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Unexpected Error",
                        "An unexpected error occurred. This has been logged for the developers."
                    ),
                    ephemeral=True
                )

async def setup(bot: commands.Bot):
    """Adds the TicketCommands cog to the bot."""
    await bot.add_cog(TicketCommands(bot))