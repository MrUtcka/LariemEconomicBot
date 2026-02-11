import discord
import asyncio
import os
import sys
from dotenv import load_dotenv
from discord.ext import commands
from logger_config import setup_logger
from config import SECRET_KEY

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
        logger.info("✅ Команды синхронизированы с Discord")

async def load_cogs(bot):
    cogs_dir = "cogs"
    
    if not os.path.exists(cogs_dir):
        logger.error(f"❌ Папка {cogs_dir} не найдена!")
        return
    
    loaded_count = 0
    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            cog_name = filename[:-3]
            try:
                await bot.load_extension(f"cogs.{cog_name}")
                logger.info(f"✅ Загружен cog: {cog_name}")
                loaded_count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки {cog_name}: {e}")
    
    logger.info(f"📦 Всего загружено cogs: {loaded_count}")

bot = MyBot()

# --- ОСНОВНОЕ СОБЫТИЕ ---

@bot.event
async def on_ready():
    from utils import init_db
    await init_db()
    logger.info(f"✅ БОТ ЗАПУЩЕН | Учётная запись: {bot.user} (ID: {bot.user.id})")
    logger.info(f"🌐 Бот подключён к {len(bot.guilds)} серверам")

# --- ОБРАБОТЧИК ОШИБОК ---

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    from discord.app_commands import CheckFailure
    
    logger.error(f"❌ ERROR | Команда: {interaction.command.name if interaction.command else 'Unknown'} | Юзер: {interaction.user} ({interaction.user.id}) | Ошибка: {error}")
    
    try:
        if interaction.response.is_done():
            logger.error(f"❌ Взаимодействие уже обработано, пропускаем отправку ошибки")
            return
    except:
        pass
    
    try:
        if isinstance(error, CheckFailure):
            embed = discord.Embed(
                title="❌ Доступ запрещён",
                description="Эта команда доступна только **администраторам сервера**!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        
        else:
            embed = discord.Embed(
                title="❌ Ошибка команды",
                description=f"При выполнении команды произошла ошибка:\n```{str(error)[:100]}```",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    except Exception as handler_error:
        logger.error(f"❌ Ошибка в обработчике ошибок: {handler_error}")

# --- ЗАПУСК ---

async def main():
    async with bot:
        await load_cogs(bot)
        await bot.start(SECRET_KEY)

if __name__ == "__main__":
    asyncio.run(main())