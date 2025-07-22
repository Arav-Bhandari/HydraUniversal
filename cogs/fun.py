import discord
import random
from discord import app_commands
from discord.ext import commands

# Common user lists for all commands
GOOD_USERS = [
    1074081130401251339,
    854735722320494632,
    618628999136018441,
    365499293357834240,
    1204465750010630157,
    1117225645718646915,
    1099798391535439913,
    667199698695749692,
]

BAD_USERS = [
    332653735170015233,
    573238651954135040,
    1166863648162066502,
    1250974340917362795,
    1001586534757175408,
    313153733104238592,
    836678938431717377,
    1335151877519572992,
    1192599992519631010,
    846936704861339699,
    1209055652153131029,
    1316081518472335410,
    824674915634511956,
    1207854388173864971,
    1311751109492342784,
    277504236328058880,
    750699987498827806,
]

SMALL_MESSAGES = [
    "Oof, {target} has a PP so small it needs a microscope to be seen! 8=D",
    "Wow, {target}'s PP is tinier than a pixel! Better luck next time! 8=D",
    "{target}'s PP is so small it could fit in a thimble. Yikes! 8=D",
    "Is that a PP or a punctuation mark, {target}? Too small to tell! 8=D",
    "{target}'s PP is so petite it could hide behind a grain of rice! 8=D",
]

BIG_MESSAGES = [
    "{target}'s PP is so massive it blocks out the sun! Legendary! 8========================================D",
    "Good grief, {target}! Your PP is longer than a CVS receipt! 8========================================D",
    "{target}'s PP is so big it needs its own zip code! Impressive! 8========================================D",
    "Watch out, {target}'s PP is so huge it could star in a kaiju movie! 8========================================D",
    "Is that a PP or a skyscraper, {target}? Absolutely colossal! 8========================================D",
]

class FunCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ppsize", description="Check how long someone's PP is")
    @app_commands.describe(user="The user to check (optional)")
    async def ppsize(self, interaction: discord.Interaction, user: discord.Member = None):
        try:
            target = user or interaction.user
            embed = discord.Embed(title="PP Size Check", color=discord.Color.random())
            embed.add_field(name="Target", value=target.mention, inline=False)

            if target.id in GOOD_USERS:
                embed.description = random.choice(BIG_MESSAGES).format(target=target.mention)
            elif target.id in BAD_USERS:
                embed.description = random.choice(SMALL_MESSAGES).format(target=target.mention)
            else:
                rand = random.random()
                if rand < 0.00001:
                    size = 300
                elif rand < 0.0001:
                    size = 100
                else:
                    size = random.randint(1, 30)

                pp_visual = "8" + "=" * size + "D"

                if size <= 2:
                    description = f"{target.mention}'s PP is {size} inches. A shy little stub—blink and you'll miss it. Hey, Atleast its larger than Kronix's PP! {pp_visual}"
                elif size <= 5:
                    description = f"{target.mention}'s PP is {size} inches. Small but scrappy, like a feisty chihuahua! {pp_visual}"
                elif size <= 8:
                    description = f"{target.mention}'s PP is {size} inches. Perfectly average—like a reliable Honda Civic! {pp_visual}"
                elif size <= 11:
                    description = f"{target.mention}'s PP is {size} inches. Above average, strutting like it owns the place! {pp_visual}"
                elif size <= 14:
                    description = f"{target.mention}'s PP is {size} inches. Wow, that's a PP with some serious swagger! {pp_visual}"
                elif size <= 17:
                    description = f"{target.mention}'s PP is {size} inches. Getting into 'whoa there' territory! {pp_visual}"
                elif size <= 20:
                    description = f"{target.mention}'s PP is {size} inches. That's a PP that demands its own theme song! {pp_visual}"
                elif size <= 23:
                    description = f"{target.mention}'s PP is {size} inches. Move over, rulers—this one's breaking records! {pp_visual}"
                elif size <= 26:
                    description = f"{target.mention}'s PP is {size} inches. Is that allowed to be *that* big? Call the PP police! {pp_visual}"
                elif size <= 30:
                    description = f"{target.mention}'s PP is {size} inches. A true titan—bows to no one! {pp_visual}"
                elif size == 100:
                    description = f"{target.mention}'s PP is {size} inches. A mythical beast—science can't explain this! {pp_visual}"
                elif size == 300:
                    description = f"{target.mention}'s PP is {size} inches. Galactic-tier PP! It's orbiting the server now! {pp_visual}"

                embed.description = description

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            # Check if we've already responded to this interaction
            if interaction.response.is_done():
                # If already responded, try to send a followup message
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ Error",
                        description=f"An error occurred while processing your request:\n```{str(e)}```",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            else:
                # If not responded yet, send the response
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"An error occurred while processing your request:\n```{str(e)}```",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Please try again later")
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="gaycheck", description="Check how gay a user is!")
    @app_commands.describe(user="The user to check (optional)")
    async def gaycheck(self, interaction: discord.Interaction, user: discord.Member = None):
        try:
            target = user or interaction.user
            embed = discord.Embed(title="🌈 Gayness Check", color=discord.Color.random())
            embed.add_field(name="Target", value=target.mention, inline=False)

            if target.id in BAD_USERS:
                embed.description = f"{target.mention} is 100% gay. Certified rainbow warrior! 🌈"
            elif target.id in GOOD_USERS:
                embed.description = f"{target.mention} is 0% gay. STRAIGHT AF!"
            else:
                gayness = random.randint(1, 100)

                if gayness < 25:
                    description = f"{target.mention} is only {gayness}% gay. Straight as an arrow!"
                elif gayness <= 50:
                    description = f"{target.mention} is {gayness}% gay. A little curious perhaps!"
                elif gayness <= 75:
                    description = f"{target.mention} is {gayness}% gay. Definitely experimenting!"
                else:
                    description = f"{target.mention} is {gayness}% gay. Pretty gay, but not as gay as Kronix!"

                embed.description = description

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            # Check if we've already responded to this interaction
            if interaction.response.is_done():
                # If already responded, try to send a followup message
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ Error",
                        description=f"An error occurred while processing your request:\n```{str(e)}```",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            else:
                # If not responded yet, send the response
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"An error occurred while processing your request:\n```{str(e)}```",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Please try again later")
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="auracheck", description="Check how much Aura someone has")
    @app_commands.describe(user="The user to check (optional)")
    async def auracheck(self, interaction: discord.Interaction, user: discord.Member = None):
        try:
            target = user or interaction.user
            embed = discord.Embed(title="AuraCheck", color=discord.Color.random())
            embed.add_field(name="Target", value=target.mention, inline=False)

            if target.id in GOOD_USERS:
                embed.description = f"{target.mention} radiates an aura of pure magnificence! ✨"
            elif target.id in BAD_USERS:
                embed.description = f"{target.mention} has no aura at all. Just like Kronix! 🤮"
            else:
                rand = random.random()
                if rand < 0.00001:
                    aura_level = 300
                elif rand < 0.0001:
                    aura_level = 100
                else:
                    aura_level = random.randint(1, 30)

                if aura_level <= 2:
                    description = f"{target.mention}'s aura is {aura_level}%. Barely a flicker—like a candle in a hurricane. At least it's better than Kronix's Aura 🤮."
                elif aura_level <= 5:
                    description = f"{target.mention}'s aura is {aura_level}%. A faint glow, like a firefly on a dim night."
                elif aura_level <= 8:
                    description = f"{target.mention}'s aura is {aura_level}%. Solidly average—vibes that won't scare or impress."
                elif aura_level <= 11:
                    description = f"{target.mention}'s aura is {aura_level}%. Rising above the norm, starting to turn heads!"
                elif aura_level <= 14:
                    description = f"{target.mention}'s aura is {aura_level}%. A bold presence—people can't help but notice!"
                elif aura_level <= 17:
                    description = f"{target.mention}'s aura is {aura_level}%. Intense vibes rolling in like a thunderstorm!"
                elif aura_level <= 20:
                    description = f"{target.mention}'s aura is {aura_level}%. A commanding energy that shifts the atmosphere!"
                elif aura_level <= 23:
                    description = f"{target.mention}'s aura is {aura_level}%. Legendary vibes—stories will be told of this!"
                elif aura_level <= 26:
                    description = f"{target.mention}'s aura is {aura_level}%. Near-mythical power—reality bends around them!"
                elif aura_level <= 30:
                    description = f"{target.mention}'s aura is {aura_level}%. A supreme aura—kings bow and stars align!"
                elif aura_level == 100:
                    description = f"{target.mention}'s aura is {aura_level}%. A divine glow—mortals can only dream of this!"
                elif aura_level == 300:
                    description = f"{target.mention}'s aura is {aura_level}%. Cosmic-tier energy—galaxies orbit their vibe!"
                
                embed.description = description

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            # Check if we've already responded to this interaction
            if interaction.response.is_done():
                # If already responded, try to send a followup message
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ Error",
                        description=f"An error occurred while processing your request:\n```{str(e)}```",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            else:
                # If not responded yet, send the response
                embed = discord.Embed(
                    title="❌ Error",
                    description=f"An error occurred while processing your request:\n```{str(e)}```",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Please try again later")
                await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(FunCommands(bot))