"""
Snapshot the SPTrans static GTFS at collection start — ETA-engine spike.

The offline analysis map-matches collected positions onto the line shapes from
the static GTFS. Those shapes drift over time (re-routes, new trips), so the
shape MUST be the one in effect during collection. Run this ONCE, at T0, before
(or alongside) starting the collector, and keep the resulting zip untouched.

The SPTrans GTFS is published on the developer portal and the direct link can
change / sit behind a login. Pass the URL you actually have access to:

    export GTFS_URL="https://.../gtfs-sptrans.zip"
    python snapshot_gtfs.py

Or, if you downloaded the zip by hand, just drop it in ./data/ named
`gtfs-snapshot-<YYYY-MM-DD>.zip` and skip this script — the analysis only needs
the file to exist with a date.
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import date

import requests

GTFS_URL = os.environ.get("GTFS_URL", "")
OUT_DIR = os.environ.get("GTFS_OUT_DIR", "data")
HTTP_TIMEOUT = 120  # GTFS zips are tens of MB


def main() -> int:
    if not GTFS_URL:
        print(
            "GTFS_URL não definido. Baixe o GTFS estático do portal SPTrans "
            "(sptrans.com.br/desenvolvedores) e exporte a URL, ou coloque o zip "
            "manualmente em ./data/gtfs-snapshot-<YYYY-MM-DD>.zip",
            file=sys.stderr,
        )
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"gtfs-snapshot-{date.today().isoformat()}.zip")
    if os.path.exists(out_path):
        print(f"snapshot já existe, não sobrescrevendo: {out_path}", file=sys.stderr)
        return 0

    print(f"baixando GTFS de {GTFS_URL} ...", file=sys.stderr)
    sha = hashlib.sha256()
    total = 0
    with requests.get(GTFS_URL, stream=True, timeout=HTTP_TIMEOUT) as resp:
        resp.raise_for_status()
        with open(out_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
                sha.update(chunk)
                total += len(chunk)

    print(f"salvo {out_path} ({total / 1e6:.1f} MB)", file=sys.stderr)
    print(f"sha256 {sha.hexdigest()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
