"""Persistent PTY-backed terminal sessions for the workbench UI."""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import subprocess
import termios
import threading
import time
import tty
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any


TERMINAL_IDLE_TIMEOUT_SECONDS = 20.0
READ_CHUNK_BYTES = 4096


def _default_shell() -> str:
    shell = os.getenv("SHELL")
    if shell:
        return shell
    if os.name == "posix" and Path("/bin/zsh").exists():
        return "/bin/zsh"
    return "/bin/bash"


def _shell_argv(shell: str) -> list[str]:
    name = Path(shell).name
    if name == "zsh":
        return [shell, "-f", "-i"]
    if name == "bash":
        return [shell, "--noprofile", "--norc", "-i"]
    return [shell, "-i"]


def _window_size(cols: int, rows: int) -> bytes:
    import struct

    safe_cols = max(20, int(cols or 80))
    safe_rows = max(8, int(rows or 24))
    return struct.pack("HHHH", safe_rows, safe_cols, 0, 0)


@dataclass
class TerminalClient:
    client_id: str
    queue: Queue[dict[str, Any]] = field(default_factory=Queue)


class TerminalSession:
    def __init__(self, session_id: str, cwd: Path) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self._lock = threading.RLock()
        self._master_fd: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._clients: dict[str, TerminalClient] = {}
        self._last_detached_at: float | None = None
        self._closed = False
        self._cols = 100
        self._rows = 28

    def connect(self, client_id: str) -> TerminalClient:
        with self._lock:
            self._ensure_running_locked()
            client = TerminalClient(client_id=client_id)
            self._clients[client_id] = client
            self._last_detached_at = None
            client.queue.put({"type": "status", "status": "connected", "cwd": str(self.cwd)})
            return client

    def disconnect(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)
            if not self._clients:
                self._last_detached_at = time.monotonic()

    def read_event(self, client_id: str, timeout: float = 0.5) -> dict[str, Any] | None:
        with self._lock:
            client = self._clients.get(client_id)
            if client is None:
                return None
        try:
            return client.queue.get(timeout=timeout)
        except Empty:
            self._expire_if_idle()
            return None

    def write(self, data: str) -> None:
        encoded = data.encode("utf-8", errors="ignore")
        with self._lock:
            if self._master_fd is None or not encoded:
                return
            os.write(self._master_fd, encoded)

    def resize(self, cols: int, rows: int) -> None:
        with self._lock:
            if self._master_fd is None:
                return
            self._cols = max(20, int(cols or self._cols))
            self._rows = max(8, int(rows or self._rows))
            import fcntl

            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, _window_size(self._cols, self._rows))

    def interrupt(self) -> None:
        with self._lock:
            if self._master_fd is None:
                return
            os.write(self._master_fd, b"\x03")

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _broadcast_locked(self, event: dict[str, Any]) -> None:
        for client in self._clients.values():
            client.queue.put(event)

    def _ensure_running_locked(self) -> None:
        if self._process and self._process.poll() is None and self._master_fd is not None:
            return
        self._close_locked()
        master_fd, slave_fd = pty.openpty()
        tty.setraw(master_fd)
        shell = _default_shell()
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")
        env.setdefault("CLICOLOR", "1")
        env["PS1"] = f"{self.cwd.name} ❯ "
        env["PROMPT"] = f"{self.cwd.name} ❯ "
        env["RPROMPT"] = ""
        import fcntl

        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, _window_size(self._cols, self._rows))
        self._process = subprocess.Popen(
            _shell_argv(shell),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=self.cwd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave_fd)
        self._master_fd = master_fd
        self._closed = False
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True, name=f"terminal-{self.session_id[:8]}")
        self._reader_thread.start()

    def _read_loop(self) -> None:
        while True:
            with self._lock:
                master_fd = self._master_fd
                process = self._process
                closed = self._closed
            if closed or master_fd is None or process is None:
                return
            ready, _, _ = select.select([master_fd], [], [], 0.25)
            if not ready:
                if process.poll() is not None:
                    break
                continue
            try:
                data = os.read(master_fd, READ_CHUNK_BYTES)
            except OSError:
                break
            if not data:
                if process.poll() is not None:
                    break
                continue
            text = data.decode("utf-8", errors="replace")
            with self._lock:
                self._broadcast_locked({"type": "output", "data": text})

        exit_code = self._process.poll() if self._process is not None else 0
        with self._lock:
            self._broadcast_locked({"type": "exit", "exitCode": int(exit_code or 0)})
            self._close_locked(keep_clients=True)

    def _expire_if_idle(self) -> None:
        with self._lock:
            if self._clients or self._last_detached_at is None:
                return
            if time.monotonic() - self._last_detached_at < TERMINAL_IDLE_TIMEOUT_SECONDS:
                return
            self._close_locked()

    def _close_locked(self, *, keep_clients: bool = False) -> None:
        self._closed = True
        process = self._process
        master_fd = self._master_fd
        self._process = None
        self._master_fd = None
        self._reader_thread = None
        self._last_detached_at = None
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGHUP)
                process.wait(timeout=1.0)
            except Exception:
                process.kill()
        if not keep_clients:
            for client in self._clients.values():
                client.queue.put({"type": "status", "status": "closed"})
            self._clients.clear()


class TerminalManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, TerminalSession] = {}

    def connect(self, session_id: str, cwd: Path, client_id: str) -> TerminalClient:
        with self._lock:
            terminal = self._sessions.get(session_id)
            if terminal is None:
                terminal = TerminalSession(session_id=session_id, cwd=cwd)
                self._sessions[session_id] = terminal
            elif terminal.cwd != cwd:
                terminal.close()
                terminal = TerminalSession(session_id=session_id, cwd=cwd)
                self._sessions[session_id] = terminal
            return terminal.connect(client_id)

    def disconnect(self, session_id: str, client_id: str) -> None:
        with self._lock:
            terminal = self._sessions.get(session_id)
        if terminal is not None:
            terminal.disconnect(client_id)

    def read_event(self, session_id: str, client_id: str, timeout: float = 0.5) -> dict[str, Any] | None:
        with self._lock:
            terminal = self._sessions.get(session_id)
        if terminal is None:
            return None
        return terminal.read_event(client_id, timeout=timeout)

    def write(self, session_id: str, data: str) -> None:
        with self._lock:
            terminal = self._sessions.get(session_id)
        if terminal is not None:
            terminal.write(data)

    def resize(self, session_id: str, cols: int, rows: int) -> None:
        with self._lock:
            terminal = self._sessions.get(session_id)
        if terminal is not None:
            terminal.resize(cols, rows)

    def interrupt(self, session_id: str) -> None:
        with self._lock:
            terminal = self._sessions.get(session_id)
        if terminal is not None:
            terminal.interrupt()

    def close(self, session_id: str) -> None:
        with self._lock:
            terminal = self._sessions.pop(session_id, None)
        if terminal is not None:
            terminal.close()


def parse_terminal_message(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Terminal messages must be objects.")
    return payload
