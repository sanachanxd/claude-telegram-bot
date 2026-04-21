import json
import uuid
import tempfile
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger(__name__)

SESSIONS_FILE = Path(__file__).parent / "sessions.json"
STATE_FILE = Path(__file__).parent / "state.json"


def _atomic_write(path: Path, data: str):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, "w") as f:
            f.write(data)
        Path(tmp).replace(path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _safe_load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"文件损坏，重置: {path} ({e})")
        backup = path.with_suffix(".json.bak")
        try:
            path.rename(backup)
            logger.info(f"已备份损坏文件到: {backup}")
        except OSError:
            pass
        return {}

@dataclass
class Session:
    session_id: str
    project_path: str
    name: str
    created_at: str
    last_active: str
    permission_mode: str = "acceptEdits"
    model: str = "claude-sonnet-4-6"

class SessionManager:
    def __init__(self, default_cwd: str, default_mode: str, default_model: str = "claude-sonnet-4-6"):
        self.default_cwd = default_cwd
        self.default_mode = default_mode
        self.default_model = default_model
        self.current_cwd: str = default_cwd
        self.current_session: Session | None = None
        self._sessions: dict[str, Session] = {}
        self._load()
        self._load_state()

    def _load(self):
        raw = _safe_load_json(SESSIONS_FILE)
        for sid, data in raw.items():
            try:
                self._sessions[sid] = Session(**data)
            except (TypeError, KeyError):
                logger.warning(f"跳过损坏的会话: {sid}")

    def _save(self):
        raw = {sid: asdict(s) for sid, s in self._sessions.items()}
        _atomic_write(SESSIONS_FILE, json.dumps(raw, indent=2, ensure_ascii=False))
        self._save_state()

    def _load_state(self):
        state = _safe_load_json(STATE_FILE)
        self.current_cwd = state.get("current_cwd", self.default_cwd)
        sid = state.get("current_session_id")
        if sid and sid in self._sessions:
            self.current_session = self._sessions[sid]

    def _save_state(self):
        state = {
            "current_cwd": self.current_cwd,
            "current_session_id": self.current_session.session_id if self.current_session else None,
        }
        _atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False))

    def new_session(self, name: str | None = None, model: str | None = None) -> Session:
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
            model=model or self.default_model,
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
        self._save_state()

    def set_mode(self, mode: str):
        if self.current_session:
            self.current_session.permission_mode = mode
            self._save()

    def set_model(self, model: str):
        if self.current_session:
            self.current_session.model = model
            self._save()
