"""Campo de velocidade por segmento, estimado em janela móvel a partir de
amostras por par-de-fixes. Sem vazamento: speed(s, t0) usa só amostras até t0."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

import numpy as np
import pandas as pd

from analysis.trajectories import Run


def fix_pair_speeds(run: Run) -> pd.DataFrame:
    """Velocidade entre fixes consecutivos: Δs/Δt. s_mid/t_mid no ponto médio.
    Ignora pares com Δt<=0. Resolução natural do dado."""
    ds = np.diff(run.s)
    dt = np.diff(run.t_epoch)
    ok = dt > 0
    return pd.DataFrame(
        {
            "s_mid": (run.s[:-1] + run.s[1:])[ok] / 2.0,
            "t_mid": (run.t_epoch[:-1] + run.t_epoch[1:])[ok] / 2.0,
            "speed": ds[ok] / dt[ok],
        }
    )


@dataclass
class SpeedField:
    samples: pd.DataFrame  # colunas seg, t_mid, speed (ordenado por t_mid)
    segment_m: float
    window_s: float
    free_flow: float
    last_was_fallback: bool = dc_field(default=False)

    @classmethod
    def from_runs(
        cls, runs: list[Run], *, segment_m: float, window_s: float, free_flow: float
    ) -> "SpeedField":
        frames = [fix_pair_speeds(r) for r in runs]
        samp = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=["s_mid", "t_mid", "speed"])
        )
        samp["seg"] = (samp["s_mid"] // segment_m).astype("int64") if len(samp) else []
        samp = samp.sort_values("t_mid").reset_index(drop=True)
        return cls(samp, segment_m, window_s, free_flow)

    def speed(self, s: float, t0_epoch: float) -> float:
        """Mediana das amostras do segmento de `s` na janela (t0-window, t0].
        Fallback para free_flow quando não há amostra. Marca last_was_fallback."""
        seg = int(s // self.segment_m)
        m = self.samples
        sel = m[
            (m["seg"] == seg)
            & (m["t_mid"] <= t0_epoch)
            & (m["t_mid"] > t0_epoch - self.window_s)
        ]
        if len(sel) == 0:
            self.last_was_fallback = True
            return self.free_flow
        self.last_was_fallback = False
        return float(sel["speed"].median())
