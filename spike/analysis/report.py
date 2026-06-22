"""Agrega o erro por horizonte e emite o veredito go/no-go."""

from __future__ import annotations

import pandas as pd

# Critério go (Seção 1 do spec).
MIN_IMPROVEMENT = 0.25   # >=25% melhor que o melhor baseline
MAX_MEDIAN_PCT = 0.15    # erro mediano <= 15% do tempo de viagem


def summarize(df: pd.DataFrame, *, group: str) -> pd.DataFrame:
    """P50/P90 do erro absoluto (s e %) por grupo (ex.: horizon_m)."""
    g = df.groupby(group)
    return pd.DataFrame(
        {
            "n": g.size(),
            "p50_abs_err_s": g["abs_err_s"].median(),
            "p90_abs_err_s": g["abs_err_s"].quantile(0.9),
            "p50_abs_err_pct": g["abs_err_pct"].median(),
            "p90_abs_err_pct": g["abs_err_pct"].quantile(0.9),
        }
    )


def verdict(*, model_p50_pct: float, baseline_p50_pct: float) -> str:
    """GO se o modelo bate o baseline em >=MIN_IMPROVEMENT E erro <= MAX_MEDIAN_PCT."""
    beats = baseline_p50_pct > 0 and (
        (baseline_p50_pct - model_p50_pct) / baseline_p50_pct >= MIN_IMPROVEMENT
    )
    usable = model_p50_pct <= MAX_MEDIAN_PCT
    return "GO" if (beats and usable) else "NO-GO"
