# Telegram Claude Code Bot — Design Spec

## Overview

一个 Telegram Bot，让用户通过手机远程操控 Mac 上的 Claude Code CLI。支持项目管理、session 管理、权限切换，与终端共享 session 存储实现手机/电脑无缝切换。

## Architecture

```
手机 Telegram → Telegram Bot API (外网)
                    ↓ (通过 127.0.0.1:10808 代理)
              Bot 进程 (Mac 本地 Python)
                    ↓ (subprocess)
              claude -p --session-id <uuid> --output-format stream-json
                    ↓
              ~/.claude/ (MCP, Skill, CLAUDE.md, session JSONL)
```

单进程 Python 应用，通过本地代理连接 Telegram API，subprocess 调用 claude CLI。

## Project Structure

```
~/claude-telegram-bot/
├── bot.py              # 主程序入口
├── config.py           # 配置管理
├── session_manager.py  # session 和项目管理
├── claude_runner.py    # 封装 claude -p 调用
├── message_handler.py  # Telegram 消息处理和分段发送
├── config.yaml         # 用户配置文件
├── manage.py           # launchd install/uninstall 管理脚本
└── logs/               # 日志目录
```

## Security

### 身份验证
- Telegram user ID 白名单，硬编码在 config.yaml
- 非白名单消息静默丢弃，不回复不报错

### 权限模式
可通过 `/mode` 命令切换，与终端 Claude Code 一致：
- `plan` — 只读，最安全
- `acceptEdits` — 可编辑文件，bash 需确认（**默认**）
- `bypassPermissions` — 全权限

### 路径安全
新建项目路径黑名单：`/usr`, `/etc`, `/System`, `/Library`, `/bin`, `/sbin`

### Token 存储
- 支持环境变量 `TELEGRAM_BOT_TOKEN`（优先）和 config.yaml
- config.yaml 文件权限设为 600

### 进程安全
- 以当前用户身份运行，不需要 sudo
- 继承用户文件权限

## Commands

### 项目管理
| 命令 | 说明 |
|------|------|
| `/projects` | 列出已注册的项目目录 |
| `/switch <name>` | 切换当前项目 |
| `/mkdir <path> [name]` | 新建项目目录并切换 |
| `/pwd` | 显示当前工作目录 |

### Session 管理
| 命令 | 说明 |
|------|------|
| `/sessions` | 列出当前项目的 session |
| `/resume <id或关键词>` | 恢复指定 session |
| `/continue` | 继续当前项目最近的 session |
| `/fresh` | 开一个新 session |
| `/name <名字>` | 给当前 session 命名 |

### 权限控制
| 命令 | 说明 |
|------|------|
| `/mode` | 查看当前权限模式 |
| `/mode <模式>` | 切换权限模式 |

### 系统管理
| 命令 | 说明 |
|------|------|
| `/status` | 查看 bot 状态（项目、session、权限、网络连接） |
| `/cancel` | 中断正在执行的 claude 进程 |
| `/help` | 命令列表 |

### 普通消息
直接作为 prompt 发给当前 session 的 claude。

## Message Output

### 发送流程
1. 收到消息 → 发 "🤔 thinking..." + typing 状态
2. subprocess 调用 `claude -p --output-format stream-json` 流式读取
3. 完成后按 4000 字符智能分段（在段落/代码块边界切割）
4. 逐条发送，Markdown 格式

### 超时与中断
- 单次调用默认 5 分钟超时，超时自动 kill 并通知
- `/cancel` 直接 kill subprocess

## Session Storage

### 共享存储
Bot 和终端共享 `~/.claude/projects/` 下的 session JSONL 文件。Bot 创建的 session 使用 `--name "tg: <项目名>"` 前缀标识来源。

### 无缝切换
- 手机上聊的 session，电脑终端 `/resume` 可以继续
- 终端里的 session，手机 `/resume` 也能接上
- 上下文、MCP、CLAUDE.md 配置全部共享

## Network

### 代理配置
Bot 进程通过 `127.0.0.1:10808` 代理连接 Telegram API。在 config.yaml 中配置：
```yaml
proxy:
  host: "127.0.0.1"
  port: 10808
  type: "http"
```

### 网络检测
`/status` 命令检测代理连通性（ping Telegram API）。

## Process Management

### 手动启动
```bash
cd ~/claude-telegram-bot && python3 bot.py
```

### launchd 守护进程
```bash
python3 manage.py install    # 安装开机自启
python3 manage.py uninstall  # 卸载
python3 manage.py start      # 启动
python3 manage.py stop       # 停止
python3 manage.py restart    # 重启
```

日志输出到 `~/claude-telegram-bot/logs/`。

## Config File (config.yaml)

```yaml
telegram:
  bot_token: ""  # 或用环境变量 TELEGRAM_BOT_TOKEN
  allowed_user_ids:
    - 123456789  # 你的 Telegram user ID

proxy:
  host: "127.0.0.1"
  port: 10808
  type: "http"

claude:
  default_mode: "acceptEdits"
  timeout: 300  # 秒
  default_cwd: "~"

projects:
  path_blacklist:
    - "/usr"
    - "/etc"
    - "/System"
    - "/Library"
    - "/bin"
    - "/sbin"
```

## Dependencies

- Python 3.13+
- `python-telegram-bot` — Telegram Bot API
- `pyyaml` — 配置文件解析
- Claude Code CLI (`claude`) — 已安装
