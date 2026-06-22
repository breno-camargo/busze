"""Reconstrói passadas (um trecho monotônico de uma viagem) por veículo."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Run:
    """Uma passada de um veículo: arrays paralelos de tempo (epoch s) e distância (m)."""

    vehicle: str
    t_epoch: np.ndarray  # segundos epoch, crescente
    s: np.ndarray        # metros ao longo do shape, não-decrescente

    @property
    def t0_epoch(self) -> float:
        return float(self.t_epoch[0])

    def time_at(self, s_target: float) -> float | None:
        """Tempo (epoch s) em que a passada cruzou s_target, por interpolação linear.
        None se s_target estiver fora do alcance coberto pela passada."""
        if s_target < self.s[0] or s_target > self.s[-1]:
            return None
        return float(np.interp(s_target, self.s, self.t_epoch))


def split_runs(
    df: pd.DataFrame,
    *,
    max_gap_s: float = 180.0,
    min_back_m: float = 200.0,
    min_points: int = 5,
) -> list[Run]:
    """Quebra os fixes (colunas vehicle, ts, s) em passadas. Nova passada quando
    o tempo salta > max_gap_s ou s recua > min_back_m. Descarta passadas com menos
    de min_points e força s não-decrescente (remove ruído de recuo pequeno)."""
    runs: list[Run] = []
    for vehicle, g in df.sort_values(["vehicle", "ts"]).groupby("vehicle", sort=False):
        t = g["ts"].astype("int64").to_numpy() / 1e9
        s = g["s"].to_numpy(dtype=float)
        start = 0
        for i in range(1, len(g) + 1):
            cut = i == len(g)
            if not cut:
                gap = t[i] - t[i - 1]
                back = s[i] < s[i - 1] - min_back_m
                cut = gap > max_gap_s or back
            if cut:
                seg_t, seg_s = t[start:i], s[start:i]
                if len(seg_t) >= min_points:
                    runs.append(Run(str(vehicle), seg_t, np.maximum.accumulate(seg_s)))
                start = i
    return runs
