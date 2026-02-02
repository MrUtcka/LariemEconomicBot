import discord
import aiosqlite
import asyncio
import json
import random
import sys
import io
import os
from dotenv import load_dotenv
from discord.ext import commands
from discord import app_commands

# --- Исправление кодировки для Windows ---
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# --- Настройки Бота ---
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

# --- Настройки Казино (Slots) ---
SLOTS_WEIGHTED = (["🍋"] * 10 + ["🍎"] * 8 + ["🍒"] * 5 + ["💎"] * 2 + ["7️⃣"] * 1)
SLOT_PAYOUTS = {"🍋": 3, "🍎": 5, "🍒": 10, "💎": 25, "7️⃣": 50}

# --- Функции Базы Данных ---
async def init_db():
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
        await db.commit()
    await load_events_from_db()

async def load_events_from_db():
    global active_events
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT guild_id, event_id, data FROM saved_events")
        rows = await cursor.fetchall()
        for g_id, e_id, data_str in rows:
            if g_id not in active_events: active_events[g_id] = {}
            active_events[g_id][int(e_id)] = json.loads(data_str)

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

# --- ВСЕ КОМАНДЫ (SLASH) ---

# 0. HELP
@bot.tree.command(name="help", description="Показать список всех команд")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Справка по командам", color=discord.Color.green())
    
    embed.add_field(name="💰 Экономика и Игры", value=(
        "`/balance` — Проверить счет\n"
        "`/slots [сумма]` — Играть в казино\n"
        "`/events` — Список активных матчей\n"
        "`/bet [id_события] [выбор] [сумма]` — Сделать ставку"
    ), inline=False)

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
    
    await interaction.response.send_message(embed=embed)

# 1. BALANCE
@bot.tree.command(name="balance", description="Посмотреть баланс")
async def balance(interaction: discord.Interaction, пользователь: discord.Member = None):
    target = пользователь or interaction.user
    bal = await get_balance(target.id, interaction.guild.id)
    await interaction.response.send_message(f"💰 Баланс {target.mention}: `{bal}` Лоресиков.")

# 2. SLOTS
@bot.tree.command(name="slots", description="Сыграть в казино")
async def slots(interaction: discord.Interaction, сумма: int):
    if сумма < 10: return await interaction.response.send_message("❌ Минимум 10 Лоресиков.", ephemeral=True)
    bal = await get_balance(interaction.user.id, interaction.guild.id)
    if сумма > bal: return await interaction.response.send_message("❌ Недостаточно Лоресиков.", ephemeral=True)

    await update_balance(interaction.user.id, interaction.guild.id, -сумма)
    await interaction.response.send_message("🎰 **Крутим...**")
    await asyncio.sleep(1)

    res = [random.choice(SLOTS_WEIGHTED) for _ in range(3)]
    line = " | ".join(res)
    if res[0] == res[1] == res[2]:
        win = сумма * SLOT_PAYOUTS[res[0]]
        await update_balance(interaction.user.id, interaction.guild.id, win)
        msg = f"🎉 **ВЫИГРЫШ!** {win} Лоресиков!"
    else:
        msg = "❌ Проигрыш."

    embed = discord.Embed(title="Игровой автомат", description=f"**[ {line} ]**\n\n{msg}", color=discord.Color.orange())
    await interaction.edit_original_response(content=None, embed=embed)

# 3. EVENTS
@bot.tree.command(name="events", description="Список событий или полная информация по ID")
async def events(interaction: discord.Interaction, id_события: int = None):
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
@bot.tree.command(name="create_match", description="Админ: Создать матч с составами")
@app_commands.checks.has_permissions(administrator=True)
async def create_match(interaction: discord.Interaction, команда1: str, ростер1: str, кэф1: float, команда2: str, ростер2: str, кэф2: float):
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
@bot.tree.command(name="create_mvp", description="Админ: Ставка на MVP с разными коэффициентами")
@app_commands.checks.has_permissions(administrator=True)
async def create_mvp(interaction: discord.Interaction, название: str, данные: str):
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
@bot.tree.command(name="create_total", description="Админ: Создать тотал (Больше/Меньше)")
@app_commands.checks.has_permissions(administrator=True)
async def create_total(interaction: discord.Interaction, описание: str, кэф_бол: float, кэф_мен: float):
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
    if id_события in active_events.get(interaction.guild.id, {}):
        active_events[interaction.guild.id][id_события]["locked"] = True
        await interaction.response.send_message(f"🔒 Ставки на #{id_события} закрыты.")

# 9. UNLOCK
@bot.tree.command(name="unlock", description="Админ: Открыть ставки")
@app_commands.checks.has_permissions(administrator=True)
async def unlock(interaction: discord.Interaction, id_события: int):
    if id_события in active_events.get(interaction.guild.id, {}):
        active_events[interaction.guild.id][id_события]["locked"] = False
        await interaction.response.send_message(f"🔓 Ставки на #{id_события} открыты.")

# 10. SETTLE
@bot.tree.command(name="settle", description="Админ: Завершить событие и выплатить выигрыши")
@app_commands.checks.has_permissions(administrator=True)
async def settle(interaction: discord.Interaction, id_события: int, победитель: str):
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
    await update_balance(пользователь.id, interaction.guild.id, сумма)
    await interaction.response.send_message(f"✅ Выдано {сумма} пользователю {пользователь.mention}")

# 12. REMOVE
@bot.tree.command(name="remove", description="Админ: Забрать Лоресиков")
@app_commands.checks.has_permissions(administrator=True)
async def remove(interaction: discord.Interaction, пользователь: discord.Member, сумма: int):
    await update_balance(пользователь.id, interaction.guild.id, -сумма)
    await interaction.response.send_message(f"✅ Забрано {сумма} у пользователя {пользователь.mention}")
    
# 13. PAY 
@bot.tree.command(name="pay", description="Передать Лоресики другому пользователю")
async def pay(interaction: discord.Interaction, получатель: discord.Member, колво: int):
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

# --- ЗАПУСК ---
@bot.event
async def on_ready():
    await init_db()
    print(f"Logged in as {bot.user}")
    
load_dotenv()
bot.run(os.getenv("SECRET_KEY"))