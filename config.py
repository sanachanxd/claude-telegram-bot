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
        path_blacklist=projects_cfg.get("path_blacklist", ["/usr", "/etc", "/System", "/Library", "/bin", "/sbin"]),
    )
