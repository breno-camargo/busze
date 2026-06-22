# Bloco A — análise/validação do motor de ETA

Pipeline offline que decide o go/no-go: a partir das posições coletadas + GTFS
congelado, estima velocidade por segmento, projeta ETA e mede o erro vs baselines.
Spec: `docs/superpowers/specs/2026-06-22-bloco-a-analise-eta-design.md`.

## Setup

```bash
cd spike
python -m venv .venv-analysis
.venv-analysis/Scripts/pip install -r analysis/requirements.txt   # Windows
```

## Testes

```bash
cd spike
.venv-analysis/Scripts/python -m pytest analysis -q
```

O autoteste sintético (`test_evaluate.py`) prova a lógica sem depender de dado real.

## Rodar sobre dado real

1. Snapshot consistente do SQLite na VM e download:
   ```bash
   ssh -i ~/.ssh/olhovivo_gcp olhovivo@<ip> \
     'sqlite3 ~/olhovivo/data/olhovivo.sqlite3 ".backup /tmp/snap.sqlite3"'
   scp -i ~/.ssh/olhovivo_gcp olhovivo@<ip>:/tmp/snap.sqlite3 data/olhovivo.sqlite3
   ```
2. Rodar por linha/sentido:
   ```bash
   .venv-analysis/Scripts/python -m analysis.run \
     --db data/olhovivo.sqlite3 --gtfs data/_gtfs \
     --route 875A --direction 0 --cl 609 --segment-m 500 --window-min 30
   ```

## Mapeamento cl ↔ GTFS (resolver no checkpoint)

O `sentido` do Olho Vivo não casa 1:1 com o `direction_id` do GTFS — descobre-se
empiricamente rodando os dois `--direction` e pegando o de **menor erro de snap**
(o sentido errado fragmenta as passadas e dá "SEM EVENTOS").

| cl    | linha | sentido OV | --direction GTFS | status |
|-------|-------|-----------|------------------|--------|
| 609   | 875A  | 1         | **0**            | confirmado (snap 0.0m) |
| 33377 | 875A  | 2         | (1?)             | resolver |
| 516   | 106A  | 1         | ?                | resolver |
| 33284 | 106A  | 2         | ?                | resolver |
| 932   | 2719  | 1         | ?                | resolver |
| 33700 | 2719  | 2         | ?                | resolver |

GTFS usa `route_short_name` com sufixo de variante (ex.: `875A-10`); o linker casa
pela base (`875A`).

## Smoke run preliminar (2026-06-22, ~4h de dados)

cl 609: 15 passadas, erro p50 ~30% (baseline vel.const ~33%), fallback 14,6% →
**NO-GO preliminar**, dominado por escassez de dados. **Não é o veredito** — esperar
~2 semanas e afinar `--segment-m`/`--window-min` antes de concluir.
