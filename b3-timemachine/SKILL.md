---
name: b3-timemachine
description: >-
  Máquina do tempo para um plano de day trade no mini índice (WIN) ou no mini
  dólar (WDO): com entrada, stop e alvo definidos, monta 10.000 pregões a
  partir dos candles reais do próprio ativo, sorteados pelo horário do dia, e
  conta quantas vezes o alvo vem antes do stop, quantas o stop vem antes,
  quantas não bate nada até o horário de zerar, o preço provável no fim e o
  resultado médio em R, pontos e reais por contrato. Roda o mesmo plano nos
  pregões reais dos últimos 60 dias e dá um veredito contra o ponto de
  empate. Aceita o plano direto de um arquivo da b3-sinais (posição aberta ou
  ordem armada). Use quando o usuário disser "esse trade vale a pena?",
  "simula essa entrada", "qual a chance de bater o alvo", "testa esse stop",
  "roda a máquina do tempo", ou depois da b3-scanner e da b3-sinais.
argument-hint: "[arquivo] --lado compra|venda --stop-pontos N [--rr 2]"
---

# b3-timemachine

Responde uma pergunta só: **com este stop e este alvo, entrando agora, como
esse ativo costuma se comportar até o horário de zerar?**

Depende de `b3-contratos`, `b3-dados` e `b3-sinais` instaladas ao lado.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
# compra no último preço, stop de 300 pontos, alvo de 2 vezes o risco
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" b3/dados/WIN_5m.csv --lado compra --stop-pontos 300 --rr 2 \
    --data 2026-10-30 --hora 10:00

# preços exatos
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" b3/dados/WIN_5m.csv --lado venda --entrada 130250 \
    --stop 130500 --alvo 129800 --data 2026-10-30 --hora 10:30

# dólar a partir do 1 min (vira 5 min sozinho)
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" b3/dados/WDO_1m.csv --lado compra --stop-pontos 8 --alvo-pontos 12

# o plano que a b3-sinais deixou armado ou aberto
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" b3/dados/WIN_1m_aovivo.csv --tf 5 \
    --de-sinal b3/sinais/WIN_5m_setup_9_1.json
```

Sem `--data` e `--hora`, a entrada é no candle seguinte ao último do arquivo.
Se o arquivo termina no fim do pregão, o script pede os dois. Sem `--entrada`,
o preço é o último fechamento antes da hora da entrada. Stop e alvo vão para
o tick (5 pontos no WIN, 0,5 no WDO).

## Como funciona

1. Separa os pregões **completos** antes da data do plano: sem buraco na grade
   e com o horário normal (a Quarta de Cinzas fica de fora). Usa os últimos
   `--dias 60`. Com menos de 20, recusa.
2. Guarda cada candle como razões: abertura, máxima, mínima e fechamento
   divididos pelo fechamento anterior. O padrão de movimento serve para
   qualquer nível de preço e não sofre com a troca de contrato. O gap da noite
   não entra.
3. Cada pregão simulado começa no preço de entrada e, candle a candle até
   `--ate` (padrão: o `zerar_em` da `b3-sinais`, 17:55), sorteia um candle real
   do mesmo horário, com folga de `--janela 2` candles para cada lado. Assim a
   abertura agitada e o almoço parado aparecem nas horas certas.
4. Dentro de cada candle, o **stop conta antes do alvo**, como na `b3-sinais`.
   Num gap além do stop, a saída é no preço do gap, que é pior que o stop.
5. Repete `--sessoes 10000` vezes com `--semente 19`: o mesmo plano dá sempre o
   mesmo número.

## O que ele mostra

- **alvo primeiro, stop primeiro, nenhum** até o horário de zerar, e quantos
  terminaram no verde;
- o preço no horário de zerar: mediana e a faixa de 90%;
- o **resultado médio** em R (stop = -1, alvo = +RR), em pontos e em reais por
  contrato, bruto;
- o **histórico**: o mesmo plano, com stop e alvo à mesma distância
  percentual, em cada um dos pregões reais, entrando no mesmo horário;
- o **veredito**: a chance de o alvo vir antes do stop comparada com o empate
  de 1 em (1 + RR). Até 5 pontos de diferença é cara ou coroa; 15 ou mais é
  com folga;
- um leque de preços ao longo do dia.

Com `--gravar`, o JSON vai para `b3/timemachine/` com o leque completo, 160
caminhos de exemplo e o histograma do preço final. `--json` imprime o resumo.

## Passos

1. Confirme ativo, lado, entrada, stop e alvo. Se o usuário der só o stop,
   o alvo padrão é 2R: diga isso.
2. Rode e mostre em poucas linhas: as três chances, o resultado médio em R e
   em reais, a linha do histórico e o veredito.
3. Se a simulação e o histórico discordam muito, diga: 60 pregões é pouco, e
   o histórico tem só um caminho por dia.
4. Para posição de estratégia que sai por sinal (Setup 9.1, médias, VWAP,
   Hi-Lo), a máquina do tempo só sabe stop, alvo e horário. Diga que o alvo
   usado é uma aproximação.
5. Com dados `mock`, diga que o número é fictício: o mock é um passeio
   aleatório, então o resultado médio fica perto de zero de propósito.

## Limites

- Candles de 5 min (ou o tempo escolhido), um por vez: não vê a ordem dos
  movimentos dentro do candle nem o tick a tick.
- 60 pregões é uma janela curta. Copom, payroll, decisão do Fed, vencimento e
  notícia fora desse período não aparecem.
- Sorteia cada candle de forma independente: a tendência de um dia inteiro
  aparece menos do que na vida real. O histórico ajuda a ver isso.
- Resultado bruto: sem corretagem, emolumentos, impostos nem slippage.
- É uma simulação, não uma previsão.

## O que nunca faz

- Nunca envia ordem. Só lê `b3/dados/` e `b3/sinais/` e grava `b3/timemachine/`.
- Nunca chama um resultado favorável de garantia, nem de recomendação.
- Nunca apresenta resultado com dados fictícios como evidência.

## Segurança

- Ferramenta de estudo, não é recomendação de investimento. A maior parte de
  quem faz day trade perde dinheiro, e uma simulação favorável não muda isso.
- Futuros são alavancados: no mini dólar, 10 pontos valem R$ 100 por contrato.
  Teste em conta de simulação antes de qualquer coisa real.
