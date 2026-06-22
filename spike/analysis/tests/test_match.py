import numpy as np
import pandas as pd

from analysis.match import match_df, match_point, to_utm
from analysis.synthetic import straight_shape


def test_match_point_on_line():
    line = straight_shape(1000.0)
    s, snap = match_point(line, 250.0, 0.0)
    assert abs(s - 250.0) < 1e-6
    assert abs(snap - 0.0) < 1e-6


def test_match_point_off_line():
    line = straight_shape(1000.0)
    s, snap = match_point(line, 250.0, 7.0)  # 7m fora da linha
    assert abs(s - 250.0) < 1e-6
    assert abs(snap - 7.0) < 1e-6


def test_match_df_drops_far_points():
    line = straight_shape(1000.0)
    df = pd.DataFrame({"x": [100.0, 200.0], "y": [2.0, 500.0]})  # 2º ponto longe
    out = match_df(df, line, max_snap_m=80.0)
    assert len(out) == 1
    assert abs(out.iloc[0]["s"] - 100.0) < 1e-6


def test_to_utm_roundtrip_scale():
    # Dois pontos ~1km de distância em SP devem dar ~1000m em UTM.
    df = pd.DataFrame({"lat": [-23.55, -23.55], "lng": [-46.63, -46.6202]})
    out = to_utm(df)
    d = np.hypot(out.iloc[1]["x"] - out.iloc[0]["x"], out.iloc[1]["y"] - out.iloc[0]["y"])
    assert 800 < d < 1200
