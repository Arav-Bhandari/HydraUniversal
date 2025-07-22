import discord
import io
import csv
from discord import app_commands
from discord.ext import commands
from utils.permissions import can_use_command
from utils.config import get_server_config
from utils.logging import log_action
from utils.embeds import EmbedBuilder
import logging
import datetime

logger = logging.getLogger('bot.roster')

DEFAULT_ROSTER_CAP = 53
PLAYERS_PER_PAGE = 10

class RosterCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_team_data(self, guild_id, team_name_filter=None, for_autocomplete=False):
        """Get team data from the server configuration"""
        config = get_server_config(guild_id)
        team_roles_legacy = config.get("team_roles", {})
        team_data_new = config.get("team_data", {})
        permission_settings = config.get("permission_settings", {})
        
        fo_role_ids = [str(role_id) for role_id in permission_settings.get("fo_roles", [])]
        gm_role_ids = [str(role_id) for role_id in permission_settings.get("gm_roles", [])]
        hc_role_ids = [str(role_id) for role_id in permission_settings.get("hc_roles", [])]
        ac_role_ids = [str(role_id) for role_id in permission_settings.get("ac_roles", [])]
        
        logger.debug(f"Guild {guild_id}: team_roles_legacy keys: {list(team_roles_legacy.keys())}, "
                    f"team_data_new keys: {list(team_data_new.keys())}, "
                    f"fo_roles: {fo_role_ids}, gm_roles: {gm_role_ids}, "
                    f"hc_roles: {hc_role_ids}, ac_role_ids: {ac_role_ids}")
        
        all_team_names_processed = set()
        teams = {}
        
        for name, data_item in team_data_new.items():
            if for_autocomplete and name.lower() == "bye week":
                continue
            
            teams[name] = {
                "name": name,
                "role_id": str(data_item.get("role_id")) if data_item.get("role_id") else None,
                "emoji": data_item.get("emoji", "🏆"),
                "description": data_item.get("description", ""),
                "roster_cap": data_item.get("roster_cap", config.get("roster_cap", DEFAULT_ROSTER_CAP)),
                "players": {} if not for_autocomplete else None
            }
            all_team_names_processed.add(name)

        for name, role_id_legacy in team_roles_legacy.items():
            if name in all_team_names_processed:
                continue
            if for_autocomplete and name.lower() == "bye week":
                continue

            teams[name] = {
                "name": name,
                "role_id": str(role_id_legacy) if role_id_legacy else None,
                "emoji": "🏆",
                "description": "",
                "roster_cap": config.get("roster_cap", DEFAULT_ROSTER_CAP),
                "players": {} if not for_autocomplete else None
            }
            all_team_names_processed.add(name)
            
        if for_autocomplete:
            logger.debug(f"Returning {len(teams)} teams for autocomplete: {list(teams.keys())}")
            return teams

        guild = self.bot.get_guild(guild_id)
        if not guild:
            logger.error(f"Guild {guild_id} not found")
            return teams if not team_name_filter else {}

        for team_name_key, team_info_item in teams.items():
            if team_info_item["role_id"]:
                try:
                    role = guild.get_role(int(team_info_item["role_id"]))
                    if not role:
                        logger.warning(f"Role {team_info_item['role_id']} not found for team {team_name_key}")
                        continue
                    player_roles = {}
                    for member in guild.members:
                        if role in member.roles:
                            member_id_str = str(member.id)
                            player_roles[member_id_str] = {"role": "Player", "number": ""}
                            for member_role in member.roles:
                                member_role_id_str = str(member_role.id)
                                if member_role_id_str in fo_role_ids:
                                    player_roles[member_id_str]["role"] = "FO"
                                    break
                                elif member_role_id_str in gm_role_ids:
                                    player_roles[member_id_str]["role"] = "GM"
                                    break
                                elif member_role_id_str in hc_role_ids:
                                    player_roles[member_id_str]["role"] = "HC"
                                    break
                                elif member_role_id_str in ac_role_ids:
                                    player_roles[member_id_str]["role"] = "AC"
                                    break
                    team_info_item["players"] = player_roles
                    logger.debug(f"Team {team_name_key}: {len(player_roles)} players, "
                                f"roles: {[v['role'] for v in player_roles.values()]}")
                except ValueError:
                    logger.warning(f"Invalid role_id '{team_info_item['role_id']}' for team {team_name_key} in guild {guild_id}")

        if team_name_filter:
            filtered_teams = {name: info for name, info in teams.items() if name.lower() == team_name_filter.lower()}
            logger.debug(f"Filtered teams for '{team_name_filter}': {list(filtered_teams.keys())}")
            return filtered_teams

        logger.debug(f"Returning {len(teams)} teams for guild {guild_id}: {list(teams.keys())}")
        return teams

    def format_team_roster(self, team_details, players, guild):
        """Format team roster for display in embed with specified roles"""
        roster_text = ""
        staff_roles_order = {
            "FO": {"name": "Franchise Owner", "members": []},
            "GM": {"name": "General Manager", "members": []},
            "HC": {"name": "Head Coach", "members": []},
            "AC": {"name": "Assistant Coach", "members": []}
        }
        regular_players = []

        for player_id, player_data in players.items():
            member = guild.get_member(int(player_id)) if guild else None
            username = member.name if member else f"ID: {player_id}"
            formatted_player = f"<@{player_id}> `{username}`"
            player_role = player_data.get("role", "Player")
            if player_role in staff_roles_order:
                staff_roles_order[player_role]["members"].append(formatted_player)
            else:
                regular_players.append(formatted_player)

        for staff_role in staff_roles_order.values():
            if staff_role["members"]:
                roster_text += f"**{staff_role['name']}**\n"
                roster_text += "\n".join(f"• {p}" for p in staff_role["members"]) + "\n\n"
            else:
                roster_text += f"**{staff_role['name']}**\n• None\n\n"

        roster_text += "**Players**\n"
        roster_text += "\n".join(f"• {p}" for p in regular_players) if regular_players else "• None\n"
        
        logger.debug(f"Formatted roster for {team_details['name']}: {roster_text}")
        return roster_text

    def create_csv_file(self, team_name, players, guild):
        """Create a CSV file from team roster data"""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Discord ID", "Role", "Username", "Display Name"])
        for player_id, player_data in players.items():
            member = guild.get_member(int(player_id)) if guild else None
            username = member.name if member else "Unknown"
            display_name = member.display_name if member else "Unknown"
            role = player_data.get("role", "Player")
            writer.writerow([player_id, role, username, display_name])
        
        output.seek(0)
        logger.debug(f"Created CSV for team {team_name} with {len(players)} players")
        return discord.File(output, filename=f"{team_name}_roster.csv")

    async def team_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete team names for the roster command"""
        try:
            guild_id = interaction.guild.id
            teams = self.get_team_data(guild_id, for_autocomplete=True)
            
            choices = [
                app_commands.Choice(name=team_info['name'], value=team_info['name'])
                for team_id_key, team_info in teams.items()
                if current.lower() in team_info['name'].lower()
            ]
            
            choices.sort(key=lambda x: x.name)
            logger.debug(f"Autocomplete for '{current}': {len(choices)} choices")
            return choices[:25]
        except Exception as e:
            logger.error(f"Autocomplete error for 'roster': {e}", exc_info=True)
            return []

    @app_commands.command(name="roster", description="View a team's roster")
    @app_commands.describe(team="The team to view the roster for", export="Export roster as CSV")
    @app_commands.autocomplete(team=team_autocomplete)
    async def roster(self, interaction: discord.Interaction, team: str, export: bool = False):
        try:
            # Make the initial deferral ephemeral
            await interaction.response.defer(ephemeral=True)
            
            all_teams_data = self.get_team_data(interaction.guild.id)
            target_team_details = next(
                (t_details for t_id, t_details in all_teams_data.items() if t_details["name"].lower() == team.lower()),
                None
            )

            if not target_team_details:
                embed = EmbedBuilder.error("Team Not Found", f"Could not find team '{team}'.")
                logger.warning(f"Team '{team}' not found for guild {interaction.guild.id}")
                # Make the followup ephemeral
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            team_name = target_team_details["name"]
            players = target_team_details["players"]
            team_emoji = target_team_details.get("emoji", "🏆")
            roster_cap_value = target_team_details.get("roster_cap", DEFAULT_ROSTER_CAP)
            guild = interaction.guild
            
            # Create paginated view for roster
            view = RosterPaginationView(target_team_details, players, guild, PLAYERS_PER_PAGE, interaction.user.id)
            embed = await view.create_embed(0)
            
            if export:
                csv_file = self.create_csv_file(team_name, players, guild)
                # Make the followup ephemeral
                await interaction.followup.send(embed=embed, file=csv_file, view=view, ephemeral=True)
            else:
                # Make the followup ephemeral
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
            await log_action(
                guild=interaction.guild,
                command_name="ROSTER",
                user=interaction.user,
                action_type="VIEW",
                details=f"Viewed roster for {team_name} (Export: {export})"
            )
        except discord.errors.NotFound:
            logger.warning(f"Interaction expired for roster command (team: {team})")
        except Exception as e:
            logger.error(f"Error in roster command for team '{team}': {e}", exc_info=True)
            try:
                # Make the followup ephemeral
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Error", "An error occurred while processing the roster."), ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning("Could not send error followup due to expired interaction")

    @app_commands.command(name="teamlist", description="List all teams in the server")
    async def teamlist(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=False) # Keeping teamlist non-ephemeral as per prompt focus
            
            teams_data = self.get_team_data(interaction.guild.id, for_autocomplete=False)
            if not teams_data:
                embed = EmbedBuilder.error("No Teams", "No teams configured for this server.")
                logger.warning(f"No teams configured for guild {interaction.guild.id}")
                await interaction.followup.send(embed=embed)
                return
            
            team_list_display = [
                {
                    "id": team_id,
                    "name": team_info["name"],
                    "emoji": team_info["emoji"],
                    "player_count": len(team_info.get("players", {})),
                    "roster_cap": team_info.get("roster_cap", DEFAULT_ROSTER_CAP)
                }
                for team_id, team_info in teams_data.items()
            ]
            team_list_display.sort(key=lambda x: x['name'])
            
            logger.debug(f"Team list for guild {interaction.guild.id}: {len(team_list_display)} teams, "
                        f"details: {[f'{t['name']} ({t['player_count']}/{t['roster_cap']})' for t in team_list_display]}")
            
            teams_per_page = 10
            view = TeamListPaginationView(team_list_display, teams_per_page, interaction.user.id)
            embed = await view.create_embed(0)
            
            await interaction.followup.send(embed=embed, view=view)
            
            await log_action(
                guild=interaction.guild,
                command_name="TEAMLIST",
                user=interaction.user,
                action_type="VIEW",
                details="Viewed team list"
            )
        except discord.errors.NotFound:
            logger.warning("Interaction expired for teamlist command")
        except Exception as e:
            logger.error(f"Error in teamlist command: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Error", "An error occurred while listing teams.")
                )
            except discord.errors.NotFound:
                logger.warning("Could not send error followup due to expired interaction")

class RosterPaginationView(discord.ui.View):
    def __init__(self, team_details, players, guild, players_per_page, requesting_user_id):
        super().__init__(timeout=180)
        self.team_details = team_details
        self.players = players
        self.guild = guild
        self.players_per_page = players_per_page
        self.current_page = 0
        self.total_pages = (len(self.players) + self.players_per_page - 1) // self.players_per_page
        self.requesting_user_id = requesting_user_id
        self._update_button_states()

    def _update_button_states(self):
        self.back_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1
        if self.total_pages <= 1:
            self.back_button.disabled = True
            self.next_button.disabled = True

    async def create_embed(self, page_number):
        self.current_page = page_number
        start_idx = self.current_page * self.players_per_page
        end_idx = min(start_idx + self.players_per_page, len(self.players))
        
        embed = discord.Embed(
            title=f"{self.team_details['emoji']} {self.team_details['name']}",
            description=f"Player Count: {len(self.players)}/{self.team_details['roster_cap']}",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        
        # Set author with guild icon and name
        if self.guild.icon:
            embed.set_author(name=self.guild.name, icon_url=self.guild.icon.url)
        
        # Set thumbnail with team emoji or logo
        embed.set_thumbnail(url=f"https://via.placeholder.com/50?text={self.team_details['emoji']}" if self.team_details['emoji'] else None)
        
        if self.team_details.get("description"):
            embed.add_field(name="About", value=self.team_details["description"], inline=False)

        roster_text = self.format_team_roster_page(self.team_details, dict(list(self.players.items())[start_idx:end_idx]), self.guild)
        embed.add_field(name="Roster (Page {}/{})".format(self.current_page + 1, self.total_pages), value=roster_text, inline=False)
        embed.set_footer(text=f"Requested by {self.requesting_user_id} | Use /roster <team_name> to view details")
        
        logger.debug(f"Roster embed created for {self.team_details['name']} page {self.current_page + 1}: {roster_text}")
        return embed

    def format_team_roster_page(self, team_details, players, guild):
        """Format a page of the team roster for display in embed"""
        roster_text = ""
        staff_roles_order = {
            "FO": {"name": "Franchise Owner", "members": []},
            "GM": {"name": "General Manager", "members": []},
            "HC": {"name": "Head Coach", "members": []},
            "AC": {"name": "Assistant Coach", "members": []}
        }
        regular_players = []

        for player_id, player_data in players.items():
            member = guild.get_member(int(player_id)) if guild else None
            username = member.name if member else f"ID: {player_id}"
            formatted_player = f"<@{player_id}> `{username}`"
            player_role = player_data.get("role", "Player")
            if player_role in staff_roles_order:
                staff_roles_order[player_role]["members"].append(formatted_player)
            else:
                regular_players.append(formatted_player)

        for staff_role in staff_roles_order.values():
            if staff_role["members"]:
                roster_text += f"**{staff_role['name']}**\n"
                roster_text += "\n".join(f"• {p}" for p in staff_role["members"]) + "\n\n"
            else:
                roster_text += f"**{staff_role['name']}**\n• None\n\n"

        roster_text += "**Players**\n"
        roster_text += "\n".join(f"• {p}" for p in regular_players) if regular_players else "• None\n"
        
        return roster_text

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requesting_user_id:
            await interaction.response.send_message("You cannot control this pagination.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.grey, custom_id="roster_prev")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            embed = await self.create_embed(self.current_page)
            self._update_button_states()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.grey, custom_id="roster_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            embed = await self.create_embed(self.current_page)
            self._update_button_states()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

class TeamListPaginationView(discord.ui.View):
    def __init__(self, teams_list_data, teams_per_page, requesting_user_id):
        super().__init__(timeout=180)
        self.teams_list_data = teams_list_data
        self.teams_per_page = teams_per_page
        self.current_page = 0
        self.total_pages = (len(self.teams_list_data) + self.teams_per_page - 1) // self.teams_per_page
        self.requesting_user_id = requesting_user_id
        self._update_button_states()

    def _update_button_states(self):
        self.back_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1
        if self.total_pages <= 1:
            self.back_button.disabled = True
            self.next_button.disabled = True

    async def create_embed(self, page_number):
        self.current_page = page_number
        start_idx = self.current_page * self.teams_per_page
        end_idx = min(start_idx + self.teams_per_page, len(self.teams_list_data))
        
        embed = discord.Embed(
            title="📋 Team List",
            description=f"Page {self.current_page + 1}/{self.total_pages}",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        
        page_teams_text = "\n".join(
            f"{team['emoji']} **{team['name']}** - {team['player_count']}/{team['roster_cap']} players"
            for team in self.teams_list_data[start_idx:end_idx]
        ) or "No teams on this page."
        
        embed.add_field(name="Teams", value=page_teams_text, inline=False)
        embed.set_footer(text=f"Requested by {self.requesting_user_id} | Use /roster <team_name> to view details")
        logger.debug(f"Team list embed created for page {self.current_page + 1}: {page_teams_text}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requesting_user_id:
            await interaction.response.send_message("You cannot control this pagination.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.grey, custom_id="teamlist_prev")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            embed = await self.create_embed(self.current_page)
            self._update_button_states()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.grey, custom_id="teamlist_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            embed = await self.create_embed(self.current_page)
            self._update_button_states()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

async def setup(bot):
    await bot.add_cog(RosterCommands(bot))
    logger.info("RosterCommands Cog loaded.")