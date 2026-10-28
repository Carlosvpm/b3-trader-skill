#!/usr/bin/env python3
"""Ferramenta de desenvolvimento: fotografa uma janela do tmux em PNG.

  python3 tools/captura_tmux.py b3:principal docs/painel.png

Junta o conteúdo colorido de cada painel (capture-pane -e) nas posições certas e
desenha as bordas. Precisa do Pillow."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "b3-grafico"))
from tela import COR, Tela, de_ansi  # noqa: E402


def tmux(*args):
    return subprocess.run(["tmux"] + list(args), capture_output=True, text=True, check=True).stdout


def main(alvo, saida):
    w, h = [int(v) for v in tmux("display", "-p", "-t", alvo, "#{window_width} #{window_height}").split()]
    t = Tela(w, h + 1)
    panes = tmux("list-panes", "-t", alvo, "-F",
                 "#{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height} #{pane_active} #{pane_title}")
    for linha in panes.strip().splitlines():
        pid, x, y, pw, ph, ativo, titulo = (linha.split(" ", 6) + [""])[:7]
        x, y, pw, ph = int(x), int(y), int(pw), int(ph)
        conteudo = tmux("capture-pane", "-p", "-e", "-t", pid)
        de_ansi(conteudo, pw, ph, t, x, y)
        cor = COR["amarelo"] if ativo == "1" else COR["apagado"]
        if y > 0:
            for xx in range(max(0, x - 1), min(w, x + pw + 1)):
                t.put(xx, y - 1, "━", cor)
            t.texto(x + 1, y - 1, " %s " % titulo, COR["amarelo"] if ativo == "1" else COR["fraco"],
                    negrito=ativo == "1")
        if x > 0:
            for yy in range(max(0, y - 1), min(h, y + ph)):
                t.put(x - 1, yy, "┃", COR["apagado"])
    status = tmux("display", "-p", "-t", alvo, "#{session_name}:#{window_index} #{window_name}")
    t.fundo(h, 235)
    t.texto(0, h, " B3 ", COR["preto"], bg=COR["amarelo"], negrito=True)
    t.texto(5, h, status.strip(), COR["fraco"], bg=235)
    t.png(saida)
    print("gravado em %s" % saida)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
