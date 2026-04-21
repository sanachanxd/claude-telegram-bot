import sys
import os
import subprocess
import getpass
from pathlib import Path

PLIST_NAME = "com.claude-telegram-bot.plist"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
BOT_DIR = Path(__file__).parent.resolve()
PYTHON = sys.executable
LOG_DIR = BOT_DIR / "logs"
ENV_FILE = BOT_DIR / ".env"


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


def load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def save_env(env: dict):
    lines = [f'{k}="{v}"' for k, v in env.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)


def is_running() -> bool:
    r = subprocess.run(
        ["launchctl", "list"], capture_output=True, text=True
    )
    return PLIST_NAME.replace(".plist", "") in r.stdout


def install():
    LOG_DIR.mkdir(exist_ok=True)
    PLIST_PATH.write_text(get_plist_content())
    subprocess.run(["launchctl", "load", str(PLIST_PATH)])
    print("✅ 已安装并加载服务")


def uninstall():
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)])
        PLIST_PATH.unlink()
        print("✅ 已卸载服务")
    else:
        print("⚠️  服务未安装")


def start():
    if not PLIST_PATH.exists():
        install()
    subprocess.run(["launchctl", "start", PLIST_NAME.replace(".plist", "")])
    print("✅ Bot 已启动")


def stop():
    subprocess.run(["launchctl", "stop", PLIST_NAME.replace(".plist", "")])
    print("✅ Bot 已停止")


def restart():
    stop()
    start()
    print("✅ Bot 已重启")


def status():
    if is_running():
        print("🟢 Bot 运行中")
    else:
        print("🔴 Bot 未运行")
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        print(f"🔑 Token: {token[:10]}...{token[-4:]}")
    else:
        print("🔑 Token: 未配置（将从 config.yaml 读取）")
    print(f"📁 项目目录: {BOT_DIR}")
    print(f"📋 日志目录: {LOG_DIR}")


def config_token():
    env = load_env()
    current = env.get("TELEGRAM_BOT_TOKEN", "")
    if current:
        print(f"当前 Token: {current[:10]}...{current[-4:]}")
    token = input("输入新 Token（留空跳过）: ").strip()
    if token:
        env["TELEGRAM_BOT_TOKEN"] = token
        save_env(env)
        print("✅ Token 已保存到 .env")
        if is_running():
            ans = input("Bot 正在运行，是否重启以生效？[Y/n] ").strip().lower()
            if ans != "n":
                restart()


def show_logs():
    log_file = LOG_DIR / "stderr.log"
    if not log_file.exists():
        log_file = LOG_DIR / "bot.log"
    if log_file.exists():
        subprocess.run(["tail", "-30", str(log_file)])
    else:
        print("暂无日志")


def clean_git_history():
    ans = input("⚠️  将清除 git 中残留的原始引用和 reflog，确认？[y/N] ").strip().lower()
    if ans != "y":
        return
    subprocess.run(
        "git for-each-ref --format='delete %(refname)' refs/original | git update-ref --stdin",
        shell=True, cwd=BOT_DIR
    )
    subprocess.run(
        ["git", "reflog", "expire", "--expire=now", "--all"], cwd=BOT_DIR
    )
    subprocess.run(
        ["git", "gc", "--prune=now", "--aggressive"], cwd=BOT_DIR
    )
    print("✅ Git 历史已清理")


MENU = """
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
╰─────────────────────────╯"""


def interactive():
    actions = {
        "1": start,
        "2": stop,
        "3": restart,
        "4": status,
        "5": config_token,
        "6": show_logs,
        "7": clean_git_history,
    }
    while True:
        print(MENU)
        choice = input("\n选择操作: ").strip()
        if choice == "0":
            break
        action = actions.get(choice)
        if action:
            print()
            action()
        else:
            print("无效选项")
        print()


if __name__ == "__main__":
    cmds = {
        "install": install, "uninstall": uninstall,
        "start": start, "stop": stop, "restart": restart,
        "status": status, "config": config_token,
    }
    if len(sys.argv) < 2:
        interactive()
    elif sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print(f"用法: python manage.py [{'|'.join(cmds)}]")
        print("       python manage.py        (交互式菜单)")
        sys.exit(1)
