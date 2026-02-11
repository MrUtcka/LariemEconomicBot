import discord
import json
from discord.ext import commands
from discord import app_commands
from logger_config import setup_logger
from utils.db import (
    load_events_from_db, save_event, delete_event, 
    get_event_bets, place_bet, get_balance, update_balance
)

logger = setup_logger()

active_events = {}

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_events = active_events

    async def cog_load(self):
        global active_events
        active_events = await load_events_from_db()
        self.active_events = active_events

    @app_commands.command(name="events", description="Список событий")
    async def events(self, interaction: discord.Interaction, id_события: int = None):
        logger.info(f"📅 /events | Вызвал: {interaction.user} ({interaction.user.id}) | ID события: {id_события if id_события else 'Все'}")
        
        try:
            evs = self.active_events.get(interaction.guild.id, {})
            
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
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /events: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="bet", description="Сделать ставку")
    async def bet(self, interaction: discord.Interaction, id_события: int, выбор: str, сумма: int):
        logger.info(f"🎲 /bet | Вызвал: {interaction.user} ({interaction.user.id}) | EventID: {id_события}")
        
        try:
            ev = self.active_events.get(interaction.guild.id, {}).get(id_события)
            if not ev: 
                return await interaction.response.send_message("❌ Матч не найден.", ephemeral=True)
            if ev["locked"]: 
                return await interaction.response.send_message("❌ Ставки закрыты.", ephemeral=True)
            
            choice_key = выбор.lower()
            if choice_key not in ev["options"]:
                return await interaction.response.send_message(f"❌ Варианты: {', '.join(ev['options'].keys())}", ephemeral=True)

            bal = await get_balance(interaction.user.id, interaction.guild.id)
            if сумма < 10 or сумма > bal: 
                return await interaction.response.send_message("❌ Ошибка суммы.", ephemeral=True)

            await place_bet(interaction.user.id, interaction.guild.id, id_события, choice_key, сумма, ev["options"][choice_key]["coeff"])
            await update_balance(interaction.user.id, interaction.guild.id, -сумма)
            await interaction.response.send_message(f"✅ Ставка `{сумма}` на **{выбор}** принята!")
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /bet: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="create_match", description="Админ: Создать матч")
    @app_commands.checks.has_permissions(administrator=True)
    async def create_match(self, interaction: discord.Interaction, команда1: str, ростер1: str, кэф1: float, команда2: str, ростер2: str, кэф2: float):
        logger.info(f"⚔️ /create_match | Админ: {interaction.user} ({interaction.user.id})")
        
        try:
            eid = (max(self.active_events.get(interaction.guild.id, {}).keys()) if self.active_events.get(interaction.guild.id, {}) else 0) + 1
            
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
            
            self.active_events.setdefault(interaction.guild.id, {})[eid] = event_data
            await save_event(interaction.guild.id, eid, event_data)

            embed = discord.Embed(title="🔔 НОВОЕ СОБЫТИЕ ОПУБЛИКОВАНО", color=discord.Color.gold())
            embed.add_field(name=f"🎮 Матч #{eid}", value=f"**{команда1}** vs **{команда2}**", inline=False)
            embed.add_field(name=f"📈 Коэффициенты", value=f"{команда1}: `{кэф1}` | {команда2}: `{кэф2}`", inline=False)
            embed.add_field(name=f"👥 Состав {команда1}", value=f"*{ростер1}*", inline=True)
            embed.add_field(name=f"👥 Состав {команда2}", value=f"*{ростер2}*", inline=True)
            embed.set_footer(text="Для ставки используйте /bet")
            
            await interaction.response.send_message(embed=embed)
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /create_match: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="create_mvp", description="Админ: Ставка на MVP")
    @app_commands.checks.has_permissions(administrator=True)
    async def create_mvp(self, interaction: discord.Interaction, название: str, данные: str):
        logger.info(f"⭐ /create_mvp | Админ: {interaction.user} ({interaction.user.id})")
        
        try:
            guild_id = interaction.guild.id
            
            eid = (max(self.active_events.get(guild_id, {}).keys()) if self.active_events.get(guild_id, {}) else 0) + 1
            
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

            self.active_events.setdefault(guild_id, {})[eid] = event_data
            await save_event(guild_id, eid, event_data)

            embed = discord.Embed(
                title="🌟 РЕГИСТРАЦИЯ СТАВОК НА MVP", 
                description=f"Событие: **{название}** (ID: `{eid}`)",
                color=discord.Color.gold()
            )
            embed.add_field(name="Участники и коэффициенты:", value="\n".join(player_list_display), inline=False)
            embed.set_footer(text="Ставка: /bet")
            
            await interaction.response.send_message(embed=embed)
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /create_mvp: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="create_total", description="Админ: Создать тотал")
    @app_commands.checks.has_permissions(administrator=True)
    async def create_total(self, interaction: discord.Interaction, описание: str, кэф_бол: float, кэф_мен: float):
        logger.info(f"📊 /create_total | Админ: {interaction.user} ({interaction.user.id})")
        
        try:
            eid = (max(self.active_events.get(interaction.guild.id, {}).keys()) if self.active_events.get(interaction.guild.id, {}) else 0) + 1
            
            event_data = {
                "type": "total", 
                "title": описание,
                "options": {
                    "больше": {"name": "Больше", "coeff": кэф_бол}, 
                    "меньше": {"name": "Меньше", "coeff": кэф_мен}
                },
                "locked": False
            }
            self.active_events.setdefault(interaction.guild.id, {})[eid] = event_data
            await save_event(interaction.guild.id, eid, event_data)

            embed = discord.Embed(title="📊 СТАВКА НА СТАТИСТИКУ", color=discord.Color.blue())
            embed.add_field(name=f"Событие #{eid}", value=f"**{описание}**", inline=False)
            embed.add_field(name="📈 Больше", value=f"Кэф: `{кэф_бол}`", inline=True)
            embed.add_field(name="📉 Меньше", value=f"Кэф: `{кэф_мен}`", inline=True)
            embed.set_footer(text="Пример: /bet")
            
            await interaction.response.send_message(embed=embed)
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /create_total: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="lock", description="Админ: Закрыть ставки")
    @app_commands.checks.has_permissions(administrator=True)
    async def lock(self, interaction: discord.Interaction, id_события: int):
        logger.info(f"🔒 /lock | Админ: {interaction.user} ({interaction.user.id})")
        
        try:
            if id_события in self.active_events.get(interaction.guild.id, {}):
                self.active_events[interaction.guild.id][id_события]["locked"] = True
                await save_event(interaction.guild.id, id_события, self.active_events[interaction.guild.id][id_события])
                await interaction.response.send_message(f"🔒 Ставки на #{id_события} закрыты.")
            else:
                await interaction.response.send_message("❌ Событие не найдено.", ephemeral=True)
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /lock: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="unlock", description="Админ: Открыть ставки")
    @app_commands.checks.has_permissions(administrator=True)
    async def unlock(self, interaction: discord.Interaction, id_события: int):
        logger.info(f"🔓 /unlock | Админ: {interaction.user} ({interaction.user.id})")
        
        try:
            if id_события in self.active_events.get(interaction.guild.id, {}):
                self.active_events[interaction.guild.id][id_события]["locked"] = False
                await save_event(interaction.guild.id, id_события, self.active_events[interaction.guild.id][id_события])
                await interaction.response.send_message(f"🔓 Ставки на #{id_события} открыты.")
            else:
                await interaction.response.send_message("❌ Событие не найдено.", ephemeral=True)
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /unlock: {e}")
            await interaction.response.send_message(
                f"❌ Произошла ошибка: {str(e)[:100]}",
                ephemeral=True
            )

    @app_commands.command(name="settle", description="Админ: Завершить событие")
    @app_commands.checks.has_permissions(administrator=True)
    async def settle(self, interaction: discord.Interaction, id_события: int, победитель: str):
        logger.info(f"🏆 /settle | Админ: {interaction.user} ({interaction.user.id}) | ID события: {id_события}")
        
        try:
            guild_id = interaction.guild.id
            
            if guild_id not in self.active_events or id_события not in self.active_events[guild_id]:
                return await interaction.response.send_message("❌ Событие не найдено.", ephemeral=True)

            await interaction.response.defer()

            event = self.active_events[guild_id][id_события]
            winner_key = победитель.lower().strip()

            if winner_key not in event['options']:
                valid_options = ", ".join(event['options'].keys())
                return await interaction.followup.send(
                    f"❌ Неверный исход. Доступные варианты: `{valid_options}`", 
                    ephemeral=True
                )

            total_payouts = 0
            winner_display_name = event['options'][winner_key]['name']
            payout_coeff = event['options'][winner_key]['coeff']

            bets = await get_event_bets(guild_id, id_события)

            for b_user_id, b_amount, b_choice in bets:
                if b_choice.lower() == winner_key:
                    payout = int(b_amount * payout_coeff)
                    await update_balance(b_user_id, guild_id, payout)
                    total_payouts += 1
                    
                    try:
                        user = await self.bot.fetch_user(b_user_id)
                        await user.send(f"🏆 Ваша ставка на **{event['title']}** сыграла! Выигрыш: **{payout}**")
                    except:
                        pass

            await delete_event(guild_id, id_события)
            del self.active_events[guild_id][id_события]

            logger.info(f"✅ /settle завершен | Событие {id_события} | Выплачено: {total_payouts}")

            embed = discord.Embed(
                title="🏁 СОБЫТИЕ ЗАВЕРШЕНО", 
                description=f"Результаты по событию **#{id_события}**\n**{event['title']}**",
                color=discord.Color.green()
            )
            embed.add_field(name="🏆 Победитель", value=f"**{winner_display_name}**", inline=True)
            embed.add_field(name="📈 Коэффициент", value=f"x{payout_coeff}", inline=True)
            embed.add_field(name="💰 Победителей", value=str(total_payouts), inline=True)
            
            await interaction.followup.send(embed=embed)
        
        except Exception as e:
            logger.error(f"❌ Ошибка в /settle: {e}")
            try:
                await interaction.followup.send(
                    f"❌ Произошла ошибка: {str(e)[:100]}",
                    ephemeral=True
                )
            except:
                pass

async def setup(bot):
    cog = Events(bot)
    await cog.cog_load()
    await bot.add_cog(cog)