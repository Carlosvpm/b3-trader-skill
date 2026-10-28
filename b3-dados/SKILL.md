---
name: b3-dados
description: >-
  Dados de mini índice (WIN) e mini dólar (WDO) num formato único, em 1, 5,
  15, 30 e 60 minutos. Gera dados FICTÍCIOS (mock) em dias e horários reais de
  pregão para testar o fluxo antes de ter uma fonte; importa exportações do
  MetaTrader 5, do Profit ou CSV genérico; puxa candles direto do MT5 (histórico
  e ao vivo, só leitura); reamostra de 1 min para os outros tempos alinhando à
  abertura do pregão; valida buracos, OHLC, tick, horário, feriados e contrato;
  e monta a série contínua ajustada nas rolagens. Use quando o usuário disser
  "gera dados de teste", "mocka o mini índice", "importa meu CSV do MT5",
  "exportei do Profit", "puxa os candles do MetaTrader", "quero os candles de 5
  e 15 minutos", "tem buraco nos dados?", "valida esse arquivo", "série
  contínua do WIN", ou antes de qualquer backtest.
argument-hint: "[WIN|WDO] [mock|importar|reamostrar|validar|continua|resumo]"
---

# b3-dados

Toda skill seguinte (sinais, backtest, risco) lê os arquivos que esta grava em
`b3/dados/`. Por isso ela tem um formato só, e valida antes de entregar.

Depende de `b3-contratos` instalada ao lado (mesma pasta-mãe): é dela que vêm o
calendário, o horário de pregão, o contrato vigente e o tick.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/dados.py" mock WIN --de 2026-08-03 --ate 2026-10-27
python3 "${CLAUDE_SKILL_DIR}/dados.py" importar export.csv --ativo WDO --tfs 1,5,15,30,60
python3 "${CLAUDE_SKILL_DIR}/dados.py" reamostrar b3/dados/WIN_1m.csv --tfs 5,15,30,60
python3 "${CLAUDE_SKILL_DIR}/dados.py" validar b3/dados/WIN_5m.csv
python3 "${CLAUDE_SKILL_DIR}/dados.py" continua b3/dados/WIN_1m.csv --metodo diferenca
python3 "${CLAUDE_SKILL_DIR}/dados.py" resumo b3/dados/WIN_1m.csv
```

## O formato

```
data_hora,ativo,contrato,abertura,maxima,minima,fechamento,volume,fonte
2026-10-27 09:00,WIN,WINZ26,130125,130210,130090,130180,1834,mock
```

- `data_hora`: início do candle, horário de Brasília, `AAAA-MM-DD HH:MM`.
- `contrato`: o código negociado naquele dia (WINZ26). Na série contínua ele
  continua lá, para saber de onde veio cada trecho.
- Preços com ponto decimal. `volume` em contratos (ou ticks, se a fonte só
  tiver isso).
- `fonte`: `mock`, `mt5`, `profit`, `generico`. **`mock` é dado fictício.**
- Arquivos: `b3/dados/WIN_1m.csv`, `WIN_5m.csv`, `WIN_15m.csv`, `WIN_30m.csv`,
  `WIN_60m.csv`; contínua com sufixo `_continua`.

Os candles de 5, 15, 30 e 60 min começam na abertura do pregão (09:00, 10:00...)
e nunca juntam dois dias. O último do dia pode ser parcial (no WIN, o de 60 min
das 18:00 vai até 18:25).

## Dados mockados

`mock` gera candles de 1 minuto em dias e horários reais de pregão (pula
feriados, abre às 13h na Quarta de Cinzas), com o contrato certo em cada dia,
preço sempre no tick, volatilidade em U ao longo do dia, gap na abertura e um
salto de prêmio na rolagem. Mesma `--semente`, mesmos dados. Os níveis de preço
são inventados.

Sempre que mostrar resultado feito com mock, diga que os dados são fictícios.
Mock serve para testar o encanamento, nunca para concluir que uma estratégia
funciona.

## Fontes reais

- **MetaTrader 5 no Linux**: o terminal roda no Wine (script oficial
  `mt5linux.sh` da MetaQuotes) com o `mt5server.exe` da ponte mt5linux ligado
  (`wine mt5server.exe -p 18812`), e aqui `pip install mt5linux`. O `mt5.py`
  escolhe a ponte sozinho quando o pacote oficial não existe; `--host` e
  `--porta` apontam para um MT5 em outra máquina. Os comandos são os mesmos
  de baixo.
- **MetaTrader 5 no Windows** (terminal aberto e logado):
  ```bash
  pip install MetaTrader5
  python mt5.py simbolo WIN                         # qual código pedir hoje
  python mt5.py exportar WIN --de 2026-09-01        # histórico de 1 min -> b3/dados/
  python mt5.py exportar WIN --de 2026-09-01 --simbolo 'WIN$N'   # série contínua da corretora
  python mt5.py ao-vivo WIN                         # vai gravando os candles fechados
  ```
  O `ao-vivo` grava `b3/dados/WIN_1m_aovivo.csv` (candles fechados) e
  `b3/estado/WIN_ultimo.json` (último preço, bid, ask e o candle em formação).
  Ele usa o contrato vigente pela regra de rolagem, nunca um código fixo.
- **Exportação do MT5** (Ferramentas, Centro de Histórico, ou o gráfico
  exportado): `importar arquivo.csv --ativo WIN`. O formato é detectado sozinho.
- **Exportação do Profit**: `importar arquivo.csv --ativo WIN --formato profit`
  (ponto e vírgula, vírgula decimal, data `dd/mm/aaaa`).
- **Qualquer CSV** com colunas de data, hora, abertura, máxima, mínima e
  fechamento, em português ou inglês: `--formato generico`.

Depois de importar, rode `validar`. Se houver erro, conserte antes de seguir.

## Série contínua

Para backtest de vários meses, os contratos precisam virar uma série só.
`continua` ajusta para trás: o trecho atual fica com o preço real e o passado
é deslocado pelo salto de cada rolagem (`diferenca`, em pontos) ou
multiplicado (`razao`). Com um arquivo só, o salto medido inclui o gap da
noite, então é uma aproximação. Se a plataforma tem a série contínua pronta
(WIN$N no MT5 e no Profit), prefira importá-la. Para calcular resultado em
reais, use os pontos da série ajustada pela `diferenca`.

## Passos

1. Pergunte qual ativo e quais tempos gráficos, se não estiver claro. Padrão:
   1, 5, 15, 30 e 60 min.
2. Sem fonte real ainda: `mock`. Com arquivo: `importar`. Com MT5 na máquina:
   `mt5.py exportar`.
3. `validar` o 1 min. Mostre erros e avisos em poucas linhas.
4. `reamostrar` para os outros tempos (o `mock` e o `importar --tfs` já fazem).
5. Se o período tem rolagem, `continua`.
6. Termine com `resumo`: período, pregões, contratos, e se é fictício.

## O que nunca faz

- Nunca envia ordem. `mt5.py` só lê cotações.
- Nunca apresenta dado mock como real.
- Nunca baixa dados de site que proíbe raspagem, nem pede senha de corretora.

## Segurança

- Ferramenta de estudo, não é recomendação de investimento.
- Dados de corretora podem ter buracos e horários diferentes. Valide sempre.
