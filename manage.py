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
