"""Runner do Bloco A sobre o SQLite real.

Uso:
    python -m analysis.run --db data/olhovivo.sqlite3 --gtfs data/_gtfs \\
        --route 875A --direction 0 --cl 609 --segment-m 500 --window-min 30
"""

from __future__ import annotations

import argparse

import pandas as pd

from analysis.baselines import constant_speed_travel_time
from analysis.eta import project_travel_time
from analysis.ingest import load_positions, load_shape_for_route
from analysis.match import match_df, to_utm
from analysis.report import summarize, verdict
from analysis.speed_field import SpeedField
from analysis.trajectories import split_runs

HORIZONS_M = [500.0, 1000.0, 2000.0, 4000.0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--gtfs", required=True)
    ap.add_argument("--route", required=True)
    ap.add_argument("--direction", type=int, required=True)
    ap.add_argument("--cl", type=int, required=True, help="código interno da linha/sentido")
    ap.add_argument("--segment-m", type=float, default=500.0)
    ap.add_argument("--window-min", type=float, default=30.0)
    ap.add_argument("--free-flow", type=float, default=8.0)
    args = ap.parse_args()

    line = load_shape_for_route(args.gtfs, args.route, args.direction)
    pos = load_positions(args.db, args.cl)
    print(f"posições: {len(pos)}; comprimento shape: {round(line.length)} m")
    pos = match_df(to_utm(pos), line)
    print(f"após snap (<=80m): {len(pos)}  (erro snap mediano {pos['snap_err'].median():.1f} m)")
    runs = split_runs(pos)
    print(f"passadas reconstruídas: {len(runs)}")
    field = SpeedField.from_runs(
        runs, segment_m=args.segment_m, window_s=args.window_min * 60, free_flow=args.free_flow
    )

    rows: list[dict] = []
    fallbacks = 0
    for run in runs:
        for idx in range(0, len(run.s), 2):
            s0, t0 = float(run.s[idx]), float(run.t_epoch[idx])
            for h in HORIZONS_M:
                t_real = run.time_at(s0 + h)
                if t_real is None or (t_real - t0) <= 0:
                    continue
                actual = t_real - t0
                pred = project_travel_time(field, s0, t0, s0 + h)
                fallbacks += int(field.last_was_fallback)
                base = constant_speed_travel_time(run, idx, h)
                rows.append(
                    {
                        "horizon_m": h,
                        "actual_s": actual,
                        "abs_err_s": abs(pred - actual),
                        "abs_err_pct": abs(pred - actual) / actual,
                        "base_abs_err_pct": (abs(base - actual) / actual)
                        if base != float("inf")
                        else float("nan"),
                    }
                )
    df = pd.DataFrame(rows)
    if df.empty:
        print("SEM EVENTOS — dados insuficientes (rode mais tarde / verifique o link)")
        return 1

    print("\n=== erro do MODELO por horizonte ===")
    print(summarize(df, group="horizon_m").round(3))
    m = df["abs_err_pct"].median()
    b = df["base_abs_err_pct"].median()
    print(f"\nmodelo p50%={m:.3f}  baseline(vel.const) p50%={b:.3f}")
    print(f"taxa de fallback de velocidade: {fallbacks / max(len(df),1):.2%}")
    print(f"\n>>> VEREDITO: {verdict(model_p50_pct=m, baseline_p50_pct=b)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
