import asyncio
import discord

from database import Database


def _is_valid_url(url: str | None) -> bool:
    if not url:
        return False
    return url.startswith("http://") or url.startswith("https://")


def _is_expiring_discord_url(url: str | None) -> bool:
    if not url:
        return False
    return "cdn.discordapp.com/attachments" in url and "ex=" in url


async def check_url_accessible(url: str, timeout: int = 8):
    """供 /查看服务器显示 调用，不参与发送主流程。"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as resp:
                return resp.status < 400 or resp.status == 429, resp.status
    except Exception as e:
        print(f"[URL检测] {url[:80]} → {e}")
        return False, None


async def send_to_log_channel(
    bot: discord.Client,
    guild_id: int,
    db: Database,
    content: str,
):
    """
    后台发送公开日志到日志频道。
    此函数只应通过 fire_log() 以 asyncio.create_task 调用，
    绝不能 await 在命令主流程中——避免 fetch_channel 挂起阻塞命令。
    """
    print(f"[日志] 开始发送 guild={guild_id}")

    settings = db.get_guild_settings(guild_id)
    if not settings:
        print(f"[日志] guild={guild_id} 无 guild_settings，跳过")
        return
    if not settings.log_channel_id:
        print(f"[日志] guild={guild_id} 未配置 log_channel_id，跳过")
        return

    channel_id = int(settings.log_channel_id)
    print(f"[日志] guild={guild_id} → channel_id={channel_id}")

    try:
        # 先查缓存，缓存没有再 fetch（fetch 加 10s 超时，避免永久挂起）
        channel = bot.get_channel(channel_id)
        print(f"[日志] get_channel → {channel} (type={type(channel).__name__})")

        if channel is None:
            print(f"[日志] 缓存未命中，尝试 fetch_channel（超时 10s）")
            channel = await asyncio.wait_for(
                bot.fetch_channel(channel_id),
                timeout=10.0,
            )
            print(f"[日志] fetch_channel → {channel} (type={type(channel).__name__})")

        # 检查频道是否可发送消息
        if not isinstance(channel, discord.abc.Messageable):
            print(f"[日志] ⚠️ channel={channel_id} 不是可发送频道，跳过")
            return

        # 检查 bot 发送权限（文字频道才能检查）
        if isinstance(channel, discord.TextChannel):
            perms = channel.permissions_for(channel.guild.me)
            if not perms.send_messages:
                print(f"[日志] ⚠️ bot 在 channel={channel_id} 无发送权限，跳过")
                return

        await channel.send(content)
        print(f"[日志] ✅ 发送成功 guild={guild_id} channel={channel_id}")

    except asyncio.TimeoutError:
        print(f"[日志] ❌ fetch_channel 超时（>10s）guild={guild_id} channel={channel_id}")
    except discord.Forbidden:
        print(f"[日志] ❌ 403 Forbidden guild={guild_id} channel={channel_id}（bot 缺少权限）")
    except discord.NotFound:
        print(f"[日志] ❌ 404 NotFound guild={guild_id} channel={channel_id}（频道不存在）")
    except Exception as e:
        print(f"[日志] ❌ 未知错误 guild={guild_id} channel={channel_id}：{type(e).__name__}: {e}")


def fire_log(bot: discord.Client, guild_id: int, db: Database, content: str):
    """
    非阻塞日志发送。在命令主流程的 followup.send 之后调用。
    create_task 保证命令协程立即返回，日志在后台独立发送。
    """
    async def _task():
        await send_to_log_channel(bot, guild_id, db, content)

    asyncio.ensure_future(_task())
