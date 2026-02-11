import discord
from discord.ext import commands
from discord import app_commands
from logger_config import setup_logger
from utils.db import (
    get_balance, update_balance, get_user_top
)

logger = setup_logger()

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="balance", description="Посмотреть баланс")
    async def balance(self, interaction: discord.Interaction, пользователь: discord.Member = None):
        target = пользователь or interaction.user
        logger.info(f"💰 /balance | Вызвал: {interaction.user} ({interaction.user.id}) | Цель: {target} (ID: {target.id})")
        
        bal = await get_balance(target.id, interaction.guild.id)
        await interaction.response.send_message(f"💰 Баланс {target.mention}: `{bal}` Лоресиков.")

    @app_commands.command(name="top", description="Топ богачей сервера")
    async def top(self, interaction: discord.Interaction):
        logger.info(f"🏆 /top | Вызвал: {interaction.user} ({interaction.user.id})")
        
        guild_id = interaction.guild.id
        
        rows = await get_user_top(guild_id)
        
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

    @app_commands.command(name="pay", description="Передать Лоресики другому пользователю")
    async def pay(self, interaction: discord.Interaction, получатель: discord.Member, колво: int):
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

async def setup(bot):
    await bot.add_cog(Economy(bot))