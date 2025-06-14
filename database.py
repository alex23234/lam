import aiosqlite
from typing import List, Dict, Any, Optional
from datetime import date

DB_FILE = "starstream.db"

# --- Database Initialization ---
async def init_db():
    """Initializes the database and creates tables if they don't exist."""
    async with aiosqlite.connect(DB_FILE) as db:
        # --- SSC User table ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0
            )
        ''')
        # --- Shop table ---
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
        # --- GRR Coin User table ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS grr_users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                last_daily TEXT
            )
        ''')
        # --- Config table ---
        await db.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        await db.commit()
    print("Database connection established and tables (users, shop_items, grr_users, config) verified.")

# --- USER & CURRENCY FUNCTIONS (Combined & Refined) ---

async def _get_or_create_user(cursor, user_id: int):
    """Ensures a user exists in the 'users' (SSC) table, creating them if not."""
    await cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
    if await cursor.fetchone() is None:
        await cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, 0)", (user_id,))

async def _get_or_create_grr_user(cursor, user_id: int):
    """Ensures a user exists in the 'grr_users' table, creating them if not."""
    await cursor.execute("SELECT 1 FROM grr_users WHERE user_id = ?", (user_id,))
    if await cursor.fetchone() is None:
        await cursor.execute("INSERT INTO grr_users (user_id, balance, last_daily) VALUES (?, 0, NULL)", (user_id,))

async def get_balance(user_id: int) -> int:
    """Gets a user's SSC balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await _get_or_create_user(cursor, user_id)
            await cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0

async def add_coins(user_id: int, amount: int):
    """Adds or removes SSC coins from a user's balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await _get_or_create_user(cursor, user_id)
            await cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def transfer_coins(sender_id: int, recipient_id: int, amount: int) -> bool:
    """Atomically transfers SSC coins from one user to another."""
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

async def get_grr_balance(user_id: int) -> int:
    """Gets a user's GRR balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await _get_or_create_grr_user(cursor, user_id)
            await cursor.execute("SELECT balance FROM grr_users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0

async def add_grr_coins(user_id: int, amount: int):
    """Adds or removes GRR coins from a user's balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await _get_or_create_grr_user(cursor, user_id)
            await cursor.execute("UPDATE grr_users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def transfer_grr_coins(sender_id: int, recipient_id: int, amount: int) -> bool:
    """Atomically transfers GRR coins from one user to another."""
    async with aiosqlite.connect(DB_FILE) as db:
        sender_balance = await get_grr_balance(sender_id)
        if sender_balance < amount:
            return False
        async with db.cursor() as cursor:
            await _get_or_create_grr_user(cursor, recipient_id)
            await cursor.execute("UPDATE grr_users SET balance = balance - ? WHERE user_id = ?", (amount, sender_id))
            await cursor.execute("UPDATE grr_users SET balance = balance + ? WHERE user_id = ?", (amount, recipient_id))
        await db.commit()
        return True

async def get_leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    """Gets the top N users by SSC balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def get_grr_leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    """Gets the top N users by GRR balance."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, balance FROM grr_users WHERE balance > 0 ORDER BY balance DESC LIMIT ?", (limit,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def get_all_users_combined() -> List[Dict[str, Any]]:
    """Gets all users from both currency systems, providing a comprehensive view."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        query = """
        SELECT
            uid.user_id,
            COALESCE(u.balance, 0) as ssc_balance,
            COALESCE(g.balance, 0) as grr_balance
        FROM (
            SELECT user_id FROM users
            UNION
            SELECT user_id FROM grr_users
        ) as uid
        LEFT JOIN users u ON uid.user_id = u.user_id
        LEFT JOIN grr_users g ON uid.user_id = g.user_id
        ORDER BY ssc_balance DESC, grr_balance DESC;
        """
        async with db.execute(query) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def update_user_balances(user_id: int, ssc_balance: int, grr_balance: int):
    """Sets the balances for a user across both systems."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, balance) VALUES (?, ?)",
            (user_id, ssc_balance)
        )
        await db.execute(
            """
            INSERT INTO grr_users (user_id, balance, last_daily) VALUES (?, ?, NULL)
            ON CONFLICT(user_id) DO UPDATE SET balance = excluded.balance
            """,
            (user_id, grr_balance)
        )
        await db.commit()

async def claim_daily_grr(user_id: int, amount_to_add: int) -> str:
    """
    Grants a user their daily GRR coins.
    Returns: "success" or "already_claimed".
    """
    today_str = str(date.today())
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await _get_or_create_grr_user(cursor, user_id)
            await cursor.execute("SELECT last_daily FROM grr_users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            last_claim_date = result[0] if result else None

            if last_claim_date == today_str:
                return "already_claimed"

            await cursor.execute(
                "UPDATE grr_users SET balance = balance + ?, last_daily = ? WHERE user_id = ?",
                (amount_to_add, today_str, user_id)
            )
            await db.commit()
            return "success"

async def perform_grr_ssc_exchange(user_id: int, grr_cost: int, ssc_reward: int) -> bool:
    """
    Atomically exchanges a specified amount of GRR for SSC.
    Returns True on success, False on failure (e.g., insufficient funds).
    """
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            # Get current GRR balance
            await _get_or_create_grr_user(cursor, user_id)
            await cursor.execute("SELECT balance FROM grr_users WHERE user_id = ?", (user_id,))
            result = await cursor.fetchone()
            current_grr_balance = result[0] if result else 0

            if current_grr_balance < grr_cost:
                return False

            # Ensure user exists in SSC table before adding to them
            await _get_or_create_user(cursor, user_id)

            # Perform the exchange
            await cursor.execute("UPDATE grr_users SET balance = balance - ? WHERE user_id = ?", (grr_cost, user_id))
            await cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ssc_reward, user_id))

        await db.commit()
        return True

# --- SHOP FUNCTIONS (Combined & Refined) ---

async def add_shop_item(guild_id: int, name: str, cost: int, role_id: int, image_url: Optional[str], one_time_buy: bool) -> bool:
    """Adds a new item to the shop. Returns False if an item with the same name already exists."""
    try:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute(
                "INSERT INTO shop_items (guild_id, name, cost, role_id, image_url, is_one_time_buy) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, name, cost, role_id, image_url, one_time_buy)
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False

async def get_shop_item(guild_id: int, name: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single shop item by name for a specific guild."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM shop_items WHERE guild_id = ? AND name = ?", (guild_id, name)) as cursor:
            result = await cursor.fetchone()
            return dict(result) if result else None

async def get_all_shop_items(guild_id: int) -> List[Dict[str, Any]]:
    """Retrieves all shop items for a guild, ordered by cost."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM shop_items WHERE guild_id = ? ORDER BY cost ASC", (guild_id,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def update_shop_item(item_id: int, updates: Dict[str, Any]):
    """Updates specific fields of a shop item by its ID."""
    async with aiosqlite.connect(DB_FILE) as db:
        fields = []
        values = []
        # Allow only a specific set of fields to be updated
        for key, value in updates.items():
            if key in ['name', 'cost', 'role_id', 'image_url', 'is_one_time_buy']:
                fields.append(f"{key} = ?")
                values.append(value)

        if not fields:
            return

        values.append(item_id)
        query = f"UPDATE shop_items SET {', '.join(fields)} WHERE item_id = ?"
        await db.execute(query, tuple(values))
        await db.commit()

async def mark_item_as_purchased(item_id: int, user_id: int):
    """Marks a one-time-buy item as sold to a specific user."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE shop_items SET purchased_by_user_id = ? WHERE item_id = ?", (user_id, item_id))
        await db.commit()

async def remove_shop_item(guild_id: int, name: str) -> bool:
    """Removes an item from the shop by name. Returns True if an item was deleted."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.cursor() as cursor:
            await cursor.execute("DELETE FROM shop_items WHERE guild_id = ? AND name = ?", (guild_id, name))
            await db.commit()
            return cursor.rowcount > 0

async def delete_shop_item(item_id: int):
    """Deletes a shop item by its primary key (item_id)."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM shop_items WHERE item_id = ?", (item_id,))
        await db.commit()

# --- CONFIG FUNCTIONS (Combined & Refined) ---

async def set_config_value(key: str, value: str):
    """Sets or updates a key-value pair in the config table."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value)
        )
        await db.commit()

async def get_config_value(key: str, default: Optional[str] = None) -> Optional[str]:
    """Gets a value from the config table, returning a default if not found."""
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else default

async def get_all_configs() -> Dict[str, str]:
    """Gets all key-value pairs from the config table."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT key, value FROM config") as cursor:
            return {row['key']: row['value'] for row in await cursor.fetchall()}