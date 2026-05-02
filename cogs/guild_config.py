import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from utils import (
    check_failure_message,
    check_url_accessible,
    is_bot_owner,
    staff_role_check,
    _is_expiring_discord_url,
    _is_valid_url,
)


def admin_only():
    return staff_role_check()


class GuildConfig(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        msg = check_failure_message(error)
        if msg:
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        else:
            raise error

    def _get(self, guild_id: int):
        return self.db.get_guild_settings(guild_id)

    @app_commands.command(name="设置管理身份组", description="设置本服务器可使用管理命令的身份组")
    @app_commands.describe(role="拥有管理权限的 Discord 身份组")
    async def set_staff_role(self, interaction: discord.Interaction, role: discord.Role):
        permissions = getattr(interaction.user, "guild_permissions", None)
        is_server_admin = bool(permissions and permissions.administrator)
        if not (is_bot_owner(interaction) or is_server_admin):
            await interaction.response.send_message(
                "只有机器人拥有者或服务器管理员可以设置管理身份组",
                ephemeral=True,
            )
            return

        gid = interaction.guild_id
        if gid is None:
            await interaction.response.send_message("此命令只能在服务器内使用", ephemeral=True)
            return

        s = self._get(gid)
        self.db.upsert_guild_settings(
            gid,
            bot_nickname       = s.bot_nickname       if s else None,
            webhook_url        = s.webhook_url        if s else None,
            display_name       = s.display_name       if s else None,
            avatar_url         = s.avatar_url         if s else None,
            log_channel_id     = s.log_channel_id     if s else None,
            allowed_channel_id = s.allowed_channel_id if s else None,
            monitor_channel_id = s.monitor_channel_id if s else None,
            staff_role_id      = str(role.id),
            welcome_channel_id = s.welcome_channel_id if s else None,
            leave_channel_id   = s.leave_channel_id   if s else None,
        )
        await interaction.response.send_message(
            f"已将管理身份组设置为 {role.mention}", ephemeral=True
        )

    # ── /设置服务器显示（仅管理身份组） ────────────────────────────
    @app_commands.command(name="设置服务器显示", description="配置 webhook、显示名称和头像（仅管理身份组）")
    @app_commands.describe(
        bot昵称="bot 在本服务器显示的昵称（可选）",
        webhook_url="用于发送公开日志消息的 Webhook URL",
        显示名称="公开日志消息显示的名称",
        头像地址="头像图片的永久公网 URL（推荐 imgur 等图床，必须 http/https）",
        头像附件="直接上传图片（注意：Discord 附件 URL 会在约 24 小时后过期！）",
    )
    @admin_only()
    async def set_guild_display(
        self,
        interaction: discord.Interaction,
        bot昵称: str | None = None,
        webhook_url: str | None = None,
        显示名称: str | None = None,
        头像地址: str | None = None,
        头像附件: discord.Attachment | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        print("DEFER OK [设置服务器显示]")

        gid = interaction.guild_id
        s = self._get(gid)
        notes = []

        print(f"━━━ [设置服务器显示] guild={gid} user={interaction.user}({interaction.user.id}) ━━━")
        print(f"  bot昵称={bot昵称!r}  webhook_url={'已提供' if webhook_url else '未提供'}")
        print(f"  显示名称={显示名称!r}")
        print(f"  头像地址={头像地址!r}")
        print(f"  头像附件={'已上传: ' + 头像附件.url if 头像附件 else '未上传'}")

        # ── 确定最终头像 URL（附件 > 地址 > 保留原值）──────────
        if 头像附件:
            avatar = 头像附件.url
            print(f"  [头像] 来源=附件 url={avatar}")
            if _is_expiring_discord_url(avatar):
                notes.append(
                    "⚠️ **Discord 附件 URL 约 24 小时后失效**\n"
                    "　建议将图片上传到永久图床（如 imgur.com），\n"
                    "　然后用 `/设置服务器显示 头像地址:https://...` 重新设置。"
                )
        elif 头像地址:
            if not _is_valid_url(头像地址):
                await interaction.followup.send(
                    "❌ 头像地址必须是公网 URL（以 http:// 或 https:// 开头）\n"
                    "不能使用本地路径，例如 D:\\xxx\\avatar.png",
                    ephemeral=True,
                )
                return
            avatar = 头像地址
            print(f"  [头像] 来源=URL输入 url={avatar}")
        else:
            avatar = s.avatar_url if s else None
            print(f"  [头像] 来源=保留原值 url={avatar!r}")

        # ── 写入数据库 ─────────────────────────────────────────
        try:
            self.db.upsert_guild_settings(
                gid,
                bot_nickname       = bot昵称     if bot昵称     is not None else (s.bot_nickname   if s else None),
                webhook_url        = webhook_url if webhook_url is not None else (s.webhook_url    if s else None),
                display_name       = 显示名称    if 显示名称    is not None else (s.display_name   if s else None),
                avatar_url         = avatar,
                log_channel_id     = s.log_channel_id     if s else None,
                allowed_channel_id = s.allowed_channel_id if s else None,
                monitor_channel_id = s.monitor_channel_id if s else None,
                welcome_channel_id = s.welcome_channel_id if s else None,
                leave_channel_id   = s.leave_channel_id   if s else None,
            )
        except Exception as e:
            print(f"  [DB] ❌ 写入失败：{e}")
            await interaction.followup.send(f"❌ 数据库写入失败：{e}", ephemeral=True)
            return

        # ── 回读验证 ───────────────────────────────────────────
        saved = self._get(gid)
        print(f"  [DB] ✅ 写入成功，回读验证：")
        print(f"    display_name = {saved.display_name!r}")
        print(f"    avatar_url   = {saved.avatar_url!r}")
        print(f"    webhook_url  = {'已配置' if saved.webhook_url else '未配置'}")

        # ── 检测头像 URL 可访问性 ──────────────────────────────
        if saved.avatar_url and _is_valid_url(saved.avatar_url):
            ok, status = await check_url_accessible(saved.avatar_url)
            print(f"  [URL检测] HTTP {status} → {'✅ 可访问' if ok else '❌ 不可访问'}")
            if not ok:
                notes.append(
                    f"❌ **头像 URL 当前不可访问**（HTTP {status}）\n"
                    "　URL 已保存，但 webhook 发送时头像将无法显示。\n"
                    "　请检查链接是否有效，或改用永久图床。"
                )
        elif avatar and not _is_valid_url(avatar):
            notes.append("❌ 头像地址格式无效，已忽略")

        # ── 更新 bot 昵称 ──────────────────────────────────────
        if bot昵称 and interaction.guild:
            try:
                await interaction.guild.me.edit(nick=bot昵称)
            except discord.Forbidden:
                notes.append("⚠️ Bot 昵称更新失败（权限不足）")

        note_str = "\n\n" + "\n".join(notes) if notes else ""
        await interaction.followup.send(
            f"✅ 服务器显示配置已更新{note_str}", ephemeral=True
        )

    # ── /查看服务器显示（仅管理身份组） ────────────────────────────
    @app_commands.command(name="查看服务器显示", description="查看本服务器当前的显示配置（仅管理身份组）")
    @admin_only()
    async def view_guild_display(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        s = self._get(interaction.guild_id)
        if not s:
            await interaction.followup.send("📭 本服务器尚未配置", ephemeral=True)
            return

        def ch(cid):
            return f"<#{cid}>" if cid else "（未设置）"

        avatar_status = ""
        if s.avatar_url and _is_valid_url(s.avatar_url):
            ok, status = await check_url_accessible(s.avatar_url)
            if ok:
                avatar_status = " ✅（Discord CDN，约24h过期）" if _is_expiring_discord_url(s.avatar_url) else " ✅"
            else:
                avatar_status = f" ❌ 不可访问（HTTP {status}）"
        elif s.avatar_url:
            avatar_status = " ❌ 格式无效"

        lines = [
            "⚙️ **本服务器显示配置**\n",
            f"Bot 昵称：{s.bot_nickname or '（未设置）'}",
            f"显示名称：{s.display_name or '（未设置）'}",
            f"头像地址：{s.avatar_url or '（未设置）'}{avatar_status}",
            f"Webhook URL：{'已配置 ✅' if s.webhook_url else '（未设置）'}",
            f"业务日志频道：{ch(s.log_channel_id)}",
            f"监听通知频道：{ch(s.monitor_channel_id)}",
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ── /设置日志频道（仅管理身份组） ──────────────────────────────
    @app_commands.command(name="设置日志频道", description="将当前频道设为业务日志频道（仅管理身份组）")
    @admin_only()
    async def set_log_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        gid = interaction.guild_id
        cid = interaction.channel_id
        print(f"[设置日志频道] guild_id={gid} channel_id={cid} user={interaction.user}({interaction.user.id})")

        channel = interaction.channel
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(cid)
            except Exception as e:
                print(f"[设置日志频道] 无法获取频道：{e}")
                await interaction.followup.send("❌ Bot 无法获取当前频道，请检查频道权限", ephemeral=True)
                return

        me = interaction.guild.me
        perms = channel.permissions_for(me)
        print(f"[设置日志频道] bot 权限 view_channel={perms.view_channel} send_messages={perms.send_messages}")
        if not perms.view_channel or not perms.send_messages:
            missing = []
            if not perms.view_channel:
                missing.append("查看频道（View Channel）")
            if not perms.send_messages:
                missing.append("发送消息（Send Messages）")
            await interaction.followup.send(
                f"❌ Bot 在当前频道缺少权限：{'、'.join(missing)}\n请在频道权限中授予 Bot 相应权限后重试",
                ephemeral=True,
            )
            return

        try:
            s = self._get(gid)
            self.db.upsert_guild_settings(
                gid,
                bot_nickname       = s.bot_nickname       if s else None,
                webhook_url        = s.webhook_url        if s else None,
                display_name       = s.display_name       if s else None,
                avatar_url         = s.avatar_url         if s else None,
                log_channel_id     = cid,
                allowed_channel_id = s.allowed_channel_id if s else None,
                monitor_channel_id = s.monitor_channel_id if s else None,
                welcome_channel_id = s.welcome_channel_id if s else None,
                leave_channel_id   = s.leave_channel_id   if s else None,
            )
            print(f"[设置日志频道] ✅ 数据库写入成功 guild_id={gid} log_channel_id={cid}")
        except Exception as e:
            print(f"[设置日志频道] ❌ 数据库写入失败：{e}")
            await interaction.followup.send(f"❌ 设置失败：{e}", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ 业务日志频道已设置为 {interaction.channel.mention}", ephemeral=True
        )

    # ── /查看日志频道（仅管理身份组） ──────────────────────────────
    @app_commands.command(name="查看日志频道", description="查看当前业务日志频道（仅管理身份组）")
    @admin_only()
    async def view_log_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = self._get(interaction.guild_id)
        ch = f"<#{s.log_channel_id}>" if s and s.log_channel_id else "（未设置）"
        await interaction.followup.send(f"📋 业务日志频道：{ch}", ephemeral=True)

    # ── /设置监听频道（仅管理身份组） ──────────────────────────────
    @app_commands.command(name="设置监听频道", description="将当前频道设为监听通知频道（仅管理身份组）")
    @admin_only()
    async def set_monitor_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = self._get(interaction.guild_id)
        self.db.upsert_guild_settings(
            interaction.guild_id,
            bot_nickname       = s.bot_nickname       if s else None,
            webhook_url        = s.webhook_url        if s else None,
            display_name       = s.display_name       if s else None,
            avatar_url         = s.avatar_url         if s else None,
            log_channel_id     = s.log_channel_id     if s else None,
            allowed_channel_id = s.allowed_channel_id if s else None,
            monitor_channel_id = interaction.channel_id,
            welcome_channel_id = s.welcome_channel_id if s else None,
            leave_channel_id   = s.leave_channel_id   if s else None,
        )
        await interaction.followup.send(
            f"✅ 已将当前频道设置为监听通知频道：{interaction.channel.mention}", ephemeral=True
        )

    # ── /查看监听频道（仅管理身份组） ──────────────────────────────
    @app_commands.command(name="查看监听频道", description="查看当前监听通知频道（仅管理身份组）")
    @admin_only()
    async def view_monitor_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = self._get(interaction.guild_id)
        ch = f"<#{s.monitor_channel_id}>" if s and s.monitor_channel_id else "（未设置）"
        await interaction.followup.send(f"👁️ 监听通知频道：{ch}", ephemeral=True)

    # ── /设置欢迎频道（仅管理身份组） ──────────────────────────────
    @app_commands.command(name="设置欢迎频道", description="将当前频道设为新成员欢迎消息频道（仅管理身份组）")
    @admin_only()
    async def set_welcome_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = self._get(interaction.guild_id)
        self.db.upsert_guild_settings(
            interaction.guild_id,
            bot_nickname       = s.bot_nickname       if s else None,
            webhook_url        = s.webhook_url        if s else None,
            display_name       = s.display_name       if s else None,
            avatar_url         = s.avatar_url         if s else None,
            log_channel_id     = s.log_channel_id     if s else None,
            allowed_channel_id = s.allowed_channel_id if s else None,
            monitor_channel_id = s.monitor_channel_id if s else None,
            welcome_channel_id = interaction.channel_id,
            leave_channel_id   = s.leave_channel_id   if s else None,
        )
        await interaction.followup.send(
            f"✅ 已将当前频道设置为欢迎频道：{interaction.channel.mention}", ephemeral=True
        )

    # ── /设置离开频道（仅管理身份组） ──────────────────────────────
    @app_commands.command(name="设置离开频道", description="将当前频道设为成员离开通知频道（仅管理身份组）")
    @admin_only()
    async def set_leave_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = self._get(interaction.guild_id)
        self.db.upsert_guild_settings(
            interaction.guild_id,
            bot_nickname       = s.bot_nickname       if s else None,
            webhook_url        = s.webhook_url        if s else None,
            display_name       = s.display_name       if s else None,
            avatar_url         = s.avatar_url         if s else None,
            log_channel_id     = s.log_channel_id     if s else None,
            allowed_channel_id = s.allowed_channel_id if s else None,
            monitor_channel_id = s.monitor_channel_id if s else None,
            welcome_channel_id = s.welcome_channel_id if s else None,
            leave_channel_id   = interaction.channel_id,
        )
        await interaction.followup.send(
            f"✅ 已将当前频道设置为离开通知频道：{interaction.channel.mention}", ephemeral=True
        )

    # ── /查看离开频道（仅管理身份组） ──────────────────────────────
    @app_commands.command(name="查看离开频道", description="查看当前成员离开通知频道（仅管理身份组）")
    @admin_only()
    async def view_leave_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = self._get(interaction.guild_id)
        if s and s.leave_channel_id:
            await interaction.followup.send(
                f"🚪 离开通知频道：<#{s.leave_channel_id}>", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "当前服务器尚未设置离开通知频道", ephemeral=True
            )

    # ── /查看欢迎频道（仅管理身份组） ──────────────────────────────
    @app_commands.command(name="查看欢迎频道", description="查看当前新成员欢迎消息频道（仅管理身份组）")
    @admin_only()
    async def view_welcome_channel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = self._get(interaction.guild_id)
        if s and s.welcome_channel_id:
            await interaction.followup.send(
                f"🎉 欢迎频道：<#{s.welcome_channel_id}>", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "当前服务器尚未设置欢迎频道", ephemeral=True
            )
