#!/usr/bin/env python3
"""Register the worker tools and the two agent profiles on the central server.

Usage: configurar.py <server url> <key file> <path of workers_mcp.py> <prompt file>
Safe to run again: it rewrites the same entries.
"""
import json
import sys
import time
import urllib.error
import urllib.request

url, key_file, mcp_path, prompt_file = sys.argv[1:5]
reviewer_prompt_file = prompt_file.replace("coordinator_prompt", "reviewer_prompt")
key = open(key_file).read().strip()


def call(method, path, body=None, missing_ok=False):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url + path,
        data=data,
        method=method,
        headers={"X-Session-API-Key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        sys.exit(f"!! {method} {path}: {exc.code} {exc.read()[:300].decode(errors='replace')}")


for _ in range(90):
    try:
        urllib.request.urlopen(url + "/alive", timeout=3)
        break
    except Exception:
        time.sleep(1)
else:
    sys.exit("!! the server did not come up")

profiles = call("GET", "/api/agent-profiles")
by_id = {p["id"]: p for p in profiles["profiles"]}
base = by_id.get(profiles.get("active_agent_profile_id")) or next(
    (p for p in profiles["profiles"] if p["name"] not in ("worker", "coordinator", "reviewer")), None
)
if base is None or not base.get("llm_profile_ref"):
    sys.exit(
        "!! Set up a model first: open the page, finish the setup with your "
        "provider and key, then run this again."
    )
if base.get("agent_kind") != "openhands":
    sys.exit("!! the active agent profile must be an OpenHands agent")
if base["name"] in ("worker", "coordinator", "reviewer"):
    base = call("GET", f"/api/agent-profiles/{base['name']}")["profile"]
llm = base["llm_profile_ref"]

call("DELETE", "/api/settings/mcp/pcworkers", missing_ok=True)
call(
    "POST",
    "/api/settings/mcp/pcworkers",
    {
        "command": "python3",
        "args": [mcp_path],
        "env": {
            "AGENTE_PC_URL": url,
            "AGENTE_PC_WORKER_PROFILE": "worker",
            "AGENTE_PC_MAX_WORKERS": "3",
        },
        "timeout": 300000,  # milliseconds: a wait for a worker takes minutes
    },
)
call(
    "POST",
    "/api/agent-profiles/worker",
    {"agent_kind": "openhands", "llm_profile_ref": llm, "mcp_server_refs": []},
)
call(
    "POST",
    "/api/agent-profiles/reviewer",
    {
        "agent_kind": "openhands",
        "llm_profile_ref": llm,
        "mcp_server_refs": [],
        "system_message_suffix": open(reviewer_prompt_file).read(),
    },
)
call(
    "POST",
    "/api/agent-profiles/coordinator",
    {
        "agent_kind": "openhands",
        "llm_profile_ref": llm,
        "mcp_server_refs": ["pcworkers"],
        "tools": [],  # no terminal, no files: it only delegates
        "system_message_suffix": open(prompt_file).read(),
    },
)
# Every other agent profile leaves the worker tools out.
for profile in profiles["profiles"]:
    if profile["name"] in ("worker", "coordinator", "reviewer") or profile.get("agent_kind") != "openhands":
        continue
    full = call("GET", f"/api/agent-profiles/{profile['name']}")["profile"]
    if full.get("mcp_server_refs") is None:
        body = {k: v for k, v in full.items() if k not in ("id", "name", "revision", "schema_version")}
        body["mcp_server_refs"] = []
        call("POST", f"/api/agent-profiles/{profile['name']}", body)
call("PATCH", "/api/settings", {"conversation_settings_diff": {"default_runtime": "docker"}})
print(f"Configured: tools 'pcworkers', profiles 'worker', 'reviewer' and 'coordinator' (model profile: {llm}).")
