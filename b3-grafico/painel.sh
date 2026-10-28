#!/usr/bin/env bash
# b3-grafico / painel.sh: monta o painel no tmux.
#
#   ┌──────────── WIN 5m ────────────┬── B3 ──────┐
#   │  velas, médias, sinais         │ preços     │
#   ├──────────── WDO 5m ────────────┤ pregão     │
#   │  velas, médias, sinais         │ estratégias│
#   └────────────────────────────────┴ eventos ───┘
#   janela 2: 1 minuto  ·  janela 3: comparação das estratégias
#
# Uso (rode na pasta do projeto, onde fica b3/):
#   painel.sh demo                       dados fictícios em replay (gera se faltar)
#   painel.sh aovivo                     lê b3/dados/*_1m_aovivo.csv (mt5.py ao-vivo)
#   painel.sh arquivo                    redesenha b3/dados/*_1m.csv a cada 2 s
#
# Opções:
#   --tf 5                    tempo gráfico dos gráficos principais
#   --estrategia NOME         estratégia desenhada nos gráficos (padrão: rompimento_abertura)
#   --ativos WIN,WDO          um ou dois ativos
#   --velocidade 0.4          demo: segundos por candle
#   --sessao b3               nome da sessão do tmux
#   --novo                    fecha a sessão com esse nome e cria de novo
#   --sem-anexar              cria a sessão e não entra nela
#
# Dentro do tmux: Ctrl+b e depois 1, 2, 3 troca de janela; Ctrl+b d sai sem fechar;
# "tmux kill-session -t b3" fecha tudo. O mouse funciona para trocar de painel.

set -euo pipefail

# o tmux precisa de UTF-8 para as velas e os acentos
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
  *UTF-8*|*utf8*|*UTF8*|*utf-8*) ;;
  *) export LC_ALL=C.UTF-8 ;;
esac

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/.." && pwd)"
PY="${PYTHON:-python3}"
MODO="${1:-demo}"
[ $# -gt 0 ] && shift

TF=5
EST=rompimento_abertura
ATIVOS=WIN,WDO
VEL=0.4
SESSAO=b3
NOVO=0
ANEXAR=1

while [ $# -gt 0 ]; do
  case "$1" in
    --tf) TF="$2"; shift 2 ;;
    --estrategia|-e) EST="$2"; shift 2 ;;
    --ativos) ATIVOS="$2"; shift 2 ;;
    --velocidade) VEL="$2"; shift 2 ;;
    --sessao) SESSAO="$2"; shift 2 ;;
    --novo) NOVO=1; shift ;;
    --sem-anexar) ANEXAR=0; shift ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

case "$MODO" in demo|aovivo|arquivo) ;; *) echo "modo deve ser demo, aovivo ou arquivo" >&2; exit 2 ;; esac
command -v tmux >/dev/null || { echo "instale o tmux (apt install tmux, brew install tmux; no Windows use o WSL)" >&2; exit 1; }

IFS=',' read -r -a LISTA <<< "$ATIVOS"
GRAF="$RAIZ/b3-grafico/grafico.py"
PAINEL="$RAIZ/b3-grafico/painel.py"
DADOS="$RAIZ/b3-dados/dados.py"
SINAIS="$RAIZ/b3-sinais/sinais.py"

if tmux has-session -t "$SESSAO" 2>/dev/null; then
  if [ "$NOVO" = 1 ]; then
    tmux kill-session -t "$SESSAO"
  else
    echo "sessão $SESSAO já existe: entrando (use --novo para recriar)"
    [ "$ANEXAR" = 1 ] && exec tmux attach -t "$SESSAO"
    exit 0
  fi
fi

arquivo_1m() {
  local a="$1"
  if [ "$MODO" = aovivo ]; then echo "b3/dados/${a}_1m_aovivo.csv"; else echo "b3/dados/${a}_1m.csv"; fi
}

if [ "$MODO" = demo ]; then
  for a in "${LISTA[@]}"; do
    if [ ! -f "b3/dados/${a}_1m.csv" ]; then
      echo "gerando dados fictícios de $a..."
      "$PY" "$DADOS" mock "$a" --tfs 1,5,15,30,60 >/dev/null
    fi
  done
fi

cmd_grafico() {   # ativo tf estrategia(opcional)
  local a="$1" tf="$2" est="${3:-}"
  local arq; arq="$(arquivo_1m "$a")"
  local extra="--medias 9,21 --vwap"
  [ -n "$est" ] && extra="$extra -e $est"
  case "$MODO" in
    demo)    local pub=""; [ -n "$est" ] && pub="--publicar"
             echo "$PY '$GRAF' '$arq' --tf $tf $extra --titulo $a --replay $VEL --loop --dias 6 $pub" ;;
    aovivo)  echo "$PY '$GRAF' '$arq' --tf $tf $extra --titulo $a --seguir 1" ;;
    arquivo) echo "$PY '$GRAF' '$arq' --tf $tf $extra --titulo $a --seguir 2 --dias 5" ;;
  esac
}

cmd_painel() {
  local extra=""
  [ "$MODO" = demo ] && extra="--replay --segundos 1"
  echo "$PY '$PAINEL' --ativos $ATIVOS --tf $TF $extra"
}

cmd_comparar() {
  local partes=""
  for a in "${LISTA[@]}"; do
    partes="$partes $PY '$SINAIS' comparar '$(arquivo_1m "$a")' --tf $TF; echo;"
  done
  echo "while true; do clear; echo; $partes echo '  atualiza a cada 60 s  ·  resultado BRUTO, sem custos'; sleep 60; done"
}

DIR="$(pwd)"
tmux -2 -u new-session -d -s "$SESSAO" -n principal -x "${B3_COLUNAS:-$(tput cols 2>/dev/null || echo 200)}" \
  -y "${B3_LINHAS:-$(tput lines 2>/dev/null || echo 50)}" -c "$DIR"

# aparência
tmux set -t "$SESSAO" -g default-terminal "tmux-256color" 2>/dev/null || true
tmux set -t "$SESSAO" mouse on
tmux set -t "$SESSAO" status-style "bg=colour235,fg=colour250"
tmux set -t "$SESSAO" status-left "#[bg=colour221,fg=colour16,bold] B3 #[default] "
tmux set -t "$SESSAO" status-left-length 20
tmux set -t "$SESSAO" status-right "#[fg=colour244]modo $MODO · ${TF}m · $EST  #[fg=colour255,bold]%H:%M:%S "
tmux set -t "$SESSAO" status-right-length 80
tmux set -t "$SESSAO" status-interval 1
tmux set -t "$SESSAO" window-status-current-format "#[bg=colour238,fg=colour255,bold] #I #W "
tmux set -t "$SESSAO" window-status-format "#[fg=colour244] #I #W "
tmux set -t "$SESSAO" pane-border-status top
tmux set -t "$SESSAO" pane-border-format "#{?pane_active,#[fg=colour221 bold],#[fg=colour244]} #{pane_title} "
tmux set -t "$SESSAO" pane-border-style "fg=colour238"
tmux set -t "$SESSAO" pane-active-border-style "fg=colour221"
tmux set -t "$SESSAO" pane-border-lines heavy 2>/dev/null || true

# janela 1: gráficos principais + painel
P0="$(tmux display -p -t "$SESSAO:principal" '#{pane_id}')"
tmux send-keys -t "$P0" "$(cmd_grafico "${LISTA[0]}" "$TF" "$EST")" C-m
tmux select-pane -t "$P0" -T "${LISTA[0]} ${TF}m · $EST"
PD="$(tmux split-window -h -l 46 -t "$P0" -c "$DIR" -P -F '#{pane_id}')"
tmux send-keys -t "$PD" "$(cmd_painel)" C-m
tmux select-pane -t "$PD" -T "painel"
if [ "${#LISTA[@]}" -gt 1 ]; then
  P1="$(tmux split-window -v -t "$P0" -c "$DIR" -P -F '#{pane_id}')"
  tmux send-keys -t "$P1" "$(cmd_grafico "${LISTA[1]}" "$TF" "$EST")" C-m
  tmux select-pane -t "$P1" -T "${LISTA[1]} ${TF}m · $EST"
fi
tmux select-pane -t "$P0"

# janela 2: 1 minuto
tmux new-window -t "$SESSAO" -n "1min" -c "$DIR"
Q0="$(tmux display -p -t "$SESSAO:1min" '#{pane_id}')"
tmux send-keys -t "$Q0" "$(cmd_grafico "${LISTA[0]}" 1)" C-m
tmux select-pane -t "$Q0" -T "${LISTA[0]} 1m"
if [ "${#LISTA[@]}" -gt 1 ]; then
  Q1="$(tmux split-window -v -t "$Q0" -c "$DIR" -P -F '#{pane_id}')"
  tmux send-keys -t "$Q1" "$(cmd_grafico "${LISTA[1]}" 1)" C-m
  tmux select-pane -t "$Q1" -T "${LISTA[1]} 1m"
fi

# janela 3: comparação das estratégias
tmux new-window -t "$SESSAO" -n "estrategias" -c "$DIR"
tmux send-keys -t "$SESSAO:estrategias" "$(cmd_comparar)" C-m
tmux select-pane -t "$SESSAO:estrategias" -T "comparação ${TF}m"

tmux select-window -t "$SESSAO:principal"
if [ "$ANEXAR" = 1 ]; then
  if [ -n "${TMUX:-}" ]; then exec tmux switch-client -t "$SESSAO"; else exec tmux attach -t "$SESSAO"; fi
fi
echo "sessão $SESSAO criada (tmux attach -t $SESSAO)"
