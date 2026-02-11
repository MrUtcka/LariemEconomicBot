import discord
from discord.ext import commands
from discord import app_commands
from logger_config import setup_logger
from utils.db import (
    get_balance, update_balance, get_shop_item,
    create_shop_item, delete_shop_item,
    add_item_to_inventory, remove_item_from_inventory
)

logger = setup_logger()

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="give", description="Админ: Выдать Лоресиков")
    @app_commands.checks.has_permissions(administrator=True)
    async def give(self, interaction: discord.Interaction, пользователь: discord.Member, сумма: int):
        logger.info(f"💸 /give | Админ: {interaction.user} ({interaction.user.id}) | Кому: {пользователь} ({пользователь.id}) | Сумма: {сумма}")
        
        try:
            if сумма <= 0:
                return await interaction.response.send_message("❌ Сумма должна быть больше 0.", ephemeral=True)
            
            await update_balance(пользователь.id, interaction.guild.id, сумма)
            await interaction.response.send_message(f"✅ Выдано {сумма} пользователю {пользователь.mention}")
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /give: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="remove", description="Админ: Забрать Лоресиков")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove(self, interaction: discord.Interaction, пользователь: discord.Member, сумма: int):
        logger.info(f"💸 /remove | Админ: {interaction.user} ({interaction.user.id}) | У кого: {пользователь} ({пользователь.id}) | Сумма: {сумма}")
        
        try:
            if сумма <= 0:
                return await interaction.response.send_message("❌ Сумма должна быть больше 0.", ephemeral=True)
            
            await update_balance(пользователь.id, interaction.guild.id, -сумма)
            await interaction.response.send_message(f"✅ Забрано {сумма} у пользователя {пользователь.mention}")
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /remove: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="create_item", description="Админ: Создать товар")
    @app_commands.checks.has_permissions(administrator=True)
    async def create_item(self, interaction: discord.Interaction, название: str, описание: str, цена: int, одноразовый: bool = False):
        logger.info(f"🔨 /create_item | Админ: {interaction.user} ({interaction.user.id}) | Товар: {название} | Цена: {цена}")
        
        try:
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /create_item: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="create_role_item", description="Админ: Создать товар-роль")
    @app_commands.checks.has_permissions(administrator=True)
    async def create_role_item(self, interaction: discord.Interaction, название: str, описание: str, цена: int, роль: discord.Role, одноразовый: bool = False):
        logger.info(f"👑 /create_role_item | Админ: {interaction.user} ({interaction.user.id}) | Товар: {название} | Роль: {роль.name}")
        
        try:
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /create_role_item: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="delete_item", description="Админ: Удалить товар")
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_item(self, interaction: discord.Interaction, id_товара: int):
        logger.info(f"🗑️ /delete_item | Админ: {interaction.user} ({interaction.user.id}) | ID товара: {id_товара}")
        
        try:
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /delete_item: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="give_item", description="Админ: Выдать товар пользователю")
    @app_commands.checks.has_permissions(administrator=True)
    async def give_item(self, interaction: discord.Interaction, пользователь: discord.Member, id_товара: int, кол_во: int = 1):
        logger.info(f"📦 /give_item | Админ: {interaction.user} ({interaction.user.id}) | Кому: {пользователь} ({пользователь.id}) | ID товара: {id_товара} | Кол-во: {кол_во}")
        
        try:
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
                except Exception as e:
                    logger.error(f"Ошибка выдачи роли: {e}")
            
            embed = discord.Embed(
                title="✅ Товар выдан!",
                description=f"Товар '{name}' выдан пользователю {пользователь.mention}",
                color=discord.Color.green()
            )
            embed.add_field(name="Количество", value=f"`{кол_во}`", inline=True)
            
            await interaction.response.send_message(embed=embed)
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /give_item: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="remove_item", description="Админ: Забрать товар у пользователя")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_item(self, interaction: discord.Interaction, пользователь: discord.Member, id_товара: int, кол_во: int = 1):
        logger.info(f"🗑️ /remove_item | Админ: {interaction.user} ({interaction.user.id}) | У кого: {пользователь} ({пользователь.id}) | ID товара: {id_товара} | Кол-во: {кол_во}")
        
        try:
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /remove_item: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Admin(bot))