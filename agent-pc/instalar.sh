#!/usr/bin/env bash
# Prueba: OpenHands (imagen del fork) como contenedor en un host Linux, con una
# micro-VM (Kata Containers) por conversacion. No toca los otros
# servicios: agrega un runtime a Docker con "reload" (sin reiniciar contenedores).
# Correr con: sudo bash instalar.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Correr con sudo"; exit 1; }
DIR=$(cd "$(dirname "$0")" && pwd)
KATA=4.4.0
STAMP=$(date +%F-%H%M)

# 1) Kata Containers en /opt/kata
if [[ ! -x /opt/kata/runtime-rs/bin/containerd-shim-kata-v2 ]]; then
  T=$(mktemp -d)
  curl -fL -o "$T/kata.tar.zst" "https://github.com/kata-containers/kata-containers/releases/download/$KATA/kata-static-$KATA-amd64.tar.zst"
  tar --zstd -xf "$T/kata.tar.zst" -C /      # el tar trae ./opt/kata/...
  rm -rf "$T"
fi
ln -sfn /opt/kata/runtime-rs/bin/containerd-shim-kata-v2 /usr/local/bin/containerd-shim-kata-v2
modprobe -a vhost_vsock vhost_net
printf 'vhost_vsock\nvhost_net\n' > /etc/modules-load.d/agente-pc.conf

# 2) Runtime "kata" en Docker (copia previa del daemon.json; reload, no restart)
cp -a /etc/docker/daemon.json "/etc/docker/daemon.json.bak-$STAMP"
python3 - <<'PY'
import json
p = "/etc/docker/daemon.json"
d = json.load(open(p))
d.setdefault("runtimes", {})["kata"] = {"runtimeType": "io.containerd.kata.v2"}
json.dump(d, open(p, "w"), indent=4)
PY
systemctl reload docker
docker info --format '{{json .Runtimes}}' | grep -q kata || { echo "!! Docker no tomo el runtime kata"; exit 1; }

# 3) Imagenes: el Canvas del fork y la PC de cada agente
zstd -dc "$DIR/agent-canvas.tar.zst" | docker load
docker pull ghcr.io/openhands/agent-server:latest-python
docker build -t agente-pc:latest "$DIR/imagen"

# 4) Red propia para las micro-VM (el firewall lo pone "agente-pc start")
docker network inspect agentes >/dev/null 2>&1 || docker network create \
  --subnet 172.30.0.0/24 -o com.docker.network.bridge.name=br-agentes agentes

install -m 755 "$DIR/agente-pc" /usr/local/sbin/agente-pc

echo; echo "== Prueba de una micro-VM (el kernel tiene que ser 6.18.x, no $(uname -r)):"
docker run --rm --runtime kata --network agentes busybox uname -r
echo "Listo. Arrancar con: sudo agente-pc start"
