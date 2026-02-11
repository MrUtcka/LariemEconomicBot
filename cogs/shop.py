import discord
from discord.ext import commands
from discord import app_commands
from logger_config import setup_logger
from utils.db import (
    get_balance, update_balance, get_shop_items, get_shop_item,
    get_user_inventory, add_item_to_inventory, remove_item_from_inventory,
    is_one_time_purchased, mark_one_time_purchased
)

logger = setup_logger()

class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="shop", description="Просмотреть магазин")
    async def shop(self, interaction: discord.Interaction):
        logger.info(f"🏪 /shop | Вызвал: {interaction.user} ({interaction.user.id})")
        
        try:
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /shop: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="inventory", description="Посмотреть инвентарь")
    async def inventory(self, interaction: discord.Interaction, пользователь: discord.Member = None):
        target = пользователь or interaction.user
        logger.info(f"🎒 /inventory | Вызвал: {interaction.user} ({interaction.user.id}) | Чей инвентарь: {target} ({target.id})")
        
        try:
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /inventory: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="buy", description="Купить товар")
    async def buy(self, interaction: discord.Interaction, id_товара: int, кол_во: int = 1):
        logger.info(f"🛒 /buy | Вызвал: {interaction.user} ({interaction.user.id}) | ID товара: {id_товара} | Кол-во: {кол_во}")
        
        try:
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
                    logger.error(f"Ошибка выдачи роли: {e}")
            
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /buy: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Shop(bot))