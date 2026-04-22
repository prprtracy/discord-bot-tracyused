import traceback

import discord
from discord import app_commands
from discord.ext import commands

from database import Database
from utils import fire_log


def _fmt(hours: float) -> str:
    return f"{hours:g} 小时"


def _operator(interaction: discord.Interaction) -> tuple[str, str]:
    return str(interaction.user.id), interaction.user.display_name


def admin_only():
    return app_commands.checks.has_permissions(administrator=True)


class Ledger(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        print(f"[ERROR] {type(error).__name__}: {error}")
        traceback.print_exc()
        msg = "你没有权限使用此命令" if isinstance(error, app_commands.MissingPermissions) \
              else f"❌ 命令出错：{error}"
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            print(f"[ERROR] cog_app_command_error 发送回复失败：{e}")

    def _log(self, interaction: discord.Interaction, content: str):
        """非阻塞：把日志任务丢到后台，命令主流程不等待。"""
        fire_log(self.bot, interaction.guild_id, self.db, content)

    # ── /添加陪玩 ──────────────────────────────────────────────
    @app_commands.command(name="添加陪玩", description="添加或增加陪玩时长（仅管理员）")
    @app_commands.describe(昵称="陪陪的昵称", 礼物="礼物名称", 类型="娱乐 或 技术", 时长="添加的小时数")
    @app_commands.choices(类型=[
        app_commands.Choice(name="娱乐", value="娱乐"),
        app_commands.Choice(name="技术", value="技术"),
    ])
    @admin_only()
    async def add_companion(
        self,
        interaction: discord.Interaction,
        昵称: str,
        礼物: str,
        类型: app_commands.Choice[str],
        时长: float,
    ):
        await interaction.response.defer(ephemeral=True)
        print(f"[添加陪玩] DEFER OK guild={interaction.guild_id} channel={interaction.channel_id}")

        try:
            if 时长 <= 0:
                await interaction.followup.send("❌ 时长必须大于 0", ephemeral=True)
                return

            gid = interaction.guild_id

            print(f"[添加陪玩] step1: 查询是否已有记录 nickname={昵称!r}")
            existing = self.db.get(gid, 昵称)
            is_new = existing is None
            print(f"[添加陪玩] step2: is_new={is_new}")

            print(f"[添加陪玩] step3: upsert_add 开始（{'INSERT' if is_new else 'UPDATE'}）")
            c = self.db.upsert_add(gid, 昵称, 礼物, 类型.value, 时长)
            print(f"[添加陪玩] step4: upsert_add 完成 remaining={c.remaining_hours}")

            op_id, op_name = _operator(interaction)
            action = "添加陪玩（新建）" if is_new else "添加陪玩（追加）"
            print(f"[添加陪玩] step5: log_action 开始")
            self.db.log_action(gid, 昵称, action,
                               f"增加 {_fmt(时长)}，累计添加：{_fmt(c.total_added_hours)}",
                               op_id, op_name)
            print(f"[添加陪玩] step6: log_action 完成")

            # ① 先给用户私有回复（必须最优先）
            print(f"[添加陪玩] step7: followup.send 开始")
            await interaction.followup.send(
                f"✅ **{c.nickname}** 添加 {_fmt(时长)}\n"
                f"　剩余陪玩时长：{_fmt(c.remaining_hours)}",
                ephemeral=True,
            )
            print(f"[添加陪玩] step8: FOLLOWUP SENT ✅")

            # ② 后台发送公开日志（不 await，绝不阻塞）
            label = "新增陪陪" if is_new else "追加时长"
            self._log(
                interaction,
                f"**{interaction.user.display_name}** {label} **{c.nickname}** {_fmt(时长)}\n"
                f"剩余陪玩：{_fmt(c.remaining_hours)}"
            )

        except Exception as e:
            print(f"[添加陪玩] ❌ 异常 {type(e).__name__}: {e}")
            traceback.print_exc()
            try:
                await interaction.followup.send(f"❌ 操作失败：{e}", ephemeral=True)
            except Exception as fe:
                print(f"[添加陪玩] ❌ followup 也失败了：{fe}")

    # ── /报单 ──────────────────────────────────────────────────
    @app_commands.command(name="报单", description="记录陪玩已完成时长")
    @app_commands.describe(昵称="陪陪的昵称", 时长="报单的小时数")
    async def report(self, interaction: discord.Interaction, 昵称: str, 时长: float):
        await interaction.response.defer(ephemeral=True)
        print(f"DEFER OK [报单] guild={interaction.guild_id} channel={interaction.channel_id}")

        gid = interaction.guild_id
        c = self.db.get(gid, 昵称)
        if c is None:
            await interaction.followup.send(f"❌ 找不到陪陪：{昵称}", ephemeral=True)
            return
        if 时长 <= 0:
            await interaction.followup.send("❌ 时长必须大于 0", ephemeral=True)
            return
        if c.remaining_hours <= 0:
            await interaction.followup.send(
                f"❌ **{昵称}** 剩余陪玩时长为 0，无法报单", ephemeral=True)
            return

        actual = min(时长, c.remaining_hours)
        capped = actual < 时长
        c = self.db.add_reported(gid, 昵称, actual)

        op_id, op_name = _operator(interaction)
        details = (
            f"用户输入 {_fmt(时长)}，实际报单 {_fmt(actual)}（已截断）"
            f"，剩余：{_fmt(c.remaining_hours)}，待结算：{_fmt(c.pending_settlement)}"
        ) if capped else (
            f"报单 {_fmt(actual)}，剩余：{_fmt(c.remaining_hours)}，待结算：{_fmt(c.pending_settlement)}"
        )
        self.db.log_action(gid, 昵称, "报单", details, op_id, op_name)

        cap_hint = f"⚠️ 超出剩余时长，已自动按 **{_fmt(actual)}** 处理\n" if capped else ""
        await interaction.followup.send(
            f"{cap_hint}✅ 报单成功\n"
            f"剩余陪玩：{_fmt(c.remaining_hours)}\n"
            f"待结算：{_fmt(c.pending_settlement)}",
            ephemeral=True,
        )
        print(f"FOLLOWUP SENT [报单]")

        self._log(
            interaction,
            f"{'⚠️ ' if capped else ''}**{interaction.user.display_name}** 为 **{c.nickname}** 报单 {_fmt(actual)}\n"
            f"剩余陪玩：{_fmt(c.remaining_hours)} ｜ 待结算：{_fmt(c.pending_settlement)}"
        )

    # ── /结算（仅管理员） ──────────────────────────────────────
    @app_commands.command(name="结算", description="结算陪玩时长（仅管理员）")
    @app_commands.describe(昵称="陪陪的昵称", 时长="结算的小时数")
    @admin_only()
    async def settle(self, interaction: discord.Interaction, 昵称: str, 时长: float):
        await interaction.response.defer(ephemeral=True)
        print(f"DEFER OK [结算] guild={interaction.guild_id}")

        gid = interaction.guild_id
        c = self.db.get(gid, 昵称)
        if c is None:
            await interaction.followup.send(f"❌ 找不到陪陪：{昵称}", ephemeral=True)
            return
        if 时长 <= 0:
            await interaction.followup.send("❌ 时长必须大于 0", ephemeral=True)
            return
        if 时长 > c.pending_settlement:
            await interaction.followup.send(
                f"❌ 结算时长 {_fmt(时长)} 超过待结算时长 {_fmt(c.pending_settlement)}",
                ephemeral=True)
            return

        c = self.db.add_settled(gid, 昵称, 时长)
        op_id, op_name = _operator(interaction)
        self.db.log_action(gid, 昵称, "结算", f"结算 {_fmt(时长)}", op_id, op_name)

        await interaction.followup.send(
            f"✅ 结算完成\n"
            f"结算时长：{_fmt(时长)}\n"
            f"剩余陪玩：{_fmt(c.remaining_hours)}\n"
            f"待结算：{_fmt(c.pending_settlement)}",
            ephemeral=True,
        )
        print(f"FOLLOWUP SENT [结算]")

        self._log(interaction, f"💰 **{昵称}** 结算 {_fmt(时长)} 啦")

    # ── /查询（仅管理员） ──────────────────────────────────────
    @app_commands.command(name="查询", description="查询所有陪陪的剩余陪玩时长（仅管理员）")
    @admin_only()
    async def query(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        companions = self.db.get_all(interaction.guild_id)
        if not companions:
            await interaction.followup.send("📭 暂无陪陪记录", ephemeral=True)
            return

        lines = ["📋 **陪玩余额**\n"]
        for c in companions:
            lines.append(
                f"**{c.nickname}** ｜ {c.category} ｜ 礼物：{c.gift_name}\n"
                f"　剩余陪玩：{_fmt(c.remaining_hours)}\n"
            )
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ── /查询结算（仅管理员） ──────────────────────────────────
    @app_commands.command(name="查询结算", description="查询所有陪陪的待结算时长（仅管理员）")
    @admin_only()
    async def query_settlement(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        companions = self.db.get_all(interaction.guild_id)
        if not companions:
            await interaction.followup.send("📭 暂无陪陪记录", ephemeral=True)
            return

        lines = ["💰 **待结算余额**\n"]
        for c in companions:
            lines.append(
                f"**{c.nickname}** ｜ {c.category} ｜ 礼物：{c.gift_name}\n"
                f"　待结算：{_fmt(c.pending_settlement)}\n"
            )
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ── /历史记录（仅管理员） ─────────────────────────────────
    @app_commands.command(name="历史记录", description="查询某个陪陪的完整操作流水（仅管理员）")
    @app_commands.describe(昵称="陪陪的昵称")
    @admin_only()
    async def history(self, interaction: discord.Interaction, 昵称: str):
        await interaction.response.defer(ephemeral=True)

        entries = self.db.get_history(interaction.guild_id, 昵称)
        if not entries:
            await interaction.followup.send(f"📭 未找到 **{昵称}** 的历史记录", ephemeral=True)
            return

        lines = [f"📋 **{昵称}** 的操作历史\n"]
        for e in entries:
            lines.append(
                f"`{e.created_at}` ｜ **{e.action_type}** ｜ {e.details} ｜ by {e.operator_name}"
            )
        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "\n…（记录过多，仅显示部分）"

        await interaction.followup.send(text, ephemeral=True)

    # ── /修改记录（仅管理员） ──────────────────────────────────
    @app_commands.command(name="修改记录", description="手动修改某条陪陪记录的字段（仅管理员）")
    @app_commands.describe(
        昵称="要修改的陪陪昵称",
        礼物="新礼物名称（不改留空）",
        类型="新类型（不改留空）",
        累计添加时长="直接覆盖 total_added_hours（不改留空）",
        累计报单时长="直接覆盖 reported_hours（不改留空）",
        累计结算时长="直接覆盖 settled_hours（不改留空）",
    )
    @app_commands.choices(类型=[
        app_commands.Choice(name="娱乐", value="娱乐"),
        app_commands.Choice(name="技术", value="技术"),
    ])
    @admin_only()
    async def edit_record(
        self,
        interaction: discord.Interaction,
        昵称: str,
        礼物: str | None = None,
        类型: app_commands.Choice[str] | None = None,
        累计添加时长: float | None = None,
        累计报单时长: float | None = None,
        累计结算时长: float | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        print(f"DEFER OK [修改记录] guild={interaction.guild_id}")

        gid = interaction.guild_id
        if self.db.get(gid, 昵称) is None:
            await interaction.followup.send(f"❌ 找不到陪陪：{昵称}", ephemeral=True)
            return

        updated = self.db.update(
            gid, 昵称,
            gift_name=礼物,
            category=类型.value if 类型 else None,
            total_added_hours=累计添加时长,
            reported_hours=累计报单时长,
            settled_hours=累计结算时长,
        )
        if not updated:
            await interaction.followup.send("❌ 没有任何字段被修改", ephemeral=True)
            return

        changes = []
        if 礼物:                     changes.append(f"礼物→{礼物}")
        if 类型:                     changes.append(f"类型→{类型.value}")
        if 累计添加时长 is not None: changes.append(f"累计添加→{_fmt(累计添加时长)}")
        if 累计报单时长 is not None: changes.append(f"累计报单→{_fmt(累计报单时长)}")
        if 累计结算时长 is not None: changes.append(f"累计结算→{_fmt(累计结算时长)}")

        op_id, op_name = _operator(interaction)
        self.db.log_action(gid, 昵称, "修改记录", "、".join(changes), op_id, op_name)

        c = self.db.get(gid, 昵称)
        await interaction.followup.send(f"✅ **{昵称}** 记录已更新", ephemeral=True)
        print(f"FOLLOWUP SENT [修改记录]")

        self._log(
            interaction,
            f"✏️ **{昵称}** 记录已修改：{'、'.join(changes)}\n"
            f"　剩余陪玩：{_fmt(c.remaining_hours)}　｜　待结算：{_fmt(c.pending_settlement)}"
        )

    # ── /我的报单（所有人可用） ────────────────────────────────
    @app_commands.command(name="查询我的剩余时长", description="查询你自己的陪玩余额")
    async def my_records(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        gid = interaction.guild_id
        uid = str(interaction.user.id)

        # 先从 bindings 表查出当前用户绑定的所有昵称
        nicknames = self.db.get_nicknames_by_user(gid, uid)
        if not nicknames:
            await interaction.followup.send(
                "你还没有绑定陪玩昵称，请联系管理员使用 /绑定账号", ephemeral=True
            )
            return

        # 再去 companions 表查这些昵称的记录
        companions = [
            c for nick in nicknames
            if (c := self.db.get(gid, nick)) is not None
        ]
        if not companions:
            await interaction.followup.send(
                "你已绑定昵称，但当前还没有陪玩记录", ephemeral=True
            )
            return

        lines = ["📋 **你的陪玩余额**\n"]
        for c in companions:
            lines.append(
                f"**{c.nickname}** ｜ {c.category} ｜ 礼物：{c.gift_name}\n"
                f"　剩余陪玩：{_fmt(c.remaining_hours)}　｜　待结算：{_fmt(c.pending_settlement)}\n"
            )
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ── /绑定账号（仅管理员） ──────────────────────────────────
    @app_commands.command(name="绑定账号", description="将陪陪昵称绑定到指定 Discord 用户（仅管理员）")
    @app_commands.describe(昵称="陪陪的昵称（不需要已存在于记录表中）", 用户="要绑定的 Discord 用户")
    @admin_only()
    async def bind_account(self, interaction: discord.Interaction, 昵称: str, 用户: discord.Member):
        await interaction.response.defer(ephemeral=True)

        gid = interaction.guild_id
        # 写入独立 bindings 表，无需 companions 记录存在
        self.db.upsert_binding(gid, 昵称, str(用户.id), 用户.display_name)

        op_id, op_name = _operator(interaction)
        # companions 如果已有该昵称，也记录一条操作日志
        if self.db.get(gid, 昵称):
            self.db.log_action(
                gid, 昵称, "绑定账号",
                f"绑定到 {用户.display_name}（{用户.id}）",
                op_id, op_name,
            )

        await interaction.followup.send(
            f"✅ 已绑定：昵称 **{昵称}** → 用户 {用户.mention}\n"
            f"（即使陪陪记录尚未创建，绑定关系已提前保存）",
            ephemeral=True,
        )

    # ── /删除记录（仅管理员） ──────────────────────────────────
    @app_commands.command(name="删除记录", description="删除一条陪陪记录（仅管理员）")
    @app_commands.describe(昵称="要删除的陪陪昵称")
    @admin_only()
    async def delete_record(self, interaction: discord.Interaction, 昵称: str):
        await interaction.response.defer(ephemeral=True)
        print(f"DEFER OK [删除记录] guild={interaction.guild_id}")

        gid = interaction.guild_id
        c = self.db.get(gid, 昵称)
        if c is None:
            await interaction.followup.send(f"❌ 找不到陪陪：{昵称}", ephemeral=True)
            return

        op_id, op_name = _operator(interaction)
        self.db.log_action(
            gid, 昵称, "删除记录",
            f"删除快照：添加 {_fmt(c.total_added_hours)}，"
            f"报单 {_fmt(c.reported_hours)}，结算 {_fmt(c.settled_hours)}",
            op_id, op_name,
        )
        self.db.delete(gid, 昵称)

        await interaction.followup.send(f"✅ 已删除 **{昵称}** 的记录", ephemeral=True)
        print(f"FOLLOWUP SENT [删除记录]")

        self._log(interaction, f"🗑️ **{昵称}** 的记录已被删除")
