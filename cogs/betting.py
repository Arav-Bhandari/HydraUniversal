import discord
import json
import logging
import random
import asyncio
from datetime import datetime, timedelta
from discord import app_commands, ui
from discord.ext import commands

# Assuming these utils exist and are correctly implemented
from utils.permissions import can_use_command
from utils.embeds import EmbedBuilder

logger = logging.getLogger('bot.betting')

# File to store user balances
BALANCES_FILE = "data/balances.json"
# Default starting balance for new users
DEFAULT_BALANCE = 1000
# Daily reward amount
DAILY_REWARD = 100
# VIP users that get infinite money (use strings for user IDs)
VIP_USERS = {
    "1099798391535439913", # Example User ID 1
    "1191091808252461146", # Example User ID 2
    "1311751109492342784", # Example User ID 3
    "959593825117040670",  # Example User ID 4
}
# Cooldown for daily command (in seconds)
DAILY_COOLDOWN = 86400  # 24 hours
# VIP balance (effectively infinite)
VIP_BALANCE = float('inf') # Use float('inf') for a true infinite representation

# Lock for thread-safe balance operations
balance_lock = asyncio.Lock()

async def _load_balances_blocking():
    """Blocking function to load balances. Intended to be run in an executor."""
    try:
        with open(BALANCES_FILE, 'r') as f:
            data = json.load(f)
        
        if not isinstance(data, dict):
            logger.warning("Invalid balances.json format. Initializing empty balances.")
            return {}
        
        # Check if data is in old guild-based format
        # Assuming old format had keys as guild_ids (strings/ints) and values were user data dicts
        # This migration assumes user_id as key inside the guild data
        if any(isinstance(k, str) and k.isdigit() and isinstance(data[k], dict) for k in data):
            logger.info("Detected old guild-based balances.json, migrating to user-based format")
            new_balances = {}
            
            for guild_id, users_in_guild in data.items():
                if not isinstance(users_in_guild, dict):
                    logger.warning(f"Skipping non-dict value for guild {guild_id} during migration.")
                    continue
                    
                for user_id_str, user_data in users_in_guild.items():
                    if isinstance(user_data, dict):
                        if "balance" in user_data:
                            new_balances[user_id_str] = {
                                "balance": user_data.get("balance", DEFAULT_BALANCE),
                                "last_daily": user_data.get("last_daily", 0)
                            }
                        else: # Handle case where user data dict exists but has no 'balance' key
                            logger.warning(f"User data for {user_id_str} in guild {guild_id} lacks 'balance'. Defaulting.")
                            new_balances[user_id_str] = {"balance": DEFAULT_BALANCE, "last_daily": 0}
                    elif isinstance(user_data, (int, float)): # Older format might have just balance value
                        new_balances[user_id_str] = {
                            "balance": user_data,
                            "last_daily": 0
                        }
                    else:
                        logger.warning(f"Skipping invalid user data for user {user_id_str} in guild {guild_id}: {user_data}")
                        continue
            
            await _save_balances_blocking(new_balances) # Save migrated data atomically
            logger.info("Migration complete")
            return new_balances
        
        # If not the old format, assume it's the new user-based format directly
        return data
    except FileNotFoundError:
        logger.info("balances.json not found. Initializing empty balances.")
        return {}
    except json.JSONDecodeError:
        logger.warning("Failed to decode balances.json. Corrupted file? Initializing empty balances.")
        return {}
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading balances.json: {e}")
        return {}

async def _save_balances_blocking(balances):
    """Blocking function to save balances. Intended to be run in an executor."""
    try:
        with open(BALANCES_FILE, 'w') as f:
            json.dump(balances, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save balances.json: {e}")

async def load_balances_safe():
    """Safely load user balances, handling file errors and migrations asynchronously."""
    # Using to_thread to run the blocking I/O in a separate thread
    return await asyncio.to_thread(_load_balances_blocking)

async def save_balances_safe(balances):
    """Safely save user balances, ensuring atomicity with a lock and using async execution."""
    async with balance_lock:
        await asyncio.to_thread(_save_balances_blocking, balances)

async def get_user_balance(user_id):
    """Get a user's balance, returning VIP balance if applicable."""
    user_id_str = str(user_id)
    if user_id_str in VIP_USERS:
        logger.debug(f"User {user_id_str} is VIP, returning VIP balance: {VIP_BALANCE}")
        return VIP_BALANCE

    balances = await load_balances_safe()
    return balances.get(user_id_str, {}).get("balance", DEFAULT_BALANCE)

async def update_user_balance(user_id, amount_change):
    """Update a user's balance atomically, returning the new balance."""
    user_id_str = str(user_id)
    if user_id_str in VIP_USERS:
        logger.debug(f"VIP user {user_id_str} balance unchanged.")
        return VIP_BALANCE # VIP balance is effectively infinite and unaffected

    async with balance_lock:
        balances = await load_balances_safe()
        
        # Ensure user exists, initialize if not
        if user_id_str not in balances:
            balances[user_id_str] = {"balance": DEFAULT_BALANCE, "last_daily": 0}
        
        balances[user_id_str]["balance"] += amount_change
        logger.info(f"Updated balance for user {user_id_str}: {amount_change:+,}. New balance: {balances[user_id_str]['balance']:,}")
        
        await save_balances_safe(balances)
        
        return balances[user_id_str]["balance"]

class BettingSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.blackjack_games = {} # Store active blackjack games by 'guild_id_user_id'
        self.bot.loop.create_task(self.cleanup_stale_games())

    async def cleanup_stale_games(self):
        """Periodically clean up blackjack games that are no longer valid (e.g., message deleted)."""
        while True:
            now = datetime.now()
            for game_id in list(self.blackjack_games.keys()):
                game_info = self.blackjack_games.get(game_id)
                if game_info:
                    message = game_info.get("message")
                    # Check if game timed out or if message is no longer accessible
                    if (message and (now - game_info["start_time"]) > timedelta(minutes=15)): # Hard timeout for 15 mins
                         logger.info(f"Game {game_id} timed out (15 min inactivity).")
                         await self.end_blackjack_game(message, game_id, is_timeout=True)
                    elif message and not await self.is_message_valid(message):
                         logger.info(f"Cleaning up stale blackjack game {game_id} due to inaccessible message.")
                         del self.blackjack_games[game_id]
                else: # Game entry itself is stale or removed
                    del self.blackjack_games[game_id]
            await asyncio.sleep(3600) # Run cleanup task every hour

    async def is_message_valid(self, message):
        """Check if a discord message object is still valid (e.g., not deleted)."""
        if not message: return False
        try:
            await message.fetch()
            return True
        except discord.NotFound:
            return False
        except discord.HTTPException: # Catch other potential issues like network errors
            return False

    # --- Embeds ---
    def _get_default_embed_color(self):
        try:
            return EmbedBuilder.COLORS.get('betting', discord.Color.blue())
        except AttributeError:
            return discord.Color.blue()

    def _get_embed_emoji(self, name, default=''):
        try:
            return EmbedBuilder.EMOJI.get(name, default)
        except AttributeError:
            return default

    def _get_embed_thumbnail(self, name):
        try:
            return EmbedBuilder.THUMBNAILS.get(name, None)
        except AttributeError:
            return None

    # --- Balance Commands ---
    @app_commands.command(name="balance", description="Check your current betting balance")
    async def balance(self, interaction: discord.Interaction):
        user_id_str = str(interaction.user.id)
        balance = await get_user_balance(user_id_str)
        
        title = f"{self._get_embed_emoji('money', '💰')} Your Balance"
        description = f"You currently have **{balance:,}** credits."
        embed = discord.Embed(title=title, description=description, color=self._get_default_embed_color())
        embed.set_thumbnail(url=self._get_embed_thumbnail('betting'))
        embed.set_footer(text="Try /daily to collect your daily reward!")
        
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="daily", description="Collect your daily credits")
    async def daily(self, interaction: discord.Interaction):
        user_id_str = str(interaction.user.id)

        if user_id_str in VIP_USERS:
            embed = discord.Embed(title=f"{self._get_embed_emoji('star', '⭐')} Daily Reward", description="As a VIP, you have an infinite balance!", color=self._get_default_embed_color())
            embed.set_thumbnail(url=self._get_embed_thumbnail('vip'))
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        async with balance_lock: # Protect concurrent access to file for this operation
            balances = await load_balances_safe() # Load all balances first

            if user_id_str not in balances:
                balances[user_id_str] = {"balance": DEFAULT_BALANCE, "last_daily": 0}
            
            last_daily = balances[user_id_str].get("last_daily", 0) # Use .get for safety
            now = datetime.now().timestamp()
            
            if last_daily > 0 and now - last_daily < DAILY_COOLDOWN:
                next_claim_ts = last_daily + DAILY_COOLDOWN
                time_until_claim = datetime.fromtimestamp(next_claim_ts) - datetime.now()
                
                hours, remainder = divmod(int(time_until_claim.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                
                embed = discord.Embed(
                    title=f"{self._get_embed_emoji('clock', '⏳')} Daily Reward",
                    description=f"You've already claimed your daily reward. Try again in **{hours}h {minutes}m**.",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Award the daily reward
            balances[user_id_str]["balance"] += DAILY_REWARD
            balances[user_id_str]["last_daily"] = now
            await save_balances_safe(balances) # Save updated balances atomically
        
        # After file operation is complete, retrieve and display new balance
        new_balance = await get_user_balance(user_id_str)
        
        embed = discord.Embed(
            title=f"{self._get_embed_emoji('gift', '🎁')} Daily Reward",
            description=f"You've claimed your daily reward of **{DAILY_REWARD:,}** credits!",
            color=discord.Color.green()
        )
        embed.add_field(name="New Balance", value=f"**{new_balance:,}** credits", inline=False)
        embed.set_thumbnail(url=self._get_embed_thumbnail('daily'))
        
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # --- Blackjack Game ---
    @app_commands.command(name="blackjack", description="Play a game of blackjack")
    @app_commands.describe(bet="The amount to bet")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        if bet <= 0:
            embed = discord.Embed(title="Error", description="Your bet must be greater than 0.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        user_id_str = str(interaction.user.id)
        user_balance = await get_user_balance(user_id_str)

        if user_balance < bet:
            embed = discord.Embed(
                title="Error",
                description=f"You don't have enough credits. Your balance is **{user_balance:,}**.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        guild_id_str = str(interaction.guild.id)
        game_id = f"{guild_id_str}_{user_id_str}"
        
        if game_id in self.blackjack_games:
            embed = discord.Embed(title="Warning", description="You already have an active game. Please finish or cancel your current game first.", color=discord.Color.orange())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Initial game setup
        deck = self.create_deck()
        player_hand = [self.draw_card(deck), self.draw_card(deck)]
        dealer_hand = [self.draw_card(deck), self.draw_card(deck)]
        
        # Store game state
        self.blackjack_games[game_id] = {
            "deck": deck, 
            "player_hand": player_hand, 
            "dealer_hand": dealer_hand,
            "bet": bet, 
            "message": None,
            "start_time": datetime.now() # Track when game started for timeout
        }
        
        player_value = self.calculate_hand(player_hand)
        dealer_value = self.calculate_hand(dealer_hand)

        # Handle immediate wins/losses (Blackjack or busts)
        if player_value == 21 and dealer_value == 21: # Player Blackjack, Dealer Blackjack
            message = None # Will get response in a moment
            await interaction.response.send_message("Checking for Blackjacks...")
            message = await interaction.original_response()
            self.blackjack_games[game_id]["message"] = message
            await self.end_blackjack_game(message, game_id)
            return
        elif player_value == 21: # Player Blackjack
            message = None
            await interaction.response.send_message("Checking for Blackjack...")
            message = await interaction.original_response()
            self.blackjack_games[game_id]["message"] = message
            await self.end_blackjack_game(message, game_id)
            return
        # No need to check dealer blackjack here, as that's handled at the end if player doesn't bust

        # Display the game board if no immediate winner
        view = BlackjackView(self, user_id_str, guild_id_str)
        embed = self.create_blackjack_embed(interaction.user, self.blackjack_games[game_id])
        await interaction.response.send_message(embed=embed, view=view)
        self.blackjack_games[game_id]["message"] = await interaction.original_response()

    def create_deck(self):
        """Creates a new, shuffled deck of 52 cards (or more for realism, here just one suit x4 values)."""
        # A standard 52-card deck * 4 for more realism in multiple rounds, or a simple smaller deck for demo.
        # Using 4 sets of standard deck for better gameplay variability
        suits = ['♠️', '♥️', '♦️', '♣️']
        values = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        # Create 4 decks and shuffle them together
        deck = []
        for _ in range(4): # Use 4 decks for better shuffling variety
            for suit in suits:
                for value in values:
                    deck.append((value, suit))
        random.shuffle(deck)
        return deck

    def draw_card(self, deck):
        """Draws a card from the deck, returning None if deck is empty."""
        if not deck:
            logger.warning("Deck is empty, cannot draw card.")
            return None # Or potentially recreate the deck if needed for longer games
        return deck.pop()

    def calculate_hand(self, hand):
        """Calculates the best possible score for a blackjack hand."""
        value, aces = 0, 0
        for card_value, _ in hand:
            if card_value in ['J', 'Q', 'K']:
                value += 10
            elif card_value == 'A':
                value += 11 # Initially count Ace as 11
                aces += 1
            else:
                value += int(card_value)
        
        # Adjust for Aces if value exceeds 21
        while value > 21 and aces > 0:
            value -= 10  # Convert an Ace from 11 to 1
            aces -= 1
        return value

    def format_card(self, card):
        """Formats a card tuple into a displayable string (e.g., 'A♠️')."""
        if card is None: return "🂠" # For hidden card representation
        return f"{card[0]}{card[1]}"

    def format_hand(self, hand, hide_second=False):
        """Formats a list of cards, optionally hiding the dealer's second card."""
        if hide_second:
            if len(hand) > 0:
                return f"{self.format_card(hand[0])} 🂠"
            else:
                return "🂠"
        return " ".join(self.format_card(card) for card in hand)

    def create_blackjack_embed(self, user, game, result_message=None, commentary=None, hide_dealer_card=None):
        """Generates the embed for the blackjack game's current state."""
        # Default behavior: hide dealer's second card unless it's an endgame summary or explicit request
        hide_dealer_card = hide_dealer_card if hide_dealer_card is not None else (result_message is None and commentary is None)
        
        player_hand = game.get("player_hand", [])
        dealer_hand = game.get("dealer_hand", [])
        bet = game.get("bet", 0)
        player_value = self.calculate_hand(player_hand)
        dealer_value = self.calculate_hand(dealer_hand)
        
        dealer_value_display = ""
        if not hide_dealer_card:
            dealer_value_display = f': {dealer_value}'

        embed = discord.Embed(
            title=f"{self._get_embed_emoji('blackjack', '🃏')} Blackjack - Bet: {bet:,}",
            color=self._get_default_embed_color()
        )
        embed.set_thumbnail(url=self._get_embed_thumbnail('blackjack'))
        
        embed.add_field(name=f"Dealer's Hand{dealer_value_display}", value=self.format_hand(dealer_hand, hide_dealer_card), inline=False)
        embed.add_field(name=f"{user.display_name}'s Hand: {player_value}", value=self.format_hand(player_hand), inline=False)

        if commentary:
            embed.add_field(name="Commentary", value=f"*{commentary}*", inline=False)
        if result_message:
            embed.add_field(name="Result", value=result_message, inline=False)
            
        return embed

    async def end_blackjack_game(self, message, game_id, is_timeout=False):
        """Handles the end of a blackjack game, determining winner, updating balances, and editing the message."""
        game_info = self.blackjack_games.get(game_id)
        if not game_info:
            logger.warning(f"Game {game_id} not found in active games during end_blackjack_game.")
            return
        
        user_id = game_id.split('_')[1]
        user = await self.bot.fetch_user(int(user_id))
        bet = game_info["bet"]
        amount_changed = 0
        result_message = ""

        # Reveal all cards if it was a timeout or natural win, prepare for outcome calculation
        player_hand = game_info["player_hand"]
        dealer_hand = game_info["dealer_hand"]
        player_value = self.calculate_hand(player_hand)
        dealer_value = self.calculate_hand(dealer_hand)

        # 1. Determine outcome based on who busted, blackjack, etc.
        if is_timeout:
            amount_changed = -bet
            result_message = f"Game timed out (no action for 15 minutes). You lost **{bet:,}** credits."
        elif player_value > 21: # Player bust
            amount_changed = -bet
            result_message = f"Bust! Your hand is {player_value}. You lost **{bet:,}** credits."
        elif dealer_value > 21: # Dealer bust
            amount_changed = bet
            result_message = f"Dealer's hand is {dealer_value}. Dealer busts! You won **{bet:,}** credits!"
        elif player_value == 21 and len(player_hand) == 2 and dealer_value != 21: # Player Blackjack, Dealer no Blackjack
            amount_changed = int(bet * 1.5) # Blackjack pays 3:2
            result_message = f"Blackjack! You won **{int(bet*1.5):,}** credits!"
        elif dealer_value > player_value: # Dealer wins
            amount_changed = -bet
            result_message = f"Dealer's hand ({dealer_value}) beats your hand ({player_value}). You lost **{bet:,}** credits."
        elif player_value > dealer_value: # Player wins
            amount_changed = bet
            result_message = f"Your hand ({player_value}) beats the dealer's ({dealer_value}). You won **{bet:,}** credits!"
        else: # Push (tie)
            amount_changed = 0
            result_message = f"Both hands are {player_value}. It's a push! Your bet has been returned."

        # Update balance
        new_balance = await update_user_balance(user_id, amount_changed) # Update balance atomically
        result_message += f"\nYou are now at **{new_balance:,}** credits."
        logger.info(f"Blackjack game {game_id} ended. Outcome: {result_message}")

        # Create final embed with results
        final_embed = self.create_blackjack_embed(user, game_info, result_message=result_message, hide_dealer_card=False) # Ensure all cards are shown

        # Edit the original message
        try:
            await message.edit(embed=final_embed, view=None) # Remove buttons
        except discord.DiscordException as e:
            logger.warning(f"Failed to edit blackjack message for game {game_id} during game end: {e}")
            try:
                # Fallback: attempt to send a new message if editing fails critically
                channel = message.channel
                await channel.send(embed=final_embed)
            except Exception as e2:
                logger.error(f"Failed to send fallback blackjack end message for game {game_id}: {e2}")
        
        # Clean up game from active games
        if game_id in self.blackjack_games:
            del self.blackjack_games[game_id]

    async def handle_hit(self, user_id, guild_id, message):
        """Handles player hitting in blackjack."""
        game_id = f"{guild_id}_{user_id}"
        game_info = self.blackjack_games.get(game_id)
        if not game_info:
            logger.warning(f"Game {game_id} not found for hit action.")
            return
        
        # Draw card for player
        drawn_card = self.draw_card(game_info["deck"])
        if drawn_card is None: # Handle empty deck if necessary
            await message.channel.send("Deck ran out! Reshuffling...", delete_after=5)
            game_info["deck"] = self.create_deck() # Reshuffle
            drawn_card = self.draw_card(game_info["deck"])
            if drawn_card is None: # Still empty? Problematic
                 logger.error(f"Deck empty even after reshuffle for game {game_id}. Cannot draw.")
                 return

        game_info["player_hand"].append(drawn_card)
        
        # Check for bust immediately after hitting
        player_value = self.calculate_hand(game_info["player_hand"])
        user = await self.bot.fetch_user(int(user_id))

        if player_value > 21: # Player busts
            await self.end_blackjack_game(message, game_id)
        else:
            commentary = f"You drew a **{self.format_card(drawn_card)}**."
            embed = self.create_blackjack_embed(user, game_info, commentary=commentary)
            # Update view: disable hit, maybe keep double if applicable, disable stand
            # For now, assume game continues until they choose to stand or bust.
            try:
                await message.edit(embed=embed)
            except discord.DiscordException as e:
                logger.warning(f"Failed to edit blackjack message after hit for game {game_id}: {e}")

    async def handle_stand(self, user_id, guild_id, message):
        """Handles player standing in blackjack."""
        game_id = f"{guild_id}_{user_id}"
        game_info = self.blackjack_games.get(game_id)
        if not game_info:
            logger.warning(f"Game {game_id} not found for stand action.")
            return

        user = await self.bot.fetch_user(int(user_id))
        dealer_hand = game_info["dealer_hand"]

        # 1. Reveal Dealer's hidden card and show initial commentary
        hidden_card_formatted = self.format_card(dealer_hand[1]) if len(dealer_hand) > 1 else "🂠"
        commentary = f"You stand. Dealer reveals their hidden card... It's a **{hidden_card_formatted}**!"
        
        embed = self.create_blackjack_embed(user, game_info, commentary=commentary, hide_dealer_card=False)
        try:
            await message.edit(embed=embed)
        except discord.DiscordException as e:
            logger.warning(f"Failed to edit blackjack message after reveal for game {game_id}: {e}")
        await asyncio.sleep(2) # Pause to let user read

        # 2. Dealer draws cards until hand value is 17 or more
        current_dealer_value = self.calculate_hand(dealer_hand)
        while current_dealer_value < 17:
            commentary = f"Dealer's hand is at {current_dealer_value}. Dealer hits."
            embed = self.create_blackjack_embed(user, game_info, commentary=commentary, hide_dealer_card=False)
            try:
                await message.edit(embed=embed)
            except discord.DiscordException as e:
                logger.warning(f"Failed to edit blackjack message during dealer draw for game {game_id}: {e}")
            await asyncio.sleep(2)

            drawn_card = self.draw_card(game_info["deck"])
            if drawn_card is None: # Handle empty deck if dealer hits
                 await message.channel.send("Dealer's deck ran out! Reshuffling...", delete_after=5)
                 game_info["deck"] = self.create_deck()
                 drawn_card = self.draw_card(game_info["deck"])
                 if drawn_card is None:
                    logger.error(f"Dealer cannot draw after reshuffle for game {game_id}.")
                    # Consider this a soft error, may impact fairness but game can proceed with current state.
                    break 

            dealer_hand.append(drawn_card)
            current_dealer_value = self.calculate_hand(dealer_hand)
            commentary = f"Dealer draws a **{self.format_card(drawn_card)}**."
            embed = self.create_blackjack_embed(user, game_info, commentary=commentary, hide_dealer_card=False)
            try:
                await message.edit(embed=embed)
            except discord.DiscordException as e:
                logger.warning(f"Failed to edit blackjack message after dealer draw for game {game_id}: {e}")
            await asyncio.sleep(2)

        # 3. End the game now that dealer has stood or busted
        await self.end_blackjack_game(message, game_id)

    async def handle_double(self, user_id, guild_id, message):
        """Handles player doubling down in blackjack."""
        game_id = f"{guild_id}_{user_id}"
        game_info = self.blackjack_games.get(game_id)
        if not game_info:
            logger.warning(f"Game {game_id} not found for double down action.")
            return

        original_bet = game_info["bet"]
        user_balance = await get_user_balance(user_id)

        # Check if player has enough for double bet
        if user_balance < original_bet:
            embed = discord.Embed(
                title="Error",
                description=f"You need at least **{original_bet:,}** more credits to double down. Your balance is **{user_balance:,}**.",
                color=discord.Color.red()
            )
            # Inform user without editing game message as they can't double down
            try:
                await message.channel.send(embed=embed, ephemeral=True, delete_after=10) # ephemeral doesn't work in context of message.channel send
            except discord.DiscordException as e:
                logger.warning(f"Failed to send double down error message: {e}")
            return
        
        # Successfully doubled down
        game_info["bet"] = original_bet * 2 # Double the bet
        
        # Draw the final card for the player
        drawn_card = self.draw_card(game_info["deck"])
        if drawn_card is None: # Handle empty deck
            await message.channel.send("Deck ran out during double down! Reshuffling...", delete_after=5)
            game_info["deck"] = self.create_deck()
            drawn_card = self.draw_card(game_info["deck"])
            if drawn_card is None:
                logger.error(f"Dealer cannot draw after reshuffle during double down for game {game_id}.")
                # Game might continue with player drawing last card if deck completely empty, potentially unfair.
                # Best to signal and stop the double-down action, or re-prompt.
                # For simplicity, we'll try to proceed or abort double-down. Let's re-evaluate player's hand.
                pass # Let game end based on current hand.

        if drawn_card:
            game_info["player_hand"].append(drawn_card)
        
        user = await self.bot.fetch_user(int(user_id))
        player_value = self.calculate_hand(game_info["player_hand"])

        commentary = f"You doubled down! Your new bet is **{game_info['bet']:,}**. You drew a **{self.format_card(drawn_card)}**. Your final hand value is {player_value}. Now for the dealer..."
        
        # Remove buttons to prevent further actions before dealer plays
        # Also set view=None when editing final game result.
        
        if player_value > 21: # Player busts after doubling down
            await self.end_blackjack_game(message, game_id)
        else:
            # Need to show the new state with only dealer's turn remaining
            embed = self.create_blackjack_embed(user, game_info, commentary=commentary, hide_dealer_card=True)
            try:
                await message.edit(embed=embed, view=None) # Remove buttons, it's dealer's turn
            except discord.DiscordException as e:
                logger.warning(f"Failed to edit blackjack message after double down for game {game_id}: {e}")
            await asyncio.sleep(2.5) # Pause for user to read
            await self.handle_stand(user_id, guild_id, message) # Dealer's turn now

    # --- Roulette Game ---
    @app_commands.command(name="roulette", description="Play a game of roulette")
    @app_commands.describe(bet="The amount to bet", bet_type="The type of bet to place", number="The specific number (for 'Single Number' bet, 0-36)")
    @app_commands.choices(bet_type=[
        app_commands.Choice(name="Red", value="red"), app_commands.Choice(name="Black", value="black"),
        app_commands.Choice(name="Even", value="even"), app_commands.Choice(name="Odd", value="odd"),
        app_commands.Choice(name="1-18 (Low)", value="low"), app_commands.Choice(name="19-36 (High)", value="high"),
        app_commands.Choice(name="1st Dozen (1-12)", value="first"), app_commands.Choice(name="2nd Dozen (13-24)", value="second"),
        app_commands.Choice(name="3rd Dozen (25-36)", value="third"), app_commands.Choice(name="Single Number", value="number")
    ])
    async def roulette(self, interaction: discord.Interaction, bet: int, bet_type: str, number: app_commands.Range[int, 0, 36] = None):
        if bet <= 0:
            embed = discord.Embed(title="Error", description="Bet must be greater than 0.", color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        user_id_str = str(interaction.user.id)
        user_balance = await get_user_balance(user_id_str)

        if user_balance < bet:
            embed = discord.Embed(
                title="Error",
                description=f"You don't have enough credits. Your balance is **{user_balance:,}**.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        if bet_type == "number" and number is None:
            embed = discord.Embed(
                title="Error",
                description="You must specify a number (0-36) for a 'Single Number' bet.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # --- Spin Animation ---
        spinning_embed = discord.Embed(
            title=f"{self._get_embed_emoji('roulette', '🎰')} Roulette - Spinning the wheel...",
            description="No more bets!",
            color=self._get_default_embed_color()
        )
        spinning_embed.set_thumbnail(url=self._get_embed_thumbnail('roulette'))
        
        await interaction.response.send_message(embed=spinning_embed)
        message = await interaction.original_response()

        red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
        number_range = range(0, 37) # 0 to 36
        
        animation_delay = 0.4 # Base delay
        current_numbers = [random.choice(list(number_range)) for _ in range(8)] # Simulate movement
        
        try:
            for i, num in enumerate(current_numbers):
                color_emoji = "🟢" if num == 0 else ("🔴" if num in red_numbers else "⚫")
                spinning_embed.title = f"{self._get_embed_emoji('roulette', '🎰')} Roulette - The ball lands on {color_emoji} {num}"
                
                # Gradually slow down the animation
                sleep_time = animation_delay + (len(current_numbers) - 1 - i) * 0.1
                await message.edit(embed=spinning_embed)
                await asyncio.sleep(sleep_time)

            # Final result
            result = random.choice(list(number_range))
            if result == 0:
                result_color_str, result_emoji = "green", "🟢"
            elif result in red_numbers:
                result_color_str, result_emoji = "red", "🔴"
            else:
                result_color_str, result_emoji = "black", "⚫"

            # Animation logic complete, prepare result embed
            winnings = 0
            bet_type_display = bet_type.replace("_", " ").title()

            if bet_type == "red" and result_color_str == "red": winnings = bet * 2
            elif bet_type == "black" and result_color_str == "black": winnings = bet * 2
            elif bet_type == "even" and result != 0 and result % 2 == 0: winnings = bet * 2
            elif bet_type == "odd" and result % 2 == 1: winnings = bet * 2
            elif bet_type == "low" and 1 <= result <= 18: winnings = bet * 2
            elif bet_type == "high" and 19 <= result <= 36: winnings = bet * 2
            elif bet_type == "first" and 1 <= result <= 12: winnings = bet * 3
            elif bet_type == "second" and 13 <= result <= 24: winnings = bet * 3
            elif bet_type == "third" and 25 <= result <= 36: winnings = bet * 3
            elif bet_type == "number" and result == number: winnings = bet * 36

            amount_changed = winnings - bet
            new_balance = await update_user_balance(user_id_str, amount_changed) # Update balance atomically

            if amount_changed > 0:
                outcome_desc = f"You won **{amount_changed:,}** credits!"
            elif result != 0 and winnings == bet: # Push case
                outcome_desc = "It's a push! Your bet has been returned."
            else: # Loss
                outcome_desc = f"You lost **{bet:,}** credits."

            if bet_type == "number":
                bet_type_display = f"Number {number}"

            if amount_changed > 0:
                result_embed_color = discord.Color.green()
            elif result != 0 and winnings == bet:
                result_embed_color = self._get_default_embed_color() # Push color
            else:
                result_embed_color = discord.Color.red()

            final_embed = discord.Embed(
                title=f"{self._get_embed_emoji('roulette', '🎰')} Roulette - The ball landed on {result_emoji} {result}!",
                description=f"Your bet: **{bet:,}** credits on **{bet_type_display}**\nOutcome: {outcome_desc}\nYour new balance: **{new_balance:,}** credits.",
                color=result_embed_color
            )
            final_embed.set_thumbnail(url=self._get_embed_thumbnail('roulette'))
            logger.info(f"Roulette result for user {user_id_str}: Bet={bet:,}, Type={bet_type_display}, Result={result_emoji}{result}, Win/Loss={amount_changed:+,}, New Balance={new_balance:,}")

            await message.edit(embed=final_embed)

        except discord.DiscordException as e:
            logger.error(f"An error occurred during roulette animation or result display: {e}")
            try:
                error_embed = discord.Embed(title="Error", description="An error occurred during the roulette spin.", color=discord.Color.red())
                await message.edit(embed=error_embed)
            except discord.DiscordException as e2:
                logger.error(f"Failed to send fallback roulette error message: {e2}")
        except Exception as e: # Catch any other unexpected errors
            logger.error(f"An unhandled exception occurred in roulette command: {e}")
            try:
                error_embed = discord.Embed(title="Error", description="An unhandled error occurred. Please try again.", color=discord.Color.red())
                await message.edit(embed=error_embed)
            except discord.DiscordException as e2:
                logger.error(f"Failed to send fallback roulette error message on unhandled exception: {e2}")


class BlackjackView(ui.View):
    """View for interactive Blackjack game controls."""
    def __init__(self, betting_cog, user_id, guild_id):
        super().__init__(timeout=180) # Game session lasts for 180 seconds (3 minutes) of inactivity
        self.betting_cog = betting_cog
        self.user_id = user_id
        self.guild_id = guild_id
        
        # The problematic line `self.initial_balance_check = user_balance` has been removed.
        # The balance check will now be performed within the button handler.

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensures only the game owner can interact with the buttons."""
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("This is not your game to control!", ephemeral=True)
            return False
        return True
    
    async def on_timeout(self):
        """Called when the view times out due to inactivity."""
        game_id = f"{self.guild_id}_{self.user_id}"
        game_info = self.betting_cog.blackjack_games.get(game_id)
        if game_info and game_info.get("message"):
            # End the game due to timeout, indicating player lost their bet
            await self.betting_cog.end_blackjack_game(game_info["message"], game_id, is_timeout=True)
        else:
            logger.warning(f"Timeout occurred for game {game_id}, but game data not found.")
        
        # Attempt to disable buttons if message still exists
        if game_info and game_info.get("message"):
            try:
                await game_info["message"].edit(view=None)
            except discord.DiscordException as e:
                logger.warning(f"Failed to disable buttons after timeout for game {game_id}: {e}")

    @ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="➕")
    async def hit_button(self, interaction: discord.Interaction, button: ui.Button):
        # Defer the interaction to allow background processing
        await interaction.response.defer()
        # Call the cog's handler for hit logic
        await self.betting_cog.handle_hit(self.user_id, self.guild_id, interaction.message)
    
    @ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="🛑")
    async def stand_button(self, interaction: discord.Interaction, button: ui.Button):
        # Disable all buttons to prevent further actions after Stand
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self) # Update the message to show disabled buttons
        # Call the cog's handler for stand logic
        await self.betting_cog.handle_stand(self.user_id, self.guild_id, interaction.message)
    
    @ui.button(label="Double Down", style=discord.ButtonStyle.danger, emoji="💰")
    async def double_button(self, interaction: discord.Interaction, button: ui.Button):
        # --- START FIX ---
        game_id = f"{self.guild_id}_{self.user_id}"
        game_info = self.betting_cog.blackjack_games.get(game_id)
        
        if not game_info:
            logger.warning(f"Game {game_id} not found for double down action.")
            await interaction.response.send_message("Game not found!", ephemeral=True)
            return

        original_bet = game_info["bet"]
        # Fetch the user's balance here, as __init__ cannot be async
        user_balance = await get_user_balance(self.user_id) 

        if user_balance < original_bet:
            # User cannot afford to double down
            embed = discord.Embed(
                title="Error",
                description=f"You need at least **{original_bet:,}** more credits to double down. Your balance is **{user_balance:,}**.",
                color=discord.Color.red()
            )
            # Send an ephemeral message to the user
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return # Do not proceed with doubling down
        # --- END FIX ---

        # If they can afford it, proceed with doubling down
        # Disable all buttons as Double Down is a commitment to stand after the draw
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(view=self) # Update the message to show disabled buttons
        
        # Call the cog's handler for double down logic
        await self.betting_cog.handle_double(self.user_id, self.guild_id, interaction.message)

async def setup(bot):
    """Setup function to add the BettingSystem cog to the bot."""
    await bot.add_cog(BettingSystem(bot))