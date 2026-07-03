#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  BOOTSTRAP — corre UNA SOLA VEZ en la VM Oracle recién creada
#  Instala Python, dependencias del sistema, y crea el usuario
#  de servicio que va a correr el agente.
#  Uso: scp este archivo a la VM y luego: sudo bash bootstrap_vm.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

echo "==> Detectando distro..."
. /etc/os-release
echo "    $PRETTY_NAME"

echo "==> Actualizando paquetes del sistema..."
if command -v dnf >/dev/null 2>&1; then
    dnf install -y python3.12 python3.12-pip python3-virtualenv git curl
    PYBIN=/usr/bin/python3.12
elif command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y python3 python3-pip python3-venv git curl
    PYBIN=$(command -v python3)
else
    echo "Distro no soportada"; exit 1
fi

echo "==> Creando usuario de servicio 'trader'..."
if ! id trader >/dev/null 2>&1; then
    useradd -m -s /bin/bash trader
fi

echo "==> Creando carpeta del agente..."
install -d -o trader -g trader /opt/trading-agent
install -d -o trader -g trader /opt/trading-agent/logs

echo "==> Configurando firewall (Oracle usa iptables)..."
# Oracle Linux por defecto bloquea TODO en iptables — no abrimos puertos porque
# el agente solo hace conexiones SALIENTES (Binance, Telegram, Supabase).
# Si en el futuro querés exponer el dashboard, abrimos 8000 acá.

echo "==> Bootstrap OK. Próximo paso: subir código y .env, luego instalar systemd."
echo "    Python detectado: $PYBIN"
$PYBIN --version
