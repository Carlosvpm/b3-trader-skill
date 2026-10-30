---
name: b3-scanner
description: >-
  Varre o mini índice (WIN) e o mini dólar (WDO) no diário e em vários tempos
  gráficos (5, 15, 60 min) e lista os setups que aparecem no último candle
  fechado, para os dois lados: rompimento da máxima ou mínima de N candles,
  bandeira de alta ou de baixa, retomada da média de 20, IFR sobrevendido ou
  sobrecomprado, repique depois do extremo, rompimento da faixa de abertura
  (ORB) do dia e a situação das seis estratégias da b3-sinais. Diz quando o
  dado está parado, marca dado fictício e sugere a linha pronta para testar o
  plano na b3-timemachine. Use quando o usuário disser "o que tem de setup
  agora", "varre o WIN e o WDO", "tem rompimento?", "como está a abertura de
  hoje", "roda o scanner", "o que apareceu no 15 minutos", ou antes da
  abertura para preparar o dia.
argument-hint: "[--ativos WIN,WDO] [--tfs D,5,15,60] [--setups ...]"
---

# b3-scanner

Lê os candles da `b3-dados`, monta o diário e os tempos gráficos pedidos e
aplica regras fixas no **último candle fechado**. Grava a lista em
`b3/scanner/varredura.json`.

Uma varredura é uma lista de gráficos que batem com uma regra. Não é uma
lista do que comprar ou vender.

Depende de `b3-contratos`, `b3-dados` e `b3-sinais` instaladas ao lado.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/scanner.py"                          # WIN e WDO, D + 5, 15 e 60 min
python3 "${CLAUDE_SKILL_DIR}/scanner.py" --ativos WDO --tfs 5,15
python3 "${CLAUDE_SKILL_DIR}/scanner.py" --aovivo                 # prefere o arquivo que o mt5.py alimenta
python3 "${CLAUDE_SKILL_DIR}/scanner.py" --setups rompimento,orb -p rompimento_n=30
python3 "${CLAUDE_SKILL_DIR}/scanner.py" --agora "2026-10-28 10:15"   # como estava naquele momento
python3 "${CLAUDE_SKILL_DIR}/scanner.py" listar
```

## Os setups

| nome | alta | baixa | parâmetros |
| --- | --- | --- | --- |
| `rompimento` | fecha acima da máxima dos N candles anteriores | fecha abaixo da mínima | `rompimento_n=20` |
| `bandeira` | mastro de alta, depois candles apertados sem devolver metade | o espelho | `bandeira_impulso=10 bandeira_consolidacao=5 bandeira_impulso_atr=3 bandeira_faixa_atr=1.5 atr=14` |
| `retomada_media` | fecha acima da média de 20 vindo de baixo | perde a média | `media=20` |
| `ifr_extremo` | IFR14 abaixo de 30 (sobrevendido) | acima de 70 (sobrecomprado) | `ifr_periodo=14 ifr_baixo=30 ifr_alto=70` |
| `repique` | IFR estava abaixo de 30 e o candle fechou subindo | acima de 70 e fechou caindo | idem |
| `orb` | um candle de 5 min fecha acima da faixa dos primeiros 15 min de hoje | fecha abaixo | `orb_minutos=15 orb_tf=5` |
| `estrategias` | posição, ordem armada, sinal ou saída de cada estratégia da `b3-sinais` | | os da `b3-sinais` |

O rompimento e a bandeira usam máxima e mínima de verdade (não só
fechamentos), e o tamanho da bandeira é medido em ATR para valer igual no WIN,
no WDO e em qualquer tempo gráfico. Os tempos intradiários leem os últimos
`dias=40` pregões; o diário usa o arquivo todo.

## Como ele lê os candles

- Procura o arquivo mais fino em `b3/dados/`: `ATIVO_1m.csv`, depois 5, 15 e
  60 min. Com `--aovivo`, começa por `ATIVO_1m_aovivo.csv`.
- Reamostra para cada tempo pedido e **descarta o candle que ainda está se
  formando**: o sinal só vale no fechamento, igual à `b3-sinais`.
- O diário só entra com o pregão completo. Durante o pregão, o último diário é
  o de ontem.
- `--agora` fixa o relógio e corta tudo o que fechou depois: serve para rever
  um momento do passado sem olhar o futuro.
- Se o pregão está aberto e o último candle tem mais de 15 minutos, avisa que
  o dado pode estar parado (MT5 desconectado, por exemplo).

## A saída

Na tela: o que foi varrido, a faixa de abertura de cada ativo, a lista de
setups e, quando o setup tem stop definido (ORB e estratégias), a linha pronta
para a `b3-timemachine`.

`b3/scanner/varredura.json`: `as_of`, `ficticio`, `parametros`, `varridos`,
`orb`, `hits[]` (ativo, tf, setup, direção, candle, preço, contrato, detalhe,
nível e plano quando houver) e `avisos`.

Código de saída: 0 quando acha algo, 1 quando não acha nada, 2 em erro.

## Passos

1. Confirme que há dados em `b3/dados/`. Se não houver, rode a `b3-dados`
   antes (`mock` serve para testar).
2. Rode a varredura. Antes da abertura, o diário e o 60 min contam mais; no
   pregão, o 5 e o 15 min e o ORB.
3. Mostre a lista em poucas linhas, agrupada por ativo. Diga o horário do
   último candle de cada um.
4. Com dados `mock`, diga que a lista é fictícia: serve para testar o fluxo.
5. Se o usuário quiser saber se um setup "vale a pena", ofereça a
   `b3-timemachine` com a linha sugerida e a `b3-sinais` para o histórico da
   estratégia.
6. A lista vence quando o preço anda: rode de novo antes de qualquer decisão.

## O que nunca faz

- Nunca envia ordem. Só lê `b3/dados/` e grava `b3/scanner/`.
- Nunca diz que um setup vai funcionar, nem chama a lista de recomendação.
- Nunca apresenta resultado com dados fictícios como evidência.

## Limites

- Regras simples aplicadas a candles: não vê livro de ofertas, fluxo, notícia
  nem agenda (Copom, payroll, IPCA).
- Os parâmetros são pontos de partida, tirados de descrições públicas dos
  setups. Variam entre autores.
- Feriados e horários vêm da `b3-contratos`: confira se a B3 mudou algo.

## Segurança

- Ferramenta de estudo, não é recomendação de investimento.
- Futuros são alavancados. Teste em conta de simulação antes de qualquer coisa real.
