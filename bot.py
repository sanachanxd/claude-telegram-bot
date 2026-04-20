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

def auth_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in config.allowed_user_ids:
            return
        return await func(update, context)
    return wrapper

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
