# database.py
import aiosqlite
from typing import List, Dict, Any, Optional

DB_FILE = "starstream.db"

async def init_db():
    """Initializes the database and creates tables if they don't exist."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                cost INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                image_url TEXT,
                is_one_time_buy BOOLEAN NOT NULL DEFAULT 0,
                purchased_by_user_id INTEGER,
                UNIQUE(guild_id, name)
            )
        ''')
        await db.commit()
    print("Database connection established and tables verified.")

async def _get_or_create_user(cursor, user_id: int):
    """Ensures a user exists in the database, creating them if not."""
    await cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    if await cursor.fetchone() is None:
        await cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, 0)", (user_id,))

async def get_balance(user_id: int) -> int:
    """Gets a user's balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await _get_or_create_user(cursor, user_id)
            await cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0

async def add_coins(user_id: int, amount: int):
    """Adds or removes coins from a user's balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await _get_or_create_user(cursor, user_id)
            await cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def transfer_coins(sender_id: int, recipient_id: int, amount: int) -> bool:
    """Atomically transfers coins from one user to another."""
    async with aiosqlite.connect(DB_FILE) as db:
        sender_balance = await get_balance(sender_id)
        if sender_balance < amount:
            return False
        async with db.cursor() as cursor:
            await _get_or_create_user(cursor, recipient_id)
            await cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, sender_id))
            await cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, recipient_id))
        await db.commit()
        return True

async def get_leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    """Gets the top N users by balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

# --- Shop Functions ---

async def add_shop_item(guild_id: int, name: str, cost: int, role_id: int, image_url: Optional[str], one_time_buy: bool) -> bool:
    """Adds a new item to the shop."""
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "INSERT INTO shop_items (guild_id, name, cost, role_id, image_url, is_one_time_buy) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, name, cost, role_id, image_url, one_time_buy)
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError: # Handles UNIQUE constraint violation
        return False

async def remove_shop_item(guild_id: int, name: str) -> bool:
    """Removes an item from the shop."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await cursor.execute("DELETE FROM shop_items WHERE guild_id = ? AND name = ?", (guild_id, name))
            await db.commit()
            return cursor.rowcount > 0

async def get_shop_item(guild_id: int, name: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single shop item by name."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM shop_items WHERE guild_id = ? AND name = ?", (guild_id, name)) as cursor:
            result = await cursor.fetchone()
            return dict(result) if result else None

async def get_all_shop_items(guild_id: int) -> List[Dict[str, Any]]:
    """Retrieves all shop items for a guild."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM shop_items WHERE guild_id = ? ORDER BY cost ASC", (guild_id,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def mark_item_as_purchased(item_id: int, user_id: int):
    """Marks a one-time-buy item as sold."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE shop_items SET purchased_by_user_id = ? WHERE item_id = ?", (user_id, item_id))
        await db.commit()
