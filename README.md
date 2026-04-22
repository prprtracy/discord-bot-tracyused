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
> 管理员使用 `/结算` 进行结算，显示剩余与待结算时长

![结算截图](docs/screenshots/settle.png)

> 💡 **添加截图方法**：将截图放入 `docs/screenshots/` 目录，文件名对应上方路径即可自动显示。

---

## ✨ 功能一览

| 功能 | 说明 |
|------|------|
| 📋 **添加陪玩** | 管理员录入陪玩昵称、礼物名、分类、时长 |
| 📝 **报单** | 用户为指定陪玩报告消耗时长 |
| 🔍 **查询剩余时长** | 用户查询自己绑定账号下的剩余时长 |
| 💰 **结算** | 管理员对指定陪玩进行结算，显示待结算金额 |
| 🔗 **绑定账号** | 将 Discord 用户与陪玩昵称绑定，无需每次输入 |
| 🖼️ **自动欢迎图** | 成员加入时生成带头像的欢迎卡片并发送到欢迎频道 |
| 🚪 **离开通知** | 成员退出时在指定频道发送离开通知 |
| 🎙️ **语音监听** | 自动记录成员进出语音频道 |
| 🏢 **多服务器隔离** | 所有数据按 `guild_id` 完全隔离，互不干扰 |
| ⚙️ **频道配置** | 可独立配置日志频道、监听频道、欢迎频道、离开频道 |

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
pip install discord.py aiohttp Pillow
```

### 3. 创建配置文件

新建 `config.py`（此文件不会被上传到 GitHub）：

```python
TOKEN = "你的 Bot Token"
GUILD_ID = 你的服务器ID  # 整数
```

### 4. 启动 Bot

```bash
python3 main.py
```

---

## 🤖 Slash Commands

### 陪玩管理（`cogs/ledger.py`）

| 命令 | 权限 | 说明 |
|------|------|------|
| `/添加陪玩` | 管理员 | 录入陪玩信息和初始时长 |
| `/报单` | 所有人 | 为指定陪玩报告消耗时长 |
| `/查询我的剩余时长` | 所有人 | 查询自己绑定昵称的剩余时长 |
| `/查询结算` | 管理员 | 查看指定陪玩的结算详情 |
| `/结算` | 管理员 | 对指定陪玩进行结算 |
| `/绑定账号` | 所有人 | 将 Discord 账号与陪玩昵称绑定 |
| `/查看所有陪玩` | 管理员 | 列出本服务器所有陪玩记录 |

### 服务器配置（`cogs/guild_config.py`）

| 命令 | 权限 | 说明 |
|------|------|------|
| `/设置服务器显示` | 管理员 | 配置 Bot 昵称、Webhook、显示名称、头像 |
| `/查看服务器显示` | 管理员 | 查看当前显示配置 |
| `/设置日志频道` | 管理员 | 设置业务日志频道 |
| `/设置监听频道` | 管理员 | 设置语音/成员监听频道 |
| `/设置欢迎频道` | 管理员 | 设置新成员欢迎图发送频道 |
| `/设置离开频道` | 管理员 | 设置成员离开通知频道 |
| `/查看日志频道` | 管理员 | 查看当前各频道配置 |

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
                welcome_channel_id, leave_channel_id)

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
