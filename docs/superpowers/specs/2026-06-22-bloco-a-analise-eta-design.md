# Bloco A — Pipeline de validação do motor de ETA (spike)

**Status:** design aprovado em espírito (delegação total do breno); pendente review do spec escrito.
**Data:** 2026-06-22
**Autor:** breno + Claude
**Contexto:** Seção 0 e Seção 8/item-0 do design doc `2026-04-28-bus-routes-sp-design.md`.

---

## 1. Objetivo e critério go/no-go

A partir dos dados coletados (`/Posicao` + `/Previsao`) e do GTFS estático congelado,
**provar (ou refutar) que dá pra estimar ETA realista por velocidade-de-segmento com
precisão útil**. É o go/no-go do produto: se a projeção não bate a realidade nem os
baselines, não há o diferencial "Waze de ônibus".

**Métrica primária:** erro absoluto da chegada projetada num ponto à frente
`|t_projetado − t_real|`, agregado por **mediana (P50)** e **P90**, e também como
**% do tempo real de viagem** (normaliza trajetos curtos vs longos), **bucketizado
por horizonte** (5/10/20/30+ min).

**Critério go:** o modelo de velocidade-por-segmento precisa
1. reduzir o erro mediano em **≥25%** vs o melhor baseline, **e**
2. atingir erro mediano **≤ ~15% do tempo de viagem** (≈ ≤2-3 min num trajeto de 20 min)
   com P90 razoável.

**No-go:** não bate baseline, ou erro mediano > ~20%. (Limiares afináveis depois de
ver a distribuição real — não cravar antes dos dados.)

**Baselines a superar:**
- **`/Previsao` da SPTrans** (forte) — a ETA-ao-ponto da própria SPTrans, por
  parada/veículo. É o concorrente real. Já sendo coletado (tabela `predictions`).
- **Tabela GTFS** (fraco) — tempo de viagem agendado via `stop_times`.
- **Velocidade constante** (fraco) — assume que o ônibus segue na velocidade média
  recente dele.

## 2. Princípios

- **Throwaway.** Código de validação, não o produto. Otimiza pra responder o go/no-go,
  não pra reuso.
- **Fino ponta-a-ponta primeiro, dado real cedo.** Os riscos que decidem o go/no-go são
  empíricos (linking GTFS↔`cl`, qualidade do map-matching no GPS real, densidade de
  dados) e o autoteste sintético não os toca. Construir o pipeline mínimo E2E, rodar na
  fatia de dados do **checkpoint (dia 3-4)**, e só então endurecer. Sintético guarda a
  lógica; o dado real retira o risco.
- **Sem vazamento temporal.** Toda estimativa de velocidade em `t0` usa apenas dados até
  `t0` (janela estritamente passada).
- **`ts_vehicle` (GPS) é o relógio**, nunca o tempo de poll.

## 3. Dados de entrada

- **`positions`** — `(line_cl, vehicle, ts_vehicle, lat, lng)`, dedupada.
- **`predictions`** — ETA-ao-ponto da SPTrans `(line_cl, stop_code, vehicle,
  predicted_arr, ts_vehicle)`. `predicted_arr` é hora **local BRT** `HH:MM`;
  `ts_vehicle` é UTC. Converter pra UTC no parse (fronteira de meia-noite via a data de
  `ts_collected`).
- **GTFS congelado** — `spike/data/_gtfs/` (snapshot 2026-06-17): `shapes`, `trips`,
  `stop_times`, `stops`, `routes`.

## 4. Arquitetura — estágios do pipeline

1. **Link GTFS↔Olho Vivo** *(maior risco)* — mapeia cada `line_cl` → `route` + sentido →
   **shape dominante** (shape_id com mais trips). Loga o casamento (`875A` → route_id,
   shape_id, nº trips) e shapes alternativos pra auditar.
2. **Map-matching (linear referencing)** — projeta cada `(lat,lng)` na polilinha do shape
   → distância acumulada `s` (metros), em CRS métrico **UTM 23S / EPSG:31983**. Descarta
   pontos a >~50-80m do shape. A distribuição do erro de snap vira sanity check do link.
3. **Reconstrução de trajetória (por veículo/passada)** — agrupa por `vehicle`, ordena por
   `ts_vehicle`, quebra em "passadas" quando `s` reseta/recua ou há gap longo. Cada passada
   dá a **verdade de campo**: interpolação `s↔t` (quando o ônibus cruzou cada distância).
4. **Campo de velocidade** — calcula velocidade **entre fixes consecutivos** de cada
   veículo (`Δs/Δt` ao longo do shape) — essa é a resolução natural do dado, desacoplada do
   tamanho de segmento. Atribui cada amostra ao segmento onde caiu. No instante `t0`,
   velocidade do segmento = **mediana das amostras na janela móvel** (~20-30 min);
   fallback: janela recente → mediana histórica do horário → free-flow. Loga taxa de
   fallback (muito fallback = sinal fraco).
   - **Tamanho de segmento guiado pela densidade/cadência**, não cravado em 200m. A
     cadência de GPS (~20-30s) a ~20 km/h cobre ~150-200m por fix; segmento curto demais
     fica com 1 fix por travessia e vira ruído. **Começar parada-a-parada (GTFS) ou
     ~400-500m**, parametrizado; testar refinar depois se a densidade permitir.
5. **Projeção de ETA** — evento: veículo em `s0` no tempo `t0`; alvo `s_target`. Tempo
   previsto = Σ `(comprimento_seg / velocidade_seg(t0))` entre `s0` e `s_target`. Chegada
   prevista = `t0 + tempo`. Vários alvos por evento (um por horizonte/parada à frente).
6. **Verdade & erro** — chegada real em `s_target` da própria passada do veículo. Erro =
   previsto − real, bucketizado por horizonte. Amostragem: muitos eventos `t0` por passada
   × vários alvos.
7. **Baselines** (mesmos eventos/alvos) — `/Previsao` SPTrans, tabela GTFS, velocidade
   constante. Para `/Previsao`: casar a previsão SPTrans daquele veículo→parada feita em
   ~`t0` contra a chegada real na mesma parada.
8. **Relatório** — distribuições P50/P90 e % do trajeto por horizonte, modelo vs cada
   baseline; taxa de fallback, cobertura, erro de snap, nº de eventos; **veredito vs
   critério go**. Plots opcionais (matplotlib).

## 5. Autoteste sintético (construído primeiro, TDD)

Gera shape reto + passadas com velocidades **conhecidas** (incl. um segmento
"congestionado") + ruído de GPS + cadência de ~25s. Asserta:
- velocidades recuperadas ≈ conhecidas (dentro de tolerância),
- ETA projetado ≈ ETA analítico,
- erro do modelo ≈ 0 quando o trânsito é estacionário.

Casos de borda: gaps, pontos fora do shape, recuo de `s`, segmento sem dado → fallback.
**Valida a lógica sem depender de dados reais — dá pra construir já.**

## 6. Sequenciamento

1. **Agora (sem dados):** autoteste sintético + pipeline fino E2E (link → match →
   trajetória → velocidade → ETA → erro) rodando contra o sintético.
2. **Checkpoint (dia 3-4, ~25-26/06):** puxar fatia real (`scp` do SQLite), rodar o
   pipeline. Validar empiricamente: link casou? snap baixo? densidade ok? Ajustar
   (tamanho de segmento, janela, thresholds) antes de gastar as 2 semanas.
3. **Fim (~06/07):** rodar sobre o dataset inteiro, computar erro vs baselines → veredito.

## 7. Estrutura, deps, execução

- `spike/analysis/`: `link_gtfs.py`, `match.py`, `trajectories.py`, `speed_field.py`,
  `eta.py`, `baselines.py`, `evaluate.py`, `report.py`, `synthetic.py`, `tests/`.
- Deps: `pandas`, `numpy`, `shapely`, `pyproj`, `pytest` (matplotlib/gtfs_kit opcionais).
- Executar localmente após `scp` do SQLite, ou na própria VM (tem Python + dados).

## 8. Riscos e mitigação

- **Link de shape errado → lixo.** Linker explícito + match logado + erro de snap como
  alarme (snap alto = shape errado).
- **Múltiplos shapes/sentido →** pega o dominante, loga alternativas.
- **Dado esparso / segmento curto demais → ruído.** Velocidade por par-de-fixes +
  segmento dimensionado pela cadência; taxa de fallback reportada.
- **Vazamento temporal →** janela estritamente passada em `t0`.
- **Fuso `predicted_arr` (BRT) vs `ts_vehicle` (UTC) →** normalizar no parse.

## 9. Estratégia de testes

- Autoteste sintético (lógica) — obrigatório, construído primeiro.
- Unit tests nos pontos frágeis: parse de fuso, quebra de passada, projeção/snap.
- Sanity pass nos dados reais no checkpoint (não é teste automatizado; é inspeção).

## 10. Fora de escopo

- Visualização de coloração de segmentos (é do produto; o spike só emite os números).
- Suavização sofisticada / ML. Mediana em janela móvel basta pro go/no-go.
- Qualquer código de produção (vem depois do go, via `writing-plans`).
