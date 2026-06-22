from datetime import datetime, timezone

import numpy as np

from analysis.speed_field import SpeedField, fix_pair_speeds
from analysis.synthetic import make_run, straight_shape
from analysis.match import match_df
from analysis.trajectories import split_runs


def _runs(speed):
    t0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    df = make_run("v1", t0, [(0.0, 2000.0, speed)], cadence_s=25.0, noise_m=0.0)
    df = match_df(df, straight_shape(2000.0))
    return split_runs(df, min_points=3)


def test_fix_pair_speeds_recovers_speed():
    run = _runs(10.0)[0]
    sp = fix_pair_speeds(run)
    assert set(sp.columns) == {"s_mid", "t_mid", "speed"}
    np.testing.assert_allclose(sp["speed"].to_numpy(), 10.0, rtol=1e-6)


def test_speed_field_segment_median():
    runs = _runs(10.0)
    field = SpeedField.from_runs(runs, segment_m=500.0, window_s=1800.0, free_flow=8.0)
    t0 = runs[0].t_epoch[-1]  # fim da passada
    assert abs(field.speed(250.0, t0) - 10.0) < 0.5


def test_speed_field_fallback_when_no_data():
    runs = _runs(10.0)
    field = SpeedField.from_runs(runs, segment_m=500.0, window_s=1800.0, free_flow=8.0)
    # segmento muito à frente, sem amostras -> free_flow
    assert field.speed(50000.0, runs[0].t_epoch[-1]) == 8.0
    assert field.last_was_fallback is True
