from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional, Union
import uuid
import time

# Assuming these utils are in a 'utils' directory relative to this cog
# If not, adjust the import paths accordingly
# Make sure these utils exist and are correctly implemented
try:
    from utils.permissions import is_admin
    from utils.logging import log_action
    from utils.embeds import EmbedBuilder
    from utils.user_blacklist_manager import UserBlacklistManager
except ImportError as e:
    print(f"ERROR: Failed to import utility modules: {e}")
    print("Please ensure 'utils/permissions.py', 'utils/logging.py', 'utils/embeds.py', and 'utils/user_blacklist_manager.py' exist and are correctly implemented.")
    # Placeholder implementations if utils are missing, for development/testing purposes
    # In a real bot, you'd want these modules to be functional.
    class MockUtil:
        def __init__(self, name="Mock"): self.name = name
        async def __call__(self, *args, **kwargs): return True # For permissions/logging
        def __getattr__(self, item): return self # For simple methods

    is_admin = MockUtil("is_admin")
    log_action = MockUtil("log_action")
    EmbedBuilder = MockUtil("EmbedBuilder")
    UserBlacklistManager = MockUtil("UserBlacklistManager")
    # You might want to print a warning here if these mocks are used in production.


logger = logging.getLogger('bot.applications')

# ----------------------------------------------------------------------------------
# Application Data Management
# ----------------------------------------------------------------------------------
class ApplicationManager:
    """Manages the loading, saving, and retrieval of application data."""
    def __init__(self):
        self.applications_data_file = "data/applications.json"
        os.makedirs(os.path.dirname(self.applications_data_file), exist_ok=True)
        self.applications_data = self.load_data()
        
    def load_data(self) -> Dict:
        """Loads application data from the JSON file."""
        try:
            if os.path.exists(self.applications_data_file):
                with open(self.applications_data_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content: return {} # Return empty dict if file is empty
                    return json.loads(content)
            else:
                # Ensure the directory exists before creating the file
                os.makedirs(os.path.dirname(self.applications_data_file), exist_ok=True)
                with open(self.applications_data_file, 'w', encoding='utf-8') as f: json.dump({}, f)
                return {}
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {self.applications_data_file}: {e}. Initializing with empty data.", exc_info=True)
            return {}
        except Exception as e:
            logger.error(f"Error loading application data from {self.applications_data_file}: {e}", exc_info=True)
            return {}
            
    def save_data(self) -> None:
        """Saves the current application data to the JSON file."""
        try:
            with open(self.applications_data_file, 'w', encoding='utf-8') as f:
                json.dump(self.applications_data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving application data to {self.applications_data_file}: {e}", exc_info=True)
    
    def get_guild_config(self, guild_id: str) -> Dict:
        """Retrieves or creates the configuration for a specific guild."""
        guild_id_str = str(guild_id) 
        if guild_id_str not in self.applications_data:
            self.applications_data[guild_id_str] = {
                "application_types": {}, "applications": {}, "counter": 0,
                "panel_color": 0x3498db, "panel_message_id": None, "panel_channel_id": None,
                "log_channel_id": None, "reviewer_roles": [], "applicant_roles": [],
                "last_panel_update": None, "last_panel_error": None
            }
            # Saving is handled externally when modifications occur, not just on retrieval.
        
        # Ensure default keys are present for guilds that might have been created before certain keys existed
        # This prevents KeyErrors if the config structure changes over time.
        default_keys = {
            "application_types": {}, "applications": {}, "counter": 0,
            "panel_color": 0x3498db, "panel_message_id": None, "panel_channel_id": None,
            "log_channel_id": None, "reviewer_roles": [], "applicant_roles": [],
            "last_panel_update": None, "last_panel_error": None
        }
        for key, value in default_keys.items():
            self.applications_data[guild_id_str].setdefault(key, value)
        return self.applications_data[guild_id_str]
    
    def get_application(self, guild_id: str, application_id: str) -> Optional[Dict]:
        """Retrieves a specific application by its ID."""
        guild_config = self.get_guild_config(str(guild_id))
        return guild_config.get("applications", {}).get(str(application_id))

    def is_blacklisted(self, guild_id: str, type_id: str, member: discord.Member, user_blacklist_manager: Optional[UserBlacklistManager]) -> bool:
        """Checks if a member is blacklisted from a specific application type (by role or manager)."""
        guild_id_str, type_id_str, user_id_str = str(guild_id), str(type_id), str(member.id)
        guild_config = self.get_guild_config(guild_id_str)
        app_type_data = guild_config.get("application_types", {}).get(type_id_str, {})

        if not isinstance(member, discord.Member):
            logger.warning(f"is_blacklisted called with non-Member: {type(member)} for user {member.id if hasattr(member, 'id') else member} in guild {guild_id_str}.")
            # Fallback check if user is not a Member but UserBlacklistManager is available
            if user_blacklist_manager and user_blacklist_manager.is_application_blacklisted(guild_id_str, user_id_str, type_id_str):
                logger.debug(f"User {user_id_str} blacklisted from type {type_id_str} by manager (non-member context).")
                return True
            return False

        # Check if member has any blacklisted roles for this type
        member_role_ids = {str(role.id) for role in member.roles}
        type_blacklisted_roles = {str(r_id) for r_id in app_type_data.get("blacklisted_roles", [])}
        if any(pr_id in member_role_ids for pr_id in type_blacklisted_roles):
            logger.debug(f"User {user_id_str} blacklisted from type {type_id_str} by role.")
            return True

        # Check against the global user blacklist manager
        if user_blacklist_manager and user_blacklist_manager.is_application_blacklisted(guild_id_str, user_id_str, type_id_str):
            logger.debug(f"User {user_id_str} blacklisted from type {type_id_str} by manager.")
            return True
        elif not user_blacklist_manager:
            logger.warning(f"UserBlacklistManager not provided for blacklist check in guild {guild_id_str}.")
            
        return False # Not blacklisted

# ----------------------------------------------------------------------------------
# UI Views & Modals
# ----------------------------------------------------------------------------------

class ConfirmActionView(discord.ui.View):
    """A generic confirmation view with Yes/No buttons."""
    def __init__(self, timeout=60, custom_id_prefix="confirm"):
        super().__init__(timeout=timeout)
        self.value: Optional[bool] = None # True for Yes, False for No
        self.callback_action = None # Function to call after user interacts
        self.yes_button_id = f"{custom_id_prefix}_yes"
        self.no_button_id = f"{custom_id_prefix}_no"

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger, custom_id="confirm_yes_btn")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        if self.callback_action:
            await self.callback_action(interaction)
        else:
            await interaction.response.defer() # Defer if no specific callback action
        self.stop() # Stop the view after interaction

    @discord.ui.button(label="No", style=discord.ButtonStyle.grey, custom_id="confirm_no_btn")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        if self.callback_action:
            await self.callback_action(interaction)
        else:
            await interaction.response.defer()
        self.stop()

class ApplicationPanelView(discord.ui.View):
    """View for the main application panel, allowing users to select an application type."""
    def __init__(self, bot: commands.Bot, application_manager: ApplicationManager):
        super().__init__(timeout=None) # View persists indefinitely
        self.bot = bot
        self.application_manager = application_manager
        self.select_custom_id = f"app_panel_select_{uuid.uuid4()}" # Unique ID for select menu

    async def select_callback(self, interaction: discord.Interaction):
        """Callback for when a user selects an application type."""
        try:
            selected_value = interaction.data["values"][0]
            # Handle placeholder selection if no types are available or eligible
            if selected_value == "no_options_placeholder":
                await interaction.response.send_message(embed=EmbedBuilder.info("No Applications", "There are no application types currently available or eligible for you."), ephemeral=True)
                return

            type_id = selected_value
            logger.debug(f"Application panel: Type '{type_id}' selected by {interaction.user.id} in guild {interaction.guild_id}")

            cog = self.bot.get_cog("ApplicationCommands")
            if not cog:
                logger.error("ApplicationCommands cog not found when handling panel selection.")
                await interaction.response.send_message(embed=EmbedBuilder.error("System Unavailable", "Application system is temporarily unavailable."), ephemeral=True)
                return

            # Start the application process for the selected type
            await cog.start_application(interaction, type_id)
        except Exception as e:
            logger.error(f"Error in ApplicationPanelView select_callback: {e}", exc_info=True)
            await interaction.response.send_message(embed=EmbedBuilder.error("Error", "Failed to start the application process."), ephemeral=True)

    async def update_options(self, guild_id: str, interaction_user: Optional[Union[discord.User, discord.Member]] = None):
        """Dynamically updates the options in the select menu based on eligibility."""
        self.clear_items() # Remove existing items before adding new ones
        guild_id_str = str(guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id_str)
        app_types = guild_config.get("application_types", {})
        options = []

        user_bl_manager_instance = None
        app_commands_cog = self.bot.get_cog("ApplicationCommands")
        if app_commands_cog:
            user_bl_manager_instance = app_commands_cog.user_blacklist_manager
        else:
            logger.error(f"ApplicationCommands cog not found for UserBlacklistManager during panel update for guild {guild_id_str}.")

        # Determine member object for blacklist checks if possible
        member_for_check = None
        if isinstance(interaction_user, discord.Member):
            member_for_check = interaction_user
        elif interaction_user and guild_id_str:
            guild = self.bot.get_guild(int(guild_id_str))
            if guild:
                member_for_check = guild.get_member(interaction_user.id)

        # Populate options, filtering out blacklisted types
        for type_id, type_data in app_types.items():
            blacklisted = False
            if member_for_check:
                # Check blacklist if user is identified as a member
                blacklisted = self.application_manager.is_blacklisted(guild_id_str, type_id, member_for_check, user_bl_manager_instance)
            elif interaction_user and user_bl_manager_instance:
                # Fallback check using user ID if user is not a member but blacklist manager exists
                blacklisted = user_bl_manager_instance.is_application_blacklisted(guild_id_str, str(interaction_user.id), type_id)

            if not blacklisted:
                emoji_str = type_data.get("emoji")
                valid_emoji = app_commands_cog.validate_emoji(emoji_str) if app_commands_cog and emoji_str else None
                options.append(discord.SelectOption(
                    label=type_data.get("name", type_id)[:100], # Truncate label if too long
                    value=type_id,
                    description=type_data.get("description", "")[:100], # Truncate description
                    emoji=valid_emoji
                ))

        # Add a placeholder if no eligible options are found
        if not options:
            options.append(discord.SelectOption(label="No eligible application types available", value="no_options_placeholder", disabled=True))

        # Create the select menu component
        select = discord.ui.Select(
            placeholder="Choose an application type...",
            options=options,
            custom_id=self.select_custom_id,
            disabled=not bool(options) or options[0].value == "no_options_placeholder", # Disable if no options or only placeholder
            min_values=1, max_values=1
        )
        select.callback = self.select_callback
        self.add_item(select)

class ApplicationTypeModal(discord.ui.Modal):
    """Modal for adding or editing application types (name, description, emoji, accepted role)."""
    def __init__(self, bot: commands.Bot, application_manager: ApplicationManager, guild_id: str,
                 parent_view_interaction: discord.Interaction, type_id: Optional[str] = None, existing_data: Optional[Dict] = None):
        title = "Edit Application Type" if type_id and existing_data else "Add New Application Type"
        super().__init__(title=title)
        self.bot = bot
        self.application_manager = application_manager
        self.guild_id = guild_id
        self.type_id = type_id or str(uuid.uuid4()) # Use provided ID or generate a new one
        self.existing_data = existing_data or {} # Initialize to empty dict if None
        self.parent_view_interaction = parent_view_interaction # The interaction that opened this modal

        # --- Input Fields ---
        self.name_input = discord.ui.TextInput(
            label="Application Type Name*",
            placeholder="e.g., Staff Application",
            default=self.existing_data.get("name", ""),
            max_length=100,
            required=True
        )
        self.description_input = discord.ui.TextInput(
            label="Description (Optional)",
            placeholder="A brief description of this application type.",
            default=self.existing_data.get("description", ""),
            style=discord.TextStyle.paragraph,
            max_length=200,
            required=False
        )
        self.emoji_input = discord.ui.TextInput(
            label="Emoji (Optional)",
            placeholder="e.g., ✨ or custom emoji like :myemoji:",
            default=self.existing_data.get("emoji", ""),
            max_length=50,
            required=False
        )

        # New Field: Role to assign on acceptance
        self.accepted_role_input = discord.ui.TextInput(
            label="Role ID to Assign on Acceptance (Optional)",
            placeholder="Enter the Role ID (e.g., 123456789012345678)",
            default=str(self.existing_data.get("accepted_role_id", "")), # Use existing_data safely
            required=False,
            max_length=20 # Max length of a Discord snowflake ID
        )

        self.add_item(self.name_input)
        self.add_item(self.description_input)
        self.add_item(self.emoji_input)
        self.add_item(self.accepted_role_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Defer immediately for ephemeral response

        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_types = guild_config.setdefault("application_types", {})

        # --- Process Emoji Input ---
        valid_emoji_str = None
        raw_emoji_input = self.emoji_input.value.strip()
        app_cog = self.bot.get_cog("ApplicationCommands") # Needed for emoji validation

        if raw_emoji_input:
            if app_cog:
                valid_emoji = app_cog.validate_emoji(raw_emoji_input)
                if valid_emoji:
                    valid_emoji_str = str(valid_emoji) # Store validated emoji string
                else:
                    # Inform user if emoji is invalid and stop submission
                    await interaction.followup.send(embed=EmbedBuilder.error("Invalid Emoji", f"The emoji `{raw_emoji_input}` is not valid or recognized."), ephemeral=True)
                    return
            else:
                # Warn if emoji validation cannot be performed
                await interaction.followup.send(embed=EmbedBuilder.warning("Emoji Validation Unavailable", "Could not validate emoji as the ApplicationCommands cog is not loaded properly."), ephemeral=True)
                valid_emoji_str = raw_emoji_input # Proceed with raw input but warn

        # --- Process Role ID Input ---
        raw_role_id_input = self.accepted_role_input.value.strip()
        validated_role_id = None
        role_validation_message = "" # For user feedback on role status

        if raw_role_id_input:
            try:
                role_id_int = int(raw_role_id_input)
                role_obj = interaction.guild.get_role(role_id_int) # Try to get from cache first
                if not role_obj: # If not in cache, fetch it
                    try:
                        role_obj = await interaction.guild.fetch_role(role_id_int)
                    except discord.NotFound:
                        role_validation_message = f"Role ID `{raw_role_id_input}` not found in this server."
                    except discord.Forbidden:
                        role_validation_message = "I lack permissions to verify the Role ID. Ensure I have 'View Roles' permission."
                    except Exception as e:
                        role_validation_message = f"An error occurred fetching the role: {e}"

                if role_obj: # If role was found (cached or fetched)
                    validated_role_id = str(role_obj.id) # Store the valid role ID
                    role_validation_message = f"Role **{role_obj.name}** is valid."
                # If role_obj is None and no specific error message, it implies an error occurred during fetch, handled above.

            except ValueError: # Input was not a valid number
                role_validation_message = f"The provided Role ID `{raw_role_id_input}` is not a valid number."
            except Exception as e: # Catch-all for unexpected errors
                role_validation_message = f"An unexpected error occurred processing the role ID: {e}"

        # Prevent submission if a role ID was provided but is invalid (and not just a permission error)
        if raw_role_id_input and validated_role_id is None and not ("I lack permissions" in role_validation_message):
            await interaction.followup.send(embed=EmbedBuilder.error("Invalid Role ID", role_validation_message), ephemeral=True)
            return

        # --- Update Configuration Data ---
        type_data = app_types.get(self.type_id, {}) # Get existing data or empty dict
        type_data.update({
            "name": self.name_input.value.strip(),
            "description": self.description_input.value.strip(),
            "emoji": valid_emoji_str, # Store validated emoji or None
            "accepted_role_id": validated_role_id # Store validated role ID or None
        })
        # Ensure lists exist for questions and blacklisted roles
        type_data.setdefault("questions", [])
        type_data.setdefault("blacklisted_roles", [])
        app_types[self.type_id] = type_data # Update the app types dict
        self.application_manager.save_data() # Save changes to file

        # --- Feedback to User ---
        action_description = "updated" if self.existing_data else "added"
        user_feedback_msg = f"Application type **{type_data['name']}** {action_description}."
        # Append role validation feedback if it exists
        if role_validation_message:
            user_feedback_msg += f"\nRole Status: {role_validation_message}"

        await interaction.followup.send(embed=EmbedBuilder.success("Type Saved", user_feedback_msg), ephemeral=True)

        # --- Refresh Parent View if it exists ---
        if self.parent_view_interaction and self.parent_view_interaction.message:
            try:
                # Re-fetch config and rebuild the parent view's embed and view
                guild_config_updated = self.application_manager.get_guild_config(self.guild_id)
                app_types_updated = guild_config_updated.get("application_types", {})

                embed = EmbedBuilder.info(title="Manage Application Types", description="Use buttons to manage your application types.")
                if app_types_updated:
                    types_display = "\n".join([f"• {d.get('emoji','')} {d.get('name', tid)}" for tid, d in app_types_updated.items()])
                    embed.add_field(name="Current Types", value=types_display or "None", inline=False)
                else:
                    embed.add_field(name="No Types Defined", value="Add a new type using the button below.", inline=False)

                # Recreate the parent view to ensure selections are reset/updated
                new_parent_view = ApplicationTypeView(self.bot, self.application_manager, self.parent_view_interaction)
                await self.parent_view_interaction.edit_original_response(embed=embed, view=new_parent_view)
            except Exception as e:
                logger.error(f"Error refreshing ApplicationTypeView after modal submission: {e}", exc_info=True)

class QuestionEditModal(discord.ui.Modal):
    """Modal for adding/editing specific questions (text or MCQ)."""
    def __init__(self, bot: commands.Bot, application_manager: ApplicationManager, guild_id: str, type_id: str,
                 parent_view_interaction: discord.Interaction, manage_questions_interaction: discord.Interaction,
                 question_type: str, question_id: Optional[str] = None, existing_question_data: Optional[Dict] = None):
        title = f"Edit {question_type.upper()} Question" if question_id else f"Add New {question_type.upper()} Question"
        super().__init__(title=title)

        self.bot = bot
        self.application_manager = application_manager
        self.guild_id = guild_id
        self.type_id = type_id
        self.question_type = question_type # Stores 'text' or 'mcq'
        self.question_id = question_id or str(uuid.uuid4()) # Unique ID for this question instance
        self.existing_question_data = existing_question_data or {}
        self.parent_view_interaction = parent_view_interaction # Interaction that opened the AppTypeView
        self.manage_questions_interaction = manage_questions_interaction # The message that presented this ManageQuestionsView

        # Input for the question text
        self.question_text_input = discord.ui.TextInput(
            label="Question Text*",
            placeholder="Enter the question here.",
            default=self.existing_question_data.get("text", ""),
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True
        )
        self.add_item(self.question_text_input)

        # Conditional input for Multiple Choice Questions (choices)
        if self.question_type == "mcq":
            self.mcq_choices_input = discord.ui.TextInput(
                label="MCQ Choices (comma-separated)*",
                placeholder="e.g., Choice A, Choice B, Choice C",
                default=", ".join(self.existing_question_data.get("choices", [])),
                required=True,
                style=discord.TextStyle.paragraph,
                max_length=1000
            )
            self.add_item(self.mcq_choices_input)
        else:
            self.mcq_choices_input = None # Ensure it's None if not MCQ

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_types = guild_config.get("application_types", {})

        # Check if the application type still exists
        if self.type_id not in app_types:
            await interaction.followup.send(embed=EmbedBuilder.error("Error", "Application type not found. Please try again."), ephemeral=True)
            return

        app_type_data = app_types[self.type_id]
        questions = app_type_data.setdefault("questions", []) # Get questions list or initialize it

        question_text = self.question_text_input.value.strip()
        choices_list = [] # Initialize choices list

        # Validate MCQ choices if it's an MCQ question
        if self.question_type == "mcq":
            mcq_choices_str = self.mcq_choices_input.value.strip()
            if not mcq_choices_str: # Choices are required for MCQ
                await interaction.followup.send(embed=EmbedBuilder.error("Input Error", "MCQ choices are required for multiple-choice questions."), ephemeral=True)
                return

            choices_list = [c.strip() for c in mcq_choices_str.split(',') if c.strip()] # Split and clean choices
            if len(choices_list) < 2: # Minimum two choices required for MCQ
                await interaction.followup.send(embed=EmbedBuilder.error("Input Error", "At least two MCQ choices are required."), ephemeral=True)
                return

        # Construct the new/updated question data
        new_q_data = {
            "id": self.question_id,
            "text": question_text,
            "type": self.question_type,
            "required": True, # Assuming all questions are required for simplicity
            "choices": choices_list # Empty list if not MCQ
        }

        # Check if this question already exists (for editing)
        existing_q_index = next((i for i, q in enumerate(questions) if q.get("id") == self.question_id), -1)
        action_taken = "updated" if existing_q_index != -1 else "added" # Determine if it's an update or addition

        if existing_q_index != -1:
            questions[existing_q_index] = new_q_data # Update the existing question
        else:
            questions.append(new_q_data) # Add the new question to the list

        self.application_manager.save_data() # Save the configuration

        # Log the action performed
        await log_action(interaction.guild, f"APP_Q_{action_taken.upper()}", interaction.user,
                         f"Question {'updated' if action_taken == 'updated' else 'added'} for type '{app_type_data.get('name', self.type_id)}': \"{question_text[:50]}...\"", "applications")

        await interaction.followup.send(embed=EmbedBuilder.success(f"Question {action_taken.capitalize()}", "Saved successfully."), ephemeral=True)

        # --- Refresh the Manage Questions View ---
        if self.manage_questions_interaction and self.manage_questions_interaction.message:
            try:
                # Re-fetch updated type data to correctly rebuild the view
                app_type_data_updated = self.application_manager.get_guild_config(self.guild_id).get("application_types", {}).get(self.type_id, {})
                type_name = app_type_data_updated.get("name", self.type_id)

                # Create a new ManageQuestionsView instance to reflect changes
                new_mq_view = ManageQuestionsView(self.bot, self.application_manager, self.guild_id, self.type_id, type_name, self.parent_view_interaction)

                # Rebuild the embed content for the Manage Questions interface
                mq_embed = EmbedBuilder.info(f"❓ Manage Questions for: {type_name}", "List of questions for this application type.")
                updated_qs = app_type_data_updated.get("questions", [])
                if updated_qs:
                    qs_description = "\n".join([f"**{i+1}.** {q.get('text', 'N/A')[:60]}... `({q.get('type')})`" for i, q in enumerate(updated_qs)])
                    mq_embed.add_field(name="Current Questions", value=qs_description, inline=False)
                else:
                    mq_embed.add_field(name="Current Questions", value="No questions have been added yet.", inline=False)

                # Edit the original message to show the updated view and embed
                await self.manage_questions_interaction.edit_original_response(embed=mq_embed, view=new_mq_view)
            except Exception as e:
                logger.error(f"Error refreshing ManageQuestionsView after question edit/add: {e}", exc_info=True)

class QuestionTypeSelectView(discord.ui.View):
    """View presented when adding a new question to choose between Text or MCQ."""
    def __init__(self, bot: commands.Bot, application_manager: ApplicationManager, guild_id: str, type_id: str,
                 parent_view_interaction: discord.Interaction, manage_questions_interaction: discord.Interaction):
        super().__init__(timeout=180) # Set a timeout for this selection process
        self.bot = bot
        self.application_manager = application_manager
        self.guild_id = guild_id
        self.type_id = type_id
        self.parent_view_interaction = parent_view_interaction # Interaction that opened the AppTypeView
        self.manage_questions_interaction = manage_questions_interaction # The message that presented this select view

    async def open_modal_for_question(self, interaction: discord.Interaction, question_type: str):
        """Helper function to open the appropriate QuestionEditModal."""
        modal = QuestionEditModal(
            bot=self.bot,
            application_manager=self.application_manager,
            guild_id=self.guild_id,
            type_id=self.type_id,
            parent_view_interaction=self.parent_view_interaction,
            manage_questions_interaction=self.manage_questions_interaction,
            question_type=question_type # Pass the chosen type ('text' or 'mcq')
        )
        await interaction.response.send_modal(modal)
        # Delete the original message that prompted the type selection
        try: await self.manage_questions_interaction.delete_original_response()
        except: pass # Ignore errors if the message is already gone
        self.stop() # Stop this view's listener

    # Button to select Text Question
    @discord.ui.button(label="Text Question", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="q_type_select_text")
    async def text_question(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_modal_for_question(interaction, 'text')

    # Button to select Multiple Choice Question
    @discord.ui.button(label="Multiple Choice Question", style=discord.ButtonStyle.secondary, emoji="🔘", custom_id="q_type_select_mcq")
    async def mcq_question(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_modal_for_question(interaction, 'mcq')

    # Button to cancel the question addition process
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="❌", row=1, custom_id="q_type_select_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() # Defer the button click
        try: await self.manage_questions_interaction.delete_original_response() # Delete the selection message
        except: pass
        self.stop()

class ManageQuestionsView(discord.ui.View):
    """View to manage questions for a specific application type (add, edit, remove, reorder)."""
    def __init__(self, bot: commands.Bot, application_manager: ApplicationManager, guild_id: str, type_id: str, type_name: str,
                 app_type_view_interaction: discord.Interaction):
        super().__init__(timeout=300) # Timeout for inactivity
        self.bot = bot
        self.application_manager = application_manager
        self.guild_id = guild_id
        self.type_id = type_id
        self.type_name = type_name
        self.app_type_view_interaction = app_type_view_interaction # The interaction that opened the AppTypeView
        self.selected_question_id: Optional[str] = None # Track the currently selected question ID
        self._update_view_components() # Populate the view initially

    def _update_view_components(self):
        """Clears and repopulates the view's components based on the current state."""
        self.clear_items()
        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_type_data = guild_config.get("application_types", {}).get(self.type_id, {})
        questions = app_type_data.get("questions", [])

        # --- Select Menu for Questions ---
        # Create options for the dropdown, including a placeholder
        options = [discord.SelectOption(label="-- Select a question to edit/remove --", value="placeholder_q_select", default=not self.selected_question_id)]
        for i, q_data in enumerate(questions):
            q_text_short = q_data.get("text", f"ID: {q_data.get('id', 'N/A')}")[:90] # Shorten text for label
            q_type_short = q_data.get("type", "N/A")[:10] # Shorten type name
            options.append(discord.SelectOption(label=f"{i+1}. {q_text_short} ({q_type_short})", value=q_data.get("id"), default=self.selected_question_id == q_data.get("id")))

        q_select_disabled = len(options) <= 1 # Disable if no questions or only placeholder
        q_select = discord.ui.Select(placeholder="Select question to Edit/Remove", options=options, custom_id=f"mq_select_q_{self.type_id}", row=0, disabled=q_select_disabled)
        q_select.callback = self.on_question_select
        self.add_item(q_select)

        # --- Action Buttons ---
        # Button to add a new question (opens type selection)
        add_question_button = discord.ui.Button(label="➕ Add Question", style=discord.ButtonStyle.success, custom_id=f"mq_add_q_{self.type_id}", row=1)
        add_question_button.callback = self.add_question_callback
        self.add_item(add_question_button)

        # Button to edit the selected question (enabled only if a question is selected)
        self.edit_question_button = discord.ui.Button(label="✏️ Edit Selected", style=discord.ButtonStyle.secondary, custom_id=f"mq_edit_q_{self.type_id}", row=1)
        self.edit_question_button.callback = self.edit_question_callback
        self.add_item(self.edit_question_button)

        # Button to remove the selected question (enabled only if a question is selected)
        self.remove_question_button = discord.ui.Button(label="🗑️ Remove Selected", style=discord.ButtonStyle.danger, custom_id=f"mq_remove_q_{self.type_id}", row=1)
        self.remove_question_button.callback = self.remove_question_callback
        self.add_item(self.remove_question_button)

        # --- Navigation Button ---
        # Button to go back to the Application Type management view
        back_button = discord.ui.Button(label="Back to App Type List", style=discord.ButtonStyle.grey, custom_id=f"mq_back_{self.type_id}", row=2)
        back_button.callback = self.back_to_type_view_callback
        self.add_item(back_button)

        self._toggle_action_buttons_state() # Ensure Edit/Remove buttons are correctly enabled/disabled

    def _toggle_action_buttons_state(self):
        """Enables or disables Edit and Remove buttons based on whether a question is selected."""
        is_q_selected = bool(self.selected_question_id) and self.selected_question_id != "placeholder_q_select"
        self.edit_question_button.disabled = not is_q_selected
        self.remove_question_button.disabled = not is_q_selected

    async def on_question_select(self, interaction: discord.Interaction):
        """Handles user selection from the question dropdown menu."""
        selected_value = interaction.data["values"][0]
        # Update selected_question_id, setting to None if placeholder is chosen
        self.selected_question_id = None if selected_value == "placeholder_q_select" else selected_value
        self._toggle_action_buttons_state() # Update button states based on new selection
        await interaction.response.edit_message(view=self) # Edit the original message to reflect selection changes

    async def add_question_callback(self, interaction: discord.Interaction):
        """Callback for the 'Add Question' button. Presents options for question type."""
        question_type_select_view = QuestionTypeSelectView(
            bot=self.bot,
            application_manager=self.application_manager,
            guild_id=self.guild_id,
            type_id=self.type_id,
            parent_view_interaction=self.app_type_view_interaction,
            manage_questions_interaction=interaction # Pass the interaction that triggered this view
        )
        await interaction.response.send_message("Please select the type of question you want to add:", view=question_type_select_view, ephemeral=True)

    async def edit_question_callback(self, interaction: discord.Interaction):
        """Callback for the 'Edit Selected' button. Opens modal pre-filled with question data."""
        if not self.selected_question_id or self.selected_question_id == "placeholder_q_select":
            await interaction.response.send_message("Please select a question from the dropdown first.", ephemeral=True)
            return

        # Retrieve the question data to be edited
        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_type_data = guild_config.get("application_types", {}).get(self.type_id, {})
        q_to_edit = next((q for q in app_type_data.get("questions", []) if q.get("id") == self.selected_question_id), None)

        if not q_to_edit: # If question not found (e.g., removed concurrently)
            await interaction.response.send_message("Selected question not found. It may have been removed. Please refresh the view.", ephemeral=True)
            self._update_view_components() # Refresh the view to clear the invalid selection
            await interaction.message.edit(view=self)
            return

        # Open the modal, passing existing data and the question type
        modal = QuestionEditModal(
            self.bot,
            self.application_manager,
            self.guild_id,
            self.type_id,
            parent_view_interaction=self.app_type_view_interaction,
            manage_questions_interaction=interaction, # The interaction that will be edited
            question_type=q_to_edit.get("type", "text"), # Determine type for modal context
            question_id=self.selected_question_id,
            existing_question_data=q_to_edit
        )
        await interaction.response.send_modal(modal)

    async def remove_question_callback(self, interaction: discord.Interaction):
        """Callback for the 'Remove Selected' button. Confirms before removing."""
        if not self.selected_question_id or self.selected_question_id == "placeholder_q_select":
            await interaction.response.send_message("Please select a question to remove.", ephemeral=True)
            return

        # Get question name for confirmation prompt
        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_type_data = guild_config.get("application_types", {}).get(self.type_id, {})
        question_to_remove = next((q for q in app_type_data.get("questions", []) if q.get("id") == self.selected_question_id), None)
        question_name = question_to_remove.get("text", "Selected Question")[:50] if question_to_remove else "Selected Question"

        # Confirm removal action with the user
        confirm_view = ConfirmActionView(custom_id_prefix=f"mq_remove_confirm_{self.selected_question_id}")
        async def confirm_removal(ci: discord.Interaction):
            if confirm_view.value: # User confirmed 'Yes'
                guild_config = self.application_manager.get_guild_config(self.guild_id)
                questions_list = guild_config.get("application_types", {}).get(self.type_id, {}).get("questions", [])

                initial_count = len(questions_list)
                # Filter out the question by its unique ID
                questions_list[:] = [q for q in questions_list if q.get("id") != self.selected_question_id]

                if len(questions_list) < initial_count: # If a question was actually removed
                    self.application_manager.save_data() # Save changes
                    # Log the removal action
                    await log_action(interaction.guild, "APP_Q_REMOVE", interaction.user, f"Removed question \"{question_name}\" from type '{self.type_name}'", "applications")

                    self.selected_question_id = None # Clear the selection
                    self._update_view_components() # Refresh the view components
                    await interaction.edit_original_response(view=self) # Update the original message with the refreshed view
                    await ci.response.send_message("Question removed successfully.", ephemeral=True, delete_after=5)
                else: # Fallback if question wasn't found (should not happen if selection was valid)
                    await ci.response.send_message("Question not found. It might have been removed already.", ephemeral=True, delete_after=5)

            else: # User selected 'No'
                await ci.response.send_message("Removal cancelled.", ephemeral=True, delete_after=5)

            # Disable confirmation buttons after interaction
            for item in confirm_view.children: item.disabled = True
            try: await ci.edit_original_response(view=confirm_view)
            except: pass # Ignore errors if edit fails

        confirm_view.callback_action = confirm_removal
        await interaction.response.send_message(f"Are you sure you want to remove the question:\n> **{question_name}**?", view=confirm_view, ephemeral=True)

    async def back_to_type_view_callback(self, interaction: discord.Interaction):
        """Callback to navigate back to the main Application Type management view."""
        guild_config = self.application_manager.get_guild_config(self.guild_id)
        types_upd = guild_config.get("application_types", {})

        # Rebuild the embed for the Application Type management view
        embed = EmbedBuilder.info(title="Manage Application Types", description="Use buttons to manage your application types.")
        if types_upd:
            types_display = "\n".join([f"• {d.get('emoji','')} {d.get('name', tid)}" for tid, d in types_upd.items()])
            embed.add_field(name="Current Types", value=types_display or "None", inline=False)
        else:
            embed.add_field(name="No Types Defined", value="Add a new type using the button below.", inline=False)

        # Create a new instance of the ApplicationTypeView to display
        new_view = ApplicationTypeView(self.bot, self.application_manager, self.app_type_view_interaction)

        # Edit the original message to show the new view and embed
        try:
            await self.app_type_view_interaction.edit_original_response(embed=embed, view=new_view)
            await interaction.response.defer() # Defer the 'Back' button interaction
        except Exception as e:
            logger.error(f"Error navigating back from Manage Questions to Application Types: {e}", exc_info=True)
            await interaction.response.send_message("Error returning to the application type list. Please try again.", ephemeral=True)

        self.stop() # Stop this view's listener

class ApplicationTypeView(discord.ui.View):
    """View for managing different application types (add, edit, delete, manage questions)."""
    def __init__(self, bot: commands.Bot, application_manager: ApplicationManager, parent_interaction: discord.Interaction):
        super().__init__(timeout=300) # Timeout for inactivity
        self.bot = bot
        self.application_manager = application_manager
        self.parent_interaction = parent_interaction # The interaction that initiated the whole setup process
        self.guild_id = str(parent_interaction.guild_id)
        self.current_selected_type_id: Optional[str] = None # Tracks the currently selected application type ID
        self._update_view_components() # Populate the view components initially

    def _update_view_components(self):
        """Clears and repopulates the view's components based on the current state."""
        self.clear_items()
        self._add_type_select_menu()
        self._add_type_action_buttons()
        self._add_type_management_buttons()
        self._add_navigation_buttons()
        self._toggle_action_buttons_state() # Ensure action buttons are enabled/disabled correctly

    def _add_type_select_menu(self):
        """Adds the dropdown menu for selecting application types."""
        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_types = guild_config.get("application_types", {})

        # Create options for the select menu, starting with a placeholder
        # Use a distinct value for the placeholder that won't conflict with actual type IDs
        placeholder_option = discord.SelectOption(
            label="-- Select an Application Type --",
            value="placeholder_novalue", # This value is required and will be checked in the callback
            default=not self.current_selected_type_id # Mark as default if no type is currently selected
        )
        options = [placeholder_option]

        if app_types:
            # Sort application types alphabetically by name for better usability
            sorted_types = sorted(app_types.items(), key=lambda item: item[1].get("name", item[0]).lower())
            for type_id, data in sorted_types:
                emoji_str = data.get('emoji', '')
                label_text = f"{emoji_str} {data.get('name', type_id)}".strip() # Combine emoji and name for label
                options.append(discord.SelectOption(
                    label=label_text[:100],
                    value=type_id,  # *** FIX: Ensure 'value' is present ***
                    description=data.get('description', '')[:100], # Add description as secondary info
                    emoji=emoji_str if emoji_str and not emoji_str.startswith(":") else None # Use emoji directly if valid, else None
                ))

        # The select menu should be disabled ONLY if there are NO selectable application types.
        select_disabled = not app_types # Disable if there are no application types

        select_custom_id = f"apptype_select_for_action_{self.guild_id}" # Unique custom ID for the select menu
        select = discord.ui.Select(
            placeholder="Select an application type to manage...",
            options=options,
            custom_id=select_custom_id,
            min_values=1, max_values=1,
            row=0,
            disabled=select_disabled # Disable the menu if there are no actual types to select
        )
        select.callback = self.on_type_select # Assign the callback function
        self.add_item(select)

    def _add_type_action_buttons(self):
        """Adds buttons for primary actions on the selected application type."""
        # Button to add a new application type
        add_button = discord.ui.Button(label="➕ Add New Type", style=discord.ButtonStyle.success, custom_id="apptype_add", row=1)
        add_button.callback = self.add_app_type_callback
        self.add_item(add_button)

        # Button to edit the selected application type's info (name, description, etc.)
        self.edit_button = discord.ui.Button(label="✏️ Edit Type Info", style=discord.ButtonStyle.secondary, custom_id="apptype_edit", row=1)
        self.edit_button.callback = self.edit_app_type_callback
        self.add_item(self.edit_button)

        # Button to remove the selected application type
        self.remove_button = discord.ui.Button(label="🗑️ Remove Type", style=discord.ButtonStyle.danger, custom_id="apptype_remove", row=1)
        self.remove_button.callback = self.remove_app_type_callback
        self.add_item(self.remove_button)

    def _add_type_management_buttons(self):
        """Adds buttons for managing specific aspects of a selected type (questions, roles)."""
        # Button to manage questions for the selected type
        self.manage_questions_button = discord.ui.Button(label="❓ Manage Questions", style=discord.ButtonStyle.blurple, custom_id="apptype_questions", row=2)
        self.manage_questions_button.callback = self.manage_questions_callback
        self.add_item(self.manage_questions_button)

        # Button to manage blacklist roles (currently a placeholder)
        self.manage_blacklist_button = discord.ui.Button(label="🚫 Manage Blacklist Roles", style=discord.ButtonStyle.blurple, custom_id="apptype_blacklist", row=2)
        self.manage_blacklist_button.callback = self.manage_blacklist_callback
        self.add_item(self.manage_blacklist_button)

    def _add_navigation_buttons(self):
        """Adds navigation buttons, like going back to the main setup menu."""
        # Button to return to the main Application Setup View
        back_button = discord.ui.Button(label="Back to Main Setup Menu", style=discord.ButtonStyle.grey, custom_id="apptype_back", row=3)
        back_button.callback = self.back_to_app_setup_callback
        self.add_item(back_button)

    def _toggle_action_buttons_state(self):
        """Enables/disables Edit, Remove, Questions, and Blacklist buttons based on type selection."""
        # Buttons are enabled only if a valid application type is selected (not placeholder)
        is_type_selected = bool(self.current_selected_type_id) and self.current_selected_type_id != "placeholder_novalue"
        self.edit_button.disabled = not is_type_selected
        self.remove_button.disabled = not is_type_selected
        self.manage_questions_button.disabled = not is_type_selected
        self.manage_blacklist_button.disabled = not is_type_selected

    async def on_type_select(self, interaction: discord.Interaction):
        """Handles selection changes in the application type dropdown."""
        selected_value = interaction.data["values"][0]
        if selected_value == "placeholder_novalue":
            self.current_selected_type_id = None # Deselect if placeholder is chosen
        else:
            self.current_selected_type_id = selected_value # Set the selected type ID

        self._toggle_action_buttons_state() # Update button states based on the new selection
        await interaction.response.edit_message(view=self) # Update the message to reflect the selection change

    async def add_app_type_callback(self, interaction: discord.Interaction):
        """Callback for the 'Add New Type' button. Opens the ApplicationTypeModal."""
        await interaction.response.send_modal(ApplicationTypeModal(
            bot=self.bot,
            application_manager=self.application_manager,
            guild_id=self.guild_id,
            parent_view_interaction=self.parent_interaction # Pass the original interaction context
        ))

    async def edit_app_type_callback(self, interaction: discord.Interaction):
        """Callback for the 'Edit Type Info' button. Opens modal with existing data."""
        if not self.current_selected_type_id or self.current_selected_type_id == "placeholder_novalue":
            await interaction.response.send_message("Please select an application type to edit first.", ephemeral=True)
            return

        # Retrieve existing data for the selected type
        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_types = guild_config.get("application_types", {})
        existing_data = app_types.get(self.current_selected_type_id)

        if not existing_data: # If type data is missing (shouldn't happen with valid selection)
            await interaction.response.send_message("Selected application type not found. Please refresh the view.", ephemeral=True)
            self._update_view_components() # Refresh view to clear invalid selection
            await interaction.message.edit(view=self)
            return

        # Open the modal, pre-filled with existing data
        await interaction.response.send_modal(ApplicationTypeModal(
            bot=self.bot,
            application_manager=self.application_manager,
            guild_id=self.guild_id,
            type_id=self.current_selected_type_id, # Pass the ID of the type being edited
            existing_data=existing_data,
            parent_view_interaction=self.parent_interaction
        ))

    async def remove_app_type_callback(self, interaction: discord.Interaction):
        """Callback for the 'Remove Type' button. Confirms before removing."""
        if not self.current_selected_type_id or self.current_selected_type_id == "placeholder_novalue":
            await interaction.response.send_message("Please select an application type to remove.", ephemeral=True)
            return

        # Get type data for confirmation prompt
        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_types = guild_config.get("application_types", {})
        type_data = app_types.get(self.current_selected_type_id)

        if not type_data: # If type data is missing
            await interaction.response.send_message("Selected application type not found. Please refresh.", ephemeral=True)
            self._update_view_components()
            await interaction.message.edit(view=self)
            return

        type_name = type_data.get("name", self.current_selected_type_id) # Get name for display

        # Create confirmation view
        confirm_view = ConfirmActionView(custom_id_prefix=f"apptype_remove_confirm_{self.current_selected_type_id}")
        async def confirm_action(ci: discord.Interaction):
            if confirm_view.value: # If user confirmed 'Yes'
                del app_types[self.current_selected_type_id] # Remove type from config
                self.application_manager.save_data() # Save changes
                # Log the removal action
                await log_action(interaction.guild, "APP_TYPE_REMOVE", interaction.user, f"Removed application type: '{type_name}'", "applications")

                # Reset selection and refresh the view
                self.current_selected_type_id = None
                self._update_view_components()
                await interaction.edit_original_response(view=self) # Update the original message with the refreshed view
                await ci.response.send_message(f"Application type **{type_name}** removed.", ephemeral=True, delete_after=5)
            else: # If user selected 'No'
                await ci.response.send_message("Removal cancelled.", ephemeral=True, delete_after=5)

            # Disable confirmation buttons after interaction
            for item in confirm_view.children: item.disabled = True
            try: await ci.edit_original_response(view=confirm_view)
            except: pass # Ignore errors if edit fails

        confirm_view.callback_action = confirm_action
        await interaction.response.send_message(f"Are you sure you want to remove the application type **{type_name}**?", view=confirm_view, ephemeral=True)

    async def manage_questions_callback(self, interaction: discord.Interaction):
        """Callback to navigate to the Manage Questions view for the selected type."""
        if not self.current_selected_type_id or self.current_selected_type_id == "placeholder_novalue":
            await interaction.response.send_message("Please select an application type first.", ephemeral=True)
            return

        guild_config = self.application_manager.get_guild_config(self.guild_id)
        app_type_data = guild_config.get("application_types", {}).get(self.current_selected_type_id)

        if not app_type_data: # If selected type data is missing
            await interaction.response.send_message("Selected application type not found. Please refresh.", ephemeral=True)
            self._update_view_components()
            await interaction.message.edit(view=self)
            return

        type_name = app_type_data.get("name", self.current_selected_type_id)

        # Create the Manage Questions View instance
        questions_view = ManageQuestionsView(self.bot, self.application_manager, self.guild_id, self.current_selected_type_id, type_name, self.parent_interaction)

        # Build the embed content for the Manage Questions interface
        embed = EmbedBuilder.info(f"❓ Manage Questions for: {type_name}", "Add, edit, or remove questions for this application type.")
        questions = app_type_data.get("questions", [])
        if questions:
            qs_description = "\n".join([f"**{i+1}.** {q.get('text', 'N/A')[:60]}... `({q.get('type')})`" for i, q in enumerate(questions)])
            embed.add_field(name="Current Questions", value=qs_description, inline=False)
        else:
            embed.add_field(name="Current Questions", value="No questions have been added yet.", inline=False)

        await interaction.response.send_message(embed=embed, view=questions_view, ephemeral=True)

    async def manage_blacklist_callback(self, interaction: discord.Interaction):
        """Placeholder callback for managing blacklist roles per type."""
        # Use Discord's Modal component for a placeholder feedback message
        await interaction.response.send_modal(discord.ui.Modal(title="Coming Soon")
            .add_item(discord.ui.TextInput(label="Feature Status", default="Managing blacklist roles for specific application types is planned for a future update.", style=discord.TextStyle.paragraph, required=False, readonly=True))
        )
        # TODO: Implement actual blacklist role management logic.

    async def back_to_app_setup_callback(self, interaction: discord.Interaction):
        """Callback to navigate back to the main Application Setup menu."""
        # Recreate the main setup view
        setup_view = ApplicationSetupView(self.bot, self.application_manager, self.guild_id)

        # Rebuild the embed for the main setup menu
        cfg = self.application_manager.get_guild_config(self.guild_id)
        types = cfg.get("application_types", {})
        title, desc = "🛠️ Application System Setup", "Configure your server's application settings and manage application types."
        if not types: # Add advice if no types are set up yet
            desc += "\n\nNo application types are set up yet. Click 'Manage Application Types' then 'Add New Type' to get started."

        embed = EmbedBuilder.info(title, desc)

        # Edit the original message to display the main setup menu
        try:
            await self.parent_interaction.edit_original_response(embed=embed, view=setup_view)
            await interaction.response.defer() # Defer the 'Back' button interaction
        except Exception as e:
            logger.error(f"Error navigating back from Application Types to Main Setup: {e}", exc_info=True)
            await interaction.response.send_message("Error returning to the setup menu. Please try again.", ephemeral=True)

        self.stop() # Stop this view's listener

class ApplicationSetupView(discord.ui.View):
    """Main view for the application system setup, presenting configuration options."""
    def __init__(self, bot: commands.Bot, application_manager: ApplicationManager, guild_id: Optional[str]=None):
        super().__init__(timeout=None) # This view is managed by the bot, timeout is handled by interaction responses
        self.bot = bot
        self.application_manager = application_manager
        self.guild_id = guild_id

    # Button to set the channel for the application panel message
    @discord.ui.button(label="Set Panel Channel", style=discord.ButtonStyle.primary, row=0, emoji="#️⃣", custom_id="appsetup_panel_channel")
    async def set_panel_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id)

        # Use Discord's ChannelSelect component for user-friendly channel selection
        channel_select = discord.ui.ChannelSelect(
            placeholder="Select channel for the application panel",
            channel_types=[discord.ChannelType.text], # Only allow text channels
            min_values=1, max_values=1
        )

        # Temporary view to hold the select component and its callback
        temp_view = discord.ui.View(timeout=60) # Timeout for channel selection
        async def channel_select_callback(inter: discord.Interaction):
            selected_channel = channel_select.values[0]
            guild_config["panel_channel_id"] = str(selected_channel.id) # Store channel ID
            self.application_manager.save_data()

            # Update the application panel message to reflect the new channel setting
            cog = self.bot.get_cog("ApplicationCommands")
            success = False
            if cog:
                # Pass the user who initiated the setup for potential filtering in update_options
                success = await cog.update_application_panel(inter.guild, interaction_user_for_options=inter.user)

            # Provide feedback to the user
            if success:
                await inter.response.send_message(embed=EmbedBuilder.success("Panel Channel Set", f"The application panel will now be posted in {selected_channel.mention}."), ephemeral=True)
            else:
                await inter.response.send_message(embed=EmbedBuilder.warning("Panel Channel Set (Error Updating)", f"Panel channel set to {selected_channel.mention}, but an error occurred updating the panel. Check bot logs."), ephemeral=True)

            # Clean up the temporary view state
            for item in temp_view.children: item.disabled = True
            try: await inter.edit_original_response(view=temp_view)
            except: pass # Ignore if edit fails

        channel_select.callback = channel_select_callback
        temp_view.add_item(channel_select)
        await interaction.response.send_message("Select a channel for the application panel:", view=temp_view, ephemeral=True)

    # Button to set the channel for application logs and reviews
    @discord.ui.button(label="Set Log Channel", style=discord.ButtonStyle.primary, row=0, emoji="📜", custom_id="appsetup_log_channel")
    async def set_log_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id)

        channel_select = discord.ui.ChannelSelect(placeholder="Select channel for application logs", channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
        temp_view = discord.ui.View(timeout=60)

        async def channel_select_callback(inter: discord.Interaction):
            selected_channel = channel_select.values[0]
            guild_config["log_channel_id"] = str(selected_channel.id) # Store channel ID
            self.application_manager.save_data()
            await inter.response.send_message(embed=EmbedBuilder.success("Log Channel Set", f"Application logs will be sent to {selected_channel.mention}."), ephemeral=True)

            for item in temp_view.children: item.disabled = True # Disable view components
            try: await inter.edit_original_response(view=temp_view)
            except: pass

        channel_select.callback = channel_select_callback
        temp_view.add_item(channel_select)
        await interaction.response.send_message("Select a channel for application logs:", view=temp_view, ephemeral=True)

    # Button to set roles that can review applications
    @discord.ui.button(label="Set Reviewer Roles", style=discord.ButtonStyle.primary, row=1, emoji="💼", custom_id="appsetup_reviewer_roles")
    async def set_reviewer_roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id)

        # Use Discord's RoleSelect component
        role_select = discord.ui.RoleSelect(placeholder="Select roles that can review applications", min_values=0, max_values=25) # Allow 0 to 25 roles
        temp_view = discord.ui.View(timeout=60)

        async def role_select_callback(inter: discord.Interaction):
            selected_roles_ids = [str(role.id) for role in role_select.values] # Get IDs of selected roles
            guild_config["reviewer_roles"] = selected_roles_ids
            self.application_manager.save_data()

            if selected_roles_ids:
                role_mentions = ", ".join([f"<@&{role_id}>" for role_id in selected_roles_ids])
                await inter.response.send_message(embed=EmbedBuilder.success("Reviewer Roles Set", f"The following roles can now review applications: {role_mentions}"), ephemeral=True)
            else:
                await inter.response.send_message(embed=EmbedBuilder.success("Reviewer Roles Cleared", "Only administrators can review applications now."), ephemeral=True)

            for item in temp_view.children: item.disabled = True # Disable view components
            try: await inter.edit_original_response(view=temp_view)
            except: pass

        role_select.callback = role_select_callback
        temp_view.add_item(role_select)
        await interaction.response.send_message("Select roles that can review applications. Admins always have permission.", view=temp_view, ephemeral=True)

    # Button to set roles that are allowed to apply for positions
    @discord.ui.button(label="Set Applicant Roles", style=discord.ButtonStyle.primary, row=1, emoji="👥", custom_id="appsetup_applicant_roles")
    async def set_applicant_roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id)

        role_select = discord.ui.RoleSelect(placeholder="Select roles that can submit applications", min_values=0, max_values=25)
        temp_view = discord.ui.View(timeout=60)

        async def role_select_callback(inter: discord.Interaction):
            selected_roles_ids = [str(role.id) for role in role_select.values] # Get selected role IDs
            guild_config["applicant_roles"] = selected_roles_ids
            self.application_manager.save_data()

            if selected_roles_ids:
                role_mentions = ", ".join([f"<@&{role_id}>" for role_id in selected_roles_ids])
                await inter.response.send_message(embed=EmbedBuilder.success("Applicant Roles Set", f"Members with these roles can now apply: {role_mentions}"), ephemeral=True)
            else:
                await inter.response.send_message(embed=EmbedBuilder.success("Applicant Roles Cleared", "All server members can now apply."), ephemeral=True)

            for item in temp_view.children: item.disabled = True # Disable view components
            try: await inter.edit_original_response(view=temp_view)
            except: pass

        role_select.callback = role_select_callback
        temp_view.add_item(role_select)
        await interaction.response.send_message("Select roles required to apply. If none are selected, all members can apply.", view=temp_view, ephemeral=True)

    # Button to manage the different types of applications (e.g., Staff, Helper)
    @discord.ui.button(label="Manage Application Types", style=discord.ButtonStyle.primary, row=2, emoji="📋", custom_id="appsetup_manage_types")
    async def manage_app_types_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id)
        app_types = guild_config.get("application_types", {})

        # Navigate to the ApplicationTypeView for managing types
        view = ApplicationTypeView(self.bot, self.application_manager, interaction)
        embed = EmbedBuilder.info("Manage Application Types", "Use buttons to manage your application types.")
        if app_types:
            # Display a summary of current application types
            types_display = "\n".join([f"• {d.get('emoji','')} {d.get('name', tid)}" for tid, d in app_types.items()])
            embed.add_field(name="Current Types", value=types_display or "None", inline=False)
        else:
            embed.add_field(name="No Types Defined", value="Add a new type using the button below.", inline=False)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ApplicationReviewView(discord.ui.View):
    """View shown on application log messages, allowing reviewers to Accept/Deny."""
    def __init__(self, bot, application_manager, application_id: str, applicant_user_id: Union[int, str]):
        super().__init__(timeout=None) # Persistent view, managed by the bot
        self.bot = bot
        self.application_manager = application_manager
        self.application_id = application_id
        self.applicant_user_id = str(applicant_user_id) # Store applicant ID for modal context

    # Button to accept an application
    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅", custom_id="accept_application_btn", row=0)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("ApplicationCommands")
        # Check permissions before allowing review action
        if not cog or not await cog.can_review_applications(interaction.user, interaction.guild_id):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "You do not have permission to review applications."), ephemeral=True)
            return

        # Open the modal for providing acceptance reason
        await interaction.response.send_modal(AcceptReasonModal(self.bot, self.application_manager, self.application_id, self.applicant_user_id))

    # Button to deny an application
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌", custom_id="deny_application_btn", row=0)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = self.bot.get_cog("ApplicationCommands")
        # Check permissions
        if not cog or not await cog.can_review_applications(interaction.user, interaction.guild_id):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "You do not have permission to review applications."), ephemeral=True)
            return

        # Open the modal for providing denial reason
        await interaction.response.send_modal(DenyReasonModal(self.bot, self.application_manager, self.application_id, self.applicant_user_id))

class AcceptReasonModal(discord.ui.Modal, title="Accept Application"):
    """Modal for providing a reason when accepting an application."""
    # Optional reason field for acceptance
    reason = discord.ui.TextInput(label="Reason for Acceptance (Optional)", style=discord.TextStyle.paragraph, placeholder="e.g., Welcomed to the team!", required=False, max_length=1000)

    def __init__(self, bot, application_manager, application_id: str, applicant_user_id: str):
        super().__init__()
        self.bot = bot
        self.application_manager = application_manager
        self.application_id = application_id
        self.applicant_user_id = applicant_user_id # Store applicant ID for role assignment and DM notification

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Defer response for processing

        cog = self.bot.get_cog("ApplicationCommands")
        if not cog:
            await interaction.response.send_message(embed=EmbedBuilder.error("System Unavailable", "Application commands are not available."), ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        application_data = self.application_manager.get_application(guild_id, self.application_id)

        # Validate application status: must be pending
        if not application_data or application_data.get("status") != "pending":
            await interaction.followup.send(embed=EmbedBuilder.error("Error", "Application not found or already processed."), ephemeral=True)
            return

        # --- Role Assignment Logic ---
        applicant_user_obj = None
        # Try to fetch the applicant member object from the guild cache first
        try:
            applicant_user_obj = interaction.guild.get_member(int(self.applicant_user_id))
        except (ValueError, TypeError):
            pass # User ID might be invalid or user might have left the server

        type_id = application_data.get("type_id")
        accepted_role_id_str = None
        assigned_role_mention = None

        if type_id: # Get configured role ID if type exists
            guild_config = self.application_manager.get_guild_config(guild_id)
            accepted_role_id_str = guild_config.get("application_types", {}).get(type_id, {}).get("accepted_role_id")

        # Attempt to assign the configured role if it exists and the applicant is still in the server
        if applicant_user_obj and accepted_role_id_str:
            try:
                role_to_assign = interaction.guild.get_role(int(accepted_role_id_str))
                if role_to_assign:
                    await applicant_user_obj.add_roles(role_to_assign, reason=f"Accepted application {self.application_id} by {interaction.user.name}")
                    assigned_role_mention = role_to_assign.mention
                    application_data["assigned_role_id"] = accepted_role_id_str # Record the assigned role ID
                    # Log successful role assignment
                    await log_action(interaction.guild, "APP_ROLE_ASSIGNED", interaction.user, f"Assigned '{role_to_assign.name}' to '{applicant_user_obj.name}' for app {self.application_id}", "applications")
                else:
                    # Log if the configured role was not found in the guild
                    await log_action(interaction.guild, "APP_ROLE_NOT_FOUND_ACCEPT", interaction.user, f"Accepted application {self.application_id}. Configured role ID {accepted_role_id_str} not found.", "applications")
                    await interaction.followup.send(embed=EmbedBuilder.warning("Role Not Found", f"The configured role for this application could not be found. No role assigned."), ephemeral=True)
            except discord.Forbidden: # Handle missing bot permissions
                await log_action(interaction.guild, "APP_ROLE_PERMISSION_DENIED_ACCEPT", interaction.user, f"Accepted application {self.application_id}. Bot lacks permissions to assign role ID {accepted_role_id_str}.", "applications")
                await interaction.followup.send(embed=EmbedBuilder.error("Permissions Error", "I lack permissions to assign roles. Please check my role permissions."), ephemeral=True)
            except Exception as e: # Catch other errors during role assignment
                await log_action(interaction.guild, "APP_ROLE_ASSIGN_ERROR_ACCEPT", interaction.user, f"Accepted application {self.application_id}. Error assigning role: {e}", "applications")
                await interaction.followup.send(embed=EmbedBuilder.error("Role Assignment Error", f"An error occurred while assigning the role: {e}"), ephemeral=True)
        elif not accepted_role_id_str: # Log if no role was configured
            await log_action(interaction.guild, "APP_ROLE_NOT_CONFIGURED_ACCEPT", interaction.user, f"Accepted application {self.application_id}. No role configured.", "applications")
        elif not applicant_user_obj: # Log if applicant left the server
             await log_action(interaction.guild, "APP_ROLE_APPLICANT_LEFT_ACCEPT", interaction.user, f"Accepted application {self.application_id}. Applicant no longer in server.", "applications")
             await interaction.followup.send(embed=EmbedBuilder.warning("Applicant Not Found", "The applicant is no longer in the server, so no role could be assigned."), ephemeral=True)

        # --- Update Application Status and Data ---
        application_data["status"] = "accepted"
        application_data["reviewer_id"] = str(interaction.user.id) # Store reviewer's ID
        application_data["review_time"] = datetime.now(timezone.utc).isoformat() # Record review timestamp
        application_data["reason"] = self.reason.value.strip() # Store the provided reason

        self.application_manager.save_data() # Save updated data

        # --- Send DM Confirmation to Applicant ---
        await self.send_status_dm(interaction.guild, applicant_user_obj, "Accepted", self.reason.value.strip(), interaction.user, self.application_id, application_data.get("type_name"))

        # --- Confirmation message to the reviewer ---
        review_confirm_embed = EmbedBuilder.success("Application Accepted", f"Application **{self.application_id}** processed.")
        if assigned_role_mention:
            review_confirm_embed.add_field(name="Assigned Role", value=assigned_role_mention, inline=False)
        if self.reason.value.strip():
            review_confirm_embed.add_field(name="Reason", value=self.reason.value.strip(), inline=False)

        await interaction.followup.send(embed=review_confirm_embed, ephemeral=True)

        # --- Update the log channel message ---
        await cog.update_application_log(interaction.guild, application_data)

class DenyReasonModal(discord.ui.Modal, title="Deny Application"):
    """Modal for providing a reason when denying an application."""
    # Required reason field for denial
    reason = discord.ui.TextInput(label="Reason for Denial (Required)", style=discord.TextStyle.paragraph, placeholder="Explain why the application was denied.", required=True, max_length=1000)

    def __init__(self, bot, application_manager, application_id: str, applicant_user_id: str):
        super().__init__()
        self.bot = bot
        self.application_manager = application_manager
        self.application_id = application_id
        self.applicant_user_id = applicant_user_id # Store applicant ID for DM notification

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Defer response for processing

        cog = self.bot.get_cog("ApplicationCommands")
        if not cog:
            await interaction.response.send_message(embed=EmbedBuilder.error("System Unavailable", "Application commands are not available."), ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        application_data = self.application_manager.get_application(guild_id, self.application_id)

        # Validate application status: must be pending
        if not application_data or application_data.get("status") != "pending":
            await interaction.followup.send(embed=EmbedBuilder.error("Error", "Application not found or already processed."), ephemeral=True)
            return

        # --- Update Application Status and Data ---
        application_data["status"] = "denied"
        application_data["reviewer_id"] = str(interaction.user.id) # Store reviewer's ID
        application_data["review_time"] = datetime.now(timezone.utc).isoformat() # Record review timestamp
        application_data["reason"] = self.reason.value.strip() # Store the provided denial reason

        self.application_manager.save_data() # Save updated data

        # --- Send DM Confirmation to Applicant ---
        # Fetch applicant user object to send DM
        applicant_user_obj = None
        try:
            applicant_user_obj = interaction.guild.get_member(int(self.applicant_user_id))
            if not applicant_user_obj: # If not in cache, try fetching globally
                applicant_user_obj = await self.bot.fetch_user(int(self.applicant_user_id))
        except Exception:
            pass # Ignore errors if user fetching fails

        await self.send_status_dm(interaction.guild, applicant_user_obj, "Denied", self.reason.value.strip(), interaction.user, self.application_id, application_data.get("type_name"))

        # --- Confirmation message to the reviewer ---
        review_confirm_embed = EmbedBuilder.error("Application Denied", f"Application **{self.application_id}** processed.\nReason: {self.reason.value.strip()}")
        await interaction.followup.send(embed=review_confirm_embed, ephemeral=True)

        # --- Update the log channel message ---
        await cog.update_application_log(interaction.guild, application_data)

class MCQAnswerView(discord.ui.View):
    """View for MCQ questions in DM applications, displaying buttons for each choice."""
    def __init__(self, cog_ref: "ApplicationCommands", user: discord.User, question_id: str, choices: List[str]):
        super().__init__(timeout=300) # Timeout for user inactivity on this question
        self.cog = cog_ref
        self.user = user
        self.question_id = question_id
        self.choices = choices
        self.message: Optional[discord.Message] = None # Reference to the message this view is attached to

        # Create buttons for each MCQ choice
        for i, choice_text in enumerate(choices):
            label = choice_text[:80] # Truncate choice label if too long
            button = discord.ui.Button(label=label, custom_id=f"mcqchoice_{self.question_id}_{i}_{user.id}", style=discord.ButtonStyle.secondary)
            button.callback = self.choice_callback # Assign callback function
            self.add_item(button)

    async def choice_callback(self, interaction: discord.Interaction):
        """Callback executed when a user clicks one of the MCQ choice buttons."""
        # Parse the custom ID to get the selected choice index and user ID
        custom_id_parts = interaction.data["custom_id"].split("_")
        if len(custom_id_parts) < 4: # Basic validation of custom ID format
            logger.warning(f"MCQAnswerView received malformed custom_id: {interaction.data['custom_id']}")
            await interaction.response.send_message("An error occurred with your selection.", ephemeral=True)
            return

        try:
            choice_idx = int(custom_id_parts[-2]) # Index of the selected choice
            selected_choice_text = self.choices[choice_idx] # Get the actual choice text
        except (IndexError, ValueError) as e: # Handle errors during parsing
            logger.error(f"Error parsing MCQ choice from custom_id: {e} for ID: {interaction.data['custom_id']}")
            await interaction.response.send_message("An error occurred processing your choice.", ephemeral=True)
            return

        # Disable all buttons in the view after a choice is made to prevent multiple selections
        for item in self.children:
            if isinstance(item, discord.ui.Button): item.disabled = True

        # Update the message to show the selected answer and indicate progression
        if self.message:
            try:
                await self.message.edit(content=f"{self.message.content}\n\n*You selected: **{selected_choice_text}***\n*Moving to the next question...*", view=self)
            except discord.HTTPException as e:
                logger.error(f"Failed to edit MCQ message {self.message.id} after selection: {e}")

        await interaction.response.defer() # Defer the button interaction response
        # Process the selected answer through the cog's logic
        await self.cog.process_dm_mcq_response(self.user, selected_choice_text)
        self.stop() # Stop listening for interactions on this view

    async def on_timeout(self):
        """Handles the view timing out due to user inactivity."""
        if self.message:
            try:
                # Disable buttons upon timeout
                for item in self.children: item.disabled = True
                # Update the message to indicate timeout
                await self.message.edit(content=self.message.content + "\n\n*This question timed out due to inactivity. Please respond to your application in DMs soon to continue.*", view=self)
            except discord.HTTPException as e:
                logger.warning(f"Failed to edit MCQ message {self.message.id} on timeout: {e}")
        logger.info(f"MCQAnswerView for user {self.user.id} timed out for question ID {self.question_id}.")

# ----------------------------------------------------------------------------------
# Main Cog
# ----------------------------------------------------------------------------------
class ApplicationCommands(commands.Cog):
    """Cog for managing server applications, including setup, applying, and reviewing."""
    def __init__(self, bot):
        self.bot = bot
        self.application_manager = ApplicationManager()
        # Initialize user_blacklist_manager; ensure it's properly initialized elsewhere or passed.
        self.user_blacklist_manager = UserBlacklistManager()
        self.persistent_views_added = False
        # Dictionary to track active DM applications: {user_id: app_state_dict}
        self.active_dm_applications: Dict[int, Dict] = {}
        # Start the background task to check for DM application timeouts
        self.check_dm_application_timeouts.start()

    async def update_application_panel(self, guild: discord.Guild, interaction_user_for_options: Optional[discord.User] = None) -> bool:
        """
        Creates or updates the application panel message in the configured channel.
        Returns True on success, False on failure.
        """
        guild_id_str = str(guild.id)
        guild_config = self.application_manager.get_guild_config(guild_id_str)
        panel_channel_id = guild_config.get("panel_channel_id")

        if not panel_channel_id:
            logger.warning(f"Attempted to update panel for guild {guild_id_str}, but no panel channel is set.")
            return False # Indicate failure if no channel is set

        try:
            # Fetch the channel object
            channel = guild.get_channel(int(panel_channel_id))
            if not isinstance(channel, discord.TextChannel):
                logger.error(f"Panel channel ID {panel_channel_id} for guild {guild.id} is invalid or not a text channel.")
                guild_config["last_panel_error"] = f"Invalid channel ID: {panel_channel_id} or channel not found."
                self.application_manager.save_data()
                return False

            # --- Create the Panel Embed ---
            panel_embed = EmbedBuilder.info(
                title="📝 Server Applications",
                description="Select an application from the dropdown menu below to begin."
            )
            # Set custom color from config, fallback to blue if invalid
            panel_color_val = guild_config.get("panel_color", 0x3498db)
            try:
                panel_embed.color = discord.Color(panel_color_val)
            except Exception:
                panel_embed.color = discord.Color(0x3498db)

            # --- Create and Update the Panel View ---
            panel_view = ApplicationPanelView(self.bot, self.application_manager)
            # Update options dynamically, potentially considering the user who triggered the update
            await panel_view.update_options(guild_id_str, interaction_user_for_options)

            # --- Send or Edit the Panel Message ---
            panel_message_id = guild_config.get("panel_message_id")
            message_to_edit = None

            if panel_message_id: # If a panel message already exists
                try:
                    message_to_edit = await channel.fetch_message(int(panel_message_id))
                    await message_to_edit.edit(embed=panel_embed, view=panel_view) # Edit the existing message
                    logger.info(f"Successfully updated application panel for guild {guild.id} (message ID: {panel_message_id}).")
                except discord.NotFound:
                    logger.warning(f"Panel message {panel_message_id} not found in guild {guild.id}. Creating a new one.")
                    panel_message_id = None # Reset to force creation of a new message
                except discord.Forbidden as e:
                    logger.error(f"Forbidden to edit panel message {panel_message_id} in guild {guild.id}: {e}")
                    guild_config["last_panel_error"] = "Bot lacks permission to edit its message in the panel channel."
                    self.application_manager.save_data()
                    return False

            if not panel_message_id: # If no existing message or it was not found/editable
                try:
                    new_message = await channel.send(embed=panel_embed, view=panel_view) # Send a new message
                    guild_config["panel_message_id"] = str(new_message.id)
                    logger.info(f"Successfully created a new application panel for guild {guild.id} (message ID: {new_message.id}).")
                except discord.Forbidden as e:
                    logger.error(f"Forbidden to send panel message in guild {guild.id} channel {channel.name}: {e}")
                    guild_config["last_panel_error"] = "Bot lacks permission to send messages in the panel channel."
                    self.application_manager.save_data()
                    return False

            # Update metadata and save configuration changes
            guild_config["last_panel_update"] = datetime.now(timezone.utc).isoformat()
            guild_config["last_panel_error"] = None # Clear any previous errors on successful update
            self.application_manager.save_data()
            return True # Indicate success

        except Exception as e: # Catch any unexpected critical errors during panel update
            logger.error(f"A critical error occurred in update_application_panel for guild {guild.id}: {e}", exc_info=True)
            guild_config["last_panel_error"] = f"Critical error during panel update: {e}"
            self.application_manager.save_data()
            return False

    async def cog_unload(self):
        """Cancel background tasks when the cog is unloaded."""
        self.check_dm_application_timeouts.cancel()
        logger.info("Applications cog unloaded, DM timeout task cancelled.")

    async def cog_load(self):
        """Called when the cog is loaded. Initializes persistent views and starts tasks."""
        logger.info("Applications cog loading...")
        if not self.persistent_views_added:
            # Persistent views like ApplicationPanelView are added dynamically when messages are sent.
            # If there were global persistent views, they'd be added here.
            self.persistent_views_added = True
            logger.info("Persistent views setup complete for Applications cog.")

        # Ensure the DM timeout checking task is running
        if not self.check_dm_application_timeouts.is_running():
            try:
                self.check_dm_application_timeouts.start()
                logger.info("DM Timeout task started successfully.")
            except RuntimeError:
                logger.warning("DM Timeout task was already running or encountered a RuntimeError on start.")

    def validate_emoji(self, emoji_str: Optional[str]) -> Optional[Union[discord.PartialEmoji, str]]:
        """
        Validates an emoji string.
        Returns a discord.PartialEmoji object if it's a valid custom emoji,
        the string itself if it's a simple Unicode emoji character, or None otherwise.
        """
        if not emoji_str: return None
        emoji_str = emoji_str.strip()
        try:
            # discord.py's PartialEmoji.from_str handles both custom and standard Unicode emojis.
            return discord.PartialEmoji.from_str(emoji_str)
        except (ValueError, TypeError, discord.errors.NotFound):
            # If it's not a recognized custom emoji format, check if it's a simple Unicode emoji character.
            # A basic check: short length, not alphanumeric, printable. Needs careful testing for broad emoji support.
            if len(emoji_str) <= 4 and not emoji_str.isalnum() and emoji_str.isprintable():
                return emoji_str # Assume it's a Unicode emoji character
            logger.debug(f"Could not validate '{emoji_str}' as a known custom emoji or simple Unicode emoji.")
            return None # Invalid emoji string

    # --- Admin Command to set up the application system ---
    @app_commands.command(name="setup_applications", description="Configure the application system for your server.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True) # Restricted to administrators
    async def setup_applications(self, interaction: discord.Interaction):
        """Initiates the application system setup via an interactive view."""
        if not await is_admin(interaction.user): # Ensure admin permissions
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "You need administrator permissions to use this command."), ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id)
        app_types = guild_config.get("application_types", {})

        embed_title = "🛠️ Application System Setup"
        embed_description = "Configure your application settings and manage different application types."
        if not app_types: # Provide guidance if no types are set up yet
            embed_description += "\n\nNo application types are set up yet. Click 'Manage Application Types' then 'Add New Type' to get started."

        # Display the main setup view for configuration
        await interaction.response.send_message(embed=EmbedBuilder.info(embed_title, embed_description), view=ApplicationSetupView(self.bot, self.application_manager, guild_id), ephemeral=True)

    # --- User Command to initiate the application process ---
    @app_commands.command(name="apply", description="Apply for a role or position in the server.")
    @app_commands.guild_only()
    async def apply(self, interaction: discord.Interaction):
        """Opens the application panel for the user to select an application type."""
        guild_id_str = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id_str)
        app_types = guild_config.get("application_types", {})

        # Check if any application types are configured
        if not app_types:
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 No Applications Available", "No application types have been configured by the server administrators."), ephemeral=True)
            return

        # Check if the user meets the applicant role requirements
        if not await self.can_apply(interaction.user, interaction.guild_id):
            await interaction.response.send_message(embed=EmbedBuilder.error("🔒 Permission Denied", "You do not have the required roles to submit applications at this time."), ephemeral=True)
            return

        # Verify if there's at least one application type the user is NOT blacklisted from
        eligible_types_exist = False
        if isinstance(interaction.user, discord.Member): # Blacklist check is relevant only for Members
            for type_id in app_types:
                if not self.application_manager.is_blacklisted(guild_id_str, type_id, interaction.user, self.user_blacklist_manager):
                    eligible_types_exist = True
                    break # Found at least one eligible type, no need to check further
        else: # If not a Member (e.g., system message), consider eligible for display purposes
            eligible_types_exist = True

        # If no eligible types are found for the user
        if not eligible_types_exist and isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(embed=EmbedBuilder.error("🚫 No Eligible Applications", "No available application types are eligible for you based on current blacklists."), ephemeral=True)
            return

        # Display the Application Panel View
        view = ApplicationPanelView(self.bot, self.application_manager)
        await view.update_options(guild_id_str, interaction.user) # Update options considering the current user

        # Check if the view is still empty/disabled after updating options
        if not view.children or (isinstance(view.children[0], discord.ui.Select) and view.children[0].disabled):
             await interaction.response.send_message(embed=EmbedBuilder.error("🚫 No Eligible Applications", "No application types are currently available or eligible for you."), ephemeral=True)
             return

        embed = EmbedBuilder.info(title="📝 Available Applications", description="Select an application type from the dropdown to begin.")
        # Set embed color based on guild configuration
        panel_color_hex = guild_config.get("panel_color", "#3498DB") # Default blue
        try: embed.color = discord.Color.from_str(str(panel_color_hex))
        except: embed.color = discord.Color.blue() # Fallback color if invalid

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def start_application(self, interaction: discord.Interaction, type_id: str):
        """Handles the initiation of a specific application type, typically via DM."""
        guild_id_str = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id_str)
        application_type = guild_config.get("application_types", {}).get(type_id)

        # --- Pre-checks ---
        if not application_type: # Check if the application type still exists
            await interaction.response.send_message(embed=EmbedBuilder.error("Not Found", "This application type no longer exists."), ephemeral=True)
            return
        if not await self.can_apply(interaction.user, interaction.guild_id): # Check applicant role eligibility
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "You do not have the required roles to start this application."), ephemeral=True)
            return
        # Ensure user is a Member object for DM operations and role checks
        if not isinstance(interaction.user, discord.Member):
             await interaction.response.send_message(embed=EmbedBuilder.error("Error", "Could not verify your membership status. Please try again."), ephemeral=True)
             return
        if self.application_manager.is_blacklisted(guild_id_str, type_id, interaction.user, self.user_blacklist_manager): # Check blacklisting
            await interaction.response.send_message(embed=EmbedBuilder.error("Not Eligible", "You are blacklisted from this application type."), ephemeral=True)
            return

        questions = application_type.get("questions", [])
        if not questions: # Check if the application type has questions configured
            await interaction.response.send_message(embed=EmbedBuilder.error("No Questions Configured", "This application type has no questions configured. Please contact an admin."), ephemeral=True)
            return

        # Prevent starting multiple DM applications simultaneously
        if interaction.user.id in self.active_dm_applications:
            await interaction.response.send_message(embed=EmbedBuilder.warning("Application in Progress", "You already have an application in progress. Complete it or use `!cancelapp` in your DMs to cancel."), ephemeral=True)
            return

        # --- Initiate DM Application Process ---
        try:
            dm_channel = await interaction.user.create_dm() # Create DM channel for the application
        except discord.Forbidden: # Handle cases where DMs are blocked
            await interaction.response.send_message(embed=EmbedBuilder.error("DM Error", "I cannot send you DMs. Please ensure your privacy settings allow DMs from server members."), ephemeral=True)
            return
        except Exception as e: # Handle other potential DM errors
            logger.error(f"Failed to create DM channel for user {interaction.user.id}: {e}")
            await interaction.response.send_message(embed=EmbedBuilder.error("DM Error", "An unexpected error occurred while trying to DM you."), ephemeral=True)
            return

        # Store the state of the active DM application
        self.active_dm_applications[interaction.user.id] = {
            "guild_id": guild_id_str,
            "type_id": type_id,
            "application_type_name": application_type.get("name", "Application"), # Store type name for display
            "questions": questions,
            "current_question_index": 0, # Start with the first question (index 0)
            "responses": {}, # Dictionary to store user's answers
            "original_interaction": interaction, # Store the initial interaction context
            "dm_channel": dm_channel, # Store the DM channel object
            "last_message_time": time.time() # Track last activity time for timeouts
        }

        # Confirm to the user that the application has started in DMs
        await interaction.response.send_message(embed=EmbedBuilder.info("Application Started", f"The **{application_type.get('name')}** application has begun in your Direct Messages."), ephemeral=True)

        # Send the first question to the user
        await self.send_next_question_dm(interaction.user)

    async def send_next_question_dm(self, user: discord.User):
        """Sends the next question in the DM application sequence or finalizes it if all questions are answered."""
        if user.id not in self.active_dm_applications:
            return # Application state is missing or cancelled

        app_state = self.active_dm_applications[user.id]
        q_idx = app_state["current_question_index"]
        questions = app_state["questions"]

        # If all questions have been answered, finalize the application
        if q_idx >= len(questions):
            await self.finalize_dm_application(user)
            return

        question_data = questions[q_idx]
        q_text = question_data.get("text", f"Question {q_idx + 1}") # Get question text, provide fallback
        q_type = question_data.get("type", "text") # Default to text question type
        q_id = question_data.get("id", str(uuid.uuid4())) # Use stored ID or generate one (should be stored)

        try:
            # --- Create Embed for the Question ---
            embed = discord.Embed(
                title=f"📝 {app_state.get('application_type_name', 'Application')}",
                description=q_text,
                color=discord.Color.blue() # Default embed color
            )
            embed.set_footer(text=f"Question {q_idx + 1} of {len(questions)} | Type '!cancelapp' in this chat to cancel.")

            view_to_send = None # Initialize view to None

            # If it's an MCQ question, create the MCQAnswerView
            if q_type == "mcq":
                choices = question_data.get("choices", [])
                if choices:
                    view_to_send = MCQAnswerView(self, user, q_id, choices) # Create MCQ view
                else: # Handle misconfigured MCQ question (no choices)
                    embed.add_field(name="⚠️ Configuration Error", value="This question is misconfigured (missing choices). Please type your answer manually or contact an admin.")
            # For text questions, no special view is needed; user types directly.

            # Send the question message in the DM channel
            sent_msg = await app_state["dm_channel"].send(embed=embed, view=view_to_send)

            # If an MCQ view was created, store a reference to the sent message for later editing
            if view_to_send and isinstance(view_to_send, MCQAnswerView):
                view_to_send.message = sent_msg

            # Update the last message time for timeout tracking
            app_state["last_message_time"] = time.time()

        except discord.Forbidden:
            # Handle cases where the bot loses DM permission mid-application
            logger.warning(f"Failed to send question DM to {user.id} due to blocked DMs.")
            if app_state.get("original_interaction"): # Notify original interaction channel if possible
                try:
                    await app_state["original_interaction"].followup.send(embed=EmbedBuilder.error("DM Error", "I can no longer send you DMs. Your application has been cancelled."), ephemeral=True)
                except discord.HTTPException:
                    pass # Ignore if interaction failed
            # Clean up application state
            if user.id in self.active_dm_applications:
                del self.active_dm_applications[user.id]
        except Exception as e:
            logger.error(f"Error sending question DM to {user.id}: {e}", exc_info=True)
            # Inform user and cancel application on other errors
            await app_state["dm_channel"].send("❌ An unexpected error occurred while sending your question. Your application has been cancelled.")
            if user.id in self.active_dm_applications:
                del self.active_dm_applications[user.id]

    async def process_dm_mcq_response(self, user: discord.User, selected_answer: str):
        """Processes a selected MCQ answer, stores it, and sends the next question."""
        if user.id not in self.active_dm_applications: return # Exit if no active application state

        app_state = self.active_dm_applications[user.id]
        q_idx = app_state["current_question_index"]
        questions = app_state["questions"]

        # Ensure index is still valid (should be handled by send_next_question_dm)
        if q_idx >= len(questions): return

        # Store the selected answer against the corresponding question text
        current_question_text = questions[q_idx].get("text")
        app_state["responses"][current_question_text] = selected_answer

        # Advance to the next question and update last activity time
        app_state["current_question_index"] += 1
        app_state["last_message_time"] = time.time()

        # Send the next question in the sequence
        await self.send_next_question_dm(user)

    # Listener for messages in DMs to handle application answers
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Processes incoming messages from users during an active DM application."""
        # Ignore messages from bots, messages in guilds, or from users not in an active application
        if message.author.bot or message.guild is not None:
            return
        if message.author.id not in self.active_dm_applications:
            return

        app_state = self.active_dm_applications[message.author.id]

        # Ensure the message is within the correct DM channel for this application
        if message.channel.id != app_state["dm_channel"].id:
            return

        content = message.content.strip()
        q_idx = app_state.get("current_question_index", 0)
        questions = app_state.get("questions", [])

        # If application state is somehow finalized but not cleared, ignore message
        if q_idx >= len(questions):
            logger.debug(f"Received message from {message.author.id} for a finished application. Ignored.")
            return

        # --- Handle Application Commands (e.g., !cancelapp) ---
        if content.lower() == "!cancelapp":
            logger.info(f"User {message.author.id} cancelled their application via DM command.")
            await app_state["dm_channel"].send("✅ **Application cancelled.**")

            # Notify original interaction channel if possible
            original_interaction = app_state.get("original_interaction")
            if original_interaction:
                try:
                    await original_interaction.followup.send(embed=EmbedBuilder.info("Application Cancelled", "Your application process in DMs was cancelled."), ephemeral=True)
                except discord.HTTPException:
                    pass # Ignore if interaction failed

            # Remove application from active tracking and stop processing
            del self.active_dm_applications[message.author.id]
            return

        # --- Process Application Answers ---
        current_question_type = questions[q_idx].get("type")

        # Ignore text input for MCQ questions; button interaction is handled by MCQAnswerView
        if current_question_type == "mcq":
            logger.debug(f"Ignoring text message from {message.author.id} for MCQ. Waiting for button selection.")
            return

        # If it's a text question, accept the typed message as the answer
        else:
            try:
                current_question_text = questions[q_idx].get("text")
                app_state["responses"][current_question_text] = content # Store the answer

                # Advance to the next question and update last activity time
                app_state["current_question_index"] += 1
                app_state["last_message_time"] = time.time()

                # Send the next question or finalize the application
                await self.send_next_question_dm(message.author)

            except Exception as e:
                logger.error(f"Critical error processing text answer for {message.author.id}: {e}", exc_info=True)
                # Inform user of error and cancel application
                await app_state["dm_channel"].send("❌ An unexpected error occurred. Your application has been cancelled.")
                if message.author.id in self.active_dm_applications: # Clean up state
                    del self.active_dm_applications[message.author.id]

    async def finalize_dm_application(self, user: discord.User):
        """Completes the DM application process, saves data, and posts to the log channel."""
        if user.id not in self.active_dm_applications: return # Exit if application state is gone

        # Remove application state from tracking immediately to prevent race conditions
        app_state = self.active_dm_applications.pop(user.id)

        original_interaction = app_state.get("original_interaction")
        guild_id = app_state["guild_id"]
        guild = self.bot.get_guild(int(guild_id)) # Get guild object

        if not guild: # Safety check: should not happen if guild was valid initially
            logger.error(f"Guild {guild_id} not found during app finalization for user {user.id}.")
            await app_state["dm_channel"].send("Error: Could not find the server. Your application cannot be submitted.")
            return

        # --- Save Application Data ---
        guild_config = self.application_manager.get_guild_config(guild_id)
        guild_config["counter"] = guild_config.get("counter", 0) + 1 # Increment application counter
        app_id = f"{guild_id}-{guild_config['counter']}" # Generate unique application ID

        # Structure the data to be saved
        app_data_to_save = {
            "id": app_id,
            "type_id": app_state["type_id"],
            "type_name": app_state["application_type_name"],
            "user_id": str(user.id),
            "submit_time": datetime.now(utc=True).isoformat(), # Record submission time in UTC
            "status": "pending", # Initial status
            "responses": app_state["responses"] # Store all collected answers
        }

        # Add the application data to the guild's configuration
        guild_config.setdefault("applications", {})[app_id] = app_data_to_save
        self.application_manager.save_data() # Save the changes to file

        # --- Send Confirmation DM to User ---
        await app_state["dm_channel"].send(embed=EmbedBuilder.success("✅ Application Submitted!", f"Your **{app_state['application_type_name']}** application for **{guild.name}** has been submitted for review.\n\nYour Application ID is: `{app_id}`"))

        # Send confirmation to the original interaction channel
        if original_interaction:
            try:
                await original_interaction.followup.send(embed=EmbedBuilder.success("Application Submitted via DM", f"Your application for **{app_state['application_type_name']}** (ID: `{app_id}`) was successfully submitted via DMs."), ephemeral=True)
            except discord.HTTPException:
                pass # Ignore if original message edit fails

        # --- Post Application to Log Channel for Review ---
        await self.update_application_log(guild, app_data_to_save)

        # --- Send Hydra Ad Message ---
        # Informational message about the bot's developer (Hydra Development)
        ad_embed = discord.Embed(
            title="Thank You for Using Our Application System!",
            description="This bot was crafted with care by the **Hydra Development** team.\nWe specialize in creating custom, high-quality Discord bots tailored to your needs.",
            color=0x7289DA # Discord blurple color
        )
        ad_embed.add_field(
            name="Need a Custom Bot?",
            value="Whether for moderation, community engagement, games, or unique features, Hydra Development can build it. Visit our Discord for a quote!",
            inline=False
        )
        ad_embed.set_thumbnail(url="https://i.imgur.com/2UfV8M5.png") # Placeholder URL for Hydra logo
        ad_embed.set_footer(text="Hydra Development | Quality Bots for Your Community")

        # Button linking to the Hydra Development Discord server
        ad_view = discord.ui.View()
        # Using a placeholder emoji ID for the Hydra server. Replace if needed.
        ad_view.add_item(discord.ui.Button(label="Join Hydra Development Discord", style=discord.ButtonStyle.link, url="https://discord.gg/jcyP5qKKmp"))

        try:
            await app_state["dm_channel"].send(embed=ad_embed, view=ad_view)
        except Exception as e:
            logger.error(f"Failed to send Hydra ad to user {user.id}: {e}")

    async def update_application_log(self, guild: discord.Guild, application_data: Dict):
        """Updates the log channel message with the application's status (pending, accepted, denied)."""
        guild_id_str = str(guild.id)
        guild_config = self.application_manager.get_guild_config(guild_id_str)
        log_channel_id_str = guild_config.get("log_channel_id")

        if not log_channel_id_str:
            logger.debug(f"No log channel configured for guild {guild_id_str}. Skipping log update.")
            return

        try: log_channel_id = int(log_channel_id_str)
        except ValueError:
            logger.error(f"Invalid log_channel_id '{log_channel_id_str}' for guild {guild_id_str}.")
            return

        log_channel = guild.get_channel(log_channel_id)
        if not isinstance(log_channel, discord.TextChannel):
            logger.warning(f"Log channel {log_channel_id} for guild {guild_id_str} not found or not a text channel.")
            return

        app_id = application_data.get("id")
        log_message_id_str = application_data.get("log_message_id") # Get ID of the log message if it exists for editing

        # Create the embed representation of the application for the log channel
        embed = await self.create_application_embed(guild, application_data)

        # Determine if the review view (Accept/Deny buttons) should be attached
        view_to_use = None
        if application_data.get("status") == "pending":
            # Pass applicant_user_id to the view for context in modals
            view_to_use = ApplicationReviewView(self.bot, self.application_manager, app_id, application_data.get("user_id"))

        try:
            if log_message_id_str: # If a log message already exists, try to edit it
                try:
                    message = await log_channel.fetch_message(int(log_message_id_str))
                    await message.edit(embed=embed, view=view_to_use) # Edit with updated embed and view
                    return # Exit if edit was successful
                except (discord.NotFound, discord.Forbidden):
                    pass # If message not found or inaccessible, proceed to send a new one

            # If no existing message or editing failed, send a new message
            message = await log_channel.send(embed=embed, view=view_to_use)
            # Store the ID of the new log message for future edits
            application_data["log_message_id"] = str(message.id)
            self.application_manager.save_data()
        except Exception as e:
            logger.error(f"Error updating or sending application log for app {app_id} in guild {guild_id_str}: {e}", exc_info=True)

    async def create_application_embed(self, guild: discord.Guild, application_data: Dict) -> discord.Embed:
        """Creates a rich embed representation of an application for the log channel."""
        status = application_data.get("status", "pending")

        # Determine embed color based on application status
        if status == "pending": color = discord.Color.gold()
        elif status == "accepted": color = discord.Color.green()
        elif status == "denied": color = discord.Color.red()
        else: color = discord.Color.light_grey() # Fallback color

        user_id_str = application_data.get("user_id")
        user = None
        # Try to fetch the applicant user object (member or user)
        if user_id_str:
            try:
                user = guild.get_member(int(user_id_str))
                if not user: user = await self.bot.fetch_user(int(user_id_str)) # Fetch globally if not in guild cache
            except (ValueError, TypeError, discord.NotFound, discord.Forbidden):
                pass # Ignore errors if user ID is invalid, user not found, or bot lacks fetch_users permission

        # Format user display: mention if possible, otherwise show ID
        user_display = f"{user.mention} (`{user_id_str}`)" if user else f"Unknown User (`{user_id_str}`)"

        # Prepare embed description with basic application info
        embed_description = f"**Applicant:** {user_display}\n"
        submit_time_iso = application_data.get('submit_time')
        if submit_time_iso:
            try:
                submit_timestamp = int(datetime.fromisoformat(submit_time_iso).timestamp())
                embed_description += f"**Submitted:** <t:{submit_timestamp}:R>" # Use relative time formatting
            except ValueError: # Handle potential ISO format errors
                embed_description += f"**Submitted:** {submit_time_iso}"

        # Create the main embed object
        embed = discord.Embed(
            title=f"{status.capitalize()} Application: {application_data.get('type_name', 'Unknown Type')}",
            description=embed_description,
            color=color
        )

        # Add application questions and answers as fields
        responses = application_data.get("responses", {})
        for question, answer in responses.items():
            embed.add_field(name=question[:250], value=answer[:1000], inline=False) # Truncate question/answer if too long

        # Add review details if the application has been processed (accepted/denied)
        if status != "pending":
            reviewer_id_str = application_data.get("reviewer_id")
            if reviewer_id_str:
                reviewer = None
                try:
                    reviewer = guild.get_member(int(reviewer_id_str))
                    if not reviewer: reviewer = await self.bot.fetch_user(int(reviewer_id_str))
                except Exception: pass # Ignore errors fetching reviewer

                reviewer_display = reviewer.mention if reviewer else f"ID: {reviewer_id_str}"
                embed.add_field(name="Reviewed by", value=reviewer_display, inline=True)

            review_time_iso = application_data.get("review_time")
            if review_time_iso:
                try:
                    review_timestamp = int(datetime.fromisoformat(review_time_iso).timestamp())
                    embed.add_field(name="Review Time", value=f"<t:{review_timestamp}:R>", inline=True)
                except ValueError:
                    embed.add_field(name="Review Time", value=review_time_iso, inline=True)

            # Add assigned role info if the application was accepted
            if status == "accepted":
                assigned_role_id = application_data.get("assigned_role_id")
                if assigned_role_id:
                    role = guild.get_role(int(assigned_role_id))
                    role_display = role.mention if role else f"Role ID: `{assigned_role_id}` (Not found)"
                    embed.add_field(name="Assigned Role", value=role_display, inline=True)

            # Add the review reason if provided
            reason = application_data.get("reason")
            if reason:
                embed.add_field(name="Reason", value=reason[:1000], inline=False) # Truncate reason if too long

        # Add application ID to the footer for easy reference
        embed.set_footer(text=f"Application ID: {application_data.get('id')}")
        return embed

    # --- Admin Command: Check the status of the application panel ---
    @app_commands.command(name="panel_status", description="Check the status and configuration of the application panel.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def panel_status(self, interaction: discord.Interaction):
        """Displays current settings and status of the application panel."""
        if not await is_admin(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "Admin permissions are required."), ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id)
        panel_channel_id = guild_config.get("panel_channel_id")
        panel_message_id = guild_config.get("panel_message_id")
        last_panel_update = guild_config.get("last_panel_update")
        last_panel_error = guild_config.get("last_panel_error")

        embed = EmbedBuilder.info("Application Panel Status", "")

        if not panel_channel_id: # If no panel channel is configured
            embed.description = "No panel channel has been set. Use `/setup_applications` to configure."
        else:
            # Try to fetch and display channel information
            channel = None
            try:
                channel = interaction.guild.get_channel(int(panel_channel_id))
                if not channel: channel = await self.bot.fetch_channel(int(panel_channel_id)) # Fetch if not cached

                embed.add_field(name="Panel Channel", value=channel.mention if channel else f"ID: `{panel_channel_id}` (Not Found)", inline=True)

                # Check status of the panel message
                if panel_message_id:
                    if channel: # Only attempt fetch if channel is valid
                        try:
                            message = await channel.fetch_message(int(panel_message_id))
                            embed.add_field(name="Panel Message", value=f"[Jump to Message]({message.jump_url})", inline=True)
                        except (discord.NotFound, discord.Forbidden): # If message is missing or inaccessible
                            embed.add_field(name="Panel Message", value=f"Message ID: `{panel_message_id}` (Not Found or Inaccessible)", inline=True)
                    else: # If channel is invalid, message status is also affected
                        embed.add_field(name="Panel Message", value=f"Message ID: `{panel_message_id}` (Channel Invalid)", inline=True)
                else:
                    embed.add_field(name="Panel Message", value="No panel message has been posted yet.", inline=True)

                # Display bot permissions for the panel channel
                if channel:
                    permissions = channel.permissions_for(interaction.guild.me)
                    embed.add_field(name="Bot Permissions", value=f"Send Messages: {permissions.send_messages}\nEmbed Links: {permissions.embed_links}\nView Channel: {permissions.view_channel}", inline=False)

                # Display last update time and any recorded errors
                if last_panel_update:
                    embed.add_field(name="Last Update", value=f"<t:{int(datetime.fromisoformat(last_panel_update).timestamp())}:R>", inline=True)
                if last_panel_error:
                    embed.add_field(name="Last Error", value=last_panel_error[:1000], inline=False) # Truncate error message

            except Exception as e: # Catch errors during channel/message fetching
                embed.add_field(name="Status Error", value=f"Could not retrieve panel details: {e}", inline=False)
                logger.error(f"Error getting panel status for guild {guild_id}: {e}", exc_info=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- Admin Command: Fix Invalid Emojis ---
    @app_commands.command(name="fix_emojis", description="Identifies and resets invalid emojis in application type configurations.")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def fix_emojis(self, interaction: discord.Interaction):
        """Finds and offers to remove invalid emojis from application types."""
        if not await is_admin(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "Admin permissions are required."), ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id)
        app_types = guild_config.get("application_types", {})

        # Find application types with invalid emojis
        invalid_emojis_info = []
        for type_id, data in app_types.items():
            emoji_val = data.get("emoji")
            if emoji_val and not self.validate_emoji(emoji_val): # Use validator function
                invalid_emojis_info.append({"id": type_id, "name": data.get("name", "Unnamed Type"), "emoji": emoji_val})

        if not invalid_emojis_info: # If no invalid emojis are found
            await interaction.response.send_message(embed=EmbedBuilder.success("No Invalid Emojis", "All configured application type emojis are valid."), ephemeral=True)
            return

        # Display the found invalid emojis in an embed
        embed = EmbedBuilder.info("Invalid Emojis Found", "The following application types have invalid emojis configured:")
        for info in invalid_emojis_info:
            embed.add_field(name=f"{info['name']} (ID: `{info['id'][:8]}...`)", value=f"Invalid Emoji: `{info['emoji']}`", inline=False)

        # Add a button to reset the invalid emojis
        view = discord.ui.View(timeout=300)
        reset_button = discord.ui.Button(label="Reset Invalid Emojis", style=discord.ButtonStyle.danger, emoji="🔧")

        async def reset_cb(inter: discord.Interaction):
            await inter.response.defer(ephemeral=True) # Defer the button interaction
            try:
                # Iterate through invalid emojis and reset their emoji field to None
                for info in invalid_emojis_info:
                    type_id_to_reset = info["id"]
                    if type_id_to_reset in guild_config.get("application_types", {}):
                        guild_config["application_types"][type_id_to_reset]["emoji"] = None
                self.application_manager.save_data() # Save changes

                # Attempt to update the application panel to reflect the removal
                await self.update_application_panel(inter.guild, inter.user)

                await inter.followup.send(embed=EmbedBuilder.success("Emojis Reset", "Invalid emojis have been removed from application type configurations."), ephemeral=True)
            except Exception as e: # Handle errors during reset
                await inter.followup.send(embed=EmbedBuilder.error("Error Resetting Emojis", f"An error occurred: {e}"), ephemeral=True)
                logger.error(f"Error resetting emojis: {e}", exc_info=True)

            # Disable buttons after action completion
            for item_v in view.children: item_v.disabled = True
            try: await inter.edit_original_response(view=view)
            except: pass # Ignore edit errors

        reset_button.callback = reset_cb
        view.add_item(reset_button)

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # Autocomplete helper for selecting application types by name or ID
    async def application_type_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Provides autocomplete suggestions for application type names."""
        guild_id = str(interaction.guild.id)
        guild_config = self.application_manager.get_guild_config(guild_id)
        app_types = guild_config.get("application_types", {})

        # Filter types based on current input string matching name or ID
        choices = [
            app_commands.Choice(name=data.get("name", type_id)[:100], value=type_id) # Limit suggestion name length
            for type_id, data in app_types.items()
            # Match if current input is empty OR matches name/ID (case-insensitive)
            if not current or current.lower() in data.get("name", type_id).lower() or current.lower() in type_id.lower()
        ]
        return choices[:25] # Discord limits autocomplete suggestions to 25

    # --- Admin Command: Blacklist a user from a specific application type ---
    @app_commands.command(name="app_blacklist", description="Blacklist a user from a specific application type.")
    @app_commands.guild_only()
    @app_commands.autocomplete(application_type=application_type_autocomplete) # Use autocomplete for selecting application type
    @app_commands.default_permissions(manage_guild=True) # Require manage guild permission
    async def app_blacklist_command(self, interaction: discord.Interaction, user: discord.Member, application_type: str):
        """Blacklists a user from an application type, optionally assigning configured roles."""
        if not await is_admin(interaction.user): # Double-check admin permission
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "Only administrators can manage blacklists."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True) # Defer response for processing

        guild_id, user_id_str = str(interaction.guild.id), str(user.id)
        guild_config = self.application_manager.get_guild_config(guild_id)
        app_type_data = guild_config.get("application_types", {}).get(application_type)

        app_name = app_type_data.get("name", application_type) if app_type_data else application_type # Get type name for messages

        if not app_type_data: # If application type is not found
            await interaction.followup.send(embed=EmbedBuilder.error("Not Found", f"Application type ID `{application_type}` not found."), ephemeral=True)
            return

        # Add user to the JSON blacklist for this application type
        self.user_blacklist_manager.add_application_blacklist(guild_id, user_id_str, application_type)
        json_msg = f"{user.mention} has been blacklisted from **{app_name}** (JSON)."

        roles_ids_str = app_type_data.get("blacklisted_roles", []) # Get configured roles for blacklisting
        roles_to_assign = []
        failed_role_ids = []

        # Identify roles to assign and validate them
        if roles_ids_str:
            for r_id_str in roles_ids_str:
                try:
                    role = interaction.guild.get_role(int(r_id_str))
                    if role: roles_to_assign.append(role)
                    else: failed_role_ids.append(r_id_str) # Store invalid/missing role IDs
                except (ValueError, TypeError): failed_role_ids.append(r_id_str) # Store malformed IDs

        assigned_mentions = []
        role_assignment_feedback = "" # Feedback string for role assignment status

        # Attempt to assign roles if any valid ones were found
        if roles_to_assign:
            try:
                # Add roles to the user
                await user.add_roles(*roles_to_assign, reason=f"Blacklisted from app '{app_name}' by {interaction.user.name}")
                assigned_mentions = [r.mention for r in roles_to_assign]
                role_assignment_feedback = f"Assigned roles: {', '.join(assigned_mentions)}."
                # Log the role assignment action
                await log_action(interaction.guild, "APP_BLACKLIST_ROLE_ASSIGNED", interaction.user, f"Assigned {', '.join(r.name for r in roles_to_assign)} to {user.name} for app '{app_name}'.", "applications")
            except discord.Forbidden: # Handle missing bot permissions
                role_assignment_feedback = "Bot lacks permissions to assign roles."
                await log_action(interaction.guild, "APP_BLACKLIST_ROLE_PERMISSION_ERROR", interaction.user, f"Could not assign roles to {user.name} for app '{app_name}' due to permissions.", "applications")
            except Exception as e: # Handle other role assignment errors
                role_assignment_feedback = f"An error occurred assigning roles: {e}"
                await log_action(interaction.guild, "APP_BLACKLIST_ROLE_ASSIGN_ERROR", interaction.user, f"Error assigning roles to {user.name} for app '{app_name}': {e}", "applications")

        # Compile final feedback message for the user
        final_message_parts = [json_msg]
        if role_assignment_feedback: final_message_parts.append(role_assignment_feedback)
        if failed_role_ids: # Inform about invalid role IDs in configuration
            final_message_parts.append(f"Note: Some configured blacklisted role IDs were invalid or not found: `{', '.join(failed_role_ids)}`")
            await log_action(interaction.guild, "APP_BLACKLIST_INVALID_ROLE_IDS", interaction.user, f"Configured blacklisted role IDs {', '.join(failed_role_ids)} were invalid/not found for type '{app_name}'.", "applications")
        else: # Log general success if no errors/warnings
            await log_action(interaction.guild, "APP_BLACKLIST_ADD_SUCCESS", interaction.user, f"Successfully blacklisted {user.name} from '{app_name}' (JSON + Roles).", "applications")

        await interaction.response.send_message(embed=EmbedBuilder.success("User Blacklisted", "\n".join(final_message_parts)), ephemeral=True)

    # --- Admin Command: Unblacklist a user from an application type ---
    @app_commands.command(name="app_unblacklist", description="Unblacklist a user from a specific application type.")
    @app_commands.guild_only()
    @app_commands.autocomplete(application_type=application_type_autocomplete) # Use autocomplete for type selection
    @app_commands.default_permissions(manage_guild=True) # Require manage guild permission
    async def app_unblacklist_command(self, interaction: discord.Interaction, user: discord.Member, application_type: str):
        """Unblacklists a user, attempting to remove associated blacklisted roles."""
        if not await is_admin(interaction.user):
            await interaction.response.send_message(embed=EmbedBuilder.error("Permission Denied", "Only administrators can manage blacklists."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True) # Defer response

        guild_id, user_id_str = str(interaction.guild.id), str(user.id)
        guild_config = self.application_manager.get_guild_config(guild_id)
        app_type_data = guild_config.get("application_types", {}).get(application_type)

        app_name = app_type_data.get("name", application_type) if app_type_data else application_type

        # Remove user from JSON blacklist
        removed_from_json = self.user_blacklist_manager.remove_application_blacklist(guild_id, user_id_str, application_type)
        json_feedback_part = f"{user.mention} " + ("removed from" if removed_from_json else "not found in") + f" JSON blacklist for **{app_name}**."
        log_parts, final_feedback_parts = [f"User {user.mention} unblacklisted from '{app_name}' (JSON " + ("removed" if removed_from_json else "not found") + ")."], [json_feedback_part]

        # Handle case where application type configuration is missing
        if not app_type_data:
            await log_action(interaction.guild, "APP_UNBLACKLIST_NO_TYPE", interaction.user, " ".join(log_parts) + " App type config not found.", "applications")
            await interaction.followup.send(embed=EmbedBuilder.warning("User Unblacklisted (JSON)", f"{json_feedback_part}\nApp type config not found, cannot manage roles."), ephemeral=True)
            return

        roles_ids_str = app_type_data.get("blacklisted_roles", [])
        roles_to_remove = []

        # Find configured blacklisted roles that the user currently possesses
        if roles_ids_str:
            for r_id_str in roles_ids_str:
                try:
                    role = interaction.guild.get_role(int(r_id_str))
                    if role and role in user.roles: # Check if role exists and user has it
                        roles_to_remove.append(role)
                except (ValueError, TypeError):
                    pass # Ignore invalid role IDs in config

        removed_mentions = []
        role_removal_feedback = ""
        # Attempt to remove the identified roles
        if roles_to_remove:
            try:
                await user.remove_roles(*roles_to_remove, reason=f"Unblacklisted from app '{app_name}' by {interaction.user.name}")
                removed_mentions = [r.mention for r in roles_to_remove]
                role_removal_feedback = f"Successfully removed roles: {', '.join(removed_mentions)}."
                log_parts.append(f"Removed roles: {', '.join(r.name for r in roles_to_remove)}.")
            except discord.Forbidden: # Handle missing bot permissions
                role_removal_feedback = f"Failed to remove roles for {user.mention}: Bot lacks permissions."
                log_parts.append("FAILED to remove roles (permissions).")
            except Exception as e: # Handle other role removal errors
                role_removal_feedback = f"Error removing roles for {user.mention}: {e}"
                log_parts.append(f"Error removing roles: {e}")
        elif roles_ids_str: # If roles were configured but user didn't have them
            role_removal_feedback = f"User {user.mention} did not have any configured blacklisted roles."
        else: # If no blacklisted roles were configured for this type
            role_removal_feedback = f"No blacklisted roles were configured for application type **{app_name}**."

        # Compile final feedback message
        final_feedback_parts = [json_feedback_part]
        if role_removal_feedback: final_feedback_parts.append(role_removal_feedback)

        # Log the overall unblacklist action
        await log_action(interaction.guild, "APP_UNBLACKLIST", interaction.user, " ".join(log_parts), "applications")

        await interaction.response.send_message(embed=EmbedBuilder.success("User Unblacklisted", "\n".join(final_feedback_parts)), ephemeral=True)

    async def can_review_applications(self, user: discord.Member, guild_id: Union[int, str]) -> bool:
        """Checks if a user has permission to review applications (admin or specific roles)."""
        if await is_admin(user): return True # Admins always have permission

        guild_id_str = str(guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id_str)
        reviewer_roles = guild_config.get("reviewer_roles", [])

        if not reviewer_roles: return False # No reviewer roles configured and user is not admin

        # Check if the user possesses any of the configured reviewer roles
        return any(str(role.id) in reviewer_roles for role in user.roles)

    async def can_apply(self, user: discord.Member, guild_id: Union[int, str]) -> bool:
        """Checks if a user is eligible to apply based on configured applicant roles."""
        guild_id_str = str(guild_id)
        guild_config = self.application_manager.get_guild_config(guild_id_str)
        applicant_roles = guild_config.get("applicant_roles", [])

        if not applicant_roles: return True # If no applicant roles are specified, everyone can apply

        # Check if the user possesses any of the configured applicant roles
        return any(str(role.id) in applicant_roles for role in user.roles)

    async def send_status_dm(self, guild: discord.Guild, applicant_user: Optional[Union[discord.Member, discord.User]], status: str, reason: str, reviewer: discord.User, application_id: str, type_name: Optional[str] = None):
        """Helper function to send a DM to the applicant about their application status."""
        if not applicant_user:
            logger.warning(f"Cannot send status DM for application {application_id}: Applicant user object is missing.")
            return

        dm_channel = None
        try:
            dm_channel = await applicant_user.create_dm()
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning(f"Failed to create DM channel for user {applicant_user.id} (app {application_id}): {e}")
            return # Cannot send DM if channel creation fails

        # Determine embed color based on status
        if status.lower() == "accepted":
            embed_color = discord.Color.green()
        elif status.lower() == "denied":
            embed_color = discord.Color.red()
        else:
            embed_color = discord.Color.gold() # Default for pending or other statuses

        # Construct the embed message for the DM
        embed = discord.Embed(
            title=f"Application Update: {type_name or 'Your Application'}",
            description=f"Your application **{application_id}** for **{guild.name}** has been **{status}**.",
            color=embed_color
        )

        embed.add_field(name="Status", value=status, inline=True)

        if reason: # Add reason if provided
            embed.add_field(name="Reason", value=reason, inline=False)

        # Add reviewer information
        reviewer_mention = reviewer.mention if hasattr(reviewer, 'mention') else str(reviewer)
        embed.add_field(name="Reviewed by", value=reviewer_mention, inline=True)

        embed.set_footer(text=f"Application ID: {application_id}")

        try:
            await dm_channel.send(embed=embed)
            await log_action(guild, f"APP_STATUS_DM_{status.upper()}", reviewer, f"Sent status DM to applicant {applicant_user.id} for app {application_id}.", "applications")
        except Exception as e:
            logger.error(f"Failed to send status DM to user {applicant_user.id} for app {application_id}: {e}", exc_info=True)

    # Background task loop to check for DM application timeouts
    @tasks.loop(seconds=60)
    async def check_dm_application_timeouts(self):
        """Checks active DM applications for inactivity and cancels them if they time out."""
        current_time = time.time()
        timed_out_user_ids = []

        # Iterate through active applications to find inactive ones
        for user_id, app_state in list(self.active_dm_applications.items()):
            # Timeout threshold: 15 minutes (900 seconds) of inactivity
            if current_time - app_state.get("last_message_time", current_time) > 900:
                timed_out_user_ids.append(user_id)

        # Process each timed-out application
        for user_id in timed_out_user_ids:
            if user_id in self.active_dm_applications:
                app_state = self.active_dm_applications[user_id]
                original_interaction = app_state.get("original_interaction")
                dm_channel = app_state.get("dm_channel")

                try:
                    # Notify the user in DM about the timeout and cancellation
                    if dm_channel: await dm_channel.send("Your application session has timed out due to inactivity and has been cancelled.")
                    # Notify the original interaction channel if available
                    if original_interaction:
                         await original_interaction.followup.send(embed=EmbedBuilder.warning("Application Timeout", "Your application session timed out and has been cancelled."), ephemeral=True)
                except Exception as e: logger.error(f"Error notifying user {user_id} of DM timeout: {e}")
                finally:
                    # Remove the application from active tracking
                    if user_id in self.active_dm_applications:
                        del self.active_dm_applications[user_id]

    # Ensure the bot is ready before starting the task loop
    @check_dm_application_timeouts.before_loop
    async def before_check_dm_timeouts(self):
        await self.bot.wait_until_ready()

# Function to setup the cog when it's loaded into the bot
async def setup(bot):
    await bot.add_cog(ApplicationCommands(bot))