import discord
import json
import os
import time
import random
from discord import app_commands
from discord.ext import commands
import datetime
from typing import Optional, List

# Path for configuration file
CONFIG_PATH = 'securitysetup.json'

# Initialize config file
def init_config():
    default_config = {
        'message_log_channel': None,
        'honeypot_channels': [],
        'watchlist_channels': [],
        'red_flag_keywords': [],
        'raid_threshold': 5,
        'role_limits': {},
        'approved_bots': []
    }
    
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(default_config, f, indent=2)
    
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
        
    # Ensure all expected keys exist
    for key, value in default_config.items():
        if key not in config:
            config[key] = value
            
    return config

# Save config to file
def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

class SilverSecurityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = init_config()
        # Store user warnings in memory - could be moved to database for persistence
        self.warnings = {}  # Format: {guild_id: {user_id: [warning_count, reason_list]}}
        # Store user risk scores
        self.risk_scores = {}  # Format: {guild_id: {user_id: score}}
        # Channel lockdown status
        self.locked_channels = set()  # Set of channel IDs

    # Message delete event
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        # Don't log bot messages
        if message.author.bot:
            return
        
        # Check if a log channel is set
        if not self.config.get('message_log_channel'):
            return
        
        # Get the log channel
        log_channel = self.bot.get_channel(int(self.config['message_log_channel']))
        if not log_channel:
            return
            
        # Create embed for deleted message
        embed = discord.Embed(
            title="Message Deleted",
            description=f"**Message from {message.author.mention} was deleted in {message.channel.mention}**",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        
        # Add message content
        if message.content:
            # Truncate if too long
            content = message.content
            if len(content) > 1024:
                content = content[:1021] + "..."
            embed.add_field(name="Content", value=content, inline=False)
        
        # Add attachments if any
        if message.attachments:
            attachment_list = "\n".join([f"[{a.filename}]({a.url})" for a in message.attachments])
            if attachment_list:
                embed.add_field(name="Attachments", value=attachment_list, inline=False)
        
        # Add author information with timestamp
        embed.set_footer(text=f"Author ID: {message.author.id} | Message ID: {message.id}")
        
        await log_channel.send(embed=embed)

    # Command to set message log channel
    @app_commands.command(name="message-log", description="Set the channel for deleted message logs")
    @app_commands.checks.has_permissions(administrator=True)
    async def message_log(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if channel:
            self.config['message_log_channel'] = channel.id
            save_config(self.config)
            await interaction.response.send_message(f"Message logging channel set to {channel.mention}", ephemeral=True)
        else:
            # If no channel is provided, display the current setting
            if self.config.get('message_log_channel'):
                current_channel = self.bot.get_channel(int(self.config['message_log_channel']))
                channel_mention = current_channel.mention if current_channel else "Unknown channel"
                await interaction.response.send_message(f"Current message logging channel: {channel_mention}", ephemeral=True)
            else:
                await interaction.response.send_message("No message logging channel is set. Provide a channel to set one.", ephemeral=True)

    # Clear message log channel
    @app_commands.command(name="clear-message-log", description="Clear the message log channel setting")
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_message_log(self, interaction: discord.Interaction):
        self.config['message_log_channel'] = None
        save_config(self.config)
        await interaction.response.send_message("Message logging has been disabled", ephemeral=True)
        
    # Ping command to check if bot is online
    @app_commands.command(name="ping", description="Check if the bot is online")
    async def ping(self, interaction: discord.Interaction):
        start_time = time.time()
        await interaction.response.send_message("Pinging...")
        end_time = time.time()
        
        latency = round((end_time - start_time) * 1000)
        api_latency = round(self.bot.latency * 1000)
        
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Bot latency: {latency}ms\nAPI latency: {api_latency}ms",
            color=discord.Color.green()
        )
        await interaction.edit_original_response(content=None, embed=embed)
    
    # Warning system commands
    @app_commands.command(name="warn", description="Warn a user")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        guild_id = str(interaction.guild_id)
        user_id = str(user.id)
        
        # Initialize warning structure if needed
        if guild_id not in self.warnings:
            self.warnings[guild_id] = {}
        
        if user_id not in self.warnings[guild_id]:
            self.warnings[guild_id][user_id] = [0, []]
        
        # Add warning
        self.warnings[guild_id][user_id][0] += 1
        self.warnings[guild_id][user_id][1].append(reason)
        
        # Update risk score
        self._update_risk_score(guild_id, user_id, 2)  # Add 2 points to risk score
        
        # Create embed
        embed = discord.Embed(
            title="User Warned",
            description=f"{user.mention} has been warned.",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Warning Count", value=self.warnings[guild_id][user_id][0], inline=False)
        embed.set_footer(text=f"Warned by {interaction.user}")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="unwarn", description="Remove a warning from a user")
    @app_commands.checks.has_permissions(kick_members=True)
    async def unwarn(self, interaction: discord.Interaction, user: discord.Member):
        guild_id = str(interaction.guild_id)
        user_id = str(user.id)
        
        if guild_id in self.warnings and user_id in self.warnings[guild_id] and self.warnings[guild_id][user_id][0] > 0:
            self.warnings[guild_id][user_id][0] -= 1
            self.warnings[guild_id][user_id][1].pop() if self.warnings[guild_id][user_id][1] else None
            
            # Update risk score
            self._update_risk_score(guild_id, user_id, -1)  # Remove 1 point from risk score
            
            await interaction.response.send_message(f"Removed a warning from {user.mention}. They now have {self.warnings[guild_id][user_id][0]} warnings.")
        else:
            await interaction.response.send_message(f"{user.mention} has no warnings to remove.", ephemeral=True)
    
    @app_commands.command(name="warnings", description="Check warnings for a user")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warnings(self, interaction: discord.Interaction, user: discord.Member):
        guild_id = str(interaction.guild_id)
        user_id = str(user.id)
        
        if guild_id in self.warnings and user_id in self.warnings[guild_id] and self.warnings[guild_id][user_id][0] > 0:
            embed = discord.Embed(
                title=f"Warnings for {user.display_name}",
                color=discord.Color.orange(),
                timestamp=datetime.datetime.now()
            )
            
            warning_count = self.warnings[guild_id][user_id][0]
            reasons = self.warnings[guild_id][user_id][1]
            
            embed.add_field(name="Warning Count", value=warning_count, inline=False)
            
            for i, reason in enumerate(reasons, 1):
                embed.add_field(name=f"Warning {i}", value=reason, inline=False)
                
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(f"{user.mention} has no warnings.", ephemeral=True)
    
    # Honeypot trap channels
    @app_commands.command(name="honeypot", description="Set a channel as a honeypot trap")
    @app_commands.checks.has_permissions(administrator=True)
    async def honeypot(self, interaction: discord.Interaction, channel: discord.TextChannel):
        channel_id = channel.id
        
        if channel_id not in self.config['honeypot_channels']:
            self.config['honeypot_channels'].append(channel_id)
            save_config(self.config)
            await interaction.response.send_message(f"{channel.mention} has been set as a honeypot trap channel.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{channel.mention} is already a honeypot trap channel.", ephemeral=True)
    
    @app_commands.command(name="unhoneypot", description="Remove a channel from honeypot traps")
    @app_commands.checks.has_permissions(administrator=True)
    async def unhoneypot(self, interaction: discord.Interaction, channel: discord.TextChannel):
        channel_id = channel.id
        
        if channel_id in self.config['honeypot_channels']:
            self.config['honeypot_channels'].remove(channel_id)
            save_config(self.config)
            await interaction.response.send_message(f"{channel.mention} is no longer a honeypot trap channel.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{channel.mention} is not a honeypot trap channel.", ephemeral=True)
    
    # Risk score system
    def _update_risk_score(self, guild_id, user_id, points):
        if guild_id not in self.risk_scores:
            self.risk_scores[guild_id] = {}
            
        if user_id not in self.risk_scores[guild_id]:
            self.risk_scores[guild_id][user_id] = 0
            
        self.risk_scores[guild_id][user_id] += points
        # Ensure score doesn't go below 0
        self.risk_scores[guild_id][user_id] = max(0, self.risk_scores[guild_id][user_id])
    
    @app_commands.command(name="riskscore", description="Check risk score for a user")
    @app_commands.checks.has_permissions(kick_members=True)
    async def riskscore(self, interaction: discord.Interaction, user: discord.Member):
        guild_id = str(interaction.guild_id)
        user_id = str(user.id)
        
        score = self.risk_scores.get(guild_id, {}).get(user_id, 0)
        
        embed = discord.Embed(
            title=f"Risk Assessment for {user.display_name}",
            description=f"Current risk score: **{score}**",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        
        # Risk level assessment
        risk_level = "Low"
        if score >= 10:
            risk_level = "Extreme"
            embed.color = discord.Color.dark_red()
        elif score >= 7:
            risk_level = "High"
            embed.color = discord.Color.red()
        elif score >= 4:
            risk_level = "Medium"
            embed.color = discord.Color.orange()
        
        embed.add_field(name="Risk Level", value=risk_level, inline=False)
        embed.set_footer(text="Risk scores increase with warnings and suspicious activity")
        
        await interaction.response.send_message(embed=embed)
    
    # Channel watchlist
    @app_commands.command(name="watchlist", description="Add a channel to the watchlist")
    @app_commands.checks.has_permissions(administrator=True)
    async def watchlist(self, interaction: discord.Interaction, channel: discord.TextChannel):
        channel_id = channel.id
        
        if channel_id not in self.config['watchlist_channels']:
            self.config['watchlist_channels'].append(channel_id)
            save_config(self.config)
            await interaction.response.send_message(f"{channel.mention} has been added to the watchlist.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{channel.mention} is already on the watchlist.", ephemeral=True)
    
    @app_commands.command(name="unwatchlist", description="Remove a channel from the watchlist")
    @app_commands.checks.has_permissions(administrator=True)
    async def unwatchlist(self, interaction: discord.Interaction, channel: discord.TextChannel):
        channel_id = channel.id
        
        if channel_id in self.config['watchlist_channels']:
            self.config['watchlist_channels'].remove(channel_id)
            save_config(self.config)
            await interaction.response.send_message(f"{channel.mention} has been removed from the watchlist.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{channel.mention} is not on the watchlist.", ephemeral=True)
    
    # Lockdown commands
    @app_commands.command(name="lockdown", description="Lock down a channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lockdown(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_channel = channel if channel else interaction.channel
        
        if target_channel.id in self.locked_channels:
            await interaction.response.send_message(f"{target_channel.mention} is already locked down.", ephemeral=True)
            return
        
        # Store current permissions and lock the channel
        overwrites = target_channel.overwrites_for(interaction.guild.default_role)
        overwrites.send_messages = False
        await target_channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        
        self.locked_channels.add(target_channel.id)
        
        embed = discord.Embed(
            title="🔒 Channel Locked",
            description=f"{target_channel.mention} has been locked down.",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text=f"Locked by {interaction.user}")
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="unlock", description="Unlock a locked channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_channel = channel if channel else interaction.channel
        
        if target_channel.id not in self.locked_channels:
            await interaction.response.send_message(f"{target_channel.mention} is not locked down.", ephemeral=True)
            return
        
        # Restore permissions
        overwrites = target_channel.overwrites_for(interaction.guild.default_role)
        overwrites.send_messages = None  # Reset to default
        await target_channel.set_permissions(interaction.guild.default_role, overwrite=overwrites)
        
        self.locked_channels.remove(target_channel.id)
        
        embed = discord.Embed(
            title="🔓 Channel Unlocked",
            description=f"{target_channel.mention} has been unlocked.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text=f"Unlocked by {interaction.user}")
        
        await interaction.response.send_message(embed=embed)
    
    # Keyword management
    @app_commands.command(name="addkeyword", description="Add a red flag keyword")
    @app_commands.checks.has_permissions(administrator=True)
    async def addkeyword(self, interaction: discord.Interaction, keyword: str):
        keyword = keyword.lower()
        
        if keyword not in self.config['red_flag_keywords']:
            self.config['red_flag_keywords'].append(keyword)
            save_config(self.config)
            await interaction.response.send_message(f"Added '{keyword}' to red flag keywords.", ephemeral=True)
        else:
            await interaction.response.send_message(f"'{keyword}' is already a red flag keyword.", ephemeral=True)
    
    @app_commands.command(name="removekeyword", description="Remove a red flag keyword")
    @app_commands.checks.has_permissions(administrator=True)
    async def removekeyword(self, interaction: discord.Interaction, keyword: str):
        keyword = keyword.lower()
        
        if keyword in self.config['red_flag_keywords']:
            self.config['red_flag_keywords'].remove(keyword)
            save_config(self.config)
            await interaction.response.send_message(f"Removed '{keyword}' from red flag keywords.", ephemeral=True)
        else:
            await interaction.response.send_message(f"'{keyword}' is not a red flag keyword.", ephemeral=True)
    
    @app_commands.command(name="listkeywords", description="List all red flag keywords")
    @app_commands.checks.has_permissions(administrator=True)
    async def listkeywords(self, interaction: discord.Interaction):
        if not self.config['red_flag_keywords']:
            await interaction.response.send_message("No red flag keywords have been set.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="Red Flag Keywords",
            description="The following keywords are being monitored:",
            color=discord.Color.yellow(),
            timestamp=datetime.datetime.now()
        )
        
        # Group keywords into chunks to avoid field value limit
        chunks = [self.config['red_flag_keywords'][i:i+15] for i in range(0, len(self.config['red_flag_keywords']), 15)]
        
        for i, chunk in enumerate(chunks, 1):
            embed.add_field(name=f"Keywords {i}", value=", ".join(chunk), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Bot approval system
    @app_commands.command(name="approvebot", description="Approve a bot to join the server")
    @app_commands.checks.has_permissions(administrator=True)
    async def approvebot(self, interaction: discord.Interaction, bot_id: str, reason: str = "No reason provided"):
        try:
            bot_id = int(bot_id)
            
            if bot_id not in self.config['approved_bots']:
                self.config['approved_bots'].append(bot_id)
                save_config(self.config)
                
                embed = discord.Embed(
                    title="Bot Approved",
                    description=f"Bot with ID `{bot_id}` has been approved to join the server.",
                    color=discord.Color.green(),
                    timestamp=datetime.datetime.now()
                )
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.set_footer(text=f"Approved by {interaction.user}")
                
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message(f"Bot with ID `{bot_id}` is already approved.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please provide a valid bot ID (numbers only).", ephemeral=True)
    
    @app_commands.command(name="rejectbot", description="Remove a bot from the approved list")
    @app_commands.checks.has_permissions(administrator=True)
    async def rejectbot(self, interaction: discord.Interaction, bot_id: str):
        try:
            bot_id = int(bot_id)
            
            if bot_id in self.config['approved_bots']:
                self.config['approved_bots'].remove(bot_id)
                save_config(self.config)
                await interaction.response.send_message(f"Bot with ID `{bot_id}` has been removed from the approved list.")
            else:
                await interaction.response.send_message(f"Bot with ID `{bot_id}` is not on the approved list.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Please provide a valid bot ID (numbers only).", ephemeral=True)
    
    # Raid threshold
    @app_commands.command(name="setraidthreshold", description="Set the threshold for raid detection")
    @app_commands.checks.has_permissions(administrator=True)
    async def setraidthreshold(self, interaction: discord.Interaction, threshold: int):
        if threshold < 2:
            await interaction.response.send_message("Threshold must be at least 2.", ephemeral=True)
            return
        
        self.config['raid_threshold'] = threshold
        save_config(self.config)
        
        await interaction.response.send_message(f"Raid detection threshold set to {threshold} joins per minute.")
    
    # Role limits
    @app_commands.command(name="setrolelimit", description="Set a limit for how many users can have a role")
    @app_commands.checks.has_permissions(administrator=True)
    async def setrolelimit(self, interaction: discord.Interaction, role: discord.Role, limit: int):
        if limit < 1:
            await interaction.response.send_message("Limit must be at least 1.", ephemeral=True)
            return
        
        self.config['role_limits'][str(role.id)] = limit
        save_config(self.config)
        
        await interaction.response.send_message(f"Role limit for {role.mention} set to {limit} users.")
    
    @app_commands.command(name="removerolelimit", description="Remove the limit for a role")
    @app_commands.checks.has_permissions(administrator=True)
    async def removerolelimit(self, interaction: discord.Interaction, role: discord.Role):
        role_id = str(role.id)
        
        if role_id in self.config['role_limits']:
            del self.config['role_limits'][role_id]
            save_config(self.config)
            await interaction.response.send_message(f"Role limit for {role.mention} has been removed.")
        else:
            await interaction.response.send_message(f"No limit is set for {role.mention}.", ephemeral=True)
    
    # Invite tracking
    @app_commands.command(name="inviteinfo", description="View information about server invites")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def inviteinfo(self, interaction: discord.Interaction):
        try:
            invites = await interaction.guild.invites()
            
            embed = discord.Embed(
                title="Server Invite Information",
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now()
            )
            
            if not invites:
                embed.description = "No active invites found for this server."
                await interaction.response.send_message(embed=embed)
                return
            
            for invite in invites:
                created_at = invite.created_at.strftime("%Y-%m-%d %H:%M:%S") if invite.created_at else "Unknown"
                expires_at = invite.expires_at.strftime("%Y-%m-%d %H:%M:%S") if invite.expires_at else "Never"
                
                value = (
                    f"Created by: {invite.inviter.mention if invite.inviter else 'Unknown'}\n"
                    f"Channel: {invite.channel.mention if invite.channel else 'Unknown'}\n"
                    f"Uses: {invite.uses}/{invite.max_uses if invite.max_uses else '∞'}\n"
                    f"Created: {created_at}\n"
                    f"Expires: {expires_at}"
                )
                
                embed.add_field(name=f"Invite: {invite.code}", value=value, inline=False)
            
            await interaction.response.send_message(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permission to view invites.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(SilverSecurityCog(bot))