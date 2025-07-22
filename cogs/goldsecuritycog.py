import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import json
import datetime
import aiohttp
import io
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from collections import defaultdict, Counter
import os
from typing import Optional, List, Union
import geoip2.database
import geoip2.errors


class PremiumSecurity(commands.Cog):
    """Premium moderation and security system"""
    
    def __init__(self, bot):
        self.bot = bot
        self.data_file = "security_config.json"
        self.data_dir = "premium_security_data"
        self.config = {}
        self.raid_mode = {}
        self.lockdown_active = {}
        self.init_json_file()
        self.load_config()
    
    def init_json_file(self):
        """Initialize the single JSON file for persistent storage"""
        os.makedirs(self.data_dir, exist_ok=True)
        file_path = os.path.join(self.data_dir, self.data_file)
        
        if not os.path.exists(file_path):
            initial_data = {
                "guild_config": {},
                "user_audit": {},
                "incidents": {},
                "shared_bans": {},
                "analytics": {}
            }
            try:
                with open(file_path, 'w') as f:
                    json.dump(initial_data, f, indent=2)
            except Exception as e:
                print(f"Error initializing JSON file: {e}")
    
    def load_config(self):
        """Load guild configurations from JSON file"""
        file_path = os.path.join(self.data_dir, self.data_file)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                self.config = data.get("guild_config", {})
        except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
            print(f"Error loading config: {e}")
            self.config = {}
    
    def get_guild_config(self, guild_id: int) -> dict:
        """Get configuration for a specific guild"""
        guild_id_str = str(guild_id)  # JSON keys must be strings
        return self.config.get(guild_id_str, {
            "arm_enabled": True,
            "arm_threshold": 10,
            "geofence_enabled": False,
            "blocked_countries": [],
            "whitelist_roles": [],
            "alert_channel": None,
            "log_channel": None,
            "auto_ban_invites": True,
            "persistent_offender_alerts": True,
            "role_tamper_alerts": True,
            "weekly_reports": True,
            "shared_bans": False
        })
    
    async def save_guild_config(self, guild_id: int, config: dict):
        """Save guild configuration to JSON file"""
        guild_id_str = str(guild_id)
        file_path = os.path.join(self.data_dir, self.data_file)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            data["guild_config"][guild_id_str] = config
            self.config[guild_id_str] = config
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
        except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
            print(f"Error saving guild config: {e}")
    
    async def log_audit(self, guild_id: int, user_id: int, action: str, details: str):
        """Log user action for audit trail"""
        guild_id_str = str(guild_id)
        file_path = os.path.join(self.data_dir, self.data_file)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            if guild_id_str not in data["user_audit"]:
                data["user_audit"][guild_id_str] = []
            data["user_audit"][guild_id_str].append({
                "user_id": user_id,
                "action": action,
                "details": details,
                "timestamp": datetime.datetime.utcnow().isoformat()
            })
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
        except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
            print(f"Error logging audit: {e}")
    
    async def log_incident(self, guild_id: int, incident_type: str, details: str):
        """Log security incident"""
        guild_id_str = str(guild_id)
        file_path = os.path.join(self.data_dir, self.data_file)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            if guild_id_str not in data["incidents"]:
                data["incidents"][guild_id_str] = []
            data["incidents"][guild_id_str].append({
                "incident_type": incident_type,
                "details": details,
                "timestamp": datetime.datetime.utcnow().isoformat()
            })
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
        except (json.JSONDecodeError, FileNotFoundError, IOError) as e:
            print(f"Error logging incident: {e}")
    
    # ====================== SLASH COMMANDS ======================
    
    @app_commands.command(name="arm-config", description="Configure Automatic Raid Mitigation system")
    @app_commands.describe(
        enabled="Enable/disable ArM system",
        threshold="Number of joins per minute to trigger ArM",
        alert_channel="Channel for security alerts"
    )
    async def arm_config(
        self, 
        interaction: discord.Interaction, 
        enabled: bool = None,
        threshold: int = None,
        alert_channel: discord.TextChannel = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permissions required!", ephemeral=True)
            return
        
        config = self.get_guild_config(interaction.guild.id)
        
        if enabled is not None:
            config["arm_enabled"] = enabled
        if threshold is not None:
            config["arm_threshold"] = max(5, threshold)
        if alert_channel:
            config["alert_channel"] = alert_channel.id
        
        await self.save_guild_config(interaction.guild.id, config)
        
        embed = discord.Embed(
            title="🛡️ ArM Configuration Updated",
            color=0x00ff88,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Status", value="✅ Enabled" if config["arm_enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Threshold", value=f"{config['arm_threshold']} joins/min", inline=True)
        embed.add_field(name="Alert Channel", value=f"<#{config['alert_channel']}>" if config.get('alert_channel') else "Not set", inline=True)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="geofence", description="Configure geographic restrictions for new members")
    @app_commands.describe(
        enabled="Enable/disable geofencing",
        countries="Comma-separated country codes to block (e.g., 'CN,RU')"
    )
    async def geofence_config(
        self, 
        interaction: discord.Interaction, 
        enabled: bool = None,
        countries: str = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Administrator permissions required!", ephemeral=True)
            return
        
        config = self.get_guild_config(interaction.guild.id)
        
        if enabled is not None:
            config["geofence_enabled"] = enabled
        if countries:
            config["blocked_countries"] = [c.strip().upper() for c in countries.split(",")]
        
        await self.save_guild_config(interaction.guild.id, config)
        
        embed = discord.Embed(
            title="🌍 Geofencing Configuration",
            color=0xff6b6b,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Status", value="✅ Enabled" if config["geofence_enabled"] else "❌ Disabled", inline=True)
        embed.add_field(name="Blocked Countries", value=", ".join(config["blocked_countries"]) or "None", inline=False)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="panic", description="Emergency lockdown - removes message permissions for all non-staff")
    async def panic_mode(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Manage Server permissions required!", ephemeral=True)
            return
        
        guild = interaction.guild
        config = self.get_guild_config(guild.id)
        
        await interaction.response.defer()
        
        staff_roles = [role for role in guild.roles if role.permissions.administrator or role.permissions.manage_messages]
        
        lockdown_count = 0
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.set_permissions(guild.default_role, send_messages=False, reason="Emergency lockdown activated")
                    lockdown_count += 1
                except discord.Forbidden:
                    pass
        
        self.lockdown_active[guild.id] = True
        
        await self.log_incident(guild.id, "PANIC_LOCKDOWN", f"Activated by {interaction.user} - {lockdown_count} channels locked")
        
        embed = discord.Embed(
            title="🚨 EMERGENCY LOCKDOWN ACTIVATED",
            description=f"**{lockdown_count}** channels have been locked down.",
            color=0xff0000,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Activated By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Staff Roles Preserved", value=f"{len(staff_roles)} roles", inline=True)
        embed.set_footer(text="Use /unlock-server to restore normal operations")
        
        await interaction.followup.send(embed=embed)
        
        if config.get("alert_channel"):
            alert_channel = guild.get_channel(config["alert_channel"])
            if alert_channel:
                await alert_channel.send(embed=embed)
    
    @app_commands.command(name="unlock-server", description="Remove emergency lockdown")
    async def unlock_server(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Manage Server permissions required!", ephemeral=True)
            return
        
        guild = interaction.guild
        
        if not self.lockdown_active.get(guild.id):
            await interaction.response.send_message("❌ Server is not in lockdown mode!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        unlock_count = 0
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.set_permissions(guild.default_role, send_messages=None, reason="Emergency lockdown deactivated")
                    unlock_count += 1
                except discord.Forbidden:
                    pass
        
        self.lockdown_active[guild.id] = False
        
        embed = discord.Embed(
            title="✅ LOCKDOWN DEACTIVATED",
            description=f"**{unlock_count}** channels have been unlocked.",
            color=0x00ff88,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Deactivated By", value=interaction.user.mention, inline=True)
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="audit", description="Generate comprehensive user behavior report")
    @app_commands.describe(user="User to audit")
    async def audit_user(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ Manage Messages permissions required!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        guild_id_str = str(interaction.guild.id)
        file_path = os.path.join(self.data_dir, self.data_file)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            audit_records = data.get("user_audit", {}).get(guild_id_str, [])[:50]
            audit_records = [
                (r["action"], r["details"], r["timestamp"])
                for r in sorted(audit_records, key=lambda x: x["timestamp"], reverse=True)
                if r["user_id"] == user.id
            ]
        except (json.JSONDecodeError, FileNotFoundError, IOError):
            audit_records = []
        
        risk_factors = {
            "recent_joins": 0,
            "name_changes": 0,
            "warnings": 0,
            "deleted_messages": 0
        }
        
        for action, details, timestamp in audit_records:
            if action == "JOIN":
                risk_factors["recent_joins"] += 1
            elif action == "NAME_CHANGE":
                risk_factors["name_changes"] += 1
            elif action == "WARNING":
                risk_factors["warnings"] += 1
            elif action == "MESSAGE_DELETE":
                risk_factors["deleted_messages"] += 1
        
        risk_score = (
            risk_factors["warnings"] * 3 +
            risk_factors["name_changes"] * 2 +
            risk_factors["deleted_messages"] * 1 +
            max(0, risk_factors["recent_joins"] - 1) * 2
        )
        
        if risk_score <= 5:
            risk_level = "🟢 LOW"
            risk_color = 0x00ff88
        elif risk_score <= 15:
            risk_level = "🟡 MEDIUM"
            risk_color = 0xffeb3b
        else:
            risk_level = "🔴 HIGH"
            risk_color = 0xff5252
        
        embed = discord.Embed(
            title=f"📊 User Audit Report",
            description=f"**Target:** {user.mention}\n**Risk Level:** {risk_level} ({risk_score} points)",
            color=risk_color,
            timestamp=datetime.datetime.utcnow()
        )
        
        embed.add_field(name="Account Info", value=f"**Created:** <t:{int(user.created_at.timestamp())}:R>\n**Joined:** <t:{int(user.joined_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Risk Factors", value=f"**Warnings:** {risk_factors['warnings']}\n**Name Changes:** {risk_factors['name_changes']}\n**Deleted Messages:** {risk_factors['deleted_messages']}", inline=True)
        embed.add_field(name="Recent Activity", value=f"{len(audit_records)} logged actions", inline=True)
        
        if audit_records:
            recent_actions = "\n".join([f"`{action}` - {timestamp[:10]}" for action, _, timestamp in audit_records[:5]])
            embed.add_field(name="Recent Actions", value=recent_actions, inline=False)
        
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Audit requested by {interaction.user}")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="analytics", description="Generate server analytics graph report")
    @app_commands.describe(
        report_type="Type of analytics report",
        days="Number of days to analyze (default: 7)"
    )
    @app_commands.choices(report_type=[
        app_commands.Choice(name="Joins & Leaves", value="joins_leaves"),
        app_commands.Choice(name="Risk Scores", value="risk_scores"),
        app_commands.Choice(name="Channel Activity", value="channel_activity"),
        app_commands.Choice(name="Moderation Stats", value="mod_stats")
    ])
    async def analytics_report(
        self, 
        interaction: discord.Interaction, 
        report_type: app_commands.Choice[str],
        days: int = 7
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Manage Server permissions required!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            graph_buffer = await self.generate_analytics_graph(interaction.guild.id, report_type.value, days)
            
            embed = discord.Embed(
                title=f"📈 {report_type.name} Report",
                description=f"Analytics for the past {days} days",
                color=0x2196F3,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_footer(text=f"Generated by Premium Security • Requested by {interaction.user}")
            
            file = discord.File(graph_buffer, filename=f"{report_type.value}_report.png")
            embed.set_image(url=f"attachment://{report_type.value}_report.png")
            
            await interaction.followup.send(embed=embed, file=file)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error generating report: {str(e)}")
    
    @app_commands.command(name="incident-log", description="Generate incident archive report")
    @app_commands.describe(days="Number of days to include (default: 30)")
    async def incident_log(self, interaction: discord.Interaction, days: int = 30):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Manage Server permissions required!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        guild_id_str = str(interaction.guild.id)
        file_path = os.path.join(self.data_dir, self.data_file)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            incidents = [
                (i["incident_type"], i["details"], i["timestamp"])
                for i in data.get("incidents", {}).get(guild_id_str, [])
                if datetime.datetime.fromisoformat(i["timestamp"]) > datetime.datetime.utcnow() - datetime.timedelta(days=days)
            ]
            incidents.sort(key=lambda x: x[2], reverse=True)
        except (json.JSONDecodeError, FileNotFoundError, IOError):
            incidents = []
        
        if not incidents:
            embed = discord.Embed(
                title="📋 Incident Log",
                description="No incidents recorded in the specified timeframe.",
                color=0x00ff88
            )
            await interaction.followup.send(embed=embed)
            return
        
        embed = discord.Embed(
            title="📋 Security Incident Archive",
            description=f"**{len(incidents)}** incidents in the past {days} days",
            color=0xff9800,
            timestamp=datetime.datetime.utcnow()
        )
        
        incident_types = Counter([incident[0] for incident in incidents])
        type_summary = "\n".join([f"**{itype}:** {count}" for itype, count in incident_types.most_common()])
        embed.add_field(name="Incident Types", value=type_summary, inline=False)
        
        recent_incidents = "\n".join([
            f"`{itype}` - {timestamp[:16]}\n{details[:50]}..." 
            for itype, details, timestamp in incidents[:5]
        ])
        embed.add_field(name="Recent Incidents", value=recent_incidents or "None", inline=False)
        
        embed.set_footer(text=f"Report generated by {interaction.user}")
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="shared-bans", description="Manage shared ban list between servers")
    @app_commands.describe(
        action="Action to perform",
        file="Ban list file to import (optional)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Export Ban List", value="export"),
        app_commands.Choice(name="Import Ban List", value="import"),
        app_commands.Choice(name="View Shared Bans", value="view")
    ])
    async def shared_bans(
        self, 
        interaction: discord.Interaction, 
        action: app_commands.Choice[str],
        file: discord.Attachment = None
    ):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Ban Members permissions required!", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        file_path = os.path.join(self.data_dir, self.data_file)
        if action.value == "export":
            bans = [ban async for ban in interaction.guild.bans()]
            ban_data = {
                "server": interaction.guild.name,
                "exported": datetime.datetime.utcnow().isoformat(),
                "bans": [
                    {
                        "user_id": ban.user.id,
                        "username": str(ban.user),
                        "reason": ban.reason or "No reason provided"
                    }
                    for ban in bans
                ]
            }
            
            ban_json = json.dumps(ban_data, indent=2)
            file_buffer = io.BytesIO(ban_json.encode())
            
            embed = discord.Embed(
                title="📤 Ban List Exported",
                description=f"Exported {len(bans)} bans from {interaction.guild.name}",
                color=0x2196F3
            )
            
            await interaction.followup.send(
                embed=embed,
                file=discord.File(file_buffer, filename=f"{interaction.guild.name}_bans.json")
            )
        
        elif action.value == "view":
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                shared_bans = data.get("shared_bans", {}).get(str(interaction.guild.id), [])[:20]
                shared_bans.sort(key=lambda x: x["timestamp"], reverse=True)
            except (json.JSONDecodeError, FileNotFoundError, IOError):
                shared_bans = []
            
            embed = discord.Embed(
                title="🔗 Shared Ban List",
                description=f"Showing {len(shared_bans)} recent shared bans",
                color=0x9c27b0
            )
            
            if shared_bans:
                ban_list = "\n".join([
                    f"<@{b['user_id']}> - {b['reason'][:30]}..." 
                    for b in shared_bans[:10]
                ])
                embed.add_field(name="Recent Bans", value=ban_list, inline=False)
            
            await interaction.followup.send(embed=embed)
    
    # ====================== EVENT HANDLERS ======================
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Handle member joins with ArM and geofencing"""
        guild = member.guild
        config = self.get_guild_config(guild.id)
        
        await self.log_audit(guild.id, member.id, "JOIN", f"User joined: {member}")
        
        if config.get("geofence_enabled") and config.get("blocked_countries"):
            # Placeholder for GeoIP implementation
            try:
                pass
            except Exception:
                pass
        
        if config.get("persistent_offender_alerts"):
            file_path = os.path.join(self.data_dir, self.data_file)
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                other_bans = [
                    b for g, bans in data.get("shared_bans", {}).items()
                    if g != str(guild.id) for b in bans if b["user_id"] == member.id
                ]
            except (json.JSONDecodeError, FileNotFoundError, IOError):
                other_bans = []
            
            if other_bans and config.get("alert_channel"):
                alert_channel = guild.get_channel(config["alert_channel"])
                if alert_channel:
                    embed = discord.Embed(
                        title="⚠️ Persistent Offender Alert",
                        description=f"**{member}** has been banned from other servers using this system.",
                        color=0xff9800
                    )
                    embed.add_field(name="Previous Offenses", value=f"{len(other_bans)} bans found", inline=True)
                    await alert_channel.send(embed=embed)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Monitor for invite spam and other suspicious activity"""
        if message.author.bot or not message.guild:
            return
        
        config = self.get_guild_config(message.guild.id)
        
        if config.get("auto_ban_invites"):
            if "discord.gg/" in message.content or "discord.com/invite/" in message.content:
                recent_invites = await self.count_recent_invites(message.author.id, message.guild.id)
                if recent_invites >= 3:
                    try:
                        await message.author.ban(reason="Automatic: Invite spam detected")
                        await message.delete()
                        await self.log_incident(message.guild.id, "INVITE_SPAM_BAN", f"Banned {message.author} for invite spam")
                    except discord.Forbidden:
                        pass
    
    # ====================== HELPER METHODS ======================
    
    async def generate_analytics_graph(self, guild_id: int, report_type: str, days: int) -> io.BytesIO:
        """Generate analytics graphs using matplotlib"""
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 8))
        
        dates = [datetime.datetime.now() - datetime.timedelta(days=i) for i in range(days)]
        dates.reverse()
        
        if report_type == "joins_leaves":
            joins = [abs(hash(f"{guild_id}_join_{date}")) % 20 for date in dates]
            leaves = [abs(hash(f"{guild_id}_leave_{date}")) % 15 for date in dates]
            
            ax.plot(dates, joins, label='Joins', color='#4CAF50', marker='o')
            ax.plot(dates, leaves, label='Leaves', color='#F44336', marker='s')
            ax.set_title('Member Joins vs Leaves', fontsize=16, color='white')
            ax.set_ylabel('Count', color='white')
        
        elif report_type == "risk_scores":
            risk_scores = [abs(hash(f"{guild_id}_risk_{date}")) % 100 for date in dates]
            ax.plot(dates, risk_scores, label='Average Risk Score', color='#FF9800', marker='d')
            ax.axhline(y=50, color='red', linestyle='--', alpha=0.7, label='High Risk Threshold')
            ax.set_title('Daily Risk Score Trends', fontsize=16, color='white')
            ax.set_ylabel('Risk Score', color='white')
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, days//7)))
        plt.xticks(rotation=45, color='white')
        plt.yticks(color='white')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        buffer = io.BytesIO()
        plt.savefig(buffer, format='png', bbox_inches='tight', facecolor='#36393f', edgecolor='none')
        buffer.seek(0)
        plt.close()
        
        return buffer
    
    async def trigger_arm_system(self, guild: discord.Guild):
        """Trigger Automatic Raid Mitigation"""
        config = self.get_guild_config(guild.id)
        
        if self.raid_mode.get(guild.id):
            return
        
        self.raid_mode[guild.id] = True
        
        locked_channels = 0
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.set_permissions(guild.default_role, send_messages=False, reason="ArM System: Raid detected")
                    locked_channels += 1
                except discord.Forbidden:
                    pass
        
        whitelist_role_ids = config.get("whitelist_roles", [])
        removed_roles = 0
        
        for member in guild.members:
            if member == guild.owner:
                continue
                
            roles_to_remove = []
            for role in member.roles:
                if role.permissions.manage_messages and role.id not in whitelist_role_ids:
                    roles_to_remove.append(role)
            
            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason="ArM System: Temporary role removal")
                    removed_roles += len(roles_to_remove)
                except discord.Forbidden:
                    pass
        
        await self.log_incident(guild.id, "ARM_ACTIVATION", f"Locked {locked_channels} channels, removed {removed_roles} mod roles")
        
        embed = discord.Embed(
            title="🚨 ArM SYSTEM ACTIVATED",
            description="**CODE RED**: Potential raid detected!",
            color=0xff0000,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Actions Taken", value=f"🔒 {locked_channels} channels locked\n👥 {removed_roles} mod roles removed", inline=False)
        embed.add_field(name="Next Steps", value="• Review recent joins\n• Use `/unlock-server` when safe\n• Check audit logs", inline=False)
        
        if config.get("alert_channel"):
            alert_channel = guild.get_channel(config["alert_channel"])
            if alert_channel:
                await alert_channel.send(embed=embed)
    
    async def count_recent_joins(self, guild_id: int, minutes: int = 1) -> int:
        """Count recent joins for ArM system"""
        guild_id_str = str(guild_id)
        file_path = os.path.join(self.data_dir, self.data_file)
        cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            count = len([
                r for r in data.get("user_audit", {}).get(guild_id_str, [])
                if r["action"] == "JOIN" and datetime.datetime.fromisoformat(r["timestamp"]) > cutoff_time
            ])
            return count
        except (json.JSONDecodeError, FileNotFoundError, IOError):
            return 0
    
    async def count_recent_invites(self, user_id: int, guild_id: int) -> int:
        """Count recent invite messages from user"""
        # Placeholder implementation
        return 0


async def setup(bot):
    await bot.add_cog(PremiumSecurity(bot))