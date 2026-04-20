# Telegram Claude Code Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram bot that lets the user remotely control Claude Code CLI from their phone, with project/session management and shared session storage.

**Architecture:** Single Python process using `python-telegram-bot` (async), connecting to Telegram API via HTTP proxy (`127.0.0.1:10808`). Calls `claude -p --output-format stream-json --verbose` via asyncio subprocess. Sessions stored in `~/.claude/projects/` shared with terminal Claude Code.

**Tech Stack:** Python 3.13, python-telegram-bot, pyyaml, asyncio subprocess

---

### Task 1: Project scaffold and config

**Files:**
- Create: `~/claude-telegram-bot/config.py`
- Create: `~/claude-telegram-bot/config.yaml`
- Create: `~/claude-telegram-bot/requirements.txt`

- [ ] **Step 1: Create requirements.txt**

```
python-telegram-bot>=21.0
pyyaml>=6.0
```

- [ ] **Step 2: Install dependencies**

Run: `cd ~/claude-telegram-bot && pip3 install -r requirements.txt`
Expected: Successfully installed packages

- [ ] **Step 3: Create config.yaml template**

```yaml
telegram:
  bot_token: ""
  allowed_user_ids: []

proxy:
  host: "127.0.0.1"
  port: 10808
  type: "http"

claude:
  default_mode: "acceptEdits"
  timeout: 300
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

- [ ] **Step 4: Create config.py**

```python
import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_PATH = Path(__file__).parent / "config.yaml"

@dataclass
class Config:
    bot_token: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)
    proxy_url: str = ""
    default_mode: str = "acceptEdits"
    timeout: int = 300
    default_cwd: str = str(Path.home())
    path_blacklist: list[str] = field(default_factory=lambda: [
        "/usr", "/etc", "/System", "/Library", "/bin", "/sbin"
    ])

def load_config() -> Config:
    with open(CONFIG_PATH) as f:
        raw = yaml.safe_load(f)

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or raw.get("telegram", {}).get("bot_token", "")
    user_ids = raw.get("telegram", {}).get("allowed_user_ids", [])

    proxy_cfg = raw.get("proxy", {})
    proxy_host = proxy_cfg.get("host", "127.0.0.1")
    proxy_port = proxy_cfg.get("port", 10808)
    proxy_type = proxy_cfg.get("type", "http")
    proxy_url = f"{proxy_type}://{proxy_host}:{proxy_port}"

    claude_cfg = raw.get("claude", {})
    default_cwd = claude_cfg.get("default_cwd", "~")
    if default_cwd == "~":
        default_cwd = str(Path.home())

    projects_cfg = raw.get("projects", {})

    return Config(
        bot_token=token,
        allowed_user_ids=user_ids,
        proxy_url=proxy_url,
        default_mode=claude_cfg.get("default_mode", "acceptEdits"),
        timeout=claude_cfg.get("timeout", 300),
        default_cwd=default_cwd,
        path_blacklist=projects_cfg.get("path_blacklist", Config.path_blacklist),
    )
```

- [ ] **Step 5: Set config.yaml permissions**

Run: `chmod 600 ~/claude-telegram-bot/config.yaml`

- [ ] **Step 6: Commit**

```bash
cd ~/claude-telegram-bot && git init && git add config.py config.yaml requirements.txt
git commit -m "feat: project scaffold with config management"
```

---

### Task 2: Claude CLI runner

**Files:**
- Create: `~/claude-telegram-bot/claude_runner.py`

- [ ] **Step 1: Create claude_runner.py**

```python
import asyncio
import json
import uuid
import signal
from pathlib import Path
from dataclasses import dataclass

@dataclass
class RunResult:
    text: str
    session_id: str
    cost_usd: float
    error: str | None = None

class ClaudeRunner:
    def __init__(self, timeout: int = 300):
        self.timeout = timeout
        self._process: asyncio.subprocess.Process | None = None

    async def run(
        self,
        prompt: str,
        cwd: str,
        session_id: str | None = None,
        session_name: str | None = None,
        permission_mode: str = "acceptEdits",
        resume: bool = False,
        continue_last: bool = False,
    ) -> RunResult:
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", permission_mode,
        ]

        if session_id and not continue_last and not resume:
            cmd.extend(["--session-id", session_id])
        if continue_last:
            cmd.append("--continue")
        if resume and session_id:
            cmd.extend(["--resume", session_id])
        if session_name:
            cmd.extend(["--name", session_name])

        cmd.append(prompt)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            text_parts = []
            final_session_id = session_id or ""
            cost = 0.0

            async def read_stream():
                nonlocal final_session_id, cost
                while True:
                    line = await self._process.stdout.readline()
                    if not line:
                        break
                    try:
                        data = json.loads(line.decode().strip())
                    except json.JSONDecodeError:
                        continue

                    if data.get("type") == "assistant":
                        msg = data.get("message", {})
                        for block in msg.get("content", []):
                            if block.get("type") == "text":
                                text_parts.append(block["text"])
                        sid = data.get("session_id")
                        if sid:
                            final_session_id = sid

                    elif data.get("type") == "result":
                        if data.get("result"):
                            text_parts.append(data["result"])
                        final_session_id = data.get("session_id", final_session_id)
                        cost = data.get("total_cost_usd", 0.0)

            await asyncio.wait_for(read_stream(), timeout=self.timeout)
            await self._process.wait()

            return RunResult(
                text=text_parts[-1] if text_parts else "(no response)",
                session_id=final_session_id,
                cost_usd=cost,
            )

        except asyncio.TimeoutError:
            await self.cancel()
            return RunResult(text="", session_id=session_id or "", cost_usd=0, error="timeout")
        except Exception as e:
            return RunResult(text="", session_id=session_id or "", cost_usd=0, error=str(e))
        finally:
            self._process = None

    async def cancel(self):
        if self._process and self._process.returncode is None:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @staticmethod
    def new_session_id() -> str:
        return str(uuid.uuid4())
```

- [ ] **Step 2: Commit**

```bash
cd ~/claude-telegram-bot && git add claude_runner.py
git commit -m "feat: claude CLI subprocess runner with stream-json parsing"
```

---

### Task 3: Session manager

**Files:**
- Create: `~/claude-telegram-bot/session_manager.py`

- [ ] **Step 1: Create session_manager.py**

```python
import json
import uuid
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime

SESSIONS_FILE = Path(__file__).parent / "sessions.json"

@dataclass
class Session:
    session_id: str
    project_path: str
    name: str
    created_at: str
    last_active: str
    permission_mode: str = "acceptEdits"

class SessionManager:
    def __init__(self, default_cwd: str, default_mode: str):
        self.default_cwd = default_cwd
        self.default_mode = default_mode
        self.current_cwd: str = default_cwd
        self.current_session: Session | None = None
        self._sessions: dict[str, Session] = {}
        self._load()

    def _load(self):
        if SESSIONS_FILE.exists():
            raw = json.loads(SESSIONS_FILE.read_text())
            for sid, data in raw.items():
                self._sessions[sid] = Session(**data)

    def _save(self):
        raw = {sid: asdict(s) for sid, s in self._sessions.items()}
        SESSIONS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False))

    def new_session(self, name: str | None = None) -> Session:
        sid = str(uuid.uuid4())
        now = datetime.now().isoformat()
        project_name = Path(self.current_cwd).name or "home"
        session_name = name or f"tg: {project_name}"
        s = Session(
            session_id=sid,
            project_path=self.current_cwd,
            name=session_name,
            created_at=now,
            last_active=now,
            permission_mode=self.default_mode,
        )
        self._sessions[sid] = s
        self.current_session = s
        self._save()
        return s

    def touch_session(self, session_id: str):
        if session_id in self._sessions:
            self._sessions[session_id].last_active = datetime.now().isoformat()
            self._save()

    def update_session_id(self, old_id: str, new_id: str):
        if old_id in self._sessions:
            s = self._sessions.pop(old_id)
            s.session_id = new_id
            self._sessions[new_id] = s
            if self.current_session and self.current_session.session_id == old_id:
                self.current_session = s
            self._save()

    def list_sessions(self, project_path: str | None = None) -> list[Session]:
        path = project_path or self.current_cwd
        sessions = [s for s in self._sessions.values() if s.project_path == path]
        return sorted(sessions, key=lambda s: s.last_active, reverse=True)

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def find_session(self, keyword: str) -> Session | None:
        for s in self._sessions.values():
            if keyword in s.session_id or keyword.lower() in s.name.lower():
                return s
        return None

    def switch_project(self, path: str):
        self.current_cwd = path
        self.current_session = None

    def set_mode(self, mode: str):
        if self.current_session:
            self.current_session.permission_mode = mode
            self._save()
```

- [ ] **Step 2: Commit**

```bash
cd ~/claude-telegram-bot && git add session_manager.py
git commit -m "feat: session manager with shared storage support"
```

---

### Task 4: Message handler (smart splitting)

**Files:**
- Create: `~/claude-telegram-bot/message_handler.py`

- [ ] **Step 1: Create message_handler.py**

```python
import re
from telegram import Update
from telegram.constants import ParseMode, ChatAction

MAX_MSG_LEN = 4000

def smart_split(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= MAX_MSG_LEN:
            chunks.append(remaining)
            break

        split_at = MAX_MSG_LEN
        # try to split at code block boundary
        code_fence = remaining.rfind("\n```\n", 0, split_at)
        if code_fence > MAX_MSG_LEN // 2:
            split_at = code_fence + 4
        else:
            # try paragraph boundary
            para = remaining.rfind("\n\n", 0, split_at)
            if para > MAX_MSG_LEN // 2:
                split_at = para + 1
            else:
                # try line boundary
                line = remaining.rfind("\n", 0, split_at)
                if line > MAX_MSG_LEN // 2:
                    split_at = line + 1

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    return chunks

def escape_markdown_v2(text: str) -> str:
    # Telegram MarkdownV2 requires escaping special chars outside code blocks
    # Simpler approach: just use regular Markdown mode which is more forgiving
    return text

async def send_thinking(update: Update):
    msg = await update.message.reply_text(
        "thinking...",
        parse_mode=None,
    )
    await update.message.chat.send_action(ChatAction.TYPING)
    return msg

async def send_response(update: Update, text: str, thinking_msg=None):
    if thinking_msg:
        try:
            await thinking_msg.delete()
        except Exception:
            pass

    chunks = smart_split(text)
    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk, parse_mode=None)

async def send_error(update: Update, error: str, thinking_msg=None):
    if thinking_msg:
        try:
            await thinking_msg.delete()
        except Exception:
            pass
    await update.message.reply_text(f"Error: {error}")
```

- [ ] **Step 2: Commit**

```bash
cd ~/claude-telegram-bot && git add message_handler.py
git commit -m "feat: smart message splitting for Telegram 4096 char limit"
```

---

### Task 5: Bot main with all command handlers

**Files:**
- Create: `~/claude-telegram-bot/bot.py`

- [ ] **Step 1: Create bot.py**

```python
import asyncio
import logging
import os
import subprocess
from pathlib import Path

from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import load_config
from claude_runner import ClaudeRunner
from session_manager import SessionManager
from message_handler import send_thinking, send_response, send_error, smart_split

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(Path(__file__).parent / "logs" / "bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

config = load_config()
runner = ClaudeRunner(timeout=config.timeout)
sm = SessionManager(default_cwd=config.default_cwd, default_mode=config.default_mode)

# --- auth decorator ---
def auth_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in config.allowed_user_ids:
            return  # silent ignore
        return await func(update, context)
    return wrapper

# --- command handlers ---
@auth_required
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Project*\n"
        "/projects - list projects\n"
        "/switch <name> - switch project\n"
        "/mkdir <path> [name] - create project dir\n"
        "/pwd - current directory\n\n"
        "*Session*\n"
        "/sessions - list sessions\n"
        "/resume <id|keyword> - resume session\n"
        "/continue - continue last session\n"
        "/fresh - new session\n"
        "/name <name> - rename session\n\n"
        "*Control*\n"
        "/mode [mode] - view/set permission mode\n"
        "/status - bot status + network\n"
        "/cancel - abort running command\n"
        "/help - this message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

@auth_required
async def cmd_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"`{sm.current_cwd}`", parse_mode="Markdown")

@auth_required
async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # read known projects from ~/.claude.json
    import json
    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        data = json.loads(claude_json.read_text())
        projects = list(data.get("projects", {}).keys())
        if projects:
            lines = [f"{'> ' if p == sm.current_cwd else '  '}`{p}`" for p in projects]
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
            return
    await update.message.reply_text("No projects found.")

@auth_required
async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /switch <path or keyword>")
        return
    target = " ".join(context.args)
    path = Path(target).expanduser().resolve()
    if not path.is_dir():
        # try fuzzy match from known projects
        import json
        claude_json = Path.home() / ".claude.json"
        if claude_json.exists():
            data = json.loads(claude_json.read_text())
            for p in data.get("projects", {}).keys():
                if target.lower() in p.lower():
                    path = Path(p)
                    break
    if not path.is_dir():
        await update.message.reply_text(f"Directory not found: `{target}`", parse_mode="Markdown")
        return
    sm.switch_project(str(path))
    await update.message.reply_text(f"Switched to `{path}`", parse_mode="Markdown")

@auth_required
async def cmd_mkdir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /mkdir <path>")
        return
    target = Path(context.args[0]).expanduser().resolve()
    for bl in config.path_blacklist:
        if str(target).startswith(bl):
            await update.message.reply_text(f"Blocked path: `{bl}`", parse_mode="Markdown")
            return
    target.mkdir(parents=True, exist_ok=True)
    sm.switch_project(str(target))
    await update.message.reply_text(f"Created and switched to `{target}`", parse_mode="Markdown")

@auth_required
async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions = sm.list_sessions()
    if not sessions:
        await update.message.reply_text("No sessions for this project.")
        return
    lines = []
    for s in sessions[:15]:
        marker = "> " if sm.current_session and s.session_id == sm.current_session.session_id else "  "
        short_id = s.session_id[:8]
        lines.append(f"{marker}`{short_id}` {s.name} ({s.last_active[:10]})")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@auth_required
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /resume <id or keyword>")
        return
    keyword = " ".join(context.args)
    session = sm.find_session(keyword)
    if not session:
        await update.message.reply_text("Session not found.")
        return
    sm.current_session = session
    sm.current_cwd = session.project_path
    await update.message.reply_text(
        f"Resumed `{session.name}` ({session.session_id[:8]})",
        parse_mode="Markdown",
    )

@auth_required
async def cmd_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions = sm.list_sessions()
    if not sessions:
        await update.message.reply_text("No sessions to continue.")
        return
    sm.current_session = sessions[0]
    await update.message.reply_text(
        f"Continuing `{sessions[0].name}` ({sessions[0].session_id[:8]})",
        parse_mode="Markdown",
    )

@auth_required
async def cmd_fresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sm.new_session()
    await update.message.reply_text(
        f"New session `{s.name}` ({s.session_id[:8]})",
        parse_mode="Markdown",
    )

@auth_required
async def cmd_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not sm.current_session:
        await update.message.reply_text("Usage: /name <new name> (need active session)")
        return
    new_name = " ".join(context.args)
    sm.current_session.name = new_name
    sm._save()
    await update.message.reply_text(f"Session renamed to `{new_name}`", parse_mode="Markdown")

@auth_required
async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    valid_modes = ["plan", "acceptEdits", "bypassPermissions"]
    if not context.args:
        mode = sm.current_session.permission_mode if sm.current_session else config.default_mode
        await update.message.reply_text(f"Current mode: `{mode}`\nAvailable: {', '.join(valid_modes)}", parse_mode="Markdown")
        return
    mode = context.args[0]
    if mode not in valid_modes:
        await update.message.reply_text(f"Invalid mode. Available: {', '.join(valid_modes)}")
        return
    sm.set_mode(mode)
    await update.message.reply_text(f"Mode set to `{mode}`", parse_mode="Markdown")

@auth_required
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = sm.current_session.permission_mode if sm.current_session else config.default_mode
    session_info = f"{sm.current_session.name} ({sm.current_session.session_id[:8]})" if sm.current_session else "none"

    # network check
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
            "--proxy", config.proxy_url,
            "--max-time", "5",
            "https://api.telegram.org",
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        net_ok = stdout.decode().strip() in ("200", "404", "301", "302")
    except Exception:
        net_ok = False

    net_status = "online" if net_ok else "offline"
    text = (
        f"Project: `{sm.current_cwd}`\n"
        f"Session: {session_info}\n"
        f"Mode: `{mode}`\n"
        f"Network: {net_status} (proxy: {config.proxy_url})\n"
        f"Claude running: {'yes' if runner.is_running else 'no'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

@auth_required
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if runner.is_running:
        await runner.cancel()
        await update.message.reply_text("Cancelled.")
    else:
        await update.message.reply_text("Nothing running.")

# --- message handler (send to claude) ---
@auth_required
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text
    if not prompt:
        return

    if not sm.current_session:
        sm.new_session()

    thinking_msg = await send_thinking(update)

    result = await runner.run(
        prompt=prompt,
        cwd=sm.current_cwd,
        session_id=sm.current_session.session_id,
        session_name=sm.current_session.name,
        permission_mode=sm.current_session.permission_mode,
    )

    if result.session_id != sm.current_session.session_id:
        sm.update_session_id(sm.current_session.session_id, result.session_id)
    sm.touch_session(result.session_id)

    if result.error:
        if result.error == "timeout":
            await send_error(update, f"Timeout ({config.timeout}s)", thinking_msg)
        else:
            await send_error(update, result.error, thinking_msg)
    else:
        await send_response(update, result.text, thinking_msg)

# --- main ---
def main():
    (Path(__file__).parent / "logs").mkdir(exist_ok=True)

    app = (
        ApplicationBuilder()
        .token(config.bot_token)
        .proxy(config.proxy_url)
        .get_updates_proxy(config.proxy_url)
        .build()
    )

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("pwd", cmd_pwd))
    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("mkdir", cmd_mkdir))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("continue", cmd_continue))
    app.add_handler(CommandHandler("fresh", cmd_fresh))
    app.add_handler(CommandHandler("name", cmd_name))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
cd ~/claude-telegram-bot && git add bot.py
git commit -m "feat: main bot with all command handlers"
```

---

### Task 6: Process manager (launchd)

**Files:**
- Create: `~/claude-telegram-bot/manage.py`

- [ ] **Step 1: Create manage.py**

```python
import sys
import os
import subprocess
from pathlib import Path

PLIST_NAME = "com.claude-telegram-bot.plist"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
BOT_DIR = Path(__file__).parent.resolve()
PYTHON = sys.executable
LOG_DIR = BOT_DIR / "logs"

def get_plist_content() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_NAME.replace('.plist', '')}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>{BOT_DIR / 'bot.py'}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{BOT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_DIR / 'stdout.log'}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_DIR / 'stderr.log'}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{Path.home() / '.local' / 'bin'}</string>
    </dict>
</dict>
</plist>"""

def install():
    LOG_DIR.mkdir(exist_ok=True)
    PLIST_PATH.write_text(get_plist_content())
    subprocess.run(["launchctl", "load", str(PLIST_PATH)])
    print(f"Installed and loaded: {PLIST_PATH}")

def uninstall():
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)])
        PLIST_PATH.unlink()
        print("Uninstalled.")
    else:
        print("Not installed.")

def start():
    subprocess.run(["launchctl", "start", PLIST_NAME.replace(".plist", "")])
    print("Started.")

def stop():
    subprocess.run(["launchctl", "stop", PLIST_NAME.replace(".plist", "")])
    print("Stopped.")

def restart():
    stop()
    start()

if __name__ == "__main__":
    cmds = {"install": install, "uninstall": uninstall, "start": start, "stop": stop, "restart": restart}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(f"Usage: python manage.py <{'|'.join(cmds)}>")
        sys.exit(1)
    cmds[sys.argv[1]]()
```

- [ ] **Step 2: Commit**

```bash
cd ~/claude-telegram-bot && git add manage.py
git commit -m "feat: launchd process manager for install/start/stop"
```

---

### Task 7: Setup, test, and first run

- [ ] **Step 1: Fill in config.yaml with real values**

User needs to:
1. Create a Telegram bot via @BotFather, get the token
2. Get their Telegram user ID (send `/start` to @userinfobot)
3. Fill in `config.yaml`:

```yaml
telegram:
  bot_token: "YOUR_BOT_TOKEN"
  allowed_user_ids:
    - YOUR_USER_ID
```

- [ ] **Step 2: Install dependencies**

Run: `cd ~/claude-telegram-bot && pip3 install -r requirements.txt`

- [ ] **Step 3: Create logs directory and test run**

Run: `cd ~/claude-telegram-bot && mkdir -p logs && python3 bot.py`
Expected: "Bot starting..." in terminal, bot responds to `/help` in Telegram

- [ ] **Step 4: Test core flow**

In Telegram:
1. Send `/help` → should show command list
2. Send `/status` → should show project, session, network status
3. Send `hello` → should get Claude response
4. Send `/sessions` → should show the session just created
5. Send `/mode plan` → should switch to plan mode
6. Send `/cancel` while Claude is running → should abort

- [ ] **Step 5: Commit final state**

```bash
cd ~/claude-telegram-bot && git add -A
git commit -m "feat: telegram claude bot v1.0 ready"
```
