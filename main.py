import traceback
import discord
from discord.ext import commands

import config
from database import Database
from cogs.ledger import Ledger
from cogs.guild_config import GuildConfig
from cogs.events import Events

intents = discord.Intents.default()
intents.members = True        # 监听成员加入/离开（需在 Developer Portal 开启 Server Members Intent）
intents.voice_states = True   # 监听语音频道变化
bot = commands.Bot(command_prefix="!", intents=intents)
db = Database()


async def apply_guild_nickname(guild: discord.Guild):
    settings = db.get_guild_settings(guild.id)
    if settings and settings.bot_nickname:
        try:
            await guild.me.edit(nick=settings.bot_nickname)
        except discord.Forbidden:
            pass


@bot.event
async def on_ready():
    try:
        await bot.add_cog(Ledger(bot, db))
        await bot.add_cog(GuildConfig(bot, db))
        await bot.add_cog(Events(bot, db))

        # 同步到所有已加入的服务器（立即生效，无需等待全局传播）
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
                print(f"[同步] Slash commands 已同步到服务器 {guild.name}（{guild.id}）")
            except Exception as e:
                print(f"[同步] 服务器 {guild.name}（{guild.id}）同步失败：{e}")
            await apply_guild_nickname(guild)

        print(f"Bot 已上线：{bot.user}，共 {len(bot.guilds)} 个服务器")
    except Exception as e:
        print(f"on_ready 错误：{e}")
        traceback.print_exc()


@bot.event
async def on_guild_join(guild: discord.Guild):
    """加入新服务器时立即同步命令"""
    try:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"[同步] 新服务器 {guild.name}（{guild.id}）命令同步完成")
    except Exception as e:
        print(f"[同步] 新服务器 {guild.name}（{guild.id}）同步失败：{e}")
    await apply_guild_nickname(guild)


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        print("错误：请设置环境变量 DISCORD_TOKEN")
    else:
        bot.run(config.DISCORD_TOKEN)
