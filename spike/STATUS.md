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

## COLETOR NO AR — GCP (2026-06-22)
A coleta migrou do PC do breno para uma **VM gratuita no Google Cloud** (o PC
seria desligado). O caminho NSSM/Windows foi abandonado.

- **VM**: GCP Compute Engine `e2-micro` (always-free), região `us-central1-a`,
  Ubuntu 24.04, projeto `busze-500215`, instância `olhovivo`. IP externo
  efêmero (pode mudar em stop/start — irrelevante, só fazemos saída).
- **Acesso SSH**: usuário `olhovivo`, chave ed25519 em
  `C:\Users\breno\.ssh\olhovivo_gcp` (sem passphrase, fica só no PC do breno).
- **Serviço**: `olhovivo.service` (systemd, `Restart=always`, enabled → sobe no
  boot). App em `~/olhovivo` (`.venv` + `requests`); `.env` com o token via
  `EnvironmentFile`; `DB_PATH=~/olhovivo/data/olhovivo.sqlite3`.
- Linhas resolvidas: 875A (cl 609/33377), 106A (cl 516/33284), 2719 (cl 932/33700)
  — ambos os sentidos. Ciclos a cada 25s, 0 falhas, ~21 MB RAM.
- **Coleta `/Previsao/Linha` também (desde 22/06, ~16:13Z):** ETA-ao-ponto da
  própria SPTrans → tabela `predictions`. É o baseline forte do Bloco A ("nosso
  ETA bate o da SPTrans?"). 12 chamadas/ciclo (6 linhas × Posição+Previsão).
- Logs: `journalctl -u olhovivo -f`. Status: `systemctl status olhovivo`.
- Unit versionado em `spike/olhovivo.service`.
- **Watchdog**: `spike/healthcheck.sh` roda via cron (`/etc/cron.d/olhovivo-health`,
  a cada 15 min, como root). Registra métricas em `~/olhovivo/logs/health.log` e
  reinicia o serviço só se o loop travar (zero ciclos em 10 min — usa "ciclos",
  não "posições novas", pra não dar falso positivo de madrugada).

## Retomar daqui
1. **Coletor rodando no GCP desde 22/06.** Deixar coletando ~2 semanas; conferir
   `journalctl -u olhovivo` de vez em quando (ciclos com 0 falhas).
   Ao terminar: `scp` do `olhovivo.sqlite3` pra rodar a análise.
2. **Bloco A (pendente, ~1 sessão):** escrever o pipeline de análise (map-matching
   + velocidade por segmento + projeção de ETA + erro) com autoteste sintético.
   Pode ser construído antes dos dados; valida a lógica no servidor onde há Python.
3. Rodar a análise sobre os dados reais → decidir go/no-go.
4. Se go: voltar ao design doc, completar Seções 2-6 pendentes, depois
   `superpowers:writing-plans`.

Design doc: `docs/superpowers/specs/2026-04-28-bus-routes-sp-design.md`
