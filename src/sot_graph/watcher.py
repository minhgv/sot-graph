"""
sot_graph.watch — Reactive file watcher daemon for real-time sync.

Backends:
- ``watchfiles`` (inotify/kqueue/ReadDirectoryChangesW) when the optional
  ``[watch]`` extra is installed;
- a stdlib polling fallback otherwise, so the daemon stays zero-dependency.

Both backends fold rapid save events through the same debouncer and publish
through the reconciler's 2-Phase CAS gate (``.sot/write.lock``); if a heavy
CLI migration holds the lock, the watcher backs off instead of hanging.

Supports:
- Foreground single-project watching
- Background daemon mode (--daemon / --stop / --status)
- Multi-project auto-discovery & concurrent real-time sync (--all)
- macOS LaunchAgent & Linux systemd user service generation (--service install/uninstall)
"""

from __future__ import annotations

import json
import os
import platform
import stat
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from sot_graph.locking import LockBusy, WriteLock

__all__ = [
    "run_watch",
    "run_watch_multi",
    "pick_backend",
    "discover_sot_projects",
    "start_daemon",
    "stop_daemon",
    "status_daemon",
    "install_service",
    "uninstall_service",
]

_WATCHFILES = None
try:  # optional [watch] extra
    import watchfiles as _WATCHFILES  # type: ignore
except ImportError:
    _WATCHFILES = None

GLOBAL_SOT_DIR = Path.home() / ".sot"
PID_FILE_GLOBAL = GLOBAL_SOT_DIR / "watch_all.pid"
LOG_FILE_GLOBAL = GLOBAL_SOT_DIR / "watch_all.log"


def pick_backend(requested: str) -> str:
    if requested == "watchfiles":
        if _WATCHFILES is None:
            raise RuntimeError(
                "watchfiles backend requested but not installed; "
                "pip install sot-graph[watch] or use --backend poll"
            )
        return "watchfiles"
    if requested == "poll":
        return "poll"
    return "watchfiles" if _WATCHFILES is not None else "poll"


def _reconcile_quietly(reconciler, paths: Set[str]) -> int:
    """Reconcile changed paths; back off gracefully when the lock is busy."""
    published = 0
    for path in sorted(paths):
        try:
            outcome = reconciler.reconcile_path(path)
        except LockBusy:
            time.sleep(0.2)
            continue
        except Exception:
            continue
        if outcome not in ("error",):
            published += 1
    return published


def _run_watchfiles(
    reconciler,
    root: str,
    debounce_ms: int,
    log: Callable[[str], None],
    stop_event: Optional[threading.Event] = None,
) -> None:
    assert _WATCHFILES is not None
    for changes in _WATCHFILES.watch(
        root, debounce=int(debounce_ms), recursive=True, step=50
    ):
        if stop_event and stop_event.is_set():
            break
        paths = {
            path for _kind, path in changes
            if not reconciler.ignore_matcher.is_ignored(path)
        }
        if not paths:
            continue
        log(f"change: {len(paths)} file(s) in {Path(root).name}")
        _reconcile_quietly(reconciler, paths)


def _run_polling(
    reconciler,
    root: str,
    debounce_ms: int,
    log: Callable[[str], None],
    interval_ms: int = 500,
    stop_event: Optional[threading.Event] = None,
) -> None:
    def snapshot() -> dict:
        state = {}
        try:
            for path in reconciler.scan(None):
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                state[path] = (stat.st_size, int(stat.st_mtime * 1000))
        except Exception:
            pass
        return state

    current = snapshot()
    while True:
        if stop_event and stop_event.is_set():
            break
        time.sleep(interval_ms / 1000.0)
        if stop_event and stop_event.is_set():
            break
        fresh = snapshot()
        changed = {
            path for path, stamp in fresh.items()
            if current.get(path) != stamp
        } | {path for path in current if path not in fresh}
        current = fresh
        if not changed:
            continue
        # Fold bursty edits: wait until quiet for debounce_ms.
        quiet_until = time.monotonic() + debounce_ms / 1000.0
        while time.monotonic() < quiet_until:
            if stop_event and stop_event.is_set():
                break
            time.sleep(min(0.05, max(0.0, quiet_until - time.monotonic())))
            fresh = snapshot()
            delta = {
                path for path, stamp in fresh.items()
                if current.get(path) != stamp
            } | {path for path in current if path not in fresh}
            current = fresh
            if delta:
                changed |= delta
                quiet_until = time.monotonic() + debounce_ms / 1000.0
        log(f"change: {len(changed)} file(s) in {Path(root).name}")
        _reconcile_quietly(reconciler, changed)


def run_watch(
    reconciler,
    root: str,
    debounce_ms: int = 200,
    backend: str = "auto",
    interval_ms: int = 500,
    log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Run the watch daemon until interrupted or stop_event is set."""
    resolved = pick_backend(backend)
    log = log or (lambda message: print(f"[sot watch:{resolved}] {message}", flush=True))
    log(f"watching {root} (backend={resolved}, debounce={debounce_ms}ms)")
    if resolved == "watchfiles":
        _run_watchfiles(reconciler, root, debounce_ms, log, stop_event=stop_event)
    else:
        _run_polling(reconciler, root, debounce_ms, log, interval_ms=interval_ms, stop_event=stop_event)


def discover_sot_projects(base_dir: str, max_depth: int = 4) -> List[str]:
    """Recursively discover all directories containing .sot/sot.db."""
    base = Path(base_dir).resolve()
    if not base.exists() or not base.is_dir():
        return []

    # If base itself is a SOT project
    if (base / ".sot" / "sot.db").exists():
        return [str(base)]

    projects: List[str] = []
    ignored = {
        ".git", "node_modules", ".venv", "venv", "__pycache__",
        "build", "dist", ".gradle", ".idea", ".vscode", "target", "Pods"
    }

    def _scan(current: Path, depth: int):
        if depth > max_depth:
            return
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            return

        if (current / ".sot" / "sot.db").exists():
            projects.append(str(current))
            return  # Do not recurse into child dirs of an indexed project

        for entry in entries:
            if (
                entry.is_dir()
                and not entry.is_symlink()
                and entry.name not in ignored
                and not entry.name.startswith(".")
            ):
                _scan(entry, depth + 1)

    _scan(base, 1)
    return sorted(projects)


def run_watch_multi(
    roots: List[str],
    debounce_ms: int = 200,
    backend: str = "auto",
    interval_ms: int = 500,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Watch multiple SOT projects concurrently in separate worker threads."""
    from sot_graph.db import Database
    from sot_graph.reconciler import Reconciler

    resolved = pick_backend(backend)
    log = log or (lambda message: print(f"[sot watch-multi:{resolved}] {message}", flush=True))

    if not roots:
        log("No initialized SOT projects found to watch.")
        return

    log(f"🚀 Starting multi-project watcher across {len(roots)} projects (backend={resolved}, debounce={debounce_ms}ms)...")
    for r in roots:
        log(f"  📂 {r}")

    stop_event = threading.Event()
    threads: List[threading.Thread] = []

    def _worker(project_root: str):
        try:
            db_path = os.path.join(project_root, ".sot", "sot.db")
            db = Database(db_path)
            reconciler = Reconciler(db, project_root)
            run_watch(
                reconciler,
                project_root,
                debounce_ms=debounce_ms,
                backend=backend,
                interval_ms=interval_ms,
                log=log,
                stop_event=stop_event,
            )
        except Exception as e:
            log(f"❌ Error in watcher for {project_root}: {e}")

    for root in roots:
        t = threading.Thread(target=_worker, args=(root,), daemon=True, name=f"watch-{Path(root).name}")
        t.start()
        threads.append(t)

    # Handle termination signals cleanly
    def _sig_handler(signum, frame):
        log("\n🛑 Stopping all project watchers...")
        stop_event.set()

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)
        while not stop_event.is_set():
            time.sleep(0.5)
    except (KeyboardInterrupt, SystemExit):
        stop_event.set()
    finally:
        try:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
        except Exception:
            pass
        log("👋 All project watchers stopped.")


# -----------------------------------------------------------------------------
# Daemon Lifecycle Management
# -----------------------------------------------------------------------------

def is_pid_alive(pid: int) -> bool:
    """Return True when *pid* names a live process.

    On Windows ``os.kill(pid, 0)`` does NOT probe: 0 is the numeric value
    of CTRL_C_EVENT, so it broadcasts a console Ctrl+C (and any other sig
    unconditionally terminates the target). Probe via the Win32 API
    instead; POSIX keeps the signal-0 semantics.
    """
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == still_active
                return False
            finally:
                kernel32.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def _process_identity(pid: int) -> Optional[Dict[str, str]]:
    """Read a process start marker and command without invoking a shell.

    Linux and macOS expose enough process metadata through ``/proc`` or the
    native ``ps`` command to detect PID reuse.  Windows has neither a
    guaranteed ``/proc`` mount nor a portable ``ps`` implementation, so do
    not manufacture an identity from an implementation-specific command.
    ``start_daemon`` treats the missing identity as an unverified launch.
    """
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return None
    try:
        command: Optional[str] = None
        start: Optional[str] = None
        proc_dir = Path("/proc") / str(pid)
        if proc_dir.is_dir():
            raw_command = (proc_dir / "cmdline").read_bytes()
            command = " ".join(part.decode("utf-8", "replace") for part in raw_command.split(b"\0") if part)
            stat_line = (proc_dir / "stat").read_text(encoding="utf-8", errors="replace")
            rest = stat_line.rsplit(")", 1)[-1].split()
            if len(rest) > 19:
                start = rest[19]
        if command is None:
            command_output = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "command="],
                stderr=subprocess.DEVNULL,
            )
            command = command_output.decode("utf-8", "replace") if isinstance(command_output, bytes) else str(command_output)
        if start is None:
            start_output = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "lstart="],
                stderr=subprocess.DEVNULL,
            )
            start = start_output.decode("utf-8", "replace") if isinstance(start_output, bytes) else str(start_output)
        command = command.strip()
        start = start.strip()
        if not command or not start:
            return None
        return {"command": command, "start": start}
    except Exception:
        return None



def _process_cwd(pid: int) -> Optional[str]:
    """Return a process cwd when the platform exposes one."""
    try:
        proc_cwd = Path("/proc") / str(pid) / "cwd"
        if proc_cwd.exists():
            return os.path.realpath(proc_cwd)
        output = subprocess.check_output(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            stderr=subprocess.DEVNULL,
        )
        text = output.decode("utf-8", "replace") if isinstance(output, bytes) else str(output)
        for line in text.splitlines():
            if line.startswith("n"):
                return os.path.realpath(line[1:])
    except Exception:
        pass
    return None


def _read_pid_metadata(pid_path: Path) -> Optional[Dict[str, Any]]:
    """Read a bounded, regular PID metadata file without following symlinks."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd: Optional[int] = None
    try:
        fd = os.open(os.fspath(pid_path), flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024:
            return None
        chunks: List[bytes] = []
        remaining = 16 * 1024
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        text = b"".join(chunks).decode("utf-8", "replace").strip()
    except (OSError, UnicodeError):
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        try:
            pid = int(text)
        except ValueError:
            return None
        return {"pid": pid, "legacy": True}
    if not isinstance(parsed, dict):
        return None
    try:
        parsed["pid"] = int(parsed["pid"])
    except (KeyError, TypeError, ValueError):
        return None
    return parsed


def _write_pid_metadata(pid_path: Path, metadata: Dict[str, Any]) -> None:
    """Atomically publish owner-scoped PID metadata with mode 0600."""
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
    temp_path = pid_path.with_name(
        f".{pid_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    fd: Optional[int] = None
    try:
        fd = os.open(
            os.fspath(temp_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(os.fspath(temp_path), os.fspath(pid_path))
        os.chmod(os.fspath(pid_path), 0o600)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _remove_pid_file(pid_path: Path) -> None:
    try:
        pid_path.unlink(missing_ok=True)
    except OSError:
        pass


def _watcher_identity_matches(
    pid: int,
    metadata: Dict[str, Any],
    *,
    is_all: bool,
    root: Optional[str] = None,
) -> bool:
    """Require both a live PID and a matching watcher command identity."""
    if not is_pid_alive(pid):
        return False
    if metadata.get("scope") and metadata.get("scope") != ("all" if is_all else "single"):
        return False
    if not is_all and root and metadata.get("root"):
        try:
            if os.path.realpath(str(metadata["root"])) != os.path.realpath(root):
                return False
        except OSError:
            return False
    identity = _process_identity(pid)
    if identity is None:
        return False
    expected = metadata.get("identity")
    if expected is not None and expected != identity:
        return False
    command = identity.get("command", "")
    tokens = command.replace("\x00", " ").split()
    if "sot_graph.cli" not in tokens or "watch" not in tokens:
        return False
    if ("--all" in tokens) != is_all:
        return False
    if root:
        process_cwd = _process_cwd(pid)
        if process_cwd and not is_all:
            if os.path.realpath(process_cwd) != os.path.realpath(root):
                return False
    return True


def _get_pid_and_log_paths(root: str, is_all: bool) -> Tuple[Path, Path]:
    if is_all:
        GLOBAL_SOT_DIR.mkdir(parents=True, exist_ok=True)
        return PID_FILE_GLOBAL, LOG_FILE_GLOBAL
    canonical_root = Path(root).resolve()
    sot_dir = canonical_root / ".sot"
    if sot_dir.is_symlink():
        try:
            if os.path.commonpath((str(canonical_root), str(sot_dir.resolve()))) != str(canonical_root):
                raise ValueError("watcher metadata directory resolves outside project root")
        except ValueError:
            raise ValueError("watcher metadata directory resolves outside project root")
    sot_dir.mkdir(parents=True, exist_ok=True)
    return sot_dir / "watch.pid", sot_dir / "watch.log"


def _daemon_gate(pid_path: Path) -> WriteLock:
    return WriteLock(str(pid_path.with_name(pid_path.name + ".lock")), timeout_ms=5_000)


def start_daemon(
    root: str,
    is_all: bool = False,
    base_dir: Optional[str] = None,
    debounce_ms: int = 200,
    interval_ms: int = 500,
    backend: str = "auto",
) -> Tuple[bool, str]:
    """Start watcher as a detached background daemon."""
    pid_path, log_path = _get_pid_and_log_paths(root, is_all)
    try:
        with _daemon_gate(pid_path):
            existing = _read_pid_metadata(pid_path)
            if existing is not None:
                existing_pid = int(existing.get("pid", 0))
                scope_root = base_dir or root
                if _watcher_identity_matches(
                    existing_pid,
                    existing,
                    is_all=is_all,
                    root=None if is_all else scope_root,
                ):
                    return False, f"Watcher daemon is already running (PID: {existing_pid})"
                _remove_pid_file(pid_path)

            cmd = [
                sys.executable,
                "-m",
                "sot_graph.cli",
                "watch",
                "--debounce-ms",
                str(debounce_ms),
                "--interval-ms",
                str(interval_ms),
                "--backend",
                backend,
            ]
            if is_all:
                cmd.append("--all")
                if base_dir:
                    cmd.extend(["--dir", base_dir])

            scope_root = str(Path(base_dir if (is_all and base_dir) else root).resolve())
            log_file = open(log_path, "a", encoding="utf-8")
            proc: Any = None
            try:
                env = os.environ.copy()
                src_dir = str(Path(__file__).resolve().parent.parent)
                env["PYTHONPATH"] = (
                    f"{src_dir}{os.pathsep}{env['PYTHONPATH']}"
                    if env.get("PYTHONPATH")
                    else src_dir
                )
                proc = subprocess.Popen(
                    cmd,
                    cwd=scope_root,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    env=env,
                )
                identity = _process_identity(int(proc.pid))
                if identity is None:
                    raise RuntimeError(
                        "watcher process identity could not be verified; "
                        "daemon start aborted"
                    )
                metadata = {
                    "pid": int(proc.pid),
                    "scope": "all" if is_all else "single",
                    "root": os.path.realpath(scope_root),
                    "cwd": scope_root,
                    "argv": cmd,
                    "identity": identity,
                    "started_at_ns": time.time_ns(),
                }
                _write_pid_metadata(pid_path, metadata)
                target_desc = f"all projects in {base_dir or root}" if is_all else f"project {root}"
                return True, (
                    f"Started SOT Watcher daemon (PID: {proc.pid}) for {target_desc}.\n"
                    f"Logs: {log_path}"
                )
            except Exception as exc:
                if proc is not None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                return False, f"Failed to start daemon: {exc}"
            finally:
                log_file.close()
    except LockBusy:
        return False, "Watcher daemon start is already in progress; retry shortly."


def stop_daemon(root: str, is_all: bool = False) -> Tuple[bool, str]:
    """Stop only a process whose command identity matches watcher metadata."""
    pid_path, _ = _get_pid_and_log_paths(root, is_all)
    try:
        with _daemon_gate(pid_path):
            metadata = _read_pid_metadata(pid_path)
            if metadata is None:
                if pid_path.exists() or pid_path.is_symlink():
                    _remove_pid_file(pid_path)
                    return False, "Corrupted or unsafe PID file removed. Daemon was not running."
                return False, "No watcher daemon PID file found (daemon is not running)."
            pid = int(metadata.get("pid", 0))
            if not _watcher_identity_matches(
                pid,
                metadata,
                is_all=is_all,
                root=None if is_all else root,
            ):
                _remove_pid_file(pid_path)
                return False, f"PID {pid} identity mismatch; no process was signaled."

            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(30):
                    time.sleep(0.1)
                    if not is_pid_alive(pid):
                        break
                if is_pid_alive(pid):
                    if not _watcher_identity_matches(
                        pid,
                        metadata,
                        is_all=is_all,
                        root=None if is_all else root,
                    ):
                        _remove_pid_file(pid_path)
                        return False, f"PID {pid} identity changed; no force signal was sent."
                    sig_kill = getattr(signal, "SIGKILL", signal.SIGTERM)
                    os.kill(pid, sig_kill)
                    time.sleep(0.2)
                _remove_pid_file(pid_path)
                return True, f"Successfully stopped SOT Watcher daemon (PID: {pid})."
            except ProcessLookupError:
                _remove_pid_file(pid_path)
                return False, f"Process {pid} is not running. Stale PID file removed."
            except OSError as exc:
                return False, f"Error stopping daemon (PID: {pid}): {exc}"
    except LockBusy:
        return False, "Watcher daemon lifecycle is busy; retry shortly."


def status_daemon(root: str, is_all: bool = False) -> Dict[str, Any]:
    """Retrieve status only when PID metadata names this watcher instance."""
    pid_path, log_path = _get_pid_and_log_paths(root, is_all)
    try:
        with _daemon_gate(pid_path):
            metadata = _read_pid_metadata(pid_path)
            if metadata is None:
                return {
                    "running": False,
                    "pid": None,
                    "log_path": str(log_path),
                    "scope": "all" if is_all else "single",
                    "message": "Watcher daemon is not running.",
                }
            pid = int(metadata.get("pid", 0))
            running = _watcher_identity_matches(
                pid,
                metadata,
                is_all=is_all,
                root=None if is_all else root,
            )
            return {
                "running": running,
                "pid": pid if running else None,
                "log_path": str(log_path),
                "scope": "all" if is_all else "single",
                "message": (
                    f"Watcher daemon is ACTIVE (PID: {pid})"
                    if running
                    else f"PID {pid} is not the expected watcher process"
                ),
            }
    except LockBusy:
        return {
            "running": False,
            "pid": None,
            "log_path": str(log_path),
            "scope": "all" if is_all else "single",
            "message": "Watcher daemon lifecycle is busy; retry shortly.",
        }


# -----------------------------------------------------------------------------
# OS Service Integration (macOS LaunchAgent / Linux systemd)
# -----------------------------------------------------------------------------

def install_service(base_dir: str, python_bin: str) -> str:
    """Install and enable a persistent user background service on macOS or Linux."""
    system = platform.system().lower()
    base_dir = str(Path(base_dir).resolve())

    if system == "darwin":
        launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        launch_agents_dir.mkdir(parents=True, exist_ok=True)
        plist_path = launch_agents_dir / "com.sotgraph.watcher.plist"
        log_path = GLOBAL_SOT_DIR / "service_launchd.log"
        GLOBAL_SOT_DIR.mkdir(parents=True, exist_ok=True)

        src_dir = str(Path(__file__).resolve().parent.parent)

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sotgraph.watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>-m</string>
        <string>sot_graph.cli</string>
        <string>watch</string>
        <string>--all</string>
        <string>--dir</string>
        <string>{base_dir}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>{src_dir}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""
        plist_path.write_text(plist_content, encoding="utf-8")
        try:
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            res = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, text=True)
            if res.returncode == 0:
                return f"✅ Installed & loaded macOS LaunchAgent: {plist_path}\nWatching all SOT projects under {base_dir}\nLogs: {log_path}"
            return f"⚠️ Plist written to {plist_path} but launchctl load returned: {res.stderr}"
        except Exception as e:
            return f"⚠️ Plist written to {plist_path}, load error: {e}"

    elif system == "linux":
        systemd_dir = Path.home() / ".config" / "systemd" / "user"
        systemd_dir.mkdir(parents=True, exist_ok=True)
        service_path = systemd_dir / "sot-watcher.service"
        src_dir = str(Path(__file__).resolve().parent.parent)

        service_content = f"""[Unit]
Description=SOT-Graph Real-time Multi-Project Watcher Daemon
After=network.target

[Service]
Type=simple
Environment=PYTHONPATH={src_dir}
ExecStart={python_bin} -m sot_graph.cli watch --all --dir {base_dir}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
        service_path.write_text(service_content, encoding="utf-8")
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            res = subprocess.run(["systemctl", "--user", "enable", "--now", "sot-watcher.service"], capture_output=True, text=True)
            if res.returncode == 0:
                return f"✅ Installed & started systemd user service: {service_path}\nWatching all SOT projects under {base_dir}"
            return f"⚠️ Service written to {service_path}, systemctl error: {res.stderr}"
        except Exception as e:
            return f"⚠️ Service written to {service_path}, error: {e}"

    return f"Unsupported OS platform for auto-service: {system}. Use 'sot watch --all --daemon' instead."


def uninstall_service() -> str:
    """Uninstall persistent background service."""
    system = platform.system().lower()
    if system == "darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.sotgraph.watcher.plist"
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            plist_path.unlink(missing_ok=True)
            return f"✅ Unloaded and removed macOS LaunchAgent: {plist_path}"
        return "macOS LaunchAgent is not installed."
    elif system == "linux":
        service_path = Path.home() / ".config" / "systemd" / "user" / "sot-watcher.service"
        if service_path.exists():
            subprocess.run(["systemctl", "--user", "stop", "sot-watcher.service"], capture_output=True)
            subprocess.run(["systemctl", "--user", "disable", "sot-watcher.service"], capture_output=True)
            service_path.unlink(missing_ok=True)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
            return f"✅ Stopped and removed systemd user service: {service_path}"
        return "systemd user service is not installed."
    return f"Unsupported OS platform: {system}"
