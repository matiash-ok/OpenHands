# PC de agente: la imagen oficial + permiso de sudo para el usuario del agente (UID 1000 de la VM),
# para que pueda arrancar su propio Docker (ya viene instalado) e instalar lo que necesite.
# Solo tiene sentido con un runtime aislante (Sysbox o Kata): ahi "root" adentro NO es root en la VM.
ARG BASE=ghcr.io/openhands/agent-server:latest-python
FROM ${BASE}
USER root
RUN set -eux; groupadd -f docker; \
    getent passwd 1000 >/dev/null || useradd -u 1000 -U -M -d /var/openhands/.openhands -s /bin/bash agente; \
    usermod -aG docker "$(getent passwd 1000 | cut -d: -f1)"; \
    echo "$(getent passwd 1000 | cut -d: -f1) ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/agente; chmod 440 /etc/sudoers.d/agente
# mkfs.ext4: para el disco propio de Docker en las micro-VM (ver docker-up)
RUN command -v mkfs.ext4 >/dev/null || { apt-get update && apt-get install -y --no-install-recommends e2fsprogs && rm -rf /var/lib/apt/lists/*; }
COPY --chmod=755 docker-up /usr/local/bin/docker-up
USER openhands
