from datetime import datetime, timezone

import pandas as pd

from analysis.trajectories import Run, split_runs


def _df(rows):
    df = pd.DataFrame(rows, columns=["vehicle", "ts", "s"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def test_split_on_time_gap():
    t = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(6):  # passada 1: s sobe
        rows.append(("v1", t.replace(second=i * 25 % 60, minute=i * 25 // 60), i * 100.0))
    # gap de 10 min e recomeça
    rows.append(("v1", datetime(2026, 6, 22, 12, 15, 0, tzinfo=timezone.utc), 0.0))
    rows.append(("v1", datetime(2026, 6, 22, 12, 15, 25, tzinfo=timezone.utc), 120.0))
    runs = split_runs(_df(rows), max_gap_s=180, min_points=2)
    assert len(runs) == 2
    assert runs[0].vehicle == "v1"


def test_run_time_at_interpolates():
    t = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    rows = [("v1", t.replace(second=s), float(s) * 10.0) for s in (0, 25, 50)]
    run = split_runs(_df(rows), min_points=2)[0]
    # em s=250m (entre 0 e 500m), a ~10 m/s, deve dar t≈25s
    secs = run.time_at(250.0)
    assert abs(secs - run.t0_epoch - 25.0) < 1e-6


def test_run_time_at_out_of_range_returns_none():
    t = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    rows = [("v1", t.replace(second=s), float(s) * 10.0) for s in (0, 25)]
    run = split_runs(_df(rows), min_points=2)[0]
    assert run.time_at(99999.0) is None
