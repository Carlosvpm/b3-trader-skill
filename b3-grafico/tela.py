"""Uma grade de caracteres coloridos que vira ANSI (terminal) ou SVG (imagem).

Cores em 256 cores (xterm). Só biblioteca padrão."""

import os
import sys

# Paleta (índices xterm-256)
COR = {
    "alta": 41, "baixa": 203, "alta_fraca": 29, "baixa_fraca": 131,
    "texto": 252, "fraco": 244, "apagado": 238, "grade": 236,
    "amarelo": 221, "ciano": 81, "magenta": 177, "laranja": 215, "azul": 75,
    "branco": 255, "fundo_cab": 236, "fundo_alta": 22, "fundo_baixa": 52,
    "fundo_aviso": 94, "preto": 16,
}


BLOCOS_V = "▁▂▃▄▅▆▇█"


def _rgb(n):
    """Índice xterm-256 (ou '#rrggbb') -> '#rrggbb' (para SVG e PNG)."""
    if isinstance(n, str):
        return n
    base = [(0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0), (0, 0, 128), (128, 0, 128),
            (0, 128, 128), (192, 192, 192), (128, 128, 128), (255, 0, 0), (0, 255, 0),
            (255, 255, 0), (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
    if n < 16:
        r, g, b = base[n]
    elif n < 232:
        n -= 16
        niveis = [0, 95, 135, 175, 215, 255]
        r, g, b = niveis[n // 36], niveis[(n // 6) % 6], niveis[n % 6]
    else:
        v = 8 + (n - 232) * 10
        r = g = b = v
    return "#%02x%02x%02x" % (r, g, b)


def usar_cor():
    if os.environ.get("NO_COLOR"):
        return False
    return True


class Tela(object):
    def __init__(self, largura, altura):
        self.w, self.h = max(10, largura), max(5, altura)
        self.ch = [[" "] * self.w for _ in range(self.h)]
        self.fg = [[None] * self.w for _ in range(self.h)]
        self.bg = [[None] * self.w for _ in range(self.h)]
        self.neg = [[False] * self.w for _ in range(self.h)]

    def vazio(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h and self.ch[y][x] == " "

    def put(self, x, y, ch, fg=None, bg=None, negrito=False, so_vazio=False):
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        if so_vazio and self.ch[y][x] != " ":
            return
        self.ch[y][x] = ch
        self.fg[y][x] = fg
        if bg is not None:
            self.bg[y][x] = bg
        self.neg[y][x] = negrito

    def texto(self, x, y, s, fg=None, bg=None, negrito=False, so_vazio=False):
        for i, ch in enumerate(s):
            self.put(x + i, y, ch, fg, bg, negrito, so_vazio)
        return x + len(s)

    def fundo(self, y, bg, x0=0, x1=None):
        for x in range(x0, self.w if x1 is None else x1):
            self.bg[y][x] = bg

    def caixa(self, x0, y0, x1, y1, fg, titulo=None, fg_titulo=None):
        for x in range(x0 + 1, x1):
            self.put(x, y0, "─", fg)
            self.put(x, y1, "─", fg)
        for y in range(y0 + 1, y1):
            self.put(x0, y, "│", fg)
            self.put(x1, y, "│", fg)
        self.put(x0, y0, "╭", fg)
        self.put(x1, y0, "╮", fg)
        self.put(x0, y1, "╰", fg)
        self.put(x1, y1, "╯", fg)
        if titulo:
            self.texto(x0 + 2, y0, " %s " % titulo, fg_titulo or fg, negrito=True)

    # ---------------------------------------------------------- saída
    def ansi(self, cor=True):
        linhas = []
        for y in range(self.h):
            partes, estado = [], None
            for x in range(self.w):
                st = (self.fg[y][x], self.bg[y][x], self.neg[y][x]) if cor else None
                if st != estado:
                    if cor:
                        cods = ["0"]
                        if st[2]:
                            cods.append("1")
                        if st[0] is not None:
                            cods.append("38;5;%d" % st[0])
                        if st[1] is not None:
                            cods.append("48;5;%d" % st[1])
                        partes.append("\x1b[%sm" % ";".join(cods))
                    estado = st
                partes.append(self.ch[y][x])
            if cor:
                partes.append("\x1b[0m")
            linhas.append("".join(partes))
        return "\n".join(linhas)

    def svg(self, fundo="#121212", cw=8.4, chh=17.0, fonte=13):
        out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
               'viewBox="0 0 %d %d">' % (self.w * cw + 24, self.h * chh + 24,
                                         self.w * cw + 24, self.h * chh + 24),
               '<rect width="100%%" height="100%%" fill="%s" rx="8"/>' % fundo,
               '<g font-family="DejaVu Sans Mono, Menlo, Consolas, monospace" '
               'font-size="%d" transform="translate(12,12)">' % fonte]
        for y in range(self.h):
            for x in range(self.w):
                if self.bg[y][x] is not None:
                    out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>'
                               % (x * cw, y * chh, cw + 0.3, chh + 0.3, _rgb(self.bg[y][x])))
        for y in range(self.h):
            x = 0
            while x < self.w:
                ch = self.ch[y][x]
                if ch == " ":
                    x += 1
                    continue
                fg = _rgb(self.fg[y][x] if self.fg[y][x] is not None else COR["texto"])
                peso = ' font-weight="bold"' if self.neg[y][x] else ""
                esc = ch.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                out.append('<text x="%.1f" y="%.1f" fill="%s"%s>%s</text>'
                           % (x * cw, y * chh + chh * 0.78, fg, peso, esc))
                x += 1
        out.append("</g></svg>")
        return "\n".join(out)


    def png(self, caminho, fonte=15, fundo="#121212"):
        """Imagem PNG da tela. Opcional: precisa do Pillow (pip install Pillow)."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            raise ValueError("para PNG instale o Pillow (pip install Pillow), ou use --svg")
        fontes = {}
        for peso, nomes in ((False, ["DejaVuSansMono.ttf", "Menlo.ttc", "consola.ttf"]),
                            (True, ["DejaVuSansMono-Bold.ttf", "Menlo.ttc", "consolab.ttf"])):
            for nome in nomes:
                for pasta in ("", "/usr/share/fonts/truetype/dejavu/", "/Library/Fonts/",
                              "/System/Library/Fonts/", "C:/Windows/Fonts/"):
                    try:
                        fontes[peso] = ImageFont.truetype(pasta + nome, fonte)
                        break
                    except OSError:
                        continue
                if peso in fontes:
                    break
            fontes.setdefault(peso, ImageFont.load_default())
        reserva = None
        for nome in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf",
                     "seguisym.ttf"):
            try:
                reserva = ImageFont.truetype(nome, fonte)
                break
            except OSError:
                continue
        cw = int(round(fontes[False].getlength("M")))
        chh = int(round(fonte * 1.25))
        img = Image.new("RGB", (self.w * cw + 24, self.h * chh + 24), fundo)
        d = ImageDraw.Draw(img)
        for y in range(self.h):
            for x in range(self.w):
                if self.bg[y][x] is not None:
                    d.rectangle([12 + x * cw, 12 + y * chh, 12 + (x + 1) * cw, 12 + (y + 1) * chh],
                                fill=_rgb(self.bg[y][x]))
        for y in range(self.h):
            for x in range(self.w):
                ch = self.ch[y][x]
                if ch == " ":
                    continue
                f = fontes[self.neg[y][x]]
                if reserva is not None and ch in "✕▲▼":
                    f = reserva
                cor = _rgb(self.fg[y][x] if self.fg[y][x] is not None else COR["texto"])
                if ch in "│┃╽╿╻╹╷╵┆" or ch in BLOCOS_V:
                    self._traco(d, ch, 12 + x * cw, 12 + y * chh, cw, chh, cor)
                    continue
                d.text((12 + x * cw, 12 + y * chh + 1), ch, font=f, fill=cor)
        img.save(caminho)

    @staticmethod
    def _traco(d, ch, x, y, cw, chh, cor):
        """Desenha as peças verticais das velas sem falhas entre as linhas."""
        if ch in BLOCOS_V:
            frac = (BLOCOS_V.index(ch) + 1) / 8.0
            d.rectangle([x + 1, y + chh - int(round(chh * frac)), x + cw - 2, y + chh], fill=cor)
            return
        meio_x = x + cw // 2
        fino, grosso = max(1, cw // 7), max(3, cw // 2)
        topo, meio, base = y, y + chh // 2, y + chh
        partes = {"│": [("f", topo, base)], "┃": [("g", topo, base)],
                  "╽": [("f", topo, meio), ("g", meio, base)], "╿": [("g", topo, meio), ("f", meio, base)],
                  "╻": [("g", meio, base)], "╹": [("g", topo, meio)],
                  "╷": [("f", meio, base)], "╵": [("f", topo, meio)], "┆": [("p", topo, base)]}
        for tipo, a, b in partes[ch]:
            if tipo == "p":
                for yy in range(a, b, 4):
                    d.line([meio_x, yy, meio_x, yy + 1], fill=cor)
                continue
            larg = fino if tipo == "f" else grosso
            d.rectangle([meio_x - larg // 2, a, meio_x - larg // 2 + larg - 1, b], fill=cor)


def de_ansi(texto, largura, altura, tela=None, x0=0, y0=0):
    """Lê texto com cores ANSI (ex.: tmux capture-pane -e) para dentro de uma Tela."""
    import re
    t = tela or Tela(largura, altura)
    padrao = re.compile(r"\x1b\[([0-9;]*)m")
    for y, linha in enumerate(texto.split("\n")[:altura]):
        fg = bg = None
        neg = False
        x, pos = 0, 0
        for m in list(padrao.finditer(linha)) + [None]:
            fim = m.start() if m else len(linha)
            for ch in linha[pos:fim]:
                if x < largura and ch not in "\r":
                    t.put(x0 + x, y0 + y, ch, fg, bg, neg)
                    x += 1
            if m is None:
                break
            pos = m.end()
            cods = [int(c) if c else 0 for c in m.group(1).split(";")]
            i = 0
            while i < len(cods):
                c = cods[i]
                if c == 0:
                    fg = bg = None
                    neg = False
                elif c == 1:
                    neg = True
                elif c == 22:
                    neg = False
                elif c in (38, 48) and i + 2 < len(cods) and cods[i + 1] == 5:
                    if c == 38:
                        fg = cods[i + 2]
                    else:
                        bg = cods[i + 2]
                    i += 2
                elif c in (38, 48) and i + 4 < len(cods) and cods[i + 1] == 2:
                    cor = "#%02x%02x%02x" % tuple(cods[i + 2:i + 5])
                    if c == 38:
                        fg = cor
                    else:
                        bg = cor
                    i += 4
                elif 30 <= c <= 37:
                    fg = c - 30
                elif 90 <= c <= 97:
                    fg = c - 90 + 8
                elif 40 <= c <= 47:
                    bg = c - 40
                elif 100 <= c <= 107:
                    bg = c - 100 + 8
                elif c == 39:
                    fg = None
                elif c == 49:
                    bg = None
                i += 1
    return t


class Terminal(object):
    """Tela cheia sem piscar: buffer alternativo, cursor escondido, redesenho no lugar."""

    def __enter__(self):
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        sys.stdout.flush()
        return self

    def desenhar(self, texto):
        sys.stdout.write("\x1b[H" + texto.replace("\n", "\x1b[K\n") + "\x1b[K\x1b[J")
        sys.stdout.flush()

    def __exit__(self, *a):
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
        return False


def tamanho_terminal(largura=None, altura=None):
    import shutil
    t = shutil.get_terminal_size((120, 36))
    return largura or t.columns, altura or t.lines


def brl(v, casas=2):
    s = ("{:,.%df}" % casas).format(abs(v)).replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + s


def preco_fmt(ativo, v):
    """WIN: 130.125 | WDO: 5.412,5"""
    if v is None:
        return "-"
    if ativo == "WIN":
        return brl(round(v), 0)
    return brl(v, 1)
