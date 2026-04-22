import asyncio

import discord
from discord.ext import commands

from database import Database
from welcome_card import generate_welcome_card


class Events(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    # ── 工具：获取频道对象（带超时）────────────────────────────
    async def _get_channel(self, channel_id: int):
        ch = self.bot.get_channel(channel_id)
        if ch is None:
            ch = await asyncio.wait_for(
                self.bot.fetch_channel(channel_id), timeout=10
            )
        return ch

    # ── 监听频道：发文字通知 ────────────────────────────────────
    async def _notify(self, guild_id: int, content: str):
        settings = self.db.get_guild_settings(guild_id)
        if not settings or not settings.monitor_channel_id:
            print(f"[监听] {content}（未配置监听频道，跳过）")
            return
        try:
            ch = await self._get_channel(int(settings.monitor_channel_id))
            await ch.send(content)
        except Exception as e:
            print(f"[监听] 发送失败：{e}")

    # ── 欢迎频道：发新样式欢迎图 ────────────────────────────────
    async def _send_welcome(self, member: discord.Member):
        settings = self.db.get_guild_settings(member.guild.id)
        if not settings or not settings.welcome_channel_id:
            print(f"[欢迎图] guild={member.guild.id} 未配置欢迎频道，跳过")
            return

        channel_id = int(settings.welcome_channel_id)
        try:
            ch = await self._get_channel(channel_id)

            # DCID：新用户名系统无 discriminator，直接用 member.name
            if member.discriminator and member.discriminator != "0":
                dcid = f"{member.name}#{member.discriminator}"
            else:
                dcid = member.name

            buf = await generate_welcome_card(
                dcid=dcid,
                member_count=member.guild.member_count or 0,
                avatar_url=str(member.display_avatar.url),
            )
            print(f"[欢迎图] 生成完成，发送到欢迎频道 {channel_id}")

            # 尝试从本服务器获取自定义表情
            EMOJI_ID = 1351647536015736853
            emoji_obj = discord.utils.get(member.guild.emojis, id=EMOJI_ID)
            emoji_str = str(emoji_obj) if emoji_obj else ""

            content = (
                f"Hey {member.mention} ， welcome to **温度计** ！\n"
                f"**玩的开心 拒绝红温哦**"
            )
            if emoji_str:
                content += f"\n{emoji_str}"

            await ch.send(
                content=content,
                file=discord.File(buf, filename="welcome.png"),
            )
            print(f"[欢迎图] ✅ guild={member.guild.id} member={dcid}")

        except asyncio.TimeoutError:
            print(f"[欢迎图] ❌ fetch_channel 超时 channel={channel_id}")
        except discord.Forbidden:
            print(f"[欢迎图] ❌ 无权限发送 channel={channel_id}")
        except Exception as e:
            import traceback
            print(f"[欢迎图] ❌ {type(e).__name__}: {e}")
            traceback.print_exc()

    # ── 用户加入服务器 ─────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        print(f"[成员] {member.display_name} 加入了 {member.guild.name}")
        # 监听频道：只发文字通知
        await self._notify(member.guild.id, f"👋 **{member.display_name}** 加入了服务器")
        # 欢迎频道：发新样式欢迎图
        await self._send_welcome(member)

    # ── 用户离开服务器 ─────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # dcid：新账号无 discriminator，直接用 member.name；旧账号显示 name#discriminator
        if member.discriminator and member.discriminator != "0":
            dcid = f"{member.name}#{member.discriminator}"
        else:
            dcid = member.name

        display = member.display_name
        print(f"[成员离开] {display}（{dcid}）离开了 {member.guild.name}")

        settings = self.db.get_guild_settings(member.guild.id)
        if not settings or not settings.leave_channel_id:
            print(f"[成员离开] guild={member.guild.id} 未配置离开通知频道，跳过")
            return

        try:
            ch = await self._get_channel(int(settings.leave_channel_id))
            await ch.send(f"{display}（{dcid}）悄悄跑路啦")
        except asyncio.TimeoutError:
            print(f"[成员离开] ❌ fetch_channel 超时 channel={settings.leave_channel_id}")
        except discord.Forbidden:
            print(f"[成员离开] ❌ 无权限发送 channel={settings.leave_channel_id}")
        except Exception as e:
            print(f"[成员离开] ❌ {type(e).__name__}: {e}")

    # ── 语音频道变化 ───────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if before.channel is None and after.channel is not None:
            msg = f"🎙️ **{member.display_name}** 进入了语音频道：**{after.channel.name}**"
        elif before.channel is not None and after.channel is None:
            msg = f"🔇 **{member.display_name}** 离开了语音频道：**{before.channel.name}**"
        elif (before.channel is not None and after.channel is not None
              and before.channel != after.channel):
            msg = (f"🔀 **{member.display_name}** 从语音频道 **{before.channel.name}**"
                   f" 切换到了 **{after.channel.name}**")
        else:
            return
        print(f"[语音] {msg}")
        await self._notify(member.guild.id, msg)
