# Bloco A — Pipeline de validação do motor de ETA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir o pipeline offline que decide o go/no-go do produto: a partir de posições GPS de ônibus, estimar velocidade por segmento, projetar ETA e medir o erro contra baselines.

**Architecture:** Pipeline funcional em estágios puros (match → trajetória → campo de velocidade → ETA → avaliação), cada um num módulo focado. **Synthetic-first/TDD:** um gerador de dados sintéticos com velocidades conhecidas guia cada estágio e prova a lógica antes de qualquer dado real. O core de geometria opera em metros planos (testável sem lat/lng); a conversão WGS84→UTM fica isolada no caminho de dado real.

**Tech Stack:** Python 3.12, pandas, numpy, shapely, pyproj, pytest. Throwaway (spike), roda offline sobre o SQLite coletado.

**Spec:** `docs/superpowers/specs/2026-06-22-bloco-a-analise-eta-design.md`

---

## File Structure

Tudo sob `spike/analysis/` (pacote Python). Um módulo por responsabilidade:

- `spike/analysis/__init__.py` — marca o pacote.
- `spike/analysis/requirements.txt` — deps da análise (separadas do coletor).
- `spike/analysis/synthetic.py` — gera shapes + passadas com velocidades conhecidas (base do TDD).
- `spike/analysis/match.py` — map-matching: projeção de ponto em LineString (metros) + conversão UTM.
- `spike/analysis/trajectories.py` — reconstrução de passadas por veículo + interpolação s↔t.
- `spike/analysis/speed_field.py` — velocidade por par-de-fixes → campo de velocidade por segmento (janela móvel + fallback).
- `spike/analysis/eta.py` — projeção de ETA (soma de comprimento/velocidade).
- `spike/analysis/baselines.py` — baselines (velocidade constante; GTFS e Previsão no caminho de dado real).
- `spike/analysis/evaluate.py` — amostragem de eventos, erro por horizonte, agregação.
- `spike/analysis/ingest.py` — leitura do SQLite (positions/predictions) + GTFS + link cl→shape.
- `spike/analysis/report.py` — relatório de erro vs baselines + veredito go/no-go.
- `spike/analysis/run.py` — CLI que liga tudo sobre o SQLite real.
- `spike/analysis/tests/` — testes pytest por módulo.

Tipos de intercâmbio: **pandas DataFrame** entre estágios (colunas explícitas, documentadas em cada task) e pequenas dataclasses para `Run` e `SpeedField`. Datas sempre `datetime` tz-aware UTC; distâncias em metros; velocidades em m/s.

---

## Task 1: Scaffolding do pacote

**Files:**
- Create: `spike/analysis/__init__.py`
- Create: `spike/analysis/requirements.txt`
- Create: `spike/analysis/tests/__init__.py`
- Create: `spike/analysis/tests/conftest.py`

- [ ] **Step 1: Criar o pacote e deps**

`spike/analysis/__init__.py`:

```python
"""Pipeline de validação do motor de ETA (spike, throwaway)."""
```

`spike/analysis/requirements.txt`:

```
pandas==2.2.3
numpy==2.1.3
shapely==2.0.6
pyproj==3.7.0
pytest==8.3.4
```

`spike/analysis/tests/__init__.py`: (arquivo vazio)

`spike/analysis/tests/conftest.py`:

```python
import sys
from pathlib import Path

# Permite `import analysis.x` rodando pytest de dentro de spike/.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
```

- [ ] **Step 2: Criar venv e instalar deps**

Run (de `spike/`):
```bash
python -m venv .venv-analysis
.venv-analysis/Scripts/pip install -r analysis/requirements.txt   # Windows
# ou: .venv-analysis/bin/pip install -r analysis/requirements.txt
```
Expected: instala sem erro; `pip list` mostra pandas/numpy/shapely/pyproj/pytest.

- [ ] **Step 3: Verificar pytest coleta zero testes**

Run (de `spike/`): `.venv-analysis/Scripts/pytest analysis -q`
Expected: "no tests ran" (exit 5) — pacote importável, nada quebrado.

- [ ] **Step 4: Commit**

```bash
git add spike/analysis
git commit -m "Scaffolding do pacote de analise do Bloco A"
```

---

## Task 2: Gerador de dados sintéticos

Base do TDD: gera passadas de veículos ao longo de um shape reto (em metros planos), com **velocidade por segmento conhecida**, ruído de GPS e cadência configurável. Saída: DataFrame de "fixes".

**Files:**
- Create: `spike/analysis/synthetic.py`
- Test: `spike/analysis/tests/test_synthetic.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_synthetic.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_synthetic.py -v`
Expected: FAIL (ModuleNotFoundError: analysis.synthetic).

- [ ] **Step 3: Implementar**

`spike/analysis/synthetic.py`:

```python
"""Gera dados sintéticos com velocidade conhecida, base do TDD do pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from shapely.geometry import LineString

# Segmento do perfil de velocidade: do metro `s_ini` ao `s_fim`, a `speed` m/s.
SpeedSegment = tuple[float, float, float]


def straight_shape(length_m: float) -> LineString:
    """Shape reto ao longo do eixo x (y=0), em metros planos."""
    return LineString([(0.0, 0.0), (length_m, 0.0)])


def make_run(
    vehicle: str,
    start_t: datetime,
    speed_profile: list[SpeedSegment],
    *,
    cadence_s: float = 25.0,
    noise_m: float = 0.0,
    seed: int | None = None,
) -> pd.DataFrame:
    """Simula uma passada: amostra (ts, x, y) a cada `cadence_s`, andando pelo
    perfil de velocidade dado. `s_true` é a distância real percorrida (sem ruído).
    x recebe `s_true`; y recebe ruído gaussiano (off-shape). Retorna DataFrame
    com colunas vehicle, ts, x, y, s_true."""
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    t = 0.0  # segundos desde start_t
    for s_ini, s_fim, speed in speed_profile:
        s = s_ini
        while s < s_fim:
            ts = start_t + timedelta(seconds=t)
            y = rng.normal(0.0, noise_m) if noise_m > 0 else 0.0
            x = s + (rng.normal(0.0, noise_m) if noise_m > 0 else 0.0)
            rows.append({"vehicle": vehicle, "ts": ts, "x": x, "y": y, "s_true": s})
            s += speed * cadence_s
            t += cadence_s
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_synthetic.py -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add spike/analysis/synthetic.py spike/analysis/tests/test_synthetic.py
git commit -m "Gerador de dados sinteticos do Bloco A"
```

---

## Task 3: Map-matching (linear referencing)

Projeta cada `(x, y)` na LineString → distância acumulada `s` + erro de snap. Isola a conversão WGS84→UTM para o caminho de dado real.

**Files:**
- Create: `spike/analysis/match.py`
- Test: `spike/analysis/tests/test_match.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_match.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_match.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

`spike/analysis/match.py`:

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_match.py -v`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add spike/analysis/match.py spike/analysis/tests/test_match.py
git commit -m "Map-matching por linear referencing"
```

---

## Task 4: Reconstrução de trajetórias (passadas)

Agrupa fixes por veículo, ordena por tempo, quebra em passadas (gap longo ou recuo de `s`), e expõe interpolação s↔t por passada.

**Files:**
- Create: `spike/analysis/trajectories.py`
- Test: `spike/analysis/tests/test_trajectories.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_trajectories.py`:

```python
from datetime import datetime, timezone

import pandas as pd

from analysis.trajectories import Run, split_runs


def _df(rows):
    df = pd.DataFrame(rows, columns=["vehicle", "ts", "s"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def test_split_on_time_gap():
    t = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(6):  # passada 1: s sobe
        rows.append(("v1", t.replace(second=i * 25 % 60, minute=i * 25 // 60), i * 100.0))
    # gap de 10 min e recomeça
    rows.append(("v1", datetime(2026, 6, 22, 12, 15, 0, tzinfo=timezone.utc), 0.0))
    rows.append(("v1", datetime(2026, 6, 22, 12, 15, 25, tzinfo=timezone.utc), 120.0))
    runs = split_runs(_df(rows), max_gap_s=180, min_points=2)
    assert len(runs) == 2
    assert runs[0].vehicle == "v1"


def test_run_time_at_interpolates():
    t = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    rows = [("v1", t.replace(second=s), float(s) * 10.0) for s in (0, 25, 50)]
    run = split_runs(_df(rows), min_points=2)[0]
    # em s=250m (entre 0 e 500m), a ~10 m/s, deve dar t≈25s
    secs = run.time_at(250.0)
    assert abs(secs - run.t0_epoch - 25.0) < 1e-6


def test_run_time_at_out_of_range_returns_none():
    t = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    rows = [("v1", t.replace(second=s), float(s) * 10.0) for s in (0, 25)]
    run = split_runs(_df(rows), min_points=2)[0]
    assert run.time_at(99999.0) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_trajectories.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

`spike/analysis/trajectories.py`:

```python
"""Reconstrói passadas (um trecho monotônico de uma viagem) por veículo."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Run:
    """Uma passada de um veículo: arrays paralelos de tempo (epoch s) e distância (m)."""

    vehicle: str
    t_epoch: np.ndarray  # segundos epoch, crescente
    s: np.ndarray        # metros ao longo do shape, não-decrescente

    @property
    def t0_epoch(self) -> float:
        return float(self.t_epoch[0])

    def time_at(self, s_target: float) -> float | None:
        """Tempo (epoch s) em que a passada cruzou s_target, por interpolação linear.
        None se s_target estiver fora do alcance coberto pela passada."""
        if s_target < self.s[0] or s_target > self.s[-1]:
            return None
        return float(np.interp(s_target, self.s, self.t_epoch))


def split_runs(
    df: pd.DataFrame,
    *,
    max_gap_s: float = 180.0,
    min_back_m: float = 200.0,
    min_points: int = 5,
) -> list[Run]:
    """Quebra os fixes (colunas vehicle, ts, s) em passadas. Nova passada quando
    o tempo salta > max_gap_s ou s recua > min_back_m. Descarta passadas com menos
    de min_points e força s não-decrescente (remove ruído de recuo pequeno)."""
    runs: list[Run] = []
    for vehicle, g in df.sort_values(["vehicle", "ts"]).groupby("vehicle", sort=False):
        t = g["ts"].astype("int64").to_numpy() / 1e9
        s = g["s"].to_numpy(dtype=float)
        start = 0
        for i in range(1, len(g) + 1):
            cut = i == len(g)
            if not cut:
                gap = t[i] - t[i - 1]
                back = s[i] < s[i - 1] - min_back_m
                cut = gap > max_gap_s or back
            if cut:
                seg_t, seg_s = t[start:i], s[start:i]
                if len(seg_t) >= min_points:
                    runs.append(Run(str(vehicle), seg_t, np.maximum.accumulate(seg_s)))
                start = i
    return runs
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_trajectories.py -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add spike/analysis/trajectories.py spike/analysis/tests/test_trajectories.py
git commit -m "Reconstrucao de passadas por veiculo"
```

---

## Task 5: Campo de velocidade por segmento

Velocidade por par-de-fixes (Δs/Δt) → amostras com timestamp → agregação por segmento em janela móvel, com fallback.

**Files:**
- Create: `spike/analysis/speed_field.py`
- Test: `spike/analysis/tests/test_speed_field.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_speed_field.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_speed_field.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

`spike/analysis/speed_field.py`:

```python
"""Campo de velocidade por segmento, estimado em janela móvel a partir de
amostras por par-de-fixes. Sem vazamento: speed(s, t0) usa só amostras até t0."""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

import numpy as np
import pandas as pd

from analysis.trajectories import Run


def fix_pair_speeds(run: Run) -> pd.DataFrame:
    """Velocidade entre fixes consecutivos: Δs/Δt. s_mid/t_mid no ponto médio.
    Ignora pares com Δt<=0. Resolução natural do dado."""
    ds = np.diff(run.s)
    dt = np.diff(run.t_epoch)
    ok = dt > 0
    return pd.DataFrame(
        {
            "s_mid": (run.s[:-1] + run.s[1:])[ok] / 2.0,
            "t_mid": (run.t_epoch[:-1] + run.t_epoch[1:])[ok] / 2.0,
            "speed": ds[ok] / dt[ok],
        }
    )


@dataclass
class SpeedField:
    samples: pd.DataFrame  # colunas seg, t_mid, speed (ordenado por t_mid)
    segment_m: float
    window_s: float
    free_flow: float
    last_was_fallback: bool = dc_field(default=False)

    @classmethod
    def from_runs(
        cls, runs: list[Run], *, segment_m: float, window_s: float, free_flow: float
    ) -> "SpeedField":
        frames = [fix_pair_speeds(r) for r in runs]
        samp = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=["s_mid", "t_mid", "speed"])
        )
        samp["seg"] = (samp["s_mid"] // segment_m).astype("int64") if len(samp) else []
        samp = samp.sort_values("t_mid").reset_index(drop=True)
        return cls(samp, segment_m, window_s, free_flow)

    def speed(self, s: float, t0_epoch: float) -> float:
        """Mediana das amostras do segmento de `s` na janela (t0-window, t0].
        Fallback para free_flow quando não há amostra. Marca last_was_fallback."""
        seg = int(s // self.segment_m)
        m = self.samples
        sel = m[
            (m["seg"] == seg)
            & (m["t_mid"] <= t0_epoch)
            & (m["t_mid"] > t0_epoch - self.window_s)
        ]
        if len(sel) == 0:
            self.last_was_fallback = True
            return self.free_flow
        self.last_was_fallback = False
        return float(sel["speed"].median())
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_speed_field.py -v`
Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add spike/analysis/speed_field.py spike/analysis/tests/test_speed_field.py
git commit -m "Campo de velocidade por segmento com janela movel e fallback"
```

---

## Task 6: Projeção de ETA

Tempo previsto = soma de (comprimento do trecho / velocidade do segmento) entre `s0` e `s_target`, usando o campo de velocidade em `t0`.

**Files:**
- Create: `spike/analysis/eta.py`
- Test: `spike/analysis/tests/test_eta.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_eta.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_eta.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

`spike/analysis/eta.py`:

```python
"""Projeção de ETA: integra comprimento/velocidade ao longo dos segmentos."""

from __future__ import annotations

from analysis.speed_field import SpeedField


def project_travel_time(
    field: SpeedField, s0: float, t0_epoch: float, s_target: float
) -> float:
    """Tempo de viagem previsto (s) de s0 a s_target, usando as velocidades de
    segmento congeladas em t0. Caminha segmento a segmento, usando só o trecho
    que cai dentro de [s0, s_target]."""
    if s_target <= s0:
        return 0.0
    seg_m = field.segment_m
    total = 0.0
    s = s0
    while s < s_target:
        seg_end = (int(s // seg_m) + 1) * seg_m
        step_end = min(seg_end, s_target)
        length = step_end - s
        v = field.speed(s, t0_epoch)
        total += length / v
        s = step_end
    return total
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_eta.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Commit**

```bash
git add spike/analysis/eta.py spike/analysis/tests/test_eta.py
git commit -m "Projecao de ETA por integracao de segmentos"
```

---

## Task 7: Baseline de velocidade constante

O baseline ingênuo: assume que o ônibus segue na velocidade média recente dele.

**Files:**
- Create: `spike/analysis/baselines.py`
- Test: `spike/analysis/tests/test_baselines.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_baselines.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_baselines.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

`spike/analysis/baselines.py`:

```python
"""Baselines ingênuos que o motor de ETA precisa bater.

constant_speed: velocidade média recente do próprio ônibus.
(GTFS schedule e Previsão SPTrans vivem no caminho de dado real — Task 9/10.)"""

from __future__ import annotations

import numpy as np

from analysis.trajectories import Run


def constant_speed_travel_time(
    run: Run, idx: int, distance_m: float, *, lookback_s: float = 120.0
) -> float:
    """Tempo previsto pra percorrer distance_m assumindo a velocidade média do
    veículo nos últimos lookback_s antes de run.t_epoch[idx]. inf se parado."""
    t_now = run.t_epoch[idx]
    mask = (run.t_epoch <= t_now) & (run.t_epoch >= t_now - lookback_s)
    ts, ss = run.t_epoch[mask], run.s[mask]
    if len(ts) < 2 or (ts[-1] - ts[0]) <= 0:
        return float("inf")
    v = (ss[-1] - ss[0]) / (ts[-1] - ts[0])
    if v <= 0:
        return float("inf")
    return distance_m / v
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_baselines.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Commit**

```bash
git add spike/analysis/baselines.py spike/analysis/tests/test_baselines.py
git commit -m "Baseline de velocidade constante"
```

---

## Task 8: Harness de avaliação + autoteste sintético E2E

Gera eventos (cada fix vira um `t0`), projeta ETA pra alvos à frente, compara com a chegada real da própria passada, bucketiza o erro por horizonte. O teste E2E é o **autoteste sintético** do spec: com trânsito estacionário, o erro do modelo tem que ser ~0, e ele tem que recuperar um segmento congestionado.

**Files:**
- Create: `spike/analysis/evaluate.py`
- Test: `spike/analysis/tests/test_evaluate.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_evaluate.py`:

```python
from datetime import datetime, timezone

import numpy as np

from analysis.evaluate import evaluate_runs
from analysis.match import match_df
from analysis.speed_field import SpeedField
from analysis.synthetic import make_run, straight_shape
from analysis.trajectories import split_runs


def _setup(profile, n_vehicles=8, headway_s=120.0):
    t0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    frames = []
    for i in range(n_vehicles):
        start = t0.replace(tzinfo=timezone.utc) + __import__("datetime").timedelta(seconds=i * headway_s)
        frames.append(make_run(f"v{i}", start, profile, cadence_s=25.0, noise_m=0.0))
    import pandas as pd
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_evaluate.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

`spike/analysis/evaluate.py`:

```python
"""Gera eventos de predição e mede o erro do modelo contra a realidade observada."""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.eta import project_travel_time
from analysis.speed_field import SpeedField
from analysis.trajectories import Run


def evaluate_runs(
    runs: list[Run], field: SpeedField, *, horizons_m: list[float], stride: int = 2
) -> pd.DataFrame:
    """Para cada passada e cada fix (a cada `stride`), projeta o tempo de viagem
    até s0+horizonte e compara com o tempo real da própria passada. Bucketiza
    pelo tempo real de viagem. Retorna DataFrame com uma linha por evento."""
    rows: list[dict] = []
    for run in runs:
        n = len(run.s)
        for idx in range(0, n, stride):
            s0, t0 = float(run.s[idx]), float(run.t_epoch[idx])
            for h in horizons_m:
                s_target = s0 + h
                t_real = run.time_at(s_target)
                if t_real is None:
                    continue
                actual = t_real - t0
                if actual <= 0:
                    continue
                pred = project_travel_time(field, s0, t0, s_target)
                rows.append(
                    {
                        "vehicle": run.vehicle,
                        "horizon_m": h,
                        "actual_s": actual,
                        "pred_s": pred,
                        "err_s": pred - actual,
                        "abs_err_s": abs(pred - actual),
                        "abs_err_pct": abs(pred - actual) / actual,
                    }
                )
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_evaluate.py -v`
Expected: PASS (2 testes) — **autoteste sintético verde: a lógica do pipeline está provada.**

- [ ] **Step 5: Rodar a suíte inteira**

Run (de `spike/`): `.venv-analysis/Scripts/pytest analysis -v`
Expected: todos os testes passam (synthetic, match, trajectories, speed_field, eta, baselines, evaluate).

- [ ] **Step 6: Commit**

```bash
git add spike/analysis/evaluate.py spike/analysis/tests/test_evaluate.py
git commit -m "Harness de avaliacao + autoteste sintetico E2E do Bloco A"
```

---

## Task 9: Ingestão de dado real (SQLite + GTFS + link cl→shape)

Carrega `positions`/`predictions` do SQLite, carrega o shape dominante de cada `cl` no GTFS congelado, e converte para o formato do pipeline. **Maior risco do spec** — por isso vem com logging de auditoria do casamento.

**Files:**
- Create: `spike/analysis/ingest.py`
- Test: `spike/analysis/tests/test_ingest.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_ingest.py`:

```python
import sqlite3
from pathlib import Path

import pandas as pd

from analysis.ingest import load_positions


def test_load_positions_parses_utc(tmp_path):
    db = tmp_path / "t.sqlite3"
    c = sqlite3.connect(db)
    c.executescript(
        "CREATE TABLE positions (line_cl INTEGER, vehicle TEXT, ts_vehicle TEXT, lat REAL, lng REAL);"
        "INSERT INTO positions VALUES (609,'1',  '2026-06-22T16:10:52Z', -23.55, -46.63);"
        "INSERT INTO positions VALUES (609,'1',  '2026-06-22T16:11:17Z', -23.551, -46.631);"
    )
    c.commit(); c.close()
    df = load_positions(str(db), cl=609)
    assert list(df.columns) == ["vehicle", "ts", "lat", "lng"]
    assert str(df["ts"].dt.tz) == "UTC"
    assert len(df) == 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_ingest.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar**

`spike/analysis/ingest.py`:

```python
"""Carrega dados reais: SQLite do coletor + GTFS congelado + link cl->shape."""

from __future__ import annotations

import csv
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

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
    # route_short_name -> route_id(s)
    route_ids = {
        r["route_id"]
        for r in _read_csv(g / "routes.txt")
        if r.get("route_short_name") == route_short_name
    }
    if not route_ids:
        raise ValueError(f"route_short_name {route_short_name!r} não achado no GTFS")
    # trips da rota no sentido -> contagem por shape_id
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Smoke test do link contra o GTFS real**

Run (de `spike/`):
```bash
.venv-analysis/Scripts/python -c "from analysis.ingest import load_shape_for_route; l=load_shape_for_route('data/_gtfs','875A',0); print('comprimento m:', round(l.length))"
```
Expected: imprime a linha `[link] 875A dir=0 -> shape=...` e um comprimento plausível (alguns milhares de metros). Se falhar (route_short_name diferente no GTFS), ajustar o nome e re-rodar.

- [ ] **Step 6: Commit**

```bash
git add spike/analysis/ingest.py spike/analysis/tests/test_ingest.py
git commit -m "Ingestao de dado real: SQLite + GTFS + link cl-shape"
```

---

## Task 10: Relatório + runner CLI

Liga tudo sobre o SQLite real: por linha/sentido, carrega posições → match → passadas → campo de velocidade → avaliação, agrega erro por horizonte vs baseline de velocidade constante, e imprime o veredito vs critério go (≥25% melhor que baseline e erro mediano ≤15%). Roda no checkpoint (dia 3-4) e no fim.

**Files:**
- Create: `spike/analysis/report.py`
- Create: `spike/analysis/run.py`
- Test: `spike/analysis/tests/test_report.py`

- [ ] **Step 1: Escrever o teste que falha**

`spike/analysis/tests/test_report.py`:

```python
import pandas as pd

from analysis.report import summarize, verdict


def test_summarize_buckets_by_horizon():
    df = pd.DataFrame(
        {
            "horizon_m": [500.0, 500.0, 2000.0],
            "abs_err_s": [10.0, 30.0, 120.0],
            "abs_err_pct": [0.05, 0.10, 0.20],
            "actual_s": [200.0, 200.0, 600.0],
        }
    )
    s = summarize(df, group="horizon_m")
    assert set(s.columns) >= {"p50_abs_err_s", "p90_abs_err_s", "p50_abs_err_pct", "n"}
    assert s.loc[500.0, "n"] == 2


def test_verdict_go_when_beats_baseline_and_threshold():
    assert verdict(model_p50_pct=0.10, baseline_p50_pct=0.20) == "GO"
    # não bate baseline por 25%
    assert verdict(model_p50_pct=0.18, baseline_p50_pct=0.20) == "NO-GO"
    # bate baseline mas erro absoluto alto demais
    assert verdict(model_p50_pct=0.22, baseline_p50_pct=0.40) == "NO-GO"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_report.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementar report.py**

`spike/analysis/report.py`:

```python
"""Agrega o erro por horizonte e emite o veredito go/no-go."""

from __future__ import annotations

import pandas as pd

# Critério go (Seção 1 do spec).
MIN_IMPROVEMENT = 0.25   # >=25% melhor que o melhor baseline
MAX_MEDIAN_PCT = 0.15    # erro mediano <= 15% do tempo de viagem


def summarize(df: pd.DataFrame, *, group: str) -> pd.DataFrame:
    """P50/P90 do erro absoluto (s e %) por grupo (ex.: horizon_m)."""
    g = df.groupby(group)
    return pd.DataFrame(
        {
            "n": g.size(),
            "p50_abs_err_s": g["abs_err_s"].median(),
            "p90_abs_err_s": g["abs_err_s"].quantile(0.9),
            "p50_abs_err_pct": g["abs_err_pct"].median(),
            "p90_abs_err_pct": g["abs_err_pct"].quantile(0.9),
        }
    )


def verdict(*, model_p50_pct: float, baseline_p50_pct: float) -> str:
    """GO se o modelo bate o baseline em >=MIN_IMPROVEMENT E erro <= MAX_MEDIAN_PCT."""
    beats = baseline_p50_pct > 0 and (
        (baseline_p50_pct - model_p50_pct) / baseline_p50_pct >= MIN_IMPROVEMENT
    )
    usable = model_p50_pct <= MAX_MEDIAN_PCT
    return "GO" if (beats and usable) else "NO-GO"
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv-analysis/Scripts/pytest analysis/tests/test_report.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Implementar o runner CLI (sem teste unitário — orquestração)**

`spike/analysis/run.py`:

```python
"""Runner do Bloco A sobre o SQLite real.

Uso:
    python -m analysis.run --db data/olhovivo.sqlite3 --gtfs data/_gtfs \\
        --route 875A --direction 0 --segment-m 500 --window-min 30
"""

from __future__ import annotations

import argparse

import pandas as pd

from analysis.baselines import constant_speed_travel_time
from analysis.eta import project_travel_time
from analysis.ingest import load_positions, load_shape_for_route
from analysis.match import match_df, to_utm
from analysis.report import summarize, verdict
from analysis.speed_field import SpeedField
from analysis.trajectories import split_runs

HORIZONS_M = [500.0, 1000.0, 2000.0, 4000.0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--gtfs", required=True)
    ap.add_argument("--route", required=True)
    ap.add_argument("--direction", type=int, required=True)
    ap.add_argument("--cl", type=int, required=True, help="código interno da linha/sentido")
    ap.add_argument("--segment-m", type=float, default=500.0)
    ap.add_argument("--window-min", type=float, default=30.0)
    ap.add_argument("--free-flow", type=float, default=8.0)
    args = ap.parse_args()

    line = load_shape_for_route(args.gtfs, args.route, args.direction)
    pos = load_positions(args.db, args.cl)
    print(f"posições: {len(pos)}; comprimento shape: {round(line.length)} m")
    pos = match_df(to_utm(pos), line)
    print(f"após snap (<=80m): {len(pos)}  (erro snap mediano {pos['snap_err'].median():.1f} m)")
    runs = split_runs(pos)
    print(f"passadas reconstruídas: {len(runs)}")
    field = SpeedField.from_runs(
        runs, segment_m=args.segment_m, window_s=args.window_min * 60, free_flow=args.free_flow
    )

    rows: list[dict] = []
    fallbacks = 0
    for run in runs:
        for idx in range(0, len(run.s), 2):
            s0, t0 = float(run.s[idx]), float(run.t_epoch[idx])
            for h in HORIZONS_M:
                t_real = run.time_at(s0 + h)
                if t_real is None or (t_real - t0) <= 0:
                    continue
                actual = t_real - t0
                pred = project_travel_time(field, s0, t0, s0 + h)
                fallbacks += int(field.last_was_fallback)
                base = constant_speed_travel_time(run, idx, h)
                rows.append(
                    {
                        "horizon_m": h,
                        "actual_s": actual,
                        "abs_err_s": abs(pred - actual),
                        "abs_err_pct": abs(pred - actual) / actual,
                        "base_abs_err_pct": (abs(base - actual) / actual)
                        if base != float("inf")
                        else float("nan"),
                    }
                )
    df = pd.DataFrame(rows)
    if df.empty:
        print("SEM EVENTOS — dados insuficientes (rode mais tarde / verifique o link)")
        return 1

    print("\n=== erro do MODELO por horizonte ===")
    print(summarize(df, group="horizon_m").round(3))
    m = df["abs_err_pct"].median()
    b = df["base_abs_err_pct"].median()
    print(f"\nmodelo p50%={m:.3f}  baseline(vel.const) p50%={b:.3f}")
    print(f"taxa de fallback de velocidade: {fallbacks / max(len(df),1):.2%}")
    print(f"\n>>> VEREDITO: {verdict(model_p50_pct=m, baseline_p50_pct=b)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Commit**

```bash
git add spike/analysis/report.py spike/analysis/run.py spike/analysis/tests/test_report.py
git commit -m "Relatorio go/no-go + runner CLI do Bloco A"
```

---

## Checkpoint (dia 3-4, ~25-26/06) — fora do build, mas no plano

- [ ] Puxar o SQLite da VM: `scp -i ~/.ssh/olhovivo_gcp olhovivo@<ip>:~/olhovivo/data/olhovivo.sqlite3 spike/data/`
- [ ] Rodar `python -m analysis.run` pra cada cl resolvido (609/33377/516/33284/932/33700) com o `--route`/`--direction` correspondente.
- [ ] Validar empiricamente: o link casou (erro de snap mediano baixo)? densidade gera eventos suficientes? taxa de fallback aceitável?
- [ ] Ajustar `--segment-m` / `--window-min` conforme a densidade real antes da rodada final.

---

## Self-Review

- **Cobertura do spec:** link GTFS↔cl (Task 9) ✓; map-matching/UTM (Task 3) ✓; reconstrução de passadas (Task 4) ✓; velocidade por par-de-fixes + janela + fallback (Task 5) ✓; projeção de ETA (Task 6) ✓; verdade de campo + erro por horizonte (Task 8) ✓; baselines — vel. constante (Task 7) ✓, **GTFS e Previsão SPTrans ficam para uma extensão pós-checkpoint** (decisão consciente: o thin-E2E valida a tese com o baseline de vel. constante; a Previsão entra quando confirmarmos que o link e a densidade prestam, evitando construir contra dado não-validado). Sem vazamento temporal — `SpeedField.speed` filtra `t_mid <= t0` (Task 5) ✓; autoteste sintético (Task 8) ✓; relatório/veredito (Task 10) ✓.
- **Lacuna registrada:** baseline `/Previsao` SPTrans e baseline GTFS-schedule não têm task de implementação aqui (só vel. constante). São uma **extensão planejada** após o checkpoint validar link+densidade. Anotado também no STATUS para não se perder.
- **Placeholders:** nenhum — todo step de código traz o código.
- **Consistência de tipos:** `Run(vehicle, t_epoch, s)`, `time_at`, `SpeedField.from_runs(...).speed(s, t0)`, `project_travel_time(field, s0, t0_epoch, s_target)`, `summarize(df, group=...)`, `verdict(model_p50_pct=, baseline_p50_pct=)` — nomes/assinaturas batem entre as tasks que os usam.
