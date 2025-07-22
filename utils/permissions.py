import logging
import discord
from utils.config import get_server_config

logger = logging.getLogger("bot.permissions")

async def is_admin(member: discord.Member):
    """Check if the user is an administrator or server owner."""
    if member.guild.owner_id == member.id:
        return True
    return member.guild_permissions.administrator

async def has_management_role(member: discord.Member):
    """Check if the user has the Management role."""
    config = get_server_config(member.guild.id)
    
    # Check if management roles are configured
    if "permission_settings" not in config or "management_roles" not in config["permission_settings"]:
        # Check legacy management_role setting
        if "permission_settings" in config and "management_role" in config["permission_settings"]:
            management_role_id = config["permission_settings"]["management_role"]
            for role in member.roles:
                if str(role.id) == management_role_id:
                    return True
        # Fall back to admin check if no roles configured
        return await is_admin(member)
    
    management_role_ids = config["permission_settings"]["management_roles"]
    
    # Check if user has any of the management roles
    for role in member.roles:
        if str(role.id) in management_role_ids:
            return True
    
    # Allow admins
    return await is_admin(member)

async def has_stat_manager_role(member: discord.Member):
    """Check if the user has the Stat Manager role."""
    config = get_server_config(member.guild.id)
    
    # Check if stat manager role is configured
    if "permission_settings" not in config or "stat_manager_role" not in config["permission_settings"]:
        # Fall back to admin check if role not configured
        return await is_admin(member)
    
    stat_manager_role_id = config["permission_settings"]["stat_manager_role"]
    
    # Check if user has the role
    for role in member.roles:
        if str(role.id) == stat_manager_role_id:
            return True
    
    # Allow admins
    return await is_admin(member)

async def has_statistician_role(member: discord.Member):
    """Check if the user has the Statistician role."""
    config = get_server_config(member.guild.id)
    
    # Check if statistician roles are configured
    if "permission_settings" not in config or "statistician_roles" not in config["permission_settings"]:
        # Fall back to admin check if roles not configured
        return await is_admin(member)
    
    statistician_role_ids = config["permission_settings"]["statistician_roles"]
    
    # Check if user has any of the statistician roles
    for role in member.roles:
        if str(role.id) in statistician_role_ids:
            return True
    
    # Allow admins
    return await is_admin(member)

async def has_streamer_role(member: discord.Member):
    """Check if the user has the Streamer role."""
    config = get_server_config(member.guild.id)
    
    # Check if streamer role is configured
    if "permission_settings" not in config or "streamer_role" not in config["permission_settings"]:
        # Fall back to admin check if role not configured
        return await is_admin(member)
    
    streamer_role_id = config["permission_settings"]["streamer_role"]
    
    # Check if user has the role
    for role in member.roles:
        if str(role.id) == streamer_role_id:
            return True
    
    # Allow admins
    return await is_admin(member)

async def has_referee_role(member: discord.Member):
    """Check if the user has the Referee role."""
    config = get_server_config(member.guild.id)
    
    # Check if referee role is configured
    if "permission_settings" not in config or "referee_role" not in config["permission_settings"]:
        # Fall back to admin check if role not configured
        return await is_admin(member)
    
    referee_role_id = config["permission_settings"]["referee_role"]
    
    # Check if user has the role
    for role in member.roles:
        if str(role.id) == referee_role_id:
            return True
    
    # Allow admins
    return await is_admin(member)

async def has_moderator_role(member: discord.Member):
    """Check if the user has the Moderator role."""
    config = get_server_config(member.guild.id)
    
    # Check if moderator role is configured
    if "permission_settings" not in config or "moderator_role" not in config["permission_settings"]:
        # Fall back to admin check if role not configured
        return await is_admin(member)
    
    moderator_role_id = config["permission_settings"]["moderator_role"]
    
    # Check if user has the role
    for role in member.roles:
        if str(role.id) == moderator_role_id:
            return True
    
    # Allow admins
    return await is_admin(member)

async def has_franchise_owner_role(member: discord.Member):
    """Check if the user has the Franchise Owner role."""
    config = get_server_config(member.guild.id)
    
    # Check if franchise owner role is configured
    if "permission_settings" not in config or "franchise_owner_role" not in config["permission_settings"]:
        # Fall back to admin check if role not configured
        return await is_admin(member)
    
    franchise_owner_role_id = config["permission_settings"]["franchise_owner_role"]
    
    # Check if user has the role
    for role in member.roles:
        if str(role.id) == franchise_owner_role_id:
            return True
    
    # Allow admins
    return await is_admin(member)

async def has_team_staff_role(member: discord.Member, role_type):
    """Check if the user has a specific team staff role (GM/HC/AC)."""
    config = get_server_config(member.guild.id)
    
    # Check if role is configured
    role_setting_key = f"{role_type.lower()}_role"
    if "permission_settings" not in config or role_setting_key not in config["permission_settings"]:
        # Fall back to admin check if role not configured
        return await is_admin(member)
    
    role_id = config["permission_settings"][role_setting_key]
    
    # Check if user has the role
    for role in member.roles:
        if str(role.id) == role_id:
            return True
    
    # Allow franchise owners for team staff roles
    if await has_franchise_owner_role(member):
        return True
    
    # Allow admins
    return await is_admin(member)

async def can_use_command(member: discord.Member, command_name: str):
    """Check if the user can use the specified command."""
    config = get_server_config(member.guild.id)
    
    # Check if command is enabled
    if "enabled_commands" in config and command_name in config["enabled_commands"]:
        if not config["enabled_commands"][command_name]:
            return False
    
    # Check specific permission settings
    if "permission_settings" in config and "command_permissions" in config["permission_settings"]:
        command_perms = config["permission_settings"].get("command_permissions", {})
        
        if command_name in command_perms:
            allowed_roles = command_perms[command_name]
            
            # Check if user has any of the allowed roles
            member_role_ids = [str(role.id) for role in member.roles]
            for role_id in allowed_roles:
                if role_id in member_role_ids:
                    return True
            
            # If specific roles are set but user doesn't have any of them
            return True
    return True

def get_team_role(member: discord.Member):
    """Get the team role of a member."""
    config = get_server_config(member.guild.id)
    
    # Check if team roles are configured
    if "team_data" not in config:
        return None
    
    team_roles = config["team_data"]
    member_role_ids = [str(role.id) for role in member.roles]
    
    # Find matching team role
    for team_name, team_info in team_roles.items():
        role_id = team_info["role_id"]
        if role_id in member_role_ids:
            return team_name
    
    return None

async def detect_team(member: discord.Member):
    """Get the team name associated with a member's team role for use in commands like /offer and /sign."""
    config = get_server_config(member.guild.id)
    
    # Check if team roles are configured
    if not config or "team_data" not in config:
        logger.warning(f"No team_data found in config for guild {member.guild.id}")
        return None
    
    team_data = config["team_data"]
    member_role_ids = [str(role.id) for role in member.roles]
    
    detected_teams = []
    if isinstance(team_data, dict):
        # Handles structures like:
        # FormatCurrent: {'TeamA': {'role_id': 'role1', ...}, ...}
        # Format1:       {'TeamA': 'role1', ...}
        for team_name, team_info_value in team_data.items():
            role_id = None
            if isinstance(team_info_value, dict) and "role_id" in team_info_value: # FormatCurrent
                try:
                    role_id = str(team_info_value["role_id"])
                except KeyError:
                    logger.error(f"Invalid team_data structure (dict entry missing 'role_id') for team {team_name} in guild {member.guild.id}")
                    continue
            elif isinstance(team_info_value, str): # Format1
                role_id = str(team_info_value)
            else:
                logger.warning(f"Skipping invalid team_data entry for team '{team_name}' (type: {type(team_info_value)}) in guild {member.guild.id}")
                continue

            if role_id and role_id in member_role_ids:
                detected_teams.append(team_name)

    elif isinstance(team_data, list):
        # Handles Format2: [{'name': 'TeamA', 'role_id': 'role1'}, ...]
        for team_entry in team_data:
            if isinstance(team_entry, dict) and "name" in team_entry and "role_id" in team_entry:
                team_name = team_entry["name"]
                try:
                    role_id = str(team_entry["role_id"])
                    if role_id in member_role_ids:
                        detected_teams.append(team_name)
                except KeyError: # Should not happen if "role_id" in team_entry check passed, but good practice
                    logger.error(f"Invalid team_data structure (list entry missing 'role_id') for team {team_name} in guild {member.guild.id}")
                    continue
            else:
                logger.warning(f"Skipping invalid team entry in list (entry: {team_entry}) in guild {member.guild.id}")
    else:
        logger.error(f"team_data for guild {member.guild.id} is neither a dict nor a list: {type(team_data)}")
        return None

    if not detected_teams:
        logger.debug(f"No team role found for member {member.id} in guild {member.guild.id}")
        return None
    if len(detected_teams) == 1:
        logger.debug(f"Detected team {detected_teams[0]} for member {member.id} in guild {member.guild.id}")
        return detected_teams[0]

    # Multiple teams detected
    logger.warning(f"Multiple teams ({', '.join(detected_teams)}) detected for member {member.id} in guild {member.guild.id}. Returning None.")
    return None

def get_position(member: discord.Member):
    """Get the position of a member."""
    roles = [role.name for role in member.roles]
    
    # Common position keywords
    positions = {
        "GM": ["GM", "General Manager"],
        "HC": ["HC", "Head Coach"],
        "AC": ["AC", "Assistant Coach"],
        "FO": ["FO", "Front Office"],
        "Player": ["QB", "WR", "RB", "TE", "OL", "DL", "LB", "CB", "S", "K", "P"]
    }
    
    for role in roles:
        for position, keywords in positions.items():
            for keyword in keywords:
                if keyword in role:
                    return position
    
    return None