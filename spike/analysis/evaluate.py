"""Gera eventos de predição e mede o erro do modelo contra a realidade observada."""

from __future__ import annotations

import pandas as pd

from analysis.eta import project_travel_time
from analysis.speed_field import SpeedField
from analysis.trajectories import Run


def evaluate_runs(
    runs: list[Run], field: SpeedField, *, horizons_m: list[float], stride: int = 2
) -> pd.DataFrame:
    """Para cada passada e cada fix (a cada `stride`), projeta o tempo de viagem
    até s0+horizonte e compara com o tempo real da própria passada. Bucketiza
    pelo tempo real de viagem. Retorna DataFrame com uma linha por evento."""
    rows: list[dict] = []
    for run in runs:
        n = len(run.s)
        for idx in range(0, n, stride):
            s0, t0 = float(run.s[idx]), float(run.t_epoch[idx])
            for h in horizons_m:
                s_target = s0 + h
                t_real = run.time_at(s_target)
                if t_real is None:
                    continue
                actual = t_real - t0
                if actual <= 0:
                    continue
                pred = project_travel_time(field, s0, t0, s_target)
                rows.append(
                    {
                        "vehicle": run.vehicle,
                        "horizon_m": h,
                        "actual_s": actual,
                        "pred_s": pred,
                        "err_s": pred - actual,
                        "abs_err_s": abs(pred - actual),
                        "abs_err_pct": abs(pred - actual) / actual,
                    }
                )
    return pd.DataFrame(rows)
