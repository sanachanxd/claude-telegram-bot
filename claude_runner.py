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
        model: str | None = None,
        resume: bool = False,
        continue_last: bool = False,
    ) -> RunResult:
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", permission_mode,
        ]

        if model:
            cmd.extend(["--model", model])

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
