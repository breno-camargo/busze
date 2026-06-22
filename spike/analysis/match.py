"""Map-matching por linear referencing: ponto -> distância no shape."""

from __future__ import annotations

import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point

# WGS84 -> SIRGAS 2000 / UTM 23S (São Paulo), métrico.
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)


def match_point(line: LineString, x: float, y: float) -> tuple[float, float]:
    """Retorna (s, snap_err): distância ao longo do shape e distância perpendicular."""
    p = Point(x, y)
    s = line.project(p)
    snap_err = p.distance(line)
    return s, snap_err


def match_df(df: pd.DataFrame, line: LineString, *, max_snap_m: float = 80.0) -> pd.DataFrame:
    """Adiciona colunas s e snap_err; descarta pontos a mais de max_snap_m do shape.
    Espera colunas x, y (metros). Preserva as demais colunas."""
    s_vals, snap_vals = [], []
    for x, y in zip(df["x"].to_numpy(), df["y"].to_numpy()):
        s, snap = match_point(line, float(x), float(y))
        s_vals.append(s)
        snap_vals.append(snap)
    out = df.copy()
    out["s"] = s_vals
    out["snap_err"] = snap_vals
    return out[out["snap_err"] <= max_snap_m].reset_index(drop=True)


def to_utm(df: pd.DataFrame, *, lat_col: str = "lat", lng_col: str = "lng") -> pd.DataFrame:
    """Adiciona colunas x, y (UTM 23S) a partir de lat/lng. Caminho de dado real."""
    x, y = _TO_UTM.transform(df[lng_col].to_numpy(), df[lat_col].to_numpy())
    out = df.copy()
    out["x"] = x
    out["y"] = y
    return out
