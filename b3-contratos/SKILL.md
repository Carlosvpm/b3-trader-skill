---
name: b3-contratos
description: >-
  Regras dos contratos futuros da B3: mini índice (WIN) e mini dólar (WDO).
  Diz qual é o contrato vigente numa data (WINZ26, WDOX26...), quando vence,
  qual o último dia de negociação e quando rolar; se o pregão está aberto e
  quando abre de novo; os dias sem pregão (calendário oficial B3 de 2026,
  calculado para outros anos, Quarta-feira de Cinzas abrindo às 13h); e quanto
  vale uma variação de pontos em reais (WIN R$ 0,20 por ponto, tick de 5; WDO
  R$ 10 por ponto, tick de 0,5). Use quando o usuário disser "qual o contrato
  do mini índice agora", "quando vence o WIN", "quando rolar o dólar", "a bolsa
  está aberta", "tem pregão amanhã", "feriados da B3", "quanto dá 300 pontos
  no mini índice", "quanto ganhei de 5410 a 5395 no WDO", ou antes de buscar
  dados, rodar um backtest ou calcular risco.
argument-hint: "[WIN|WDO] [data]"
---

# b3-contratos

A base do pacote. Toda conta de preço, de contrato e de horário passa por
aqui, para que nenhuma skill chute vencimento, feriado ou valor de ponto.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill (onde está este SKILL.md).

```bash
python3 "${CLAUDE_SKILL_DIR}/contratos.py" info WIN
python3 "${CLAUDE_SKILL_DIR}/contratos.py" vigente WIN --data 2026-10-28
python3 "${CLAUDE_SKILL_DIR}/contratos.py" vencimentos WDO --ano 2027
python3 "${CLAUDE_SKILL_DIR}/contratos.py" pregao --agora "2026-11-02 10:00"
python3 "${CLAUDE_SKILL_DIR}/contratos.py" feriados --ano 2026
python3 "${CLAUDE_SKILL_DIR}/contratos.py" valor WIN --pontos 350 --contratos 2
python3 "${CLAUDE_SKILL_DIR}/contratos.py" valor WDO --de 5412.5 --para 5398 --lado venda
```

Todo comando aceita `--json`. Sem `--data` ou `--agora`, usa hoje no horário de
Brasília (UTC-3 fixo: o Brasil não tem horário de verão desde 2019).

## As regras

| | WIN (Futuro Mini de Ibovespa) | WDO (Futuro Mini de Dólar) |
| --- | --- | --- |
| valor do ponto | R$ 0,20 por contrato | R$ 10,00 por contrato |
| tick | 5 pontos = R$ 1,00 | 0,5 ponto = R$ 5,00 |
| vencimentos | meses pares: G J M Q V Z | todo mês: F G H J K M N Q U V X Z |
| vencimento | quarta-feira mais próxima do dia 15 (sem pregão: próximo dia útil) | primeiro dia útil do mês |
| último dia de negociação | o próprio vencimento | último dia útil do mês anterior |
| horário (desde 09/03/2026) | 09:00 às 18:25 | 09:00 às 18:30 |
| código | WIN + letra do mês + ano com 2 dígitos | WDO + letra + ano |

**Rolagem.** A liquidez migra para o próximo vencimento alguns dias antes do
fim. A regra prática deste pacote: rolar 2 dias úteis antes do último dia de
negociação. `vigente` devolve `contrato_liquido`, que já aplica essa regra, e é
esse código que as outras skills usam. Ajuste em `b3/config.json`
(`rolagem_dias_uteis`).

**Calendário.** 2026 usa a lista oficial publicada pela B3. Os outros anos são
calculados (feriados nacionais, Carnaval, Sexta-feira Santa e Corpus Christi
pela Páscoa, 24/12 e 31/12) e saem marcados como "calculado". Quando a B3
publicar o calendário do ano, confira e, se algo divergir, corrija em
`b3/config.json` (`feriados_extras`, `dias_com_pregao`).

**Horários.** A B3 muda o horário de negociação algumas vezes por ano, em geral
junto do horário de verão dos EUA. O padrão do script vale desde 09/03/2026. Se
a B3 mudar, ou se seus dados forem de antes disso, coloque os períodos em
`b3/config.json` (veja `config.example.json`), cada um com a data `desde`.

## Passos

1. Para qualquer pergunta sobre contrato, vencimento, feriado, horário ou valor
   em reais, rode o comando. Não responda de memória.
2. Mostre a resposta curta: o código, a data, o valor em reais.
3. Se o resultado vier de um ano "calculado" ou de horário que pode ter mudado,
   diga isso em uma linha e aponte a página oficial da B3.
4. Se o usuário corrigir uma regra (feriado novo, horário novo), grave em
   `b3/config.json` e rode de novo.

## Exemplo

```
$ contratos.py vigente WDO --data 2026-10-28
WDO em 2026-10-28
  vigente:  WDOX26  vence 2026-11-03, último dia 2026-10-30 (2 dias úteis)
  próximo:  WDOZ26  vence 2026-12-01
  use:      WDOZ26
  Já passou do ponto de rolagem: a liquidez costuma migrar para WDOZ26.
```

O WDOX26 vence em 03/11 porque 01/11 é domingo e 02/11 é Finados.

## O que nunca faz

- Nunca envia ordem nem fala com corretora.
- Nunca dá recomendação de compra ou venda.
- Nunca inventa um feriado ou horário: se não souber, diz que é calculado e
  manda conferir na B3.

## Segurança

- Ferramenta de estudo, não é recomendação de investimento. Futuros são
  alavancados: um movimento pequeno do preço vira um valor grande em reais.
- Confira contrato, horário e feriados na B3 e na sua corretora antes de operar.
