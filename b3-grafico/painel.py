#!/usr/bin/env python3
"""b3-grafico / painel.py: coluna de status para o tmux.

Mostra, para cada ativo: preço, variação, máxima e mínima do dia, se o pregão
está aberto, o contrato e a rolagem; depois a situação de cada estratégia
(posição, ordem armada, resultado do dia) e os últimos eventos.

Uso:
  python3 painel.py                         # WIN e WDO, sinais em 5 min, atualiza a cada 2 s
  python3 painel.py --ativos WIN --tf 15 --estrategias rompimento_abertura,vwap
  python3 painel.py --replay                # acompanha o replay dos gráficos
  python3 painel.py --uma-vez               # imprime uma vez e sai
"""

import argparse
import datetime as dt
import json
import os
import signal
import sys
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
import grafico as G  # noqa: E402
from tela import COR, Tela, Terminal, brl, preco_fmt, tamanho_terminal, usar_cor  # noqa: E402

S, D, C = G.S, G.D, G.C

CURTO = {"rompimento_abertura": "ORB", "setup_9_1": "9.1", "cruzamento_medias": "Médias",
         "vwap": "VWAP", "ifr2": "IFR2", "hilo": "Hi-Lo"}


def arquivo_do_ativo(ativo, pasta=D.PASTA_PADRAO):
    for nome in ("%s_1m_aovivo.csv", "%s_1m.csv", "%s_5m.csv"):
        p = os.path.join(pasta, nome % ativo)
        if os.path.exists(p):
            return p
    return None


def limite_replay(ativo):
    p = os.path.join("b3", "estado", "%s_replay.json" % ativo)
    try:
        with open(p, encoding="utf-8") as f:
            return dt.datetime.strptime(json.load(f)["ate"], "%Y-%m-%d %H:%M")
    except (OSError, ValueError, KeyError):
        return None


def coletar(ativos, tf, estrategias, dias, replay=False, agora=None):
    """Junta tudo o que o painel mostra. Separado do desenho para testar."""
    info = {"ativos": [], "eventos": [], "agora": agora}
    for ativo in ativos:
        arq = arquivo_do_ativo(ativo)
        item = {"ativo": ativo, "arquivo": arq, "estrategias": {}}
        info["ativos"].append(item)
        if not arq:
            item["erro"] = "sem dados em b3/dados/"
            continue
        try:
            um = G.carregar(arq, None, dias)
        except (ValueError, OSError) as e:
            item["erro"] = str(e)
            continue
        if replay:
            ate = limite_replay(ativo)
            if ate:
                tf_arq = D.inferir_tf(um)
                um = [c for c in um if c.data_hora + dt.timedelta(minutes=tf_arq) <= ate + dt.timedelta(minutes=tf)]
        if not um:
            item["erro"] = "aguardando candles"
            continue
        cs = D.reamostrar(um, tf) if tf != D.inferir_tf(um) else um
        ult = cs[-1]
        hoje = [c for c in cs if c.data_hora.date() == ult.data_hora.date()]
        antes = [c for c in cs if c.data_hora.date() < ult.data_hora.date()]
        ref = antes[-1].fechamento if antes else hoje[0].abertura
        momento = info["agora"] or (ult.data_hora + dt.timedelta(minutes=tf) if replay else
                                    dt.datetime.now(C.BRT).replace(tzinfo=None))
        info["agora"] = info["agora"] or momento
        v = C.vigente(ativo, momento.date())
        item.update({
            "contrato": ult.contrato, "ultimo": ult.fechamento, "ref": ref,
            "variacao": (ult.fechamento / ref - 1) * 100 if ref else 0.0,
            "maxima": max(c.maxima for c in hoje), "minima": min(c.minima for c in hoje),
            "volume": sum(c.volume for c in hoje), "hora": ult.data_hora,
            "ficticio": any(c.fonte == "mock" for c in cs[-20:]),
            "pregao": C.status_pregao(ativo, momento), "vigente": v,
        })
        dia = ult.data_hora.strftime("%Y-%m-%d")
        for nome in estrategias:
            r = S.simular(cs, nome)
            do_dia = [o for o in r["operacoes"] if o["entrada"]["data_hora"].startswith(dia)]
            pts = sum(o["pontos"] for o in do_dia) + (r["aberta"]["pontos_abertos"] if r["aberta"] else 0)
            item["estrategias"][nome] = {"aberta": r["aberta"], "pendente": r["pendente"],
                                         "pontos_dia": pts, "ops_dia": len(do_dia) + (1 if r["aberta"] else 0)}
            for o in do_dia + ([r["aberta"]] if r["aberta"] else []):
                info["eventos"].append((o["entrada"]["data_hora"], ativo, nome, o["lado"], "entrada",
                                        o["entrada"]["preco"], None))
                if o.get("saida"):
                    info["eventos"].append((o["saida"]["data_hora"], ativo, nome, o["lado"], "saida",
                                            o["saida"]["preco"], o["pontos"]))
    info["eventos"].sort(reverse=True)
    return info


def _dur(minutos):
    h, m = divmod(int(minutos), 60)
    return ("%dh%02d" % (h, m)) if h else ("%d min" % m)


def desenhar(info, largura, altura, tf, estrategias):
    t = Tela(largura, altura)
    w = t.w - 1
    agora = info["agora"] or dt.datetime.now()
    dias_sem = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    t.fundo(0, COR["fundo_cab"])
    t.texto(1, 0, " B3 ", COR["preto"], bg=COR["amarelo"], negrito=True)
    t.texto(6, 0, "%s %s" % (dias_sem[agora.weekday()], agora.strftime("%d/%m %H:%M:%S")),
            COR["branco"], bg=COR["fundo_cab"], negrito=True)
    if any(a.get("ficticio") for a in info["ativos"]):
        t.texto(w - 9, 0, " FICTÍCIO ", COR["preto"], bg=COR["laranja"], negrito=True)
    y = 2
    for a in info["ativos"]:
        if y + 6 >= t.h:
            break
        t.caixa(0, y, w, y + 6, COR["apagado"], "%s · %s" % (a["ativo"], a.get("contrato", "-")),
                COR["amarelo"])
        if a.get("erro"):
            t.texto(2, y + 2, a["erro"], COR["fraco"])
            y += 8
            continue
        sobe = a["variacao"] >= 0
        cor = COR["alta"] if sobe else COR["baixa"]
        x = t.texto(2, y + 1, preco_fmt(a["ativo"], a["ultimo"]), cor, negrito=True)
        t.texto(x + 2, y + 1, "%s%s%%" % ("▲ +" if sobe else "▼ ", brl(a["variacao"], 2)), cor)
        t.texto(2, y + 2, "máx %s  mín %s" % (preco_fmt(a["ativo"], a["maxima"]),
                                              preco_fmt(a["ativo"], a["minima"])), COR["fraco"])
        st = a["pregao"]
        if st["aberto"]:
            x = t.texto(2, y + 3, "● ABERTO", COR["alta"], negrito=True)
            t.texto(x + 1, y + 3, "fecha em %s" % _dur(st["minutos_para_fechar"]), COR["fraco"])
        else:
            x = t.texto(2, y + 3, "● FECHADO", COR["baixa"], negrito=True)
            prox = dt.datetime.fromisoformat(st["proxima_abertura"])
            t.texto(x + 1, y + 3, ("abre %s" % prox.strftime("%d/%m %H:%M"))[:w - x - 2], COR["fraco"])
        v = a["vigente"]
        venc = dt.date.fromisoformat(v["vigente"]["ultimo_dia_negociacao"]).strftime("%d/%m")
        rolar = dt.date.fromisoformat(v["vigente"]["rolar_em"]).strftime("%d/%m")
        if v["rolar_agora"]:
            t.texto(2, y + 4, ("ROLAR → %s" % v["contrato_liquido"])[:w - 3], COR["preto"],
                    bg=COR["amarelo"], negrito=True)
        else:
            t.texto(2, y + 4, ("último dia %s · rolar %s" % (venc, rolar))[:w - 3], COR["fraco"])
        t.texto(2, y + 5, ("candle %s · vol %s" % (a["hora"].strftime("%H:%M"), G._curto(a["volume"])))[:w - 3],
                COR["apagado"])
        y += 8

    # tabela de estratégias
    ativos_ok = [a for a in info["ativos"] if not a.get("erro")]
    if ativos_ok and y + 4 < t.h:
        altura_tab = min(len(estrategias) + 3, t.h - y - 1)
        t.caixa(0, y, w, y + altura_tab, COR["apagado"], "Estratégias %dm" % tf, COR["amarelo"])
        col = max(11, (w - 10) // max(1, len(ativos_ok)))
        x = 9
        for a in ativos_ok:
            t.texto(x, y + 1, a["ativo"].rjust(col - 1), COR["fraco"], negrito=True)
            x += col
        for k, nome in enumerate(estrategias):
            yy = y + 2 + k
            if yy >= y + altura_tab:
                break
            t.texto(2, yy, CURTO.get(nome, nome)[:7], COR["texto"])
            x = 9
            for a in ativos_ok:
                e = a["estrategias"].get(nome, {})
                ab, pe = e.get("aberta"), e.get("pendente")
                if ab:
                    seta = "▲" if ab["lado"] == "compra" else "▼"
                    txt, cor = "%s%+.0f" % (seta, ab["pontos_abertos"]) if a["ativo"] == "WIN" else \
                        "%s%+.1f" % (seta, ab["pontos_abertos"]), (COR["alta"] if ab["pontos_abertos"] >= 0 else COR["baixa"])
                    neg = True
                elif pe:
                    txt, cor, neg = ("armada " if pe["tipo"] == "stop" else "sinal ") + \
                        ("▲" if pe["lado"] == "compra" else "▼"), COR["amarelo"], True
                elif e.get("ops_dia"):
                    p = e["pontos_dia"]
                    txt = ("%+.0f" % p) if a["ativo"] == "WIN" else ("%+.1f" % p)
                    cor, neg = (COR["alta_fraca"] if p >= 0 else COR["baixa_fraca"]), False
                else:
                    txt, cor, neg = "—", COR["apagado"], False
                t.texto(x, yy, txt.rjust(col - 1)[-(col - 1):], cor, negrito=neg)
                x += col
        y += altura_tab + 1

    # eventos
    if info["eventos"] and y + 3 < t.h:
        altura_ev = t.h - y - 1
        t.caixa(0, y, w, y + altura_ev, COR["apagado"], "Eventos do dia", COR["amarelo"])
        for k, ev in enumerate(info["eventos"][:altura_ev - 1]):
            quando, ativo, nome, lado, tipo, preco, pts = ev
            yy = y + 1 + k
            x = t.texto(2, yy, quando[11:], COR["fraco"])
            x = t.texto(x + 1, yy, ativo, COR["texto"])
            x = t.texto(x + 1, yy, CURTO.get(nome, nome)[:6].ljust(6), COR["amarelo"])
            if tipo == "entrada":
                seta = "▲" if lado == "compra" else "▼"
                t.texto(x + 1, yy, ("%s %s" % (seta, preco_fmt(ativo, preco)))[:w - x - 2],
                        COR["alta"] if lado == "compra" else COR["baixa"], negrito=True)
            else:
                t.texto(x + 1, yy, ("✕ %s %+g" % (preco_fmt(ativo, preco), round(pts, 1)))[:w - x - 2],
                        COR["alta"] if pts > 0 else COR["baixa"])
    return t


def main(argv=None):
    p = argparse.ArgumentParser(description="Painel de status (para a coluna do tmux).")
    p.add_argument("--ativos", default="WIN,WDO")
    p.add_argument("--tf", type=int, default=5)
    p.add_argument("--estrategias", default=",".join(S.ESTRATEGIAS))
    p.add_argument("--dias", type=int, default=3)
    p.add_argument("--segundos", type=float, default=2.0)
    p.add_argument("--replay", action="store_true", help="segue o horário do replay dos gráficos")
    p.add_argument("--uma-vez", action="store_true")
    p.add_argument("--largura", type=int)
    p.add_argument("--altura", type=int)
    p.add_argument("--png")
    p.add_argument("--sem-cor", action="store_true")
    a = p.parse_args(argv)
    ativos = [x.strip().upper() for x in a.ativos.split(",") if x.strip()]
    ests = [x.strip() for x in a.estrategias.split(",") if x.strip()]
    for e in ests:
        S.estrategia(e)
    cor = usar_cor() and not a.sem_cor
    signal.signal(signal.SIGTERM, lambda *x: sys.exit(0))

    def quadro():
        w, h = tamanho_terminal(a.largura, a.altura)
        return desenhar(coletar(ativos, a.tf, ests, a.dias, a.replay), w, h, a.tf, ests)

    try:
        if a.uma_vez or a.png:
            t = quadro()
            if a.png:
                t.png(a.png)
                print("gravado em %s" % a.png)
            else:
                print(t.ansi(cor))
            return 0
        with Terminal() as term:
            while True:
                term.desenhar(quadro().ansi(cor))
                time.sleep(a.segundos)
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError) as e:
        print("erro: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
