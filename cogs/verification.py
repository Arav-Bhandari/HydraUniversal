import discord
from discord.ext import commands
from discord import app_commands
import json
import random
import string
import asyncio
from datetime import datetime, timedelta
import os

class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view

    @discord.ui.button(
        label="🛡️ Verify Account", 
        style=discord.ButtonStyle.primary,
        custom_id="verify_button",
        emoji="🛡️"
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle verification button clicks"""
        # Get the cog instance
        cog = interaction.client.get_cog('VerificationCog')
        if not cog:
            await interaction.response.send_message("❌ Verification system not available.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        if guild_id not in cog.config:
            await interaction.response.send_message("❌ Verification system is not configured.", ephemeral=True)
            return

        config = cog.config[guild_id]

        # Check if user already has verified role
        verified_role = interaction.guild.get_role(config.get('verified_role'))
        if verified_role and verified_role in interaction.user.roles:
            embed = discord.Embed(
                title="✅ Already Verified",
                description="Your account is already verified! You have full access to the server.",
                color=0x57F287
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Send acknowledgment
        embed = discord.Embed(
            title="🔄 Verification Started",
            description="I've sent you a direct message with your verification challenge. Please check your DMs!",
            color=0x5865F2
        )
        embed.add_field(
            name="📱 Can't find the DM?",
            value="Make sure you have DMs enabled from server members, or use `/verify` as an alternative.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Start verification process
        await cog.start_verification_process(interaction.user, interaction.guild, config)

class VerificationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = "verification_config.json"
        self.pending_verifications = {}
        self.load_config()

    def load_config(self):
        """Load verification configuration from JSON file"""
        try:
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            self.config = {}

    def save_config(self):
        """Save verification configuration to JSON file"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=4)

    def generate_math_captcha(self):
        """Generate a simple math captcha"""
        num1 = random.randint(1, 20)
        num2 = random.randint(1, 20)
        operation = random.choice(['+', '-', '*'])

        if operation == '+':
            answer = num1 + num2
        elif operation == '-':
            answer = num1 - num2
        else:  # multiplication
            answer = num1 * num2

        question = f"{num1} {operation} {num2} = ?"
        return question, str(answer)

    def generate_text_captcha(self):
        """Generate a random text captcha"""
        length = random.randint(5, 8)
        # Mix of letters and numbers, avoiding confusing characters
        chars = string.ascii_uppercase + string.digits
        chars = chars.replace('0', '').replace('O', '').replace('1', '').replace('I', '').replace('L', '')

        captcha_text = ''.join(random.choice(chars) for _ in range(length))
        return f"Type this code: **{captcha_text}**", captcha_text

    verification_group = app_commands.Group(name="verification", description="Verification system commands")

    @verification_group.command(name="setup", description="Interactive setup for the verification system")
    @app_commands.describe()
    @app_commands.default_permissions(manage_guild=True)
    async def setup_verification(self, interaction: discord.Interaction):
        """Interactive setup for verification system"""
        guild_id = str(interaction.guild.id)

        embed = discord.Embed(
            title="🛠️ Verification Setup",
            description="Let's set up the verification system step by step!",
            color=0x2ecc71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            # Step 1: Verification Channel
            embed = discord.Embed(
                title="Step 1: Verification Channel",
                description="Please mention the channel where verification messages will be sent (e.g., #verification)",
                color=0x3498db
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            if msg.channel_mentions:
                verification_channel = msg.channel_mentions[0]
            else:
                await interaction.followup.send("❌ No valid channel mentioned. Setup cancelled.", ephemeral=True)
                return

            # Step 2: Captcha Type
            embed = discord.Embed(
                title="Step 2: Captcha Type",
                description="Choose captcha type: `math` or `text`",
                color=0x3498db
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            captcha_type = msg.content.lower()
            if captcha_type not in ['math', 'text']:
                await interaction.followup.send("❌ Invalid captcha type. Setup cancelled.", ephemeral=True)
                return

            # Step 3: Verified Role
            embed = discord.Embed(
                title="Step 3: Verified Role",
                description="Please mention the role that will be given to verified users (e.g., @Verified)",
                color=0x3498db
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            if msg.role_mentions:
                verified_role = msg.role_mentions[0]
            else:
                await interaction.followup.send("❌ No valid role mentioned. Setup cancelled.", ephemeral=True)
                return

            # Step 4: Unverified Role
            embed = discord.Embed(
                title="Step 4: Unverified Role",
                description="Please mention the role that will be removed after verification (e.g., @Unverified)",
                color=0x3498db
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            msg = await self.bot.wait_for('message', check=check, timeout=60.0)
            if msg.role_mentions:
                unverified_role = msg.role_mentions[0]
            else:
                await interaction.followup.send("❌ No valid role mentioned. Setup cancelled.", ephemeral=True)
                return

            # Save configuration
            self.config[guild_id] = {
                'verification_channel': verification_channel.id,
                'captcha_type': captcha_type,
                'verified_role': verified_role.id,
                'unverified_role': unverified_role.id,
                'enabled': True
            }
            self.save_config()

            # Send confirmation
            embed = discord.Embed(
                title="✅ Verification Setup Complete!",
                color=0x2ecc71
            )
            embed.add_field(name="Channel", value=verification_channel.mention, inline=True)
            embed.add_field(name="Captcha Type", value=captcha_type.title(), inline=True)
            embed.add_field(name="Verified Role", value=verified_role.mention, inline=True)
            embed.add_field(name="Unverified Role", value=unverified_role.mention, inline=True)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="❌ Setup Timeout",
                description="Setup cancelled due to timeout. Please try again.",
                color=0xe74c3c
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @verification_group.command(name="channel", description="Set the verification channel")
    @app_commands.describe(channel="The channel where verification messages will be sent")
    @app_commands.default_permissions(manage_guild=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the verification channel"""
        guild_id = str(interaction.guild.id)

        if guild_id not in self.config:
            self.config[guild_id] = {}

        self.config[guild_id]['verification_channel'] = channel.id
        self.save_config()

        embed = discord.Embed(
            title="✅ Verification Channel Set",
            description=f"Verification channel set to {channel.mention}",
            color=0x2ecc71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @verification_group.command(name="captcha", description="Set the captcha type")
    @app_commands.describe(captcha_type="The type of captcha to use")
    @app_commands.choices(captcha_type=[
        discord.app_commands.Choice(name="Math (Simple arithmetic)", value="math"),
        discord.app_commands.Choice(name="Text (Random code)", value="text")
    ])
    @app_commands.default_permissions(manage_guild=True)
    async def set_captcha(self, interaction: discord.Interaction, captcha_type: discord.app_commands.Choice[str]):
        """Set the captcha type"""
        guild_id = str(interaction.guild.id)

        if guild_id not in self.config:
            self.config[guild_id] = {}

        self.config[guild_id]['captcha_type'] = captcha_type.value
        self.save_config()

        embed = discord.Embed(
            title="✅ Captcha Type Set",
            description=f"Captcha type set to **{captcha_type.name}**",
            color=0x2ecc71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @verification_group.command(name="roles", description="Set the verified and unverified roles")
    @app_commands.describe(
        verified_role="Role given to users after successful verification",
        unverified_role="Role removed from users after verification"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def set_roles(self, interaction: discord.Interaction, verified_role: discord.Role, unverified_role: discord.Role):
        """Set the verified and unverified roles"""
        guild_id = str(interaction.guild.id)

        if guild_id not in self.config:
            self.config[guild_id] = {}

        self.config[guild_id]['verified_role'] = verified_role.id
        self.config[guild_id]['unverified_role'] = unverified_role.id
        self.save_config()

        embed = discord.Embed(
            title="✅ Roles Set",
            color=0x2ecc71
        )
        embed.add_field(name="Verified Role", value=verified_role.mention, inline=True)
        embed.add_field(name="Unverified Role", value=unverified_role.mention, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @verification_group.command(name="status", description="View current verification configuration")
    @app_commands.default_permissions(manage_guild=True)
    async def verification_status(self, interaction: discord.Interaction):
        """View current verification configuration"""
        guild_id = str(interaction.guild.id)

        if guild_id not in self.config:
            embed = discord.Embed(
                title="❌ Not Configured",
                description="Verification system is not set up for this server.",
                color=0xe74c3c
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        config = self.config[guild_id]
        embed = discord.Embed(
            title="🔒 Verification Status",
            color=0x3498db
        )

        # Get channel
        channel = self.bot.get_channel(config.get('verification_channel'))
        embed.add_field(
            name="Channel", 
            value=channel.mention if channel else "Not set", 
            inline=True
        )

        # Get captcha type
        captcha_display = {
            'math': 'Math (Simple arithmetic)',
            'text': 'Text (Random code)'
        }
        captcha_type = config.get('captcha_type', 'Not set')
        embed.add_field(
            name="Captcha Type", 
            value=captcha_display.get(captcha_type, captcha_type.title()), 
            inline=True
        )

        # Get roles
        verified_role = interaction.guild.get_role(config.get('verified_role'))
        unverified_role = interaction.guild.get_role(config.get('unverified_role'))

        embed.add_field(
            name="Verified Role", 
            value=verified_role.mention if verified_role else "Not set", 
            inline=True
        )
        embed.add_field(
            name="Unverified Role", 
            value=unverified_role.mention if unverified_role else "Not set", 
            inline=True
        )

        embed.add_field(
            name="Status", 
            value="✅ Enabled" if config.get('enabled', False) else "❌ Disabled", 
            inline=True
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @verification_group.command(name="reset", description="Reset verification configuration")
    @app_commands.default_permissions(manage_guild=True)
    async def reset_verification(self, interaction: discord.Interaction):
        """Reset verification configuration"""
        guild_id = str(interaction.guild.id)

        if guild_id in self.config:
            del self.config[guild_id]
            self.save_config()

        embed = discord.Embed(
            title="✅ Configuration Reset",
            description="Verification configuration has been reset.",
            color=0x2ecc71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="startverify", description="Send the verification message to the verification channel")
    @app_commands.default_permissions(manage_guild=True)
    async def start_verify(self, interaction: discord.Interaction):
        """Send the verification message to the verification channel"""
        guild_id = str(interaction.guild.id)

        if guild_id not in self.config:
            embed = discord.Embed(
                title="⚠️ Configuration Required",
                description="The verification system needs to be configured first.\n\nUse `/verification setup` to get started.",
                color=0xff6b6b
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        config = self.config[guild_id]
        channel = self.bot.get_channel(config.get('verification_channel'))

        if not channel:
            embed = discord.Embed(
                title="❌ Channel Not Found",
                description="The configured verification channel could not be found.\n\nPlease reconfigure using `/verification channel`.",
                color=0xff6b6b
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Professional verification embed
        embed = discord.Embed(
            title="🛡️ Account Verification Required",
            description="",
            color=0x5865F2  # Discord blurple
        )

        embed.add_field(
            name="📋 **Verification Process**",
            value=(
                "To access all server features and channels, please complete our quick verification process.\n\n"
                "• Click the **Verify** button below\n"
                "• Complete the simple challenge sent to your DMs\n"
                "• Gain full server access instantly"
            ),
            inline=False
        )

        embed.add_field(
            name="🔐 **Why We Verify**",
            value=(
                "This process helps us:\n"
                "• Prevent spam and bot accounts\n"
                "• Maintain a safe community environment\n"
                "• Ensure all members are genuine users"
            ),
            inline=True
        )

        embed.add_field(
            name="⚡ **Quick & Easy**",
            value=(
                "The verification takes less than 30 seconds to complete and only needs to be done once."
            ),
            inline=True
        )

        embed.set_footer(
            text=f"Verification • {interaction.guild.name}",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1234567890123456789.png")  # You can replace with a shield emoji URL

        # Create a view with a button
        view = VerificationView()
        message = await channel.send(embed=embed, view=view)

        # Success response
        success_embed = discord.Embed(
            title="✅ Verification System Deployed",
            description=f"Professional verification message has been sent to {channel.mention}",
            color=0x57F287
        )
        await interaction.response.send_message(embed=success_embed, ephemeral=True)

    @app_commands.command(name="verify", description="Manual verification command for users")
    async def manual_verify(self, interaction: discord.Interaction):
        """Manual verification command for users who can't use the reaction"""
        guild_id = str(interaction.guild.id)

        if guild_id not in self.config:
            await interaction.response.send_message("❌ Verification system is not set up on this server.", ephemeral=True)
            return

        config = self.config[guild_id]

        # Check if user already has verified role
        verified_role = interaction.guild.get_role(config.get('verified_role'))
        if verified_role and verified_role in interaction.user.roles:
            await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
            return

        await interaction.response.send_message("🔍 Starting verification process... Check your DMs!", ephemeral=True)

        # Start verification process
        await self.start_verification_process(interaction.user, interaction.guild, config)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        """Handle verification reactions"""
        if user.bot:
            return

        # Check if this is a verification reaction
        if str(reaction.emoji) != "✅":
            return

        guild_id = str(reaction.message.guild.id)
        if guild_id not in self.config:
            return

        config = self.config[guild_id]

        # Check if reaction is in verification channel
        if reaction.message.channel.id != config.get('verification_channel'):
            return

        # Check if user already has verified role
        verified_role = reaction.message.guild.get_role(config.get('verified_role'))
        if verified_role and verified_role in user.roles:
            return

        # Start verification process
        await self.start_verification_process(user, reaction.message.guild, config)

    async def start_verification_process(self, user, guild, config):
        """Start the verification process for a user"""
        # Check if user is already in verification process
        if user.id in self.pending_verifications:
            try:
                embed = discord.Embed(
                    title="⚠️ Verification In Progress",
                    description="You already have a pending verification challenge. Please complete your current verification first.",
                    color=0xFEE75C
                )
                embed.add_field(
                    name="Need help?",
                    value="If you're stuck, wait 5 minutes for it to expire and try again.",
                    inline=False
                )
                await user.send(embed=embed)
            except discord.Forbidden:
                pass
            return

        # Generate captcha
        captcha_type = config.get('captcha_type', 'math')

        if captcha_type == 'math':
            question, answer = self.generate_math_captcha()
            captcha_icon = "🔢"
        else:
            question, answer = self.generate_text_captcha()
            captcha_icon = "📝"

        # Create professional verification embed
        embed = discord.Embed(
            title=f"{captcha_icon} Account Verification Challenge",
            description="",
            color=0x5865F2
        )

        embed.add_field(
            name="🎯 **Your Challenge**",
            value=f"```{question}```",
            inline=False
        )

        embed.add_field(
            name="📝 **Instructions**",
            value=(
                "• Type your answer in this DM conversation\n"
                "• You have **5 minutes** to complete this challenge\n"
                "• Answer is case-insensitive for text challenges\n"
                "• Send only the answer (no extra text needed)"
            ),
            inline=False
        )

        embed.add_field(
            name="⏱️ **Time Limit**",
            value="This verification expires in **5 minutes**",
            inline=True
        )

        embed.add_field(
            name="🔒 **Security**",
            value="This helps protect the server from automated accounts",
            inline=True
        )

        embed.set_footer(
            text=f"Verification for {guild.name} • Expires in 5 minutes",
            icon_url=guild.icon.url if guild.icon else None
        )
        embed.set_author(
            name="Security Verification",
            icon_url="https://cdn.discordapp.com/emojis/853569966740938782.png"  # Shield emoji
        )

        try:
            # Send DM to user
            dm_message = await user.send(embed=embed)

            # Store pending verification
            self.pending_verifications[user.id] = {
                'answer': answer,
                'guild_id': guild.id,
                'expires': datetime.now() + timedelta(minutes=5),
                'challenge_type': captcha_type
            }

            # Wait for response
            def check(m):
                return (m.author == user and 
                       isinstance(m.channel, discord.DMChannel) and
                       user.id in self.pending_verifications)

            try:
                response = await self.bot.wait_for('message', check=check, timeout=300.0)
                await self.process_verification_response(user, response, guild, config)

            except asyncio.TimeoutError:
                # Remove from pending verifications
                if user.id in self.pending_verifications:
                    del self.pending_verifications[user.id]

                timeout_embed = discord.Embed(
                    title="⏰ Verification Expired",
                    description="Your verification challenge has expired due to timeout.",
                    color=0xED4245
                )
                timeout_embed.add_field(
                    name="What's next?",
                    value="You can start a new verification anytime by clicking the verify button again or using `/verify`.",
                    inline=False
                )
                timeout_embed.set_footer(text="No worries - you can try again anytime!")
                await user.send(embed=timeout_embed)

        except discord.Forbidden:
            # Can't send DM to user - create a more helpful error message
            verification_channel = guild.get_channel(config.get('verification_channel'))
            if verification_channel:
                embed = discord.Embed(
                    title="📱 Direct Message Required",
                    description=f"{user.mention}, I need to send you a verification challenge, but your DMs are disabled.",
                    color=0xFEE75C
                )
                embed.add_field(
                    name="🔧 How to fix this:",
                    value=(
                        "1. Go to **User Settings** ⚙️\n"
                        "2. Click **Privacy & Safety**\n"
                        "3. Enable **Allow direct messages from server members**\n"
                        "4. Try verification again"
                    ),
                    inline=False
                )
                embed.add_field(
                    name="🔄 Alternative:",
                    value="You can also use the `/verify` slash command directly.",
                    inline=False
                )
                embed.set_footer(text="This message will be deleted in 60 seconds")
                await verification_channel.send(embed=embed, delete_after=60)

    async def process_verification_response(self, user, message, guild, config):
        """Process the user's verification response"""
        if user.id not in self.pending_verifications:
            return

        verification_data = self.pending_verifications[user.id]

        # Check if verification has expired
        if datetime.now() > verification_data['expires']:
            del self.pending_verifications[user.id]

            embed = discord.Embed(
                title="⏰ Challenge Expired",
                description="Your verification challenge has timed out.",
                color=0xED4245
            )
            embed.add_field(
                name="No problem!",
                value="You can start a new verification anytime. Just click the verify button again.",
                inline=False
            )
            await user.send(embed=embed)
            return

        # Check answer
        user_answer = message.content.strip().lower()
        correct_answer = verification_data['answer'].lower()

        if user_answer == correct_answer:
            # Correct answer - verify user
            success = await self.verify_user(user, guild, config)

            # Remove from pending verifications
            del self.pending_verifications[user.id]

            if success:
                embed = discord.Embed(
                    title="🎉 Verification Successful!",
                    description=f"**Welcome to {guild.name}!**",
                    color=0x57F287
                )
                embed.add_field(
                    name="✅ Account Verified",
                    value="You now have full access to all server channels and features.",
                    inline=False
                )
                embed.add_field(
                    name="🎊 What's Next?",
                    value=(
                        "• Explore all the available channels\n"
                        "• Read the server rules and guidelines\n"
                        "• Introduce yourself to the community\n"
                        "• Have fun and be respectful!"
                    ),
                    inline=False
                )
                embed.set_footer(
                    text=f"Welcome to the community!",
                    icon_url=guild.icon.url if guild.icon else None
                )
                embed.set_thumbnail(url=user.display_avatar.url)
            else:
                embed = discord.Embed(
                    title="⚠️ Verification Issue",
                    description="Your answer was correct, but there was an issue updating your roles.",
                    color=0xFEE75C
                )
                embed.add_field(
                    name="What to do:",
                    value="Please contact a server moderator for assistance.",
                    inline=False
                )

            await user.send(embed=embed)

        else:
            # Wrong answer
            challenge_type = verification_data.get('challenge_type', 'unknown')

            embed = discord.Embed(
                title="❌ Incorrect Answer",
                description="That's not the correct answer to the challenge.",
                color=0xED4245
            )

            if challenge_type == 'math':
                embed.add_field(
                    name="💡 Tip for Math Challenges:",
                    value="Make sure to calculate carefully and enter only the number (no spaces or extra characters).",
                    inline=False
                )
            else:
                embed.add_field(
                    name="💡 Tip for Text Challenges:",
                    value="Copy the code exactly as shown, including correct capitalization.",
                    inline=False
                )

            embed.add_field(
                name="🔄 Try Again",
                value="You can start a new verification anytime by clicking the verify button or using `/verify`.",
                inline=False
            )
            embed.set_footer(text="Don't worry - you can try as many times as needed!")

            await user.send(embed=embed)

            # Remove from pending verifications
            del self.pending_verifications[user.id]

    async def verify_user(self, user, guild, config):
        """Verify a user by managing their roles"""
        member = guild.get_member(user.id)
        if not member:
            return False

        # Get roles
        verified_role = guild.get_role(config.get('verified_role'))
        unverified_role = guild.get_role(config.get('unverified_role'))

        try:
            # Add verified role
            if verified_role:
                await member.add_roles(verified_role, reason="✅ User successfully verified")

            # Remove unverified role
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason="✅ User successfully verified")

            return True

        except discord.Forbidden:
            print(f"❌ Missing permissions to manage roles for {member}")
            return False
        except discord.HTTPException as e:
            print(f"❌ Error managing roles: {e}")
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Auto-assign unverified role to new members"""
        guild_id = str(member.guild.id)

        if guild_id not in self.config:
            return

        config = self.config[guild_id]
        unverified_role = member.guild.get_role(config.get('unverified_role'))

        if unverified_role:
            try:
                await member.add_roles(unverified_role, reason="New member - pending verification")
            except discord.Forbidden:
                print(f"Missing permissions to add unverified role to {member}")

async def setup(bot):
    await bot.add_cog(VerificationCog(bot))