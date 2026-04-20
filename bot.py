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
sm = SessionManager(default_cwd=config.default_cwd, default_mode=config.default_mode, default_model=config.default_model)

def auth_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in config.allowed_user_ids:
            return
        return await func(update, context)
    return wrapper

@auth_required
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*项目管理*\n"
        "/projects - 列出所有项目\n"
        "/switch <名称> - 切换项目\n"
        "/mkdir <路径> - 新建项目目录\n"
        "/pwd - 当前工作目录\n\n"
        "*会话管理*\n"
        "/sessions - 列出当前项目的会话\n"
        "/resume <ID|关键词> - 恢复会话\n"
        "/continue - 继续最近的会话\n"
        "/fresh - 新建会话\n"
        "/name <名称> - 重命名会话\n\n"
        "*控制*\n"
        "/mode [模式] - 查看/切换权限模式\n"
        "/model [模型] - 查看/切换模型\n"
        "/status - 查看状态和网络\n"
        "/cancel - 中断当前任务\n"
        "/help - 显示帮助"
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
    await update.message.reply_text("没有找到项目。")

@auth_required
async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法: /switch <路径或关键词>")
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
        await update.message.reply_text(f"目录不存在: `{target}`", parse_mode="Markdown")
        return
    sm.switch_project(str(path))
    await update.message.reply_text(f"已切换到 `{path}`", parse_mode="Markdown")

@auth_required
async def cmd_mkdir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法: /mkdir <路径>")
        return
    target = Path(context.args[0]).expanduser().resolve()
    for bl in config.path_blacklist:
        if str(target).startswith(bl):
            await update.message.reply_text(f"路径被禁止: `{bl}`", parse_mode="Markdown")
            return
    target.mkdir(parents=True, exist_ok=True)
    sm.switch_project(str(target))
    await update.message.reply_text(f"已创建并切换到 `{target}`", parse_mode="Markdown")

@auth_required
async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions = sm.list_sessions()
    if not sessions:
        await update.message.reply_text("当前项目没有会话。")
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
        await update.message.reply_text("用法: /resume <ID或关键词>")
        return
    keyword = " ".join(context.args)
    session = sm.find_session(keyword)
    if not session:
        await update.message.reply_text("未找到会话。")
        return
    sm.current_session = session
    sm.current_cwd = session.project_path
    await update.message.reply_text(
        f"已恢复 `{session.name}` ({session.session_id[:8]})",
        parse_mode="Markdown",
    )

@auth_required
async def cmd_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions = sm.list_sessions()
    if not sessions:
        await update.message.reply_text("没有可继续的会话。")
        return
    sm.current_session = sessions[0]
    await update.message.reply_text(
        f"继续会话 `{sessions[0].name}` ({sessions[0].session_id[:8]})",
        parse_mode="Markdown",
    )

@auth_required
async def cmd_fresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = sm.new_session()
    await update.message.reply_text(
        f"新建会话 `{s.name}` ({s.session_id[:8]})",
        parse_mode="Markdown",
    )

@auth_required
async def cmd_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not sm.current_session:
        await update.message.reply_text("用法: /name <新名称>（需要活跃会话）")
        return
    new_name = " ".join(context.args)
    sm.current_session.name = new_name
    sm._save()
    await update.message.reply_text(f"会话已重命名为 `{new_name}`", parse_mode="Markdown")

@auth_required
async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    valid_modes = ["plan", "acceptEdits", "bypassPermissions"]
    if not context.args:
        mode = sm.current_session.permission_mode if sm.current_session else config.default_mode
        await update.message.reply_text(f"当前模式: `{mode}`\nAvailable: {', '.join(valid_modes)}", parse_mode="Markdown")
        return
    mode = context.args[0]
    if mode not in valid_modes:
        await update.message.reply_text(f"无效模式。可用: {', '.join(valid_modes)}")
        return
    sm.set_mode(mode)
    await update.message.reply_text(f"模式已切换为 `{mode}`", parse_mode="Markdown")

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

    net_status = "在线" if net_ok else "离线"
    text = (
        f"项目: `{sm.current_cwd}`\n"
        f"会话: {session_info}\n"
        f"模式: `{mode}`\n"
        f"网络: {net_status} (proxy: {config.proxy_url})\n"
        f"Claude运行中: {'是' if runner.is_running else '否'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

@auth_required
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if runner.is_running:
        await runner.cancel()
        await update.message.reply_text("已中断。")
    else:
        await update.message.reply_text("没有正在运行的任务。")

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
        model=sm.current_session.model,
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

@auth_required
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        current = sm.current_session.model if sm.current_session else config.default_model
        lines = [f"当前模型: `{current}`\n", "可用模型:"]
        for m in config.available_models:
            marker = ">" if m["id"] == current else " "
            lines.append(f"{marker} `{m['name']}` - {m['desc']}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return
    target = context.args[0].lower()
    for m in config.available_models:
        if target == m["name"] or target == m["id"]:
            if sm.current_session:
                sm.current_session.model = m["id"]
                sm._save()
            await update.message.reply_text(f"模型已切换为 `{m['name']}` ({m['desc']})", parse_mode="Markdown")
            return
    names = ", ".join(m["name"] for m in config.available_models)
    await update.message.reply_text(f"未知模型。可用: {names}")

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
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
