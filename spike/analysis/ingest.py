"""Carrega dados reais: SQLite do coletor + GTFS congelado + link cl->shape."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
import sqlite3

import pandas as pd
from shapely.geometry import LineString

from analysis.match import _TO_UTM


def load_positions(db_path: str, cl: int) -> pd.DataFrame:
    """Posições de uma linha (cl), ordenadas por veículo/tempo. ts em UTC."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT vehicle, ts_vehicle, lat, lng FROM positions "
            "WHERE line_cl = ? AND ts_vehicle IS NOT NULL ORDER BY vehicle, ts_vehicle",
            conn,
            params=(cl,),
        )
    finally:
        conn.close()
    df = df.rename(columns={"ts_vehicle": "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df[["vehicle", "ts", "lat", "lng"]]


def load_shape_for_route(gtfs_dir: str, route_short_name: str, direction_id: int) -> LineString:
    """Carrega o shape DOMINANTE (mais trips) de uma rota+sentido, projetado em UTM.
    Loga o casamento e shapes alternativos pra auditoria (maior risco do spike)."""
    g = Path(gtfs_dir)
    # SPTrans sufixa o route_short_name com a variante (ex.: "875A-10"), mas o
    # Olho Vivo usa só "875A". Casa por igualdade OU pela base (antes do "-").
    def _matches(sn: str) -> bool:
        return sn == route_short_name or sn.split("-")[0] == route_short_name

    route_ids = {
        r["route_id"]
        for r in _read_csv(g / "routes.txt")
        if _matches(r.get("route_short_name", ""))
    }
    if not route_ids:
        raise ValueError(f"route_short_name {route_short_name!r} não achado no GTFS")
    shape_counts: Counter[str] = Counter()
    for t in _read_csv(g / "trips.txt"):
        if t["route_id"] in route_ids and t.get("direction_id") == str(direction_id):
            if t.get("shape_id"):
                shape_counts[t["shape_id"]] += 1
    if not shape_counts:
        raise ValueError(f"sem shape para {route_short_name} sentido {direction_id}")
    shape_id, n = shape_counts.most_common(1)[0]
    print(
        f"[link] {route_short_name} dir={direction_id} -> shape={shape_id} "
        f"({n} trips); alternativos={dict(shape_counts)}"
    )
    return _load_shape_geometry(g / "shapes.txt", shape_id)


def _load_shape_geometry(shapes_csv: Path, shape_id: str) -> LineString:
    pts: list[tuple[int, float, float]] = []
    for row in _read_csv(shapes_csv):
        if row["shape_id"] == shape_id:
            pts.append(
                (
                    int(row["shape_pt_sequence"]),
                    float(row["shape_pt_lat"]),
                    float(row["shape_pt_lon"]),
                )
            )
    pts.sort()
    xs, ys = _TO_UTM.transform([p[2] for p in pts], [p[1] for p in pts])
    return LineString(list(zip(xs, ys)))


def _read_csv(path: Path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)
