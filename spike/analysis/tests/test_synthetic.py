from datetime import datetime, timezone

import numpy as np

from analysis.synthetic import make_run, straight_shape


def test_straight_shape_length():
    line = straight_shape(length_m=2000.0)
    assert abs(line.length - 2000.0) < 1e-6


def test_make_run_recovers_known_speed():
    # Um veículo, velocidade constante 10 m/s, sem ruído, cadência 25s.
    t0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    df = make_run(
        vehicle="v1",
        start_t=t0,
        speed_profile=[(0.0, 2000.0, 10.0)],  # de 0 a 2000m a 10 m/s
        cadence_s=25.0,
        noise_m=0.0,
    )
    assert set(df.columns) == {"vehicle", "ts", "x", "y", "s_true"}
    assert (df["vehicle"] == "v1").all()
    # s_true monotônico e velocidade implícita ~10 m/s
    ds = np.diff(df["s_true"].to_numpy())
    dt = np.diff(df["ts"].astype("int64").to_numpy()) / 1e9
    np.testing.assert_allclose(ds / dt, 10.0, rtol=1e-6)


def test_make_run_applies_noise():
    t0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    df = make_run("v1", t0, [(0.0, 1000.0, 8.0)], cadence_s=25.0, noise_m=5.0, seed=1)
    # com ruído, y desvia da linha (y=0); desvio na ordem de noise_m
    assert df["y"].abs().mean() > 0.5
