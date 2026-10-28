---
name: b3-grafico
description: >-
  Gráfico de velas colorido no terminal para mini índice (WIN) e mini dólar
  (WDO), como o da plataforma da corretora: velas, volume, médias
  exponenciais, VWAP, Hi-Lo, as entradas e saídas de uma estratégia, a linha
  de stop, alvo e entrada da posição aberta, e o preço atual na escala. Roda
  uma vez, ao vivo (recarregando o arquivo que o MetaTrader 5 alimenta) ou em
  replay do histórico. Monta um painel no tmux com os gráficos, uma coluna de
  status (preço, pregão, contrato, rolagem, situação de cada estratégia,
  eventos do dia) e uma janela de comparação. Exporta PNG e SVG. Use quando o
  usuário disser "mostra o gráfico", "abre o painel", "quero ver as velas",
  "monta o tmux", "replay do dia", "acompanha ao vivo", "tira um print do
  gráfico", ou depois da b3-sinais.
argument-hint: "[arquivo] [--tf N] [-e estratégia]"
---

# b3-grafico

A parte visual do pacote. Só lê os arquivos de `b3/dados/`, `b3/sinais/` e
`b3/estado/`: não envia ordens.

Depende de `b3-contratos`, `b3-dados` e `b3-sinais` instaladas ao lado. Só
biblioteca padrão do Python; o painel precisa do `tmux` (Linux, macOS ou WSL
no Windows). Para exportar PNG, o Pillow (`pip install Pillow`), opcional.

`${CLAUDE_SKILL_DIR}` é a pasta desta skill.

```bash
# um gráfico, uma vez
python3 "${CLAUDE_SKILL_DIR}/grafico.py" b3/dados/WIN_5m.csv -e rompimento_abertura --vwap

# ao vivo, a partir do 1 min que o mt5.py grava, desenhado em 5 min
python3 "${CLAUDE_SKILL_DIR}/grafico.py" b3/dados/WIN_1m_aovivo.csv --tf 5 --seguir 1 -e setup_9_1

# replay do histórico, um candle a cada 0,3 s
python3 "${CLAUDE_SKILL_DIR}/grafico.py" b3/dados/WIN_1m.csv --tf 5 --replay 0.3 --inicio 2026-10-20

# imagem para compartilhar
python3 "${CLAUDE_SKILL_DIR}/grafico.py" b3/dados/WIN_5m.csv --dias 1 --largura 150 --altura 40 --png win.png

# o painel completo no tmux
"${CLAUDE_SKILL_DIR}/painel.sh" demo            # dados fictícios em replay
"${CLAUDE_SKILL_DIR}/painel.sh" aovivo          # com o mt5.py ao-vivo rodando
"${CLAUDE_SKILL_DIR}/painel.sh" arquivo --tf 15 -e vwap
```

## O que aparece

- **Cabeçalho**: ativo, contrato, tempo gráfico, último preço, variação do dia
  (contra o fechamento anterior), máxima, mínima, volume, `FICTÍCIO` quando os
  dados são mock, data e hora do último candle.
- **Velas** verdes (alta) e vermelhas (baixa) com meia linha de resolução,
  alinhadas à direita como na plataforma. Separador pontilhado entre os dias.
- **Linhas**: MME 9 e 21 (`--medias`), VWAP (`--vwap`), Hi-Lo (`--hilo 8`).
- **Estratégia** (`-e`): ▲ compra, ▼ venda, ✕ saída (verde se ganhou, vermelho
  se perdeu). Com posição aberta: linhas de entrada (azul), stop (vermelho) e
  alvo (verde), com rótulo na escala. Se o stop ou o alvo ficam longe demais,
  o rótulo fica preso na borda com uma seta ↑ ou ↓.
- **Volume** embaixo e **eixo do tempo** com as datas.
- **Rodapé**: pregão aberto ou fechado, resumo da estratégia (operações,
  acerto, pontos brutos) e a posição ou o sinal do momento.

## O painel no tmux

`painel.sh` cria a sessão `b3` com três janelas:

1. **principal**: WIN e WDO no tempo gráfico escolhido, com a estratégia, e
   a coluna `painel.py` à direita (preço, pregão, contrato e rolagem de cada
   ativo; a situação das seis estratégias; os eventos do dia).
2. **1min**: WIN e WDO em 1 minuto.
3. **estrategias**: a comparação das estratégias, atualizada a cada minuto.

Modos: `demo` (gera dados fictícios se faltar e reproduz em replay; a coluna
segue o horário do replay), `aovivo` (lê `b3/dados/*_1m_aovivo.csv`, que o
`b3-dados/mt5.py ao-vivo` grava), `arquivo` (redesenha os arquivos de
`b3/dados/` a cada 2 s).

Lista de monitoramento: com o `b3-dados/mt5.py cotacoes` rodando, a coluna
troca as caixas de WIN e WDO por uma lista de código, cotação e variação do
dia (IBOV, dólar pelo `WDO$N`, PETR4, VALE3, ITUB4... ou a lista de
`--simbolos`). Se o arquivo parar de atualizar, o título vira "parado HH:MM:SS".
`painel.py --monitor nao` volta às caixas.

No tmux: `Ctrl+b` e depois `1`, `2` ou `3` troca de janela, `Ctrl+b d` sai e
deixa rodando, `tmux attach -t b3` volta, `tmux kill-session -t =b3` fecha. O
mouse troca de painel.

**MetaTrader 5 no Windows + tmux no WSL**: rode o `mt5.py ao-vivo` no
Windows, na pasta do projeto, e o `painel.sh aovivo` no WSL, na mesma pasta
(por exemplo `/mnt/c/Users/voce/projeto`). Os dois conversam pelos arquivos de
`b3/`.

## Passos

1. Confira se há dados em `b3/dados/`. Se não, rode a `b3-dados` (`mock` para testar).
2. Para mostrar ao usuário dentro da conversa, gere um PNG (`--png`) e envie.
   Para ele usar no computador, passe o comando do `painel.sh`.
3. Se for mostrar uma estratégia, use o mesmo nome e parâmetros da `b3-sinais`.
4. Com dados `mock`, diga que o gráfico é fictício.

## O que nunca faz

- Nunca envia ordem nem fala com corretora.
- Nunca esconde o selo `FICTÍCIO` quando os dados são mock.

## Segurança

- Ferramenta de estudo, não é recomendação de investimento.
- O gráfico mostra o que está no arquivo. Confira preços na sua plataforma
  antes de qualquer decisão.
