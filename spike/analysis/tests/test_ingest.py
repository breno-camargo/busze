import sqlite3

from analysis.ingest import load_positions, load_shape_for_route


def _write_min_gtfs(d):
    # GTFS mínimo: route_short_name com sufixo de variante (estilo SPTrans).
    (d / "routes.txt").write_text(
        'route_id,route_short_name\n"875A-10","875A-10"\n', encoding="utf-8"
    )
    (d / "trips.txt").write_text(
        "route_id,direction_id,shape_id\n875A-10,0,sh1\n875A-10,0,sh1\n875A-10,1,sh2\n",
        encoding="utf-8",
    )
    (d / "shapes.txt").write_text(
        "shape_id,shape_pt_sequence,shape_pt_lat,shape_pt_lon\n"
        "sh1,1,-23.55,-46.63\nsh1,2,-23.55,-46.62\n",
        encoding="utf-8",
    )


def test_load_shape_matches_base_name(tmp_path):
    # Olho Vivo manda "875A"; GTFS tem "875A-10". O link deve casar pela base.
    _write_min_gtfs(tmp_path)
    line = load_shape_for_route(str(tmp_path), "875A", direction_id=0)
    assert line.length > 500  # ~1km entre os dois pontos em SP


def test_load_positions_parses_utc(tmp_path):
    db = tmp_path / "t.sqlite3"
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE positions (line_cl INTEGER, vehicle TEXT, ts_vehicle TEXT, lat REAL, lng REAL);"
        "INSERT INTO positions VALUES (609,'1',  '2026-06-22T16:10:52Z', -23.55, -46.63);"
        "INSERT INTO positions VALUES (609,'1',  '2026-06-22T16:11:17Z', -23.551, -46.631);"
    )
    c.commit()
    c.close()
    df = load_positions(str(db), cl=609)
    assert list(df.columns) == ["vehicle", "ts", "lat", "lng"]
    assert str(df["ts"].dt.tz) == "UTC"
    assert len(df) == 2
