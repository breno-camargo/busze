#!/usr/bin/env bash
# Instala o cron do healthcheck e valida numa execucao. Idempotente.
set -uo pipefail
CRON=/etc/cron.d/olhovivo-health
{
  echo "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  echo "*/15 * * * * root /home/olhovivo/olhovivo/healthcheck.sh"
  echo ""
} | sudo tee "$CRON" >/dev/null
sudo chmod 644 "$CRON"
echo "=== CRON ==="
cat "$CRON"
echo "=== RUN healthcheck ==="
sudo bash /home/olhovivo/olhovivo/healthcheck.sh
echo "=== health.log (ultimas 3 linhas) ==="
tail -n 3 /home/olhovivo/olhovivo/logs/health.log
echo "=== servico ==="
systemctl is-active olhovivo
