import aiosqlite
import json
from datetime import datetime
from logger_config import setup_logger
from config import DEFAULT_BALANCE

logger = setup_logger()

DB_NAME = "economy.db"

# --- ИНИЦИАЛИЗАЦИЯ БД ---

async def init_db():
    logger.info("🛠️ Начало инициализации базы данных...")
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER, guild_id INTEGER, balance INTEGER DEFAULT 100,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, guild_id INTEGER, event_id INTEGER,
                choice TEXT, amount INTEGER, coeff REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS saved_events (
                guild_id INTEGER, event_id INTEGER, data TEXT,
                PRIMARY KEY (guild_id, event_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER, name TEXT, description TEXT, price INTEGER,
                item_type TEXT, role_id INTEGER, is_one_time BOOLEAN DEFAULT 1,
                UNIQUE(guild_id, name)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, guild_id INTEGER, item_id INTEGER,
                quantity INTEGER DEFAULT 1,
                UNIQUE(user_id, guild_id, item_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS one_time_purchases (
                user_id INTEGER, guild_id INTEGER, item_id INTEGER,
                PRIMARY KEY (user_id, guild_id, item_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                reward INTEGER NOT NULL,
                expires_at DATETIME,
                created_by INTEGER,
                max_uses INTEGER DEFAULT NULL
            )
        """)

        try:
            await db.execute("ALTER TABLE promo_codes ADD COLUMN max_uses INTEGER DEFAULT NULL")
        except aiosqlite.OperationalError:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                redeemed_at DATETIME,
                UNIQUE(code, user_id, guild_id),
                FOREIGN KEY (code) REFERENCES promo_codes(code)
            )
        """)
        await db.commit()
    
    logger.info("✅ База данных инициализирована успешно")

# --- УПРАВЛЕНИЕ БАЛАНСОМ ---

async def get_balance(user_id, guild_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        row = await cursor.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, guild_id, balance) VALUES (?, ?, ?)", (user_id, guild_id, DEFAULT_BALANCE))
            await db.commit()
            return DEFAULT_BALANCE
        return row[0]

async def update_balance(user_id, guild_id, amount):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        row = await cursor.fetchone()
        
        if not row:
            new_balance = 100 + int(amount)
            await db.execute("INSERT INTO users (user_id, guild_id, balance) VALUES (?, ?, ?)", (user_id, guild_id, new_balance))
        else:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ? AND guild_id = ?", (int(amount), user_id, guild_id))
        
        await db.commit()
        
    if amount > 0:
        logger.info(f"💳 [DB] Баланс изменен: Пользователь {user_id} получил {amount} Лоресиков")
    else:
        logger.info(f"💳 [DB] Баланс изменен: У пользователя {user_id} списано {abs(amount)} Лоресиков")

# --- УПРАВЛЕНИЕ ТОВАРАМИ ---

async def add_item_to_inventory(user_id, guild_id, item_id, quantity=1):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT quantity FROM inventory WHERE user_id = ? AND guild_id = ? AND item_id = ?",
            (user_id, guild_id, item_id)
        )
        row = await cursor.fetchone()
        
        if row:
            await db.execute(
                "UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND guild_id = ? AND item_id = ?",
                (quantity, user_id, guild_id, item_id)
            )
        else:
            await db.execute(
                "INSERT INTO inventory (user_id, guild_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                (user_id, guild_id, item_id, quantity)
            )
        await db.commit()
    logger.info(f"📦 [DB] Инвентарь: Пользователю {user_id} добавлен предмет ID {item_id} ({quantity} шт.)")

async def remove_item_from_inventory(user_id, guild_id, item_id, quantity=1):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT quantity FROM inventory WHERE user_id = ? AND guild_id = ? AND item_id = ?",
            (user_id, guild_id, item_id)
        )
        row = await cursor.fetchone()
        
        if row and row[0] >= quantity:
            if row[0] == quantity:
                await db.execute(
                    "DELETE FROM inventory WHERE user_id = ? AND guild_id = ? AND item_id = ?",
                    (user_id, guild_id, item_id)
                )
            else:
                await db.execute(
                    "UPDATE inventory SET quantity = quantity - ? WHERE user_id = ? AND guild_id = ? AND item_id = ?",
                    (quantity, user_id, guild_id, item_id)
                )
            await db.commit()
            logger.info(f"📦 [DB] Инвентарь: У пользователя {user_id} изъят предмет ID {item_id} ({quantity} шт.)")
            return True
        return False

async def get_user_inventory(user_id, guild_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT si.item_id, si.name, si.description, inv.quantity, si.item_type, si.role_id
            FROM inventory inv
            JOIN shop_items si ON inv.item_id = si.item_id
            WHERE inv.user_id = ? AND inv.guild_id = ?
            ORDER BY si.name
        """, (user_id, guild_id))
        return await cursor.fetchall()

async def get_shop_items(guild_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT item_id, name, description, price, item_type, role_id, is_one_time FROM shop_items WHERE guild_id = ? ORDER BY name",
            (guild_id,)
        )
        return await cursor.fetchall()

async def get_shop_item(item_id, guild_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT item_id, name, description, price, item_type, role_id, is_one_time FROM shop_items WHERE item_id = ? AND guild_id = ?",
            (item_id, guild_id)
        )
        return await cursor.fetchone()

async def create_shop_item(guild_id, name, description, price, item_type, role_id=None, is_one_time=False):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            cursor = await db.execute(
                "INSERT INTO shop_items (guild_id, name, description, price, item_type, role_id, is_one_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, name, description, price, item_type, role_id, is_one_time)
            )
            await db.commit()
            logger.info(f"🏪 [DB] Магазин: Создан товар '{name}' за {price}")
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            return None

async def delete_shop_item(item_id, guild_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM shop_items WHERE item_id = ? AND guild_id = ?", (item_id, guild_id))
        await db.execute("DELETE FROM inventory WHERE item_id = ? AND guild_id = ?", (item_id, guild_id))
        await db.execute("DELETE FROM one_time_purchases WHERE item_id = ? AND guild_id = ?", (item_id, guild_id))
        await db.commit()
    logger.info(f"🏪 [DB] Магазин: Удален товар ID {item_id}")

async def is_one_time_purchased(user_id, guild_id, item_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT 1 FROM one_time_purchases WHERE user_id = ? AND guild_id = ? AND item_id = ?",
            (user_id, guild_id, item_id)
        )
        return await cursor.fetchone() is not None

async def mark_one_time_purchased(user_id, guild_id, item_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO one_time_purchases (user_id, guild_id, item_id) VALUES (?, ?, ?)",
            (user_id, guild_id, item_id)
        )
        await db.commit()

# --- УПРАВЛЕНИЕ СОБЫТИЯМИ ---

async def load_events_from_db():
    events_dict = {}
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT guild_id, event_id, data FROM saved_events")
        rows = await cursor.fetchall()
        for g_id, e_id, data_str in rows:
            if g_id not in events_dict: 
                events_dict[g_id] = {}
            events_dict[g_id][int(e_id)] = json.loads(data_str)
    
    total_events = sum(len(events) for events in events_dict.values())        
    logger.info(f"📅 Загружено {total_events} событий из БД")
    return events_dict

async def save_event(guild_id, event_id, event_data):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO saved_events VALUES (?, ?, ?)", 
            (guild_id, event_id, json.dumps(event_data, ensure_ascii=False))
        )
        await db.commit()

async def delete_event(guild_id, event_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM saved_events WHERE guild_id = ? AND event_id = ?", (guild_id, event_id))
        await db.execute("DELETE FROM bets WHERE guild_id = ? AND event_id = ?", (guild_id, event_id))
        await db.commit()

async def get_event_bets(guild_id, event_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, amount, choice FROM bets WHERE guild_id = ? AND event_id = ?",
            (guild_id, event_id)
        ) as cursor:
            return await cursor.fetchall()

async def place_bet(user_id, guild_id, event_id, choice, amount, coeff):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO bets (user_id, guild_id, event_id, choice, amount, coeff) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, guild_id, event_id, choice, amount, coeff)
        )
        await db.commit()

# --- УПРАВЛЕНИЕ ПРОМОКОДАМИ ---

async def get_promo(code):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT reward, expires_at, max_uses FROM promo_codes WHERE code = ?",
            (code,)
        )
        return await cursor.fetchone()

async def create_promo(code, reward, expires_at, created_by, max_uses):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO promo_codes (code, reward, expires_at, created_by, max_uses) VALUES (?, ?, ?, ?, ?)",
                (code, reward, expires_at, created_by, max_uses)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def delete_promo(code):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
        await db.commit()

async def get_all_promos():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT code, reward, expires_at, created_by, max_uses FROM promo_codes ORDER BY code"
        )
        return await cursor.fetchall()

async def check_promo_redemption(code, user_id, guild_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT 1 FROM promo_redemptions WHERE code = ? AND user_id = ? AND guild_id = ?",
            (code, user_id, guild_id)
        )
        return await cursor.fetchone() is not None

async def add_promo_redemption(code, user_id, guild_id):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO promo_redemptions (code, user_id, guild_id, redeemed_at) VALUES (?, ?, ?, ?)",
                (code, user_id, guild_id, datetime.now().isoformat())
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def get_promo_use_count(code):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM promo_redemptions WHERE code = ?",
            (code,)
        )
        return (await cursor.fetchone())[0]

async def get_user_top(guild_id, limit=10):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT user_id, balance FROM users WHERE guild_id = ? ORDER BY balance DESC LIMIT ?",
            (guild_id, limit)
        )
        return await cursor.fetchall()