import discord
import aiosqlite
import asyncio
import json
import random
import sys
import io
import os
from typing import Optional
from dotenv import load_dotenv
from discord.app_commands import MissingPermissions, CheckFailure
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
from logger_config import setup_logger

# --- НАСТРОЙКА ---

logger = setup_logger()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="/", intents=intents, help_command=None)

    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()
DB_NAME = "economy.db"
active_events = {}

ROULETTE_COLORS = {
    0: "🟢",
    **{n: "🔴" for n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]},
    **{n: "⚫" for n in [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]}
}

SYM_WILD = "👑"
SYM_SCATTER = "⭐"
SYM_HIGH = ["💎", "7️⃣"]
SYM_MID = ["🔔", "🍉", "🍇"]
SYM_LOW = ["🍋", "🍒", "🍎"]
SYM_EMPTY = "⬛" 

user_retention_data = {} 

PAYTABLE = {
    "👑": [0, 0, 5, 20, 100],
    "⭐": [0, 0, 10, 50, 200],
    "💎": [0, 0, 4, 15, 50],
    "7️⃣": [0, 0, 3, 10, 40],
    "🔔": [0, 0, 3, 8, 30],
    "🍉": [0, 0, 2, 5, 20],
    "🍇": [0, 0, 1, 4, 15],
    "🍋": [0, 0, 1, 2.5, 10],
    "🍒": [0, 0, 1, 2, 8],
    "🍎": [0, 0, 1, 1.5, 5],
}

PAYLINES = [
    [1, 1, 1, 1, 1], [0, 0, 0, 0, 0], [2, 2, 2, 2, 2], 
    [0, 1, 2, 1, 0], [2, 1, 0, 1, 2], 
    [0, 0, 1, 2, 2], [2, 2, 1, 0, 0], 
]

def get_reels():
    reels = []
    for _ in range(5):
        strip = [SYM_WILD]*2 + [SYM_SCATTER]*1 + SYM_HIGH*3 + SYM_MID*6 + SYM_LOW*10
        random.shuffle(strip)
        reels.append(strip)
    return reels

REEL_STRIPS = get_reels()

def force_win_grid():
    grid = [[random.choice(SYM_LOW + SYM_MID) for _ in range(5)] for _ in range(3)]
    line = random.choice(PAYLINES)
    win_sym = random.choice(SYM_LOW + SYM_MID)
    for i in range(random.randint(3, 4)):
        grid[line[i]][i] = win_sym
    return grid

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
    await load_events_from_db()
    logger.info("✅ База данных инициализирована успешно")

async def load_events_from_db():
    global active_events
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT guild_id, event_id, data FROM saved_events")
        rows = await cursor.fetchall()
        for g_id, e_id, data_str in rows:
            if g_id not in active_events: active_events[g_id] = {}
            active_events[g_id][int(e_id)] = json.loads(data_str)
    
    total_events = sum(len(events) for events in active_events.values())        
    logger.info(f"📅 Загружено {total_events} событий из БД")

async def get_balance(user_id, guild_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        row = await cursor.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, guild_id, balance) VALUES (?, ?, ?)", (user_id, guild_id, 100))
            await db.commit()
            return 100
        return row[0]

async def update_balance(user_id, guild_id, amount):
    await get_balance(user_id, guild_id)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ? AND guild_id = ?", (int(amount), user_id, guild_id))
        await db.commit()
        
    if amount > 0:
        logger.info(f"💳 [DB] Баланс изменен: Пользователь {user_id} получил {amount} Лоресиков")
    else:
        logger.info(f"💳 [DB] Баланс изменен: У пользователя {user_id} списано {abs(amount)} Лоресиков")
        
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

# --- СНОВНЫЕ КОМАНДЫ ---

# 0. HELP
@bot.tree.command(name="help", description="Показать список всех команд")
async def help_command(interaction: discord.Interaction):
    logger.info(f"ℹ️ /help | Вызвал: {interaction.user} (ID: {interaction.user.id})")
    embed = discord.Embed(title="📖 Справка по командам", color=discord.Color.green())
    
    embed.add_field(name="💰 Экономика и Игры", value=(
        "`/balance` — Проверить счет\n"
        "`/top` — Топ богачей сервера\n"
        "`/slots [сумма]` — Играть в казино\n"
        "`/events` — Список активных матчей\n"
        "`/bet [id_события] [выбор] [сумма]` — Сделать ставку\n"
        "`/pay [пользователь] [сумма]` — Передать деньги"
    ), inline=False)

    embed.add_field(name="🛍️ Магазин", value=(
        "`/shop` — Просмотреть товары магазина\n"
        "`/inventory` — Посмотреть инвентарь\n"
        "`/buy [id_товара] [кол-во (опц)]` — Купить товар"
    ), inline=False)
    
    embed.add_field(name="🎁 Промо", value="`/promo [код]` — активировать промокод и получить награду", inline=False)

    if interaction.user.guild_permissions.administrator:
        embed.add_field(name="🛡️ Администрирование", value=(
            "`/create_match` — Создать матч 1vs1\n"
            "`/create_mvp` — Ставка на лучшего игрока\n"
            "`/create_total` — Ставка на счет (Больше/Меньше)\n"
            "`/lock [id_события]` — Закрыть прием ставок\n"
            "`/unlock [id_события]` — Открыть прием ставок\n"
            "`/settle [id_события] [победитель]` — Выплатить выигрыши\n"
            "`/give [пользователь] [сумма]` — Выдать Лоресиков\n"
            "`/remove [пользователь] [сумма]` — Забрать Лоресиков"
        ), inline=False)

        embed.add_field(name="🏪 Управление магазином", value=(
            "`/create_item` — Создать товар\n"
            "`/create_role_item` — Создать товар-роль\n"
            "`/delete_item [id]` — Удалить товар\n"
            "`/give_item [пользователь] [id_товара] [кол-во]` — Выдать товар\n"
            "`/remove_item [пользователь] [id_товара] [кол-во]` — Забрать товар"
        ), inline=False)
        
        embed.add_field(name="🎁 Промокоды", value=(
            "`/create_promo` — создать промокод\n"
            "`/delete_promo [код]` — удалить промокод\n"
            "`/list_promos` — посмотреть все промокоды"
        ), inline=False)
    
    await interaction.response.send_message(embed=embed)

# 1. BALANCE
@bot.tree.command(name="balance", description="Посмотреть баланс")
async def balance(interaction: discord.Interaction, пользователь: discord.Member = None):
    target = пользователь or interaction.user
    logger.info(f"💰 /balance | Вызвал: {interaction.user} ({interaction.user.id}) | Цель: {target} (ID: {target.id})")
    
    bal = await get_balance(target.id, interaction.guild.id)
    await interaction.response.send_message(f"💰 Баланс {target.mention}: `{bal}` Лоресиков.")

# 2. SLOTS
@bot.tree.command(name="slots", description="Слот-машина 3x5")
async def slots(interaction: discord.Interaction, ставка: int):
    logger.info(f"🎰 /slots | Вызвал: {interaction.user} | Ставка: {ставка}")
    user_id = interaction.user.id
    guild_id = interaction.guild.id
    
    if ставка < 10:
        return await interaction.response.send_message("❌ Минимальная ставка — 10.", ephemeral=True)
    
    bal = await get_balance(user_id, guild_id)
    if ставка > bal:
        return await interaction.response.send_message(f"❌ Недостаточно средств ({bal})", ephemeral=True)

    await update_balance(user_id, guild_id, -ставка)
    
    if user_id not in user_retention_data:
        user_retention_data[user_id] = 0
    
    loss_streak = user_retention_data[user_id]
    pity_chance = min(0.70, loss_streak * 0.07)
    
    is_pity_triggered = False
    if loss_streak >= 2 and random.random() < pity_chance:
        grid = force_win_grid()
        is_pity_triggered = True
    else:
        grid = [[None for _ in range(5)] for _ in range(3)]
        for c in range(5):
            stop = random.randint(0, len(REEL_STRIPS[c])-1)
            for r in range(3):
                grid[r][c] = REEL_STRIPS[c][(stop + r) % len(REEL_STRIPS[c])]

    total_win = 0
    win_coords = set()
    details = []

    for idx, line in enumerate(PAYLINES):
        match_sym = grid[line[0]][0]
        count = 1
        temp_coords = [(line[0], 0)]
        
        for c in range(1, 5):
            char = grid[line[c]][c]
            if char == match_sym or char == SYM_WILD or match_sym == SYM_WILD:
                count += 1
                temp_coords.append((line[c], c))
                if match_sym == SYM_WILD and char != SYM_WILD:
                    match_sym = char
            else:
                break
        
        if count >= 3:
            pay_sym = SYM_WILD if match_sym == SYM_WILD else match_sym
            mult = PAYTABLE[pay_sym][count-1]
            if mult > 0:
                win_amount = int(ставка * mult)
                total_win += win_amount
                details.append(f"Линия {idx+1}: {pay_sym} x{count}")
                for coord in temp_coords: win_coords.add(coord)

    if total_win > 0:
        await update_balance(user_id, guild_id, total_win)
        user_retention_data[user_id] = 0 
        color = discord.Color.green()
        title = "🎰 ВЫИГРЫШ!"
        result_text = f"💰 **+{total_win}** Лоресиков"
        logger.info(f"🎰 /slots | Результат: WIN | {interaction.user} выиграл {total_win}")
    else:
        user_retention_data[user_id] += 1 
        color = discord.Color.red()
        title = "🎰 КАЗИНО"
        result_text = "Ничего не выпало. Попробуй еще раз!"
        logger.info(f"🎰 /slots | Результат: LOSE | {interaction.user} проиграл {ставка}")

    board = ""
    for r in range(3):
        row_icons = []
        for c in range(5):
            row_icons.append(grid[r][c])
        board += " | ".join(row_icons) + "\n"

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Спины", value=f"```\n{board}\n```", inline=False)

    if total_win > 0:
        line_map = ""
        for r in range(3):
            row_map = []
            for c in range(5):
                if (r, c) in win_coords:
                    row_map.append(grid[r][c]) 
                else:
                    row_map.append(SYM_EMPTY)
            line_map += " ".join(row_map) + "\n"
        
        embed.add_field(name="🏆 Выигрышная схема", value=f"```\n{line_map}\n```", inline=False)
        
        if details:
            embed.add_field(name="Инфо", value="\n".join(details[:3]), inline=True)

    embed.add_field(name="Итог", value=result_text, inline=False)
    embed.set_footer(text=f"Баланс: {await get_balance(user_id, guild_id)}")

    await interaction.response.send_message(embed=embed)

# 3. EVENTS
@bot.tree.command(name="events", description="Список событий")
async def events(interaction: discord.Interaction, id_события: int = None):
    logger.info(f"📅 /events | Вызвал: {interaction.user} ({interaction.user.id}) | ID события: {id_события if id_события else 'Все'}")
    
    evs = active_events.get(interaction.guild.id, {})
    
    if id_события is None:
        if not evs: 
            return await interaction.response.send_message("Нет активных событий.", ephemeral=True)
        
        embed = discord.Embed(title="📅 Активные события", color=discord.Color.blue())
        for eid, data in evs.items():
            status = "🔒 (Закрыто)" if data["locked"] else "✅ (Открыто)"
            embed.add_field(
                name=f"ID: {eid} | {data['title']}", 
                value=f"Статус: {status}", 
                inline=False
            )
        
        embed.set_footer(text="Чтобы увидеть коэффициенты и составы: /events id_события")
        await interaction.response.send_message(embed=embed)
        return

    event = evs.get(id_события)
    if not event:
        return await interaction.response.send_message(f"❌ Событие с ID **{id_события}** не найдено.", ephemeral=True)

    is_locked = event["locked"]
    status_emoji = "🔒" if is_locked else "✅"
    status_text = "Прием ставок закрыт" if is_locked else "Прием ставок открыт"
    color = discord.Color.red() if is_locked else discord.Color.blue()

    embed = discord.Embed(
        title=event['title'], 
        description=f"**ID события:** `{id_события}`\n**Статус:** {status_emoji} {status_text}", 
        color=color
    )

    options_list = []
    for key, val in event['options'].items():
        name = val['name']
        coeff = val['coeff']
        options_list.append(f"🔹 **{name}** — x`{coeff}`")
    
    embed.add_field(name="📊 Коэффициенты", value="\n".join(options_list), inline=False)

    if event.get("type") == "match" and "rosters" in event:
        for team_name, roster_text in event["rosters"].items():
            if roster_text: 
                embed.add_field(name=f"👥 Состав {team_name}", value=f"_{roster_text}_", inline=True)

    embed.set_footer(text=f"Сделать ставку: /bet")
    
    await interaction.response.send_message(embed=embed)

# 4. BET
@bot.tree.command(name="bet", description="Сделать ставку")
async def bet(interaction: discord.Interaction, id_события: int, выбор: str, сумма: int):
    logger.info(f"🎲 /bet | Вызвал: {interaction.user} ({interaction.user.id}) | EventID: {id_события} | Выбор: {выбор} | Сумма: {сумма}")
    
    ev = active_events.get(interaction.guild.id, {}).get(id_события)
    if not ev: return await interaction.response.send_message("❌ Матч не найден.", ephemeral=True)
    if ev["locked"]: return await interaction.response.send_message("❌ Ставки закрыты.", ephemeral=True)
    
    choice_key = выбор.lower()
    if choice_key not in ev["options"]:
        return await interaction.response.send_message(f"❌ Варианты: {', '.join(ev['options'].keys())}", ephemeral=True)

    bal = await get_balance(interaction.user.id, interaction.guild.id)
    if сумма < 10 or сумма > bal: return await interaction.response.send_message("❌ Ошибка суммы.", ephemeral=True)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO bets (user_id, guild_id, event_id, choice, amount, coeff) VALUES (?, ?, ?, ?, ?, ?)",
                         (interaction.user.id, interaction.guild.id, id_события, choice_key, сумма, ev["options"][choice_key]["coeff"]))
        await db.commit()
    await update_balance(interaction.user.id, interaction.guild.id, -сумма)
    await interaction.response.send_message(f"✅ Ставка `{сумма}` на **{выбор}** принята!")

# 5. CREATE_MATCH
@bot.tree.command(name="create_match", description="Админ: Создать матч")
@app_commands.checks.has_permissions(administrator=True)
async def create_match(interaction: discord.Interaction, команда1: str, ростер1: str, кэф1: float, команда2: str, ростер2: str, кэф2: float):
    logger.info(f"⚔️ /create_match | Админ: {interaction.user} ({interaction.user.id}) | {команда1} (x{кэф1}) vs {команда2} (x{кэф2})")
    
    eid = (max(active_events.get(interaction.guild.id, {}).keys()) if active_events.get(interaction.guild.id, {}) else 0) + 1
    
    event_data = {
        "type": "match",
        "title": f"⚔️ {команда1} vs {команда2}",
        "rosters": {команда1: ростер1, команда2: ростер2},
        "options": {
            команда1.lower(): {"name": команда1, "coeff": кэф1},
            команда2.lower(): {"name": команда2, "coeff": кэф2}
        },
        "locked": False
    }
    
    active_events.setdefault(interaction.guild.id, {})[eid] = event_data
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO saved_events VALUES (?, ?, ?)", (interaction.guild.id, eid, json.dumps(event_data)))
        await db.commit()

    embed = discord.Embed(title="🔔 НОВОЕ СОБЫТИЕ ОПУБЛИКОВАНО", color=discord.Color.gold())
    embed.add_field(name=f"🎮 Матч #{eid}", value=f"**{команда1}** vs **{команда2}**", inline=False)
    embed.add_field(name=f"📈 Коэффициенты", value=f"{команда1}: `{кэф1}` | {команда2}: `{кэф2}`", inline=False)
    embed.add_field(name=f"👥 Состав {команда1}", value=f"*{ростер1}*", inline=True)
    embed.add_field(name=f"👥 Состав {команда2}", value=f"*{ростер2}*", inline=True)
    embed.set_footer(text="Для ставки используйте /bet")
    
    await interaction.response.send_message(embed=embed)

# 6. CREATE_MVP
@bot.tree.command(name="create_mvp", description="Админ: Ставка на MVP")
@app_commands.checks.has_permissions(administrator=True)
async def create_mvp(interaction: discord.Interaction, название: str, данные: str):
    logger.info(f"⭐ /create_mvp | Админ: {interaction.user} ({interaction.user.id}) | Название: {название} | Данные: {данные}")
    guild_id = interaction.guild.id
    
    eid = (max(active_events.get(guild_id, {}).keys()) if active_events.get(guild_id, {}) else 0) + 1
    
    options = {}
    player_list_display = []

    try:
        parts = данные.split(",")
        for part in parts:
            name_part, coeff_part = part.split(":")
            name = name_part.strip()
            coeff = float(coeff_part.strip())
            
            options[name.lower()] = {"name": name, "coeff": coeff}
            player_list_display.append(f"**{name}** — x{coeff}")
            
    except ValueError:
        return await interaction.response.send_message(
            "❌ Ошибка формата! Используйте: `Имя:Коэф, Имя:Коэф`.\nПример: `s1mple:1.5, m0nesy:2.4`", 
            ephemeral=True
        )

    if len(options) < 2:
        return await interaction.response.send_message("❌ Нужно минимум 2 игрока.", ephemeral=True)

    event_data = {
        "type": "mvp",
        "title": f"⭐ {название}",
        "options": options,
        "locked": False
    }

    active_events.setdefault(guild_id, {})[eid] = event_data

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO saved_events (guild_id, event_id, data) VALUES (?, ?, ?)",
            (guild_id, eid, json.dumps(event_data, ensure_ascii=False))
        )
        await db.commit()

    embed = discord.Embed(
        title="🌟 РЕГИСТРАЦИЯ СТАВОК НА MVP", 
        description=f"Событие: **{название}** (ID: `{eid}`)",
        color=discord.Color.gold()
    )
    embed.add_field(name="Участники и коэффициенты:", value="\n".join(player_list_display), inline=False)
    embed.set_footer(text="Ставка: /bet")
    
    await interaction.response.send_message(embed=embed)

# 7. CREATE_TOTAL
@bot.tree.command(name="create_total", description="Админ: Создать тотал")
@app_commands.checks.has_permissions(administrator=True)
async def create_total(interaction: discord.Interaction, описание: str, кэф_бол: float, кэф_мен: float):
    logger.info(f"📊 /create_total | Админ: {interaction.user} ({interaction.user.id}) | Описание: {описание} | Больше: {кэф_бол} | Меньше: {кэф_мен}")
    eid = (max(active_events.get(interaction.guild.id, {}).keys()) if active_events.get(interaction.guild.id, {}) else 0) + 1
    
    event_data = {
        "type": "total", "title": описание,
        "options": {"больше": {"name": "Больше", "coeff": кэф_бол}, "меньше": {"name": "Меньше", "coeff": кэф_мен}},
        "locked": False
    }
    active_events.setdefault(interaction.guild.id, {})[eid] = event_data
    
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO saved_events VALUES (?, ?, ?)", (interaction.guild.id, eid, json.dumps(event_data)))
        await db.commit()

    embed = discord.Embed(title="📊 СТАВКА НА СТАТИСТИКУ", color=discord.Color.blue())
    embed.add_field(name=f"Событие #{eid}", value=f"**{описание}**", inline=False)
    embed.add_field(name="📈 Больше", value=f"Кэф: `{кэф_бол}`", inline=True)
    embed.add_field(name="📉 Меньше", value=f"Кэф: `{кэф_мен}`", inline=True)
    embed.set_footer(text="Пример: /bet")
    
    await interaction.response.send_message(embed=embed)

# 8. LOCK
@bot.tree.command(name="lock", description="Админ: Закрыть ставки")
@app_commands.checks.has_permissions(administrator=True)
async def lock(interaction: discord.Interaction, id_события: int):
    logger.info(f"🔒 /lock | Админ: {interaction.user} ({interaction.user.id}) | ID события: {id_события}")
    if id_события in active_events.get(interaction.guild.id, {}):
        active_events[interaction.guild.id][id_события]["locked"] = True
        await interaction.response.send_message(f"🔒 Ставки на #{id_события} закрыты.")

# 9. UNLOCK
@bot.tree.command(name="unlock", description="Админ: Открыть ставки")
@app_commands.checks.has_permissions(administrator=True)
async def unlock(interaction: discord.Interaction, id_события: int):
    logger.info(f"🔓 /unlock | Админ: {interaction.user} ({interaction.user.id}) | ID события: {id_события}")
    if id_события in active_events.get(interaction.guild.id, {}):
        active_events[interaction.guild.id][id_события]["locked"] = False
        await interaction.response.send_message(f"🔓 Ставки на #{id_события} открыты.")

# 10. SETTLE
@bot.tree.command(name="settle", description="Админ: Завершить событие")
@app_commands.checks.has_permissions(administrator=True)
async def settle(interaction: discord.Interaction, id_события: int, победитель: str):
    logger.info(f"🏆 /settle | Админ: {interaction.user} ({interaction.user.id}) | ID события: {id_события} | Победитель: {победитель}")
    guild_id = interaction.guild.id
    
    if guild_id not in active_events or id_события not in active_events[guild_id]:
        return await interaction.response.send_message("❌ Событие не найдено.", ephemeral=True)

    event = active_events[guild_id][id_события]
    winner_key = победитель.lower().strip()

    if winner_key not in event['options']:
        valid_options = ", ".join(event['options'].keys())
        return await interaction.response.send_message(
            f"❌ Неверный исход. Доступные варианты: `{valid_options}`", 
            ephemeral=True
        )

    await interaction.response.defer()

    total_payouts = 0
    winner_display_name = event['options'][winner_key]['name']
    payout_coeff = event['options'][winner_key]['coeff']

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, amount, choice FROM bets WHERE guild_id = ? AND event_id = ?",
            (guild_id, id_события)
        ) as cursor:
            bets = await cursor.fetchall()

        for b_user_id, b_amount, b_choice in bets:
            if b_choice.lower() == winner_key:
                payout = int(b_amount * payout_coeff)
                await update_balance(b_user_id, guild_id, payout)
                total_payouts += 1
                
                try:
                    user = await bot.fetch_user(b_user_id)
                    await user.send(f"🏆 Ваша ставка на **{event['title']}** сыграла! Выигрыш: **{payout}**")
                except:
                    pass

        await db.execute("DELETE FROM bets WHERE guild_id = ? AND event_id = ?", (guild_id, id_события))
        await db.execute("DELETE FROM saved_events WHERE guild_id = ? AND event_id = ?", (guild_id, id_события))
        await db.commit()

    del active_events[guild_id][id_события]

    logger.info(f"✅ /settle завершен | Событие {id_события} | Выплачено победителям: {total_payouts}")

    embed = discord.Embed(
        title="🏁 СОБЫТИЕ ЗАВЕРШЕНО", 
        description=f"Результаты по событию **#{id_события}**\n**{event['title']}**",
        color=discord.Color.green()
    )
    embed.add_field(name="🏆 Победитель", value=f"**{winner_display_name}**", inline=True)
    embed.add_field(name="📈 Коэффициент", value=f"x{payout_coeff}", inline=True)
    embed.add_field(name="💰 Победителей", value=str(total_payouts), inline=True)
    
    await interaction.followup.send(embed=embed)

# 11. GIVE
@bot.tree.command(name="give", description="Админ: Выдать Лоресиков")
@app_commands.checks.has_permissions(administrator=True)
async def give(interaction: discord.Interaction, пользователь: discord.Member, сумма: int):
    logger.info(f"💸 /give | Админ: {interaction.user} ({interaction.user.id}) | Кому: {пользователь} ({пользователь.id}) | Сумма: {сумма}")
    await update_balance(пользователь.id, interaction.guild.id, сумма)
    await interaction.response.send_message(f"✅ Выдано {сумма} пользователю {пользователь.mention}")

# 12. REMOVE
@bot.tree.command(name="remove", description="Админ: Забрать Лоресиков")
@app_commands.checks.has_permissions(administrator=True)
async def remove(interaction: discord.Interaction, пользователь: discord.Member, сумма: int):
    logger.info(f"💸 /remove | Админ: {interaction.user} ({interaction.user.id}) | У кого: {пользователь} ({пользователь.id}) | Сумма: {сумма}")
    await update_balance(пользователь.id, interaction.guild.id, -сумма)
    await interaction.response.send_message(f"✅ Забрано {сумма} у пользователя {пользователь.mention}")
    
# 13. PAY 
@bot.tree.command(name="pay", description="Передать Лоресики другому пользователю")
async def pay(interaction: discord.Interaction, получатель: discord.Member, колво: int):
    logger.info(f"💳 /pay | От: {interaction.user} ({interaction.user.id}) | Кому: {получатель} ({получатель.id}) | Сумма: {колво}")
    
    if колво <= 0:
        return await interaction.response.send_message("❌ Сумма перевода должна быть больше 0!", ephemeral=True)
    
    if interaction.user.id == получатель.id:
        return await interaction.response.send_message("❌ Вы не можете перевести деньги самому себе!", ephemeral=True)
    
    if получатель.bot:
        return await interaction.response.send_message("❌ Ботам деньги не нужны.", ephemeral=True)

    guild_id = interaction.guild.id
    sender_id = interaction.user.id
    
    sender_balance = await get_balance(sender_id, guild_id)
    
    if sender_balance < колво:
        return await interaction.response.send_message(
            f"❌ Недостаточно средств! Ваш баланс: `{sender_balance}` Лоресиков.", 
            ephemeral=True
        )

    await update_balance(sender_id, guild_id, -колво)
    await update_balance(получатель.id, guild_id, колво)

    embed = discord.Embed(
        title="💸 Успешный перевод",
        description=f"**{interaction.user.display_name}** перевел деньги пользователю **{получатель.display_name}**",
        color=discord.Color.gold()
    )
    embed.add_field(name="Сумма", value=f"`{колво}` Лоресиков", inline=True)
    embed.set_footer(text=f"ID отправителя: {sender_id}")

    await interaction.response.send_message(content=f"{получатель.mention}, вам подарок!", embed=embed)

# 14. SHOP
@bot.tree.command(name="shop", description="Просмотреть магазин")
async def shop(interaction: discord.Interaction):
    logger.info(f"🏪 /shop | Вызвал: {interaction.user} ({interaction.user.id}) ")
    guild_id = interaction.guild.id
    items = await get_shop_items(guild_id)
    
    if not items:
        return await interaction.response.send_message("❌ Магазин пуст.", ephemeral=True)
    
    embed = discord.Embed(title="🏪 Магазин товаров", color=discord.Color.purple())
    
    for item_id, name, description, price, item_type, role_id, is_one_time in items:
        one_time_badge = "🔴 Одноразовый" if is_one_time else ""
        type_emoji = "🎁" if item_type == "item" else "👑"
        value = f"{description}\n💰 Цена: `{price}` Лоресиков\n{one_time_badge}"
        embed.add_field(name=f"{type_emoji} {name} (ID: {item_id})", value=value, inline=False)
    
    embed.set_footer(text="Чтобы купить товар: /buy [id]")
    await interaction.response.send_message(embed=embed)

# 15. INVENTORY
@bot.tree.command(name="inventory", description="Посмотреть инвентарь")
async def inventory(interaction: discord.Interaction, пользователь: discord.Member = None):
    target = пользователь or interaction.user
    logger.info(f"🎒 /inventory | Вызвал: {interaction.user} ({interaction.user.id}) | Чей инвентарь: {target} ({target.id})")
    guild_id = interaction.guild.id
    
    inv = await get_user_inventory(target.id, guild_id)
    
    if not inv:
        return await interaction.response.send_message(f"❌ Инвентарь {target.display_name} пуст.", ephemeral=True)
    
    embed = discord.Embed(title=f"🎒 Инвентарь {target.display_name}", color=discord.Color.blue())
    
    for item_id, name, description, quantity, item_type, role_id in inv:
        type_emoji = "🎁" if item_type == "item" else "👑"
        embed.add_field(
            name=f"{type_emoji} {name} (ID: {item_id})", 
            value=f"Количество: `{quantity}`", 
            inline=False
        )
    
    embed.set_footer(text="Покупайте еще товары в /shop")
    await interaction.response.send_message(embed=embed)

# 16. BUY
@bot.tree.command(name="buy", description="Купить товар")
async def buy(interaction: discord.Interaction, id_товара: int, кол_во: int = 1):
    logger.info(f"🛒 /buy | Вызвал: {interaction.user} ({interaction.user.id}) | ID товара: {id_товара} | Кол-во: {кол_во}")
    guild_id = interaction.guild.id
    user_id = interaction.user.id
    
    if кол_во < 1:
        return await interaction.response.send_message("❌ Количество должно быть больше 0.", ephemeral=True)
    
    item = await get_shop_item(id_товара, guild_id)
    if not item:
        return await interaction.response.send_message("❌ Товар не найден.", ephemeral=True)
    
    item_id, name, description, price, item_type, role_id, is_one_time = item
    
    if is_one_time and кол_во > 1:
        return await interaction.response.send_message(
            "❌ Этот товар одноразовый! Можно купить максимум 1 копию.",
            ephemeral=True
        )
    
    if is_one_time:
        already_bought = await is_one_time_purchased(user_id, guild_id, item_id)
        if already_bought:
            return await interaction.response.send_message(
                f"❌ Вы уже купили этот товар! Он одноразовый.",
                ephemeral=True
            )
    
    balance = await get_balance(user_id, guild_id)
    total_price = price * кол_во
    
    if balance < total_price:
        return await interaction.response.send_message(
            f"❌ Недостаточно средств! Нужно {total_price}, у вас {balance}.",
            ephemeral=True
        )
    
    await update_balance(user_id, guild_id, -total_price)
    await add_item_to_inventory(user_id, guild_id, item_id, кол_во)
    
    role_given = False
    if item_type == "role" and role_id:
        try:
            role = interaction.guild.get_role(role_id)
            if role and role not in interaction.user.roles:
                await interaction.user.add_roles(role)
                role_given = True
        except Exception as e:
            pass
    
    if is_one_time:
        await mark_one_time_purchased(user_id, guild_id, item_id)
    
    embed = discord.Embed(
        title="✅ Покупка успешна!",
        description=f"Вы купили **{name}**",
        color=discord.Color.green()
    )
    embed.add_field(name="Описание", value=description, inline=False)
    embed.add_field(name="Количество", value=f"`{кол_во}` шт.", inline=True)
    embed.add_field(name="Цена за единицу", value=f"`{price}` Лоресиков", inline=True)
    embed.add_field(name="Общая цена", value=f"`{total_price}` Лоресиков", inline=True)
    embed.add_field(name="Новый баланс", value=f"`{balance - total_price}` Лоресиков", inline=True)
    if role_given:
        embed.add_field(name="👑 Роль выдана!", value=role.mention, inline=True)
    
    await interaction.response.send_message(embed=embed)

# 17. CREATE_ITEM
@bot.tree.command(name="create_item", description="Админ: Создать товар")
@app_commands.checks.has_permissions(administrator=True)
async def create_item(interaction: discord.Interaction, название: str, описание: str, цена: int, одноразовый: bool = False):
    logger.info(f"🔨 /create_item | Админ: {interaction.user} ({interaction.user.id}) | Товар: {название} | Цена: {цена}")
    guild_id = interaction.guild.id
    
    if цена <= 0:
        return await interaction.response.send_message("❌ Цена должна быть больше 0.", ephemeral=True)
    
    item_id = await create_shop_item(guild_id, название, описание, цена, "item", None, одноразовый)
    
    if not item_id:
        return await interaction.response.send_message(f"❌ Товар с названием '{название}' уже существует.", ephemeral=True)
    
    one_time_text = "🔴 Одноразовый товар" if одноразовый else "♻️ Многоразовый товар"
    
    embed = discord.Embed(
        title="✅ Товар создан!",
        description=f"Товар '{название}' успешно добавлен в магазин",
        color=discord.Color.green()
    )
    embed.add_field(name="ID товара", value=f"`{item_id}`", inline=True)
    embed.add_field(name="Название", value=название, inline=True)
    embed.add_field(name="Описание", value=описание, inline=False)
    embed.add_field(name="Цена", value=f"`{цена}` Лоресиков", inline=True)
    embed.add_field(name="Тип", value=one_time_text, inline=True)
    
    await interaction.response.send_message(embed=embed)

# 18. CREATE_ROLE_ITEM
@bot.tree.command(name="create_role_item", description="Админ: Создать товар-роль")
@app_commands.checks.has_permissions(administrator=True)
async def create_role_item(interaction: discord.Interaction, название: str, описание: str, цена: int, роль: discord.Role, одноразовый: bool = False):
    logger.info(f"👑 /create_role_item | Админ: {interaction.user} ({interaction.user.id}) | Товар: {название} | Роль: {роль.name}")
    guild_id = interaction.guild.id
    
    if цена <= 0:
        return await interaction.response.send_message("❌ Цена должна быть больше 0.", ephemeral=True)
    
    item_id = await create_shop_item(guild_id, название, описание, цена, "role", роль.id, одноразовый)
    
    if not item_id:
        return await interaction.response.send_message(f"❌ Товар с названием '{название}' уже существует.", ephemeral=True)
    
    one_time_text = "🔴 Одноразовый товар" if одноразовый else "♻️ Многоразовый товар"
    
    embed = discord.Embed(
        title="✅ Товар-роль создан!",
        description=f"Товар '{название}' успешно добавлен в магазин",
        color=discord.Color.green()
    )
    embed.add_field(name="ID товара", value=f"`{item_id}`", inline=True)
    embed.add_field(name="Название", value=название, inline=True)
    embed.add_field(name="Описание", value=описание, inline=False)
    embed.add_field(name="Цена", value=f"`{цена}` Лоресиков", inline=True)
    embed.add_field(name="Роль", value=роль.mention, inline=True)
    embed.add_field(name="Тип", value=one_time_text, inline=True)
    
    await interaction.response.send_message(embed=embed)

# 19. DELETE_ITEM
@bot.tree.command(name="delete_item", description="Админ: Удалить товар")
@app_commands.checks.has_permissions(administrator=True)
async def delete_item(interaction: discord.Interaction, id_товара: int):
    logger.info(f"🗑️ /delete_item | Админ: {interaction.user} ({interaction.user.id}) | ID товара: {id_товара}")
    guild_id = interaction.guild.id
    
    item = await get_shop_item(id_товара, guild_id)
    if not item:
        return await interaction.response.send_message("❌ Товар не найден.", ephemeral=True)
    
    item_id, name, description, price, item_type, role_id, is_one_time = item
    
    await delete_shop_item(id_товара, guild_id)
    
    embed = discord.Embed(
        title="✅ Товар удален!",
        description=f"Товар '{name}' удален из магазина",
        color=discord.Color.green()
    )
    
    await interaction.response.send_message(embed=embed)

# 20. GIVE_ITEM
@bot.tree.command(name="give_item", description="Админ: Выдать товар пользователю")
@app_commands.checks.has_permissions(administrator=True)
async def give_item(interaction: discord.Interaction, пользователь: discord.Member, id_товара: int, кол_во: int = 1):
    logger.info(f"📦 /give_item | Админ: {interaction.user} ({interaction.user.id}) | Кому: {пользователь} ({пользователь.id}) | ID товара: {id_товара} | Кол-во: {кол_во}")
    guild_id = interaction.guild.id
    
    item = await get_shop_item(id_товара, guild_id)
    if not item:
        return await interaction.response.send_message("❌ Товар не найден.", ephemeral=True)
    
    item_id, name, description, price, item_type, role_id, is_one_time = item
    
    if кол_во <= 0:
        return await interaction.response.send_message("❌ Количество должно быть больше 0.", ephemeral=True)
    
    if is_one_time and кол_во > 1:
        кол_во = 1
    
    await add_item_to_inventory(пользователь.id, guild_id, item_id, кол_во)
    
    if item_type == "role" and role_id:
        try:
            role = interaction.guild.get_role(role_id)
            if role and role not in пользователь.roles:
                await пользователь.add_roles(role)
        except:
            pass
    
    embed = discord.Embed(
        title="✅ Товар выдан!",
        description=f"Товар '{name}' выдан пользователю {пользователь.mention}",
        color=discord.Color.green()
    )
    embed.add_field(name="Количество", value=f"`{кол_во}`", inline=True)
    
    await interaction.response.send_message(embed=embed)

# 21. REMOVE_ITEM
@bot.tree.command(name="remove_item", description="Админ: Забрать товар у пользователя")
@app_commands.checks.has_permissions(administrator=True)
async def remove_item(interaction: discord.Interaction, пользователь: discord.Member, id_товара: int, кол_во: int = 1):
    logger.info(f"🗑️ /remove_item | Админ: {interaction.user} ({interaction.user.id}) | У кого: {пользователь} ({пользователь.id}) | ID товара: {id_товара} | Кол-во: {кол_во}")
    guild_id = interaction.guild.id
    
    item = await get_shop_item(id_товара, guild_id)
    if not item:
        return await interaction.response.send_message("❌ Товар не найден.", ephemeral=True)
    
    item_id, name, description, price, item_type, role_id, is_one_time = item
    
    if кол_во <= 0:
        return await interaction.response.send_message("❌ Количество должно быть больше 0.", ephemeral=True)
    
    success = await remove_item_from_inventory(пользователь.id, guild_id, item_id, кол_во)
    
    if not success:
        return await interaction.response.send_message(f"❌ У пользователя недостаточно товара или он его не имеет.", ephemeral=True)
    
    embed = discord.Embed(
        title="✅ Товар забран!",
        description=f"Товар '{name}' забран у пользователя {пользователь.mention}",
        color=discord.Color.green()
    )
    embed.add_field(name="Количество", value=f"`{кол_во}`", inline=True)
    
    await interaction.response.send_message(embed=embed)
    
# 22. CREATE_PROMO
@bot.tree.command(name="create_promo", description="Админ: Создать промокод")
@app_commands.checks.has_permissions(administrator=True)
async def create_promo(interaction: discord.Interaction, код: str, сумма: int, время_окончания: Optional[str] = None, количество_использований: Optional[int] = None):
    logger.info(f"🎟️ /create_promo | Админ: {interaction.user} ({interaction.user.id}) | Код: {код} | Сумма: {сумма} | Лимит: {количество_использований}")
    expires_at = None
    if время_окончания:
        try:
            expires_at = datetime.strptime(время_окончания, "%Y-%m-%d %H:%M")
        except ValueError:
            return await interaction.response.send_message(
                "❌ Укажите время в формате: **YYYY-MM-DD HH:MM**\nПример: `2026-04-26 23:59`", 
                ephemeral=True
            )
            
    if количество_использований is not None and количество_использований < 1:
        return await interaction.response.send_message("❌ Количество использований должно быть больше 0.", ephemeral=True)

    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO promo_codes (code, reward, expires_at, created_by, max_uses) VALUES (?, ?, ?, ?, ?)",
                (код, сумма, expires_at.isoformat() if expires_at else None, interaction.user.id, количество_использований)
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            return await interaction.response.send_message("❌ Такой промокод уже существует.", ephemeral=True)
    
    embed = discord.Embed(
        title="✅ Промокод создан!",
        description=f"Промокод `{код}`",
        color=discord.Color.gold()
    )
    embed.add_field(name="Сумма", value=f"`{сумма}` Лоресиков", inline=True)
    
    limit_text = f"{количество_использований} раз" if количество_использований else "∞ (безлимитно)"
    embed.add_field(name="Лимит использований", value=limit_text, inline=True)
    
    if время_окончания:
        embed.add_field(name="Истекает", value=f"`{время_окончания}`", inline=True)
        
    embed.add_field(name="Инструкция", value=f"Пользователи активируют командой:\n`/promo {код}`", inline=False)
    
    await interaction.response.send_message(embed=embed)

# 23. DELETE_PROMO
@bot.tree.command(name="delete_promo", description="Админ: Удалить промокод")
@app_commands.checks.has_permissions(administrator=True)
async def delete_promo(interaction: discord.Interaction, код: str):
    logger.info(f"🗑️ /delete_promo | Админ: {interaction.user} ({interaction.user.id}) | Код: {код}")
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT code FROM promo_codes WHERE code = ?", (код,))
        row = await cursor.fetchone()
        
        if not row:
            return await interaction.response.send_message(f"❌ Промокод `{код}` не найден.", ephemeral=True)
        
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (код,))
        await db.commit()
    
    await interaction.response.send_message(f"✅ Промокод `{код}` удалён.")

# 24. LIST_PROMOS
@bot.tree.command(name="list_promos", description="Админ: Список всех промокодов")
@app_commands.checks.has_permissions(administrator=True)
async def list_promos(interaction: discord.Interaction):
    logger.info(f"📋 /list_promos | Админ: {interaction.user} ({interaction.user.id})")
    await interaction.response.defer()
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT code, reward, expires_at, created_by, max_uses FROM promo_codes ORDER BY code"
        )
        rows = await cursor.fetchall()
    
    if not rows:
        return await interaction.followup.send("❌ Промокодов нет.", ephemeral=True)
    
    embed = discord.Embed(title="🎁 Список промокодов", color=discord.Color.magenta())
    
    for code, reward, expires_at, created_by, max_uses in rows:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM promo_redemptions WHERE code = ?",
                (code,)
            )
            count = (await cursor.fetchone())[0]
        
        limit_str = f"/{max_uses}" if max_uses else "/∞"
        txt = f"**Сумма:** `{reward}` Лоресиков\n**Использовано:** `{count}{limit_str}`"
        
        if expires_at:
            try:
                expires = datetime.fromisoformat(expires_at)
                now = datetime.now(timezone.utc)
                is_expired = now > expires
                expire_status = "⏰ *истекает скоро*" if not is_expired else "❌ *истёк*"
                txt += f"\n**Истекает:** `{expires.strftime('%Y-%m-%d %H:%M')}` {expire_status}"
            except:
                txt += f"\n**Истекает:** `{expires_at}`"
        else:
            txt += "\n**Истекает:** ∞ (никогда)"
            
        if max_uses and count >= max_uses:
            txt += "\n⛔ **Лимит исчерпан**"
        
        embed.add_field(name=f"`{code}`", value=txt, inline=False)
    
    await interaction.followup.send(embed=embed)

# 25. PROMO
@bot.tree.command(name="promo", description="Активировать промокод")
async def promo(interaction: discord.Interaction, код: str):
    logger.info(f"🎫 /promo | Вызвал: {interaction.user} ({interaction.user.id}) | Код: {код}")
    user_id = interaction.user.id
    guild_id = interaction.guild.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT reward, expires_at, max_uses FROM promo_codes WHERE code = ?",
            (код,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return await interaction.response.send_message("❌ Промокод не найден.", ephemeral=True)
        
        reward, expires_at, max_uses = row
        
        if expires_at:
            try:
                expires = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) > expires:
                    return await interaction.response.send_message(
                        f"❌ Срок действия промокода истёк `{expires.strftime('%Y-%m-%d %H:%M')}`.",
                        ephemeral=True
                    )
            except Exception:
                pass
        
        if max_uses is not None:
            cursor = await db.execute("SELECT COUNT(*) FROM promo_redemptions WHERE code = ?", (код,))
            current_uses = (await cursor.fetchone())[0]
            
            if current_uses >= max_uses:
                return await interaction.response.send_message(
                    "❌ Этот промокод достиг лимита использований.",
                    ephemeral=True
                )
        
        cursor = await db.execute(
            "SELECT 1 FROM promo_redemptions WHERE code = ? AND user_id = ? AND guild_id = ?",
            (код, user_id, guild_id)
        )
        already = await cursor.fetchone()
        
        if already:
            return await interaction.response.send_message(
                "❌ Вы уже активировали этот промокод!",
                ephemeral=True
            )
        
        try:
            await db.execute(
                "INSERT INTO promo_redemptions (code, user_id, guild_id, redeemed_at) VALUES (?, ?, ?, ?)",
                (код, user_id, guild_id, datetime.now(timezone.utc).isoformat())
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            return await interaction.response.send_message(
                "❌ Вы уже активировали этот промокод!",
                ephemeral=True
            )
    
    await update_balance(user_id, guild_id, reward)
    
    embed = discord.Embed(
        title="🎉 Промокод активирован!",
        color=discord.Color.green()
    )
    embed.add_field(name="Вам начислено", value=f"`{reward}` Лоресиков", inline=True)
    embed.add_field(name="Новый баланс", value=f"`{await get_balance(user_id, guild_id)}` Лоресиков", inline=True)
    
    await interaction.response.send_message(embed=embed)
    
# 26. TOP
@bot.tree.command(name="top", description="Топ богачей сервера")
async def top(interaction: discord.Interaction):
    logger.info(f"🏆 /top | Вызвал: {interaction.user} ({interaction.user.id})")
    guild_id = interaction.guild.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT user_id, balance FROM users WHERE guild_id = ? ORDER BY balance DESC LIMIT 10",
            (guild_id,)
        )
        rows = await cursor.fetchall()
        
    if not rows:
        return await interaction.response.send_message("❌ База данных пуста.", ephemeral=True)
    
    embed = discord.Embed(title="🏆 Топ богачей сервера", color=discord.Color.gold())
    
    description_lines = []
    for index, (user_id, balance) in enumerate(rows, 1):
        member = interaction.guild.get_member(user_id)
        if member:
            name = member.display_name
        else:
            name = f"Участник <{user_id}>"
            
        medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else f"{index}."
        description_lines.append(f"**{medal}** {name} — `{balance}` Лоресиков")
        
    embed.description = "\n".join(description_lines)
    
    await interaction.response.send_message(embed=embed)
    
# 27. ROULETTE
@bot.tree.command(name="roulette", description="Европейская рулетка")
@app_commands.describe(
    ставка="Сумма Лоресиков",
    тип_ставки="red, black, zero, even, odd, или (0-36)"
)
async def roulette(interaction: discord.Interaction, ставка: int, тип_ставки: str):
    logger.info(f"🎰 /roulette | Вызвал: {interaction.user} | Ставка: {ставка}")
    user_id = interaction.user.id
    guild_id = interaction.guild.id
    choice = тип_ставки.lower().strip()

    if ставка < 10:
        return await interaction.response.send_message("❌ Минимальная ставка — 10.", ephemeral=True)
    
    bal = await get_balance(user_id, guild_id)
    if ставка > bal:
        return await interaction.response.send_message(f"❌ Недостаточно средств ({bal})", ephemeral=True)

    is_numeric = choice.isdigit() and 0 <= int(choice) <= 36
    if choice in ["zero", "0"]: 
        is_numeric = True
        choice = "0"
        
    valid_choices = ["red", "black", "even", "odd"]
    if not is_numeric and choice not in valid_choices:
        return await interaction.response.send_message("❌ Ошибка! Используй: `red`, `black`, `zero`, `even`, `odd` или число `1-36`.", ephemeral=True)

    await update_balance(user_id, guild_id, -ставка)
    
    await interaction.response.send_message("⚪ Шарик запущен... Колесо вращается...")

    if user_id not in user_retention_data: user_retention_data[user_id] = 0
    
    result = random.randint(0, 36)

    win_multiplier = 0
    res_color = ROULETTE_COLORS[result]
    
    if is_numeric and int(choice) == result:
        win_multiplier = 36 
    elif choice == "red" and res_color == "🔴":
        win_multiplier = 2
    elif choice == "black" and res_color == "⚫":
        win_multiplier = 2
    elif choice == "even" and result % 2 == 0:
        win_multiplier = 2
    elif choice == "odd" and result % 2 != 0:
        win_multiplier = 2

    if win_multiplier > 0:
        total_payout = ставка * win_multiplier
        await update_balance(user_id, guild_id, total_payout)
        user_retention_data[user_id] = 0
        color = discord.Color.green()
        title = "🎉 ПОБЕДА В РУЛЕТКЕ!"
        summary = f"💰 **+{total_payout}** Лоресиков"
        logger.info(f"🎰 /roulette | Результат: WIN | {interaction.user} выиграл {total_payout}")
    else:
        user_retention_data[user_id] += 1
        color = discord.Color.red() 
        title = "💀 СТАВКА НЕ СЫГРАЛА"
        summary = "Ничего не выпало. Попробуй еще раз!"
        logger.info(f"🎰 /roulette | Результат: LOSE | {interaction.user} проиграл {ставка}")

    def get_lane(res):
        items = []
        for i in range(res - 2, res + 3):
            n = i % 37
            c = ROULETTE_COLORS[n]
            if n == res: items.append(f"**[{c}{n}]**")
            else: items.append(f"{c}{n}")
        return " — ".join(items)

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Вращение", value=f"```\n{get_lane(result)}\n```", inline=False)
    
    bet_display = f"ЗЕРО" if choice == "0" else choice.upper()
    embed.add_field(name="Ваша ставка", value=f"`{bet_display}`", inline=True)
    embed.add_field(name="Выпало", value=f"{res_color} **{result}**", inline=True)
    
    embed.add_field(name="Итог", value=f"{summary}", inline=False)
    embed.set_footer(text=f"Баланс: {await get_balance(user_id, guild_id)}")

    await interaction.edit_original_response(content=None, embed=embed)
    
# --- ОБРАБОТЧИК ОШИБКО ---   
    
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    logger.error(f"❌ ERROR | Команда: {interaction.command.name if interaction.command else 'Unknown'} | Юзер: {interaction.user} ({interaction.user.id}) | Ошибка: {error}")
    
    is_responded = interaction.response.is_done()
    
    if isinstance(error, CheckFailure):
        embed = discord.Embed(
            title="❌ Доступ запрещён",
            description="Эта команда доступна только **администраторам сервера**!",
            color=discord.Color.red()
        )
        
        if is_responded:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    elif isinstance(error, Exception):
        embed = discord.Embed(
            title="❌ Ошибка команды",
            description=f"При выполнении команды произошла ошибка:\n```{str(error)[:100]}```",
            color=discord.Color.red()
        )
        
        if is_responded:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        print(f"Ошибка команды {interaction.command.name}: {error}")

# --- ЗАПУСК ---
@bot.event
async def on_ready():
    await init_db()
    logger.info(f"✅ БОТ ЗАПУЩЕН | Учётная запись: {bot.user} (ID: {bot.user.id})")
    logger.info(f"🌐 Бот подключён к {len(bot.guilds)} серверам")
    
load_dotenv()
bot.run(os.getenv("SECRET_KEY"))