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
# Import the new admin panel module
import admin_panel
# Import the new, advanced poker logic module
import poker_logic

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv('DISCORD_TOKEN')

try:
    ADMIN_LOG_CHANNEL_ID = int(os.getenv('ADMIN_LOG_CHANNEL_ID'))
except (TypeError, ValueError):
    ADMIN_LOG_CHANNEL_ID = None
    print("WARNING: ADMIN_LOG_CHANNEL_ID not found or invalid in .env file. Admin channel logging is disabled.")

CONSTELLATION_USER_IDS = [1374059561417441324, 1072508556907139133] # Replace with your admin user IDs
CONSTELLATION_ROLE_IDS = [1382422834965385318, 1382423081565425694] # Replace with your admin role IDs

CURRENCY_NAME = "Starstream Coin"
CURRENCY_SYMBOL = "SSC"

MAIN_GUILD_ID = 1382416574811734190 # Replace with your main guild ID
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
    author = ctx.author
    if author.id in CONSTELLATION_USER_IDS:
        return True
    if isinstance(author, discord.Member):
        author_role_ids = [role.id for role in author.roles]
        if any(role_id in CONSTELLATION_ROLE_IDS for role_id in author_role_ids):
            return True
    return False

def is_constellation_from_message(message: discord.Message) -> bool:
    author = message.author
    if author.id in CONSTELLATION_USER_IDS:
        return True
    if isinstance(author, discord.Member):
        author_role_ids = [role.id for role in author.roles]
        if any(role_id in CONSTELLATION_ROLE_IDS for role_id in author_role_ids):
            return True
    return False

# --- LOGGING & WEB SERVER ---
LOG_CACHE = collections.deque(maxlen=200)

async def send_log(embed: discord.Embed):
    if ADMIN_LOG_CHANNEL_ID:
        try:
            log_channel = bot.get_channel(ADMIN_LOG_CHANNEL_ID) or await bot.fetch_channel(ADMIN_LOG_CHANNEL_ID)
            await log_channel.send(embed=embed)
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"ERROR: Could not send to admin log channel ({ADMIN_LOG_CHANNEL_ID}). {e}")
        except Exception as e:
            print(f"ERROR: Failed to send log to admin channel. {e}")

    ts = f"<span class='timestamp'>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span>"
    title = f"<span class='title'>{html.escape(str(embed.title))}</span>" if embed.title else ""
    parts = [f"{ts}<br>{title}"]
    if embed.description:
        parts.append(html.escape(str(embed.description)))
    for field in embed.fields:
        parts.append(f"<span class='field-name'>{html.escape(field.name)}:</span><br>{html.escape(field.value)}")
    
    html_log = "<br>".join(parts)
    LOG_CACHE.append(html_log)
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
    print(f'Logged in as {bot.user} | The Star Stream is watching.')
    await db.init_db()
    await bot.sync_commands()
    print("All Scenarios (Slash Commands) have been synced with Discord.")
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

async def handle_grr_exchange(message: discord.Message, args: list):
    exchange_enabled = await db.get_config_value('exchange_enabled', 'false')
    if exchange_enabled != 'true':
        disabled_message = await db.get_config_value('exchange_disabled_message', 'The exchange is currently disabled by the Constellations.')
        await message.channel.send(disabled_message, reference=message)
        return
    try:
        grr_cost_str = await db.get_config_value('exchange_grr_cost', '5000')
        ssc_reward_str = await db.get_config_value('exchange_ssc_reward', '100')
        grr_cost = int(grr_cost_str)
        ssc_reward = int(ssc_reward_str)
    except (ValueError, TypeError):
        await message.channel.send("An error occurred with the exchange configuration. Please contact a Constellation.", reference=message)
        return
    user_id = message.author.id
    if await db.perform_grr_ssc_exchange(user_id, grr_cost, ssc_reward):
        new_grr_balance = await db.get_grr_balance(user_id)
        new_ssc_balance = await db.get_balance(user_id)
        response = (f"✅ Exchange successful! You traded **{grr_cost:,} GRR** for **{ssc_reward:,} {CURRENCY_SYMBOL}**.\n"
                    f"Your new balances are:\nGRR: **{new_grr_balance:,}**\n{CURRENCY_SYMBOL}: **{new_ssc_balance:,}**")
        await message.channel.send(response, reference=message)
    else:
        current_grr_balance = await db.get_grr_balance(user_id)
        response = f"🚫 Exchange failed. You need at least **{grr_cost:,} GRR** to make the exchange. You only have **{current_grr_balance:,}**."
        await message.channel.send(response, reference=message)

async def handle_grr_cf(message: discord.Message, args: list):
    if not args:
        return await message.channel.send("Usage: `grr cf <amount|all> [t for tails]`", reference=message)
    choice = "Tails" if len(args) > 1 and args[1].lower() == 't' else "Heads"
    balance = await db.get_grr_balance(message.author.id)
    if args[0].lower() == 'all':
        if balance <= 0: return await message.channel.send("You have no GRR coins to bet!", reference=message)
        bet_amount = balance
    else:
        try:
            bet_amount = int(args[0])
            if bet_amount <= 0: return await message.channel.send("You must bet a positive amount.", reference=message)
        except ValueError:
            return await message.channel.send(f"'{args[0]}' is not a valid number.", reference=message)
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

async def handle_grr_bet(message: discord.Message, args: list):
    if not args: return await message.channel.send("Usage: `grr bet <amount>`", reference=message)
    try:
        bet_amount = int(args[0])
        if bet_amount <= 0: return await message.channel.send("You must bet a positive amount.", reference=message)
    except ValueError:
        return await message.channel.send("That's not a valid number.", reference=message)
    balance = await db.get_grr_balance(message.author.id)
    if balance < bet_amount: return await message.channel.send(f"You can't bet more than you have! Your balance is **{balance:,}** GRR.", reference=message)
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
    title = "🎉 High-Stakes Win! 🎉" if profit > 0 else "💸 High-Stakes Loss 💸"
    result_text = f"You risked **{bet_amount:,}** and were rewarded with **{payout:,}** GRR!" if profit > 0 else f"You risked **{bet_amount:,}** and lost it all."
    response = (f"{title}\n{result_text}\n"
                f"**Profit/Loss:** {profit:+,} GRR | **New Balance:** {new_balance:,} GRR")
    await message.channel.send(response, reference=message)

async def handle_grr_slots(message: discord.Message, args: list):
    """Handles the slot machine game."""
    if not args:
        return await message.channel.send("Usage: `grr slots <amount|all>`", reference=message)

    balance = await db.get_grr_balance(message.author.id)

    if args[0].lower() == 'all':
        if balance <= 0:
            return await message.channel.send("You have no GRR coins to bet!", reference=message)
        bet_amount = balance
    else:
        try:
            bet_amount = int(args[0])
            if bet_amount <= 0:
                return await message.channel.send("You must bet a positive amount.", reference=message)
        except ValueError:
            return await message.channel.send(f"'{args[0]}' is not a valid number.", reference=message)

    if balance < bet_amount:
        return await message.channel.send(f"You can't bet **{bet_amount:,}** GRR, you only have **{balance:,}**.", reference=message)

    await db.add_grr_coins(message.author.id, -bet_amount)

    # Slot machine setup
    emojis = {
        "🍒": 5, "🍇": 5, "🍊": 5, # Common, 5x
        "🍋": 8, "🔔": 8, # Uncommon, 8x
        "💎": 15,          # Rare, 15x
        "🍀": 25,          # Very Rare, 25x
        "💰": 50           # Jackpot, 50x
    }
    
    # Weights for more realistic reel stops
    symbols = list(emojis.keys())
    weights = [10, 10, 10, 8, 8, 5, 3, 1] 

    initial_msg = await message.channel.send(f"Betting **{bet_amount:,} GRR**... Good luck!\n**[ ❓ | ❓ | ❓ ]**", reference=message)
    await asyncio.sleep(1)

    # Animation of spinning
    for _ in range(3): # Do 3 quick spins for animation
        reels = random.choices(symbols, k=3)
        await initial_msg.edit(content=f"Betting **{bet_amount:,} GRR**... Good luck!\n**[ {reels[0]} | {reels[1]} | {reels[2]} ]**")
        await asyncio.sleep(0.5)

    # Final result
    final_reels = random.choices(symbols, weights=weights, k=3)

    # Check for wins
    win = False
    payout = 0
    result_text = ""

    # Three of a kind (Jackpot)
    if final_reels[0] == final_reels[1] == final_reels[2]:
        win = True
        winning_symbol = final_reels[0]
        multiplier = emojis[winning_symbol]
        payout = bet_amount * multiplier
        result_text = f"🎉 **JACKPOT!** Three **{winning_symbol}**! You win **{payout:,}** GRR!"
    # Two of a kind (small win)
    elif final_reels[0] == final_reels[1] or final_reels[1] == final_reels[2]:
        win = True
        winning_symbol = final_reels[1] # The middle reel will be part of any 2-pair
        multiplier = 2 # Small win pays 2x the bet
        payout = bet_amount * multiplier
        result_text = f"👍 **Small Win!** Two **{winning_symbol}**! You win **{payout:,}** GRR!"

    if win:
        await db.add_grr_coins(message.author.id, payout)
    else:
        result_text = f"💸 Tough luck! You lost **{bet_amount:,}** GRR."

    new_balance = await db.get_grr_balance(message.author.id)
    final_content = (f"{message.author.mention}'s Spin:\n"
                     f"**[ {final_reels[0]} | {final_reels[1]} | {final_reels[2]} ]**\n\n"
                     f"{result_text}\n"
                     f"Your new balance is **{new_balance:,}** GRR.")

    await initial_msg.edit(content=final_content)

async def handle_grr_leaderboard(message: discord.Message, args: list):
    top_users = await db.get_grr_leaderboard(limit=10)
    if not top_users: return await message.channel.send("The leaderboard is empty.", reference=message)
    title = "🏆 **GRR Coin Leaderboard** 🏆\n"
    lines = []
    for rank, record in enumerate(top_users, 1):
        try:
            user = bot.get_user(record['user_id']) or await bot.fetch_user(record['user_id'])
            user_display = user.display_name
        except discord.NotFound:
            user_display = f"Forgotten User (ID: {record['user_id']})"
        emoji = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"**#{rank}**"
        lines.append(f"{emoji} {user_display} - **{record['balance']:,}** GRR")
    response = title + "\n".join(lines)
    await message.channel.send(response, reference=message)

async def handle_grr_pay(message: discord.Message, args: list):
    if not message.mentions or len(args) < 2: return await message.channel.send("Usage: `grr pay <@user> <amount>`", reference=message)
    recipient, sender = message.mentions[0], message.author
    amount_str = next((arg for arg in args if arg.isdigit()), None)
    if not amount_str: return await message.channel.send("Please provide a valid amount.", reference=message)
    amount = int(amount_str)
    if amount <= 0: return await message.channel.send("You must pay a positive amount.", reference=message)
    if recipient.bot or recipient.id == sender.id: return await message.channel.send("You can't pay that user.", reference=message)
    if await db.transfer_grr_coins(sender.id, recipient.id, amount):
        s_bal, r_bal = await db.get_grr_balance(sender.id), await db.get_grr_balance(recipient.id)
        response = (f"💸 Transfer Success! {sender.mention} sent **{amount:,}** GRR to {recipient.mention}.\n"
                    f"{sender.display_name}'s New Balance: **{s_bal:,}** GRR\n"
                    f"{recipient.display_name}'s New Balance: **{r_bal:,}** GRR")
        await message.channel.send(response, reference=message)
    else:
        bal = await db.get_grr_balance(sender.id)
        response = f"🚫 Transfer Failed. You only have **{bal:,}** GRR."
        await message.channel.send(response, reference=message)

async def handle_grr_set_winrate(message: discord.Message, args: list):
    if not is_constellation_from_message(message): return await message.channel.send("The Star Stream does not recognize your Modifier.", reference=message, delete_after=10)
    if len(args) < 2: return await message.channel.send("Usage: `grr set-winrate <percentage> <cf | bet>`", reference=message)
    game = args[1].lower()
    if game not in ['cf', 'bet']: return await message.channel.send("Invalid game type. Use `cf` or `bet`.", reference=message)
    try:
        percentage = float(args[0])
        if not (0 < percentage <= 100): raise ValueError
    except ValueError:
        return await message.channel.send(f"'{args[0]}' is not a valid percentage.", reference=message)
    win_rate = percentage / 100.0
    await db.set_config_value(f"{game}_win_rate", str(win_rate))
    await message.channel.send(f"⚙️ Probability Adjusted! The win rate for `{game}` is now **{percentage:.2f}%**.", reference=message)

# --- NEW/REFINED POKER HANDLERS ---
async def _send_table_status(channel, table: poker_logic.PokerTable, title_override=None):
    if not table: return

    stage_titles = {
        poker_logic.GameStage.BETTING_ROUND_1: "First Betting Round",
        poker_logic.GameStage.DISCARD_ROUND: "Discard Round",
        poker_logic.GameStage.BETTING_ROUND_2: "Second Betting Round",
    }
    title = title_override or stage_titles.get(table.stage, "Poker Table")
    color = discord.Color.dark_green()
    
    turn_player_user = None
    if table.stage in [poker_logic.GameStage.BETTING_ROUND_1, poker_logic.GameStage.BETTING_ROUND_2]:
        turn_player = table.players[table.turn_index]
        turn_player_user = await bot.fetch_user(turn_player.user_id)
    
    desc = f"**Total Pot:** {table.pot + sum(p.bet_in_round for p in table.players):,} GRR\n"
    if turn_player_user:
        desc += f"**Turn:** {turn_player_user.mention}\n"
        desc += f"**Bet to Match:** {table.current_bet_to_match:,} GRR\n"
    elif table.stage == poker_logic.GameStage.DISCARD_ROUND:
        desc += "**Action:** All players can now `grr discard` or `grr stand`."

    embed = discord.Embed(title=f"🃏 {title} 🃏", description=desc, color=color)

    for p in table.players:
        user = await bot.fetch_user(p.user_id)
        status = p.last_action
        if p.is_folded: status = "Folded"
        player_info = f"Bet this round: {p.bet_in_round:,} GRR\nStatus: {status}"
        embed.add_field(name=f"Player: {user.display_name}", value=player_info, inline=True)
    
    await channel.send(embed=embed)

async def _handle_showdown(channel, table: poker_logic.PokerTable):
    results = table.determine_winners()
    embed = discord.Embed(title="🃏 Showdown! 🃏", color=discord.Color.gold())
    
    # Display all non-folded hands
    for p in table.active_players:
        user = await bot.fetch_user(p.user_id)
        hand_eval = poker_logic.evaluate_hand_detailed(p.hand)
        hand_name = poker_logic.get_hand_name(hand_eval).capitalize()
        hand_str = poker_logic.format_hand(p.hand)
        embed.add_field(name=f"{user.display_name}'s Hand", value=f"{hand_str}\n({hand_name})", inline=False)

    # Announce winners and distribute pot
    result_descs = []
    for pot_share, hand_name, winner_ids in results:
        mentions = []
        for uid in winner_ids:
            await db.add_grr_coins(uid, pot_share)
            user = await bot.fetch_user(uid)
            mentions.append(user.mention)
        
        result_descs.append(f"**{' and '.join(mentions)} win {pot_share:,} GRR with {hand_name}!**")

    embed.description = "\n".join(result_descs)
    await channel.send(embed=embed)
    poker_logic.end_table(channel.id)

async def _check_betting_round_end(message, table):
    if table.is_betting_round_over():
        table.advance_stage()
        await message.channel.send(f"**Betting round is over! Moving to the {table.stage.name.replace('_', ' ')}.**")
        
        if table.stage == poker_logic.GameStage.SHOWDOWN:
            await _handle_showdown(message.channel, table)
        else:
            await _send_table_status(message.channel, table)

async def handle_grr_poker(message: discord.Message, args: list):
    if poker_logic.find_table(message.channel.id):
        return await message.channel.send("A poker game is already in progress in this channel.", reference=message)
    try:
        bet = int(args[0])
        if bet <= 0: raise ValueError
    except (ValueError, IndexError):
        return await message.channel.send("Usage: `grr poker <bet> [single|multi]`", reference=message)
    balance = await db.get_grr_balance(message.author.id)
    if balance < bet:
        return await message.channel.send(f"You don't have enough to cover the initial bet of {bet:,} GRR.", reference=message)

    game_type = poker_logic.GameType.MULTI_PLAYER if len(args) > 1 and args[1].lower() == "multi" else poker_logic.GameType.SINGLE_PLAYER
    
    await db.add_grr_coins(message.author.id, -bet)
    table = poker_logic.create_table(message.channel.id, game_type, message.author.id, bet)

    if game_type == poker_logic.GameType.SINGLE_PLAYER:
        table.pot = bet
        table.stage = poker_logic.GameStage.DISCARD_ROUND # Skip betting for single player
        table.start_game()
        player = table.get_player(message.author.id)
        hand_str = poker_logic.format_hand(player.hand)
        response = (f"**Single Player Poker**\n{message.author.mention}, you bet **{bet:,} GRR**.\n\n"
                    f"**Your Hand:** {hand_str}\n"
                    f"**Cards:**       `  1  `   `  2  `   `  3  `   `  4  `   `  5  `\n\n"
                    f"Use `grr discard <numbers>` or `grr stand`.")
        await message.channel.send(response, reference=message)
    else:
        response = (f"**Multiplayer Poker Table Created!**\n"
                    f"{message.author.mention} has started a table with an initial bet of **{bet:,} GRR**.\n"
                    f"Others can type `grr join {bet}` to play.\n"
                    f"The starter ({message.author.mention}) types `grr start` to begin the game.")
        await message.channel.send(response, reference=message)

async def handle_grr_join(message: discord.Message, args: list):
    table = poker_logic.find_table(message.channel.id)
    if not table or table.stage != poker_logic.GameStage.WAITING_FOR_PLAYERS:
        return await message.channel.send("No game to join or it has already started.", reference=message)
    if table.get_player(message.author.id):
        return await message.channel.send("You are already at the table.", reference=message)
    
    try:
        bet = int(args[0])
        initial_bet = table.players[0].initial_bet
        if bet != initial_bet:
            return await message.channel.send(f"You must join with the same bet: **{initial_bet:,} GRR**.", reference=message)
    except (ValueError, IndexError):
        return await message.channel.send(f"Usage: `grr join <bet>`", reference=message)

    balance = await db.get_grr_balance(message.author.id)
    if balance < bet:
        return await message.channel.send(f"You don't have enough to join with a {bet:,} GRR bet.", reference=message)

    await db.add_grr_coins(message.author.id, -bet)
    table.add_player(message.author.id, bet)
    await message.channel.send(f"{message.author.mention} has joined the table!", reference=message)

async def handle_grr_start(message: discord.Message, args: list):
    table = poker_logic.find_table(message.channel.id)
    if not table or table.starter_id != message.author.id or table.stage != poker_logic.GameStage.WAITING_FOR_PLAYERS:
        return # Silently fail
    
    await message.channel.send("The game is starting! Dealing cards now...")
    table.start_game()
    
    for p in table.players:
        user = await bot.fetch_user(p.user_id)
        hand_str = poker_logic.format_hand(p.hand)
        await user.send(f"Your hand for the game in **#{message.channel.name}**:\n{hand_str}")
    
    await _send_table_status(message.channel, table)

async def handle_grr_discard(message: discord.Message, args: list):
    table = poker_logic.find_table(message.channel.id)
    player = table.get_player(message.author.id) if table else None
    
    if not player or table.stage != poker_logic.GameStage.DISCARD_ROUND or player.has_discarded:
        return

    try:
        indices = sorted([int(i) - 1 for i in args], reverse=True)
        if any(i < 0 or i > 4 for i in indices) or len(set(indices)) != len(indices):
            raise ValueError
    except ValueError:
        return await message.channel.send("Invalid input. Use card numbers 1-5. Ex: `grr discard 1 4`", reference=message)

    num_discarded = len(indices)
    new_cards = table.deck.deal(num_discarded)
    for index in indices: player.hand.pop(index)
    player.hand.extend(new_cards)
    player.has_discarded = True
    
    hand_str = poker_logic.format_hand(player.hand)
    await message.author.send(f"Your new hand: {hand_str}")
    await message.channel.send(f"{message.author.mention} has discarded {num_discarded} card(s).", delete_after=10)
    
    if table.game_type == poker_logic.GameType.SINGLE_PLAYER:
        # Payout based on video poker for single player
        payout_multipliers = {9: 250, 8: 50, 7: 25, 6: 9, 5: 6, 4: 4, 3: 3, 2: 2, 1: 1, 0: 0} # Royal, SF, 4K, FH, F, S, 3K, 2P, JoB
        hand_eval = poker_logic.evaluate_hand_detailed(player.hand)
        hand_rank = hand_eval[0]
        # Jacks or Better check for one pair
        if hand_rank == 1 and hand_eval[1] < poker_logic.RANK_VALUES['J']:
            hand_rank = 0
            
        winnings = table.pot * payout_multipliers.get(hand_rank, 0)
        hand_name = poker_logic.get_hand_name(hand_eval)
        if winnings > 0:
            await db.add_grr_coins(player.user_id, winnings)
            await message.channel.send(f"Congratulations! You got **{hand_name}** and won **{winnings:,}** GRR!")
        else:
            await message.channel.send(f"Tough luck. You got **{hand_name}** and lost your bet.")
        poker_logic.end_table(message.channel.id)

    elif all(p.is_folded or p.has_discarded for p in table.players):
        table.advance_stage()
        await message.channel.send("**All players have acted! Moving to the second betting round.**")
        table.advance_turn() # Set turn to first active player
        await _send_table_status(message.channel, table)

async def handle_grr_stand(message: discord.Message, args: list):
    await handle_grr_discard(message, [])

async def handle_grr_fold(message: discord.Message, args: list):
    table = poker_logic.find_table(message.channel.id)
    player = table.get_player(message.author.id) if table else None
    if not player or player.is_folded or table.players[table.turn_index].user_id != player.user_id: return
    
    player.is_folded = True
    player.last_action = "Folded"
    await message.channel.send(f"{message.author.mention} has folded.", reference=message)
    
    active_players = table.active_players
    if len(active_players) <= 1:
        await _handle_showdown(message.channel, table)
    else:
        table.advance_turn()
        await _send_table_status(message.channel, table, "Player Folded")

async def handle_grr_check(message: discord.Message, args: list):
    table = poker_logic.find_table(message.channel.id)
    player = table.get_player(message.author.id) if table else None
    if not player or player.is_folded or table.players[table.turn_index].user_id != player.user_id: return
    
    if player.bet_in_round < table.current_bet_to_match:
        return await message.channel.send(f"You can't check, there's a bet of {table.current_bet_to_match:,} GRR to you. Use `grr call` or `grr raise`.", reference=message)
        
    player.has_acted = True
    player.last_action = "Checked"
    await message.channel.send(f"{message.author.mention} has checked.", reference=message)
    
    if table.is_betting_round_over():
        await _check_betting_round_end(message, table)
    else:
        table.advance_turn()
        await _send_table_status(message.channel, table)

async def handle_grr_call(message: discord.Message, args: list):
    table = poker_logic.find_table(message.channel.id)
    player = table.get_player(message.author.id) if table else None
    if not player or player.is_folded or table.players[table.turn_index].user_id != player.user_id: return

    amount_to_call = table.current_bet_to_match - player.bet_in_round
    if amount_to_call <= 0:
        return await message.channel.send("There is no bet to call. You can `grr check`.", reference=message)

    balance = await db.get_grr_balance(player.user_id)
    if balance < amount_to_call:
        return await message.channel.send(f"You don't have enough GRR to call. You need {amount_to_call:,} more.", reference=message)

    await db.add_grr_coins(player.user_id, -amount_to_call)
    player.bet_in_round += amount_to_call
    player.has_acted = True
    player.last_action = f"Called {table.current_bet_to_match:,}"
    await message.channel.send(f"{message.author.mention} has called.", reference=message)
    
    if table.is_betting_round_over():
        await _check_betting_round_end(message, table)
    else:
        table.advance_turn()
        await _send_table_status(message.channel, table)

async def handle_grr_raise(message: discord.Message, args: list):
    table = poker_logic.find_table(message.channel.id)
    player = table.get_player(message.author.id) if table else None
    if not player or player.is_folded or table.players[table.turn_index].user_id != player.user_id: return

    try:
        raise_amount = int(args[0])
        if raise_amount <= table.current_bet_to_match:
            return await message.channel.send(f"You must raise to an amount higher than the current bet of {table.current_bet_to_match:,} GRR.", reference=message)
    except (ValueError, IndexError):
        return await message.channel.send("Usage: `grr raise <total_amount>`", reference=message)

    amount_needed = raise_amount - player.bet_in_round
    balance = await db.get_grr_balance(player.user_id)
    if balance < amount_needed:
        return await message.channel.send(f"You don't have enough GRR to raise to that amount. You need {amount_needed:,} more.", reference=message)

    await db.add_grr_coins(player.user_id, -amount_needed)
    player.bet_in_round += amount_needed
    table.current_bet_to_match = player.bet_in_round
    
    # Reset 'has_acted' for all other players so they get a chance to call the new raise
    for p in table.active_players:
        if p.user_id != player.user_id:
            p.has_acted = False

    player.has_acted = True
    player.last_action = f"Raised to {raise_amount:,}"
    await message.channel.send(f"{message.author.mention} has raised the bet to **{raise_amount:,} GRR**!", reference=message)

    table.advance_turn()
    await _send_table_status(message.channel, table)


# --- MAIN MESSAGE ROUTER ---
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.content.lower().startswith('grr '):
        return

    parts = message.content.lower().split()
    command_args = message.content.split()[2:]
    
    command_map = {
        'cash': handle_grr_cash, 'bal': handle_grr_cash,
        'daily': handle_grr_daily,
        'exchange': handle_grr_exchange,
        'cf': handle_grr_cf,
        'bet': handle_grr_bet,
        'slots': handle_grr_slots,
        'leaderboard': handle_grr_leaderboard, 'lb': handle_grr_leaderboard,
        'pay': handle_grr_pay, 'give': handle_grr_pay,
        'set-winrate': handle_grr_set_winrate,
        # Poker commands
        'poker': handle_grr_poker,
        'join': handle_grr_join,
        'start': handle_grr_start,
        'discard': handle_grr_discard,
        'stand': handle_grr_stand,
        'check': handle_grr_check,
        'call': handle_grr_call,
        'raise': handle_grr_raise,
        'fold': handle_grr_fold,
    }

    if len(parts) > 1:
        subcommand = parts[1]
        if subcommand in command_map:
            await command_map[subcommand](message, command_args)
        else:
            await message.channel.send(f"Unknown subcommand `{subcommand}`.", reference=message, delete_after=10)
    else:
        await message.channel.send(f"Please specify a subcommand.", reference=message, delete_after=10)

# --- AUTOCOMPLETE & SLASH COMMANDS ---
async def autocomplete_shop_items(ctx: discord.AutocompleteContext):
    if not ctx.interaction.guild: return []
    items = await db.get_all_shop_items(ctx.interaction.guild.id)
    return [item['name'] for item in items if item['name'].lower().startswith(ctx.value.lower())]

@bot.slash_command(name="balance", description=f"Examine your or another Incarnation's {CURRENCY_NAME} balance.")
async def balance(ctx: discord.ApplicationContext, user: discord.Option(discord.Member, "The Incarnation to view.", required=False)):
    target_user = user or ctx.author
    user_balance = await db.get_balance(target_user.id)
    embed = EmbedFactory.create(title=f"「{target_user.display_name}'s Fable」", description=f"This Incarnation holds **{user_balance:,}** {CURRENCY_SYMBOL}.", color=discord.Color.gold())
    embed.set_thumbnail(url=target_user.display_avatar.url)
    await ctx.respond(embed=embed)

@bot.slash_command(name="pay", description=f"Share your story by sending {CURRENCY_NAME}s to another.")
async def pay(ctx: discord.ApplicationContext, recipient: discord.Option(discord.Member, "The Incarnation to receive your story."), amount: discord.Option(int, "The amount of Coin to send.")):
    await ctx.defer()
    sender = ctx.author
    if amount <= 0: return await ctx.followup.send("A story's value must be positive.", ephemeral=True)
    if recipient.bot or recipient.id == sender.id: return await ctx.followup.send("You cannot write a story for that user.", ephemeral=True)
    if await db.transfer_coins(sender.id, recipient.id, amount):
        embed = EmbedFactory.create(title="「Fable Weaving」", description=f"A new story has been woven. You sent **{amount:,} {CURRENCY_SYMBOL}** to {recipient.mention}.", color=discord.Color.green())
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
        embed.description = "The ranking is currently empty."
        return await ctx.followup.send(embed=embed)
    desc = []
    for rank, record in enumerate(top_users, 1):
        try:
            user = bot.get_user(record['user_id']) or await bot.fetch_user(record['user_id'])
            user_display = user.mention
        except discord.NotFound:
            user_display = f"A Forgotten Incarnation (ID: {record['user_id']})"
        emoji = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"**#{rank}**"
        desc.append(f"{emoji} {user_display} — **{record['balance']:,} {CURRENCY_SYMBOL}**")
    embed.description = "\n".join(desc)
    await ctx.followup.send(embed=embed)

constellation_cmds = SlashCommandGroup("constellation", "Commands for managing the Star Stream.", guild_ids=[MAIN_GUILD_ID])

@constellation_cmds.command(name="generate", description=f"Bestow a Revelation of {CURRENCY_NAME}s.")
@commands.cooldown(1, 60, commands.BucketType.user)
async def generate(ctx: discord.ApplicationContext, amount: discord.Option(int, "The amount of the Revelation."), recipient: discord.Option(discord.Member, "The Incarnation to be blessed.")):
    await ctx.defer()
    if not is_constellation(ctx): return await ctx.followup.send("The Star Stream does not recognize your Modifier.", ephemeral=True)
    if amount <= 0: return await ctx.followup.send("A Revelation must have substance.", ephemeral=True)
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
    if not is_constellation(ctx): return await ctx.followup.send("The Star Stream does not recognize your Modifier.", ephemeral=True)
    if amount <= 0: return await ctx.followup.send("A Judgment must have substance.", ephemeral=True)
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
shop = SlashCommandGroup("shop", "Commands for the Dokkaebi Bag.")

@shop.command(name="add", description="[CONSTELLATION] Place a new Artifact in the Dokkaebi Bag.")
async def shop_add(ctx: discord.ApplicationContext, name: discord.Option(str, "The unique name of the Artifact."), cost: discord.Option(int, f"The price in {CURRENCY_SYMBOL}."), reward_role: discord.Option(discord.Role, "The Stigma (Role) a user gets for buying this."), one_time_buy: discord.Option(bool, "Is this a unique Artifact?"), image_file: discord.Option(discord.Attachment, "Upload an image for the Artifact.", required=False)):
    await ctx.defer()
    if not is_constellation(ctx): return await ctx.followup.send("Only Constellations may stock the Dokkaebi Bag.", ephemeral=True)
    if not ctx.guild: return await ctx.followup.send("This Scenario can only be performed in a guild.", ephemeral=True)
    if cost <= 0: return await ctx.followup.send("Artifacts must have a positive cost.", ephemeral=True)
    image_url = image_file.url if image_file else None
    if await db.add_shop_item(ctx.guild.id, name, cost, reward_role.id, image_url, one_time_buy):
        embed = EmbedFactory.create(title="<Dokkaebi Bag Updated>", description=f"The Artifact **{name}** is now for sale!", color=discord.Color.blue())
        embed.add_field(name="Cost", value=f"{cost:,} {CURRENCY_SYMBOL}", inline=True)
        embed.add_field(name="Reward Stigma", value=reward_role.mention, inline=True)
        if one_time_buy: embed.add_field(name="Type", value="Hidden Piece (Unique)")
        if image_url: embed.set_thumbnail(url=image_url)
        await ctx.followup.send(embed=embed)
        log_embed = EmbedFactory.create(title="Akashic Record: Artifact Added", color=discord.Color.blue(), timestamp=discord.utils.utcnow(), author_name=f"Stocked by: {ctx.author.display_name}", author_icon=ctx.author.display_avatar.url)
        log_embed.add_field(name="Artifact Name", value=name, inline=True); log_embed.add_field(name="Cost", value=f"{cost:,} {CURRENCY_SYMBOL}", inline=True); log_embed.add_field(name="Reward Stigma", value=reward_role.mention, inline=False); log_embed.add_field(name="Is Unique?", value=str(one_time_buy), inline=True)
        await send_log(log_embed)
    else:
        await ctx.followup.send(f"An Artifact with the name '{name}' already exists.", ephemeral=True)

@shop.command(name="view", description="Peer into the Dokkaebi Bag.")
async def shop_view(ctx: discord.ApplicationContext):
    await ctx.defer()
    if not ctx.guild: return await ctx.followup.send("The Dokkaebi Bag only opens within a guild.", ephemeral=True)
    items = await db.get_all_shop_items(ctx.guild.id)
    embed = EmbedFactory.create(title=f"「{ctx.guild.name}'s Dokkaebi Bag」", color=discord.Color.dark_magenta())
    if not items:
        embed.description = "The Bag is currently empty."
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
                        purchaser_mention = f"Forgotten Incarnation"
                    item_line += f"**Status:** 🔴 CLAIMED (by {purchaser_mention})\n"
                else:
                    item_line += "**Type:** ✨ Hidden Piece (Unique)\n"
            desc.append(item_line)
        embed.description = "\n".join(desc)
    await ctx.followup.send(embed=embed)

@shop.command(name="buy", description="Make a contract to buy an Artifact.")
async def shop_buy(ctx: discord.ApplicationContext, name: discord.Option(str, "The name of the Artifact to buy.", autocomplete=autocomplete_shop_items)):
    await ctx.defer(ephemeral=True)
    if not ctx.guild or not isinstance(ctx.author, discord.Member): return await ctx.followup.send("Contracts can only be made in a guild.", ephemeral=True)
    item = await db.get_shop_item(ctx.guild.id, name)
    if not item: return await ctx.followup.send(f"Cannot find an Artifact named '{name}'.", ephemeral=True)
    if item['is_one_time_buy'] and item['purchased_by_user_id']: return await ctx.followup.send("This Hidden Piece has already been claimed.", ephemeral=True)
    user_balance = await db.get_balance(ctx.author.id)
    if user_balance < item['cost']: return await ctx.followup.send(f"Your Fable is insufficient. You need **{item['cost']:,} {CURRENCY_SYMBOL}**.", ephemeral=True)
    role_to_grant = ctx.guild.get_role(item['role_id'])
    if not role_to_grant: return await ctx.followup.send("Error: The promised Stigma has faded.", ephemeral=True)
    if role_to_grant in ctx.author.roles: return await ctx.followup.send("You already possess this Stigma.", ephemeral=True)
    if not ctx.guild.me.guild_permissions.manage_roles or role_to_grant.position >= ctx.guild.me.top_role.position:
        return await ctx.followup.send("Bot Error: This Dokkaebi cannot grant a Stigma of this station.", ephemeral=True)
    try:
        await db.add_coins(ctx.author.id, -item['cost'])
        await ctx.author.add_roles(role_to_grant, reason=f"Purchased Artifact '{item['name']}'")
        if item['is_one_time_buy']: await db.mark_item_as_purchased(item['item_id'], ctx.author.id)
        embed = EmbedFactory.create(title="「Contract Fulfilled」", description=f"You acquired **{item['name']}** for **{item['cost']:,} {CURRENCY_SYMBOL}**.", color=discord.Color.green())
        embed.add_field(name="Stigma Acquired", value=f"You have been granted the {role_to_grant.mention} Stigma!")
        if item['image_url']: embed.set_thumbnail(url=item['image_url'])
        await ctx.author.send(embed=embed)
        await ctx.followup.send("Contract fulfilled! Details sent to your DMs.", ephemeral=True)
        log_embed = EmbedFactory.create(title="Akashic Record: Artifact Purchase", color=discord.Color.purple(), timestamp=discord.utils.utcnow())
        log_embed.add_field(name="Incarnation", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=False)
        log_embed.add_field(name="Artifact", value=item['name'], inline=True)
        log_embed.add_field(name="Cost", value=f"**{item['cost']:,} {CURRENCY_SYMBOL}**", inline=True)
        await send_log(log_embed); await send_purchase_log_to_constellations(log_embed)
    except Exception as e:
        print(f"Purchase error, refunding. Error: {e}")
        await ctx.followup.send("A fatal error occurred. The contract is voided and Coins returned.", ephemeral=True)
        await db.add_coins(ctx.author.id, item['cost'])

@shop.command(name="remove", description="[CONSTELLATION] Remove an Artifact from the Dokkaebi Bag.")
async def shop_remove(ctx: discord.ApplicationContext, name: discord.Option(str, "The name of the Artifact to remove.", autocomplete=autocomplete_shop_items)):
    await ctx.defer()
    if not is_constellation(ctx): return await ctx.followup.send("Only Constellations may alter the Bag's contents.", ephemeral=True)
    if not ctx.guild: return await ctx.followup.send("This can only be performed in a guild.", ephemeral=True)
    if await db.remove_shop_item(ctx.guild.id, name):
        embed = EmbedFactory.create(title="<Artifact Removed>", description=f"Removed **{name}** from the Dokkaebi Bag.", color=discord.Color.orange())
        await ctx.followup.send(embed=embed)
        log_embed = EmbedFactory.create(title="Akashic Record: Artifact Removed", color=discord.Color.orange(), timestamp=discord.utils.utcnow(), author_name=f"Removed by: {ctx.author.display_name}", author_icon=ctx.author.display_avatar.url)
        log_embed.add_field(name="Artifact Name", value=name, inline=False)
        await send_log(log_embed)
    else:
        await ctx.followup.send(f"Could not find an Artifact named '{name}'.", ephemeral=True)

bot.add_application_command(shop)

# --- RUN BOT ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Fatal Error: DISCORD_TOKEN not found in .env file.")
    else:
        bot.run(BOT_TOKEN)