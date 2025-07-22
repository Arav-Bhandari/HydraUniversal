import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger("bot.awards")

class AwardsCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'awardsconfig.json'
        self.config = self.load_config()

    # Load or initialize awards config
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading awardsconfig.json: {e}")
                return {}
        return {}

    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving awardsconfig.json: {e}")

    # Helper to get or create guild config
    def get_guild_config(self, guild_id):
        guild_id = str(guild_id)
        if guild_id not in self.config:
            self.config[guild_id] = {"awards": []}
            self.save_config()
        return self.config[guild_id]

    # Send log message to #general or configured log channel
    async def send_log_message(self, guild, embed):
        try:
            from utils.config import get_server_config
            config = get_server_config(guild.id)
            log_channel_id = config.get("log_channels", {}).get("general")
            
            if log_channel_id:
                log_channel = guild.get_channel(int(log_channel_id))
            else:
                log_channel = discord.utils.get(guild.text_channels, name="general")
            
            if log_channel:
                await log_channel.send(embed=embed)
            else:
                logger.warning(f"No log channel found for guild {guild.id}")
        except ImportError:
            log_channel = discord.utils.get(guild.text_channels, name="general")
            if log_channel:
                await log_channel.send(embed=embed)
            else:
                logger.warning(f"No #general channel found for guild {guild.id}")
        except Exception as e:
            logger.error(f"Error sending log message in guild {guild.id}: {e}")

    # Autocomplete for configured award roles
    async def award_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        guild_config = self.get_guild_config(interaction.guild.id)
        awards = guild_config.get("awards", [])
        choices = []
        
        for role_id in awards:
            role = interaction.guild.get_role(int(role_id))
            if role and (current.lower() in role.name.lower() or not current):
                choices.append(app_commands.Choice(name=role.name, value=role_id))
        
        return choices[:25]  # Discord limits to 25 choices

    @app_commands.command(name="award_create", description="Create a new award role")
    @app_commands.describe(role="The role to add as an award")
    async def award_create(self, interaction: discord.Interaction, role: discord.Role):
        """Create a new award role"""
        from utils.permissions import is_admin, has_management_role
        
        if not (await is_admin(interaction.user) or await has_management_role(interaction.user)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You need admin or management permissions to create awards.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Missing Permissions",
                    description="I don't have permission to manage roles.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        guild_config = self.get_guild_config(interaction.guild.id)
        if str(role.id) in guild_config["awards"]:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Award Exists",
                    description=f"{role.mention} is already an award.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        guild_config["awards"].append(str(role.id))
        self.save_config()

        embed = discord.Embed(
            title="Award Created",
            description=f"Award {role.mention} has been created.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Created by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        # Send log message
        log_embed = discord.Embed(
            title="🏆 Award Created",
            description=f"Award {role.mention} created by {interaction.user.mention}.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Role ID", value=role.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="award_view", description="View all configured awards")
    async def award_view(self, interaction: discord.Interaction):
        """View all configured awards"""

        guild_config = self.get_guild_config(interaction.guild.id)
        awards = guild_config.get("awards", [])

        if not awards:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="No Awards",
                    description="No awards are configured for this guild.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        award_list = []
        for role_id in awards:
            role = interaction.guild.get_role(int(role_id))
            if role:
                award_list.append(f"- {role.mention} (ID: {role_id})")
            else:
                award_list.append(f"- Role ID: {role_id} (Not found)")

        embed = discord.Embed(
            title="Configured Awards",
            description="\n".join(award_list) or "No valid awards found.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Requested by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="award_assign", description="Assign an award to a user")
    @app_commands.describe(
        user="The user to assign the award to",
        award="The award role to assign"
    )
    @app_commands.autocomplete(award=award_autocomplete)
    async def award_assign(self, interaction: discord.Interaction, user: discord.Member, award: str):
        """Assign an award to a user"""
        from utils.permissions import is_admin, has_management_role
        
        if not (await is_admin(interaction.user) or await has_management_role(interaction.user)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You need admin or management permissions to assign awards.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Missing Permissions",
                    description="I don't have permission to manage roles.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        guild_config = self.get_guild_config(interaction.guild.id)
        if award not in guild_config["awards"]:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Invalid Award",
                    description="This role is not a configured award.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(int(award))
        if not role:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Role Not Found",
                    description="The award role no longer exists.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if role in user.roles:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Award Already Assigned",
                    description=f"{user.mention} already has the {role.mention} award.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        try:
            await user.add_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Error",
                    description="I don't have permission to assign this role. Ensure my role is above the award role.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return
        except Exception as e:
            logger.error(f"Error assigning award role {role.id} to {user.id}: {e}")
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Error",
                    description=f"Failed to assign award: {e}",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Award Assigned",
            description=f"Award {role.mention} assigned to {user.mention}.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Assigned by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        # Send log message
        log_embed = discord.Embed(
            title="🏆 Award Assigned",
            description=f"Award {role.mention} assigned to {user.mention} by {interaction.user.mention}.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Role ID", value=role.id, inline=True)
        log_embed.add_field(name="User ID", value=user.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="award_remove", description="Remove an award from a user")
    @app_commands.describe(
        user="The user to remove the award from",
        award="The award role to remove"
    )
    @app_commands.autocomplete(award=award_autocomplete)
    async def award_remove(self, interaction: discord.Interaction, user: discord.Member, award: str):
        """Remove an award from a user"""
        from utils.permissions import is_admin, has_management_role
        
        if not (await is_admin(interaction.user) or await has_management_role(interaction.user)):
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Denied",
                    description="You need admin or management permissions to remove awards.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Missing Permissions",
                    description="I don't have permission to manage roles.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        guild_config = self.get_guild_config(interaction.guild.id)
        if award not in guild_config["awards"]:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Invalid Award",
                    description="This role is not a configured award.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(int(award))
        if not role:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Role Not Found",
                    description="The award role no longer exists.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        if role not in user.roles:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Award Not Assigned",
                    description=f"{user.mention} does not have the {role.mention} award.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        try:
            await user.remove_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Permission Error",
                    description="I don't have permission to remove this role. Ensure my role is above the award role.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return
        except Exception as e:
            logger.error(f"Error removing award role {role.id} from {user.id}: {e}")
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Error",
                    description=f"Failed to remove award: {e}",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Award Removed",
            description=f"Award {role.mention} removed from {user.mention}.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Removed by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed)

        # Send log message
        log_embed = discord.Embed(
            title="🏆 Award Removed",
            description=f"Award {role.mention} removed from {user.mention} by {interaction.user.mention}.",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Role ID", value=role.id, inline=True)
        log_embed.add_field(name="User ID", value=user.id, inline=True)
        await self.send_log_message(interaction.guild, log_embed)

    @app_commands.command(name="awardcheck", description="Check awards for a user")
    @app_commands.describe(user="The user to check awards for (defaults to you)")
    async def awardcheck(self, interaction: discord.Interaction, user: discord.Member = None):
        """Check awards for a user (defaults to the interaction user)"""
        # Default to interaction user if no user is provided
        target_user = user or interaction.user

        guild_config = self.get_guild_config(interaction.guild.id)
        awards = guild_config.get("awards", [])

        if not awards:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="No Awards Configured",
                    description="No awards are configured for this guild.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Find awards the user has
        user_awards = []
        for role_id in awards:
            role = interaction.guild.get_role(int(role_id))
            if role and role in target_user.roles:
                user_awards.append(f"- {role.mention} (ID: {role_id})")

        # Create embed
        embed = discord.Embed(
            title=f"Awards for {target_user.display_name}",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.set_thumbnail(url=target_user.avatar.url if target_user.avatar else None)
        
        if user_awards:
            embed.description = "\n".join(user_awards)
        else:
            embed.description = f"{target_user.mention} has no awards."
        
        embed.add_field(name="Requested by", value=interaction.user.mention, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AwardsCommands(bot))