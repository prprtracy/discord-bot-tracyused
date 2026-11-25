# 🌡️ Discord Bot TracyUsed

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![Pillow](https://img.shields.io/badge/Pillow-10%2B-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

**一个功能完整的 Discord 陪玩/时长管理机器人**
支持报单、结算、查询、绑定账号、多服务器隔离、自动欢迎图生成

</div>

---

## 📸 截图预览

### 欢迎图效果
> 成员加入服务器时，自动在欢迎频道发送带头像的欢迎卡片

![欢迎图截图](docs/screenshots/welcome_card.png)

### 报单 / 查询
> 用户使用 `/报单` 记录时长，`/查询我的剩余时长` 查看剩余

![报单截图](docs/screenshots/ledger.png)

### 结算面板
> 拥有管理身份组的成员使用 `/结算` 进行结算，显示剩余与待结算时长

![结算截图](docs/screenshots/settle.png)

> 💡 **添加截图方法**：将截图放入 `docs/screenshots/` 目录，文件名对应上方路径即可自动显示。

---

## ✨ 功能一览

| 功能 | 说明 |
|------|------|
| 📋 **添加陪玩** | 管理身份组成员录入陪玩昵称、礼物名、分类、时长 |
| 📝 **报单** | 用户为指定陪玩报告消耗时长 |
| 🔍 **查询剩余时长** | 用户查询自己绑定账号下的剩余时长 |
| 💰 **结算** | 管理身份组成员对指定陪玩进行结算，显示待结算金额 |
| 🔗 **绑定账号** | 将 Discord 用户与陪玩昵称绑定，无需每次输入 |
| 🖼️ **自动欢迎图** | 成员加入时生成带头像的欢迎卡片并发送到欢迎频道 |
| 🚪 **离开通知** | 成员退出时在指定频道发送离开通知 |
| 🎙️ **语音监听** | 自动记录成员进出语音频道 |
| 🏢 **多服务器隔离** | 所有数据按 `guild_id` 完全隔离，互不干扰 |
| ⚙️ **频道配置** | 可独立配置日志频道、监听频道、欢迎频道、离开频道 |
| 🎮 **VALORANT 趣味内战** | 最多 10 人报名、名单确认、主办人手动分队 |

---

## 🛠️ 技术栈

- **语言**：Python 3.10+
- **框架**：[discord.py 2.x](https://discordpy.readthedocs.io/)（Cog 架构 + app_commands slash commands）
- **数据库**：SQLite 3（`sqlite3` 标准库，自动迁移）
- **图像生成**：[Pillow](https://pillow.readthedocs.io/)（圆形头像裁剪、圆角矩形、alpha 合成）
- **异步 HTTP**：[aiohttp](https://docs.aiohttp.org/)（下载头像、检测 URL）

---

## 📁 项目结构

```
discord-bot/
├── main.py               # 入口：Bot 初始化、Cog 加载、slash command 同步
├── database.py           # 数据库封装（companions / bindings / guild_settings / history）
├── welcome_card.py       # 欢迎图片生成（Pillow）
├── utils.py              # 工具函数（日志频道发送、URL 检测）
├── config.py             # 配置文件（Token、Guild ID 等，不上传）
├── cogs/
│   ├── ledger.py         # 陪玩管理命令（报单、结算、查询、绑定）
│   ├── guild_config.py   # 服务器配置命令（频道设置、显示设置）
│   └── events.py         # 事件监听（成员加入/离开、语音状态变化）
└── ledger.db             # SQLite 数据库（不上传）
```

---

## ⚡ 快速部署

### 1. 克隆项目

```bash
git clone https://github.com/prprtracy/discord-bot-tracyused.git
cd discord-bot-tracyused
```

### 2. 安装依赖

```bash
pip install "discord.py>=2.4,<3" aiohttp Pillow
```

### 3. 创建配置文件

新建 `config.py`（此文件不会被上传到 GitHub）：

```python
DISCORD_TOKEN = "你的 Bot Token"
BOT_OWNER_ID = "你的 Discord 用户 ID"
```

### 4. 启动 Bot

```bash
python3 main.py
```

### 5. 设置管理身份组

第一次部署后，机器人拥有者需要先运行：

```text
/设置管理身份组 @客服
```

之后拥有该身份组的人才可以使用管理命令。`BOT_OWNER_ID` 永远拥有最高权限，即使服务器还没有设置管理身份组也可以运行 `/设置管理身份组`。

---

## 🤖 Slash Commands

### 陪玩管理（`cogs/ledger.py`）

| 命令 | 权限 | 说明 |
|------|------|------|
| `/添加陪玩` | 管理身份组 / BOT_OWNER_ID | 录入陪玩信息和初始时长 |
| `/报单` | 所有人 | 为指定陪玩报告消耗时长 |
| `/查询我的剩余时长` | 所有人 | 查询自己绑定昵称的剩余时长 |
| `/查询结算` | 管理身份组 / BOT_OWNER_ID | 查看指定陪玩的结算详情 |
| `/结算` | 管理身份组 / BOT_OWNER_ID | 对指定陪玩进行结算 |
| `/绑定账号` | 所有人 | 将 Discord 账号与陪玩昵称绑定 |
| `/查看所有陪玩` | 管理身份组 / BOT_OWNER_ID | 列出本服务器所有陪玩记录 |

### 服务器配置（`cogs/guild_config.py`）

| 命令 | 权限 | 说明 |
|------|------|------|
| `/设置管理身份组` | BOT_OWNER_ID | 设置本服务器可使用管理命令的 Discord 身份组 |
| `/设置服务器显示` | 管理身份组 / BOT_OWNER_ID | 配置 Bot 昵称、Webhook、显示名称、头像 |
| `/查看服务器显示` | 管理身份组 / BOT_OWNER_ID | 查看当前显示配置 |
| `/设置日志频道` | 管理身份组 / BOT_OWNER_ID | 设置业务日志频道 |
| `/设置监听频道` | 管理身份组 / BOT_OWNER_ID | 设置语音/成员监听频道 |
| `/设置欢迎频道` | 管理身份组 / BOT_OWNER_ID | 设置新成员欢迎图发送频道 |
| `/设置离开频道` | 管理身份组 / BOT_OWNER_ID | 设置成员离开通知频道 |
| `/查看日志频道` | 管理身份组 / BOT_OWNER_ID | 查看当前各频道配置 |

### VALORANT 趣味内战

1. 拥有「管理服务器」权限的成员使用 `/设置内战频道` 选择公告频道。机器人需要在该频道拥有「查看频道」和「发送消息」权限。
2. 成员使用 `/趣味内战` 发起活动。机器人在指定频道发布带场次编号的公告，发起人自动成为主办人并占一个名额。其他成员点击「确认参加」报名。
3. 主办人可在报名期间点击「主办人面板」，删除成员并补招，或点击「确认列表，开始分队」锁定当前名单并关闭报名。报名满 10 人时会自动关闭。
4. 主办人按实际人数选择 A 队成员，其余成员自动进入 B 队。人数为奇数时，A 队多 1 人。频道公告会显示分队预览，主办人可以修改或确认。
5. 正式确认后，参赛者点击分队公告上的「查看我的分队」，机器人会私密回复队伍和「抽取被动」按钮。同场被动不会重复，重复点击会显示当前结果。个人抽取回复仅本人可见，所有参赛者都抽完后，分队公告会公开显示玩家和被动对照表。
6. 主办人可从分队公告点击「主办人重抽」，选择任意已抽取的玩家。新结果从未被占用的条目中抽取，已公开的对照表会同步更新。
7. 所有参赛者抽完后，主办人点击「确认被动」锁定结果。之后可点击「抽取地图」随机选图，或点击「手动选择地图」从下拉菜单选图。机器人会在内战频道发出地图确认公告，上方展示 Riot 官方地图图，下方按 A、B 队列出 Discord 昵称和对应被动。主办人改选时，机器人会更新同一条地图公告。机器人需要在内战频道拥有「嵌入链接」权限。

服务器默认使用内置的 45 条被动。成员可用 `/查看被动列表` 查看当前服务器实际用于抽取的条目。拥有「管理服务器」权限的成员可用 `/添加内战被动` 编辑本服务器的被动库，每行填写一条条件。服务器已有的自定义清单会优先使用。10 人抽完至少需要 10 条不同的被动，满员后重抽需要有空闲条目，建议配置至少 11 条。

选图池包含 VALORANT 官网截至 2026 年 11 月 22 日列出的 13 张标准地图，适用于本功能的 5v5 爆破内战。下拉菜单和选图结果会同时显示英文名和国际服官方繁中名。 [英文地图列表](https://playvalorant.com/en-us/maps/) [繁中地图列表](https://playvalorant.com/zh-tw/maps/)

场次编号、活动状态、被动库、抽取结果和所选地图按服务器保存在 SQLite 中。机器人重启后，原公告和分队通知上的按钮仍可使用。

---

## 🗄️ 数据库结构

```sql
-- 陪玩记录
companions (guild_id, nickname, gift_name, category,
            total_added_hours, reported_hours, settled_hours, discord_user_id)

-- Discord 账号绑定（独立于陪玩记录，绑定先于录入也生效）
bindings (guild_id, nickname, discord_user_id, discord_user_name, created_at)

-- 服务器配置
guild_settings (guild_id, bot_nickname, webhook_url, display_name, avatar_url,
                log_channel_id, allowed_channel_id, monitor_channel_id,
                staff_role_id, welcome_channel_id, leave_channel_id)

-- 操作历史
history (id, guild_id, nickname, action_type, details,
         operator_id, operator_name, created_at)
```

---

## 🔒 安全说明

以下文件已加入 `.gitignore`，**不会**上传到 GitHub：

- `config.py` — Bot Token 和服务器 ID
- `ledger.db` — 用户数据
- `*.log` — 运行日志
- `.env` — 环境变量

---

## 📄 License

MIT License © prprtracy
