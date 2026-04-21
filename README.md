# Claude Code Telegram Bot

通过 Telegram 远程操控 Mac 上的 Claude Code CLI。支持项目管理、会话管理、模型切换，与终端 Claude Code 共享会话存储。

## 功能

- 手机远程发送 prompt 给 Claude Code
- 项目切换、新建项目目录
- 会话管理（新建/恢复/继续），与终端共享
- 权限模式切换（plan / acceptEdits / bypassPermissions）
- 模型切换（Sonnet / Opus / Haiku）
- 智能分段发送（适配 Telegram 4096 字符限制）
- launchd 守护进程，开机自启 + 崩溃重启
- 重启后自动恢复上次的项目和会话

## 安装

```bash
git clone <this-repo> ~/claude-telegram-bot
cd ~/claude-telegram-bot
pip3 install -r requirements.txt
```

## 配置与管理

运行交互式管理面板：

```bash
python3 manage.py
```

```
╭─────────────────────────╮
│   Claude Telegram Bot   │
├─────────────────────────┤
│  1. 启动 Bot            │
│  2. 停止 Bot            │
│  3. 重启 Bot            │
│  4. 查看状态            │
│  5. 配置 Token          │
│  6. 查看日志            │
│  7. 清理 Git 泄露历史   │
│  0. 退出                │
╰─────────────────────────╯
```

也支持命令行直接调用：

```bash
python3 manage.py start    # 启动
python3 manage.py stop     # 停止
python3 manage.py restart  # 重启
python3 manage.py status   # 查看状态
python3 manage.py config   # 配置 Token
python3 manage.py install  # 安装为系统服务
```

Token 存储在 `.env` 文件中（权限 600，不进版本控制），通过管理面板的「配置 Token」选项设置。

`config.yaml` 中配置其他选项：
- 你的 Telegram User ID（从 @userinfobot 获取）
- 代理地址（如需要）

## Telegram 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/projects` | 列出所有项目 |
| `/switch <名称>` | 切换项目 |
| `/mkdir <路径>` | 新建项目目录 |
| `/pwd` | 当前工作目录 |
| `/sessions` | 列出当前项目的会话 |
| `/resume <ID>` | 恢复指定会话 |
| `/continue` | 继续最近的会话 |
| `/fresh` | 新建会话 |
| `/name <名称>` | 重命名会话 |
| `/mode [模式]` | 查看/切换权限模式 |
| `/model [模型]` | 查看/切换模型 |
| `/status` | 查看状态和网络 |
| `/cancel` | 中断当前任务 |

直接发送文字消息即作为 prompt 发给 Claude。

## 前置条件

- macOS
- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) 已安装并登录
- 能访问 Telegram API 的网络（或配置代理）

## 许可

MIT
