
import discord
import logging
from discord import app_commands
from discord.ext import commands
from utils.config import get_server_config
from utils.permissions import can_use_command
from datetime import datetime

logger = logging.getLogger("bot.folist")

class OwnersUpdateView(discord.ui.View):
    """View with button to manually refresh owners list"""
    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        
    @discord.ui.button(label="🔄 Update List", style=discord.ButtonStyle.primary, custom_id="owners_update_button")
    async def update_owners_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Manual refresh of owners list"""
        await interaction.response.defer()
        
        try:
            config = get_server_config(self.guild_id)
            guild = self.bot.get_guild(self.guild_id)
            
            if not guild:
                await interaction.followup.send("Guild not found.", ephemeral=True)
                return
                
            # Clear previous messages in channel
            channel = interaction.channel
            async for message in channel.history(limit=50):
                if message.author == self.bot.user:
                    try:
                        await message.delete()
                    except:
                        pass
            
            # Recreate and send updated owners list
            team_data = config.get("team_data", {})
            permission_settings = config.get("permission_settings", {})
            fo_role_ids = permission_settings.get("fo_roles", [])
            
            if not team_data or not fo_role_ids:
                embed = discord.Embed(
                    title="🏆 Franchise Owners Directory",
                    description="No franchise owners configured. Use setup to assign roles and teams.",
                    color=discord.Color.orange()
                )
                await channel.send(embed=embed, view=OwnersUpdateView(self.bot, self.guild_id))
                return
            
            # Create updated embeds
            embeds = []
            current_embed = discord.Embed(
                title="🏆 Franchise Owners Directory",
                description="Current franchise owners and their teams:",
                color=discord.Color.gold()
            )
            
            field_count = 0
            
            for team_name, team_info in sorted(team_data.items()):
                team_role_id = team_info.get("role_id")
                team_emoji = team_info.get("emoji", "🏆")
                
                if not team_role_id:
                    continue
                    
                team_role = guild.get_role(team_role_id)
                if not team_role:
                    continue
                
                # Find franchise owners for this team
                team_owners = []
                for member in guild.members:
                    if (team_role in member.roles and 
                        any(guild.get_role(fo_role_id) in member.roles for fo_role_id in fo_role_ids if guild.get_role(fo_role_id))):
                        team_owners.append(member)
                
                if team_owners:
                    owners_text = "\n".join([f"{member.mention} `{member.display_name}`" for member in team_owners])
                    field_value = f"{team_emoji} {team_role.mention}\n{owners_text}"
                    
                    # Check if we need a new embed (25 field limit)
                    if field_count >= 25:
                        embeds.append(current_embed)
                        current_embed = discord.Embed(
                            title="🏆 Franchise Owners Directory (Continued)",
                            color=discord.Color.gold()
                        )
                        field_count = 0
                    
                    current_embed.add_field(
                        name=f"{team_emoji} {team_name}",
                        value=field_value,
                        inline=True
                    )
                    field_count += 1
            
            if field_count > 0:
                embeds.append(current_embed)
            
            if not embeds:
                embed = discord.Embed(
                    title="🏆 Franchise Owners Directory",
                    description="No franchise owners found. Assign the Franchise Owner role to team members.",
                    color=discord.Color.orange()
                )
                embeds.append(embed)
            
            # Send updated embeds
            for i, embed in enumerate(embeds):
                if i == len(embeds) - 1:  # Add button to last embed
                    embed.set_footer(text=f"Last updated: {discord.utils.format_dt(discord.utils.utcnow(), 'F')}")
                    await channel.send(embed=embed, view=OwnersUpdateView(self.bot, self.guild_id))
                else:
                    await channel.send(embed=embed)
                    
            await interaction.followup.send("✅ Owners list updated successfully!", ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error updating owners list for guild {self.guild_id}: {e}", exc_info=True)
            await interaction.followup.send("❌ Error updating owners list.", ephemeral=True)

class folist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="franchiselist", description="Display a list of all Franchise Owners and their teams")
    @app_commands.check(lambda inter: can_use_command(inter, "franchiselist"))
    async def franchiselist(self, interaction: discord.Interaction):
        """Display a list of all Franchise Owners and their teams in the owners channel"""
        guild = interaction.guild
        config = get_server_config(guild.id)

        # Get the owners channel from config (updated to use setup configuration)
        owners_channel_id = config.get("log_channels", {}).get("owners")
        if not owners_channel_id:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Configuration Error",
                    description="Owners channel not configured. Please set it up using `/setup` or `/setchannel owners`.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        owners_channel = guild.get_channel(int(owners_channel_id))
        if not owners_channel:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Channel Error",
                    description="Owners channel not found. Please check the configuration using `/settings`.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        try:
            # Get team data and permission settings from config
            team_data = config.get("team_data", {})
            permission_settings = config.get("permission_settings", {})
            fo_role_ids = permission_settings.get("fo_roles", [])
            
            if not fo_role_ids:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Configuration Error",
                        description="Franchise Owner roles not configured. Please set them up using `/setup` or `/setrole fo`.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return

            if not team_data:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        title="❌ Configuration Error",
                        description="No teams configured. Please add teams using `/addteam` or `/setup`.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
                return

            # Create embeds for franchise owners
            embeds = []
            current_embed = discord.Embed(
                title="🏆 Franchise Owners Directory",
                description="Current franchise owners and their teams:",
                color=discord.Color.gold()
            )
            
            # Set thumbnail if guild has icon
            if guild.icon:
                current_embed.set_thumbnail(url=guild.icon.url)
            
            field_count = 0
            
            for team_name, team_info in sorted(team_data.items()):
                team_role_id = team_info.get("role_id")
                team_emoji = team_info.get("emoji", "🏆")
                
                if not team_role_id:
                    continue
                    
                team_role = guild.get_role(team_role_id)
                if not team_role:
                    continue
                
                # Find franchise owners for this team
                team_owners = []
                for member in guild.members:
                    if (team_role in member.roles and 
                        any(guild.get_role(fo_role_id) in member.roles for fo_role_id in fo_role_ids if guild.get_role(fo_role_id))):
                        team_owners.append(member)
                
                if team_owners:
                    owners_text = "\n".join([f"{member.mention} `{member.display_name}`" for member in team_owners])
                    field_value = f"{team_emoji} {team_role.mention}\n{owners_text}"
                    
                    # Check if we need a new embed (25 field limit)
                    if field_count >= 25:
                        embeds.append(current_embed)
                        current_embed = discord.Embed(
                            title="🏆 Franchise Owners Directory (Continued)",
                            color=discord.Color.gold()
                        )
                        field_count = 0
                    
                    current_embed.add_field(
                        name=f"{team_emoji} {team_name}",
                        value=field_value,
                        inline=True
                    )
                    field_count += 1
            
            if field_count > 0:
                embeds.append(current_embed)
            
            if not embeds:
                # No franchise owners found
                embed = discord.Embed(
                    title="🏆 Franchise Owners Directory",
                    description="No franchise owners found. Assign the Franchise Owner role to team members.",
                    color=discord.Color.orange()
                )
                embeds.append(embed)
            
            # Send embeds with update button
            for i, embed in enumerate(embeds):
                if i == len(embeds) - 1:  # Add button to last embed
                    embed.set_footer(text=f"Generated by {interaction.user.display_name} • {discord.utils.format_dt(discord.utils.utcnow(), 'F')}")
                    await owners_channel.send(embed=embed, view=OwnersUpdateView(self.bot, guild.id))
                else:
                    await owners_channel.send(embed=embed)

            # Confirm success to user
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="✅ Success",
                    description=f"Franchise Owner list has been sent to {owners_channel.mention}.",
                    color=discord.Color.green()
                ),
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Unexpected error in /franchiselist for guild {guild.id}: {e}", exc_info=True)
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Error",
                    description=f"An unexpected error occurred: {str(e)}",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )

    @franchiselist.error
    async def franchiselist_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            embed = discord.Embed(
                title="🚫 Permission Denied",
                description="You don't have permission to use this command.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            logger.error(f"Error in franchiselist command: {error}")
            embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred: {error}",
                color=discord.Color.red()
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(folist(bot))
