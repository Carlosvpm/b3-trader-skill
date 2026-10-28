---
name: b3-sinais
description: >-
  Aplica estratégias de day trade nos candles de mini índice (WIN) e mini
  dólar (WDO) e mostra os sinais e as operações simuladas, com stop, alvo e
  resultado bruto em pontos e em reais. Seis estratégias prontas e
  configuráveis: rompimento da faixa de abertura (ORB), Setup 9.1 de Larry
  Williams, cruzamento de médias 9 x 21, lado da VWAP, IFR2 (Stormer) e Hi-Lo
  Activator. Diz a situação no último candle (posição, ordem armada, sinal de
  saída) e compara as estratégias lado a lado. Use quando o usuário disser
  "roda o setup 9.1 no WIN", "qual estratégia foi melhor", "compara as
  estratégias", "tem sinal agora?", "testa o rompimento da abertura no dólar",
  "muda o stop para", "quais estratégias você tem", ou depois da b3-dados.
argument-hint: "[arquivo] [estratégia] [nome=valor ...]"
---

# b3-sinais

Lê os arquivos da `b3-dados` e aplica uma estratégia candle a candle, do jeito
que ela teria rodado ao vivo. Grava o resultado em `b3/sinais/`, onde o gráfico
(`b3-grafico`) e, depois, o risco e a ponte vão buscar.

Depende de `b3-contratos` e `b3-dados` instaladas ao lado.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/sinais.py" listar
python3 "${CLAUDE_SKILL_DIR}/sinais.py" rodar b3/dados/WIN_5m.csv -e rompimento_abertura
python3 "${CLAUDE_SKILL_DIR}/sinais.py" rodar b3/dados/WDO_5m.csv -e setup_9_1 -p validade=3 -p vender=false
python3 "${CLAUDE_SKILL_DIR}/sinais.py" comparar b3/dados/WIN_1m.csv --tf 15
python3 "${CLAUDE_SKILL_DIR}/sinais.py" agora b3/dados/WIN_1m_aovivo.csv --tf 5 -e vwap
```

## As estratégias

| nome | ideia | entrada | stop | saída | parâmetros |
| --- | --- | --- | --- | --- | --- |
| `rompimento_abertura` | ORB | candle fecha fora da faixa dos primeiros minutos | outro lado da faixa | alvo de `rr` vezes o risco | `minutos=15 rr=2 buffer_ticks=1` |
| `setup_9_1` | Larry Williams | MME9 vira: ordem stop 1 tick além da máxima (ou mínima) do candle que virou | 1 tick além do outro extremo dele | MME9 vira contra | `periodo=9 validade=2 vender=true` |
| `cruzamento_medias` | tendência | MME rápida cruza a lenta | extremo dos últimos `stop_candles` | cruzamento contrário | `rapida=9 lenta=21 stop_candles=5` |
| `vwap` | lado da VWAP | candle fecha cruzando a VWAP do dia | extremo dos últimos `stop_candles` | fecha do outro lado | `inicio=09:30 stop_candles=3` |
| `ifr2` | Stormer | IFR de 2 períodos abaixo de `entrada` | nenhum por padrão (`stop_pontos`) | máxima dos 2 últimos candles, ou `max_candles` | `entrada=25 max_candles=7 vender=false` |
| `hilo` | Hi-Lo Activator | Hi-Lo vira | linha do Hi-Lo (stop móvel) | Hi-Lo vira contra | `periodo=8` |

Parâmetros gerais, valem para todas: `contratos=1`, `fim_entradas=17:30`,
`zerar_em=17:55`, `max_operacoes_dia=0` (sem limite).

Mude com `-p nome=valor` na linha de comando, ou deixe fixo em
`b3/estrategias.json` (modelo em `estrategias.example.json`).

As regras foram tiradas de descrições públicas dos setups. Os próprios autores
avisam que há variações, e o IFR2 foi pensado para o gráfico diário: no
intraday, os custos pesam muito. Trate os parâmetros como ponto de partida.

## Como a simulação funciona

As mesmas regras para todas, para que a comparação seja justa:

- o sinal sai no **fechamento** do candle, só com dados até ali (sem olhar o futuro);
- ordem a mercado entra na **abertura do candle seguinte**;
- ordem stop entra quando o preço toca o gatilho; num gap, pelo preço de abertura;
- se o stop e o alvo cabem no mesmo candle, conta o **stop** (pessimista);
- uma posição por vez, um sentido por vez;
- day trade: nada de entrada depois de `fim_entradas`, posição zerada em
  `zerar_em` ou no último candle do dia, ordem pendente não passa para o dia seguinte;
- resultado **bruto**: sem corretagem, emolumentos, impostos nem slippage. A
  `b3-backtest` (próxima versão) desconta tudo isso.

## O arquivo gravado

`b3/sinais/WIN_5m_rompimento_abertura.json`:

- `operacoes`: cada uma com lado, entrada (hora, preço, motivo), stop inicial,
  alvo, saída (hora, preço, motivo), pontos e reais;
- `aberta`: a posição ainda aberta no último candle, com o resultado parcial;
- `pendente`: a ordem armada ou o sinal para o próximo candle;
- `ultimo_sinal` e `resumo` (acerto, pontos, fator de lucro, drawdown).

Esse arquivo é o que a ponte vai ler no futuro. Hoje, nada sai daqui para
corretora nenhuma.

## Passos

1. Confirme o arquivo e o tempo gráfico. Se não houver dados, rode a
   `b3-dados` antes (`mock` serve para testar).
2. `comparar` para ter a visão geral, `rodar` para os detalhes de uma.
3. Mostre o resumo em poucas linhas: operações, acerto, pontos, reais, fator
   de lucro e drawdown. Diga sempre que é resultado bruto.
4. Com dados `mock`, diga que o resultado é fictício e não serve para escolher
   estratégia: o objetivo é testar o fluxo.
5. Para ajustar, mude um parâmetro por vez e compare. Desconfie de ajuste fino
   demais num período curto: é o caminho mais rápido para uma estratégia que
   só funciona no passado.

## O que nunca faz

- Nunca envia ordem. Só grava arquivos em `b3/sinais/`.
- Nunca chama resultado bruto de lucro.
- Nunca apresenta resultado com dados fictícios como evidência.

## Segurança

- Ferramenta de estudo, não é recomendação de investimento. Resultado passado,
  simulado, não garante resultado futuro.
- Futuros são alavancados. Teste em conta de simulação antes de qualquer coisa real.
