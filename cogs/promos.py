import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
from typing import Optional
from logger_config import setup_logger
from utils.db import (
    get_balance, update_balance, get_promo,
    create_promo, delete_promo, get_all_promos,
    check_promo_redemption, add_promo_redemption,
    get_promo_use_count
)

logger = setup_logger()

class Promos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="promo", description="Активировать промокод")
    async def promo(self, interaction: discord.Interaction, код: str):
        logger.info(f"🎫 /promo | Вызвал: {interaction.user} ({interaction.user.id}) | Код: {код}")
        user_id = interaction.user.id
        guild_id = interaction.guild.id
        
        try:
            row = await get_promo(код)
            
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
                except Exception as e:
                    logger.error(f"Ошибка проверки срока промокода: {e}")
            
            if max_uses is not None:
                current_uses = await get_promo_use_count(код)
                
                if current_uses >= max_uses:
                    return await interaction.response.send_message(
                        "❌ Этот промокод достиг лимита использований.",
                        ephemeral=True
                    )
            
            already = await check_promo_redemption(код, user_id, guild_id)
            
            if already:
                return await interaction.response.send_message(
                    "❌ Вы уже активировали этот промокод!",
                    ephemeral=True
                )
            
            success = await add_promo_redemption(код, user_id, guild_id)
            
            if not success:
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /promo: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="create_promo", description="Админ: Создать промокод")
    @app_commands.checks.has_permissions(administrator=True)
    async def create_promo_cmd(self, interaction: discord.Interaction, код: str, сумма: int, время_окончания: Optional[str] = None, количество_использований: Optional[int] = None):
        logger.info(f"🎟️ /create_promo | Админ: {interaction.user} ({interaction.user.id}) | Код: {код} | Сумма: {сумма}")
        
        try:
            expires_at = None
            if время_окончания:
                try:
                    expires_at = datetime.strptime(время_окончания, "%Y-%m-%d %H:%M")
                except ValueError:
                    return await interaction.response.send_message(
                        "❌ Укажите время в формате: **YYYY-MM-DD HH:MM**\nПример: `2026-04-26 23:59`", 
                        ephemeral=True
                    )
            
            if сумма <= 0:
                return await interaction.response.send_message("❌ Сумма должна быть больше 0.", ephemeral=True)
                
            if количество_использований is not None and количество_использований < 1:
                return await interaction.response.send_message("❌ Количество использований должно быть больше 0.", ephemeral=True)

            success = await create_promo(
                код, сумма, 
                expires_at.isoformat() if expires_at else None, 
                interaction.user.id, 
                количество_использований
            )
            
            if not success:
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /create_promo: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="delete_promo", description="Админ: Удалить промокод")
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_promo_cmd(self, interaction: discord.Interaction, код: str):
        logger.info(f"🗑️ /delete_promo | Админ: {interaction.user} ({interaction.user.id}) | Код: {код}")
        
        try:
            row = await get_promo(код)
            
            if not row:
                return await interaction.response.send_message(f"❌ Промокод `{код}` не найден.", ephemeral=True)
            
            await delete_promo(код)
            
            await interaction.response.send_message(f"✅ Промокод `{код}` удалён.")
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /delete_promo: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="list_promos", description="Админ: Список всех промокодов")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_promos(self, interaction: discord.Interaction):
        logger.info(f"📋 /list_promos | Админ: {interaction.user} ({interaction.user.id})")
        
        try:
            await interaction.response.defer()
            
            rows = await get_all_promos()
            
            if not rows:
                return await interaction.followup.send("❌ Промокодов нет.", ephemeral=True)
            
            embed = discord.Embed(title="🎁 Список промокодов", color=discord.Color.magenta())
            
            for code, reward, expires_at, created_by, max_uses in rows:
                count = await get_promo_use_count(code)
                
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /list_promos: {e}")
            try:
                await interaction.followup.send(
                    f"❌ Произошла ошибка: {str(e)[:100]}",
                    ephemeral=True
                )
            except:
                pass

async def setup(bot):
    await bot.add_cog(Promos(bot))