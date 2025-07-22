import discord
import re
import random
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("bot.team_detection")

# Team-related keywords that might appear in role names
TEAM_KEYWORDS = [
    "team", "squad", "club", "franchise", "gaming", "esports", "roster", 
    "crew", "outfit", "gang", "alliance", "legion", "raiders",
    "knights", "warriors", "tigers", "lions", "eagles", "hawks", "falcons",
    "dragons", "griffins", "phoenix", "sharks", "wolves", "panthers", "bears",
    "bulls", "stallions", "mustangs", "raptors", "vipers", "cobras", "saints",
    "giants", "titans", "gladiators", "spartans", "pirates", "vikings", "ninjas",
    "bandits", "elite", "fc", "united", "city", "athletic", "athletics", "sports",
    "arsenal", "royal", "kings", "queens", "imperial", "dynasty", "empire"
]

# Common sports team name patterns
TEAM_PATTERNS = [
    r"\b[A-Z][a-z]+ (FC|United|City|Athletic|Wanderers|Rovers|Rangers|Town|County)\b",
    r"\b(Team|Club|Gaming|Esports|Squad) [A-Z][a-z]+\b",
    r"\bThe [A-Z][a-z]+ (Team|Squad|Club|Gaming)\b",
    r"\b[A-Z][a-z]+ (Tigers|Lions|Eagles|Hawks|Falcons|Dragons|Sharks|Wolves|Panthers|Bears)\b",
    r"\b[A-Z][a-z]+ (Bulls|Stallions|Mustangs|Raptors|Vipers|Cobras|Saints|Giants|Titans)\b",
    r"\b[A-Z][a-z]+ (Gladiators|Spartans|Pirates|Vikings|Ninjas|Bandits|Elite)\b",
    r"\b[A-Z][a-z]* [A-Z][a-z]* (Athletics|Sports|Team)\b"
]

# Role names that shouldn't be considered teams
NON_TEAM_KEYWORDS = [
    "admin", "moderator", "mod", "staff", "developer", "owner", "manager",
    "helper", "support", "bot", "muted", "banned", "timeout", "new", "member",
    "everyone", "here", "verified", "unverified", "roles", "color", "colour"
]

def detect_team_roles(guild: discord.Guild) -> List[discord.Role]:
    """Detect potential team roles in a guild based on name patterns"""
    potential_team_roles = []
    
    for role in guild.roles:
        if role.name == "@everyone":
            continue
            
        # Skip roles that match non-team keywords
        if any(keyword.lower() in role.name.lower() for keyword in NON_TEAM_KEYWORDS):
            continue
            
        # Check if the role matches any team keyword
        if any(keyword.lower() in role.name.lower() for keyword in TEAM_KEYWORDS):
            potential_team_roles.append(role)
            continue
            
        # Check if the role matches any team pattern
        if any(re.search(pattern, role.name, re.IGNORECASE) for pattern in TEAM_PATTERNS):
            potential_team_roles.append(role)
            continue
            
        # Check for roles with colors (often team roles)
        if role.color != discord.Color.default() and len(role.name) > 3:
            # Only add colored roles with 3+ members as potential teams
            member_count = sum(1 for member in guild.members if role in member.roles)
            if member_count >= 3:
                potential_team_roles.append(role)
    
    # Sort by position (highest first)
    potential_team_roles.sort(key=lambda r: r.position, reverse=True)
    
    return potential_team_roles

def detect_team_channels(guild: discord.Guild, team_roles: List[discord.Role]) -> Dict[str, List[discord.TextChannel]]:
    """Detect text channels that might be associated with detected team roles"""
    team_channels = {}
    
    for role in team_roles:
        team_name = role.name
        team_channels[team_name] = []
        
        # Look for channels that contain the team name
        for channel in guild.text_channels:
            if team_name.lower() in channel.name.lower():
                team_channels[team_name].append(channel)
                
    return team_channels

def generate_team_name_from_role(role: discord.Role) -> str:
    """Generate a clean team name from a role"""
    # Remove common prefixes/suffixes
    name = role.name
    name = re.sub(r"\b(Team|Club|Gaming|Esports|Squad)\s+", "", name)
    name = re.sub(r"\s+(Team|Club|Gaming|Esports|Squad)\b", "", name)
    
    # Clean up any extra whitespace
    name = re.sub(r"\s+", " ", name).strip()
    
    return name

def detect_related_roles(guild: discord.Guild, team_role: discord.Role) -> Dict[str, Optional[discord.Role]]:
    """Detect roles that might be related to a team (GM, HC, etc.)"""
    related_roles = {
        "GM": None,
        "HC": None,
        "AC": None,
        "FO": None
    }
    
    team_name = generate_team_name_from_role(team_role)
    
    for role in guild.roles:
        role_name = role.name.lower()
        
        # Look for GM roles
        if ("gm" in role_name or "general manager" in role_name) and team_name.lower() in role_name:
            related_roles["GM"] = role
            
        # Look for HC roles
        if ("hc" in role_name or "head coach" in role_name) and team_name.lower() in role_name:
            related_roles["HC"] = role
            
        # Look for AC roles
        if ("ac" in role_name or "assistant coach" in role_name) and team_name.lower() in role_name:
            related_roles["AC"] = role
            
        # Look for FO roles
        if ("fo" in role_name or "front office" in role_name) and team_name.lower() in role_name:
            related_roles["FO"] = role
    
    return related_roles

def find_team_emoji(guild: discord.Guild, team_name: str) -> Optional[str]:
    """Try to find an emoji that matches the team name"""
    # Default emoji options
    default_emojis = ['🏆', '🏅', '🎮', '🎯', '🎲', '🎯', '🏁', '🏈', '⚽', '🏀', '⚾', '🏐', '🏉']
    
    # Look for custom emojis in the guild that match the team name
    for emoji in guild.emojis:
        if team_name.lower() in emoji.name.lower():
            return str(emoji)
    
    # If no custom emoji found, return a random default emoji
    return random.choice(default_emojis)

def detect_team_members(guild: discord.Guild, team_role: discord.Role) -> List[discord.Member]:
    """Get all members with the team role"""
    return [member for member in guild.members if team_role in member.roles]