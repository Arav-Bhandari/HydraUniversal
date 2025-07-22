
import discord
import random
from datetime import datetime

class EmbedBuilder:
    """Helper class to build Discord embeds with consistent styling."""
    
    # Brand colors
    COLORS = {
        'success': 0x43B581,  # Green
        'error': 0xF04747,    # Red
        'warning': 0xFAA61A,  # Orange
        'info': 0x7289DA,     # Blurple
        'default': 0x2F3136,  # Dark
        'betting': 0xE91E63,  # Pink
        'ban': 0xFF0000,      # Bright Red
        'purple': 0x9B59B6,   # Purple
        'blue': 0x3498DB,     # Blue
        'cyan': 0x1ABC9C      # Cyan
    }

    # Emoji mapping
    EMOJI = {
        'success': '✅',
        'error': '❌',
        'warning': '⚠️',
        'info': 'ℹ️',
        'roster': '📋',
        'game': '🏈',
        'stats': '📊',
        'contract': '📝',
        'trade': '🔄',
        'staff': '👔',
        'team': '🏆',
        'settings': '⚙️',
        'ban': '🚫',
        'card': '🃏',
        'dice': '🎲',
        'money': '💰',
        'trophy': '🏆',
        'celebration': '🎉',
        'eyes': '👀',
        'roulette': '🎡',
        'blackjack': '♠️'
    }
    

    THUMBNAILS = {
        'success': 'https://upload.wikimedia.org/wikipedia/commons/thumb/7/73/Green_check_mark.svg/2048px-Green_check_mark.svg.png',
        'error': 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c1/Red_X.svg/2048px-Red_X.svg.png',
        'warning': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a2/Ambox_warning_yellow.svg/1024px-Ambox_warning_yellow.svg.png',
        'info': 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b8/Information_icon.svg/2048px-Information_icon.svg.png',
        'betting': 'https://i.imgur.com/K0wS0cR.png',  # A known-stable public Imgur link
        'ban': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Gavel_icon.svg/1024px-Gavel_icon.svg.png'
    }
    
    @staticmethod
    def _add_decorative_line(embed, color=None):
        """Add a decorative line to the embed for visual enhancement."""
        if not color:
            color = random.choice([EmbedBuilder.COLORS['cyan'], 
                                  EmbedBuilder.COLORS['purple'], 
                                  EmbedBuilder.COLORS['blue']])
        
        embed.add_field(
            name="‎",  # Zero-width space
            value=f"[⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯](https://discord.com)",
            inline=False
        )
        return embed
    
    @staticmethod
    def success(title, description=None, thumbnail=True):
        """Create a success embed with enhanced styling."""
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['success']} {title}",
            description=description,
            color=discord.Color(EmbedBuilder.COLORS['success']),
            timestamp=datetime.now()
        )
        if thumbnail:
            embed.set_thumbnail(url=EmbedBuilder.THUMBNAILS['success'])
        
        embed.set_footer(text="Hydra League Bot • Success", 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        return embed
    
    @staticmethod
    def error(title, description=None, thumbnail=True):
        """Create an error embed with enhanced styling."""
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['error']} {title}",
            description=description,
            color=discord.Color(EmbedBuilder.COLORS['error']),
            timestamp=datetime.now()
        )
        if thumbnail:
            embed.set_thumbnail(url=EmbedBuilder.THUMBNAILS['error'])
            
        embed.set_footer(text="Hydra League Bot • Error", 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        return embed
    
    @staticmethod
    def warning(title, description=None, thumbnail=True):
        """Create a warning embed with enhanced styling."""
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['warning']} {title}",
            description=description,
            color=discord.Color(EmbedBuilder.COLORS['warning']),
            timestamp=datetime.now()
        )
        if thumbnail:
            embed.set_thumbnail(url=EmbedBuilder.THUMBNAILS['warning'])
            
        embed.set_footer(text="Hydra League Bot • Warning", 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        return embed
    
    @staticmethod
    def info(title, description=None, thumbnail=True):
        """Create an info embed with enhanced styling."""
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['info']} {title}",
            description=description,
            color=discord.Color(EmbedBuilder.COLORS['info']),
            timestamp=datetime.now()
        )
        if thumbnail:
            embed.set_thumbnail(url=EmbedBuilder.THUMBNAILS['info'])
            
        embed.set_footer(text="Hydra League Bot • Information", 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        return embed
    
    @staticmethod
    def confirmation(title, description=None, thumbnail=True):
        """Create a confirmation embed with enhanced styling."""
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['warning']} {title}",
            description=description,
            color=discord.Color(EmbedBuilder.COLORS['warning']),
            timestamp=datetime.now()
        )
        if thumbnail:
            embed.set_thumbnail(url=EmbedBuilder.THUMBNAILS['warning'])
            
        embed.set_footer(text="Hydra League Bot • Awaiting Confirmation", 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        return embed
    
    @staticmethod
    def team(title, description=None, team_color=None):
        """Create a team-branded embed."""
        color = team_color if team_color else EmbedBuilder.COLORS['default']
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['team']} {title}",
            description=description,
            color=discord.Color(color),
            timestamp=datetime.now()
        )
        embed.set_footer(text="Hydra League Bot • Team Management")
        return embed
    
    @staticmethod
    def roster(team_name, members, team_color=None):
        """Create a roster embed."""
        color = team_color if team_color else EmbedBuilder.COLORS['default']
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['roster']} {team_name} Roster",
            color=discord.Color(color),
            timestamp=datetime.now()
        )
        
        # Staff sections with emojis
        sections = {
            f"{EmbedBuilder.EMOJI['staff']} Franchise Owner": [],
            f"{EmbedBuilder.EMOJI['staff']} General Manager": [],
            f"{EmbedBuilder.EMOJI['staff']} Head Coach": [],
            f"{EmbedBuilder.EMOJI['staff']} Assistant Coach": [],
            f"{EmbedBuilder.EMOJI['team']} Players": []
        }
        
        for member in members:
            if "GM" in member["role"]:
                sections[f"{EmbedBuilder.EMOJI['staff']} General Manager"].append(member)
            elif "HC" in member["role"]:
                sections[f"{EmbedBuilder.EMOJI['staff']} Head Coach"].append(member)
            elif "AC" in member["role"]:
                sections[f"{EmbedBuilder.EMOJI['staff']} Assistant Coach"].append(member)
            elif "FO" in member["role"]:
                sections[f"{EmbedBuilder.EMOJI['staff']} Franchise Owner"].append(member)
            else:
                sections[f"{EmbedBuilder.EMOJI['team']} Players"].append(member)
        
        for title, members in sections.items():
            if members:
                member_list = "\n".join([f"• {m['mention']} (`{m['name']}`)" for m in members])
                embed.add_field(name=title, value=member_list or "*None*", inline=False)
        
        embed.set_footer(text=f"Hydra League Bot • {team_name}")
        return embed
    
    @staticmethod
    def contract(title, player, team, details, status="Pending"):
        """Create a contract embed."""
        status_colors = {
            "Pending": EmbedBuilder.COLORS['warning'],
            "Accepted": EmbedBuilder.COLORS['success'],
            "Denied": EmbedBuilder.COLORS['error'],
            "Expired": EmbedBuilder.COLORS['default']
        }
        
        status_emoji = {
            "Pending": "⏳",
            "Accepted": "✅",
            "Denied": "❌",
            "Expired": "⌛"
        }
        
        color = status_colors.get(status, EmbedBuilder.COLORS['default'])
        emoji = status_emoji.get(status, "📄")
        
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['contract']} {title}",
            description=f"Contract details for {player} with {team}",
            color=discord.Color(color),
            timestamp=datetime.now()
        )
        
        for key, value in details.items():
            embed.add_field(name=key, value=value, inline=True)
        
        embed.add_field(name="Status", value=f"{emoji} {status}", inline=False)
        embed.set_footer(text="Hydra League Bot • Contract Management")
        return embed
    
    @staticmethod
    def game(title, team1, team2, date_time, additional_info=None, thumbnail=None):
        """Create a game schedule embed with enhanced styling."""
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['game']} {title}",
            description=f"**{team1}** vs **{team2}**",
            color=discord.Color(EmbedBuilder.COLORS['info']),
            timestamp=datetime.now()
        )
        
        # Add a decorative separator - safely handling None description
        if embed.description:
            embed.description += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        else:
            embed.description = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        embed.add_field(name="📅 Date & Time", value=date_time, inline=False)
        
        if additional_info:
            for key, value in additional_info.items():
                embed.add_field(name=key, value=value, inline=True)
        
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        
        embed.set_footer(text="Hydra League Bot • Game Schedule", 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        return embed
    
    @staticmethod
    def stats(title, player, stats, thumbnail=None):
        """Create a stats embed with enhanced styling."""
        embed = discord.Embed(
            title=f"{EmbedBuilder.EMOJI['stats']} {title}",
            description=f"Statistics for {player}",
            color=discord.Color(EmbedBuilder.COLORS['info']),
            timestamp=datetime.now()
        )
        
        # Add a decorative separator
        embed.description += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        # Group stats in sections if there are many
        if len(stats) > 6:
            # First section: primary stats
            primary_stats = {}
            secondary_stats = {}
            
            # Split stats into two sections
            for i, (key, value) in enumerate(stats.items()):
                if i < len(stats) // 2:
                    primary_stats[key] = value
                else:
                    secondary_stats[key] = value
            
            # Add primary stats
            for key, value in primary_stats.items():
                embed.add_field(name=key, value=value, inline=True)
            
            # Add separator between sections
            embed.add_field(name="\u200b", value="\u200b", inline=False)
            
            # Add secondary stats
            for key, value in secondary_stats.items():
                embed.add_field(name=key, value=value, inline=True)
        else:
            # Simple layout for fewer stats
            for key, value in stats.items():
                embed.add_field(name=key, value=value, inline=True)
        
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        
        embed.set_footer(text="Hydra League Bot • Player Statistics", 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        return embed
    
    @staticmethod
    def reminder(title, time_text, team1, team2, game_time, stream_url=None, color=None, type="channel"):
        """Create a game reminder embed with enhanced styling."""
        
        if not color:
            color = EmbedBuilder.COLORS['gold'] if type == "channel" else EmbedBuilder.COLORS['blue']
        
        # Different styling based on reminder type
        if type == "channel":
            description = f"**Game starts in {time_text}!**\n{game_time}"
        elif type == "player":
            description = f"**Your game starts in {time_text}!**\n{game_time}"
        elif type == "referee":
            description = f"**You are assigned as referee for a game starting in {time_text}!**\n{game_time}"
        elif type == "streamer":
            description = f"**You are assigned to stream a game starting in {time_text}!**\n{game_time}"
        else:
            description = f"**Game starts in {time_text}!**\n{game_time}"
        
        embed = discord.Embed(
            title=f"🏈 {title}: {team1} vs {team2}",
            description=description,
            color=discord.Color(color),
            timestamp=datetime.now()
        )
        
        # Add a decorative separator
        embed.description += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        # Add stream link if available
        if stream_url:
            embed.add_field(
                name="📺 Stream",
                value=f"[Watch Live]({stream_url})",
                inline=False
            )
        
        # Set thumbnail based on reminder type
        thumbnails = {
            "channel": "https://i.imgur.com/q7KBj0g.png",  # Football field
            "player": "https://i.imgur.com/3xYAafX.png",   # Player helmet
            "referee": "https://i.imgur.com/BpKJkM1.png",  # Referee whistle
            "streamer": "https://i.imgur.com/AegcELd.png"  # Streaming camera
        }
        
        if type in thumbnails:
            embed.set_thumbnail(url=thumbnails[type])
        
        # Custom footer based on reminder type
        footers = {
            "channel": "Hydra League Bot • Game Reminder",
            "player": "Hydra League Bot • Player Reminder",
            "referee": "Hydra League Bot • Referee Assignment",
            "streamer": "Hydra League Bot • Streamer Assignment"
        }
        
        embed.set_footer(text=footers.get(type, "Hydra League Bot • Game Reminder"), 
                         icon_url="https://i.imgur.com/uZIlRnK.png")
        return embed
