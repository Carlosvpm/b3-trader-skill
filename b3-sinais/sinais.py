#!/usr/bin/env python3
"""b3-sinais: aplica estratégias nos candles de b3-dados e grava os sinais e as
operações simuladas. NÃO envia ordens.

Só biblioteca padrão. Python 3.8+.

Uso:
  python3 sinais.py listar
  python3 sinais.py rodar b3/dados/WIN_5m.csv --estrategia rompimento_abertura
  python3 sinais.py rodar b3/dados/WIN_5m.csv --estrategia setup_9_1 --param validade=3
  python3 sinais.py comparar b3/dados/WIN_5m.csv
  python3 sinais.py agora b3/dados/WIN_1m_aovivo.csv --tf 5 --estrategia vwap

Regras da simulação (iguais para todas as estratégias):
  - o sinal é calculado no FECHAMENTO do candle, só com dados até ali;
  - ordem a mercado entra na ABERTURA do candle seguinte;
  - ordem stop entra quando o preço toca o gatilho (no gap, pelo preço de abertura);
  - se stop e alvo cabem no mesmo candle, conta o stop (pessimista);
  - uma posição por vez, sem pirâmide;
  - day trade: não entra depois de `fim_entradas`, zera em `zerar_em` ou no
    último candle do dia, e ordens pendentes não passam para o dia seguinte;
  - resultado BRUTO: sem corretagem, emolumentos nem slippage (isso é a b3-backtest).
"""

import argparse
import datetime as dt
import json
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.abspath(os.environ.get("B3_DADOS_DIR", os.path.join(_AQUI, "..", "b3-dados"))))
import indicadores as I  # noqa: E402
try:
    import dados as D  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit("erro: não achei b3-dados/dados.py. Instale b3-contratos, b3-dados e b3-sinais lado a lado.")
C = D.C

PASTA_SINAIS = os.path.join("b3", "sinais")

PARAMS_GERAIS = {
    "contratos": 1,
    "fim_entradas": "17:30",
    "zerar_em": "17:55",
    "max_operacoes_dia": 0,      # 0 = sem limite
}


# ------------------------------------------------------------------ estratégias

class Estrategia(object):
    nome = ""
    titulo = ""
    resumo = ""
    fonte = ""
    params = {}

    def preparar(self, candles, p):
        return {}

    def sinal(self, i, ctx):
        return {}


class Contexto(object):
    def __init__(self, candles, ind, p, tick):
        self.candles, self.ind, self.p, self.tick = candles, ind, p, tick
        self.pos = None
        self.dia_inicio = 0
        self.ops_hoje = 0

    def mesmo_dia(self, i, j):
        return j >= 0 and self.candles[i].data_hora.date() == self.candles[j].data_hora.date()

    def minima(self, i, n):
        ini = max(self.dia_inicio, i - n + 1)
        return min(c.minima for c in self.candles[ini:i + 1])

    def maxima(self, i, n):
        ini = max(self.dia_inicio, i - n + 1)
        return max(c.maxima for c in self.candles[ini:i + 1])


def _hora(t):
    h, m = t.split(":")
    return dt.time(int(h), int(m))


class RompimentoAbertura(Estrategia):
    nome = "rompimento_abertura"
    titulo = "Rompimento da faixa de abertura (ORB)"
    resumo = ("Marca a máxima e a mínima dos primeiros `minutos` do pregão. Compra quando um "
              "candle fecha acima da máxima, vende quando fecha abaixo da mínima. Stop do outro "
              "lado da faixa, alvo de `rr` vezes o risco. Uma operação por dia.")
    fonte = "https://doc.stocksharp.com/pt/api-examples/0459_Opening_Range_Breakout"
    params = {"minutos": 15, "rr": 2.0, "buffer_ticks": 1}

    def preparar(self, candles, p):
        alta, baixa, pronta = [None] * len(candles), [None] * len(candles), [False] * len(candles)
        dia, fim, a, b = None, None, None, None
        for i, c in enumerate(candles):
            d = c.data_hora.date()
            if d != dia:
                dia = d
                h = C.horario(c.ativo, d)
                abre = dt.datetime.combine(d, h[0] if h else c.data_hora.time())
                fim = abre + dt.timedelta(minutes=int(p["minutos"]))
                a, b = c.maxima, c.minima
            elif c.data_hora < fim:
                a, b = max(a, c.maxima), min(b, c.minima)
            alta[i], baixa[i] = a, b
            # só dispara em candles que começam depois de a faixa fechar
            pronta[i] = c.data_hora >= fim
        return {"alta": alta, "baixa": baixa, "pronta": pronta}

    def sinal(self, i, ctx):
        if ctx.pos or ctx.ops_hoje or not ctx.ind["pronta"][i]:
            return {}
        c, buf = ctx.candles[i], ctx.p["buffer_ticks"] * ctx.tick
        a, b = ctx.ind["alta"][i], ctx.ind["baixa"][i]
        if c.fechamento > a + buf:
            return {"entrada": {"lado": "compra", "tipo": "mercado", "stop": b,
                                "rr": ctx.p["rr"], "motivo": "fechou acima da faixa %s" % D._num(a)}}
        if c.fechamento < b - buf:
            return {"entrada": {"lado": "venda", "tipo": "mercado", "stop": a,
                                "rr": ctx.p["rr"], "motivo": "fechou abaixo da faixa %s" % D._num(b)}}
        return {}


class Setup91(Estrategia):
    nome = "setup_9_1"
    titulo = "Setup 9.1 (Larry Williams)"
    resumo = ("Quando a média exponencial de 9 vira para cima, arma uma compra no rompimento da "
              "máxima do candle que virou, com stop abaixo da mínima dele. Vira para baixo: o "
              "contrário. Sai quando a média vira contra a posição.")
    fonte = "https://www.awaketrader.com/pt/educacao/setup-9-1-9-2-9-3-larry-williams"
    params = {"periodo": 9, "validade": 2, "vender": True}

    def preparar(self, candles, p):
        return {"mme": I.mme(I.fechamentos(candles), int(p["periodo"]))}

    def sinal(self, i, ctx):
        m = ctx.ind["mme"]
        if i < 2 or m[i - 2] is None:
            return {}
        cima = m[i] > m[i - 1] and m[i - 1] <= m[i - 2]
        baixo = m[i] < m[i - 1] and m[i - 1] >= m[i - 2]
        c, t, s = ctx.candles[i], ctx.tick, {}
        if ctx.pos and ((ctx.pos["lado"] == "compra" and baixo) or
                        (ctx.pos["lado"] == "venda" and cima)):
            s["sair"] = "MME%d virou contra" % ctx.p["periodo"]
        if cima and (not ctx.pos or s.get("sair")):
            s["entrada"] = {"lado": "compra", "tipo": "stop", "gatilho": c.maxima + t,
                            "stop": c.minima - t, "validade": int(ctx.p["validade"]),
                            "motivo": "MME%d virou para cima" % ctx.p["periodo"]}
        elif baixo and ctx.p["vender"] and (not ctx.pos or s.get("sair")):
            s["entrada"] = {"lado": "venda", "tipo": "stop", "gatilho": c.minima - t,
                            "stop": c.maxima + t, "validade": int(ctx.p["validade"]),
                            "motivo": "MME%d virou para baixo" % ctx.p["periodo"]}
        return s


class CruzamentoMedias(Estrategia):
    nome = "cruzamento_medias"
    titulo = "Cruzamento de médias (MME 9 x 21)"
    resumo = ("Compra quando a média rápida cruza a lenta para cima, vende quando cruza para "
              "baixo. Stop na mínima (ou máxima) dos últimos `stop_candles`. Sai no cruzamento "
              "contrário.")
    fonte = "regra clássica de médias móveis"
    params = {"rapida": 9, "lenta": 21, "stop_candles": 5}

    def preparar(self, candles, p):
        f = I.fechamentos(candles)
        return {"r": I.mme(f, int(p["rapida"])), "l": I.mme(f, int(p["lenta"]))}

    def sinal(self, i, ctx):
        r, l = ctx.ind["r"], ctx.ind["l"]
        if i < 1 or l[i - 1] is None:
            return {}
        cima = r[i] > l[i] and r[i - 1] <= l[i - 1]
        baixo = r[i] < l[i] and r[i - 1] >= l[i - 1]
        s, t, n = {}, ctx.tick, int(ctx.p["stop_candles"])
        if ctx.pos and ((ctx.pos["lado"] == "compra" and baixo) or
                        (ctx.pos["lado"] == "venda" and cima)):
            s["sair"] = "cruzamento contrário"
        if cima and (not ctx.pos or s.get("sair")):
            s["entrada"] = {"lado": "compra", "tipo": "mercado", "stop": ctx.minima(i, n) - t,
                            "motivo": "MME%s cruzou acima da MME%s" % (ctx.p["rapida"], ctx.p["lenta"])}
        elif baixo and (not ctx.pos or s.get("sair")):
            s["entrada"] = {"lado": "venda", "tipo": "mercado", "stop": ctx.maxima(i, n) + t,
                            "motivo": "MME%s cruzou abaixo da MME%s" % (ctx.p["rapida"], ctx.p["lenta"])}
        return s


class Vwap(Estrategia):
    nome = "vwap"
    titulo = "Lado da VWAP"
    resumo = ("Comprado enquanto o preço está acima da VWAP do dia, vendido abaixo: entra quando "
              "um candle fecha cruzando a VWAP e sai quando fecha do outro lado. Stop na mínima "
              "(ou máxima) dos últimos `stop_candles`. Começa a operar em `inicio`.")
    fonte = ("https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-"
             "for-day-trading-systems/")
    params = {"inicio": "09:30", "stop_candles": 3}

    def preparar(self, candles, p):
        return {"vwap": I.vwap(candles)}

    def sinal(self, i, ctx):
        if not ctx.mesmo_dia(i, i - 1):
            return {}
        v, cs = ctx.ind["vwap"], ctx.candles
        cima = cs[i].fechamento > v[i] and cs[i - 1].fechamento <= v[i - 1]
        baixo = cs[i].fechamento < v[i] and cs[i - 1].fechamento >= v[i - 1]
        s, t, n = {}, ctx.tick, int(ctx.p["stop_candles"])
        if ctx.pos and ((ctx.pos["lado"] == "compra" and cs[i].fechamento < v[i]) or
                        (ctx.pos["lado"] == "venda" and cs[i].fechamento > v[i])):
            s["sair"] = "fechou do outro lado da VWAP"
        if cs[i].data_hora.time() < _hora(ctx.p["inicio"]):
            return s
        if cima and (not ctx.pos or s.get("sair")):
            s["entrada"] = {"lado": "compra", "tipo": "mercado", "stop": ctx.minima(i, n) - t,
                            "motivo": "fechou acima da VWAP %s" % D._num(round(v[i]))}
        elif baixo and (not ctx.pos or s.get("sair")):
            s["entrada"] = {"lado": "venda", "tipo": "mercado", "stop": ctx.maxima(i, n) + t,
                            "motivo": "fechou abaixo da VWAP %s" % D._num(round(v[i]))}
        return s


class Ifr2(Estrategia):
    nome = "ifr2"
    titulo = "IFR2 (Stormer)"
    resumo = ("Compra quando o IFR de 2 períodos fecha abaixo de `entrada`. Sai quando o preço "
              "atinge a máxima dos 2 últimos candles, ou após `max_candles`. Sem stop de preço "
              "por padrão (só o tempo e o zeramento do dia). Pensado para gráfico diário: no "
              "intraday, os custos pesam.")
    fonte = "https://br.tradingview.com/script/UD0anrUb"
    params = {"periodo": 2, "entrada": 25, "max_candles": 7, "vender": False, "saida_venda": 75,
              "stop_pontos": 0}

    def preparar(self, candles, p):
        return {"ifr": I.ifr(I.fechamentos(candles), int(p["periodo"]))}

    def sinal(self, i, ctx):
        x = ctx.ind["ifr"][i]
        if x is None:
            return {}
        s = {}
        if ctx.pos:
            if ctx.pos["candles"] >= int(ctx.p["max_candles"]):
                s["sair"] = "saída por tempo (%d candles)" % ctx.p["max_candles"]
            elif ctx.pos["lado"] == "compra":
                s["alvo_movel"] = ctx.maxima(i, 2)
            else:
                s["alvo_movel"] = ctx.minima(i, 2)
            return s
        sp = float(ctx.p["stop_pontos"]) or None
        c = ctx.candles[i].fechamento
        if x < float(ctx.p["entrada"]):
            return {"entrada": {"lado": "compra", "tipo": "mercado",
                                "stop": (c - sp) if sp else None, "alvo": ctx.maxima(i, 2),
                                "motivo": "IFR%s em %.0f" % (ctx.p["periodo"], x)}}
        if ctx.p["vender"] and x > float(ctx.p["saida_venda"]):
            return {"entrada": {"lado": "venda", "tipo": "mercado",
                                "stop": (c + sp) if sp else None, "alvo": ctx.minima(i, 2),
                                "motivo": "IFR%s em %.0f" % (ctx.p["periodo"], x)}}
        return {}


class HiLo(Estrategia):
    nome = "hilo"
    titulo = "Hi-Lo Activator"
    resumo = ("Segue a tendência do Hi-Lo: compra quando o fechamento passa acima da média das "
              "máximas, vende quando passa abaixo da média das mínimas. A linha do Hi-Lo é o "
              "stop móvel. Vira a mão quando o Hi-Lo vira.")
    fonte = "https://github.com/fkdias/b3-mcp-server"
    params = {"periodo": 8}

    def preparar(self, candles, p):
        linha, tend = I.hilo(candles, int(p["periodo"]))
        return {"linha": linha, "tend": tend}

    def sinal(self, i, ctx):
        tend, linha = ctx.ind["tend"], ctx.ind["linha"]
        if i < 1 or linha[i] is None:
            return {}
        s, t = {}, ctx.tick
        virou_cima = tend[i] == 1 and tend[i - 1] != 1
        virou_baixo = tend[i] == -1 and tend[i - 1] != -1
        if ctx.pos:
            if (ctx.pos["lado"] == "compra" and virou_baixo) or \
                    (ctx.pos["lado"] == "venda" and virou_cima):
                s["sair"] = "Hi-Lo virou"
            else:
                s["stop_movel"] = linha[i] - t if ctx.pos["lado"] == "compra" else linha[i] + t
        if virou_cima and (not ctx.pos or s.get("sair")):
            s["entrada"] = {"lado": "compra", "tipo": "mercado", "stop": linha[i] - t,
                            "motivo": "Hi-Lo virou para alta"}
        elif virou_baixo and (not ctx.pos or s.get("sair")):
            s["entrada"] = {"lado": "venda", "tipo": "mercado", "stop": linha[i] + t,
                            "motivo": "Hi-Lo virou para baixo"}
        return s


ESTRATEGIAS = {e.nome: e for e in (RompimentoAbertura(), Setup91(), CruzamentoMedias(),
                                   Vwap(), Ifr2(), HiLo())}


def estrategia(nome):
    if nome not in ESTRATEGIAS:
        raise ValueError("estratégia desconhecida: %s (use: %s)" % (nome, ", ".join(ESTRATEGIAS)))
    return ESTRATEGIAS[nome]


def parametros(est, extras=None, arquivo=None):
    p = dict(PARAMS_GERAIS)
    p.update(est.params)
    arquivo = arquivo or os.path.join("b3", "estrategias.json")
    if os.path.exists(arquivo):
        with open(arquivo, encoding="utf-8") as f:
            cfg = json.load(f)
        p.update(cfg.get("geral", {}))
        p.update(cfg.get(est.nome, {}))
    for k, v in (extras or {}).items():
        if k not in p:
            raise ValueError("parâmetro %r não existe em %s (tem: %s)" % (k, est.nome, ", ".join(p)))
        base = p[k]
        if isinstance(base, bool):
            v = str(v).lower() in ("1", "true", "sim", "s", "yes")
        elif isinstance(base, int):
            v = int(float(v))
        elif isinstance(base, float):
            v = float(v)
        p[k] = v
    return p


# ------------------------------------------------------------------ simulação

def _hm(c):
    return c.data_hora.strftime("%Y-%m-%d %H:%M")


def simular(candles, nome, extras=None, arquivo_params=None):
    """Roda a estratégia candle a candle e devolve operações, posição aberta,
    ordem pendente e o sinal do último candle."""
    est = estrategia(nome)
    p = parametros(est, extras, arquivo_params)
    if not candles:
        return {"estrategia": nome, "parametros": p, "operacoes": [], "aberta": None,
                "pendente": None, "ultimo_sinal": {}, "resumo": resumir([], candles)}
    ativo = candles[0].ativo
    tick = C.ESPECIFICACOES[ativo]["tick"]
    ind = est.preparar(candles, p)
    ctx = Contexto(candles, ind, p, tick)
    fim_entr, zerar = _hora(p["fim_entradas"]), _hora(p["zerar_em"])
    ops, pos, pend_e, pend_s, ultimo = [], None, None, None, {}
    n = len(candles)

    def fechar(preco, c, motivo):
        nonlocal pos
        pts = (preco - pos["preco"]) if pos["lado"] == "compra" else (pos["preco"] - preco)
        op = dict(pos)
        op.pop("candles_desde", None)
        op["saida"] = {"data_hora": _hm(c), "preco": preco, "motivo": motivo}
        op["pontos"] = round(pts, 4)
        op["reais"] = C.valor_pontos(ativo, pts, int(p["contratos"]))["resultado_reais"]
        ops.append(op)
        pos = None
        ctx.pos = None

    for i, c in enumerate(candles):
        dia = c.data_hora.date()
        if i == 0 or dia != candles[i - 1].data_hora.date():
            pend_e, pend_s = None, None
            ctx.dia_inicio, ctx.ops_hoje = i, 0
        fim_do_dia = i + 1 < n and candles[i + 1].data_hora.date() != dia
        hora = c.data_hora.time()
        if pos:
            pos["candles"] += 1

        # 1. horário de zerar
        if pos and hora >= zerar:
            fechar(c.abertura, c, "zerada às %s" % p["zerar_em"])
            pend_s = None
        if hora >= zerar or hora >= fim_entr:
            pend_e = None                       # ordem armada não entra depois do horário
        # 2. saída a mercado pendente
        if pos and pend_s:
            fechar(c.abertura, c, pend_s)
        pend_s = None
        # 3. entrada pendente
        if pos is None and pend_e:
            e, preco = pend_e, None
            if e["tipo"] == "mercado":
                preco = c.abertura
            elif e["lado"] == "compra" and c.maxima >= e["gatilho"]:
                preco = max(e["gatilho"], c.abertura)
            elif e["lado"] == "venda" and c.minima <= e["gatilho"]:
                preco = min(e["gatilho"], c.abertura)
            if preco is not None:
                stop = e.get("stop")
                valido = stop is None or (stop < preco if e["lado"] == "compra" else stop > preco)
                if valido:
                    alvo = e.get("alvo")
                    if e.get("rr") and stop is not None:
                        risco = abs(preco - stop)
                        alvo = preco + e["rr"] * risco if e["lado"] == "compra" else preco - e["rr"] * risco
                        alvo = C.arredondar_tick(ativo, alvo)
                    pos = {"lado": e["lado"], "preco": preco, "stop": stop, "stop_inicial": stop,
                           "alvo": alvo, "candles": 0,
                           "entrada": {"data_hora": _hm(c), "preco": preco, "motivo": e["motivo"]}}
                    ctx.pos = pos
                    ctx.ops_hoje += 1
                pend_e = None
            else:
                e["validade"] = e.get("validade", 1) - 1
                if e["validade"] <= 0:
                    pend_e = None
        # 4. stop e alvo dentro do candle (stop primeiro: pessimista)
        if pos:
            compra = pos["lado"] == "compra"
            st, al = pos["stop"], pos["alvo"]
            if st is not None and ((compra and c.minima <= st) or (not compra and c.maxima >= st)):
                preco = min(c.abertura, st) if compra else max(c.abertura, st)
                if pos["entrada"]["data_hora"] == _hm(c):
                    preco = st
                fechar(preco, c, "stop")
            elif al is not None and ((compra and c.maxima >= al) or (not compra and c.minima <= al)):
                preco = max(c.abertura, al) if compra else min(c.abertura, al)
                if pos["entrada"]["data_hora"] == _hm(c):
                    preco = al
                fechar(preco, c, "alvo")
        # 5. fim do dia
        if pos and fim_do_dia:
            fechar(c.fechamento, c, "zerada no fim do dia")
        # 6. sinal no fechamento
        if fim_do_dia or hora >= zerar:
            continue
        s = est.sinal(i, ctx)
        if i == n - 1:
            ultimo = s
        if pos:
            if s.get("sair"):
                pend_s = s["sair"]
            if s.get("stop_movel") is not None and pos["stop"] is not None:
                novo = C.arredondar_tick(ativo, s["stop_movel"])
                pos["stop"] = max(pos["stop"], novo) if pos["lado"] == "compra" else min(pos["stop"], novo)
            if s.get("alvo_movel") is not None:
                pos["alvo"] = s["alvo_movel"]
        limite = int(p["max_operacoes_dia"])
        pode = hora < fim_entr and (not limite or ctx.ops_hoje < limite)
        if s.get("entrada") and pode and (pos is None or pend_s):
            e = dict(s["entrada"])
            if e.get("stop") is not None:
                e["stop"] = C.arredondar_tick(ativo, e["stop"])
            if e.get("gatilho") is not None:
                e["gatilho"] = C.arredondar_tick(ativo, e["gatilho"])
            e["sinal_em"] = _hm(c)
            pend_e = e

    aberta = None
    if pos:
        u = candles[-1].fechamento
        pts = (u - pos["preco"]) if pos["lado"] == "compra" else (pos["preco"] - u)
        aberta = dict(pos, pontos_abertos=round(pts, 4),
                      reais_abertos=C.valor_pontos(ativo, pts, int(p["contratos"]))["resultado_reais"])
    return {
        "ativo": ativo,
        "tf": D.inferir_tf(candles),
        "estrategia": nome,
        "titulo": est.titulo,
        "parametros": p,
        "ficticio": any(c.fonte == "mock" for c in candles),
        "de": _hm(candles[0]),
        "ate": _hm(candles[-1]),
        "operacoes": ops,
        "aberta": aberta,
        "pendente": pend_e,
        "ultimo_sinal": ultimo,
        "resumo": resumir(ops, candles),
    }


def resumir(ops, candles):
    if not ops:
        return {"operacoes": 0, "pontos": 0, "reais_bruto": 0.0}
    pts = [o["pontos"] for o in ops]
    ganhos = [x for x in pts if x > 0]
    perdas = [x for x in pts if x < 0]
    curva, pico, dd = 0.0, 0.0, 0.0
    for x in pts:
        curva += x
        pico = max(pico, curva)
        dd = min(dd, curva - pico)
    dias = len({o["entrada"]["data_hora"][:10] for o in ops})
    return {
        "operacoes": len(ops),
        "compras": sum(1 for o in ops if o["lado"] == "compra"),
        "vendas": sum(1 for o in ops if o["lado"] == "venda"),
        "acerto_pct": round(100.0 * len(ganhos) / len(ops), 1),
        "pontos": round(sum(pts), 2),
        "reais_bruto": round(sum(o["reais"] for o in ops), 2),
        "media_pontos": round(sum(pts) / len(ops), 2),
        "maior_ganho": max(pts),
        "maior_perda": min(pts),
        "fator_lucro": round(sum(ganhos) / -sum(perdas), 2) if perdas else None,
        "drawdown_pontos": round(dd, 2),
        "dias_com_operacao": dias,
        "pregoes": len({c.data_hora.date() for c in candles}),
    }


# ------------------------------------------------------------------- CLI

def _params_cli(lista):
    out = {}
    for item in lista or []:
        if "=" not in item:
            raise ValueError("use --param nome=valor (recebi %r)" % item)
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _carregar(arquivo, tf=None):
    cs = D.ler(arquivo)
    if tf and tf != D.inferir_tf(cs):
        cs = D.reamostrar(cs, tf)
    return cs


def caminho_saida(r):
    return os.path.join(PASTA_SINAIS, "%s_%dm_%s.json" % (r["ativo"], r["tf"], r["estrategia"]))


def salvar(r, caminho=None):
    caminho = caminho or caminho_saida(r)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)
    return caminho


def _brl(v):
    s = "{:,.2f}".format(abs(v)).replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def texto_resumo(r):
    s = r["resumo"]
    linhas = ["%s  %s %dm  %s a %s%s" % (r["titulo"], r["ativo"], r["tf"], r["de"], r["ate"],
                                        "  [DADOS FICTÍCIOS]" if r["ficticio"] else "")]
    if not s["operacoes"]:
        linhas.append("  nenhuma operação no período")
    else:
        linhas.append("  %d operações (%d compras, %d vendas) em %d de %d pregões, acerto %.1f%%"
                      % (s["operacoes"], s["compras"], s["vendas"], s["dias_com_operacao"],
                         s["pregoes"], s["acerto_pct"]))
        linhas.append("  resultado bruto: %+.1f pontos = %s, média %+.1f, fator de lucro %s, "
                      "drawdown %.1f pontos" % (s["pontos"], _brl(s["reais_bruto"]), s["media_pontos"],
                                               s["fator_lucro"], s["drawdown_pontos"]))
    return "\n".join(linhas)


def texto_status(r):
    linhas = []
    a, pe, u = r["aberta"], r["pendente"], r["ultimo_sinal"]
    if a:
        linhas.append("  POSIÇÃO: %s em %s desde %s, stop %s, alvo %s, %+.1f pontos" % (
            a["lado"].upper(), D._num(a["preco"]), a["entrada"]["data_hora"][11:],
            D._num(a["stop"]) if a["stop"] is not None else "-",
            D._num(a["alvo"]) if a["alvo"] is not None else "-", a["pontos_abertos"]))
    if pe:
        if pe["tipo"] == "stop":
            linhas.append("  ORDEM ARMADA: %s stop em %s, stop %s (%s)" % (
                pe["lado"], D._num(pe["gatilho"]), D._num(pe["stop"]), pe["motivo"]))
        else:
            linhas.append("  SINAL: %s a mercado no próximo candle (%s)" % (pe["lado"], pe["motivo"]))
    if u.get("sair"):
        linhas.append("  SAÍDA no próximo candle: %s" % u["sair"])
    if not linhas:
        linhas.append("  sem posição nem sinal no último candle")
    return "\n".join(linhas)


def cmd_listar(a):
    if a.json:
        print(json.dumps({k: {"titulo": e.titulo, "resumo": e.resumo, "fonte": e.fonte,
                              "parametros": dict(PARAMS_GERAIS, **e.params)}
                          for k, e in ESTRATEGIAS.items()}, ensure_ascii=False, indent=2))
        return 0
    for k, e in ESTRATEGIAS.items():
        print("%s  %s" % (k, e.titulo))
        print("    %s" % e.resumo)
        print("    parâmetros: %s" % ", ".join("%s=%s" % kv for kv in e.params.items()))
    print("\nGerais: %s" % ", ".join("%s=%s" % kv for kv in PARAMS_GERAIS.items()))
    return 0


def cmd_rodar(a):
    cs = _carregar(a.arquivo, a.tf)
    r = simular(cs, a.estrategia, _params_cli(a.param))
    caminho = salvar(r, a.saida)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print(texto_resumo(r))
    if r["operacoes"]:
        print("  últimas operações:")
        for o in r["operacoes"][-a.ultimas:]:
            print("    %s %-6s %s -> %s %s  %+7.1f pts  %s  (%s)" % (
                o["entrada"]["data_hora"], o["lado"], D._num(o["preco"]), o["saida"]["data_hora"][11:],
                D._num(o["saida"]["preco"]), o["pontos"], _brl(o["reais"]), o["saida"]["motivo"]))
    print(texto_status(r))
    print("  gravado em %s" % caminho)
    return 0


def cmd_comparar(a):
    cs = _carregar(a.arquivo, a.tf)
    nomes = a.estrategias.split(",") if a.estrategias else list(ESTRATEGIAS)
    linhas = []
    for nome in nomes:
        r = simular(cs, nome.strip())
        salvar(r)
        s = r["resumo"]
        linhas.append((nome, s))
    if a.json:
        print(json.dumps({n: s for n, s in linhas}, ensure_ascii=False, indent=2))
        return 0
    tf = D.inferir_tf(cs)
    print("%s %dm, %s a %s%s  (resultado BRUTO, sem custos)" % (
        cs[0].ativo, tf, _hm(cs[0])[:10], _hm(cs[-1])[:10],
        "  [DADOS FICTÍCIOS]" if any(c.fonte == "mock" for c in cs) else ""))
    print("  %-20s %5s %7s %10s %14s %7s %10s" % ("estratégia", "ops", "acerto", "pontos",
                                                  "reais", "fator", "drawdown"))
    for nome, s in sorted(linhas, key=lambda x: -x[1].get("pontos", 0)):
        if not s["operacoes"]:
            print("  %-20s %5d" % (nome, 0))
            continue
        print("  %-20s %5d %6.1f%% %+10.1f %14s %7s %10.1f" % (
            nome, s["operacoes"], s["acerto_pct"], s["pontos"], _brl(s["reais_bruto"]),
            s["fator_lucro"] if s["fator_lucro"] is not None else "-", s["drawdown_pontos"]))
    return 0


def cmd_agora(a):
    cs = _carregar(a.arquivo, a.tf)
    r = simular(cs, a.estrategia, _params_cli(a.param))
    salvar(r)
    if a.json:
        print(json.dumps({"ativo": r["ativo"], "tf": r["tf"], "estrategia": r["estrategia"],
                          "ultimo_candle": r["ate"], "aberta": r["aberta"], "pendente": r["pendente"],
                          "ultimo_sinal": r["ultimo_sinal"]}, ensure_ascii=False, indent=2))
        return 0
    print("%s %s %dm, último candle %s%s" % (r["titulo"], r["ativo"], r["tf"], r["ate"],
                                             "  [FICTÍCIO]" if r["ficticio"] else ""))
    print(texto_status(r))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Sinais de estratégias sobre os candles da b3-dados.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("listar", help="estratégias disponíveis e parâmetros")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_listar)
    for nome, fn, ajuda in (("rodar", cmd_rodar, "roda uma estratégia e grava b3/sinais/"),
                            ("agora", cmd_agora, "só a situação no último candle"),
                            ("comparar", cmd_comparar, "roda várias e compara")):
        s = sub.add_parser(nome, help=ajuda)
        s.add_argument("arquivo")
        s.add_argument("--tf", type=int, help="reamostrar para este tempo gráfico antes")
        s.add_argument("--json", action="store_true")
        if nome == "comparar":
            s.add_argument("--estrategias", help="lista separada por vírgula (padrão: todas)")
        else:
            s.add_argument("--estrategia", "-e", required=True)
            s.add_argument("--param", "-p", action="append", help="nome=valor (pode repetir)")
        if nome == "rodar":
            s.add_argument("--saida")
            s.add_argument("--ultimas", type=int, default=8)
        s.set_defaults(fn=fn)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, OSError) as e:
        print("erro: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
