#!/usr/bin/env bash
# Sanity check + watchdog do coletor Olho Vivo (GCP). Roda via cron a cada 15 min
# como root. Registra metricas em logs/health.log e reinicia o servico apenas se
# o loop estiver travado.
set -uo pipefail

DB=/home/olhovivo/olhovivo/data/olhovivo.sqlite3
LOG=/home/olhovivo/olhovivo/logs/health.log
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

total=$(sqlite3 "$DB" "select count(*) from positions" 2>/dev/null || echo -1)
last_1h=$(sqlite3 "$DB" "select count(*) from positions where ts_vehicle >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 hour')" 2>/dev/null || echo -1)
last_ts=$(sqlite3 "$DB" "select max(ts_vehicle) from positions" 2>/dev/null || echo "")
disk=$(df -h / | awk 'NR==2{print $4"/"$2" ("$5")"}')
active=$(systemctl is-active olhovivo 2>/dev/null || echo unknown)

# O coletor completa um ciclo a cada 25s independente de haver veiculos, entao
# "ciclos recentes" e o sinal de vida correto (nao "posicoes novas", que cai a
# zero de madrugada). Zero ciclos em 10 min = loop travado.
cycles_10m=$(journalctl -u olhovivo --since "10 min ago" -o cat 2>/dev/null | grep -c "ciclo ok")

echo "$now active=$active cycles_10m=$cycles_10m total=$total last_1h=$last_1h last=$last_ts disk=$disk" >> "$LOG"

if [ "$active" != "active" ] || [ "$cycles_10m" -eq 0 ]; then
  echo "$now WARN sem ciclos em 10min (active=$active) -> systemctl restart olhovivo" >> "$LOG"
  systemctl restart olhovivo
fi
