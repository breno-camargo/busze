# Onde paramos — spike do motor de ETA (2026-06-22)

## Contexto em 1 parágrafo
SPTrans não tem GTFS-RT. O diferencial "Waze de ônibus" (segmentos coloridos por
trânsito real + ETA realista) precisa ser construído do zero a partir do `/Posicao`
do Olho Vivo. Antes de qualquer build do produto, rodamos um **spike de validação**:
coletar posições por ~2 semanas → map-matching no shape do GTFS → velocidade por
segmento → projetar ETA → medir erro. Se não bater, repensa o produto. Isso é o
**go/no-go** (Seção 0 e 8-item-0 do design doc).

## Decisões travadas
- Runtime: **servidor Windows 24h do breno** (NÃO VPS, NÃO Docker Desktop). Deploy
  via Python nativo + **NSSM** como serviço (auto-restart em crash/reboot). Passo
  a passo em `README.md`.
- Linguagem do spike: **Python** (throwaway; geoespacial é pandas/shapely/gtfs_kit).
- **Trio de linhas escolhido** (pelo GTFS — densidade no pico + corredores):
  - `875A` Aeroporto–Perdizes — corredor congestionado/variável (Av. Paulista +
    Av. 23 de Maio). Primária.
  - `106A` Metrô Santana–Itaim Bibi — compartilha o trecho da Paulista com a 875A
    → validação cruzada de velocidade por segmento.
  - `2719` Ermelino Matarazzo–Metrô Vl. Matilde — controle estável (zona leste,
    fora de corredor congestionado).
  - Já preenchidos em `LINE_SEARCH_TERMS` no topo de `collector.py`.

## Feito nesta sessão (2026-06-17)
- Coletor endurecido: ignora posições sem `ta` (evita dup por NULL no índice
  único, que enviesaria velocidade por segmento); falha isolada por linha (uma
  linha quebrada não derruba o ciclo nem aciona backoff sozinha).
- `snapshot_gtfs.py` + passo no README pra congelar o GTFS no T0.
- Caminho de deploy Windows/NSSM documentado no README.
- **GTFS estático baixado e fixado**: `data/_gtfs/` (extraído) e
  `data/gtfs-snapshot-2026-06-17.zip` (proveniência travada p/ a análise).
- Confirmado que o GTFS está pronto pro map-matching: `shape_dist_traveled`
  preenchido (~45 m de espaçamento na 875A), `stop_times` presente por trip.
- Token Olho Vivo cadastrado (app **BUSZE**, chave homologada no portal).

## DESBLOQUEADO (2026-06-22): conta liberada, token autentica
- **`/Login/Autenticar` retorna `true` (HTTP 200)** com o token do `.env`. A conta
  foi habilitada pra API Olho Vivo — o bloqueio que segurava o spike acabou.
- Histórico do bloqueio (resolvido): entre 17 e 18/06 o `Autenticar` retornava
  `false` pra qualquer token (incl. um segundo app novo) → diagnóstico foi
  **conta não habilitada**, não o token. Liberou em algum momento até 22/06.
- Nota de chamada: o POST exige `Content-Length` (mandar body vazio, `-d ""`);
  sem isso a API retorna **HTTP 411**. O coletor já usa `session.post`, ok.

## COLETOR NO AR (2026-06-22)
- Serviço **`OlhoVivoCollector`** instalado via NSSM em `C:\olhovivo-spike`
  (Running, StartType Automatic → sobe no boot). Python 3.12 do python.org em
  `.venv`. Token via `AppEnvironmentExtra`; logs em `logs\collector.log` (UTF-8 —
  ler com `Get-Content -Encoding UTF8`, senão aparece mojibake no PS 5.1).
- Linhas resolvidas no startup: 875A (cl 609/33377), 106A (cl 516/33284),
  2719 (cl 932/33700) — ambos os sentidos cada.
- Ciclos a cada 25s, 0 falhas. DB em `C:\olhovivo-spike\data\olhovivo.sqlite3`.
- Manter o PC ligado ~2 semanas (sleep/hibernate desativados via `powercfg`).

## Retomar daqui
1. **Coletor já rodando desde 22/06.** Deixar coletando ~2 semanas; conferir
   `logs\collector.log` de tempos em tempos (ciclos com 0 falhas).
2. **Bloco A (pendente, ~1 sessão):** escrever o pipeline de análise (map-matching
   + velocidade por segmento + projeção de ETA + erro) com autoteste sintético.
   Pode ser construído antes dos dados; valida a lógica no servidor onde há Python.
4. Rodar a análise sobre os dados reais → decidir go/no-go.
5. Se go: voltar ao design doc, completar Seções 2-6 pendentes, depois
   `superpowers:writing-plans`.

Design doc: `docs/superpowers/specs/2026-04-28-bus-routes-sp-design.md`
