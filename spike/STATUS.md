# Onde paramos — spike do motor de ETA (2026-06-17)

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

## Bloqueado em 1 coisa (lado da SPTrans)
- **Token retorna `false` no `/Login/Autenticar`** apesar de homologado no portal.
  Chave correta e bem formada (64 hex, confere com o portal); a chamada está certa
  (HTTP 200, body `false`). É **defasagem de propagação** entre o portal e o
  backend de auth da API. Esperar (de horas até ~24h). Se passar disso, abrir
  chamado no suporte ao desenvolvedor SPTrans.
- Monitor de recheck a cada 30 min estava ativo nesta sessão (cron `1a26ea2b`,
  some ao fechar o Claude). Pra retomar: mandar "verifique" numa nova sessão.

## Retomar daqui
1. **Quando o token virar `true`:** subir o coletor no servidor Windows via NSSM
   (ver README). Conferir nos logs do startup quais `cl`/sentidos cada termo
   (`875A`/`106A`/`2719`) resolveu.
2. Deixar coletando ~2 semanas.
3. **Bloco A (pendente, ~1 sessão):** escrever o pipeline de análise (map-matching
   + velocidade por segmento + projeção de ETA + erro) com autoteste sintético.
   Pode ser construído antes dos dados; valida a lógica no servidor onde há Python.
4. Rodar a análise sobre os dados reais → decidir go/no-go.
5. Se go: voltar ao design doc, completar Seções 2-6 pendentes, depois
   `superpowers:writing-plans`.

Design doc: `docs/superpowers/specs/2026-04-28-bus-routes-sp-design.md`
