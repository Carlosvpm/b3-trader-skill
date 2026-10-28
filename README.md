# b3-trader-skill

Skills do Claude para operar a B3 com método, começando pelo **mini índice
(WIN)** e pelo **mini dólar (WDO)**.

Gratuito, MIT, sem cadastro e sem chave de API. As ferramentas são scripts
Python simples (só a biblioteca padrão), e o Claude roda esses scripts em vez de
fazer conta de cabeça.

**Este pacote não envia ordens.** Ele cuida das regras, dos dados e, nas
próximas versões, dos sinais, do backtest e do risco. A execução fica com uma
plataforma da sua corretora (por exemplo, um robô no MetaTrader 5), sob o seu
controle.

> Status: versão 0.1. Duas skills prontas (`b3-contratos` e `b3-dados`), com
> dados mockados para testar o fluxo antes de ter uma fonte real. Veja o
> [roteiro](#roteiro).

## O que já faz

| comando | o que faz |
| --- | --- |
| `/b3-contratos` | Qual o contrato vigente (WINZ26, WDOX26...), quando vence, quando rolar, se o pregão está aberto, os feriados da B3 e quanto vale uma variação de pontos em reais. |
| `/b3-dados` | Candles de WIN e WDO em 1, 5, 15, 30 e 60 min num formato único: gera dados fictícios para teste, importa do MetaTrader 5 e do Profit, puxa do MT5 ao vivo, valida e monta a série contínua. |

Pergunte em português normal. Por exemplo:

- "Qual o contrato do mini índice hoje e quando eu rolo?"
- "Tem pregão na segunda? E que horas fecha o dólar?"
- "Quanto dá 350 pontos no WIN com 3 contratos?"
- "Gera 3 meses de dados de teste do WDO em 5 e 15 minutos."
- "Importa esse CSV que exportei do MetaTrader e vê se tem buraco."

## Instalar

### No Claude Code, como plugin

```
/plugin marketplace add Carlosvpm/b3-trader-skill
/plugin install b3-trader-skill@b3-trader-skill
```

Como plugin, as skills aparecem com prefixo: `/b3-trader-skill:b3-contratos`.

### No Claude Code, copiando as pastas

Para ter `/b3-contratos` e `/b3-dados` sem prefixo:

```bash
git clone https://github.com/Carlosvpm/b3-trader-skill.git
cp -r b3-trader-skill/b3-* ~/.claude/skills/
```

Só para um projeto: copie as mesmas pastas para `.claude/skills/` dentro do
repositório do projeto.

**Copie sempre as duas juntas.** A `b3-dados` usa o calendário e as regras de
contrato da `b3-contratos`, e procura por ela na pasta ao lado.

### No app do Claude

Cole isto numa conversa:

```
https://github.com/Carlosvpm/b3-trader-skill

install skill
```

Ou envie cada pasta (zipada) na área de Skills das configurações. Sem a
possibilidade de rodar scripts, o `SKILL.md` ainda funciona como guia de
método, mas você perde as contas exatas.

### Requisitos

- Python 3.8 ou mais novo. Nada para instalar com pip.
- Só para puxar dados do MetaTrader 5: Windows, o terminal MT5 aberto e logado
  na sua corretora, e `pip install MetaTrader5`.

## Começo rápido (com dados de teste)

Tudo o que as skills gravam fica numa pasta `b3/` no diretório onde você está
trabalhando.

```bash
python3 b3-contratos/contratos.py vigente WIN
python3 b3-dados/dados.py mock WIN --de 2026-08-03 --ate 2026-10-27
python3 b3-dados/dados.py validar b3/dados/WIN_1m.csv
python3 b3-dados/dados.py continua b3/dados/WIN_1m.csv
python3 b3-dados/dados.py resumo b3/dados/WIN_15m.csv
```

Isso cria `b3/dados/WIN_1m.csv`, `WIN_5m.csv`, `WIN_15m.csv`, `WIN_30m.csv` e
`WIN_60m.csv`, em dias e horários reais de pregão, com o contrato certo em cada
dia e as rolagens no lugar.

**Os dados `mock` são fictícios.** A coluna `fonte` diz `mock`, e as skills
avisam sempre que um resultado vier deles. Servem para testar o fluxo, não para
avaliar estratégia.

## Dados reais pelo MetaTrader 5

No Windows, com o terminal MT5 aberto e logado:

```bash
pip install MetaTrader5
python b3-dados/mt5.py simbolo WIN                    # qual código pedir hoje
python b3-dados/mt5.py exportar WIN --de 2026-09-01   # histórico de 1 min, já em 5/15/30/60
python b3-dados/mt5.py ao-vivo WIN                    # grava os candles conforme fecham
```

O `ao-vivo` mantém dois arquivos:

- `b3/dados/WIN_1m_aovivo.csv`: candles de 1 min já fechados, no formato padrão.
- `b3/estado/WIN_ultimo.json`: último preço, bid, ask e o candle em formação.

O símbolo sai sempre da regra de rolagem, então você não precisa trocar
`WINZ26` por `WING27` na mão. Para usar a série contínua da corretora, passe
`--simbolo 'WIN$N'`. O script só lê cotações e nunca envia ordem.

Também dá para importar o que você exportar à mão:

```bash
python3 b3-dados/dados.py importar export_mt5.csv --ativo WIN --tfs 1,5,15,30,60
python3 b3-dados/dados.py importar export_profit.csv --ativo WDO --formato profit
```

## O formato dos dados

```
data_hora,ativo,contrato,abertura,maxima,minima,fechamento,volume,fonte
2026-10-27 09:00,WIN,WINZ26,130125,130210,130090,130180,1834,mt5
```

- Horário de Brasília. `data_hora` é o início do candle.
- Os candles de 5, 15, 30 e 60 min começam na abertura do pregão (09:00,
  10:00...) e nunca juntam dois dias.
- `contrato` mostra o vencimento negociado naquele dia, mesmo na série contínua.

## As regras que o pacote usa

| | WIN | WDO |
| --- | --- | --- |
| valor do ponto | R$ 0,20 | R$ 10,00 |
| tick | 5 pontos (R$ 1,00) | 0,5 ponto (R$ 5,00) |
| vencimentos | meses pares | todo mês |
| vence | quarta-feira mais próxima do dia 15 | primeiro dia útil do mês |
| último dia de negociação | o vencimento | último dia útil do mês anterior |
| horário (desde 09/03/2026) | 09:00 às 18:25 | 09:00 às 18:30 |
| rolagem (regra prática) | 2 dias úteis antes do último dia | 2 dias úteis antes do último dia |

O calendário de 2026 é a lista oficial da B3. Outros anos são calculados e
marcados como "calculado". A B3 muda o horário de negociação algumas vezes por
ano. Quando isso acontecer, ajuste em `b3/config.json` (modelo em
`b3-contratos/config.example.json`), sem mexer no código.

## Como o pacote foi pensado

- **Uma skill para cada tarefa.** Cada uma lê o que a anterior gravou em `b3/`.
- **Conta é feita por script, nunca de cabeça.** Vencimento, feriado, tick e
  valor em reais saem de código testado.
- **Formato único entre as etapas.** É ele que vai servir de ponte para o
  executor.
- **Testes offline.** Rode `python3 -m unittest discover -s tests -v`.
- **Dado fictício é sempre marcado como fictício.**

## Roteiro

```
contratos -> dados -> sinais -> backtest -> risco -> ponte -> (robô na sua plataforma)
```

| skill | situação | o que vai fazer |
| --- | --- | --- |
| `b3-contratos` | pronta | regras, calendário, rolagem e valor do ponto |
| `b3-dados` | pronta | mock, importação, MT5, validação e série contínua |
| `b3-sinais` | planejada | aplicar regras de entrada, saída, stop e alvo e gravar sinais, sem enviar ordem |
| `b3-backtest` | planejada | resultado em pontos e em reais, com corretagem, emolumentos e slippage |
| `b3-risco` | planejada | perda máxima no dia, limite de contratos, janela de horário e margem |
| `b3-ponte` | planejada | gravar o sinal aprovado num arquivo que um robô do MT5 lê e executa, com você no controle |
| ações da B3 | depois | reaproveitar dados, risco e ponte para o mercado à vista |

## Contribuir

Issues e pull requests são bem-vindos. Antes de abrir um PR:

- rode os testes (`python3 -m unittest discover -s tests -v`);
- mantenha os scripts só com a biblioteca padrão;
- toda regra nova de mercado precisa de teste e de fonte (página ou ofício da B3).

## Avisos

**Não é recomendação de investimento.** É software que aplica regras e faz
contas. Ele não conhece a sua situação e não prevê o mercado.

**Futuros são alavancados.** No mini dólar, um movimento de 10 pontos vale
R$ 100 por contrato. Você pode perder mais do que a margem depositada.

**Não envia ordens.** Nenhuma skill deste pacote fala com a corretora para
operar. Quando existir a ponte para um robô, comece em conta de simulação.

**Confira as regras.** Horários e feriados mudam. Confirme no site da B3 e na sua
corretora antes de operar.

## Arquivos

```
b3-contratos/   SKILL.md, contratos.py, config.example.json
b3-dados/       SKILL.md, dados.py, mt5.py
tests/          testes unittest + exemplos de exportação do MT5 e do Profit
.claude-plugin/ manifesto do plugin para o Claude Code
```

Inspirado na estrutura do [trader-skill](https://github.com/Jakeschincariol/trader-skill).
MIT. Feito por [Carlosvpm](https://github.com/Carlosvpm).
