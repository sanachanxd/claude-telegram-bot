import json
import uuid
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime

SESSIONS_FILE = Path(__file__).parent / "sessions.json"
STATE_FILE = Path(__file__).parent / "state.json"

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
        if SESSIONS_FILE.exists():
            raw = json.loads(SESSIONS_FILE.read_text())
            for sid, data in raw.items():
                self._sessions[sid] = Session(**data)

    def _save(self):
        raw = {sid: asdict(s) for sid, s in self._sessions.items()}
        SESSIONS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False))
        self._save_state()

    def _load_state(self):
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text())
            self.current_cwd = state.get("current_cwd", self.default_cwd)
            sid = state.get("current_session_id")
            if sid and sid in self._sessions:
                self.current_session = self._sessions[sid]

    def _save_state(self):
        state = {
            "current_cwd": self.current_cwd,
            "current_session_id": self.current_session.session_id if self.current_session else None,
        }
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))

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
