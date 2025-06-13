
import os
import discord
from discord.commands import SlashCommandGroup
from discord.ext import commands
from dotenv import load_dotenv

# --- IMPORTS FROM BOTH SCRIPTS ---
import asyncio
import collections
from datetime import datetime
import html # Used to escape characters for safe HTML display
import random # For gambling games

# --- NEW/MODIFIED IMPORTS ---
# Use the new asynchronous database module
import database as db
# Import the new admin panel module, replacing aiohttp
import admin_panel

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv('DISCORD_TOKEN')

try:
    ADMIN_LOG_CHANNEL_ID = int(os.getenv('ADMIN_LOG_CHANNEL_ID'))
except (TypeError, ValueError):
    ADMIN_LOG_CHANNEL_ID = None
    print("WARNING: ADMIN_LOG_CHANNEL_ID not found or invalid in .env file. Admin channel logging is disabled.")


CONSTELLATION_USER_IDS = [1072508556907139133] # Replace with your admin user IDs
CONSTELLATION_ROLE_IDS = [1382715685276221483] # Replace with your admin role IDs

CURRENCY_NAME = "Starstream Coin"
CURRENCY_SYMBOL = "SSC"

MAIN_GUILD_ID = 1369930083564912670 # Replace with your main guild ID
# --- END CONFIGURATION ---

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)
# --- END BOT SETUP ---

# --- THEME & EMBED FACTORY ---
class EmbedFactory:
    FOOTER_TEXT = "A Message from the Star Stream"

    @staticmethod
    def create(title: str, color: discord.Color, description: str = "", **kwargs) -> discord.Embed:
        author_name = kwargs.pop('author_name', None)
        author_icon = kwargs.pop('author_icon', None)
        embed = discord.Embed(title=title, description=description, color=color, **kwargs)
        if author_name and author_icon:
            embed.set_author(name=author_name, icon_url=author_icon)
        embed.set_footer(text=EmbedFactory.FOOTER_TEXT)
        return embed

# --- PERMISSIONS ---
def is_constellation(ctx: discord.ApplicationContext) -> bool:
    """Check if the user is a 'Constellation' (admin/generator). (Now safe for DMs)"""
    author = ctx.author
    if author.id in CONSTELLATION_USER_IDS:
        return True
    # Roles only exist on Member objects (i.e., in a guild context)
    if isinstance(author, discord.Member):
        author_role_ids = [role.id for role in author.roles]
        if any(role_id in CONSTELLATION_ROLE_IDS for role_id in author_role_ids):
            return True
    return False

def is_constellation_from_message(message: discord.Message) -> bool:
    """Check if the author of a message is a 'Constellation'."""
    author = message.author
    if author.id in CONSTELLATION_USER_IDS:
        return True
    # Roles only exist on Member objects (i.e., in a guild context)
    if isinstance(author, discord.Member):
        author_role_ids = [role.id for role in author.roles]
        if any(role_id in CONSTELLATION_ROLE_IDS for role_id in author_role_ids):
            return True
    return False

# --- LOGGING & WEB SERVER (MODIFIED FOR NEW ADMIN PANEL) ---
LOG_CACHE = collections.deque(maxlen=200)

async def send_log(embed: discord.Embed):
    """Logs to a Discord channel and broadcasts to the new web admin panel."""
    # Log to Discord Channel
    if ADMIN_LOG_CHANNEL_ID:
        try:
            log_channel = bot.get_channel(ADMIN_LOG_CHANNEL_ID) or await bot.fetch_channel(ADMIN_LOG_CHANNEL_ID)
            await log_channel.send(embed=embed)
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"ERROR: Could not send to admin log channel ({ADMIN_LOG_CHANNEL_ID}). {e}")
        except Exception as e:
            print(f"ERROR: Failed to send log to admin channel. {e}")

    # Prepare log for HTML and WebSocket broadcast
    ts = f"<span class='timestamp'>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span>"
    title = f"<span class='title'>{html.escape(str(embed.title))}</span>" if embed.title else ""
    parts = [f"{ts}<br>{title}"]
    if embed.description:
        parts.append(html.escape(str(embed.description)))
    for field in embed.fields:
        parts.append(f"<span class='field-name'>{html.escape(field.name)}:</span><br>{html.escape(field.value)}")
    
    html_log = "<br>".join(parts)
    LOG_CACHE.append(html_log)
    
    # Broadcast to admin panel via WebSocket
    await admin_panel.broadcast_log(html_log)


async def send_purchase_log_to_constellations(embed: discord.Embed):
    for user_id in CONSTELLATION_USER_IDS:
        try:
            user = bot.get_user(user_id) or await bot.fetch_user(user_id)
            if user and not user.bot:
                await user.send(embed=embed)
        except Exception as e:
            print(f"ERROR: Could not DM Constellation {user_id}: {e}")

# --- BOT EVENTS ---
@bot.event
async def on_ready():
    """Event handler for when the bot is ready."""
    print(f'Logged in as {bot.user} | The Star Stream is watching.')
    await db.init_db()
    await bot.sync_commands()
    print("All Scenarios (Slash Commands) have been synced with Discord.")
    # Start the new admin panel server
    asyncio.create_task(admin_panel.start_admin_panel_server(bot, LOG_CACHE))

# --- GRR TEXT COMMAND HANDLERS ---
async def handle_grr_cash(message: discord.Message, args: list):
    target_user = message.mentions[0] if message.mentions else message.author
    user_balance = await db.get_grr_balance(target_user.id)
    response = f"💰 {target_user.display_name} is hoarding **{user_balance:,}** GRR coins."
    await message.channel.send(response, reference=message)

async def handle_grr_daily(message: discord.Message, args: list):
    daily_amount = random.randint(50, 150)
    result = await db.claim_daily_grr(message.author.id, daily_amount)

    if result == "success":
        new_balance = await db.get_grr_balance(message.author.id)
        response = f"🎉 {message.author.mention} has received a surprise of **{daily_amount:,}** GRR coins! Their new balance is **{new_balance:,}** GRR."
        await message.channel.send(response, reference=message)
    elif result == "already_claimed":
        response = "🚫 You've already claimed your daily GRR coins. Come back tomorrow!"
        await message.channel.send(response, reference=message, delete_after=10)

# --- MODIFICATION START: Disable grr exchange ---
async def handle_grr_exchange(message: discord.Message, args: list):
    await message.channel.send("The GRR to SSC exchange is temporarily disabled due to market instability.", reference=message)
    return
# --- MODIFICATION END ---

# --- MODIFICATION START: Add 'all' subcommand to grr cf ---
async def handle_grr_cf(message: discord.Message, args: list):
    """Handles the coin flip command. `grr cf <amount|all> [t]`"""
    if not args:
        return await message.channel.send("Please specify an amount to bet! Usage: `grr cf <amount|all> [t for tails]`", reference=message)

    choice = "Tails" if len(args) > 1 and args[1].lower() == 't' else "Heads"
    balance = await db.get_grr_balance(message.author.id)

    if args[0].lower() == 'all':
        if balance <= 0:
            return await message.channel.send("You have no GRR coins to bet!", reference=message)
        bet_amount = balance
    else:
        try:
            bet_amount = int(args[0])
            if bet_amount <= 0:
                return await message.channel.send("You must bet a positive amount of GRR coins.", reference=message)
        except ValueError:
            return await message.channel.send(f"'{args[0]}' is not a valid number. Usage: `grr cf <amount|all> [t for tails]`", reference=message)

    if balance < bet_amount:
        return await message.channel.send(f"You can't bet **{bet_amount:,}** GRR, you only have **{balance:,}**.", reference=message)

    win_rate_str = await db.get_config_value('cf_win_rate', '0.31')
    win_rate = float(win_rate_str)

    await db.add_grr_coins(message.author.id, -bet_amount)
    initial_msg = await message.channel.send(f"Flipping a coin for **{bet_amount:,}** GRR... your choice is **{choice}**! 🪙", reference=message)
    await asyncio.sleep(2)

    win = random.random() < win_rate
    payout = bet_amount * 2

    if win:
        await db.add_grr_coins(message.author.id, payout)
        outcome_desc = f"The coin landed on **{choice}**! You win **{payout:,}** GRR!"
    else:
        actual_flip = "Tails" if choice == "Heads" else "Heads"
        outcome_desc = f"Tough luck! It was **{actual_flip}**. You lost **{bet_amount:,}** GRR."

    new_balance = await db.get_grr_balance(message.author.id)
    final_response = f"{message.author.mention}, {outcome_desc}\nYour new balance is **{new_balance:,}** GRR."
    await initial_msg.edit(content=final_response)
# --- MODIFICATION END ---


async def handle_grr_bet(message: discord.Message, args: list):
    """Handles the high-stakes, high-loss-chance bet command."""
    if not args:
        return await message.channel.send("Please specify an amount to bet! Ex: `grr bet 100`", reference=message)

    try:
        bet_amount = int(args[0])
        if bet_amount <= 0:
            return await message.channel.send("You must bet a positive amount of coins.", reference=message)
    except ValueError:
        return await message.channel.send("That's not a valid number! Please bet a whole number of coins.", reference=message)

    balance = await db.get_grr_balance(message.author.id)
    if balance < bet_amount:
        return await message.channel.send(f"You can't bet more than you have! Your balance is **{balance:,}** GRR.", reference=message)

    win_rate_str = await db.get_config_value('bet_win_rate', '0.29')
    win_rate = float(win_rate_str)

    await db.add_grr_coins(message.author.id, -bet_amount)

    win = random.random() < win_rate
    payout = 0

    if win:
        mu = bet_amount * 2.5
        sigma = bet_amount * 0.75
        payout = max(0, int(round(random.gauss(mu, sigma))))
        await db.add_grr_coins(message.author.id, payout)

    new_balance = await db.get_grr_balance(message.author.id)
    profit = payout - bet_amount

    if profit > 0:
        title = "🎉 High-Stakes Win! 🎉"
        result_text = f"You risked **{bet_amount:,}** and the universe rewarded you with **{payout:,}** GRR!"
    else:
        title = "💸 High-Stakes Loss 💸"
        result_text = f"You risked **{bet_amount:,}** and lost it all to the void."

    response = (f"{title}\n"
                f"{result_text}\n"
                f"**Profit/Loss:** {profit:+,} GRR | **New Balance:** {new_balance:,} GRR")
    await message.channel.send(response, reference=message)


async def handle_grr_pay(message: discord.Message, args: list):
    """Handles paying another user with GRR coins."""
    if not message.mentions or len(args) < 2:
        return await message.channel.send("Usage: `grr pay <@user> <amount>`", reference=message)

    recipient = message.mentions[0]
    sender = message.author
    
    amount_str = next((arg for arg in args if arg.isdigit()), None)
    if not amount_str:
        return await message.channel.send("Please provide a valid amount to pay.", reference=message)
    
    amount_val = int(amount_str)

    if amount_val <= 0:
        return await message.channel.send("You must pay a positive amount of GRR coins.", reference=message)
    if recipient.bot:
        return await message.channel.send("Bots do not care for your mortal currency.", reference=message)
    if recipient.id == sender.id:
        return await message.channel.send("You can't pay yourself.", reference=message)

    if await db.transfer_grr_coins(sender.id, recipient.id, amount_val):
        sender_balance = await db.get_grr_balance(sender.id)
        recipient_balance = await db.get_grr_balance(recipient.id)
        response = (f"💸 GRR Transfer Success! {sender.mention} sent **{amount_val:,}** GRR to {recipient.mention}.\n"
                    f"{sender.display_name}'s New Balance: **{sender_balance:,}** GRR\n"
                    f"{recipient.display_name}'s New Balance: **{recipient_balance:,}** GRR")
        await message.channel.send(response, reference=message)
    else:
        balance = await db.get_grr_balance(sender.id)
        response = f"🚫 Transfer Failed. You don't have enough GRR. You tried to send **{amount_val:,}** but only have **{balance:,}** GRR."
        await message.channel.send(response, reference=message)

async def handle_grr_set_winrate(message: discord.Message, args: list):
    """Handles `grr set-winrate <percentage> <cf|bet>`"""
    if not is_constellation_from_message(message):
        return await message.channel.send("The Star Stream does not recognize your Modifier.", reference=message, delete_after=10)

    if len(args) < 2:
        return await message.channel.send("Usage: `grr set-winrate <percentage> <cf | bet>`", reference=message)

    game = args[1].lower()
    if game not in ['cf', 'bet']:
        return await message.channel.send("Invalid game type. Use `cf` for coinflip or `bet` for the high-stakes game.", reference=message)

    try:
        percentage = float(args[0])
        if not (0 < percentage <= 100):
            raise ValueError("Percentage must be between 0 and 100.")
    except ValueError:
        return await message.channel.send(f"'{args[0]}' is not a valid percentage. Please provide a number (e.g., 31 for 31%).", reference=message)

    win_rate = percentage / 100.0
    config_key = f"{game}_win_rate"

    await db.set_config_value(config_key, str(win_rate))
    response = f"⚙️ Probability Adjusted! The win rate for `{game}` has been set to **{percentage:.2f}%** by {message.author.mention}."
    await message.channel.send(response, reference=message)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.content.lower().startswith('grr '):
        return

    parts = message.content.split()
    command = parts[0].lower()
    
    command_map = {
        'grr': {
            'cash': handle_grr_cash, 'bal': handle_grr_cash,
            'daily': handle_grr_daily,
            'exchange': handle_grr_exchange,
            'cf': handle_grr_cf,
            'bet': handle_grr_bet,
            'pay': handle_grr_pay, 'give': handle_grr_pay, 'payment': handle_grr_pay,
            'set-winrate': handle_grr_set_winrate,
        }
    }

    if command == 'grr' and len(parts) > 1:
        subcommand = parts[1].lower()
        args = parts[2:]
        if subcommand in command_map['grr']:
            await command_map['grr'][subcommand](message, args)
        else:
            await message.channel.send(f"Unknown subcommand `{subcommand}` for `grr`.", reference=message, delete_after=10)
    elif command == 'grr':
         await message.channel.send(f"Please specify a subcommand. Choices: `cash`, `daily`, `exchange`, `cf`, `bet`, `pay`", reference=message)


# --- AUTOCOMPLETE ---
async def autocomplete_shop_items(ctx: discord.AutocompleteContext):
    if not ctx.interaction.guild: return []
    items = await db.get_all_shop_items(ctx.interaction.guild.id)
    return [item['name'] for item in items if item['name'].lower().startswith(ctx.value.lower())]

# --- USER COMMANDS (SSC) ---
@bot.slash_command(name="balance", description=f"Examine your or another Incarnation's {CURRENCY_NAME} balance.")
async def balance(ctx: discord.ApplicationContext, user: discord.Option(discord.Member, "The Incarnation to view.", required=False)):
    target_user = user or ctx.author
    user_balance = await db.get_balance(target_user.id)

    embed = EmbedFactory.create(
        title=f"「{target_user.display_name}'s Fable」",
        description=f"This Incarnation holds **{user_balance:,}** {CURRENCY_SYMBOL}.",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=target_user.display_avatar.url)
    await ctx.respond(embed=embed)

@bot.slash_command(name="pay", description=f"Share your story by sending {CURRENCY_NAME}s to another.")
async def pay(ctx: discord.ApplicationContext, recipient: discord.Option(discord.Member, "The Incarnation to receive your story."), amount: discord.Option(int, "The amount of Coin to send.")):
    await ctx.defer()
    sender = ctx.author
    if amount <= 0:
        return await ctx.followup.send("A story's value must be positive.", ephemeral=True)
    if recipient.bot:
        return await ctx.followup.send("Dokkaebi do not trade in mortal currency.", ephemeral=True)
    if recipient.id == sender.id:
        return await ctx.followup.send("You cannot write a story for yourself.", ephemeral=True)

    if await db.transfer_coins(sender.id, recipient.id, amount):
        embed = EmbedFactory.create(
            title="「Fable Weaving」",
            description=f"A new story has been woven. You sent **{amount:,} {CURRENCY_SYMBOL}** to {recipient.mention}.",
            color=discord.Color.green()
        )
        await ctx.followup.send(embed=embed)

        log_embed = EmbedFactory.create(title="Akashic Record: Coin Transfer", color=discord.Color.from_rgb(100, 150, 255), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Sender", value=f"{sender.mention} (`{sender.id}`)", inline=True)
        log_embed.add_field(name="Recipient", value=f"{recipient.mention} (`{recipient.id}`)", inline=True)
        log_embed.add_field(name="Amount", value=f"**{amount:,} {CURRENCY_SYMBOL}**", inline=False)
        await send_log(log_embed)
    else:
        balance = await db.get_balance(sender.id)
        embed = EmbedFactory.create(title="「Transaction Failed」", description=f"Your Fable is insufficient. You only possess **{balance:,} {CURRENCY_SYMBOL}**.", color=discord.Color.red())
        await ctx.followup.send(embed=embed, ephemeral=True)

@bot.slash_command(name="leaderboard", description="View the Ranking Scenario for the wealthiest Incarnations.")
async def leaderboard(ctx: discord.ApplicationContext):
    await ctx.defer()

    top_users = await db.get_leaderboard(limit=10)
    embed = EmbedFactory.create(title="🏆「The Throne of the Absolute」🏆", color=discord.Color.blurple())
    if not top_users:
        embed.description = "The ranking is currently empty. No great Fables have been told."
        return await ctx.followup.send(embed=embed)

    desc = []
    for rank, record in enumerate(top_users, 1):
        try:
            user = bot.get_user(record['user_id']) or await bot.fetch_user(record['user_id'])
            user_display = user.mention
        except discord.NotFound:
            user_display = f"An Forgotten Incarnation (ID: {record['user_id']})"

        emoji = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"**#{rank}**"
        desc.append(f"{emoji} {user_display} — **{record['balance']:,} {CURRENCY_SYMBOL}**")

    embed.description = "\n".join(desc)
    await ctx.followup.send(embed=embed)

# --- CONSTELLATION COMMANDS ---
constellation_cmds = SlashCommandGroup("constellation", "Commands for managing the Star Stream.", guild_ids=[MAIN_GUILD_ID])

@constellation_cmds.command(name="generate", description=f"Bestow a Revelation of {CURRENCY_NAME}s.")
@commands.cooldown(1, 60, commands.BucketType.user)
async def generate(ctx: discord.ApplicationContext, amount: discord.Option(int, "The amount of the Revelation."), recipient: discord.Option(discord.Member, "The Incarnation to be blessed.")):
    await ctx.defer()
    if not is_constellation(ctx):
        return await ctx.followup.send("The Star Stream does not recognize your Modifier.", ephemeral=True)
    if amount <= 0:
        return await ctx.followup.send("A Revelation must have substance.", ephemeral=True)

    await db.add_coins(recipient.id, amount)

    embed = EmbedFactory.create(title="「Myth-Grade Fable Genesis」", description=f"The Constellation {ctx.author.mention} has bestowed a Revelation upon {recipient.mention}, granting them **{amount:,} {CURRENCY_SYMBOL}**.", color=discord.Color.from_rgb(0, 255, 255))
    await ctx.followup.send(embed=embed)

    log_embed = EmbedFactory.create(title="Akashic Record: Coin Generation", color=discord.Color.from_rgb(0, 255, 255), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="Constellation", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=True)
    log_embed.add_field(name="Recipient", value=f"{recipient.mention} (`{recipient.id}`)", inline=True)
    log_embed.add_field(name="Amount Generated", value=f"**{amount:,} {CURRENCY_SYMBOL}**", inline=False)
    await send_log(log_embed)

@generate.error
async def generate_error(ctx: discord.ApplicationContext, error: discord.DiscordException):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(f"Your Stigma is on cooldown. Try again in {error.retry_after:.2f} seconds.", ephemeral=True)

@constellation_cmds.command(name="confiscate", description=f"Judge an Incarnation and confiscate their {CURRENCY_NAME}s.")
async def confiscate(ctx: discord.ApplicationContext, amount: discord.Option(int, "The amount of Coin to confiscate."), recipient: discord.Option(discord.Member, "The Incarnation to be judged.")):
    await ctx.defer()
    if not is_constellation(ctx):
        return await ctx.followup.send("The Star Stream does not recognize your Modifier.", ephemeral=True)
    if amount <= 0:
        return await ctx.followup.send("A Judgment must have substance. The amount must be positive.", ephemeral=True)

    current_balance = await db.get_balance(recipient.id)
    amount_to_remove = min(amount, current_balance)
    await db.add_coins(recipient.id, -amount_to_remove)

    embed = EmbedFactory.create(title="「Probability Adjustment」", description=f"The Constellation {ctx.author.mention} has passed Judgment upon {recipient.mention}, confiscating **{amount_to_remove:,} {CURRENCY_SYMBOL}**.", color=discord.Color.dark_red())
    await ctx.followup.send(embed=embed)

    log_embed = EmbedFactory.create(title="Akashic Record: Coin Confiscation", color=discord.Color.dark_red(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="Constellation", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=True)
    log_embed.add_field(name="Incarnation Judged", value=f"{recipient.mention} (`{recipient.id}`)", inline=True)
    log_embed.add_field(name="Amount Confiscated", value=f"**{amount_to_remove:,} {CURRENCY_SYMBOL}**", inline=False)
    await send_log(log_embed)

bot.add_application_command(constellation_cmds)

# --- DOKKAEBI BAG (SHOP) COMMANDS ---
shop = SlashCommandGroup("shop", "Commands for the Dokkaebi Bag.")

@shop.command(name="add", description="[CONSTELLATION] Place a new Artifact in the Dokkaebi Bag.")
async def shop_add(ctx: discord.ApplicationContext,
                   name: discord.Option(str, "The unique name of the Artifact."),
                   cost: discord.Option(int, f"The price in {CURRENCY_SYMBOL}."),
                   reward_role: discord.Option(discord.Role, "The Stigma (Role) a user gets for buying this."),
                   one_time_buy: discord.Option(bool, "Is this a unique Artifact?"),
                   image_file: discord.Option(discord.Attachment, "Upload an image for the Artifact.", required=False)):
    await ctx.defer()
    if not is_constellation(ctx):
        return await ctx.followup.send("Only Constellations may stock the Dokkaebi Bag.", ephemeral=True)
    if not ctx.guild:
        return await ctx.followup.send("This Scenario can only be performed in a guild.", ephemeral=True)
    if cost <= 0:
        return await ctx.followup.send("Artifacts must have a positive cost.", ephemeral=True)

    image_url = image_file.url if image_file else None

    if await db.add_shop_item(ctx.guild.id, name, cost, reward_role.id, image_url, one_time_buy):
        embed = EmbedFactory.create(title="<Dokkaebi Bag Updated>", description=f"The Artifact **{name}** is now for sale!", color=discord.Color.blue())
        embed.add_field(name="Cost", value=f"{cost:,} {CURRENCY_SYMBOL}", inline=True)
        embed.add_field(name="Reward Stigma", value=reward_role.mention, inline=True)
        if one_time_buy: embed.add_field(name="Type", value="Hidden Piece (Unique)")
        if image_url: embed.set_thumbnail(url=image_url)
        await ctx.followup.send(embed=embed)

        log_embed = EmbedFactory.create(title="Akashic Record: Artifact Added", color=discord.Color.blue(), timestamp=discord.utils.utcnow(), author_name=f"Stocked by: {ctx.author.display_name}", author_icon=ctx.author.display_avatar.url)
        log_embed.add_field(name="Artifact Name", value=name, inline=True)
        log_embed.add_field(name="Cost", value=f"{cost:,} {CURRENCY_SYMBOL}", inline=True)
        log_embed.add_field(name="Reward Stigma", value=reward_role.mention, inline=False)
        log_embed.add_field(name="Is Unique?", value=str(one_time_buy), inline=True)
        await send_log(log_embed)
    else:
        await ctx.followup.send(f"An Artifact with the name '{name}' already exists in this channel.", ephemeral=True)

@shop.command(name="view", description="Peer into the Dokkaebi Bag.")
async def shop_view(ctx: discord.ApplicationContext):
    await ctx.defer()
    if not ctx.guild:
        return await ctx.followup.send("The Dokkaebi Bag only opens within a guild.", ephemeral=True)
    items = await db.get_all_shop_items(ctx.guild.id)
    embed = EmbedFactory.create(title=f"「{ctx.guild.name}'s Dokkaebi Bag」", color=discord.Color.dark_magenta())
    if not items:
        embed.description = "The Bag is currently empty. A Constellation must add Artifacts."
    else:
        desc = []
        for item in items:
            role = ctx.guild.get_role(item['role_id'])
            item_line = f"### {item['name']}\n**Cost:** {item['cost']:,} {CURRENCY_SYMBOL}\n**Reward:** {role.mention if role else '`Faded Stigma`'}\n"
            if item['is_one_time_buy']:
                if item['purchased_by_user_id']:
                    try:
                        purchaser = bot.get_user(item['purchased_by_user_id']) or await bot.fetch_user(item['purchased_by_user_id'])
                        purchaser_mention = purchaser.mention
                    except discord.NotFound:
                        purchaser_mention = f"Forgotten Incarnation (ID: {item['purchased_by_user_id']})"
                    item_line += f"**Status:** 🔴 CLAIMED (by {purchaser_mention})\n"
                else:
                    item_line += "**Type:** ✨ Hidden Piece (Unique)\n"
            desc.append(item_line)
        embed.description = "\n".join(desc)
    await ctx.followup.send(embed=embed)

@shop.command(name="buy", description="Make a contract to buy an Artifact.")
async def shop_buy(ctx: discord.ApplicationContext, name: discord.Option(str, "The name of the Artifact to buy.", autocomplete=autocomplete_shop_items)):
    await ctx.defer(ephemeral=True)

    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return await ctx.followup.send("Contracts can only be made in a guild.", ephemeral=True)
    item = await db.get_shop_item(ctx.guild.id, name)
    if not item:
        return await ctx.followup.send(f"The Star Stream cannot find an Artifact named '{name}'.", ephemeral=True)
    if item['is_one_time_buy'] and item['purchased_by_user_id']:
        return await ctx.followup.send("This Hidden Piece has already been claimed by another Incarnation.", ephemeral=True)

    user_balance = await db.get_balance(ctx.author.id)
    if user_balance < item['cost']:
        return await ctx.followup.send(f"Your Fable is insufficient. You need **{item['cost']:,} {CURRENCY_SYMBOL}** but only have **{user_balance:,}**.", ephemeral=True)

    role_to_grant = ctx.guild.get_role(item['role_id'])
    if not role_to_grant:
        return await ctx.followup.send("Error: The promised Stigma has faded from this world.", ephemeral=True)
    if role_to_grant in ctx.author.roles:
        return await ctx.followup.send("You already possess this Stigma.", ephemeral=True)
    if not ctx.guild.me.guild_permissions.manage_roles or role_to_grant.position >= ctx.guild.me.top_role.position:
        return await ctx.followup.send("Bot Error: This Dokkaebi cannot grant a Stigma of this station.", ephemeral=True)

    try:
        await db.add_coins(ctx.author.id, -item['cost'])
        await ctx.author.add_roles(role_to_grant, reason=f"Purchased Artifact '{item['name']}'")
        if item['is_one_time_buy']:
            await db.mark_item_as_purchased(item['item_id'], ctx.author.id)

        embed = EmbedFactory.create(title="「Contract Fulfilled」", description=f"You acquired the Artifact **{item['name']}** for **{item['cost']:,} {CURRENCY_SYMBOL}**.", color=discord.Color.green())
        embed.add_field(name="Stigma Acquired", value=f"You have been granted the {role_to_grant.mention} Stigma!")
        if item['image_url']: embed.set_thumbnail(url=item['image_url'])

        await ctx.author.send(embed=embed)
        await ctx.followup.send("Your contract has been fulfilled! I've sent the details to your DMs.", ephemeral=True)

        log_embed = EmbedFactory.create(title="Akashic Record: Artifact Purchase", color=discord.Color.purple(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Incarnation", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=False)
        log_embed.add_field(name="Artifact", value=item['name'], inline=True)
        log_embed.add_field(name="Cost", value=f"**{item['cost']:,} {CURRENCY_SYMBOL}**", inline=True)

        await send_log(log_embed)
        await send_purchase_log_to_constellations(log_embed)

    except Exception as e:
        print(f"An error occurred during purchase, refunding user. Error: {e}")
        await ctx.followup.send("A fatal error occurred in the Star Stream. The contract has been voided and your Coins returned.", ephemeral=True)
        await db.add_coins(ctx.author.id, item['cost']) # Refund on any failure

@shop.command(name="remove", description="[CONSTELLATION] Remove an Artifact from the Dokkaebi Bag.")
async def shop_remove(ctx: discord.ApplicationContext, name: discord.Option(str, "The name of the Artifact to remove.", autocomplete=autocomplete_shop_items)):
    await ctx.defer()
    if not is_constellation(ctx):
        return await ctx.followup.send("Only Constellations may alter the Dokkaebi Bag's contents.", ephemeral=True)
    if not ctx.guild:
        return await ctx.followup.send("This Scenario can only be performed in a guild.", ephemeral=True)

    if await db.remove_shop_item(ctx.guild.id, name):
        embed = EmbedFactory.create(title="<Artifact Removed>", description=f"Removed **{name}** from the Dokkaebi Bag.", color=discord.Color.orange())
        await ctx.followup.send(embed=embed)

        log_embed = EmbedFactory.create(title="Akashic Record: Artifact Removed", color=discord.Color.orange(), timestamp=discord.utils.utcnow(), author_name=f"Removed by: {ctx.author.display_name}", author_icon=ctx.author.display_avatar.url)
        log_embed.add_field(name="Artifact Name", value=name, inline=False)
        await send_log(log_embed)
    else:
        await ctx.followup.send(f"Could not find an Artifact named '{name}'.", ephemeral=True)

bot.add_application_command(shop)

# --- Run the bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Fatal Error: DISCORD_TOKEN not found in .env file. The Star Stream cannot connect.")
    else:
        bot.run(BOT_TOKEN)
