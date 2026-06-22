from datetime import datetime, timedelta, timezone

import pandas as pd

from analysis.evaluate import evaluate_runs
from analysis.match import match_df
from analysis.speed_field import SpeedField
from analysis.synthetic import make_run, straight_shape
from analysis.trajectories import split_runs


def _setup(profile, n_vehicles=8, headway_s=120.0):
    t0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    frames = []
    for i in range(n_vehicles):
        start = t0 + timedelta(seconds=i * headway_s)
        frames.append(make_run(f"v{i}", start, profile, cadence_s=25.0, noise_m=0.0))
    df = pd.concat(frames, ignore_index=True)
    df = match_df(df, straight_shape(profile[-1][1]))
    runs = split_runs(df, min_points=5)
    field = SpeedField.from_runs(runs, segment_m=500.0, window_s=1800.0, free_flow=10.0)
    return runs, field


def test_model_error_near_zero_when_stationary():
    # trânsito constante 10 m/s em toda a linha de 4km
    runs, field = _setup([(0.0, 4000.0, 10.0)])
    res = evaluate_runs(runs, field, horizons_m=[500.0, 1000.0, 2000.0])
    assert len(res) > 0
    # erro absoluto mediano do modelo bem pequeno (sem ruído, trânsito estável)
    assert res["abs_err_s"].median() < 15.0


def test_recovers_congested_segment():
    # segmento do meio lento (2 m/s), resto rápido (12 m/s)
    runs, field = _setup([(0.0, 1500.0, 12.0), (1500.0, 2500.0, 2.0), (2500.0, 4000.0, 12.0)])
    # velocidade estimada no segmento congestionado deve ser bem menor que no rápido
    t_ref = max(r.t_epoch[-1] for r in runs)
    v_cong = field.speed(2000.0, t_ref)
    v_fast = field.speed(500.0, t_ref)
    assert v_cong < 4.0 < v_fast
