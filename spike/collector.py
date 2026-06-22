"""
Olho Vivo position collector — ETA-engine de-risking spike.

Goal: continuously poll SPTrans Olho Vivo /Posicao AND /Previsao for a small set
of bus lines and persist every reading to SQLite, so we can later run map-matching
+ per-segment speed analysis offline and measure projection error (go/no-go for
the product's "Waze for buses" differentiator). /Previsao stores SPTrans's own
ETA-to-stop per vehicle — the strong baseline our segment-speed ETA must beat.

This is throwaway validation code. It optimizes for: never losing data, surviving
SPTrans hiccups, and being trivial to restart. It is NOT the product.

Run:
    export OLHOVIVO_TOKEN=...        # from sptrans.com.br/desenvolvedores
    python collector.py

Designed to run unattended on a VPS via `docker run --restart=always`.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

# ──────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────

# HTTPS obrigatório: a SPTrans desativou o acesso via HTTP em 01/02/2024.
API_BASE = "https://api.olhovivo.sptrans.com.br/v2.1"

# TODO(breno): preencher com os termos de busca das linhas do spike.
# Use o rótulo público da linha (ex.: "8000", "477P", "6291"). Cada termo é
# resolvido para 1+ códigos internos (cl) no startup — normalmente um cl por
# sentido (ida/volta). Recomendado o trio:
#   - 1 linha de corredor congestionado e variável (ex.: Faria Lima/Rebouças/23 de Maio)
#   - 1 linha alternativa pro mesmo par O-D (caso de uso "qual chega primeiro")
#   - 1 linha de baixa variabilidade como controle
# Trio do spike, escolhido pelo GTFS estático (densidade no pico + corredores):
#   875A — Aeroporto–Perdizes: corredor congestionado/variável (cruza Av. Paulista
#          e Av. 23 de Maio). Primária — máxima variação de trânsito.
#   106A — Metrô Santana–Itaim Bibi: compartilha o trecho da Paulista com a 875A.
#          Validação cruzada — duas linhas no mesmo asfalto devem dar a mesma
#          velocidade por segmento no mesmo instante.
#   2719 — Ermelino Matarazzo–Metrô Vl. Matilde: controle estável, zona leste,
#          fora de qualquer corredor congestionado.
# Cada termo é resolvido para 1+ cl (um por sentido) no startup via /Linha/Buscar.
LINE_SEARCH_TERMS: list[str] = [
    "875A",
    "106A",
    "2719",
]

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "25"))
DB_PATH = os.environ.get("DB_PATH", "olhovivo.sqlite3")
TOKEN = os.environ.get("OLHOVIVO_TOKEN", "")
HTTP_TIMEOUT = 15  # seconds per request

# Backoff bounds for transient failures (network, 5xx, auth loss).
BACKOFF_MIN = 5
BACKOFF_MAX = 120

# Windows consoles/NSSM log files default to cp1252, which can't encode the
# arrows/accents in our log lines and raises UnicodeEncodeError on emit (the
# message is then dropped). Force UTF-8 on the streams before configuring logging.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("collector")


# ──────────────────────────────────────────────────────────────────────────
# Storage
# ──────────────────────────────────────────────────────────────────────────


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    # WAL = durable across crashes + non-blocking reads while we collect.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS lines (
            cl           INTEGER PRIMARY KEY,  -- internal SPTrans line code
            label        TEXT NOT NULL,        -- public label (lt), e.g. "8000"
            direction    INTEGER,              -- sl: 1 main, 2 secondary
            origin       TEXT,                 -- tp: terminal origem
            destination  TEXT,                 -- ts: terminal destino
            search_term  TEXT NOT NULL,
            resolved_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS positions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            line_cl       INTEGER NOT NULL,
            vehicle       TEXT NOT NULL,        -- p: vehicle prefix
            ts_vehicle    TEXT,                 -- ta: vehicle GPS timestamp (UTC, from API)
            ts_collected  TEXT NOT NULL,        -- our poll wall-clock (UTC)
            lat           REAL,                 -- py
            lng           REAL,                 -- px
            accessible    INTEGER               -- a: 1 if wheelchair accessible
        );

        -- One reading per (line, vehicle, vehicle-timestamp). The API often
        -- repeats the same ta between polls; this dedups so per-segment speed
        -- isn't biased by polling cadence.
        CREATE UNIQUE INDEX IF NOT EXISTS uq_position
            ON positions (line_cl, vehicle, ts_vehicle);

        CREATE INDEX IF NOT EXISTS ix_positions_line_time
            ON positions (line_cl, ts_vehicle);

        -- SPTrans's own ETA-to-stop, per stop per vehicle, from /Previsao/Linha.
        -- This is the baseline our segment-speed ETA must beat: at poll time we
        -- record "SPTrans predicts vehicle p reaches stop cp at HH:MM".
        CREATE TABLE IF NOT EXISTS predictions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            line_cl       INTEGER NOT NULL,
            stop_code     INTEGER,              -- cp: código da parada
            stop_name     TEXT,                 -- np
            stop_lat      REAL,                 -- py da parada
            stop_lng      REAL,                 -- px da parada
            vehicle       TEXT NOT NULL,        -- p: vehicle prefix
            predicted_arr TEXT,                 -- t: HH:MM previsto pela SPTrans
            ts_vehicle    TEXT,                 -- ta: vehicle GPS timestamp (UTC)
            ts_collected  TEXT NOT NULL,        -- our poll wall-clock (UTC)
            lat           REAL,                 -- py do veículo
            lng           REAL                  -- px do veículo
        );

        -- Dedup identical predictions between polls: same vehicle GPS fix (ta)
        -- yields the same ETA, so without this every poll re-inserts it and
        -- bloats the table by polling cadence (mirrors uq_position).
        CREATE UNIQUE INDEX IF NOT EXISTS uq_prediction
            ON predictions (line_cl, stop_code, vehicle, ts_vehicle, predicted_arr);

        CREATE INDEX IF NOT EXISTS ix_predictions_line_time
            ON predictions (line_cl, ts_vehicle);

        -- Raw responses kept verbatim for re-analysis. Throwaway spike: cheap insurance.
        CREATE TABLE IF NOT EXISTS raw_polls (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            line_cl       INTEGER NOT NULL,
            ts_collected  TEXT NOT NULL,
            payload       TEXT NOT NULL,
            kind          TEXT NOT NULL DEFAULT 'posicao'  -- 'posicao' | 'previsao'
        );
        """
    )
    # Migração: DBs criados antes do /Previsao não têm raw_polls.kind. ALTER
    # idempotente — adiciona só se faltar, sem tocar nas linhas existentes.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(raw_polls)")}
    if "kind" not in existing_cols:
        conn.execute(
            "ALTER TABLE raw_polls ADD COLUMN kind TEXT NOT NULL DEFAULT 'posicao'"
        )
    conn.commit()
    return conn


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────
# Olho Vivo client
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Line:
    cl: int
    label: str
    direction: int | None
    origin: str | None
    destination: str | None
    search_term: str


class OlhoVivo:
    """Thin client over the Olho Vivo session-cookie auth flow."""

    def __init__(self, token: str) -> None:
        if not token:
            raise RuntimeError("OLHOVIVO_TOKEN não definido")
        self._token = token
        self._session = requests.Session()
        self._authenticated = False

    def authenticate(self) -> None:
        resp = self._session.post(
            f"{API_BASE}/Login/Autenticar",
            params={"token": self._token},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        # API returns the literal `true`/`false` as JSON body.
        if resp.json() is not True:
            raise RuntimeError("Autenticação Olho Vivo falhou (token inválido?)")
        self._authenticated = True
        log.info("autenticado na Olho Vivo")

    def _get(self, path: str, params: dict) -> requests.Response:
        if not self._authenticated:
            self.authenticate()
        resp = self._session.get(f"{API_BASE}{path}", params=params, timeout=HTTP_TIMEOUT)
        # Session expired → re-auth once and retry.
        if resp.status_code in (401, 403):
            log.warning("sessão expirada (%s), re-autenticando", resp.status_code)
            self._authenticated = False
            self.authenticate()
            resp = self._session.get(
                f"{API_BASE}{path}", params=params, timeout=HTTP_TIMEOUT
            )
        resp.raise_for_status()
        return resp

    def search_lines(self, term: str) -> list[Line]:
        """Resolve a public label to internal line codes (one per direction)."""
        resp = self._get("/Linha/Buscar", {"termosBusca": term})
        out: list[Line] = []
        for item in resp.json():
            out.append(
                Line(
                    cl=item["cl"],
                    label=item.get("lt") or term,
                    direction=item.get("sl"),
                    origin=item.get("tp"),
                    destination=item.get("ts"),
                    search_term=term,
                )
            )
        return out

    def positions(self, cl: int) -> dict:
        resp = self._get("/Posicao/Linha", {"codigoLinha": cl})
        return resp.json()

    def predictions(self, cl: int) -> dict:
        """SPTrans's ETA-to-stop for every stop of the line, per vehicle."""
        resp = self._get("/Previsao/Linha", {"codigoLinha": cl})
        return resp.json()


# ──────────────────────────────────────────────────────────────────────────
# Collection loop
# ──────────────────────────────────────────────────────────────────────────


def resolve_lines(client: OlhoVivo, conn: sqlite3.Connection) -> list[Line]:
    if not LINE_SEARCH_TERMS:
        raise RuntimeError(
            "LINE_SEARCH_TERMS está vazio — preencha os códigos de linha no topo de collector.py"
        )
    resolved: list[Line] = []
    for term in LINE_SEARCH_TERMS:
        matches = client.search_lines(term)
        if not matches:
            log.warning("nenhuma linha encontrada para o termo %r", term)
            continue
        for line in matches:
            conn.execute(
                """INSERT OR REPLACE INTO lines
                   (cl, label, direction, origin, destination, search_term, resolved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    line.cl,
                    line.label,
                    line.direction,
                    line.origin,
                    line.destination,
                    line.search_term,
                    now_utc_iso(),
                ),
            )
            resolved.append(line)
            log.info(
                "linha resolvida: %s (cl=%s, sentido=%s) %s → %s",
                line.label,
                line.cl,
                line.direction,
                line.origin,
                line.destination,
            )
    conn.commit()
    if not resolved:
        raise RuntimeError("nenhuma linha resolvida — verifique LINE_SEARCH_TERMS")
    return resolved


def store_poll(conn: sqlite3.Connection, cl: int, payload: dict) -> int:
    collected = now_utc_iso()
    conn.execute(
        "INSERT INTO raw_polls (line_cl, ts_collected, payload, kind) VALUES (?, ?, ?, 'posicao')",
        (cl, collected, json.dumps(payload, separators=(",", ":"))),
    )
    inserted = 0
    skipped_no_ts = 0
    for v in payload.get("vs", []):
        ts_vehicle = v.get("ta")
        if not ts_vehicle:
            # No GPS timestamp → SQLite treats NULL as distinct in the unique
            # index, so dedup silently fails and every poll re-inserts the same
            # reading, biasing per-segment speed by polling cadence. Such a row
            # is also useless for speed analysis. The raw payload is still kept
            # in raw_polls, so we lose nothing by leaving it out of positions.
            skipped_no_ts += 1
            continue
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO positions
                   (line_cl, vehicle, ts_vehicle, ts_collected, lat, lng, accessible)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    cl,
                    str(v.get("p")),
                    ts_vehicle,
                    collected,
                    v.get("py"),
                    v.get("px"),
                    1 if v.get("a") else 0,
                ),
            )
            inserted += cur.rowcount  # 0 when the dedup index skips a repeat reading
        except sqlite3.Error as exc:
            log.error("falha ao inserir posição: %s", exc)
    if skipped_no_ts:
        log.warning(
            "linha cl=%s: %d veículo(s) sem 'ta' ignorados em positions (só em raw_polls)",
            cl,
            skipped_no_ts,
        )
    conn.commit()
    return inserted


def store_predictions(conn: sqlite3.Connection, cl: int, payload: dict) -> int:
    """Persist /Previsao/Linha: one row per (stop, vehicle) prediction."""
    collected = now_utc_iso()
    conn.execute(
        "INSERT INTO raw_polls (line_cl, ts_collected, payload, kind) VALUES (?, ?, ?, 'previsao')",
        (cl, collected, json.dumps(payload, separators=(",", ":"))),
    )
    inserted = 0
    skipped_no_ts = 0
    for stop in payload.get("ps", []):
        for v in stop.get("vs", []):
            ts_vehicle = v.get("ta")
            if not ts_vehicle:
                # Same rationale as positions: NULL ta breaks dedup and is useless
                # for matching a prediction to a real arrival. Raw payload kept.
                skipped_no_ts += 1
                continue
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO predictions
                       (line_cl, stop_code, stop_name, stop_lat, stop_lng,
                        vehicle, predicted_arr, ts_vehicle, ts_collected, lat, lng)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cl,
                        stop.get("cp"),
                        stop.get("np"),
                        stop.get("py"),
                        stop.get("px"),
                        str(v.get("p")),
                        v.get("t"),
                        ts_vehicle,
                        collected,
                        v.get("py"),
                        v.get("px"),
                    ),
                )
                inserted += cur.rowcount
            except sqlite3.Error as exc:
                log.error("falha ao inserir previsão: %s", exc)
    if skipped_no_ts:
        log.warning(
            "linha cl=%s: %d previsão(ões) sem 'ta' ignoradas (só em raw_polls)",
            cl,
            skipped_no_ts,
        )
    conn.commit()
    return inserted


_running = True


def _handle_signal(signum, _frame) -> None:
    global _running
    log.info("sinal %s recebido, encerrando após o ciclo atual", signum)
    _running = False


def main() -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    conn = open_db(DB_PATH)
    client = OlhoVivo(TOKEN)
    client.authenticate()
    lines = resolve_lines(client, conn)
    log.info(
        "coletando %d linha(s) a cada %ds → %s",
        len(lines),
        POLL_INTERVAL_SECONDS,
        DB_PATH,
    )

    backoff = BACKOFF_MIN
    ops_per_cycle = len(lines) * 2  # /Posicao + /Previsao por linha
    while _running:
        cycle_start = time.monotonic()
        seen = 0
        new_rows = 0
        pred_rows = 0
        failures = 0
        # Poll each line/endpoint independently: a single broken call (or one the
        # API momentarily 500s on) must not abort the cycle and force healthy
        # calls to be re-polled. Backoff only kicks in if the whole cycle fails,
        # which signals a systemic problem (network down, auth permanently lost).
        for line in lines:
            try:
                payload = client.positions(line.cl)
                new_rows += store_poll(conn, line.cl, payload)
                seen += len(payload.get("vs", []))
            except (requests.RequestException, RuntimeError) as exc:
                failures += 1
                log.error("posição %s (cl=%s) falhou: %s", line.label, line.cl, exc)
            try:
                pred_payload = client.predictions(line.cl)
                pred_rows += store_predictions(conn, line.cl, pred_payload)
            except (requests.RequestException, RuntimeError) as exc:
                failures += 1
                log.error("previsão %s (cl=%s) falhou: %s", line.label, line.cl, exc)

        if failures == ops_per_cycle:
            log.error("todas as chamadas falharam — backoff %ds", backoff)
            _sleep_interruptible(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
            continue

        backoff = BACKOFF_MIN  # any success resets backoff
        log.info(
            "ciclo ok — %d veículos, %d posições novas, %d previsões novas, %d/%d chamadas com falha",
            seen,
            new_rows,
            pred_rows,
            failures,
            ops_per_cycle,
        )
        elapsed = time.monotonic() - cycle_start
        _sleep_interruptible(max(0.0, POLL_INTERVAL_SECONDS - elapsed))

    conn.close()
    log.info("encerrado")
    return 0


def _sleep_interruptible(seconds: float) -> None:
    """Sleep in small slices so SIGTERM is honored promptly."""
    end = time.monotonic() + seconds
    while _running and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


if __name__ == "__main__":
    sys.exit(main())
