import discord
from discord.ext import commands
from discord import app_commands
from logger_config import setup_logger

logger = setup_logger()

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Показать список всех команд")
    async def help_command(self, interaction: discord.Interaction):
        logger.info(f"ℹ️ /help | Вызвал: {interaction.user} (ID: {interaction.user.id})")
        embed = discord.Embed(title="📖 Справка по командам", color=discord.Color.green())
        
        embed.add_field(name="💰 Экономика и Игры", value=(
            "`/balance` — Проверить счет\n"
            "`/top` — Топ богачей сервера\n"
            "`/slots [сумма]` — Играть в казино\n"
            "`/roulette [сумма] [тип_ставки]` — Европейская рулетка\n"
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

async def setup(bot):
    await bot.add_cog(Help(bot))