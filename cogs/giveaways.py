import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import datetime
import json
from typing import Optional, Dict

# --- UI Components: Modal for custom duration ---
class CustomDurationModal(discord.ui.Modal, title="Set Custom Duration"):
    hours = discord.ui.TextInput(label="Hours", placeholder="e.g., 2", default="0", required=False, style=discord.TextStyle.short)
    minutes = discord.ui.TextInput(label="Minutes", placeholder="e.g., 30", default="0", required=False, style=discord.TextStyle.short)

    def __init__(self):
        super().__init__()

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hours = int(self.hours.value or 0)
            minutes = int(self.minutes.value or 0)
            if hours < 0 or minutes < 0 or (hours == 0 and minutes == 0):
                raise ValueError("Duration must be positive.")
            self.result = hours * 3600 + minutes * 60
            await interaction.response.defer()
        except ValueError as e:
            await interaction.response.send_message(f"Invalid duration: {e}. Please enter non-negative numbers.", ephemeral=True)
            self.result = None
        self.stop()

# --- UI Components: Modal for text input ---
class TextInputModal(discord.ui.Modal):
    def __init__(self, field: str, default: str, required: bool = False, is_paragraph: bool = False):
        super().__init__(title=f"Set {field}")
        self.result = None
        self.add_item(discord.ui.TextInput(
            label=field,
            default=default,
            placeholder=f"Enter the {field.lower()}",
            required=required,
            style=discord.TextStyle.paragraph if is_paragraph else discord.TextStyle.short
        ))

    async def on_submit(self, interaction: discord.Interaction):
        self.result = self.children[0].value
        await interaction.response.defer()
        self.stop()

# --- UI Components: Main interactive setup view ---
class GiveawaySetupView(discord.ui.View):
    def __init__(self, author: discord.User, is_poll: bool = False):
        super().__init__(timeout=600)
        self.author = author
        self.is_poll = is_poll
        self.finished = False
        self.message = None  # Track the message to edit
        self.responses = {
            "Item": "A Mystery Prize" if not is_poll else "Your Question Here",
            "Winners/Options": 1 if not is_poll else ["Yes", "No"],
            "Duration": 3600,  # Default: 1 hour
            "Max Participants": 100,
            "Required Roles": []
        }
        self.steps = [
            ("Item", "Prize (e.g., Nitro)" if not is_poll else "Question (e.g., Favorite color?)", True, True),
            ("Winners/Options", "Number of winners" if not is_poll else "Comma-separated options (e.g., Red,Blue)", True, False),
            ("Duration", "How long the event runs", False, False),
            ("Max Participants", "Max entrants/voters", False, False),
            ("Required Roles", "Roles needed to participate", False, False),
        ]
        self.current_step = 0
        self.update_buttons()

    def update_buttons(self):
        if self.current_step < len(self.steps):
            self.set_button.label = f"Set: {self.steps[self.current_step][0]}"
            self.set_button.disabled = False
        else:
            self.set_button.disabled = True
        self.back_button.disabled = self.current_step == 0
        self.finish_button.disabled = self.current_step < len(self.steps) - 1 and not self.finished

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("Only the person who started the setup can interact.", ephemeral=True)
            return False
        return True

    def create_embed(self):
        item_key = "Question" if self.is_poll else "Prize"
        options_key = "Options" if self.is_poll else "Winners"
        max_part_key = "Max Voters" if self.is_poll else "Max Entrants"
        options_val = self.responses["Winners/Options"]
        options_display = ', '.join(options_val) if isinstance(options_val, list) else options_val

        embed = discord.Embed(
            title=f"🎉 {'Poll' if self.is_poll else 'Giveaway'} Setup",
            description=(
                f"**Configure your {'poll' if self.is_poll else 'giveaway'} step by step.**\n"
                f"Current step: **{self.steps[self.current_step][0] if self.current_step < len(self.steps) else 'Review'}**\n\n"
                f"📝 **{item_key}**: {self.responses['Item']}\n"
                f"🏆 **{options_key}**: {options_display}\n"
                f"⏰ **Duration**: {datetime.timedelta(seconds=self.responses['Duration'])}\n"
                f"👥 **{max_part_key}**: {self.responses['Max Participants']}\n"
                f"🔒 **Required Roles**: {', '.join([r.mention for r in self.responses['Required Roles']]) if self.responses['Required Roles'] else 'None'}"
            ),
            color=discord.Color.blue()
        )
        progress = "█" * (self.current_step + 1) + "░" * (len(self.steps) - self.current_step - 1)
        embed.set_footer(text=f"Progress: {progress} ({self.current_step + 1}/{len(self.steps)})")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        if self.finished or self.current_step >= len(self.steps):
            self.finished = True
            embed = discord.Embed(
                title=f"✅ {'Poll' if self.is_poll else 'Giveaway'} Ready!",
                description=(
                    f"**Summary:**\n"
                    f"📝 {'Question' if self.is_poll else 'Prize'}: {self.responses['Item']}\n"
                    f"🏆 {'Options' if self.is_poll else 'Winners'}: {', '.join(self.responses['Winners/Options']) if isinstance(self.responses['Winners/Options'], list) else self.responses['Winners/Options']}\n"
                    f"⏰ Duration: {datetime.timedelta(seconds=self.responses['Duration'])}\n"
                    f"👥 Max {'Voters' if self.is_poll else 'Entrants'}: {self.responses['Max Participants']}\n"
                    f"🔒 Required Roles: {', '.join([r.mention for r in self.responses['Required Roles']]) if self.responses['Required Roles'] else 'None'}\n\n"
                    f"Click 'Finish & Create' to start!"
                ),
                color=discord.Color.green()
            )
            self.update_buttons()
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, view=self, ephemeral=True)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        else:
            self.update_buttons()
            embed = self.create_embed()
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, view=self, ephemeral=True)
            else:
                await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Set Current Step", style=discord.ButtonStyle.primary, row=0)
    async def set_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_step >= len(self.steps):
            return  # Prevent further actions after last step

        field, description, required, is_paragraph = self.steps[self.current_step]
        
        if field == "Duration":
            duration_view = DurationSelectView(self)
            await interaction.response.send_message(embed=discord.Embed(
                title="⏰ Select Duration",
                description="Choose a preset duration or set a custom one.",
                color=discord.Color.blue()
            ), view=duration_view, ephemeral=True)
            await duration_view.wait()
            if duration_view.result is not None:
                self.responses['Duration'] = duration_view.result
                self.current_step += 1
                await self.update_message(interaction)
        elif field == "Required Roles":
            role_select = discord.ui.RoleSelect(placeholder="Select required roles (or none)", max_values=10)
            role_view = discord.ui.View(timeout=180)
            role_view.add_item(role_select)
            async def role_callback(inter: discord.Interaction):
                self.responses['Required Roles'] = [inter.guild.get_role(int(r_id)) for r_id in inter.data.get("values", [])]
                self.finished = True  # Set finished instead of incrementing step
                await inter.response.edit_message(content="Roles updated!", view=None)
                await self.update_message(inter)  # Update with summary embed
            role_select.callback = role_callback
            await interaction.response.send_message("Select roles required to participate.", view=role_view, ephemeral=True)
        else:
            modal = TextInputModal(field=field, default=str(self.responses.get(field, "")), required=required, is_paragraph=is_paragraph)
            await interaction.response.send_modal(modal)
            await modal.wait()

            if modal.result:
                try:
                    if field == "Item":
                        self.responses['Item'] = modal.result
                    elif field == "Winners/Options":
                        if self.is_poll:
                            opts = [opt.strip() for opt in modal.result.split(',') if opt.strip()]
                            if len(opts) < 2:
                                raise ValueError("Polls require at least 2 options (e.g., Yes,No).")
                            self.responses['Winners/Options'] = opts[:25]
                        else:
                            winners = int(modal.result)
                            if winners < 1:
                                raise ValueError("Number of winners must be at least 1.")
                            self.responses['Winners/Options'] = winners
                    elif field == "Max Participants":
                        participants = int(modal.result)
                        if participants < 1:
                            raise ValueError("Max participants must be at least 1.")
                        self.responses['Max Participants'] = participants
                    self.current_step += 1
                    await self.update_message(interaction)
                except ValueError as e:
                    await interaction.followup.send(f"Invalid input: {e}", ephemeral=True)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_step > 0:
            self.current_step -= 1
            self.finished = False
            await self.update_message(interaction)

    @discord.ui.button(label="Finish & Create", style=discord.ButtonStyle.success, row=2)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        await interaction.response.edit_message(content=f"{'Poll' if self.is_poll else 'Giveaway'} setup complete! Creating...", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=2)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"{'Poll' if self.is_poll else 'Giveaway'} setup cancelled.", embed=None, view=None)
        self.stop()

# --- UI Components: Duration selection view ---
class DurationSelectView(discord.ui.View):
    def __init__(self, parent_view: 'GiveawaySetupView'):
        super().__init__(timeout=180)
        self.parent_view = parent_view
        self.result = None
        durations = [
            (600, "10 Minutes"), (1800, "30 Minutes"), (3600, "1 Hour"),
            (86400, "1 Day"), (604800, "1 Week")
        ]
        select = discord.ui.Select(placeholder="Choose a duration", options=[
            discord.SelectOption(label=label, value=str(seconds)) for seconds, label in durations
        ])
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        self.result = int(interaction.data["values"][0])
        await interaction.response.edit_message(content="Duration set!", view=None)
        self.stop()

    @discord.ui.button(label="Custom Duration", style=discord.ButtonStyle.secondary)
    async def custom_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CustomDurationModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.result is not None:
            self.result = modal.result
            await interaction.message.edit(content="Duration set!", view=None)
            self.stop()

# --- UI Components: View for entering giveaways ---
class GiveawayEnterView(discord.ui.View):
    def __init__(self, giveaway_cog: 'GiveawayCog', host_id: int):
        super().__init__(timeout=None)
        self.giveaway_cog = giveaway_cog
        self.host_id = host_id

    @discord.ui.button(label="Enter", style=discord.ButtonStyle.primary, emoji="🎉", custom_id="gw_enter_button")
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = self.giveaway_cog.giveaways.get(interaction.message.id)
        if not giveaway:
            button.disabled = True
            await interaction.response.edit_message(content="This giveaway has ended or could not be found.", embed=None, view=self)
            return

        user_id = interaction.user.id
        required_roles = giveaway.get("required_roles", [])
        if required_roles and not any(role.id in required_roles for role in interaction.user.roles):
            return await interaction.response.send_message("You don't have the required role(s) to enter.", ephemeral=True)
            
        if user_id in giveaway["entrants"]:
            giveaway["entrants"].remove(user_id)
            await interaction.response.send_message("You have left the giveaway.", ephemeral=True)
        elif len(giveaway["entrants"]) < giveaway["max_applicants"]:
            giveaway["entrants"].append(user_id)
            await interaction.response.send_message("You have entered the giveaway! Good luck!", ephemeral=True)
        else:
            await interaction.response.send_message("This giveaway is already full.", ephemeral=True)
        
        self.giveaway_cog.save_giveaways() # Save after entrant change

    @discord.ui.button(label="End Early", style=discord.ButtonStyle.danger, custom_id="gw_end_button")
    async def end_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host_id:
            return await interaction.response.send_message("Only the person who started the giveaway can end it.", ephemeral=True)

        await interaction.response.defer()
        giveaway_data = self.giveaway_cog.giveaways.pop(interaction.message.id, None)
        if giveaway_data:
            await self.giveaway_cog.end_giveaway(interaction.message, giveaway_data)
            self.giveaway_cog.save_giveaways() # Save after ending

# --- UI Components: View for voting in polls ---
class PollVoteView(discord.ui.View):
    def __init__(self, poll_cog: 'GiveawayCog', poll_id: int, host_id: int):
        super().__init__(timeout=None)
        self.poll_cog = poll_cog
        self.poll_id = poll_id
        self.host_id = host_id
        
        poll_data = self.poll_cog.polls.get(self.poll_id)
        if poll_data:
            for i, option in enumerate(poll_data["options"]):
                button = discord.ui.Button(label=option, style=discord.ButtonStyle.secondary, custom_id=f"poll_{poll_id}_opt_{i}", row=0)
                button.callback = self.create_vote_callback(i)
                self.add_item(button)
            
            end_button = discord.ui.Button(label="End Poll", style=discord.ButtonStyle.danger, custom_id=f"poll_{poll_id}_end", row=1)
            end_button.callback = self.end_poll_callback
            self.add_item(end_button)

    def create_vote_callback(self, option_index: int):
        async def callback(interaction: discord.Interaction):
            poll_id_from_custom_id = int(interaction.data["custom_id"].split("_")[1])
            await self.poll_cog.handle_vote(interaction, poll_id_from_custom_id, option_index)
        return callback
        
    async def end_poll_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.host_id:
            return await interaction.response.send_message("Only the person who started the poll can end it.", ephemeral=True)
        
        await interaction.response.defer()
        poll_data = self.poll_cog.polls.pop(self.poll_id, None)
        if poll_data:
            await self.poll_cog.end_poll(interaction.message, poll_data)
            self.poll_cog.save_polls() # Save after ending

# --- Main Cog ---
class GiveawayCog(commands.Cog, name="Events"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.giveaways: Dict[int, Dict] = {}
        self.polls: Dict[int, Dict] = {}
        self.ended_giveaways: Dict[int, Dict] = {}
        self.giveaway_file = 'giveaways.json'
        self.poll_file = 'polls.json'
        self.ended_giveaway_file = 'ended_giveaways.json'
        self.load_data()

    def load_data(self):
        try:
            with open(self.giveaway_file, 'r') as f:
                raw_giveaways = json.load(f)
                self.giveaways = {
                    int(k): {
                        **v,
                        "end_time": datetime.datetime.fromtimestamp(v["end_time"], tz=datetime.timezone.utc)
                    } for k, v in raw_giveaways.items()
                }
        except FileNotFoundError:
            self.giveaways = {}
        except json.JSONDecodeError:
            print(f"Error decoding {self.giveaway_file}. Starting with empty giveaways.")
            self.giveaways = {}

        try:
            with open(self.poll_file, 'r') as f:
                raw_polls = json.load(f)
                self.polls = {
                    int(k): {
                        **v,
                        "end_time": datetime.datetime.fromtimestamp(v["end_time"], tz=datetime.timezone.utc)
                    } for k, v in raw_polls.items()
                }
        except FileNotFoundError:
            self.polls = {}
        except json.JSONDecodeError:
            print(f"Error decoding {self.poll_file}. Starting with empty polls.")
            self.polls = {}

        try:
            with open(self.ended_giveaway_file, 'r') as f:
                raw_ended_giveaways = json.load(f)
                self.ended_giveaways = {
                    int(k): {
                        **v,
                        "ended_at": datetime.datetime.fromtimestamp(v["ended_at"], tz=datetime.timezone.utc)
                    } for k, v in raw_ended_giveaways.items()
                }
        except FileNotFoundError:
            self.ended_giveaways = {}
        except json.JSONDecodeError:
            print(f"Error decoding {self.ended_giveaway_file}. Starting with empty ended giveaways.")
            self.ended_giveaways = {}


    def save_giveaways(self):
        with open(self.giveaway_file, 'w') as f:
            # Convert datetime objects to timestamps for JSON serialization
            serializable_giveaways = {
                k: {**v, "end_time": v["end_time"].timestamp()}
                for k, v in self.giveaways.items()
            }
            json.dump(serializable_giveaways, f, indent=4)

    def save_polls(self):
        with open(self.poll_file, 'w') as f:
            # Convert datetime objects to timestamps for JSON serialization
            serializable_polls = {
                k: {**v, "end_time": v["end_time"].timestamp()}
                for k, v in self.polls.items()
            }
            json.dump(serializable_polls, f, indent=4)

    def save_ended_giveaways(self):
        with open(self.ended_giveaway_file, 'w') as f:
            serializable_ended_giveaways = {
                k: {**v, "ended_at": v["ended_at"].timestamp()}
                for k, v in self.ended_giveaways.items()
            }
            json.dump(serializable_ended_giveaways, f, indent=4)

    @commands.Cog.listener()
    async def on_ready(self):
        print("GiveawayCog is ready, ensuring views are persistent.")
        # Re-add persistent views for active giveaways and polls
        for giveaway_id, data in self.giveaways.items():
            self.bot.add_view(GiveawayEnterView(self, data.get("host_id", 0))) # Pass host_id
        for poll_id, data in self.polls.items():
            self.bot.add_view(PollVoteView(self, poll_id, data.get("host_id", 0))) # Pass host_id

        if not self.check_expirations.is_running():
            self.check_expirations.start()

    def cog_unload(self):
        self.check_expirations.cancel()
        self.save_giveaways()
        self.save_polls()
        self.save_ended_giveaways()

    @tasks.loop(seconds=15)
    async def check_expirations(self):
        now = discord.utils.utcnow()
        reroll_period = datetime.timedelta(hours=24)

        # Check for expired giveaways
        for giveaway_id, data in list(self.giveaways.items()):
            if now >= data["end_time"]:
                channel = self.bot.get_channel(data["channel_id"])
                giveaway_data = self.giveaways.pop(giveaway_id)
                self.save_giveaways() # Save changes immediately
                if channel:
                    try:
                        message = await channel.fetch_message(giveaway_id)
                        await self.end_giveaway(message, giveaway_data)
                    except discord.NotFound:
                        pass
                
                giveaway_data["ended_at"] = now
                self.ended_giveaways[giveaway_id] = giveaway_data
                self.save_ended_giveaways() # Save ended giveaways

        # Clear old ended giveaways from reroll list
        for giveaway_id, data in list(self.ended_giveaways.items()):
            if now > data["ended_at"] + reroll_period:
                del self.ended_giveaways[giveaway_id]
                self.save_ended_giveaways() # Save changes immediately

        # Check for expired polls
        for poll_id, data in list(self.polls.items()):
            if now >= data["end_time"]:
                poll_data = self.polls.pop(poll_id)
                self.save_polls() # Save changes immediately
                channel = self.bot.get_channel(poll_data["channel_id"])
                if channel:
                    try:
                        message = await channel.fetch_message(poll_id)
                        await self.end_poll(message, poll_data)
                    except discord.NotFound:
                        pass

    async def end_giveaway(self, message: discord.Message, data: dict):
        winners = random.sample(data["entrants"], k=min(data["winners_count"], len(data["entrants"])))
        winner_mentions = [f"<@{w}>" for w in winners]
        result_text = f"Congratulations {', '.join(winner_mentions)}!" if winners else "No one entered the giveaway."
        
        embed = message.embeds[0]
        embed.title = "🎉 Giveaway Ended! 🎉"
        embed.description = f"**Prize:** {data['prize']}\n**Winner(s):** {', '.join(winner_mentions) if winners else 'None'}"
        embed.color = discord.Color.green()
        
        await message.edit(embed=embed, view=None)
        if winners:
            await message.channel.send(f"{result_text} You won **{data['prize']}**!")

    async def end_poll(self, message: discord.Message, data: dict):
        total_votes = sum(data["votes"])
        if total_votes == 0:
            winner_text, max_votes = "No votes were cast.", 0
        else:
            max_votes = max(data["votes"])
            winners = [f"**{data['options'][i]}**" for i, v in enumerate(data["votes"]) if v == max_votes]
            winner_text = ", ".join(winners)
            
        embed = discord.Embed(
            title="📊 Poll Ended!",
            description=f"**Question:** {data['question']}\n\n**Winning Option(s):** {winner_text} ({max_votes} votes)",
            color=discord.Color.green()
        ).set_footer(text=f"Total Votes: {total_votes}")
        await message.edit(embed=embed, view=None)
    
    async def handle_vote(self, interaction: discord.Interaction, poll_id: int, option_index: int):
        poll = self.polls.get(poll_id)
        if not poll:
            return await interaction.response.send_message("This poll has ended or is invalid.", ephemeral=True)
        
        required_roles = poll.get("required_roles", [])
        if required_roles and not any(role.id in required_roles for role in interaction.user.roles):
            return await interaction.response.send_message("You don't have the required role(s) to vote.", ephemeral=True)

        user_id = interaction.user.id
        if user_id in poll["voters"]:
            previous_vote = poll["voters"][user_id]
            if previous_vote == option_index:
                poll["votes"][previous_vote] -= 1
                del poll["voters"][user_id]
                await interaction.response.send_message("Your vote has been removed.", ephemeral=True)
            else:
                poll["votes"][previous_vote] -= 1
                poll["votes"][option_index] += 1
                poll["voters"][user_id] = option_index
                await interaction.response.send_message(f"You changed your vote to **{poll['options'][option_index]}**.", ephemeral=True)
        elif len(poll["voters"]) < poll["max_participants"]:
            poll["voters"][user_id] = option_index
            poll["votes"][option_index] += 1
            await interaction.response.send_message(f"You voted for **{poll['options'][option_index]}**.", ephemeral=True)
        else:
            return await interaction.response.send_message("This poll has reached its maximum number of participants.", ephemeral=True)
        
        await self.update_poll_message(interaction.message, poll)
        self.save_polls() # Save after vote change

    async def update_poll_message(self, message: discord.Message, poll_data: dict):
        total_votes = sum(poll_data["votes"])
        description = f"**Question:** {poll_data['question']}\n\n"
        for i, option in enumerate(poll_data["options"]):
            votes = poll_data["votes"][i]
            percentage = (votes / total_votes * 100) if total_votes > 0 else 0
            bar = "█" * int(percentage / 10) + "░" * (10 - int(percentage / 10))
            description += f"**{option}**: {votes} votes ({percentage:.1f}%)\n`{bar}`\n"
        description += f"\n**Total Votes:** {total_votes}\n**Ends:** <t:{int(poll_data['end_time'].timestamp())}:R>"
        
        embed = discord.Embed(title="📊 Active Poll", description=description, color=discord.Color.blue())
        await message.edit(embed=embed)

    giveaway_group = app_commands.Group(name="giveaway", description="Commands for managing giveaways.")
    poll_group = app_commands.Group(name="poll", description="Commands for managing polls.")

    @giveaway_group.command(name="setup", description="Interactively set up a new giveaway.")
    async def giveaway_setup(self, interaction: discord.Interaction):
        view = GiveawaySetupView(author=interaction.user, is_poll=False)
        await interaction.response.send_message(embed=view.create_embed(), view=view, ephemeral=True)
        await view.wait()

        if not view.finished:
            return
        data = view.responses
        end_time = discord.utils.utcnow() + datetime.timedelta(seconds=data["Duration"])
        
        embed = discord.Embed(
            title=f"🎉 {data['Item']}",
            description=(
                f"Click the button to enter!\n"
                f"**Winners:** {data['Winners/Options']}\n"
                f"**Ends:** <t:{int(end_time.timestamp())}:R>\n"
                f"**Required Roles:** {', '.join([r.mention for r in data['Required Roles']]) if data['Required Roles'] else 'None'}"
            ), color=discord.Color.magenta()
        ).set_footer(text=f"Hosted by {interaction.user.display_name}")

        try:
            msg = await interaction.channel.send(embed=embed, view=GiveawayEnterView(self, interaction.user.id))
            self.giveaways[msg.id] = {
                "channel_id": interaction.channel.id, "prize": data["Item"],
                "winners_count": data["Winners/Options"], "end_time": end_time,
                "max_applicants": data["Max Participants"], "required_roles": [r.id for r in data['Required Roles']],
                "entrants": [], "host_id": interaction.user.id
            }
            self.save_giveaways() # Save new giveaway
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to send messages in this channel.", ephemeral=True)

    @giveaway_group.command(name="reroll", description="Reroll a winner for a recently ended giveaway.")
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            giveaway_id = int(message_id)
            ended_giveaway = self.ended_giveaways.get(giveaway_id)

            if not ended_giveaway:
                return await interaction.followup.send("This giveaway is either still active, too old to be rerolled, or the ID is invalid.", ephemeral=True)
            
            entrants = ended_giveaway["entrants"]
            if not entrants:
                return await interaction.followup.send("There were no entrants in this giveaway to reroll from.", ephemeral=True)
            
            new_winner_id = random.choice(entrants)
            new_winner = self.bot.get_user(new_winner_id)
            if not new_winner: # Fetch if not in cache
                try:
                    new_winner = await self.bot.fetch_user(new_winner_id)
                except discord.NotFound:
                    new_winner = None
            
            winner_mention = new_winner.mention if new_winner else f"User ID: {new_winner_id}"
            
            await interaction.followup.send(f"Reroll complete! The new winner is {winner_mention}!", ephemeral=True)
            
            channel = self.bot.get_channel(ended_giveaway["channel_id"])
            if channel:
                await channel.send(f"A winner for the **{ended_giveaway['prize']}** giveaway has been rerolled! Congratulations {winner_mention}!")

        except ValueError:
            await interaction.followup.send("Invalid Message ID format. Please provide a valid number.", ephemeral=True)

    @poll_group.command(name="setup", description="Interactively set up a new poll.")
    async def poll_setup(self, interaction: discord.Interaction):
        view = GiveawaySetupView(author=interaction.user, is_poll=True)
        await interaction.response.send_message(embed=view.create_embed(), view=view, ephemeral=True)
        await view.wait()

        if not view.finished:
            return
        data = view.responses
        end_time = discord.utils.utcnow() + datetime.timedelta(seconds=data["Duration"])
        
        options = data["Winners/Options"]
        description = f"**Question:** {data['Item']}\n\n" + "\n".join(f"**{opt}**: 0 votes (0.0%)\n`{'░'*10}`\n" for opt in options)
        embed = discord.Embed(title="📊 New Poll!", description=description, color=discord.Color.dark_blue())

        try:
            msg = await interaction.channel.send(content="Loading poll...", embed=embed)
            poll_data = {
                "channel_id": interaction.channel.id, "question": data["Item"],
                "options": options, "end_time": end_time, "host_id": interaction.user.id,
                "max_participants": data["Max Participants"], "required_roles": [r.id for r in data["Required Roles"]],
                "voters": {}, "votes": [0] * len(options)
            }
            self.polls[msg.id] = poll_data
            self.save_polls() # Save new poll
            await msg.edit(content=None, view=PollVoteView(self, msg.id, interaction.user.id))
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to send messages in this channel.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))