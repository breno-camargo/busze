import numpy as np

from analysis.baselines import constant_speed_travel_time
from analysis.trajectories import Run


def test_constant_speed_uses_recent_average():
    # passada a 10 m/s; média recente ~10; 1000m -> ~100s
    t = np.arange(0, 250, 25, dtype=float)
    s = t * 10.0
    run = Run("v1", t + 1_000_000.0, s)
    tt = constant_speed_travel_time(run, idx=len(t) - 1, distance_m=1000.0, lookback_s=120.0)
    assert abs(tt - 100.0) < 5.0


def test_constant_speed_handles_stopped():
    # parado nos últimos fixes -> velocidade ~0 -> tempo infinito (cap)
    t = np.array([0.0, 25.0, 50.0, 75.0]) + 1_000_000.0
    s = np.array([0.0, 250.0, 250.0, 250.0])
    run = Run("v1", t, s)
    tt = constant_speed_travel_time(run, idx=3, distance_m=1000.0, lookback_s=60.0)
    assert tt == float("inf")
