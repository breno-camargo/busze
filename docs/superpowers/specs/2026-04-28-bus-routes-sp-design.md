# Bus Routes SP — Design Document

**Status:** WIP — brainstorm em andamento. Seções 2-6 bloqueadas no go/no-go do spike.
**Data:** 2026-04-28
**Atualizado:** 2026-06-22 — simplificação pré-validação (ver Seção 0.5)
**Autor:** breno + Claude (sessão de brainstorm)

---

## 0. ⚠ Achados de validação (2026-06-12) — LEIA ANTES DO RESTO

Pesquisa confirmou dois fatos que mudam o núcleo técnico e o pitch do produto:

### 0.1 SPTrans NÃO tem GTFS-Realtime

- O feed SPTrans no Transitland (`f-6gy-sptrans`) é **só GTFS estático**. Não existe feed GTFS-RT (trip updates / vehicle positions / service alerts) que o OTP consuma direto.
- A API Olho Vivo é **JSON REST puro** (não protobuf). Ela entrega apenas:
  - `/Posicao` → posição GPS crua dos ônibus (lat/lng)
  - `/Previsao` → previsão de chegada **no ponto** (modelo da própria SPTrans, ETA ao ponto — não trânsito por segmento do trajeto)

**Consequência:** o OTP com GTFS estático faz roteamento por **horário de tabela**, e não há RT pra plugar nele. Toda a camada de "trânsito incorporado no trajeto" — o diferencial do produto — **precisa ser construída do zero** a partir do `/Posicao`: map-matching das posições no shape da linha → velocidade real por segmento no tempo → suavização → projeção de ETA e coloração verde/amarelo/vermelho. **Esse é o maior risco técnico e o diferencial são a mesma coisa.**

### 0.2 O push "hora de descer" já é commodity

O **Moovit já tem desembarque/"hora de descer" em SP** (feature "Live Directions / Get Off Alerts", em PT "Vamos"), cobrindo linhas SPTrans. A feature #4 do V1 **não diferencia**. Comparar rotas por chegada no destino também já existe (Moovit/Google).

### 0.3 Diferencial real (revisado)

Único fosso verdadeiro: **visualização estilo Waze — segmentos do trajeto coloridos por trânsito real + faixa narrativa.** Ninguém faz em SP, E depende inteiramente do motor de ETA caseiro acima. Pitch revisado: *"o app que te mostra ONDE o trânsito vai te atrasar no trajeto"* — visual, não funcional.

### 0.4 Ação que precede tudo

**Antes de `writing-plans`:** spike isolado de de-risking do motor de ETA (ver Seção 8, item 0). Se a projeção não bater contra a realidade, não há produto — descobrir isso em ~2 semanas de spike, não depois do monorepo/Docker/Cloudflare montados.

Fontes: [Olho Vivo API docs](https://www.sptrans.com.br/desenvolvedores/api-do-olho-vivo-guia-de-referencia/documentacao-api/) · [Transitland f-6gy-sptrans](https://www.transit.land/feeds/f-6gy-sptrans) · [Moovit Get Off Alerts](https://support.moovitapp.com/hc/en-us/articles/211392929-Live-Directions-Get-Off-Alerts)

---

## 0.5 Revisão 2026-06-22 — simplificação pré-validação

Ajustes após walkthrough: enxugar a infra antes do go/no-go e trocar o fosso visual
(copiável) por um fosso de dados. Decisões:

1. **Build em fases.** Pré-go: só o coletor (já rodando no GCP). No go, V1 MVP com o
   mínimo de stack — itens abaixo. Não montar Postgres/OTP/Compose antes da validação.
2. **SQLite + config no V1, Postgres adiado.** V1 não tem login nem PII; os únicos dados
   persistentes (feature flags, cidades, paradas estáticas) cabem em SQLite/arquivos.
   Posições e viagens ativas já vivem no Redis. Postgres entra quando houver multi-instância
   ou audit pesado.
3. **OTP fora do V1.** Substituído por um finder espacial caseiro sobre o GTFS ("quais linhas
   passam perto de O e D no sentido certo", via índice espacial), focado em poucos corredores
   curados. OTP (container Java, roteamento multimodal completo) é desproporcional; revisitar
   só se transbordo multi-perna virar essencial.
4. **Moat de dados desde o dia 1.** Persistir o histórico de velocidade por segmento (perfis
   horário × dia-da-semana). O diferencial deixa de ser só o visual (copiável) e passa a ser
   um modelo de trânsito de ônibus de SP que compõe com o tempo e é caro de replicar. Bônus:
   alimenta o fallback histórico do motor de ETA (já no design do Bloco A).
5. **Push "hora de descer" → V1.1 (fast-follow), não V1 core.** É table-stakes (Moovit já tem);
   não deve atrasar o lançamento do núcleo (comparação + mapa colorido).
6. **Seções 2-6 bloqueadas no go/no-go.** Não preencher no escuro antes do spike decidir.

---

## 1. O que é

PWA que compara rotas de ônibus em tempo real entre origem e destino em São Paulo, mostrando ETA realista por linha (considerando trânsito atual no trajeto), com alerta push de "hora de descer" enquanto você viaja.

Tagline interna: **"Waze para ônibus"**.

### Problema que resolve

Quando o usuário tem várias linhas viáveis pra ir do ponto A ao B, hoje ele não consegue saber facilmente:

- Qual ônibus chega primeiro no destino *considerando trânsito atual no trajeto da linha* (não só ETA até o ponto)
- Se o caminho mais curto está congestionado e o caminho mais longo está livre — qual sai melhor agora

Apps existentes (Cittamobi, Moovit, Google Maps) mostram posição e ETA até o ponto, mas não comparam o tempo total no destino com trânsito incorporado.

### Caso de uso (combinação de cenários)

- "Vou sair de casa" — comparar rotas alternativas antes de sair
- "Estou no ponto" — ver qual chega primeiro considerando trânsito
- "Estou no ônibus" — receber push quando hora de descer

---

## 2. Decisões fechadas no brainstorm

| Decisão | Escolha | Motivo |
|---|---|---|
| Cidade | São Paulo (V1) | SPTrans Olho Vivo tem API gratuita com posição GPS em tempo real |
| Descoberta de rotas | Auto (origem → destino) | Usuário digita endereços, app acha combinações |
| Plataforma | PWA | Sem Mac, evita custo App Store, deploy instantâneo, cobre iOS+Android |
| Frontend | Vite + React + PWA plugin | SPA + Service Worker, sem mágica do Next.js |
| Backend | Fastify (Node + TypeScript) | TS unificado front/back via monorepo, ecossistema maduro |
| DB | **SQLite + config no V1** (Postgres só ao escalar) | V1 sem login/PII; dados estáticos cabem em SQLite/arquivos. Postgres entra com multi-instância/audit pesado (ver Seção 0.5) |
| Cache + filas | Redis + BullMQ | Posições de ônibus, viagens ativas (TTL 2h), workers |
| Descoberta de rotas | **Finder espacial caseiro sobre GTFS** (não OTP no V1) | Para V1 (poucos corredores) basta achar linhas que passam perto de O e D no sentido certo via índice espacial. OTP é desproporcional; revisitar só se transbordo multi-perna virar essencial (ver Seção 0.5). **NÃO é fonte de ETA realista (ver Seção 0.1).** |
| Motor de ETA realista | **Serviço caseiro** sobre `/Posicao` (map-matching + velocidade por segmento) | SPTrans não tem GTFS-RT; o diferencial Waze tem que ser construído. **Spike #1 de validação.** |
| Hospedagem | VPS Hetzner + Docker Compose | ~€5/mês inicial; escala horizontal depois |
| CDN/WAF | Cloudflare (free) | DDoS, picos, TLS borda |
| Auth | **Sem login na V1** | Reduz superfície de ataque; locais salvos via localStorage |
| Tipos compartilhados | Monorepo pnpm workspaces | Mesmo `Route`, `Trip`, `BusPosition` nos dois lados |

### Escopo V1 (cutoff travado)

1. Digitar origem + destino → ver lista comparativa de rotas
2. Tocar numa rota → ver detalhe com mapa colorido por trânsito + barra temporal
3. Salvar locais frequentes ("Casa", "Trabalho") no localStorage

(Push "hora de descer" saiu do core do V1 → V1.1 fast-follow, ver Seção 0.5.)

### Fora da V1 (V2+)

- **(V1.1 — fast-follow, não V2)** Push "hora de descer" — table-stakes, sai logo após o núcleo (ver Seção 0.5)
- Login / conta de usuário / sincronização entre dispositivos
- Histórico de viagens
- Compartilhar rota com terceiro
- Outras cidades além de SP
- Affiliate Uber/99 (slot reservado no design, ativação depois)
- Tier premium (estrutura `plan: free|premium` já modelada no schema)
- Modo offline com cache de mapa

---

## 3. UI / UX

### Tela principal — comparação (Layout A)

Lista vertical de cards. Cada card mostra:

- Nome da linha (ou combinação com transbordo)
- ETA total no destino — número grande, cor indicando trânsito (verde/amarelo/vermelho)
- "Próximo ônibus em X min · trânsito leve/médio/pesado"
- Toque → tela de detalhe

**Razão:** decisão rápida no momento de "vou pegar qual?". Sem mapa nessa tela — comparação numérica direta.

Mockup: `.superpowers/brainstorm/8816-1777392317/content/main-screen-layout.html`

### Tela de detalhe — versão A+

Componentes verticais de cima pra baixo:

1. **Header**: linha + origem→destino + ETA grande (chega às HH:MM)
2. **Faixa narrativa de 1 linha**: ex. "⚠ Faria Lima travada custa +6 min · ainda é a opção mais rápida"
3. **Mapa grande** (60-65% da tela):
   - Rota colorida segmento por segmento por trânsito (verde/amarelo/vermelho)
   - Posição do ônibus em tempo real (ponto azul pulsante)
   - Anotação flutuante sobre hot spots de trânsito ("⚠ Faria Lima · +6min")
   - Etiquetas: "você", "destino", "ônibus · chega em Xmin"
4. **Barra de progresso temporal**: gradiente colorido mostrando proporção de cada trecho com horários (sai 14:32 → embarca 14:36 → chega 15:10)
5. **Legenda** das cores
6. **CTA primária**: botão amarelo "Avisar quando chegar" (dispara permissão de push)
7. **Secundária**: "Compartilhar"

**Razão da escolha A+:** mapa é a essência da analogia com Waze (visual). Faixa narrativa + anotação flutuante resolvem o problema de "só cor não conta a história".

Mockup: `.superpowers/brainstorm/8816-1777392317/content/detail-a-plus.html`

### Tela "estou neste ônibus" (a desenhar)

Pendente de design visual. Lógica fechada:

- Tela mostra rota atual com ponto de descida marcado
- Botão "Estou neste ônibus" registra trip ativa no servidor
- Sem rastreamento GPS do cliente — servidor vigia posição via SPTrans
- Push dispara quando ônibus a 2 paradas / 400m do ponto de descida
- Confirmação de proximidade GPS opcional no momento do "embarquei" pra validar bus correto

---

## 4. Arquitetura técnica

### Diagrama de alto nível

```
┌─────────────────────────────────────────────────────────────────┐
│                      USUÁRIO (mobile/desktop)                    │
│              PWA (Vite + React + Service Worker)                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS
                           ▼
              ┌─────────────────────────┐
              │     CLOUDFLARE          │  CDN, WAF, DDoS, TLS
              └────────────┬────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │   Caddy (reverse proxy) │  TLS interno, headers
              └────────────┬────────────┘
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
┌──────────────┐  ┌──────────────┐    ┌──────────────┐
│   Fastify    │  │  Web Push    │    │  Static      │
│   API        │  │  endpoint    │    │  assets      │
│  (stateless) │  │  (VAPID)     │    │              │
└──┬────┬───┬──┘  └──────┬───────┘    └──────────────┘
   │    │   │            │
   │    │   │            ▼
   │    │   │    ┌──────────────┐
   │    │   │    │  navegador   │
   │    │   │    │  Service     │
   │    │   │    │  Worker      │
   │    │   │    └──────────────┘
   │    │   ▼
   │    │  ┌────────────────────────┐
   │    │  │   PostgreSQL           │  feature_flags, cidades,
   │    │  │                        │  paradas estáticas, audit
   │    │  └────────────────────────┘
   │    ▼
   │   ┌────────────────────────┐
   │   │   Redis                │  cache de posições de ônibus,
   │   │                        │  viagens ativas (TTL 2h),
   │   │                        │  filas BullMQ
   │   └─────────┬──────────────┘
   │             │
   │             ▼
   │   ┌────────────────────────┐
   │   │  Worker (BullMQ)       │
   │   │  • Poller SPTrans      │ ───▶ SPTrans Olho Vivo API
   │   │    (1x/30s)            │      (chave única, externa)
   │   │  • Trip notifier       │ ───▶ Web Push (VAPID)
   │   │    (1x/15s)            │
   │   └────────────────────────┘
   ▼
┌────────────────────────┐
│  OpenTripPlanner       │  Java, GTFS estático SPTrans,
│  (interno, sem porta   │  responde "rotas candidatas A→B"
│   pública)             │  (por TABELA — ver Seção 0.1)
└────────────────────────┘
```

> **Rev. 0.5 (2026-06-22):** no V1 o bloco OTP é substituído por um finder espacial
> caseiro sobre o GTFS, e o Postgres é adiado (SQLite + config). Ver Seção 0.5.

### Princípios

- **API stateless** → escala horizontal trivial atrás de LB
- **Worker centralizado de SPTrans** desde dia 1 — 1 chamada/intervalo serve todos os usuários, custo O(1) em vez de O(usuários ativos), respeita rate limit. **Esse worker também alimenta o motor de ETA caseiro** (Seção 0.1): além de cachear posições, computa velocidade por segmento.
- **Descoberta de rotas via finder caseiro** (V1; OTP adiado, ver Seção 0.5): índice espacial sobre o GTFS acha linhas candidatas A→B por proximidade de O e D. O ETA realista/trânsito vem do motor caseiro, não do roteador.
- **Redis como hub central** — cache, BullMQ e estado de viagens ativas
- **Cloudflare na borda** — DDoS + CDN + abuso

---

## 5. Estratégia de monetização (decidida estruturalmente, não ativada V1)

Em ordem de probabilidade pra solo dev:

1. **Affiliate Uber/99** — quando ETA do ônibus ultrapassa threshold, mostrar "Uber faria em Y · R$Z" com link de afiliado (~5-10% comissão). Slot já reservado no design.
2. **Freemium** R$ 9-19/mês — múltiplos alertas, modo offline, widget (com Capacitor), histórico ilimitado, sem ads. Schema já tem `plan: free|premium`.
3. **Ads** — só acima de ~50k DAU, marginal.
4. **B2B / B2G** (médio prazo) — dashboard de fluxo pra prefeitura/SPTrans/empresas de logística.

**Não recomendado:** vender dados de localização (LGPD).

### Custos previstos

| DAU | Infra | Custo/mês |
|---|---|---|
| 100 | 1 VPS Hetzner CX22 | ~€5 |
| 10k | 2-3 VPS + Postgres | ~€30-50 |
| 100k | LB + Postgres dedicado + Cloudflare pago | ~€250 |
| 1M+ | Arquitetura mais séria — mas com receita | varia |

---

## 6. Future-proofing built-in V1

Decisões que custam zero hoje e abrem caminho pra escala/monetização:

- [x] Cloudflare na frente (free)
- [x] Worker centralizado SPTrans (escala horizontal trivial depois)
- [x] **Histórico de velocidade por segmento persistido desde o dia 1** — moat de dados que compõe com o tempo (Seção 0.5)
- [x] Telemetria desde o começo (Plausible self-host ou PostHog free)
- [x] Slot pré-reservado de affiliate banner no UI
- [ ] ~~`city_id` em toda tabela~~ — **adiado**: pressupõe Postgres. YAGNI até multi-cidade real (Seção 0.5)
- [ ] ~~Tabela `feature_flags`~~ — **adiado**: começa como config/flag em arquivo; vira tabela com o Postgres (Seção 0.5)
- [ ] ~~Schema com `plan: free|premium`~~ — **adiado** junto com o Postgres (Seção 0.5)

---

## 7. Segurança e manutenção

### Segurança (concreto)

- **Validação no boundary** com Zod em toda entrada HTTP e em todo dado vindo da SPTrans
- **Sem login na V1** = sem auth surface
- **Sem PII persistida** — viagem ativa em Redis com TTL 2h e auto-expira
- **Helmet** (security headers), **fastify-rate-limit** (anti-abuso), **CSP estrito** no front
- **Dependabot** + `pnpm audit` no CI
- **OTP num container interno**, sem porta pública
- **Secrets** via env vars (nunca no repo), VAPID keys separadas das de DB
- **LGPD**: geolocalização pedida no momento do uso, não armazenada

### Manutenção

- TypeScript estrito ponta a ponta com tipos compartilhados via monorepo
- Vite + Fastify (menos mágica que Next.js, separação clara cliente/servidor)
- Estrutura por feature (`/features/route-search`, `/features/trip-tracking`)
- Docker Compose levanta tudo com 1 comando

---

## 8. Pendente de discutir e aprovar (pegamos aqui na próxima sessão)

> **As Seções 2-6 estão BLOQUEADAS no go/no-go do spike (item 0) — não preencher no
> escuro. O design de produto só avança guiado pelos dados do spike (ver Seção 0.5).**

- [ ] **Item 0 — SPIKE DE VALIDAÇÃO DO MOTOR DE ETA (bloqueia todo o resto, ver Seção 0)**
  - Coletar `/Posicao` de 3-4 linhas por ~2 semanas
  - Map-matching das posições no shape do GTFS estático
  - Computar velocidade real por segmento → projetar chegada
  - Comparar projeção vs. realidade observada; medir erro
  - **Critério de go/no-go:** se a precisão não for útil, repensar o produto antes de qualquer build
- [ ] **Seção 2 — Componentes detalhados** (responsabilidade de cada serviço, contratos de I/O) — incluir o serviço motor-de-ETA como componente de primeira classe
- [ ] **Seção 3 — Fluxo de dados** (3 jornadas: busca de rota, tracking de viagem, recebimento de push)
- [ ] **Seção 4 — Tratamento de erros** (SPTrans fora do ar, OTP timeout, push permission negada, rate limits)
- [ ] **Seção 5 — Estratégia de testes** (unit, integration, e2e — o que cobrir e onde parar)
- [ ] **Seção 6 — Roadmap V1** (sprints/marcos, ordem de construção, dependências)
- [ ] **Mockup pendente:** tela "estou neste ônibus" + tela inicial (input de origem/destino com locais salvos)
- [ ] **Self-review do spec** (placeholders, contradições, escopo, ambiguidade)
- [ ] **User review final**
- [ ] **Invocar `superpowers:writing-plans`** pra gerar plano de implementação

---

## 9. Estrutura de pastas planejada

```
bus-routes-sp/
├── apps/
│   ├── web/                # Vite + React + PWA
│   │   ├── src/
│   │   │   ├── features/
│   │   │   │   ├── route-search/
│   │   │   │   ├── route-detail/
│   │   │   │   └── trip-tracking/
│   │   │   ├── components/
│   │   │   ├── lib/
│   │   │   └── service-worker.ts
│   │   └── vite.config.ts
│   └── api/                # Fastify
│       ├── src/
│       │   ├── features/
│       │   ├── plugins/    # helmet, rate-limit, swagger
│       │   ├── workers/    # poller, trip-notifier
│       │   └── server.ts
│       └── package.json
├── packages/
│   └── shared-types/       # Zod schemas + TS types
├── infra/
│   ├── docker-compose.yml  # V1: api + redis + caddy (postgres/otp adiados — Seção 0.5)
│   ├── caddy/Caddyfile
│   └── otp/                # configs do OpenTripPlanner
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-04-28-bus-routes-sp-design.md
├── .github/
│   └── workflows/ci.yml
├── pnpm-workspace.yaml
└── package.json
```

---

## 10. Referências externas

- **SPTrans Olho Vivo API** — https://www.sptrans.com.br/desenvolvedores (cadastro de token gratuito)
- **GTFS estático SPTrans** — publicado em https://www.sptrans.com.br/desenvolvedores
- **OpenTripPlanner** — https://www.opentripplanner.org/
- **Web Push (VAPID)** — RFC 8292
- **MapLibre GL JS** — https://maplibre.org/ (para o mapa, alternativa open source ao Mapbox)
- **Tiles do mapa** — Stadia Maps (free tier generoso) ou OpenStreetMap direto
