import discord
import random
from discord.ext import commands
from discord import app_commands, ui
from logger_config import setup_logger
from utils.db import get_balance, update_balance

logger = setup_logger()

user_retention_data = {}

# Константы для слотов
SYM_WILD = "👑"
SYM_SCATTER = "⭐"
SYM_HIGH = ["💎", "7️⃣"]
SYM_MID = ["🔔", "🍉", "🍇"]
SYM_LOW = ["🍋", "🍒", "🍎"]
SYM_EMPTY = "⬛"

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

ROULETTE_COLORS = {
    0: "🟢",
    **{n: "🔴" for n in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]},
    **{n: "⚫" for n in [2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35]}
}

# Константы для бомб
CLOSED_CELL = "🔲"
REVEALED_BOMB = "☠️"
REVEALED_CRYSTAL = "✨"

# Шаг коэффициента зависит от кол-ва бомб
BOMB_COEFFICIENT_STEPS = {
    1: 0.05,
    2: 0.10,
    3: 0.15,
    4: 0.20,
    5: 0.25,
    6: 0.30,
    7: 0.35,
    8: 0.40,
}

def get_bomb_coefficient(bombs_count, crystals_found):
    """Получить коэффициент в зависимости от кол-ва бомб и открытых кристаллов"""
    if bombs_count not in BOMB_COEFFICIENT_STEPS:
        bombs_count = 8
    
    step = BOMB_COEFFICIENT_STEPS[bombs_count]
    coeff = 1.0 + (step * crystals_found)
    return coeff

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

class BombButton(ui.Button):
    def __init__(self, row: int, col: int, game_view: 'BombGameView', position: int):
        labels = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
        super().__init__(style=discord.ButtonStyle.secondary, label=labels[position], row=row)
        self.row_idx = row
        self.col_idx = col
        self.game_view = game_view

    async def callback(self, interaction: discord.Interaction):
        game_data = self.game_view.game_data
        
        if interaction.user.id != game_data['user_id']:
            await interaction.response.defer()
            return

        if game_data['revealed'][self.row_idx][self.col_idx]:
            await interaction.response.defer()
            return

        game_data['revealed'][self.row_idx][self.col_idx] = True
        is_bomb = game_data['grid'][self.row_idx][self.col_idx]

        await interaction.response.defer()

        if is_bomb:
            await self.game_view.end_game_lose(interaction)
        else:
            # Проверяем, все ли кристаллы открыты
            crystals_found = sum(1 for y in range(3) for x in range(3) 
                               if game_data['revealed'][y][x] and not game_data['grid'][y][x])
            
            if crystals_found == game_data['crystals_total']:
                # Все кристаллы найдены - автоматический финиш
                await self.game_view.finish_game(interaction, auto_win=True)
            else:
                # Обновляем доску
                await self.game_view.update_game_board(interaction)

class FinishButton(ui.Button):
    def __init__(self, game_view: 'BombGameView'):
        super().__init__(style=discord.ButtonStyle.success, label="✅ Закончить", row=2)
        self.game_view = game_view

    async def callback(self, interaction: discord.Interaction):
        game_data = self.game_view.game_data
        
        if interaction.user.id != game_data['user_id']:
            await interaction.response.defer()
            return

        await interaction.response.defer()
        await self.game_view.finish_game(interaction, auto_win=False)

class BombGameView(ui.View):
    def __init__(self, game_data):
        super().__init__(timeout=600)
        self.game_data = game_data

    def _render_bomb_board(self):
        """Отрисовывает поле бомб 3x3"""
        revealed = self.game_data['revealed']
        grid = self.game_data['grid']
        
        board = ""
        for row_idx in range(3):
            row = ""
            for col_idx in range(3):
                if revealed[row_idx][col_idx]:
                    if grid[row_idx][col_idx]:
                        row += REVEALED_BOMB + " "
                    else:
                        row += REVEALED_CRYSTAL + " "
                else:
                    row += CLOSED_CELL + " "
            board += row + "\n"
        return board

    async def update_game_board(self, interaction: discord.Interaction):
        """Обновляет доску игры"""
        board = self._render_bomb_board()
        crystals_found = sum(1 for y in range(3) for x in range(3) 
                           if self.game_data['revealed'][y][x] and not self.game_data['grid'][y][x])
        coeff = get_bomb_coefficient(self.game_data['bombs_count'], crystals_found)

        embed = discord.Embed(
            title="💣 БОМБЫ 💣",
            description=f"Ищи кристаллы и избегай бомб!\n\n**Ставка:** `{self.game_data['bet']}` Лоресиков",
            color=discord.Color.purple()
        )
        embed.add_field(name="Поле:", value=board, inline=False)
        embed.add_field(name="Бомб на поле", value=f"`{self.game_data['bombs_count']}`", inline=True)
        embed.add_field(name="Текущий коэффициент", value=f"x`{coeff:.2f}`", inline=True)
        embed.add_field(name="Открыто кристаллов", value=f"`{crystals_found}/{self.game_data['crystals_total']}`", inline=True)

        await interaction.message.edit(embed=embed, view=self)

    async def end_game_lose(self, interaction: discord.Interaction):
        """Завершение игры - поражение"""
        for y in range(3):
            for x in range(3):
                self.game_data['revealed'][y][x] = True

        board = self._render_bomb_board()
        user_retention_data[self.game_data['user_id']] = user_retention_data.get(self.game_data['user_id'], 0) + 1

        embed = discord.Embed(
            title="☠️ ИГРА ОКОНЧЕНА - БОМБА!",
            color=discord.Color.red()
        )
        embed.add_field(name="Поле:", value=board, inline=False)
        embed.add_field(name="Результат:", value="💔 Ставка потеряна", inline=False)
        new_bal = await get_balance(interaction.user.id, self.game_data['guild_id'])
        embed.set_footer(text=f"Ваш баланс: {new_bal} Лоресиков")

        await interaction.message.edit(embed=embed, view=None)

        logger.info(f"💣 /bombs | {interaction.user} попал на бомбу и проиграл {self.game_data['bet']}")

    async def finish_game(self, interaction: discord.Interaction, auto_win: bool = False):
        """Завершение игры - финиш с текущим коэффициентом"""
        crystals_found = sum(1 for y in range(3) for x in range(3) 
                           if self.game_data['revealed'][y][x] and not self.game_data['grid'][y][x])
        
        # Если не все кристаллы найдены и это не автоматический финиш
        if crystals_found < self.game_data['crystals_total'] and not auto_win:
            # Проверяем систему 50%
            if not self.game_data['will_win']:
                # Игрок должен проиграть - находим случайную бомбу и "взрываем" её
                bomb_cells = [(y, x) for y in range(3) for x in range(3) 
                             if not self.game_data['revealed'][y][x] and self.game_data['grid'][y][x]]
                if bomb_cells:
                    y, x = random.choice(bomb_cells)
                    self.game_data['revealed'][y][x] = True
                    
                    for row in range(3):
                        for col in range(3):
                            self.game_data['revealed'][row][col] = True

                    board = self._render_bomb_board()
                    user_retention_data[self.game_data['user_id']] = user_retention_data.get(self.game_data['user_id'], 0) + 1

                    embed = discord.Embed(
                        title="☠️ ИГРА ОКОНЧЕНА - БОМБА!",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="Поле:", value=board, inline=False)
                    embed.add_field(name="Результат:", value="💔 Ставка потеряна", inline=False)
                    new_bal = await get_balance(interaction.user.id, self.game_data['guild_id'])
                    embed.set_footer(text=f"Ваш баланс: {new_bal} Лоресиков")

                    await interaction.message.edit(embed=embed, view=None)
                    logger.info(f"💣 /bombs | {interaction.user} попал на скрытую бомбу при финише и проиграл {self.game_data['bet']}")
                    return
        
        # Игрок выигрывает
        coeff = get_bomb_coefficient(self.game_data['bombs_count'], crystals_found)
        payout = int(self.game_data['bet'] * coeff)

        await update_balance(interaction.user.id, self.game_data['guild_id'], payout)
        user_retention_data[interaction.user.id] = 0

        for y in range(3):
            for x in range(3):
                self.game_data['revealed'][y][x] = True

        board = self._render_bomb_board()

        # Определяем сообщение в зависимости от типа финиша
        finish_type = "Все кристаллы найдены!" if auto_win else "Финиш выигрыш!"

        embed = discord.Embed(
            title="🎉 ИГРА ЗАВЕРШЕНА - ПОБЕДА!",
            color=discord.Color.green()
        )
        embed.add_field(name="Поле:", value=board, inline=False)
        embed.add_field(name="Открыто кристаллов", value=f"`{crystals_found}/{self.game_data['crystals_total']}`", inline=True)
        embed.add_field(name="Бомб на поле", value=f"`{self.game_data['bombs_count']}`", inline=True)
        embed.add_field(name="Коэффициент", value=f"x`{coeff:.2f}`", inline=True)
        embed.add_field(name="Результат:", value=f"💰 **+{payout}** Лоресиков\n_{finish_type}_", inline=False)
        new_bal = await get_balance(interaction.user.id, self.game_data['guild_id'])
        embed.set_footer(text=f"Ваш баланс: {new_bal} Лоресиков")

        await interaction.message.edit(embed=embed, view=None)

        logger.info(f"💣 /bombs | {interaction.user} выиграл {payout} (кристаллов: {crystals_found}, коэф: {coeff:.2f}, авто: {auto_win})")

class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="slots", description="Слот-машина 3x5")
    async def slots(self, interaction: discord.Interaction, ставка: int):
        logger.info(f"🎰 /slots | Вызвал: {interaction.user} | Ставка: {ставка}")
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        if ставка < 10:
            return await interaction.response.send_message("❌ Минимальная ставка — 10.", ephemeral=True)
        
        bal = await get_balance(user_id, guild_id)
        if ставка > bal:
            return await interaction.response.send_message(f"❌ Недостаточно средств ({bal})", ephemeral=True)

        await interaction.response.defer()

        await update_balance(user_id, guild_id, -ставка)
        
        if user_id not in user_retention_data:
            user_retention_data[user_id] = 0
        
        loss_streak = user_retention_data[user_id]
        pity_chance = min(0.70, loss_streak * 0.07)
        
        if loss_streak >= 2 and random.random() < pity_chance:
            grid = force_win_grid()
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

        embed.add_field(name="Результат:", value=result_text, inline=False)
        new_bal = await get_balance(user_id, guild_id)
        embed.set_footer(text=f"Ваш баланс: {new_bal} Лоресиков")

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="roulette", description="Европейская рулетка")
    @app_commands.describe(
        ставка="Сумма Лоресиков",
        тип_ставки="red, black, zero, even, odd, или (0-36)"
    )
    async def roulette(self, interaction: discord.Interaction, ставка: int, тип_ставки: str):
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

        await interaction.response.send_message("⚪ Шарик запущен... Колесо вращается...")

        await update_balance(user_id, guild_id, -ставка)

        if user_id not in user_retention_data: 
            user_retention_data[user_id] = 0
        
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
        
        embed.add_field(name="Результат:", value=f"{summary}", inline=False)
        new_bal = await get_balance(user_id, guild_id)
        embed.set_footer(text=f"Ваш баланс: {new_bal} Лоресиков")

        await interaction.edit_original_response(content=None, embed=embed)

    @app_commands.command(name="bombs", description="Игра 'Бомбы' - ищи кристаллы, избегай бомб")
    @app_commands.describe(
        ставка="Сумма Лоресиков",
        бомб="Количество бомб на поле (1-8)"
    )
    async def bombs(self, interaction: discord.Interaction, ставка: int, бомб: int = 3):
        logger.info(f"💣 /bombs | Вызвал: {interaction.user} | Ставка: {ставка} | Бомб: {бомб}")
        user_id = interaction.user.id
        guild_id = interaction.guild.id

        if ставка < 10:
            return await interaction.response.send_message("❌ Минимальная ставка — 10.", ephemeral=True)
        
        if бомб < 1 or бомб > 8:
            return await interaction.response.send_message("❌ Количество бомб должно быть от 1 до 8.", ephemeral=True)
        
        bal = await get_balance(user_id, guild_id)
        if ставка > bal:
            return await interaction.response.send_message(f"❌ Недостаточно средств ({bal})", ephemeral=True)

        await interaction.response.defer()

        if user_id not in user_retention_data:
            user_retention_data[user_id] = 0
        
        loss_streak = user_retention_data[user_id]
        win_chance = min(0.70, 0.3 + (loss_streak * 0.08))

        await update_balance(user_id, guild_id, -ставка)

        grid = [[False for _ in range(3)] for _ in range(3)]
        
        bomb_positions = set()
        while len(bomb_positions) < бомб:
            x = random.randint(0, 2)
            y = random.randint(0, 2)
            bomb_positions.add((x, y))
        
        for x, y in bomb_positions:
            grid[y][x] = True

        game_data = {
            'grid': grid,
            'bomb_positions': bomb_positions,
            'revealed': [[False for _ in range(3)] for _ in range(3)],
            'bet': ставка,
            'bombs_count': бомб,
            'crystals_total': 9 - бомб,
            'will_win': random.random() < win_chance,
            'user_id': user_id,
            'guild_id': guild_id,
        }

        view = BombGameView(game_data)
        
        position = 0
        for row in range(3):
            for col in range(3):
                button = BombButton(row, col, view, position)
                view.add_item(button)
                position += 1
        
        view.add_item(FinishButton(view))

        board = view._render_bomb_board()
        current_coeff = get_bomb_coefficient(бомб, 0)
        embed = discord.Embed(
            title="💣 БОМБЫ 💣",
            description=f"Ищи кристаллы и избегай бомб!\n\n**Ставка:** `{ставка}` Лоресиков",
            color=discord.Color.purple()
        )
        embed.add_field(name="Поле:", value=board, inline=False)
        embed.add_field(name="Бомб на поле", value=f"`{бомб}`", inline=True)
        embed.add_field(name="Текущий коэффициент", value=f"x`{current_coeff:.2f}`", inline=True)
        embed.add_field(name="Кристаллов доступно", value=f"`{9 - бомб}`", inline=True)
        new_bal = await get_balance(user_id, guild_id)
        embed.set_footer(text=f"Ваш баланс: {new_bal} Лоресиков")

        msg = await interaction.followup.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Games(bot))