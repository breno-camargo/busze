"""Gera dados sintéticos com velocidade conhecida, base do TDD do pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from shapely.geometry import LineString

# Segmento do perfil de velocidade: do metro `s_ini` ao `s_fim`, a `speed` m/s.
SpeedSegment = tuple[float, float, float]


def straight_shape(length_m: float) -> LineString:
    """Shape reto ao longo do eixo x (y=0), em metros planos."""
    return LineString([(0.0, 0.0), (length_m, 0.0)])


def make_run(
    vehicle: str,
    start_t: datetime,
    speed_profile: list[SpeedSegment],
    *,
    cadence_s: float = 25.0,
    noise_m: float = 0.0,
    seed: int | None = None,
) -> pd.DataFrame:
    """Simula uma passada: amostra (ts, x, y) a cada `cadence_s`, andando pelo
    perfil de velocidade dado. `s_true` é a distância real percorrida (sem ruído).
    x recebe `s_true`; y recebe ruído gaussiano (off-shape). Retorna DataFrame
    com colunas vehicle, ts, x, y, s_true."""
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    t = 0.0  # segundos desde start_t
    for s_ini, s_fim, speed in speed_profile:
        s = s_ini
        while s < s_fim:
            ts = start_t + timedelta(seconds=t)
            y = rng.normal(0.0, noise_m) if noise_m > 0 else 0.0
            x = s + (rng.normal(0.0, noise_m) if noise_m > 0 else 0.0)
            rows.append({"vehicle": vehicle, "ts": ts, "x": x, "y": y, "s_true": s})
            s += speed * cadence_s
            t += cadence_s
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
