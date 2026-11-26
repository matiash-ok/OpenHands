#!/usr/bin/env bash
# Agrega el coordinador: un agente sin terminal que arranca y dirige workers,
# cada uno en su micro-VM. Reinicia el OpenHands central (las micro-VM siguen).
# Correr con: sudo bash actualizar.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Correr con sudo"; exit 1; }
DIR=$(cd "$(dirname "$0")" && pwd)
# Imagen nueva del Canvas, si la copiaron despues de la ultima carga.
if [[ "$DIR/agent-canvas.tar.zst" -nt /srv/agente-pc/.imagen-cargada ]]; then
  zstd -dc "$DIR/agent-canvas.tar.zst" | docker load
  touch /srv/agente-pc/.imagen-cargada
fi
install -d -m 755 /srv/agente-pc/lib
install -m 644 "$DIR/lib/workers_mcp.py" "$DIR/lib/coordinator_prompt.md" "$DIR/lib/reviewer_prompt.md" "$DIR/lib/configurar.py" /srv/agente-pc/lib/
install -m 755 "$DIR/agente-pc" /usr/local/sbin/agente-pc
# Skills compartidos con todos los agentes (solo lectura para ellos).
install -d -m 755 /srv/agente-pc/skills
cp -a "$DIR/skills/." /srv/agente-pc/skills/
# Tambien para el OpenHands central: asi aparecen en su lista de skills.
install -d -o 1000 -g 1000 /srv/agente-pc/home/.agents /srv/agente-pc/home/.agents/skills
cp -a "$DIR/skills/." /srv/agente-pc/home/.agents/skills/
chown -R 1000:1000 /srv/agente-pc/home/.agents
chown -R root:root /srv/agente-pc/skills
agente-pc start
agente-pc configurar
