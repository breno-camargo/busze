from datetime import datetime, timezone

from analysis.eta import project_travel_time
from analysis.speed_field import SpeedField
from analysis.synthetic import make_run, straight_shape
from analysis.match import match_df
from analysis.trajectories import split_runs


def _field(speed):
    t0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    df = make_run("v1", t0, [(0.0, 3000.0, speed)], cadence_s=25.0, noise_m=0.0)
    df = match_df(df, straight_shape(3000.0))
    runs = split_runs(df, min_points=3)
    return SpeedField.from_runs(runs, segment_m=500.0, window_s=3600.0, free_flow=speed), runs


def test_project_constant_speed():
    field, runs = _field(10.0)
    t_end = runs[0].t_epoch[-1]
    # de 0 a 2000m a 10 m/s -> 200s
    tt = project_travel_time(field, s0=0.0, t0_epoch=t_end, s_target=2000.0)
    assert abs(tt - 200.0) < 5.0


def test_project_zero_distance():
    field, runs = _field(10.0)
    tt = project_travel_time(field, 1000.0, runs[0].t_epoch[-1], 1000.0)
    assert tt == 0.0
