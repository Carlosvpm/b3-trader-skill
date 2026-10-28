#!/usr/bin/env python3
"""b3-grafico: gráfico de velas colorido no terminal, como o da plataforma.

Velas, volume, médias, VWAP, Hi-Lo, as entradas e saídas de uma estratégia, o
stop e o alvo da posição aberta. Só lê arquivos: NÃO envia ordens.

Uso:
  python3 grafico.py b3/dados/WIN_5m.csv                       # desenha uma vez
  python3 grafico.py b3/dados/WIN_5m.csv -e rompimento_abertura --medias 9,21 --vwap
  python3 grafico.py b3/dados/WIN_1m_aovivo.csv --tf 5 --seguir 2   # ao vivo
  python3 grafico.py b3/dados/WIN_1m.csv --tf 5 --replay 0.3 --loop -e setup_9_1
  python3 grafico.py b3/dados/WIN_5m.csv --svg grafico.svg --largura 140 --altura 40
"""

import argparse
import datetime as dt
import json
import math
import os
import signal
import sys
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.abspath(os.environ.get("B3_SINAIS_DIR", os.path.join(_AQUI, "..", "b3-sinais"))))
from tela import COR, Tela, Terminal, preco_fmt, brl, tamanho_terminal, usar_cor  # noqa: E402
try:
    import sinais as S  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit("erro: não achei b3-sinais/sinais.py. Instale b3-contratos, b3-dados, b3-sinais e "
             "b3-grafico lado a lado.")
I, D, C = S.I, S.D, S.C

EIXO = 11          # largura da escala de preço à direita
VOL_LINHAS = 4
BLOCOS = " ▁▂▃▄▅▆▇█"
# meia linha de cima, meia de baixo: corpo (C), pavio (P), vazio (V)
VELA = {("C", "C"): "┃", ("P", "P"): "│", ("V", "C"): "╻", ("C", "V"): "╹",
        ("V", "P"): "╷", ("P", "V"): "╵", ("P", "C"): "╽", ("C", "P"): "╿", ("V", "V"): " "}


class Opcoes(object):
    def __init__(self, **kw):
        self.medias = kw.get("medias", [9, 21])
        self.vwap = kw.get("vwap", False)
        self.hilo = kw.get("hilo", 0)
        self.estrategia = kw.get("estrategia")
        self.params = kw.get("params", {})
        self.espaco = kw.get("espaco", True)
        self.titulo = kw.get("titulo")


CORES_MEDIA = [COR["amarelo"], COR["ciano"], COR["laranja"], COR["azul"]]


def _escala(lo, hi, linhas):
    if hi <= lo:
        hi = lo + 1
    pad = (hi - lo) * 0.04
    return lo - pad, hi + pad, (hi - lo + 2 * pad) / float(linhas)


def _linha(preco, topo, passo, linhas):
    r = int((topo - preco) / passo)
    return min(max(r, 0), linhas - 1)


def _passo_rotulo(lo, hi, linhas, tick):
    alvo = (hi - lo) / max(2, linhas // 3)
    base = 10 ** math.floor(math.log10(max(alvo, tick)))
    for m in (1, 2, 2.5, 5, 10):
        if base * m >= alvo:
            return max(base * m, tick)
    return base * 10


def desenhar(candles, largura, altura, op, resultado=None, agora=None):
    """Monta a Tela com o gráfico. `resultado` = retorno de sinais.simular (opcional)."""
    t = Tela(largura, altura)
    if not candles:
        t.texto(1, 1, "sem candles para mostrar", COR["fraco"])
        return t
    ativo = candles[0].ativo
    tick = C.ESPECIFICACOES[ativo]["tick"]
    cw = 2 if op.espaco else 1
    area_w = t.w - EIXO
    n_vis = max(1, area_w // cw)
    ini = max(0, len(candles) - n_vis)
    vis = candles[ini:]
    topo_graf, rod = 2, 3                      # cabeçalho+legenda em cima; eixo do tempo e status embaixo
    linhas = t.h - topo_graf - VOL_LINHAS - rod
    if linhas < 4:
        linhas, vol_l = t.h - topo_graf - rod, 0
    else:
        vol_l = VOL_LINHAS

    # séries sobrepostas (calculadas no histórico inteiro, mostradas no visível)
    fech = I.fechamentos(candles)
    series = []
    for k, n in enumerate(op.medias or []):
        series.append(("MME%d" % n, I.mme(fech, n)[ini:], CORES_MEDIA[k % len(CORES_MEDIA)]))
    if op.vwap:
        series.append(("VWAP", I.vwap(candles)[ini:], COR["magenta"]))
    if op.hilo:
        series.append(("HiLo%d" % op.hilo, I.hilo(candles, op.hilo)[0][ini:], COR["laranja"]))

    lo = min(c.minima for c in vis)
    hi = max(c.maxima for c in vis)
    for _, s, _ in series:
        vals = [v for v in s if v is not None]
        if vals:
            lo, hi = min(lo, min(vals)), max(hi, max(vals))
    aberta = resultado.get("aberta") if resultado else None
    if aberta:
        # stop e alvo ampliam a escala só até 35% além das velas; longe disso
        # ficam presos na borda, com seta
        folga = (hi - lo) * 0.35
        for v in (aberta.get("stop"), aberta.get("alvo"), aberta.get("preco")):
            if v is not None:
                lo, hi = min(lo, max(v, lo - folga)), max(hi, min(v, hi + folga))
    base, topo, passo = _escala(lo, hi, linhas)
    topo_p = topo

    def y_de(preco):
        return topo_graf + _linha(preco, topo_p, passo, linhas)

    x0 = area_w - len(vis) * cw          # alinha à direita, como na plataforma

    # grade e escala de preço
    rot = _passo_rotulo(base, topo, linhas, tick)
    v = math.ceil(base / rot) * rot
    while v <= topo:
        y = y_de(v)
        for x in range(0, area_w, 2):
            t.put(x, y, "┈", COR["grade"], so_vazio=True)
        t.texto(area_w + 1, y, preco_fmt(ativo, v).rjust(EIXO - 2), COR["fraco"])
        v += rot

    # separador de dias
    for k in range(1, len(vis)):
        if vis[k].data_hora.date() != vis[k - 1].data_hora.date():
            x = x0 + k * cw - 1
            for y in range(topo_graf, topo_graf + linhas + vol_l):
                t.put(x, y, "┆", COR["apagado"], so_vazio=False)

    # velas
    for k, c in enumerate(vis):
        x = x0 + k * cw
        sobe = c.fechamento >= c.abertura
        cor = COR["alta"] if sobe else COR["baixa"]
        cl, ch = min(c.abertura, c.fechamento), max(c.abertura, c.fechamento)
        for r in range(linhas):
            alto = topo - r * passo
            meio = alto - passo / 2.0
            baixo = alto - passo

            def estado(a, b):
                if cl <= a and ch >= b:
                    return "C"
                if c.minima <= a and c.maxima >= b:
                    return "P"
                return "V"
            par = (estado(alto, meio), estado(meio, baixo))
            if par == ("V", "V") and cl == ch and baixo <= cl <= alto:
                t.put(x, topo_graf + r, "━", cor)
                continue
            simbolo = VELA[par]
            if simbolo != " ":
                t.put(x, topo_graf + r, simbolo, cor)

    # médias e outras linhas
    for _, s, cor in series:
        for k in range(len(vis)):
            if s[k] is None:
                continue
            x = x0 + k * cw
            t.put(x, y_de(s[k]), "•", cor, so_vazio=True)
            if cw == 2 and k + 1 < len(vis) and s[k + 1] is not None and \
                    vis[k].data_hora.date() == vis[k + 1].data_hora.date():
                t.put(x + 1, y_de((s[k] + s[k + 1]) / 2.0), "·", cor, so_vazio=True)

    # operações da estratégia
    if resultado:
        idx = {c.data_hora.strftime("%Y-%m-%d %H:%M"): k for k, c in enumerate(vis)}
        for o in resultado.get("operacoes", []) + ([aberta] if aberta else []):
            k = idx.get(o["entrada"]["data_hora"])
            if k is not None:
                c = vis[k]
                if o["lado"] == "compra":
                    t.put(x0 + k * cw, min(y_de(c.minima) + 1, topo_graf + linhas - 1), "▲",
                          COR["alta"], negrito=True)
                else:
                    t.put(x0 + k * cw, max(y_de(c.maxima) - 1, topo_graf), "▼", COR["baixa"],
                          negrito=True)
            sai = o.get("saida")
            if sai:
                k = idx.get(sai["data_hora"])
                if k is not None:
                    cor = COR["alta"] if o["pontos"] > 0 else COR["baixa"]
                    xx = x0 + k * cw + (1 if cw == 2 else 0)
                    t.put(xx, y_de(sai["preco"]), "✕", cor, negrito=True)
        if aberta:
            for nome, valor, cor in (("entrada", aberta.get("preco"), COR["azul"]),
                                     ("stop", aberta.get("stop"), COR["baixa"]),
                                     ("alvo", aberta.get("alvo"), COR["alta"])):
                if valor is None:
                    continue
                y = y_de(valor)
                fora = "↑" if valor > topo else ("↓" if valor < base else " ")
                k = idx.get(aberta["entrada"]["data_hora"], 0)
                if fora == " ":
                    for x in range(x0 + k * cw, area_w):
                        t.put(x, y, "╌", cor, so_vazio=True)
                rotulo = nome[:1].upper() + fora + preco_fmt(ativo, valor)
                t.texto(area_w + 1, y, rotulo.rjust(EIXO - 1)[:EIXO - 1], COR["preto"], bg=cor, negrito=True)

    # último preço
    ult = vis[-1]
    sobe = ult.fechamento >= ult.abertura
    y = y_de(ult.fechamento)
    for x in range(x0 + (len(vis) - 1) * cw + 1, area_w):
        t.put(x, y, "┄", COR["alta_fraca"] if sobe else COR["baixa_fraca"], so_vazio=True)
    t.texto(area_w, y, (" " + preco_fmt(ativo, ult.fechamento)).ljust(EIXO), COR["preto"],
            bg=COR["alta"] if sobe else COR["baixa"], negrito=True)

    # volume
    if vol_l:
        vmax = max(c.volume for c in vis) or 1
        yv = topo_graf + linhas
        for k, c in enumerate(vis):
            x = x0 + k * cw
            altura_v = c.volume / vmax * vol_l * 8
            cor = COR["alta_fraca"] if c.fechamento >= c.abertura else COR["baixa_fraca"]
            for r in range(vol_l):
                resto = altura_v - (vol_l - 1 - r) * 8
                if resto <= 0:
                    continue
                t.put(x, yv + r, BLOCOS[min(8, int(math.ceil(resto)))], cor)
        t.texto(area_w + 1, yv, "vol", COR["fraco"])
        t.texto(area_w + 1, yv + 1, _curto(vmax).rjust(EIXO - 2), COR["apagado"])

    # eixo do tempo
    ye = t.h - 3
    ultimo_x = -99
    for k, c in enumerate(vis):
        x = x0 + k * cw
        novo_dia = k == 0 or c.data_hora.date() != vis[k - 1].data_hora.date()
        if novo_dia and x - ultimo_x >= 7:
            ultimo_x = t.texto(x, ye, c.data_hora.strftime("%d/%m"), COR["texto"], negrito=True) + 1
        elif x - ultimo_x >= 8 and c.data_hora.minute % 30 == 0:
            ultimo_x = t.texto(x, ye, c.data_hora.strftime("%H:%M"), COR["fraco"]) + 1

    _cabecalho(t, candles, vis, op, series, resultado)
    _rodape(t, ativo, resultado, agora or ult.data_hora)
    return t


def _curto(v):
    if v >= 1e6:
        return "%.1fM" % (v / 1e6)
    if v >= 1e3:
        return "%.0fk" % (v / 1e3)
    return "%d" % v


def _cabecalho(t, candles, vis, op, series, resultado):
    ult = vis[-1]
    ativo = ult.ativo
    tf = D.inferir_tf(candles)
    dia = [c for c in candles if c.data_hora.date() == ult.data_hora.date()]
    antes = [c for c in candles if c.data_hora.date() < ult.data_hora.date()]
    ref = antes[-1].fechamento if antes else dia[0].abertura
    var = (ult.fechamento / ref - 1) * 100 if ref else 0
    cor = COR["alta"] if var >= 0 else COR["baixa"]
    t.fundo(0, COR["fundo_cab"])
    x = t.texto(1, 0, " %s " % (op.titulo or ativo), COR["preto"], bg=COR["amarelo"], negrito=True)
    x = t.texto(x + 1, 0, "%s %dm" % (ult.contrato, tf), COR["branco"], bg=COR["fundo_cab"], negrito=True)
    x = t.texto(x + 2, 0, preco_fmt(ativo, ult.fechamento), cor, bg=COR["fundo_cab"], negrito=True)
    x = t.texto(x + 1, 0, "%s%s%%" % ("▲ +" if var >= 0 else "▼ ", brl(var, 2)), cor, bg=COR["fundo_cab"])
    x = t.texto(x + 2, 0, "máx %s  mín %s  vol %s" % (
        preco_fmt(ativo, max(c.maxima for c in dia)), preco_fmt(ativo, min(c.minima for c in dia)),
        _curto(sum(c.volume for c in dia))), COR["fraco"], bg=COR["fundo_cab"])
    direita = ult.data_hora.strftime("%d/%m/%Y %H:%M")
    if any(c.fonte == "mock" for c in candles[-50:]):
        t.texto(t.w - len(direita) - 15, 0, " FICTÍCIO ", COR["preto"], bg=COR["laranja"], negrito=True)
    t.texto(t.w - len(direita) - 2, 0, direita, COR["texto"], bg=COR["fundo_cab"])
    # legenda
    x = 1
    for nome, _, cor_s in series:
        x = t.texto(x, 1, "• ", cor_s)
        x = t.texto(x, 1, nome, COR["fraco"]) + 2
    if resultado:
        x = t.texto(x, 1, "▲", COR["alta"], negrito=True)
        x = t.texto(x, 1, " compra  ", COR["fraco"])
        x = t.texto(x, 1, "▼", COR["baixa"], negrito=True)
        x = t.texto(x, 1, " venda  ", COR["fraco"])
        x = t.texto(x, 1, "✕", COR["amarelo"], negrito=True)
        t.texto(x, 1, " saída", COR["fraco"])


def _rodape(t, ativo, resultado, agora):
    y = t.h - 2
    st = C.status_pregao(ativo, agora if isinstance(agora, dt.datetime) else dt.datetime.now())
    if st["aberto"]:
        x = t.texto(1, y, " ABERTO ", COR["preto"], bg=COR["alta"], negrito=True)
        x = t.texto(x + 1, y, "fecha %s" % st["fecha_em"][11:], COR["fraco"])
    else:
        x = t.texto(1, y, " FECHADO ", COR["branco"], bg=COR["fundo_baixa"], negrito=True)
        prox = dt.datetime.fromisoformat(st["proxima_abertura"])
        x = t.texto(x + 1, y, "abre %s" % prox.strftime("%d/%m %H:%M"), COR["fraco"])
    if not resultado:
        return
    r = resultado["resumo"]
    x = t.texto(x + 3, y, resultado.get("titulo", resultado["estrategia"]), COR["amarelo"], negrito=True)
    if r["operacoes"]:
        cor = COR["alta"] if r["pontos"] >= 0 else COR["baixa"]
        x = t.texto(x + 2, y, "%d ops  acerto %.0f%%  " % (r["operacoes"], r["acerto_pct"]), COR["fraco"])
        x = t.texto(x, y, "%+.1f pts" % r["pontos"], cor, negrito=True)
        x = t.texto(x, y, " bruto", COR["apagado"])
    a, pe = resultado.get("aberta"), resultado.get("pendente")
    y2 = t.h - 1
    if a:
        cor = COR["alta"] if a["pontos_abertos"] >= 0 else COR["baixa"]
        x = t.texto(1, y2, " %s " % ("COMPRADO" if a["lado"] == "compra" else "VENDIDO"), COR["preto"],
                    bg=COR["alta"] if a["lado"] == "compra" else COR["baixa"], negrito=True)
        x = t.texto(x + 1, y2, "em %s  stop %s  alvo %s  " % (
            preco_fmt(ativo, a["preco"]), preco_fmt(ativo, a["stop"]), preco_fmt(ativo, a["alvo"])), COR["texto"])
        t.texto(x, y2, "%+.1f pts" % a["pontos_abertos"], cor, negrito=True)
    elif pe:
        txt = ("%s stop em %s" % (pe["lado"], preco_fmt(ativo, pe["gatilho"]))) if pe["tipo"] == "stop" \
            else ("%s a mercado no próximo candle" % pe["lado"])
        x = t.texto(1, y2, " SINAL ", COR["preto"], bg=COR["amarelo"], negrito=True)
        t.texto(x + 1, y2, "%s  (%s)" % (txt, pe["motivo"]), COR["amarelo"])
    else:
        t.texto(1, y2, "sem posição", COR["apagado"])


# ------------------------------------------------------------------ dados

def carregar(arquivo, tf=None, dias=None, estado=True):
    cs = D.ler(arquivo)
    if estado and cs:
        caminho = os.path.join("b3", "estado", "%s_ultimo.json" % cs[0].ativo)
        if os.path.exists(caminho) and "aovivo" in os.path.basename(arquivo):
            try:
                with open(caminho, encoding="utf-8") as f:
                    e = json.load(f)
                fm = e.get("candle_formando")
                if fm:
                    quando = dt.datetime.strptime(fm["data_hora"], "%Y-%m-%d %H:%M")
                    if quando > cs[-1].data_hora:
                        cs.append(D.Candle(quando, cs[-1].ativo, cs[-1].contrato, fm["abertura"],
                                           fm["maxima"], fm["minima"], fm["fechamento"],
                                           fm.get("volume", 0), cs[-1].fonte))
            except (ValueError, KeyError, OSError):
                pass
    if dias and cs:
        # um pregão a mais, para a variação do dia ter o fechamento anterior
        datas = sorted({c.data_hora.date() for c in cs})[-(dias + 1):]
        cs = [c for c in cs if c.data_hora.date() >= datas[0]]
    if tf and cs and tf != D.inferir_tf(cs):
        cs = D.reamostrar(cs, tf)
    return cs


def gravar_replay(candles):
    if not candles:
        return
    caminho = os.path.join("b3", "estado", "%s_replay.json" % candles[0].ativo)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = "%s.%d.tmp" % (caminho, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ate": candles[-1].data_hora.strftime("%Y-%m-%d %H:%M"),
                       "ativo": candles[0].ativo}, f)
        os.replace(tmp, caminho)
    except OSError:
        pass


def quadro(candles, op, largura=None, altura=None):
    w, h = tamanho_terminal(largura, altura)
    res = S.simular(candles, op.estrategia, op.params) if op.estrategia else None
    return desenhar(candles, w, h, op, res)


def main(argv=None):
    p = argparse.ArgumentParser(description="Gráfico de velas no terminal (só leitura).")
    p.add_argument("arquivo")
    p.add_argument("--tf", type=int, help="reamostrar para este tempo gráfico (min)")
    p.add_argument("--estrategia", "-e", help="mostra entradas, saídas, stop e alvo")
    p.add_argument("--param", "-p", action="append", help="parâmetro da estratégia nome=valor")
    p.add_argument("--medias", default="9,21", help="MMEs, ex.: 9,21 (vazio para nenhuma)")
    p.add_argument("--vwap", action="store_true")
    p.add_argument("--hilo", type=int, default=0, help="período do Hi-Lo (0 = não mostra)")
    p.add_argument("--dias", type=int, default=0, help="só os últimos N pregões")
    p.add_argument("--compacto", action="store_true", help="velas sem espaço entre elas")
    p.add_argument("--largura", type=int)
    p.add_argument("--altura", type=int)
    p.add_argument("--titulo")
    p.add_argument("--seguir", type=float, help="recarrega o arquivo a cada N segundos")
    p.add_argument("--replay", type=float, help="reproduz o histórico, um candle a cada N segundos")
    p.add_argument("--inicio", help="replay: data/hora inicial AAAA-MM-DD[ HH:MM]")
    p.add_argument("--loop", action="store_true", help="replay: recomeça ao terminar")
    p.add_argument("--publicar", action="store_true",
                   help="replay: grava o horário em b3/estado/ATIVO_replay.json para o painel seguir")
    p.add_argument("--svg", help="grava o quadro em SVG em vez de mostrar")
    p.add_argument("--png", help="grava o quadro em PNG (precisa do Pillow)")
    p.add_argument("--sem-cor", action="store_true")
    a = p.parse_args(argv)

    op = Opcoes(medias=[int(x) for x in a.medias.split(",") if x.strip()],
                vwap=a.vwap, hilo=a.hilo, estrategia=a.estrategia,
                params=S._params_cli(a.param), espaco=not a.compacto, titulo=a.titulo)
    if a.estrategia:
        S.estrategia(a.estrategia)
    cor = usar_cor() and not a.sem_cor
    signal.signal(signal.SIGTERM, lambda *x: sys.exit(0))

    try:
        if a.replay:
            todos = carregar(a.arquivo, a.tf, a.dias or None, estado=False)
            if not todos:
                raise ValueError("arquivo vazio")
            if a.inicio:
                marco = dt.datetime.fromisoformat(a.inicio if " " in a.inicio else a.inicio + " 09:00")
                k0 = next((i for i, c in enumerate(todos) if c.data_hora >= marco), len(todos) - 1)
            else:
                # começa no início do antepenúltimo pregão
                datas = sorted({c.data_hora.date() for c in todos})
                marco = datas[-3] if len(datas) >= 3 else datas[0]
                k0 = max(1, next(i for i, c in enumerate(todos) if c.data_hora.date() == marco))
            with Terminal() as term:
                while True:
                    for k in range(k0, len(todos) + 1):
                        vis = todos[:k]
                        if a.publicar:
                            gravar_replay(vis)
                        term.desenhar(quadro(vis, op, a.largura, a.altura).ansi(cor))
                        time.sleep(a.replay)
                    if not a.loop:
                        while True:
                            time.sleep(1)
        elif a.seguir:
            with Terminal() as term:
                while True:
                    try:
                        cs = carregar(a.arquivo, a.tf, a.dias or 5)
                        term.desenhar(quadro(cs, op, a.largura, a.altura).ansi(cor))
                    except (ValueError, OSError) as e:
                        term.desenhar("aguardando dados: %s" % e)
                    time.sleep(a.seguir)
        else:
            cs = carregar(a.arquivo, a.tf, a.dias or None)
            t = quadro(cs, op, a.largura, a.altura)
            if a.png:
                t.png(a.png)
                print("gravado em %s" % a.png)
            elif a.svg:
                with open(a.svg, "w", encoding="utf-8") as f:
                    f.write(t.svg())
                print("gravado em %s" % a.svg)
            else:
                print(t.ansi(cor))
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError) as e:
        print("erro: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
