"""Worker tools for a coordinator conversation (MCP server, stdio).

A coordinator that runs on the central OpenHands server uses these tools to
start other conversations ("workers"), each in a machine of its own, and to
steer them: send a message, wait for the answer, read it, pass files from one
worker to another, and stop the machine.

It talks to the central agent server's HTTP API with the server's own key, so
it only works where that server runs. Anywhere else it offers no tools.

Environment:
  AGENTE_PC_URL             agent server base URL (default http://127.0.0.1:18000)
  AGENTE_PC_KEY_FILE        file with the server's session key
                            (default ~/.openhands/agent-canvas/api-key.txt)
  AGENTE_PC_WORKER_PROFILE  name of the agent profile workers run
                            (default: the server's active agent profile)
  AGENTE_PC_WORKER_ISOLATION container isolation for workers, e.g. "vm"
                            (default: the server's own default)
  AGENTE_PC_MAX_WORKERS     most workers with a running machine at once (default 3)
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastmcp import FastMCP


URL = os.environ.get("AGENTE_PC_URL", "http://127.0.0.1:18000").rstrip("/")
HOME = Path(os.environ.get("HOME", "/home/openhands"))
KEY_FILE = Path(
    os.environ.get(
        "AGENTE_PC_KEY_FILE", HOME / ".openhands" / "agent-canvas" / "api-key.txt"
    )
)
WORKER_PROFILE = os.environ.get("AGENTE_PC_WORKER_PROFILE", "").strip()
WORKER_ISOLATION = os.environ.get("AGENTE_PC_WORKER_ISOLATION", "").strip()
MAX_WORKERS = int(os.environ.get("AGENTE_PC_MAX_WORKERS", "3"))
RUNTIME_DATA = HOME / ".openhands" / "runtime-data"
STATE_FILE = HOME / ".openhands" / "agente-pc-workers.json"
WORKER_TAG = "agentepcworker"
BUSY = {"running"}
# A turn takes a moment to show as running after a message is delivered.
SETTLE_SECONDS = 15.0
POLL_SECONDS = 4.0

mcp = FastMCP("workers")


class WorkerError(Exception):
    pass


def _key() -> str | None:
    try:
        return KEY_FILE.read_text().strip() or None
    except OSError:
        return None


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    key = _key()
    if key is None:
        raise WorkerError("Worker tools are only available on the central server.")
    try:
        with httpx.Client(timeout=kwargs.pop("timeout", 60.0)) as client:
            response = client.request(
                method, f"{URL}{path}", headers={"X-Session-API-Key": key}, **kwargs
            )
    except httpx.HTTPError as exc:
        raise WorkerError(f"Could not reach the server: {type(exc).__name__}") from exc
    if response.is_error:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = response.text[:300]
        raise WorkerError(f"Server answered {response.status_code}: {detail}")
    return response


def _secrets(profile_id: str) -> dict[str, dict[str, Any]]:
    """References to the user's stored secrets that the profile may use.

    The server resolves each reference itself when it starts the worker, as it
    does for a conversation started from the web interface; no value passes
    through this process or reaches the coordinator.
    """
    listing = _request(
        "GET", "/api/settings/secrets", params={"agent_profile_id": profile_id}
    ).json()
    headers = {"X-Session-API-Key": _key()}
    return {
        item["name"]: {
            "kind": "LookupSecret",
            "url": "/api/settings/secrets/" + quote(item["name"], safe=""),
            "headers": headers,
        }
        for item in listing.get("secrets", [])
    }


# Not copied between workers: each workspace keeps its own git history, and
# installed dependencies and caches are rebuilt by whoever needs them (a
# virtualenv does not survive a move anyway).
NOT_COPIED = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


def _copy_tree(src: Path, dst: Path) -> int:
    """Copy ``src`` over ``dst``, replacing what is there; returns files copied."""
    count = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in NOT_COPIED]
        here = Path(root)
        out = dst / here.relative_to(src)
        if out.is_symlink() or (out.exists() and not out.is_dir()):
            out.unlink()
        out.mkdir(parents=True, exist_ok=True)
        # os.walk lists a symlink to a directory under dirs but does not enter it.
        links = [d for d in dirs if (here / d).is_symlink()]
        dirs[:] = [d for d in dirs if d not in links]
        for name in [*files, *links]:
            if name in NOT_COPIED:
                continue
            source, target = here / name, out / name
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            shutil.copy2(source, target, follow_symlinks=False)
            count += 1
    return count


def _load_state() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def _worker(worker: str) -> tuple[str, dict[str, Any]]:
    """Resolve a worker by id or by the name it was started with."""
    state = _load_state()
    if worker in state:
        return worker, state[worker]
    matches = [(wid, w) for wid, w in state.items() if w.get("name") == worker]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise WorkerError(f"Several workers are named {worker!r}; use the id.")
    raise WorkerError(f"No worker {worker!r}. Use list_pc_workers to see them.")


def _profile_id(name: str = "") -> str:
    data = _request("GET", "/api/agent-profiles").json()
    wanted = name.strip() or WORKER_PROFILE
    if wanted == "coordinator":
        raise WorkerError("A worker cannot run the coordinator profile.")
    if wanted:
        for profile in data.get("profiles", []):
            if profile.get("name") == wanted:
                return profile["id"]
        names = sorted(
            p["name"] for p in data.get("profiles", []) if p["name"] != "coordinator"
        )
        raise WorkerError(
            f"Agent profile {wanted!r} does not exist. Available: {', '.join(names)}."
        )
    active = data.get("active_agent_profile_id")
    if not active:
        raise WorkerError("The server has no active agent profile for workers.")
    return active


def _raw_status(worker_id: str) -> str:
    info = _request("GET", f"/api/conversations/{worker_id}").json()
    return str(info.get("execution_status") or "unknown")


def _status(worker_id: str) -> str:
    status = _raw_status(worker_id)
    sent = _load_state().get(worker_id, {}).get("sent", 0)
    if status == "idle" and time.time() - sent < SETTLE_SECONDS:
        return "running"
    return status


def _power_on(worker_id: str) -> bool:
    """Start a stopped worker's machine again; True when it had to."""
    if _machine_running(worker_id):
        return False
    _request(
        "POST", f"/api/conversations/{worker_id}/runtime/reprovision", timeout=280.0
    )
    deadline = time.monotonic() + 120.0
    while not _machine_running(worker_id) and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
    if not _machine_running(worker_id):
        raise WorkerError("The worker's machine did not start again.")
    return True


def _mark_sent(worker_id: str, **record: Any) -> None:
    state = _load_state()
    state[worker_id] = {**state.get(worker_id, {}), **record, "sent": time.time()}
    _save_state(state)


def _final(worker_id: str) -> str:
    try:
        data = _request("GET", f"/api/conversations/{worker_id}/agent_final_response")
    except WorkerError:
        return ""
    return str(data.json().get("response") or "")


def _machine_running(worker_id: str) -> bool:
    try:
        info = _request("GET", f"/api/conversations/{worker_id}/runtime").json()
    except WorkerError:
        return False
    return info.get("runtime_status") == "available"


def _report(worker_id: str, name: str, status: str) -> str:
    answer = _final(worker_id) if status not in BUSY else ""
    lines = [f"worker: {name} ({worker_id})", f"status: {status}"]
    if status in BUSY:
        lines.append("It is still working. Call wait_pc_worker again.")
    elif answer:
        lines += ["its final message:", answer]
    else:
        lines.append("It stopped without a final message.")
    return "\n".join(lines)


def _workspace(worker_id: str) -> Path:
    return RUNTIME_DATA / worker_id.replace("-", "") / "workspace"


def _guard(fn):
    """Return tool errors as text: the agent reads them and decides."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except WorkerError as exc:
            return f"ERROR: {exc}"

    return wrapper


def start_worker(name: str, task: str, profile: str = "") -> str:
    """Start a new worker: another agent in a machine of its own, with Docker.

    name: a short role name you will refer to it by, e.g. "coder" or "reviewer".
    task: the complete instructions. The worker knows nothing else: it does not
      see this conversation or the other workers, so include everything it needs.
    profile: which kind of agent it is. Leave empty for a general worker (it
      codes, runs and tests). Use "reviewer" for a read-only code reviewer that
      follows the review-pr skill, or "claude-code" for a coder that runs
      Claude Code on the user's Claude subscription.
    It starts working at once. Use wait_pc_worker to get its answer.
    """
    name = name.strip() or "worker"
    state = _load_state()
    running = [wid for wid in state if _machine_running(wid)]
    for wid, record in state.items():
        if record.get("name") != name:
            continue
        if wid in running:
            raise WorkerError(
                f"A worker named {name!r} is already running. Message it, or "
                "pick a new name."
            )
        # An earlier task's worker: free the name, keep it reachable by id.
        record["name"] = f"{name}-{wid[:8]}"
    if len(running) >= MAX_WORKERS:
        raise WorkerError(
            f"{len(running)} workers already have a running machine (limit "
            f"{MAX_WORKERS}). Stop one with stop_pc_worker first."
        )
    profile_id = _profile_id(profile)
    body: dict[str, Any] = {
        "conversation_runtime": "docker",
        "agent_profile_id": profile_id,
        "secrets": _secrets(profile_id),
        "workspace": {"working_dir": "/workspace"},
        "tags": {WORKER_TAG: name[:64]},
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": task}],
            "run": True,
        },
    }
    if WORKER_ISOLATION:
        body["container"] = {"isolation": WORKER_ISOLATION}
    info = _request("POST", "/api/conversations", json=body, timeout=280.0).json()
    worker_id = str(info["id"])
    try:
        _request(
            "PATCH", f"/api/conversations/{worker_id}", json={"title": f"[{name}]"}
        )
    except WorkerError:
        pass  # the title is cosmetic
    _save_state(state)  # keeps a freed name freed
    _mark_sent(worker_id, name=name)
    return (
        f"Started worker {name} ({worker_id}) in its own machine. "
        "It is working on the task. Call wait_pc_worker to get its answer."
    )


def wait_worker(worker: str, max_wait_seconds: int = 240) -> str:
    """Wait until a worker finishes its current turn, then return its final message.

    worker: the worker's name or id.
    Waits at most max_wait_seconds (240 at most). If the worker is still working
    after that, it says so: call wait_pc_worker again. Long tasks need several calls.
    """
    worker_id, record = _worker(worker)
    deadline = time.monotonic() + max(5, min(int(max_wait_seconds), 240))
    status = _status(worker_id)
    while status in BUSY and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        status = _status(worker_id)
    return _report(worker_id, record["name"], status)


def read_worker(worker: str) -> str:
    """Return a worker's status and its latest final message, without waiting."""
    worker_id, record = _worker(worker)
    status = _status(worker_id)
    answer = _final(worker_id)
    text = f"worker: {record['name']} ({worker_id})\nstatus: {status}"
    return f"{text}\nits latest final message:\n{answer}" if answer else text


def message_worker(worker: str, message: str) -> str:
    """Send a worker a follow-up message. It keeps its machine and what it did.

    Use it to pass on review findings or ask for changes. The worker starts
    working on it at once; call wait_pc_worker for the answer.
    """
    worker_id, record = _worker(worker)
    status = _status(worker_id)
    if status == "running":
        raise WorkerError(
            f"{record['name']} is still working. Wait for it with "
            "wait_pc_worker, or use interrupt_pc_worker if it must change "
            "course now."
        )
    if status in ("error", "stuck"):
        raise WorkerError(
            f"{record['name']} is in state {status!r} and cannot continue. "
            "Stop it and start a new worker with the full context."
        )
    woken = _power_on(worker_id)
    _request(
        "POST",
        f"/api/conversations/{worker_id}/events",
        json={
            "role": "user",
            "content": [{"type": "text", "text": message}],
            "run": True,
        },
        timeout=280.0,
    )
    _mark_sent(worker_id)
    note = (
        " Its machine was off and is on again: it remembers the conversation "
        "and its files, but nothing is running (it must start Docker and its "
        "servers again)."
        if woken
        else ""
    )
    return (
        f"Message delivered to {record['name']}.{note} Call wait_pc_worker for "
        "its answer."
    )


def interrupt_worker(worker: str, message: str) -> str:
    """Stop a worker in the middle of its work and give it a new instruction.

    Use it when a worker is still working and must change course: it is going
    the wrong way, the task changed, or it needs a fact now. The worker stops
    after the step it is on, keeps its machine and everything it did, reads the
    message and carries on. Say in the message what to do with the work it had
    in progress. For a worker that already finished, use message_pc_worker.
    A "claude-code" worker may finish what it was doing before it acts on the
    message; if it must stop at once, stop its machine instead.
    """
    worker_id, record = _worker(worker)
    name = record["name"]
    status = _status(worker_id)
    if status in ("error", "stuck"):
        raise WorkerError(
            f"{name} is in state {status!r} and cannot continue. Stop it and "
            "start a new worker with the full context."
        )
    how = "it was not working"
    if status == "running":
        info = _request("GET", f"/api/conversations/{worker_id}").json()
        # Pausing does not reach an external agent (Claude Code): it reports
        # "paused" and keeps working. Those are cut instead.
        external = (info.get("agent") or {}).get("kind") != "Agent"
        if not external:
            _request("POST", f"/api/conversations/{worker_id}/pause", timeout=60.0)
            how = "stopped after its current step"
            deadline = time.monotonic() + 150.0
            while _raw_status(worker_id) == "running" and time.monotonic() < deadline:
                time.sleep(POLL_SECONDS)
        if external or _raw_status(worker_id) == "running":
            # A step that does not end (a long command): cut it.
            _request("POST", f"/api/conversations/{worker_id}/interrupt", timeout=60.0)
            how = "cut in the middle of a step"
            deadline = time.monotonic() + 30.0
            while _raw_status(worker_id) == "running" and time.monotonic() < deadline:
                time.sleep(POLL_SECONDS)
            if _raw_status(worker_id) == "running":
                raise WorkerError(
                    f"{name} did not stop. Stop its machine with stop_pc_worker."
                )
    _power_on(worker_id)
    _request(
        "POST",
        f"/api/conversations/{worker_id}/events",
        json={
            "role": "user",
            "content": [{"type": "text", "text": message}],
            "run": True,
        },
        timeout=280.0,
    )
    _mark_sent(worker_id)
    return (
        f"{name} interrupted ({how}) and given the message. Call wait_pc_worker "
        "for its answer."
    )


def copy_files(from_worker: str, to_worker: str, path: str = ".") -> str:
    """Copy files from one worker's /workspace into another worker's /workspace.

    Workers do not share a disk: this is how one hands its work to another.
    path: a file or folder relative to /workspace (default: everything). It lands
    at the same relative path in the other worker, replacing files of the same name.
    Tell the receiving worker where the files are, and that git history,
    installed dependencies (.venv, node_modules) and caches are not copied: it
    installs what it needs.
    """
    source_id, source = _worker(from_worker)
    target_id, target = _worker(to_worker)
    source_root = _workspace(source_id).resolve()
    target_root = _workspace(target_id).resolve()
    if not source_root.is_dir() or not target_root.is_dir():
        raise WorkerError("A worker's workspace does not exist (yet).")
    src = (source_root / path).resolve()
    dst = (target_root / path).resolve()
    if not src.is_relative_to(source_root) or not dst.is_relative_to(target_root):
        raise WorkerError("path must stay inside /workspace.")
    if not src.exists():
        raise WorkerError(f"{path!r} does not exist in {source['name']}'s workspace.")
    try:
        if src.is_dir():
            # Each workspace is a git repository of its own: its history stays.
            count = _copy_tree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            count = 1
    except (OSError, shutil.Error) as exc:
        raise WorkerError(f"Copy failed: {str(exc)[:300]}") from exc
    where = "/workspace" if path in (".", "") else f"/workspace/{path}"
    return (
        f"Copied {count} file(s) from {source['name']} to {target['name']} at {where}."
    )


def stop_worker(worker: str) -> str:
    """Shut down a worker's machine to free memory, or to stop it at once.

    The worker keeps its conversation (it remembers everything) and the files
    in /workspace. What was running inside (Docker, servers, an unfinished
    command) is lost. message_pc_worker turns the machine on again.
    """
    worker_id, record = _worker(worker)
    for _ in range(3):
        _request("DELETE", f"/api/conversations/{worker_id}/runtime", timeout=120.0)
        # A message still being delivered can bring the machine back.
        time.sleep(2)
        if not _machine_running(worker_id):
            return f"Stopped {record['name']}'s machine."
    raise WorkerError(f"{record['name']}'s machine is still on after three tries.")


def list_workers() -> str:
    """List the workers started so far, with their status."""
    state = _load_state()
    if not state:
        return "No workers yet."
    lines = []
    for worker_id, record in state.items():
        try:
            status = _status(worker_id)
        except WorkerError:
            status = "gone"
        machine = "machine on" if _machine_running(worker_id) else "machine off"
        lines.append(f"{record['name']} ({worker_id}): {status}, {machine}")
    return "\n".join(lines)


if _key() is not None:
    for tool in (
        start_worker,
        wait_worker,
        read_worker,
        message_worker,
        interrupt_worker,
        copy_files,
        stop_worker,
        list_workers,
    ):
        # Named apart from OpenHands' own project tools (list_workers, ...).
        mcp.tool(_guard(tool), name=tool.__name__.replace("worker", "pc_worker"))

if __name__ == "__main__":
    mcp.run()
