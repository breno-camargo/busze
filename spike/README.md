# ETA-engine de-risking spike — coletor Olho Vivo

Coleta posições GPS de algumas linhas SPTrans por ~2 semanas pra depois rodar
map-matching + velocidade por segmento offline e medir o erro de projeção de ETA.
**É o go/no-go do produto** (ver Seção 0 do design doc). Código throwaway.

## Pré-requisitos

1. **Token Olho Vivo** — cadastro gratuito em
   <https://www.sptrans.com.br/desenvolvedores/>. A validação não é instantânea;
   comece já.
2. **Códigos de linha** — edite `LINE_SEARCH_TERMS` no topo de `collector.py`.
   Use o rótulo público (ex.: `"8000"`, `"477P"`). Cada termo vira 1+ `cl`
   (um por sentido) no startup. Perfil recomendado do trio: 1 corredor
   congestionado/variável, 1 alternativa pro mesmo O-D, 1 controle estável.
3. **Snapshot do GTFS estático** — rode `snapshot_gtfs.py` no T0 da coleta (ver
   abaixo). O map-matching da análise casa as posições com o *shape* da linha; o
   shape muda com o tempo, então tem que ser o que estava valendo durante a
   coleta. Baixar o GTFS depois pode casar posição com traçado já alterado.

## Rodar num host 24h (VPS ou servidor próprio)

Qualquer máquina ligada 24h com Docker e internet de saída serve — não precisa
de VPS dedicada. O rate limit da Olho Vivo é por token, não por IP, então rodar
em casa não muda nada. Só garanta um diretório persistente pro volume `./data`.

```bash
cd spike
cp .env.example .env        # preencha OLHOVIVO_TOKEN

# T0: congela o GTFS estático da coleta (uma vez)
export GTFS_URL="https://.../gtfs-sptrans.zip"   # URL do portal SPTrans
python snapshot_gtfs.py                          # gera data/gtfs-snapshot-<data>.zip

docker build -t olhovivo-collector .
docker run -d --name collector --restart=always \
  --env-file .env \
  -v "$PWD/data:/data" \
  olhovivo-collector
docker logs -f collector
```

DB em `./data/olhovivo.sqlite3`. `--restart=always` garante retomada após
reboot/crash; o índice único dedup evita duplicatas na retomada.

## Rodar no Windows 24h sem Docker (serviço via NSSM)

Para uma máquina Windows sempre ligada, **não use Docker Desktop** — ele só sobe
o daemon com um usuário logado, o que quebra operação headless. Rode o Python
nativo como serviço com [NSSM](https://nssm.cc), que reinicia em crash e no boot
(equivalente ao `--restart=always`).

Pré-requisitos: instale o **Python 3.12 do python.org** (marque "Add to PATH" —
não use o alias da Microsoft Store) e baixe o `nssm.exe`.

```powershell
# Copie collector.py, snapshot_gtfs.py, requirements.txt para, ex., C:\olhovivo-spike
cd C:\olhovivo-spike
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# Diretórios precisam existir: o sqlite3 cria o arquivo, não a pasta
New-Item -ItemType Directory -Force data, logs

# T0: snapshot do GTFS (uma vez)
$env:GTFS_URL = "https://.../gtfs-sptrans.zip"
.venv\Scripts\python snapshot_gtfs.py

# Instala o serviço (rode o terminal como Administrador)
nssm install OlhoVivoCollector "C:\olhovivo-spike\.venv\Scripts\python.exe" "C:\olhovivo-spike\collector.py"
nssm set OlhoVivoCollector AppDirectory "C:\olhovivo-spike"
nssm set OlhoVivoCollector AppEnvironmentExtra OLHOVIVO_TOKEN=COLE_O_TOKEN DB_PATH=C:\olhovivo-spike\data\olhovivo.sqlite3
nssm set OlhoVivoCollector AppStdout "C:\olhovivo-spike\logs\collector.log"
nssm set OlhoVivoCollector AppStderr "C:\olhovivo-spike\logs\collector.log"
nssm set OlhoVivoCollector Start SERVICE_AUTO_START
nssm start OlhoVivoCollector
```

NSSM reinicia o processo em falha por padrão e `SERVICE_AUTO_START` retoma após
reboot. O `stop` do serviço mata o processo sem SIGTERM limpo, mas WAL + commit
por ciclo mantêm o DB consistente. Logs em `logs\collector.log`; pare/remova com
`nssm stop OlhoVivoCollector` / `nssm remove OlhoVivoCollector confirm`.

## Rodar local (teste rápido)

```bash
cd spike
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export OLHOVIVO_TOKEN=...                            # Windows: $env:OLHOVIVO_TOKEN="..."
python collector.py
```

## Esquema do SQLite

- `lines` — `cl` ↔ rótulo/sentido/terminais resolvidos no startup.
- `positions` — uma linha por `(line_cl, vehicle, ts_vehicle)`, do `/Posicao`.
  **Use esta** pra análise; já está dedupada do ruído de cadência de polling.
- `predictions` — ETA-ao-ponto da própria SPTrans, do `/Previsao/Linha`: uma linha
  por `(line_cl, stop_code, vehicle, ts_vehicle, predicted_arr)`. `predicted_arr`
  é hora **local** (BRT) `HH:MM`; `ts_vehicle` é UTC. É o **baseline** que o ETA
  caseiro precisa bater.
- `raw_polls` — JSON cru de cada resposta (`kind` = `posicao`|`previsao`), pra
  re-análise se o schema parseado faltar algo.

## Próximo passo (depois de ~2 semanas coletando)

Notebook de análise (pandas + shapely + gtfs_kit): casar posições com o shape
do GTFS estático, computar velocidade real por segmento, projetar chegada e
comparar com a realidade observada. Aí decide go/no-go.
