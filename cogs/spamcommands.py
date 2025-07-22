import discord
import asyncio
import logging
from discord import app_commands
from discord.ext import commands
from utils.permissions import is_admin
from utils.logging import log_action
from utils.embeds import EmbedBuilder
from datetime import datetime

logger = logging.getLogger("bot.spam")

class SpamCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="spamdmwqvp", description="Send 15 DMs to Wqvp with a custom message")
    @app_commands.describe(message="The message to send in the DMs")
    async def spamdmtexas(self, interaction: discord.Interaction, message: str):
        """Send 5 direct messages to user ID 667199698695749692 with the specified message"""
        try:

            if not message or len(message) > 2000:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Invalid Message", "Message must be non-empty and under 2000 characters."),
                    ephemeral=True
                )
                return
            
            # Fetch the target user
            target_user_id = 667199698695749692
            try:
                target_user = await self.bot.fetch_user(target_user_id)
            except discord.errors.NotFound:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("User Not Found", f"No user found with ID {target_user_id}."),
                    ephemeral=True
                )
                return
            except Exception as e:
                logger.error(f"Failed to fetch user {target_user_id}: {e}")
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Fetch Error", "Failed to fetch the target user. Please try again later."),
                    ephemeral=True
                )
                return
            
            # Send 5 DMs with a slight delay to avoid rate limits
            sent_count = 0
            for i in range(15):
                try:
                    await target_user.send(
                        embed=discord.Embed(
                            title=f"Message {i+1} from {interaction.user.name}",
                            description=message,
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        ).set_footer(text=f"Sent via /spamdmemily command")
                    )
                    sent_count += 1
                    await asyncio.sleep(1)  # Delay to prevent rate limiting
                except discord.errors.Forbidden:
                    await interaction.response.send_message(
                        embed=EmbedBuilder.error("DM Failed", f"Cannot send DMs to {target_user.name}. They may have DMs disabled or blocked the bot."),
                        ephemeral=True
                    )
                    return
                except Exception as e:
                    logger.error(f"Failed to send DM {i+1} to {target_user_id}: {e}")
                    await interaction.response.send_message(
                        embed=EmbedBuilder.error("DM Error", f"Failed to send DM {i+1}. Please try again later."),
                        ephemeral=True
                    )
                    return
            
            # Send success response
            embed = discord.Embed(
                title="DMs Sent Successfully",
                description=f"Sent {sent_count} DMs to {target_user.mention} with the message:\n\n{message}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Sent by {interaction.user.name}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Log the action
            try:
                log_message = f"{interaction.user.mention} sent {sent_count} DMs to {target_user.mention} with message: {message}"
                await log_action(
                    interaction.guild,
                    "SPAMDM",
                    interaction.user,
                    log_message,
                    "spamdmtexas"
                )
            except Exception as e:
                logger.error(f"Failed to log spamdmtexas action: {e}")
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Log Error", "Failed to log the action. The DMs were sent but not recorded."),
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error in spamdmtexas command: {e}")
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Unexpected Error", "An error occurred while processing the command. Please try again."),
                ephemeral=True
            )

    @app_commands.command(name="remind", description="Send a reminder DM to all users in a specified role")
    @app_commands.describe(
        role="The role to send the reminder to",
        message="The message to send in the DMs"
    )
    async def remind(self, interaction: discord.Interaction, role: discord.Role, message: str):
        """Send a reminder DM to all members with the specified role"""
        try:
            # Check if the user is an admin
            if not await is_admin(interaction.user):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Permission Denied", "Only admins can use this command."),
                    ephemeral=True
                )
                return
            
            # Validate message length
            if not message or len(message) > 2000:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Invalid Message", "Message must be non-empty and under 2000 characters."),
                    ephemeral=True
                )
                return
            
            # Validate role
            if not role.members:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Empty Role", f"The role {role.mention} has no members."),
                    ephemeral=True
                )
                return
            
            # Send DMs to each member with the role
            sent_count = 0
            failed_count = 0
            failed_users = []
            
            for member in role.members:
                if member.bot:
                    continue  # Skip bots
                try:
                    await member.send(
                        embed=discord.Embed(
                            title=f"Reminder from {interaction.guild.name}",
                            description=message,
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        ).set_footer(text=f"Sent via /remind command by {interaction.user.name}")
                    )
                    sent_count += 1
                    await asyncio.sleep(1)  # Delay to prevent rate limiting
                except discord.errors.Forbidden:
                    failed_count += 1
                    failed_users.append(member.mention)
                except Exception as e:
                    logger.error(f"Failed to send DM to {member.id}: {e}")
                    failed_count += 1
                    failed_users.append(member.mention)
            
            # Send success response
            embed = discord.Embed(
                title="Reminder DMs Sent",
                description=f"Sent {sent_count} DMs to members with {role.mention}.\n\n**Message:**\n{message}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            if failed_count > 0:
                embed.add_field(
                    name="Failed DMs",
                    value=f"Failed to send DMs to {failed_count} member(s): {', '.join(failed_users[:5])}{'...' if len(failed_users) > 5 else ''}",
                    inline=False
                )
            embed.set_footer(text=f"Sent by {interaction.user.name}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Log the action
            try:
                log_message = f"{interaction.user.mention} sent reminder DMs to {sent_count} members with {role.mention} (failed: {failed_count}). Message: {message}"
                await log_action(
                    interaction.guild,
                    "REMIND",
                    interaction.user,
                    log_message,
                    "remind"
                )
            except Exception as e:
                logger.error(f"Failed to log remind action: {e}")
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Log Error", "Failed to log the action. The DMs were sent but not recorded."),
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error in remind command: {e}")
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Unexpected Error", "An error occurred while processing the command. Please try again."),
                ephemeral=True
            )

async def setup(bot):
    try:
        await bot.add_cog(SpamCommands(bot))
    except Exception as e:
        logger.error(f"Failed to load SpamCommands cog: {e}")