"""Baselines ingênuos que o motor de ETA precisa bater.

constant_speed: velocidade média recente do próprio ônibus.
(GTFS schedule e Previsão SPTrans vivem no caminho de dado real — Task 9/10.)"""

from __future__ import annotations

import numpy as np

from analysis.trajectories import Run


def constant_speed_travel_time(
    run: Run, idx: int, distance_m: float, *, lookback_s: float = 120.0
) -> float:
    """Tempo previsto pra percorrer distance_m assumindo a velocidade média do
    veículo nos últimos lookback_s antes de run.t_epoch[idx]. inf se parado."""
    t_now = run.t_epoch[idx]
    mask = (run.t_epoch <= t_now) & (run.t_epoch >= t_now - lookback_s)
    ts, ss = run.t_epoch[mask], run.s[mask]
    if len(ts) < 2 or (ts[-1] - ts[0]) <= 0:
        return float("inf")
    v = (ss[-1] - ss[0]) / (ts[-1] - ts[0])
    if v <= 0:
        return float("inf")
    return distance_m / v
