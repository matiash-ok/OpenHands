# agent-pc: a machine of its own for every agent

This folder turns one OpenHands (built from this fork) into a small team:
a **coordinator** that only delegates, and **workers** and **reviewers** that
each get a private machine with `sudo` and their own Docker, so a reviewer can
bring up the backend, the frontend or whatever the app under review needs
without touching the host or another agent.

```
 browser ──► OpenHands (container "agente-pc", holds the host's Docker socket)
                │
                ├─ coordinator conversation   runs here, no terminal, no files,
                │                             only the start/wait/copy/stop tools
                │
                ├─ worker  ──► micro-VM (Kata)  own kernel, sudo, Docker
                ├─ reviewer ─► micro-VM (Kata)  read-only review + runs the app
                └─ ...
```

It depends on two branches named `feat/agent-pc-isolation`:

| Repository | What the branch adds |
| --- | --- |
| [`software-agent-sdk`](https://github.com/matiash-ok/software-agent-sdk/tree/feat/agent-pc-isolation) | `container.isolation` on conversation start (`OH_CONVERSATION_CONTAINER_ISOLATIONS`), and `OH_CONVERSATION_LOCAL_AGENT_PROFILES`, which limits the agent profiles allowed to run on the host |
| this repository | the Docker / Sysbox / Micro-VM choice in the workspace menu |

The scripts print their messages in Spanish.

## What is in here

| Path | Purpose |
| --- | --- |
| `instalar.sh` | One-time host setup: Kata Containers in `/opt/kata`, the `kata` Docker runtime, the images, the `agentes` network, the `agente-pc` command |
| `agente-pc` | The command that runs everything: `start`, `stop`, `logs`, `key`, `status`, `configurar`, `telefono on [IP:PORT]` / `off`, `quitar` |
| `actualizar.sh` | Re-installs the files in this folder, loads a new Canvas image if there is one, restarts OpenHands and re-applies the profiles |
| `imagen/` | The image every agent machine boots: the agent server plus `sudo` and `docker-up` (starts Docker inside the micro-VM) |
| `lib/workers_mcp.py` | MCP server that gives the coordinator its tools |
| `lib/coordinator_prompt.md`, `lib/reviewer_prompt.md` | Instructions for those two profiles |
| `lib/configurar.py` | Creates the `coordinator`, `worker` and `reviewer` agent profiles and registers the MCP server |
| `skills/` | Skills shared with every agent. Anything placed here is mounted read-only into each machine as a user skill |

## Requirements

- A Linux host on bare metal with KVM (`/dev/kvm`). Micro-VMs nested inside
  another VM were unstable in testing.
- Docker, with a `/etc/docker/daemon.json` that already exists.
- `zstd`, `python3`, `curl`, `iptables`; `adb` only for the phone.
- About 4 GB of free memory per agent machine that runs at once.

## Install

1. Build the two images from the forks, on any machine with Docker:

   ```bash
   # in software-agent-sdk
   uv run python openhands-agent-server/openhands/agent_server/docker/build.py \
     --image agent-pc/agent-server --custom-tags python --target binary \
     --base-image python-node-runtime --platforms linux/amd64 --load
   # in this repository; use the tag the previous command printed
   docker build -f docker/Dockerfile \
     --build-arg AGENT_SERVER_IMAGE=agent-pc/agent-server:<sha>-python \
     --build-arg AGENT_SERVER_VERSION=$(node -p "require('./config/defaults.json').versions.agentServer") \
     --build-arg AUTOMATION_VERSION=$(node -p "require('./config/defaults.json').versions.automation") \
     -t agent-pc/agent-canvas:latest .
   docker save agent-pc/agent-canvas:latest | zstd -T0 > agent-pc/agent-canvas.tar.zst
   ```

2. Copy this folder, with `agent-canvas.tar.zst` in it, to the host and run:

   ```bash
   sudo bash instalar.sh      # once
   sudo bash actualizar.sh    # starts OpenHands and creates the profiles
   ```

3. Open it through an SSH tunnel; the ports listen on `127.0.0.1` only:

   ```bash
   ssh -L 8100:127.0.0.1:8100 <host>     # then http://localhost:8100/canvas
   sudo agente-pc key                    # on the host, if the page asks for a key
   ```

4. In OpenHands, add an LLM and any secrets (Git tokens and so on). Then run
   `sudo agente-pc configurar` again so the profiles pick the LLM up.

## Use

Start a conversation with the **coordinator** profile in **Local** mode and
describe the job. It starts a coder in its own machine, waits, starts a
reviewer (profile `reviewer`), copies the files across, relays the findings
back to the coder, and repeats until the reviewer approves. Then it stops the
machines.

The coordinator's tools:

| Tool | What it does |
| --- | --- |
| `start_pc_worker(name, task, profile)` | New conversation in a new micro-VM, with the secrets stored in OpenHands that its profile may use. Empty `profile` is a general worker on the API key; `claude-code` is Claude Code on a Claude subscription (needs the `CLAUDE_CODE_OAUTH_TOKEN` secret); `reviewer` is the code reviewer |
| `wait_pc_worker(name)` | Waits (up to 4 minutes per call) for the worker to finish its turn |
| `read_pc_worker(name)` | The worker's last answer |
| `message_pc_worker(name, text)` | Sends the worker a follow-up |
| `copy_files(from, to)` | Copies one worker's workspace into another's (without `.git`, installed dependencies or caches) |
| `stop_pc_worker(name)` | Stops the machine and frees its memory |
| `list_pc_workers()` | Workers of this coordinator and their state |

You can also start a `worker` or `reviewer` conversation yourself: choose
**Micro-VM** as the workspace.

## Safety model

- **Local mode is for the coordinator only.** A Local conversation runs
  inside the central container, which holds the host's Docker socket. The
  server refuses any other profile there
  (`OH_CONVERSATION_LOCAL_AGENT_PROFILES='["coordinator"]'`), and the
  coordinator profile has no terminal or file tools.
- **Agent machines are micro-VMs** with their own kernel. Root inside one is
  not root on the host.
- **Network:** agent machines reach the internet, and nothing else: not the
  host, the LAN, a tailnet (`100.64.0.0/10`) or other containers. The rules
  live in the `AGENTE-PC-IN` and `AGENTE-PC-FWD` iptables chains.
- **Not persistent across reboots.** After the host restarts, run
  `sudo agente-pc start` to bring OpenHands and the firewall back.

## Skills

`skills/android-device` lets an agent build, install and inspect an app on a
real Android phone. The phone stays attached to the host (USB, or paired over
Wi-Fi), the host runs the adb server, and agents reach it only while sharing
is on:

```bash
sudo agente-pc telefono on                 # USB
sudo agente-pc telefono on 192.168.1.50:37123   # wireless debugging address
sudo agente-pc telefono off
```

While sharing is on, every agent machine has full adb control of the phone.
The skill limits agents to the app under development by instruction only.

To add a skill, put its folder (with a `SKILL.md`) in `skills/` and run
`actualizar.sh`. Scripts inside a skill must be referenced as
`$HOME/.agents/skills/<name>/...`, which is where machines see them.

## Status

Verified end to end on one host: a coordinator drove a coder and a reviewer
through two rounds without human relaying. Not yet exercised: the `reviewer`
profile with a review skill inside a micro-VM, the phone sharing with a real
device, and a full coordinator run with `claude-code` workers (a single
Claude Code conversation in a micro-VM does work).
