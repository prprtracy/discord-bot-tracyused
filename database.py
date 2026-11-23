import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from random import choice
from typing import Optional

from scrim_passives import DEFAULT_SCRIM_PASSIVES


@dataclass
class Binding:
    guild_id: int
    nickname: str
    discord_user_id: str
    discord_user_name: str
    created_at: str
    dcid: Optional[str] = None

DB_PATH = "ledger.db"


@dataclass
class Companion:
    guild_id: int
    nickname: str
    gift_name: str
    category: str
    total_added_hours: float
    reported_hours: float
    settled_hours: float
    discord_user_id: Optional[str] = None  # 绑定的 Discord 用户 ID

    @property
    def remaining_hours(self) -> float:
        return self.total_added_hours - self.reported_hours

    @property
    def pending_settlement(self) -> float:
        return self.reported_hours - self.settled_hours


@dataclass
class HistoryEntry:
    id: int
    guild_id: int
    nickname: str
    action_type: str
    details: str
    operator_id: str
    operator_name: str
    created_at: str


@dataclass
class GuildSettings:
    guild_id: int
    bot_nickname: Optional[str]
    webhook_url: Optional[str]
    display_name: Optional[str]
    avatar_url: Optional[str]
    log_channel_id: Optional[int]      # 业务日志频道（报单/结算等）
    allowed_channel_id: Optional[int]  # 允许使用 slash commands 的频道
    monitor_channel_id: Optional[int]  # 监听通知频道（语音/成员进出）
    staff_role_id: Optional[str] = None
    welcome_channel_id: Optional[int] = None  # 欢迎消息频道
    leave_channel_id: Optional[int] = None    # 成员离开通知频道


@dataclass
class Scrim:
    guild_id: int
    number: int
    channel_id: int
    message_id: int
    host_id: int
    players: dict[int, str]
    stage: str = "signup"
    team_a: tuple[int, ...] = ()
    revision: int = 0
    passives_confirmed: bool = False
    map_name: str | None = None
    map_announcement_id: int | None = None


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._init_tables()

    def _conn(self):
        return sqlite3.connect(self.path)

    def _init_tables(self):
        with closing(self._conn()) as conn, conn:
            self._migrate(conn)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS scrim_channels (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scrims (
                    guild_id INTEGER NOT NULL,
                    number INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    players TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    team_a TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    passives_confirmed INTEGER NOT NULL DEFAULT 0,
                    map_name TEXT,
                    map_announcement_id INTEGER,
                    PRIMARY KEY (guild_id, message_id),
                    UNIQUE (guild_id, number)
                )
            """)
            scrim_columns = {row[1] for row in conn.execute("PRAGMA table_info(scrims)")}
            if "passives_confirmed" not in scrim_columns:
                conn.execute("ALTER TABLE scrims ADD COLUMN passives_confirmed INTEGER NOT NULL DEFAULT 0")
            if "map_name" not in scrim_columns:
                conn.execute("ALTER TABLE scrims ADD COLUMN map_name TEXT")
            if "map_announcement_id" not in scrim_columns:
                conn.execute("ALTER TABLE scrims ADD COLUMN map_announcement_id INTEGER")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scrim_passive_pools (
                    guild_id INTEGER PRIMARY KEY,
                    entries TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scrim_passive_results (
                    guild_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    passive TEXT NOT NULL,
                    PRIMARY KEY (guild_id, message_id, user_id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS companions (
                    guild_id          INTEGER NOT NULL,
                    nickname          TEXT NOT NULL,
                    gift_name         TEXT NOT NULL,
                    category          TEXT NOT NULL,
                    total_added_hours REAL DEFAULT 0,
                    reported_hours    REAL DEFAULT 0,
                    settled_hours     REAL DEFAULT 0,
                    discord_user_id   TEXT,
                    PRIMARY KEY (guild_id, nickname)
                )
            """)
            # 兼容旧数据库：按需追加新列
            try:
                conn.execute("ALTER TABLE companions ADD COLUMN discord_user_id TEXT")
            except Exception:
                pass
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id      INTEGER NOT NULL DEFAULT 0,
                    nickname      TEXT NOT NULL,
                    action_type   TEXT NOT NULL,
                    details       TEXT NOT NULL,
                    operator_id   TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    created_at    TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id           INTEGER PRIMARY KEY,
                    bot_nickname       TEXT,
                    webhook_url        TEXT,
                    display_name       TEXT,
                    avatar_url         TEXT,
                    log_channel_id     INTEGER,
                    allowed_channel_id INTEGER,
                    monitor_channel_id INTEGER
                )
            """)
            # 兼容旧数据库：按需追加新列
            for col in ("allowed_channel_id", "monitor_channel_id", "welcome_channel_id", "leave_channel_id"):
                try:
                    conn.execute(f"ALTER TABLE guild_settings ADD COLUMN {col} INTEGER")
                except Exception:
                    pass
            try:
                conn.execute("ALTER TABLE guild_settings ADD COLUMN staff_role_id TEXT")
            except Exception:
                pass

            # ── bindings 表（独立绑定关系，不依赖 companions 是否存在）──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bindings (
                    guild_id          INTEGER NOT NULL,
                    nickname          TEXT NOT NULL,
                    dcid              TEXT,
                    discord_user_id   TEXT NOT NULL,
                    discord_user_name TEXT NOT NULL DEFAULT '',
                    created_at        TEXT NOT NULL,
                    PRIMARY KEY (guild_id, nickname)
                )
            """)
            try:
                conn.execute("ALTER TABLE bindings ADD COLUMN dcid TEXT")
            except Exception:
                pass

    def get_scrim_channel(self, guild_id: int) -> Optional[int]:
        with closing(self._conn()) as conn:
            row = conn.execute(
                "SELECT channel_id FROM scrim_channels WHERE guild_id = ?", (guild_id,)
            ).fetchone()
        return row[0] if row else None

    def set_scrim_channel(self, guild_id: int, channel_id: int):
        with closing(self._conn()) as conn, conn:
            conn.execute("""
                INSERT INTO scrim_channels VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
            """, (guild_id, channel_id))

    def next_scrim_number(self, guild_id: int) -> int:
        with closing(self._conn()) as conn:
            return conn.execute(
                "SELECT COALESCE(MAX(number), 0) + 1 FROM scrims WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()[0]

    def get_scrim(self, guild_id: int, message_id: int) -> Optional[Scrim]:
        with closing(self._conn()) as conn:
            row = conn.execute("""
                SELECT guild_id, number, channel_id, message_id, host_id,
                       players, stage, team_a, revision, passives_confirmed, map_name, map_announcement_id
                FROM scrims WHERE guild_id = ? AND message_id = ?
            """, (guild_id, message_id)).fetchone()
        if row is None:
            return None
        players = {int(user_id): name for user_id, name in json.loads(row[5]).items()}
        return Scrim(*row[:5], players, row[6], tuple(json.loads(row[7])), row[8], bool(row[9]), *row[10:])

    def save_scrim(self, scrim: Scrim):
        with closing(self._conn()) as conn, conn:
            conn.execute("""
                INSERT INTO scrims
                    (guild_id, number, channel_id, message_id, host_id,
                     players, stage, team_a, revision, passives_confirmed, map_name, map_announcement_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, message_id) DO UPDATE SET
                    players = excluded.players,
                    stage = excluded.stage,
                    team_a = excluded.team_a,
                    revision = excluded.revision,
                    passives_confirmed = excluded.passives_confirmed,
                    map_name = excluded.map_name,
                    map_announcement_id = excluded.map_announcement_id
            """, (
                scrim.guild_id, scrim.number, scrim.channel_id, scrim.message_id,
                scrim.host_id, json.dumps(scrim.players), scrim.stage,
                json.dumps(scrim.team_a), scrim.revision, scrim.passives_confirmed, scrim.map_name,
                scrim.map_announcement_id,
            ))

    def _scrim_passives(self, conn: sqlite3.Connection, guild_id: int) -> list[str]:
        row = conn.execute(
            "SELECT entries FROM scrim_passive_pools WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return json.loads(row[0]) if row else list(DEFAULT_SCRIM_PASSIVES)

    def get_scrim_passives(self, guild_id: int) -> list[str]:
        with closing(self._conn()) as conn:
            return self._scrim_passives(conn, guild_id)

    def set_scrim_passives(self, guild_id: int, entries: list[str]):
        with closing(self._conn()) as conn, conn:
            conn.execute("""
                INSERT INTO scrim_passive_pools VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET entries = excluded.entries
            """, (guild_id, json.dumps(entries)))

    def _scrim_passive_results(self, conn: sqlite3.Connection, guild_id: int, message_id: int) -> dict[int, str]:
        return dict(conn.execute("""
            SELECT user_id, passive FROM scrim_passive_results
            WHERE guild_id = ? AND message_id = ?
        """, (guild_id, message_id)))

    def get_scrim_passive_results(self, guild_id: int, message_id: int) -> dict[int, str]:
        with closing(self._conn()) as conn:
            return self._scrim_passive_results(conn, guild_id, message_id)

    def draw_scrim_passive(
        self, guild_id: int, message_id: int, user_id: int, *, reroll: bool = False,
    ) -> Optional[str]:
        with closing(self._conn()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            results = self._scrim_passive_results(conn, guild_id, message_id)
            previous = results.get(user_id)
            if not reroll:
                if previous is not None:
                    return previous
            elif previous is None:
                return None
            taken = set(results.values())
            available = [entry for entry in self._scrim_passives(conn, guild_id) if entry not in taken]
            if not available:
                return None
            passive = choice(available)
            conn.execute("""
                INSERT INTO scrim_passive_results VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, message_id, user_id) DO UPDATE SET passive = excluded.passive
            """, (guild_id, message_id, user_id, passive))
            return passive

    def _migrate(self, conn: sqlite3.Connection):
        """
        将旧表（无 guild_id）迁移为新结构。
        旧数据以 guild_id=0 保留，不会出现在任何真实服务器的查询中。
        """
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        # ── companions 迁移 ────────────────────────────────────
        if "companions" in tables:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(companions)").fetchall()}
            if "guild_id" not in cols:
                conn.execute("ALTER TABLE companions RENAME TO companions_old")
                conn.execute("""
                    CREATE TABLE companions (
                        guild_id          INTEGER NOT NULL,
                        nickname          TEXT NOT NULL,
                        gift_name         TEXT NOT NULL,
                        category          TEXT NOT NULL,
                        total_added_hours REAL DEFAULT 0,
                        reported_hours    REAL DEFAULT 0,
                        settled_hours     REAL DEFAULT 0,
                        PRIMARY KEY (guild_id, nickname)
                    )
                """)
                conn.execute("""
                    INSERT INTO companions
                        (guild_id, nickname, gift_name, category, total_added_hours, reported_hours, settled_hours)
                    SELECT 0, nickname, gift_name, category, total_added_hours, reported_hours, settled_hours
                    FROM companions_old
                """)
                conn.execute("DROP TABLE companions_old")
                print("[迁移] companions 表已升级，旧数据 guild_id=0")

        # ── history 迁移 ───────────────────────────────────────
        if "history" in tables:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(history)").fetchall()}
            if "guild_id" not in cols:
                conn.execute("ALTER TABLE history RENAME TO history_old")
                conn.execute("""
                    CREATE TABLE history (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id      INTEGER NOT NULL DEFAULT 0,
                        nickname      TEXT NOT NULL,
                        action_type   TEXT NOT NULL,
                        details       TEXT NOT NULL,
                        operator_id   TEXT NOT NULL,
                        operator_name TEXT NOT NULL,
                        created_at    TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    INSERT INTO history
                        (guild_id, nickname, action_type, details, operator_id, operator_name, created_at)
                    SELECT 0, nickname, action_type, details, operator_id, operator_name, created_at
                    FROM history_old
                """)
                conn.execute("DROP TABLE history_old")
                print("[迁移] history 表已升级，旧数据 guild_id=0")

    # ── 主表操作（全部按 guild_id 隔离） ───────────────────────

    def get(self, guild_id: int, nickname: str) -> Optional[Companion]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM companions WHERE guild_id = ? AND nickname = ?",
                (guild_id, nickname),
            ).fetchone()
        return Companion(*row) if row else None

    def upsert_add(self, guild_id: int, nickname: str, gift_name: str, category: str, hours: float) -> Companion:
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM companions WHERE guild_id = ? AND nickname = ?",
                (guild_id, nickname),
            ).fetchone()
            if exists:
                conn.execute(
                    "UPDATE companions SET total_added_hours = total_added_hours + ? "
                    "WHERE guild_id = ? AND nickname = ?",
                    (hours, guild_id, nickname),
                )
            else:
                # 如果 bindings 中已有绑定，插入时同步 discord_user_id
                binding_row = conn.execute(
                    "SELECT discord_user_id FROM bindings WHERE guild_id = ? AND nickname = ?",
                    (guild_id, nickname),
                ).fetchone()
                bound_uid = binding_row[0] if binding_row else None
                conn.execute(
                    "INSERT INTO companions "
                    "(guild_id, nickname, gift_name, category, "
                    " total_added_hours, reported_hours, settled_hours, discord_user_id) "
                    "VALUES (?, ?, ?, ?, ?, 0, 0, ?)",
                    (guild_id, nickname, gift_name, category, hours, bound_uid),
                )
        return self.get(guild_id, nickname)

    def add_reported(self, guild_id: int, nickname: str, hours: float) -> Companion:
        with self._conn() as conn:
            conn.execute(
                "UPDATE companions SET reported_hours = reported_hours + ? "
                "WHERE guild_id = ? AND nickname = ?",
                (hours, guild_id, nickname),
            )
        return self.get(guild_id, nickname)

    def add_settled(self, guild_id: int, nickname: str, hours: float) -> Companion:
        with self._conn() as conn:
            conn.execute(
                "UPDATE companions SET settled_hours = settled_hours + ? "
                "WHERE guild_id = ? AND nickname = ?",
                (hours, guild_id, nickname),
            )
        return self.get(guild_id, nickname)

    def update(
        self,
        guild_id: int,
        nickname: str,
        gift_name: str | None = None,
        category: str | None = None,
        total_added_hours: float | None = None,
        reported_hours: float | None = None,
        settled_hours: float | None = None,
    ) -> bool:
        fields = {
            "gift_name": gift_name,
            "category": category,
            "total_added_hours": total_added_hours,
            "reported_hours": reported_hours,
            "settled_hours": settled_hours,
        }
        updates = {k: v for k, v in fields.items() if v is not None}
        if not updates:
            return False
        clauses = ", ".join(f"{k} = ?" for k in updates)
        with self._conn() as conn:
            affected = conn.execute(
                f"UPDATE companions SET {clauses} WHERE guild_id = ? AND nickname = ?",
                (*updates.values(), guild_id, nickname),
            ).rowcount
        return affected > 0

    def delete(self, guild_id: int, nickname: str) -> bool:
        with self._conn() as conn:
            affected = conn.execute(
                "DELETE FROM companions WHERE guild_id = ? AND nickname = ?",
                (guild_id, nickname),
            ).rowcount
        return affected > 0

    def get_all(self, guild_id: int) -> list[Companion]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM companions WHERE guild_id = ? ORDER BY nickname",
                (guild_id,),
            ).fetchall()
        return [Companion(*row) for row in rows]

    def get_by_user_id(self, guild_id: int, discord_user_id: str) -> list[Companion]:
        """按绑定的 Discord 用户 ID 查询该用户名下的所有记录"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM companions WHERE guild_id = ? AND discord_user_id = ?",
                (guild_id, discord_user_id),
            ).fetchall()
        return [Companion(*row) for row in rows]

    def bind_user(self, guild_id: int, nickname: str, discord_user_id: str) -> bool:
        """旧接口兼容：同步 companions 表中的 discord_user_id（昵称必须已存在）"""
        with self._conn() as conn:
            affected = conn.execute(
                "UPDATE companions SET discord_user_id = ? WHERE guild_id = ? AND nickname = ?",
                (discord_user_id, guild_id, nickname),
            ).rowcount
        return affected > 0

    # ── bindings 表操作 ────────────────────────────────────────

    def upsert_binding(
        self,
        guild_id: int,
        nickname: str,
        discord_user_id: str,
        discord_user_name: str = "",
    ) -> None:
        """
        在 bindings 表写入或更新绑定关系。
        无论 companions 表中是否存在该昵称均可调用。
        同时将 discord_user_id 同步写入 companions 表（若该昵称已存在）。
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO bindings (guild_id, nickname, discord_user_id, discord_user_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, nickname) DO UPDATE SET
                    discord_user_id   = excluded.discord_user_id,
                    discord_user_name = excluded.discord_user_name,
                    created_at        = excluded.created_at
                """,
                (guild_id, nickname, discord_user_id, discord_user_name, now),
            )
            # 如果 companions 中已有该昵称，顺手同步
            conn.execute(
                "UPDATE companions SET discord_user_id = ? WHERE guild_id = ? AND nickname = ?",
                (discord_user_id, guild_id, nickname),
            )

    def get_binding(self, guild_id: int, nickname: str) -> Optional["Binding"]:
        """查询某个昵称在当前服务器的绑定关系"""
        with self._conn() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(bindings)").fetchall()}
            dcid_expr = "dcid" if "dcid" in cols else "NULL"
            row = conn.execute(
                f"SELECT guild_id, nickname, discord_user_id, discord_user_name, created_at, {dcid_expr} "
                "FROM bindings WHERE guild_id = ? AND nickname = ?",
                (guild_id, nickname),
            ).fetchone()
        return Binding(*row) if row else None

    def get_nicknames_by_user(self, guild_id: int, discord_user_id: str) -> list[str]:
        """通过 Discord 用户 ID 查出该用户在当前服务器绑定的所有昵称"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT nickname FROM bindings WHERE guild_id = ? AND discord_user_id = ?",
                (guild_id, discord_user_id),
            ).fetchall()
        return [row[0] for row in rows]

    # ── 历史记录操作 ───────────────────────────────────────────

    def log_action(
        self,
        guild_id: int,
        nickname: str,
        action_type: str,
        details: str,
        operator_id: str,
        operator_name: str,
    ):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO history (guild_id, nickname, action_type, details, operator_id, operator_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, nickname, action_type, details, operator_id, operator_name, now),
            )

    def get_history(self, guild_id: int, nickname: str) -> list[HistoryEntry]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM history WHERE guild_id = ? AND nickname = ? ORDER BY id ASC",
                (guild_id, nickname),
            ).fetchall()
        return [HistoryEntry(*row) for row in rows]

    # ── 服务器配置操作 ─────────────────────────────────────────

    def get_guild_settings(self, guild_id: int) -> Optional[GuildSettings]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT guild_id, bot_nickname, webhook_url, display_name, avatar_url,
                       log_channel_id, allowed_channel_id, monitor_channel_id,
                       staff_role_id, welcome_channel_id, leave_channel_id
                FROM guild_settings
                WHERE guild_id = ?
                """,
                (guild_id,),
            ).fetchone()
        return GuildSettings(*row) if row else None

    def upsert_guild_settings(
        self,
        guild_id: int,
        bot_nickname: str | None = None,
        webhook_url: str | None = None,
        display_name: str | None = None,
        avatar_url: str | None = None,
        log_channel_id: int | None = None,
        allowed_channel_id: int | None = None,
        monitor_channel_id: int | None = None,
        staff_role_id: str | None = None,
        welcome_channel_id: int | None = None,
        leave_channel_id: int | None = None,
    ):
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO guild_settings
                    (guild_id, bot_nickname, webhook_url, display_name, avatar_url,
                     log_channel_id, allowed_channel_id, monitor_channel_id,
                     staff_role_id, welcome_channel_id, leave_channel_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    bot_nickname       = excluded.bot_nickname,
                    webhook_url        = excluded.webhook_url,
                    display_name       = excluded.display_name,
                    avatar_url         = excluded.avatar_url,
                    log_channel_id     = excluded.log_channel_id,
                    allowed_channel_id = excluded.allowed_channel_id,
                    monitor_channel_id = excluded.monitor_channel_id,
                    staff_role_id      = COALESCE(excluded.staff_role_id, guild_settings.staff_role_id),
                    welcome_channel_id = excluded.welcome_channel_id,
                    leave_channel_id   = excluded.leave_channel_id
            """, (guild_id, bot_nickname, webhook_url, display_name, avatar_url,
                  log_channel_id, allowed_channel_id, monitor_channel_id,
                  staff_role_id,
                  welcome_channel_id, leave_channel_id))
