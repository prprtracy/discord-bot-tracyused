import asyncio
import logging
from contextlib import closing
from dataclasses import replace
from functools import partial
from io import BytesIO
from pathlib import Path
from random import choice

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from database import Database, Scrim
from scrim_card import CardPlayer, render_matchup, render_victory


PLAYER_COUNT = 10
# Riot's map catalog: https://playvalorant.com/en-us/maps/
# Summit uses the official 13.00 patch artwork shown in the announcement preview.
VALORANT_MAPS = {
    "Abyss": ("深窟幽境", "news_live/53698d442a14b5a6be643d53eb970ac16442cb38-930x522.png"),
    "Ascent": ("義境空島", "news/5cb7e65c04a489eccd725ce693fdc11e99982e10-3840x2160.png"),
    "Bind": ("劫境之地", "news/7df1e6ee284810ef0cbf8db369c214a8cbf6578c-3840x2160.png"),
    "Breeze": ("熱帶樂園", "news_live/430fb50965f1d99cdaef3588df13d98dbea340cf-930x522.png"),
    "Corrode": ("晶蝕之地", "news_live/6e3e66577519c8290d874aa94d82e28aec2ccc3e-915x515.jpg"),
    "Fracture": ("天漠之峽", "news/983a6d66978aabd3ccd4e51517298d9a0b5467d9-3840x2160.png"),
    "Haven": ("遺落境地", "news/bccc7b5f8647a4f654d4bb359247bce6e82c77ab-3840x2160.png"),
    "Icebox": ("極地寒港", "news/72853f583a0f6b25aed54870531756483a7b61de-3840x2160.png"),
    "Lotus": ("蓮華古城", "news/67d199e0f7108bc60e8293d3f9a37538b0b55b11-3840x2160.png"),
    "Pearl": ("深海遺珠", "news/7ba5df090f5efee7988d8d33f4b43c3441cb1aab-3840x2160.png"),
    "Split": ("雙塔迷城", "news/878d51688c0f9dd0de827162e80c40811668e0c6-3840x2160.png"),
    "Summit": ("頂峰亭閣", "news_live/ff7f89ff681da27cfec24bf61986c23fb2aba543-1920x1080.jpg"),
    "Sunset": ("日落之城", "news/5101e4ee241fbfca261bf8150230236c46c8b991-3840x2160.png"),
}
MAP_IMAGE_DIR = Path(__file__).resolve().parents[1] / "assets" / "scrim_maps"
NO_PINGS = discord.AllowedMentions.none()
log = logging.getLogger(__name__)


def map_label(name: str) -> str:
    localized_name, _ = VALORANT_MAPS[name]
    return f"{name}（{localized_name}）"


def team_a_size(scrim: Scrim) -> int:
    return (len(scrim.players) + 1) // 2


def teams_text(scrim: Scrim) -> str:
    team_a = ", ".join(f"<@{user_id}>" for user_id in scrim.team_a)
    team_b = ", ".join(f"<@{user_id}>" for user_id in scrim.players if user_id not in scrim.team_a)
    return f"**A 队**　{team_a}\n**B 队**　{team_b or '暂无成员'}"


def roster_text(scrim: Scrim) -> str:
    return "\n".join(
        f"{index}. <@{user_id}>" + ("（主办人）" if user_id == scrim.host_id else "")
        for index, user_id in enumerate(scrim.players, start=1)
    )


def passives_complete(scrim: Scrim, results: dict[int, str]) -> bool:
    return (
        bool(scrim.players)
        and scrim.players.keys() <= results.keys()
        and len({results[user_id] for user_id in scrim.players}) == len(scrim.players)
    )


class ScrimAnnouncement(discord.ui.View):
    def __init__(self, cog: "Scrims", signup_open: bool = True, *, legacy: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        if not legacy:
            self.remove_item(self.manage)
        if not signup_open:
            self.remove_item(self.join)

    @discord.ui.button(label="确认参加", style=discord.ButtonStyle.success, custom_id="scrim:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_public(interaction, join=True)

    @discord.ui.button(label="主办人面板", custom_id="scrim:manage")
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_public(interaction, join=False)


class PassiveDraw(discord.ui.DynamicItem[discord.ui.Button], template=r"scrim:passive:(?P<round_id>\d+):(?P<recipient_id>\d+)(?::(?P<guild_id>\d+))?"):
    def __init__(self, round_id: int, recipient_id: int = 0, guild_id: int | None = None):
        self.round_id = round_id
        self.recipient_id = recipient_id
        self.guild_id = guild_id
        custom_id = f"scrim:passive:{round_id}:{recipient_id}"
        if guild_id is not None:
            custom_id += f":{guild_id}"
        super().__init__(discord.ui.Button(
            label="抽取被动",
            style=discord.ButtonStyle.primary,
            custom_id=custom_id,
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["round_id"]), int(match["recipient_id"]), int(match["guild_id"]) if match["guild_id"] else None)

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Scrims")
        if cog is not None:
            await cog.handle_draw(interaction, self.round_id, self.recipient_id, self.guild_id)


class EndMatch(discord.ui.DynamicItem[discord.ui.Button], template=r"scrim:end:(?P<round_id>\d+)"):
    def __init__(self, round_id: int):
        self.round_id = round_id
        super().__init__(discord.ui.Button(label="结束对战", style=discord.ButtonStyle.danger,
                                           custom_id=f"scrim:end:{round_id}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["round_id"]))

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Scrims")
        if cog:
            await cog.handle_map_setup(interaction, self.round_id, "end")


def assignment_notice(scrim: Scrim, user_id: int) -> dict:
    view = discord.ui.View(timeout=None)
    view.add_item(PassiveDraw(scrim.message_id, user_id, scrim.guild_id))
    team = "A" if user_id in scrim.team_a else "B"
    return dict(content=f"第 {scrim.number} 次趣味瓦内战的主办人 <@{scrim.host_id}> 已将你分配到 **{team} 队**。点击下方按钮抽取你的被动。",
                view=view, allowed_mentions=NO_PINGS)


class FinalScrimView(discord.ui.View):
    def __init__(self, cog: "Scrims", scrim: Scrim | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        if scrim is None:
            return
        self.remove_item(self.reroll)
        self.remove_item(self.confirm_passives)
        self.remove_item(self.match_found)
        self.remove_item(self.random_map)
        self.remove_item(self.choose_map)

    @discord.ui.button(label="查看我的分队", style=discord.ButtonStyle.primary, custom_id="scrim:my-team")
    async def my_team(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_my_team(interaction)

    @discord.ui.button(label="主办人重抽", custom_id="scrim:reroll")
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.open_reroll_panel(interaction, interaction.message.id)

    @discord.ui.button(label="确认被动", style=discord.ButtonStyle.success, custom_id="scrim:confirm-passives")
    async def confirm_passives(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_map_setup(interaction, interaction.message.id, "confirm")

    @discord.ui.button(label="抽取地图", style=discord.ButtonStyle.primary, custom_id="scrim:random-map")
    async def random_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_map_setup(interaction, interaction.message.id, "random")

    @discord.ui.button(label="手动选择地图", custom_id="scrim:choose-map")
    async def choose_map(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_map_setup(interaction, interaction.message.id, "picker")

    @discord.ui.button(label="开始比赛", style=discord.ButtonStyle.success, custom_id="scrim:match-found")
    async def match_found(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_map_setup(interaction, interaction.message.id, "match")


class MapPicker(discord.ui.View):
    def __init__(self, cog: "Scrims", scrim: Scrim):
        super().__init__(timeout=900)
        picker = discord.ui.Select(
            placeholder="选择 VALORANT 地图",
            options=[
                discord.SelectOption(label=map_label(name), value=name, default=name == scrim.map_name)
                for name in VALORANT_MAPS
            ],
        )

        async def select(interaction: discord.Interaction):
            action = "replace_map" if scrim.map_announcement_id is not None else "select"
            await cog.handle_map_setup(interaction, scrim.message_id, action, picker.values[0])

        picker.callback = select
        self.add_item(picker)


class RerollPanel(discord.ui.View):
    def __init__(self, cog: "Scrims", scrim: Scrim, results: dict[int, str]):
        super().__init__(timeout=900)
        picker = discord.ui.Select(
            placeholder="选择要重抽的玩家",
            options=[
                discord.SelectOption(label=f"{index}. {name}"[:100], value=str(user_id))
                for index, (user_id, name) in enumerate(scrim.players.items(), start=1)
                if user_id in results
            ],
        )

        async def select(interaction: discord.Interaction):
            await cog.reroll_passive(interaction, scrim.message_id, int(picker.values[0]))

        picker.callback = select
        self.add_item(picker)


class PassivePoolModal(discord.ui.Modal, title="设置内战被动库"):
    def __init__(self, db: Database, guild_id: int):
        super().__init__(timeout=600)
        self.db = db
        self.entries = discord.ui.TextInput(
            label="被动条件（每行一条）",
            style=discord.TextStyle.paragraph,
            default="\n".join(db.get_scrim_passives(guild_id)),
            max_length=4000,
        )
        self.add_item(self.entries)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild_id is None or not interaction.permissions.manage_guild:
            await interaction.response.send_message("你需要「管理服务器」权限。", ephemeral=True)
            return
        entries = list(dict.fromkeys(line.strip() for line in self.entries.value.splitlines() if line.strip()))
        if not entries or any(len(entry) > 300 for entry in entries):
            await interaction.response.send_message("请输入至少一条被动，每条最多 300 字。", ephemeral=True)
            return
        self.db.set_scrim_passives(interaction.guild_id, entries)
        await interaction.response.send_message(f"已保存 {len(entries)} 条被动。", ephemeral=True)


class HostPanel(discord.ui.View):
    def __init__(self, cog: "Scrims", scrim: Scrim, mode: str = ""):
        super().__init__(timeout=900)
        self.cog = cog
        self.scrim = scrim
        a_size = team_a_size(scrim)
        if mode == "winner":
            if scrim.team_a:
                self.add_map_button("A 队获胜", "win_a", discord.ButtonStyle.success)
            if set(scrim.players).difference(scrim.team_a):
                self.add_map_button("B 队获胜", "win_b", discord.ButtonStyle.success)
        elif mode == "remove":
            self.add_picker("删除用户", "remove", 1)
        elif mode == "pick":
            self.add_picker(f"选择 A 队的 {a_size} 名成员", "pick", a_size)
        elif scrim.stage in ("signup", "full"):
            self.add_button("确认列表，开始分队", "start", discord.ButtonStyle.success)
            self.add_button("删除用户", "show_remove", discord.ButtonStyle.danger)
        elif scrim.stage == "teams" and scrim.team_a:
            self.add_button("确认分队", "confirm", discord.ButtonStyle.success)
            self.add_button("修改分队", "show_pick", discord.ButtonStyle.secondary)
        elif scrim.stage == "teams":
            self.add_picker(f"选择 A 队的 {a_size} 名成员", "pick", a_size)
        elif scrim.stage == "confirmed" and not scrim.passives_confirmed:
            reroll = discord.ui.Button(label="主办人重抽")
            reroll.callback = partial(cog.open_reroll_panel, round_id=scrim.message_id)
            self.add_item(reroll)
            self.add_map_button("确认被动", "confirm", discord.ButtonStyle.success)
        elif scrim.stage == "confirmed" and scrim.map_announcement_id is None:
            self.add_map_button("抽取地图", "random", discord.ButtonStyle.primary)
            self.add_map_button("修改地图" if scrim.map_name else "手动选择地图", "picker", discord.ButtonStyle.secondary)
            if scrim.map_name:
                self.add_map_button("开始比赛", "match", discord.ButtonStyle.success)
        elif scrim.stage == "confirmed":
            self.add_map_button("修改地图", "picker", discord.ButtonStyle.secondary)

    def add_map_button(self, label: str, action: str, style: discord.ButtonStyle):
        button = discord.ui.Button(label=label, style=style)
        button.callback = partial(self.cog.handle_map_setup, round_id=self.scrim.message_id, action=action)
        self.add_item(button)

    def add_button(self, label: str, action: str, style: discord.ButtonStyle):
        button = discord.ui.Button(label=label, style=style)
        button.callback = partial(self.cog.handle_host, self.scrim, action)
        self.add_item(button)

    def add_picker(self, placeholder: str, action: str, count: int):
        options = [
            discord.SelectOption(
                label=f"{index}. {name}"[:100],
                value=str(user_id),
                description="主办人" if user_id == self.scrim.host_id else None,
                default=action == "pick" and user_id in self.scrim.team_a,
            )
            for index, (user_id, name) in enumerate(self.scrim.players.items(), start=1)
            if action != "remove" or user_id != self.scrim.host_id
        ]
        picker = discord.ui.Select(
            placeholder=placeholder, min_values=count, max_values=count, options=options,
        )

        async def select(interaction: discord.Interaction):
            await self.cog.handle_host(self.scrim, action, interaction, tuple(map(int, picker.values)))

        picker.callback = select
        self.add_item(picker)
        if action == "remove" or self.scrim.team_a:
            self.add_button("返回", "back", discord.ButtonStyle.secondary)


class Scrims(commands.Cog):
    def __init__(self, bot: commands.Bot, db: Database):
        self.bot = bot
        self.db = db
        self.guild_locks: dict[int, asyncio.Lock] = {}
        self.player_interactions: dict[tuple[int, int], discord.Interaction] = {}
        self.host_panels: dict[int, discord.Interaction] = {}

    async def cog_load(self):
        # The message ID identifies the round, so one fallback view handles old announcements.
        self.bot.add_view(ScrimAnnouncement(self, legacy=True))
        self.bot.add_view(FinalScrimView(self))
        self.bot.add_dynamic_items(PassiveDraw, EndMatch)

    async def cog_unload(self):
        self.bot.remove_dynamic_items(PassiveDraw, EndMatch)

    def lock_for(self, guild_id: int) -> asyncio.Lock:
        return self.guild_locks.setdefault(guild_id, asyncio.Lock())

    def announcement(self, scrim: Scrim, passives_ready: bool = False) -> dict:
        status = {
            "signup": f"开始咯，请玩家报名！（{len(scrim.players)}/{PLAYER_COUNT}）",
            "full": "报名已满，等待主办人确认名单",
            "teams": "名单已确认，等待主办人分队",
            "confirmed": "分队已确认",
        }[scrim.stage]
        if scrim.stage == "teams" and scrim.team_a:
            status = "分队预览，等待主办人确认"
        title = f"**第 {scrim.number} 次趣味瓦内战**"
        body = teams_text(scrim) if scrim.team_a else roster_text(scrim)
        if scrim.stage == "confirmed":
            if scrim.passives_confirmed:
                selected_map = map_label(scrim.map_name) if scrim.map_name else "待主办人选择"
                body += f"\n被动已确认 · **比赛地图**　{selected_map}"
                if scrim.map_name:
                    if scrim.ended:
                        body += "\n对战已结束。"
                    else:
                        body += "\n对战已确认。" if scrim.map_announcement_id else "\n地图已确认，等待主办人开始比赛。"
            elif passives_ready:
                body += f"\n{len(scrim.players)} 位玩家已抽完被动，等待主办人确认。"
            else:
                body += "\n请在本频道仅自己可见的分队通知中抽取被动。未看到通知时，可点击「查看我的分队」。"
            view = FinalScrimView(self, scrim)
        else:
            view = ScrimAnnouncement(self, scrim.stage == "signup")
        return {
            "content": f"{title} {status}\n{body}",
            "view": view,
            "allowed_mentions": NO_PINGS,
        }

    def panel(self, scrim: Scrim, mode: str = "", note: str = "") -> dict:
        if mode == "remove":
            body = "选择要移除的成员。空出的名额会重新开放报名。"
        elif mode == "pick" or (scrim.stage == "teams" and not scrim.team_a):
            a_size = team_a_size(scrim)
            b_size = len(scrim.players) - a_size
            body = f"请选择 A 队的 {a_size} 名成员，其余 {b_size} 人自动进入 B 队。"
        elif scrim.stage == "confirmed":
            body = "分队已确认。\n" + teams_text(scrim)
            if scrim.map_name:
                body += f"\n比赛地图：**{map_label(scrim.map_name)}**"
        else:
            body = teams_text(scrim) if scrim.team_a else roster_text(scrim)
        return {
            "content": f"**第 {scrim.number} 次趣味瓦内战 · 主办人面板**\n{note}{body}",
            "view": None if scrim.ended else HostPanel(self, scrim, mode),
            "allowed_mentions": NO_PINGS,
        }

    @app_commands.command(name="设置内战频道", description="设置趣味内战公告发布的文字频道")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(channel="发布报名、名单和分队结果的频道")
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        permissions = channel.permissions_for(interaction.guild.me)
        if not (permissions.view_channel and permissions.send_messages):
            await interaction.response.send_message("请先给机器人该频道的查看和发送消息权限。", ephemeral=True)
            return
        self.db.set_scrim_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(f"趣味内战公告将发布到 {channel.mention}。", ephemeral=True)

    @app_commands.command(name="添加内战被动", description="编辑趣味内战的随机被动库")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_passives(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PassivePoolModal(self.db, interaction.guild_id))

    @app_commands.command(name="查看被动列表", description="查看当前服务器用于趣味内战抽取的被动")
    @app_commands.guild_only()
    async def list_passives(self, interaction: discord.Interaction):
        entries = self.db.get_scrim_passives(interaction.guild_id)
        content = f"**内战被动列表（共 {len(entries)} 条）**"
        pages = []
        for index, entry in enumerate(entries, start=1):
            line = f"{index}. {entry}"
            if len(f"{content}\n{line}".encode("utf-16-le")) > 4000:
                pages.append(content)
                content = line
            else:
                content += f"\n{line}"
        pages.append(content)
        await interaction.response.send_message(pages[0], ephemeral=True, allowed_mentions=NO_PINGS)
        for page in pages[1:]:
            await interaction.followup.send(page, ephemeral=True, allowed_mentions=NO_PINGS)

    @app_commands.command(name="趣味内战", description="发起一场最多 10 人的 VALORANT 趣味内战")
    @app_commands.guild_only()
    async def start_scrim(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        async with self.lock_for(guild_id):
            channel_id = self.db.get_scrim_channel(guild_id)
            channel = interaction.guild.get_channel(channel_id) if channel_id else None
            if not isinstance(channel, discord.TextChannel):
                await interaction.edit_original_response(content="请让服务器管理员先使用 /设置内战频道。")
                return
            host = interaction.user
            origin = host.voice.channel if host.voice else None
            if origin is None:
                await interaction.edit_original_response(content="请先加入赛后集合用的语音频道，再输入 /趣味内战。")
                return
            scrim = Scrim(guild_id, self.db.next_scrim_number(guild_id), channel.id, 0,
                          host.id, {host.id: host.display_name}, origin_voice_id=origin.id)
            try:
                message = await channel.send(**self.announcement(scrim))
            except discord.HTTPException:
                log.exception("Could not post scrim in channel %s", channel.id)
                await interaction.edit_original_response(content="公告发送失败，请检查机器人在内战频道的权限后重试。")
                return
            try:
                scrim = replace(scrim, message_id=message.id)
                self.db.save_scrim(scrim)
            except Exception:
                try:
                    await message.delete()
                except discord.HTTPException:
                    log.exception("Could not remove unsaved scrim announcement %s", message.id)
                raise
            await interaction.edit_original_response(**self.panel(scrim, note=f"报名已发布到 {channel.mention}。{message.jump_url}\n"))
            self.remember_host_panel(scrim, interaction)

    def remember_host_panel(self, scrim: Scrim, interaction: discord.Interaction):
        self.host_panels = {key: value for key, value in self.host_panels.items() if not value.is_expired()}
        self.host_panels[scrim.message_id] = interaction

    @app_commands.command(name="内战管理", description="重新打开自己主办场次的私密管理按钮")
    @app_commands.guild_only()
    @app_commands.describe(number="公告上的内战场次编号")
    async def reopen_panel(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        async with self.lock_for(interaction.guild_id):
            scrim = self.db.get_host_scrim(interaction.guild_id, interaction.user.id, number)
            if not scrim or scrim.ended:
                await interaction.edit_original_response(content="没有可管理的对应场次。")
                return
            await interaction.edit_original_response(**self.panel(scrim))
            self.remember_host_panel(scrim, interaction)

        if scrim.map_announcement_id is not None:
            await self.send_end_button(interaction, scrim)

    async def send_end_button(self, interaction: discord.Interaction, scrim: Scrim):
        view = discord.ui.View(timeout=None)
        view.add_item(EndMatch(scrim.message_id))
        try:
            await interaction.followup.send(f"第 {scrim.number} 次趣味瓦内战 · 赛后结算", view=view, ephemeral=True)
        except discord.HTTPException:
            await interaction.edit_original_response(**self.panel(
                scrim, note=f"赛后请用 /内战管理 输入 {scrim.number} 重新领取结束按钮。\n",
            ))

    async def publish(self, previous: Scrim, updated: Scrim, message: discord.PartialMessage):
        self.db.save_scrim(updated)
        try:
            await message.edit(**self.announcement(updated))
        except discord.HTTPException:
            self.db.save_scrim(previous)
            log.exception("Could not update scrim announcement %s", updated.message_id)
            return False
        return True

    async def handle_public(self, interaction: discord.Interaction, *, join: bool):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock_for(interaction.guild_id):
            scrim = self.db.get_scrim(interaction.guild_id, interaction.message.id)
            user = interaction.user
            remember_signup = False
            if scrim is None:
                result = "这场内战的记录已不可用。"
            elif not join:
                if user.id == scrim.host_id:
                    await interaction.edit_original_response(**self.panel(scrim))
                    return
                result = "只有本场主办人可以打开管理面板。"
            elif user.id in scrim.players:
                result = "你已在参赛名单中。"
                remember_signup = scrim.stage != "confirmed"
            elif scrim.stage != "signup":
                result = "本场报名已关闭。"
            else:
                players = {**scrim.players, user.id: user.display_name}
                stage = "full" if len(players) == PLAYER_COUNT else "signup"
                updated = replace(scrim, players=players, stage=stage, revision=scrim.revision + 1)
                saved = await self.publish(scrim, updated, interaction.message)
                panel = self.host_panels.get(scrim.message_id)
                if saved and panel and not panel.is_expired():
                    try:
                        await panel.edit_original_response(**self.panel(updated))
                    except discord.HTTPException:
                        log.info("Could not refresh private roster for %s", scrim.message_id)
                remember_signup = saved
                result = "报名成功！" if saved else "公告更新失败，报名暂未保存，请重试。"
            await interaction.edit_original_response(content=result)
            if remember_signup:
                self.remember_player_interaction(scrim, interaction)

    def remember_player_interaction(self, scrim: Scrim, interaction: discord.Interaction):
        if interaction.guild_id != scrim.guild_id or interaction.channel_id != scrim.channel_id:
            return
        for key, previous in list(self.player_interactions.items()):
            if previous.is_expired():
                self.player_interactions.pop(key)
        self.player_interactions[scrim.message_id, interaction.user.id] = interaction

    async def handle_host(
        self, snapshot: Scrim, action: str, interaction: discord.Interaction, values: tuple[int, ...] = (),
    ):
        if interaction.user.id != snapshot.host_id or interaction.guild_id != snapshot.guild_id:
            await interaction.response.send_message("只有本场主办人可以操作。", ephemeral=True)
            return
        await interaction.response.defer()
        async with self.lock_for(snapshot.guild_id):
            scrim = self.db.get_scrim(snapshot.guild_id, snapshot.message_id)
            if scrim is None:
                await interaction.edit_original_response(content="这场内战的记录已不可用。", view=None)
                return
            if snapshot.revision != scrim.revision and not (
                action in ("start", "show_remove") and scrim.stage in ("signup", "full")
            ):
                await interaction.edit_original_response(**self.panel(scrim, note="名单或分队已更新，请重新操作。\n"))
                return
            if action in ("show_remove", "show_pick", "back"):
                if action == "show_remove" and len(scrim.players) == 1:
                    await interaction.edit_original_response(**self.panel(scrim, note="目前只有主办人，没有可删除的成员。\n"))
                    return
                mode = {"show_remove": "remove", "show_pick": "pick", "back": ""}[action]
                await interaction.edit_original_response(**self.panel(scrim, mode))
                return
            updated = self.apply_host_action(scrim, action, values)
            if updated is None:
                await interaction.edit_original_response(**self.panel(scrim, note="当前状态无法执行这项操作。\n"))
                return
            channel = self.bot.get_partial_messageable(scrim.channel_id)
            message = channel.get_partial_message(scrim.message_id)
            saved = await self.publish(scrim, updated, message)
            note = "" if saved else "公告更新失败，本次修改暂未保存，请重试。\n"
        await interaction.edit_original_response(**self.panel(updated if saved else scrim, note=note))
        if saved and updated.stage == "confirmed":
            self.host_panels.pop(updated.message_id, None)
            failed = []
            for user_id in updated.players:
                signup = self.player_interactions.get((updated.message_id, user_id))
                target = interaction if user_id == updated.host_id else signup
                if target is None or target.is_expired() or target.channel_id != updated.channel_id:
                    failed.append(f"<@{user_id}>")
                    continue
                try:
                    await target.followup.send(**assignment_notice(updated, user_id), ephemeral=True)
                except discord.HTTPException:
                    failed.append(f"<@{user_id}>")
            if failed:
                note = f"以下玩家可在本频道公告点击「查看我的分队」领取通知：{'、'.join(failed)}。\n"
                await interaction.edit_original_response(**self.panel(updated, note=note))

    async def show_my_team(self, interaction: discord.Interaction):
        scrim = self.get_confirmed_scrim(interaction, interaction.message.id)
        user_id = interaction.user.id
        if scrim is None or user_id not in scrim.players:
            await interaction.response.send_message("只有本场参赛者可以查看自己的分队。", ephemeral=True)
            return
        self.remember_player_interaction(scrim, interaction)
        current = self.db.get_scrim_passive_results(scrim.guild_id, scrim.message_id).get(user_id)
        if current:
            team = "A" if user_id in scrim.team_a else "B"
            await interaction.response.send_message(f"你在 {team} 队，当前被动是：{current}",
                                                    ephemeral=True, allowed_mentions=NO_PINGS)
        else:
            await interaction.response.send_message(**assignment_notice(scrim, user_id), ephemeral=True)

    async def handle_draw(self, interaction: discord.Interaction, round_id: int, recipient_id: int, source_guild_id: int | None = None):
        user_id = interaction.user.id
        if recipient_id and recipient_id != user_id:
            await interaction.response.send_message("请在分队公告上点击「查看我的分队」。", ephemeral=True)
            return
        guild_id = interaction.guild_id or source_guild_id
        if guild_id is None or (interaction.guild_id is None and not recipient_id):
            await interaction.response.send_message("请在内战频道使用这个按钮。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with self.lock_for(guild_id):
            scrim = self.db.get_scrim(guild_id, round_id)
            if scrim is None or scrim.stage != "confirmed" or (interaction.guild_id and interaction.channel_id != scrim.channel_id):
                result = "这场内战的抽取暂不可用。"
            elif user_id not in scrim.players:
                result = "只有本场参赛者可以抽取被动。"
            else:
                self.remember_player_interaction(scrim, interaction)
                passive = self.db.draw_scrim_passive(scrim.guild_id, scrim.message_id, user_id)
                if passive is None:
                    result = "暂无可用的被动，请管理员通过 /添加内战被动 补充条目。"
                else:
                    result = f"你的被动是：{passive}"
                    if not await self.publish_passive_table(scrim):
                        result += "\n公开表格更新失败，可以再次点击按钮重试。"
        await interaction.edit_original_response(content=result, allowed_mentions=NO_PINGS)

    async def publish_passive_table(self, scrim: Scrim) -> bool:
        results = self.db.get_scrim_passive_results(scrim.guild_id, scrim.message_id)
        if not passives_complete(scrim, results):
            return True
        table = discord.Embed(title=f"第 {scrim.number} 次趣味瓦内战 · 被动一览")
        for user_id in scrim.players:
            team = "A" if user_id in scrim.team_a else "B"
            table.add_field(name=f"{team} 队", value=f"<@{user_id}> · {results[user_id]}", inline=False)
        channel = self.bot.get_partial_messageable(scrim.channel_id)
        try:
            await channel.get_partial_message(scrim.message_id).edit(
                embed=table, **self.announcement(scrim, passives_ready=True),
            )
        except discord.HTTPException:
            log.exception("Could not update passive table for scrim %s", scrim.message_id)
            return False
        return True

    async def ensure_team_voice_channels(self, guild: discord.Guild, scrim: Scrim):
        lobby = guild.get_channel(scrim.channel_id) or await guild.fetch_channel(scrim.channel_id)
        existing = self.db.get_scrim_voice_channels(scrim.message_id)
        channels = {}
        for team in ("A", "B"):
            if team in existing:
                try:
                    channel = guild.get_channel(existing[team]) or await guild.fetch_channel(existing[team])
                except discord.NotFound:
                    pass
                else:
                    if isinstance(channel, discord.VoiceChannel):
                        channels[team] = channel
                        continue
            channel = await guild.create_voice_channel(
                f"内战{team}队", category=lobby.category, reason=f"第 {scrim.number} 次趣味瓦内战",
            )
            self.db.save_scrim_voice_channel(scrim.message_id, team, channel.id)
            channels[team] = channel
        return channels

    async def return_voice_members(self, guild: discord.Guild, scrim: Scrim) -> str:
        origin = guild.get_channel(scrim.origin_voice_id) if scrim.origin_voice_id else None
        for channel_id in self.db.get_scrim_voice_channels(scrim.message_id).values():
            try:
                room = await guild.fetch_channel(channel_id)
            except discord.NotFound:
                continue
            if not isinstance(room, discord.VoiceChannel):
                continue
            for member in list(room.members):
                if member.id not in scrim.players:
                    return "队伍频道里还有非参赛成员，请等其离开，再选择胜方重试。"
                if origin is None:
                    return "原集合频道不可用，请先让队员离开队伍频道，再选择胜方以清理空频道。"
                await member.move_to(origin, reason=f"第 {scrim.number} 场内战结束")
            await room.delete(reason=f"第 {scrim.number} 场内战结束")
        return ""

    async def load_card_players(self, scrim: Scrim, roster: dict[int, str], results: dict[int, str]):
        guild = self.bot.get_guild(scrim.guild_id)
        async def load_player(user_id, saved_name):
            member = guild.get_member(user_id) if guild else None
            try:
                if guild and member is None:
                    member = await asyncio.wait_for(guild.fetch_member(user_id), timeout=5)
                avatar = None
                if member:
                    asset = member.display_avatar.replace(size=128, format="png")
                    avatar = await asyncio.wait_for(asset.read(), timeout=5)
            except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, OSError):
                avatar = None
            return CardPlayer(member.display_name if member else saved_name, results.get(user_id, ""), avatar)

        return await asyncio.gather(*(load_player(uid, name) for uid, name in roster.items()))

    async def publish_victory(self, scrim: Scrim, team: str, roster: dict[int, str]):
        players = await self.load_card_players(scrim, roster, {})
        data = await asyncio.to_thread(render_victory, team, players)
        channel = self.bot.get_partial_messageable(scrim.channel_id)
        with closing(discord.File(BytesIO(data), filename=f"victory-{scrim.number}.jpg")) as image:
            await channel.send(f"第 {scrim.number} 次趣味瓦内战 · **{team} 队获胜**", file=image, allowed_mentions=NO_PINGS)

    async def publish_map_announcement(
        self, scrim: Scrim, map_name: str, results: dict[int, str],
    ) -> int:
        image_path = MAP_IMAGE_DIR / f"{map_name.lower()}.jpg"
        heading = f"第 {scrim.number} 次趣味瓦内战 · **开始比赛**\n{map_label(map_name)}"
        players = await self.load_card_players(scrim, scrim.players, results)
        card_teams = {"A": [], "B": []}
        team_rows: dict[str, list[str]] = {"A": [], "B": []}
        for user_id, player in zip(scrim.players, players):
            nickname = discord.utils.escape_mentions(discord.utils.escape_markdown(player.name))
            if user_id == scrim.host_id:
                nickname += "（主办人）"
            passive = discord.utils.escape_mentions(results[user_id])
            team = "A" if user_id in scrim.team_a else "B"
            card_teams[team].append(player)
            team_rows[team].append(f"**{nickname}** · {passive}")
        try:
            background = MAP_IMAGE_DIR.with_name("scrim_backgrounds") / image_path.name
            artwork = await asyncio.to_thread(render_matchup, background, map_name,
                                              VALORANT_MAPS[map_name][0], scrim.number, card_teams)
            filename = f"match-{scrim.number}-{image_path.name}"
        except OSError:
            log.exception("Matchup rendering failed for scrim %s", scrim.message_id)
            artwork = image_path.read_bytes()
            filename = image_path.name
        embeds = [
            discord.Embed(title=f"{team} 队", description="\n".join(rows) or "暂无成员")
            for team, rows in team_rows.items()
        ]

        channel = self.bot.get_partial_messageable(scrim.channel_id)
        if scrim.map_announcement_id is not None:
            message = channel.get_partial_message(scrim.map_announcement_id)
            try:
                with closing(discord.File(BytesIO(artwork), filename=filename)) as image:
                    await message.edit(content=heading, embeds=embeds, attachments=[image], allowed_mentions=NO_PINGS)
            except discord.NotFound:
                pass  # Recreate the announcement if it was deleted.
            else:
                return scrim.map_announcement_id
        with closing(discord.File(BytesIO(artwork), filename=filename)) as image:
            message = await channel.send(content=heading, embeds=embeds, file=image, allowed_mentions=NO_PINGS)
        return message.id

    def get_confirmed_scrim(self, interaction: discord.Interaction, round_id: int) -> Scrim | None:
        if interaction.guild_id is None:
            return None
        scrim = self.db.get_scrim(interaction.guild_id, round_id)
        if scrim and scrim.stage == "confirmed" and scrim.channel_id == interaction.channel_id:
            return scrim
        return None

    async def open_reroll_panel(self, interaction: discord.Interaction, round_id: int):
        scrim = self.db.get_scrim(interaction.guild_id, round_id)
        if scrim is None or scrim.stage != "confirmed" or interaction.user.id != scrim.host_id:
            await interaction.response.send_message("只有本场主办人可以替玩家重抽。", ephemeral=True)
            return
        if scrim.passives_confirmed:
            await interaction.response.send_message("被动已确认，重抽已关闭。", ephemeral=True)
            return
        results = self.db.get_scrim_passive_results(scrim.guild_id, scrim.message_id)
        if not results.keys() & scrim.players.keys():
            await interaction.response.send_message("还没有玩家抽取被动。", ephemeral=True)
            return
        await interaction.response.send_message(
            "选择一位已抽取的玩家，为该玩家换一条尚未被占用的被动。",
            view=RerollPanel(self, scrim, results),
            ephemeral=True,
        )

    async def reroll_passive(self, interaction: discord.Interaction, round_id: int, user_id: int):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if interaction.guild_id is None:
            await interaction.edit_original_response(content="只有本场主办人可以替玩家重抽。")
            return
        async with self.lock_for(interaction.guild_id):
            scrim = self.db.get_scrim(interaction.guild_id, round_id)
            if scrim is None or scrim.stage != "confirmed" or interaction.user.id != scrim.host_id:
                await interaction.edit_original_response(content="只有本场主办人可以替玩家重抽。")
                return
            if scrim.passives_confirmed:
                await interaction.edit_original_response(content="被动已确认，重抽已关闭。")
                return
            results = self.db.get_scrim_passive_results(scrim.guild_id, round_id)
            if user_id not in scrim.players or user_id not in results:
                result = "这位玩家还没有抽取被动。"
            else:
                passive = self.db.draw_scrim_passive(scrim.guild_id, round_id, user_id, reroll=True)
                if passive is None:
                    result = "没有空闲的被动可以重抽，请先通过 /添加内战被动 补充条目。"
                else:
                    result = f"已为 <@{user_id}> 重抽。新被动是：{passive}"
                    if user_id != interaction.user.id:
                        target = self.player_interactions.get((round_id, user_id))
                        delivered = False
                        if target and not target.is_expired():
                            try:
                                await target.followup.send(
                                    f"第 {scrim.number} 次趣味瓦内战 · 主办人已为你重抽。\n你的新被动是：**{passive}**",
                                    ephemeral=True, allowed_mentions=NO_PINGS,
                                )
                                delivered = True
                            except discord.HTTPException:
                                log.info("Could not deliver private reroll for scrim %s", round_id)
                        result += "\n已在内战频道通知该玩家。" if delivered else "\n未能自动通知。该玩家可点击「查看我的分队」查看最新被动。"
                    if not await self.publish_passive_table(scrim):
                        result += "\n公开表格更新失败。参赛者再次点击「抽取被动」即可重试更新。"
        await interaction.edit_original_response(content=result, allowed_mentions=NO_PINGS)

    async def handle_map_setup(
        self, interaction: discord.Interaction, round_id: int, action: str, map_name: str | None = None,
    ):
        private_panel = interaction.message.flags.ephemeral
        await interaction.response.defer(ephemeral=True, thinking=not private_panel)
        if interaction.guild_id is None:
            await interaction.edit_original_response(content="请在内战频道使用这个按钮。")
            return
        async with self.lock_for(interaction.guild_id):
            scrim = self.db.get_scrim(interaction.guild_id, round_id)
            if scrim is None or scrim.stage != "confirmed" or interaction.user.id != scrim.host_id:
                await interaction.edit_original_response(content="只有本场主办人可以确认被动、选图或确认对战。")
                return
            if scrim.ended:
                await interaction.edit_original_response(content="本场对战已结束。", view=None)
                return
            if scrim.map_announcement_id is not None and action not in ("picker", "replace_map", "end", "win_a", "win_b"):
                await interaction.edit_original_response(**self.panel(scrim, note="本场对战已经发布。\n"))
                return
            if action in ("end", "win_a", "win_b"):
                if scrim.map_announcement_id is None:
                    await interaction.edit_original_response(content="本场对战尚未开始。")
                    return
                if action == "end":
                    await interaction.edit_original_response(**self.panel(scrim, "winner", "请选择本场获胜队伍。\n"))
                    return
                team = "A" if action == "win_a" else "B"
                roster = {uid: name for uid, name in scrim.players.items() if (uid in scrim.team_a) == (team == "A")}
                if not roster:
                    await interaction.edit_original_response(**self.panel(scrim, "winner", "这支队伍没有参赛者。\n"))
                    return
                try:
                    issue = await self.return_voice_members(interaction.guild, scrim)
                except discord.HTTPException:
                    log.exception("Could not finish voice cleanup for scrim %s", round_id)
                    issue = "语音归队或清理失败。请检查「移动成员」「连接」「管理频道」权限及集合频道容量，再选择胜方重试。"
                if issue:
                    await interaction.edit_original_response(**self.panel(scrim, "winner", note=issue + "\n"))
                    return
                try:
                    await self.publish_victory(scrim, team, roster)
                except (discord.HTTPException, OSError):
                    log.exception("Could not post victory card for scrim %s", round_id)
                    await interaction.edit_original_response(**self.panel(scrim, "winner", "语音已清理，胜利图发布失败，请选择胜方重试。\n"))
                    return
                updated = replace(scrim, ended=True)
                result = "对战已结束，本场队伍语音频道已清理。"
            elif action == "confirm":
                results = self.db.get_scrim_passive_results(scrim.guild_id, round_id)
                if not passives_complete(scrim, results):
                    await interaction.edit_original_response(content="请等所有参赛者抽完各自的被动。")
                    return
                updated = replace(scrim, passives_confirmed=True)
                result = "已确认被动。现在可以抽取地图或手动选择地图。"
            elif not scrim.passives_confirmed:
                await interaction.edit_original_response(content="请先确认本场被动。")
                return
            elif action == "picker":
                prompt = "选择新地图后，机器人会更新已发布的对战图。" if scrim.map_announcement_id else "请选择本场地图。"
                await interaction.edit_original_response(content=prompt, view=MapPicker(self, scrim))
                return
            elif action in ("match", "replace_map"):
                selected = map_name if action == "replace_map" else scrim.map_name
                if selected not in VALORANT_MAPS or (action == "replace_map" and scrim.map_announcement_id is None):
                    await interaction.edit_original_response(content="请先选择本场地图。")
                    return
                results = self.db.get_scrim_passive_results(scrim.guild_id, round_id)
                if not passives_complete(scrim, results):
                    await interaction.edit_original_response(content="被动结果不完整，暂时无法发布地图公告。")
                    return
                if action == "match":
                    offline = []
                    try:
                        channels = await self.ensure_team_voice_channels(interaction.guild, scrim)
                        if scrim.origin_voice_id:
                            for uid in scrim.players:
                                member = interaction.guild.get_member(uid)
                                if not member or not member.voice or not member.voice.channel:
                                    offline.append(f"<@{uid}>")
                                    continue
                                room = channels["A" if uid in scrim.team_a else "B"]
                                if member.voice.channel.id != room.id:
                                    await member.move_to(room, reason=f"第 {scrim.number} 场内战开始")
                    except discord.HTTPException:
                        log.exception("Could not prepare team voice channels for scrim %s", round_id)
                        await interaction.edit_original_response(**self.panel(
                            scrim, note="语音分队尚未完成。请检查「管理频道」「移动成员」「连接」权限及频道容量，再点「开始比赛」重试。\n",
                        ))
                        return
                try:
                    announcement_id = await self.publish_map_announcement(scrim, selected, results)
                except discord.HTTPException:
                    log.exception("Could not publish map announcement for scrim %s", round_id)
                    await interaction.edit_original_response(content="地图公告发布失败，请检查频道的发送消息、嵌入链接和附加文件权限后重试。")
                    return
                updated = replace(scrim, map_name=selected, map_announcement_id=announcement_id)
                result = "对战图已按新地图更新。" if action == "replace_map" else "对战已确认，对战公告已发布。"
                if action == "match" and offline:
                    result += "\n未连接语音，请自行加入队伍频道：" + "、".join(offline)
            else:
                selected = choice(tuple(VALORANT_MAPS)) if action == "random" else map_name
                if selected not in VALORANT_MAPS:
                    await interaction.edit_original_response(content="请选择地图列表中的选项。")
                    return
                updated = replace(scrim, map_name=selected)
                result = f"地图已确认：**{map_label(selected)}**。点击「开始比赛」发布对战图。"
            self.db.save_scrim(updated)
            published = await self.publish_passive_table(updated)
            if not published:
                if updated.map_announcement_id is None:
                    self.db.save_scrim(scrim)
                    result = "公告更新失败，操作暂未保存，请重试。"
                else:
                    result += "\n原报名公告刷新失败，对战公告仍可在频道中查看。"
        panel_state = updated if published or updated.map_announcement_id is not None else scrim
        await interaction.edit_original_response(**self.panel(panel_state, note=result + "\n"))
        if action == "match":
            await self.send_end_button(interaction, updated)

    @staticmethod
    def apply_host_action(scrim: Scrim, action: str, values: tuple[int, ...]) -> Scrim | None:
        revision = scrim.revision + 1
        if action == "remove" and scrim.stage in ("signup", "full") and len(values) == 1:
            user_id = values[0]
            if user_id in scrim.players and user_id != scrim.host_id:
                players = {uid: name for uid, name in scrim.players.items() if uid != user_id}
                return replace(scrim, players=players, stage="signup", revision=revision)
        if action == "start" and scrim.stage in ("signup", "full") and scrim.players:
            return replace(scrim, stage="teams", revision=revision)
        if action == "pick" and scrim.stage == "teams":
            selected = set(values)
            if len(values) == len(selected) == team_a_size(scrim) and selected.issubset(scrim.players):
                return replace(scrim, team_a=values, revision=revision)
        if action == "confirm" and scrim.stage == "teams" and scrim.team_a:
            return replace(scrim, stage="confirmed", revision=revision)
        return None
