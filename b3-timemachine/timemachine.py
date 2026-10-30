#!/usr/bin/env python3
"""b3-timemachine: simula um plano de day trade (entrada, stop, alvo) em milhares
de pregões montados com os candles reais do próprio ativo, e roda o mesmo plano
nos pregões reais do passado. NÃO envia ordens.

Só biblioteca padrão. Python 3.8+.

Uso:
  python3 timemachine.py b3/dados/WIN_5m.csv --lado compra --stop-pontos 300 --rr 2
  python3 timemachine.py b3/dados/WIN_5m.csv --lado venda --entrada 130250 --stop 130500 --alvo 129800 --hora 10:30
  python3 timemachine.py b3/dados/WDO_1m.csv --tf 5 --lado compra --stop-pontos 8 --alvo-pontos 12
  python3 timemachine.py b3/dados/WIN_5m.csv --de-sinal b3/sinais/WIN_5m_setup_9_1.json

Como funciona (bootstrap por horário do dia):
  1. separa os pregões COMPLETOS anteriores à data do plano (sem buracos e sem
     dia de horário reduzido) e fica com os últimos `--dias`;
  2. guarda cada candle como 4 razões (abertura, máxima, mínima e fechamento
     divididos pelo fechamento do candle anterior). Assim o padrão serve para
     qualquer nível de preço e a troca de contrato não atrapalha;
  3. cada pregão simulado começa no preço de entrada e, candle a candle até
     `--ate`, sorteia um candle real do mesmo horário (± `--janela` candles);
  4. dentro de cada candle o stop conta antes do alvo (pessimista, igual à
     b3-sinais). Num gap além do stop, a saída é no preço do gap;
  5. repete `--sessoes` vezes, com semente fixa: a mesma entrada dá o mesmo
     resultado.

O resultado é BRUTO (sem custos) e é uma simulação, não uma previsão.
"""

import argparse
import datetime as dt
import json
import math
import os
import random
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.environ.get("B3_SINAIS_DIR", os.path.join(_AQUI, "..", "b3-sinais"))))
try:
    import sinais as S  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit("erro: não achei b3-sinais/sinais.py. Instale b3-contratos, b3-dados, b3-sinais e "
             "b3-timemachine lado a lado.")
D, C = S.D, S.C

PASTA_SAIDA = os.path.join("b3", "timemachine")
MIN_SESSOES = 20


# ------------------------------------------------------------------ pregões

def _abertura(c):
    h = C.horario(c.ativo, c.data_hora.date())
    return dt.datetime.combine(c.data_hora.date(), h[0]) if h else None


def slot(c, tf):
    """Posição do candle no pregão: 0 = primeiro candle do dia."""
    ab = _abertura(c)
    if ab is None:
        return None
    return int((c.data_hora - ab).total_seconds() // 60) // tf


def slots_do_dia(ativo, data, tf):
    return int(math.ceil(C.minutos_de_pregao(ativo, data) / float(tf)))


def hora_do_slot(ativo, data, tf, k):
    h = C.horario(ativo, data)
    return dt.datetime.combine(data, h[0]) + dt.timedelta(minutes=k * tf)


def separar_pregoes(candles, tf):
    """Devolve (completos, descartados). Cada pregão completo é uma lista de
    candles indexada pelo slot. Fica fora o dia com buraco, candle fora da grade
    ou horário diferente do normal (Quarta de Cinzas, por exemplo)."""
    por_dia = {}
    for c in candles:
        por_dia.setdefault(c.data_hora.date(), []).append(c)
    completos, descartados = [], []
    normal = {}
    for d, cs in sorted(por_dia.items()):
        n = slots_do_dia(cs[0].ativo, d, tf)
        normal[n] = normal.get(n, 0) + 1
    tamanho_normal = max(normal, key=normal.get) if normal else 0
    for d, cs in sorted(por_dia.items()):
        n = slots_do_dia(cs[0].ativo, d, tf)
        grade = {}
        ok = n == tamanho_normal
        for c in cs:
            k = slot(c, tf)
            if k is None or k in grade or k >= n or \
                    c.data_hora != hora_do_slot(c.ativo, d, tf, k):
                ok = False
                break
            grade[k] = c
        if ok and len(grade) == n:
            completos.append((d, [grade[k] for k in range(n)]))
        else:
            descartados.append(d)
    return completos, descartados


def razoes(pregao):
    """Por slot: (o, h, l, c) relativos ao fechamento anterior e (h, l, c)
    relativos à própria abertura. O primeiro candle do dia usa a própria
    abertura, então o gap da noite não entra."""
    out = []
    for k, c in enumerate(pregao):
        ref = pregao[k - 1].fechamento if k else c.abertura
        out.append(((c.abertura / ref, c.maxima / ref, c.minima / ref, c.fechamento / ref),
                    (c.maxima / c.abertura, c.minima / c.abertura, c.fechamento / c.abertura)))
    return out


# --------------------------------------------------------------------- plano

def _num(v):
    return D._num(round(v, 4))


def montar_plano(ativo, lado, entrada, stop=None, alvo=None, stop_pontos=None, alvo_pontos=None,
                 rr=None):
    lado = (lado or "").lower()
    if lado not in ("compra", "venda"):
        raise ValueError("diga o lado: --lado compra ou --lado venda")
    sinal = 1 if lado == "compra" else -1
    if stop is None and stop_pontos:
        stop = entrada - sinal * float(stop_pontos)
    if stop is None:
        raise ValueError("falta o stop: --stop PREÇO ou --stop-pontos N")
    stop = C.arredondar_tick(ativo, stop)
    risco = (entrada - stop) * sinal
    if risco <= 0:
        raise ValueError("stop do lado errado: na %s o stop fica %s da entrada %s"
                         % (lado, "abaixo" if sinal > 0 else "acima", _num(entrada)))
    if alvo is None and alvo_pontos:
        alvo = entrada + sinal * float(alvo_pontos)
    if alvo is None:
        alvo = entrada + sinal * float(rr or 2.0) * risco
    alvo = C.arredondar_tick(ativo, alvo)
    ganho = (alvo - entrada) * sinal
    if ganho <= 0:
        raise ValueError("alvo do lado errado: na %s o alvo fica %s da entrada %s"
                         % (lado, "acima" if sinal > 0 else "abaixo", _num(entrada)))
    return {"ativo": ativo, "lado": lado, "entrada": entrada, "stop": stop, "alvo": alvo,
            "risco_pontos": round(risco, 4), "alvo_pontos": round(ganho, 4),
            "rr": round(ganho / risco, 2)}


def caminhar(barras, lado, entrada, stop, alvo):
    """Percorre candles absolutos (o, h, l, c). Devolve (resultado, preço de
    saída, índice). Stop antes do alvo no mesmo candle."""
    compra = lado == "compra"
    for j, (o, h, l, c) in enumerate(barras):
        if compra:
            if l <= stop:
                return "stop", (min(o, stop) if j else stop), j
            if h >= alvo:
                return "alvo", (max(o, alvo) if j else alvo), j
        else:
            if h >= stop:
                return "stop", (max(o, stop) if j else stop), j
            if l <= alvo:
                return "alvo", (min(o, alvo) if j else alvo), j
    return "nenhum", barras[-1][3], len(barras) - 1


def _r(plano, saida):
    sinal = 1 if plano["lado"] == "compra" else -1
    return (saida - plano["entrada"]) * sinal / plano["risco_pontos"]


def _pct(ordenados, q):
    if not ordenados:
        return None
    i = (len(ordenados) - 1) * q
    a, b = int(math.floor(i)), int(math.ceil(i))
    return ordenados[a] + (ordenados[b] - ordenados[a]) * (i - a)


# ----------------------------------------------------------------- simulação

def simular(candles, plano, data, hora, ate="17:55", sessoes=10000, semente=19, janela=2,
            dias=60, tf=None, amostras=160):
    """Roda a máquina do tempo. `data` é o dia do plano (só pregões anteriores
    entram), `hora` é o horário da entrada (início do candle de entrada) e `ate`
    é o horário de zerar."""
    if not candles:
        raise ValueError("arquivo sem candles")
    ativo = candles[0].ativo
    tf = tf or D.inferir_tf(candles)
    h = C.horario(ativo, data)
    if h is None:
        raise ValueError("%s não tem pregão de %s" % (data, ativo))
    completos, descartados = separar_pregoes(candles, tf)
    pool = [(d, p) for d, p in completos if d < data][-int(dias):]
    if len(pool) < MIN_SESSOES:
        raise ValueError("só %d pregões completos antes de %s (mínimo %d). Importe mais histórico."
                         % (len(pool), data, MIN_SESSOES))
    n = len(pool[0][1])
    abre = dt.datetime.combine(data, h[0])
    fecha = dt.datetime.combine(data, h[1])
    t_ent = dt.datetime.combine(data, hora)
    t_ate = min(dt.datetime.combine(data, S._hora(ate)), fecha)
    k0 = int(math.ceil((t_ent - abre).total_seconds() / 60.0 / tf))
    if t_ent < abre:
        k0 = 0
    # último candle simulado: o que começa antes de `ate`
    k_fim = min(n, int(math.ceil((t_ate - abre).total_seconds() / 60.0 / tf))) - 1
    if k0 > k_fim:
        raise ValueError("a entrada (%s) fica depois do horário de zerar (%s)"
                         % (hora.strftime("%H:%M"), t_ate.strftime("%H:%M")))
    rz = [razoes(p) for _, p in pool]
    cand = []
    for k in range(n):
        lo, hi = max(0, k - janela), min(n - 1, k + janela)
        cand.append([rz[s][j] for s in range(len(rz)) for j in range(lo, hi + 1)])

    rnd = random.Random(semente)
    lado, ent, st, al = plano["lado"], plano["entrada"], plano["stop"], plano["alvo"]
    compra = lado == "compra"
    passos = k_fim - k0 + 1
    contagem = {"alvo": 0, "stop": 0, "nenhum": 0}
    verdes, rs, finais = 0, [], []
    faixas = [[] for _ in range(passos)]
    caminhos = []
    for s in range(int(sessoes)):
        px, fora, res, saida = ent, False, None, None
        trilha = []
        for j in range(passos):
            k = k0 + j
            rel_ant, rel_ab = cand[k][rnd.randrange(len(cand[k]))]
            if j == 0:
                o = ent
                hh, ll, cc = o * rel_ab[0], o * rel_ab[1], o * rel_ab[2]
            else:
                o, hh, ll, cc = px * rel_ant[0], px * rel_ant[1], px * rel_ant[2], px * rel_ant[3]
            if not fora:
                if compra and ll <= st:
                    res, saida = "stop", (min(o, st) if j else st)
                elif not compra and hh >= st:
                    res, saida = "stop", (max(o, st) if j else st)
                elif compra and hh >= al:
                    res, saida = "alvo", (max(o, al) if j else al)
                elif not compra and ll <= al:
                    res, saida = "alvo", (min(o, al) if j else al)
                fora = res is not None
            px = cc
            faixas[j].append(cc)
            trilha.append(cc)
        if res is None:
            res, saida = "nenhum", px
        contagem[res] += 1
        r = _r(plano, saida)
        rs.append(r)
        if res == "alvo" or (res == "nenhum" and r > 0):
            verdes += 1
        finais.append(px)
        if s < amostras:
            caminhos.append([round(x, 2) for x in trilha])

    total = float(sessoes)
    finais.sort()
    odds = {k: round(100.0 * v / total, 1) for k, v in contagem.items()}
    odds["verde"] = round(100.0 * verdes / total, 1)
    r_medio = sum(rs) / total
    horas = [hora_do_slot(ativo, data, tf, k0 + j).strftime("%H:%M") for j in range(passos)]
    leque = []
    for j in range(passos):
        f = sorted(faixas[j])
        leque.append({"hora": horas[j], "p5": round(_pct(f, .05), 2), "p25": round(_pct(f, .25), 2),
                      "p50": round(_pct(f, .5), 2), "p75": round(_pct(f, .75), 2),
                      "p95": round(_pct(f, .95), 2)})
    historia = historico(pool, plano, k0, k_fim)
    pontos_medio = r_medio * plano["risco_pontos"]
    return {
        "ativo": ativo,
        "tf": tf,
        "plano": dict(plano, data=data.isoformat(), hora=t_ent.strftime("%H:%M"),
                      ate=t_ate.strftime("%H:%M")),
        "ficticio": any(c.fonte == "mock" for c in candles),
        "pregoes_usados": len(pool),
        "pregoes_de": pool[0][0].isoformat(),
        "pregoes_ate": pool[-1][0].isoformat(),
        "pregoes_descartados": len([d for d in descartados if d < data]),
        "sessoes": int(sessoes),
        "semente": semente,
        "janela": janela,
        "odds": odds,
        "preco_final": {"p5": round(_pct(finais, .05), 2), "p50": round(_pct(finais, .5), 2),
                        "p95": round(_pct(finais, .95), 2)},
        "r_medio": round(r_medio, 3),
        "pontos_medio": round(pontos_medio, 2),
        "reais_medio_contrato": C.valor_pontos(ativo, round(pontos_medio, 4))["resultado_reais"],
        "empate_pct": round(100.0 / (1 + plano["rr"]), 1),
        "veredito": veredito(odds, plano["rr"]),
        "historico": historia,
        "leque": leque,
        "histograma": histograma(finais, 24),
        "caminhos": caminhos,
    }


def historico(pool, plano, k0, k_fim):
    """O mesmo plano nos pregões reais: entra na abertura do candle `k0` de cada
    dia, com stop e alvo à mesma distância percentual da entrada."""
    cont = {"alvo": 0, "stop": 0, "nenhum": 0}
    rs = []
    for _, p in pool:
        barras = [(c.abertura, c.maxima, c.minima, c.fechamento) for c in p[k0:k_fim + 1]]
        if not barras:
            continue
        e = barras[0][0]
        f = e / plano["entrada"]
        sinal = 1 if plano["lado"] == "compra" else -1
        st = e - sinal * plano["risco_pontos"] * f
        al = e + sinal * plano["alvo_pontos"] * f
        res, saida, _ = caminhar(barras, plano["lado"], e, st, al)
        cont[res] += 1
        rs.append((saida - e) * sinal / (plano["risco_pontos"] * f))
    n = len(rs)
    return {"pregoes": n, "alvo": cont["alvo"], "stop": cont["stop"], "nenhum": cont["nenhum"],
            "r_medio": round(sum(rs) / n, 3) if n else None}


def veredito(odds, rr):
    """Compara a chance de o alvo vir antes do stop com o empate de 1 em (1 + rr)."""
    resolvidos = odds["alvo"] + odds["stop"]
    empate = 100.0 / (1 + rr)
    if resolvidos < 1:
        return {"texto": "quase nada bate stop ou alvo até o horário de zerar: o plano depende "
                         "do preço no fim", "diferenca_pts": None}
    taxa = 100.0 * odds["alvo"] / resolvidos
    dif = taxa - empate
    if abs(dif) < 5:
        txt = "cara ou coroa: alvo antes do stop em %.0f%% dos casos resolvidos, empate em %.0f%%" % (taxa, empate)
    elif dif >= 15:
        txt = "a favor, com folga: %.0f%% contra o empate de %.0f%%" % (taxa, empate)
    elif dif > 0:
        txt = "levemente a favor: %.0f%% contra o empate de %.0f%%" % (taxa, empate)
    elif dif <= -15:
        txt = "contra, com folga: %.0f%% contra o empate de %.0f%%" % (taxa, empate)
    else:
        txt = "levemente contra: %.0f%% contra o empate de %.0f%%" % (taxa, empate)
    if odds["nenhum"] >= 50:
        txt += "; mais da metade dos pregões chega ao horário de zerar sem bater nada"
    return {"texto": txt, "alvo_antes_do_stop_pct": round(taxa, 1), "diferenca_pts": round(dif, 1)}


def histograma(ordenados, caixas):
    if not ordenados:
        return []
    lo, hi = ordenados[0], ordenados[-1]
    if hi <= lo:
        return [{"de": lo, "ate": hi, "n": len(ordenados)}]
    w = (hi - lo) / caixas
    cont = [0] * caixas
    for x in ordenados:
        cont[min(caixas - 1, int((x - lo) / w))] += 1
    return [{"de": round(lo + i * w, 2), "ate": round(lo + (i + 1) * w, 2), "n": cont[i]}
            for i in range(caixas)]


# ------------------------------------------------------------- do b3-sinais

def plano_do_sinal(caminho, candles, rr=None):
    """Lê um arquivo de b3/sinais/: a posição aberta ou a ordem pendente vira o
    plano. Devolve (lado, entrada, stop, alvo, data, hora)."""
    with open(caminho, encoding="utf-8") as f:
        r = json.load(f)
    ult = candles[-1]
    tf = r.get("tf") or D.inferir_tf(candles)
    proximo = ult.data_hora + dt.timedelta(minutes=tf)
    a, pe = r.get("aberta"), r.get("pendente")
    if a:
        return {"lado": a["lado"], "entrada": ult.fechamento, "stop": a.get("stop"),
                "alvo": a.get("alvo"), "data": proximo.date(), "hora": proximo.time(),
                "origem": "posição aberta de %s desde %s (simula o resto do dia a partir do último "
                          "preço %s)" % (r.get("estrategia"), a["entrada"]["data_hora"],
                                         _num(ult.fechamento))}
    if pe:
        ent = pe.get("gatilho") if pe.get("tipo") == "stop" else ult.fechamento
        rr = rr or pe.get("rr") or r.get("parametros", {}).get("rr")
        return {"lado": pe["lado"], "entrada": ent, "stop": pe.get("stop"), "alvo": pe.get("alvo"),
                "rr": rr, "data": proximo.date(), "hora": proximo.time(),
                "origem": "%s de %s (%s)" % ("ordem stop armada" if pe.get("tipo") == "stop"
                                             else "sinal a mercado", r.get("estrategia"),
                                             pe.get("motivo", ""))}
    raise ValueError("%s não tem posição aberta nem ordem pendente no último candle" % caminho)


# -------------------------------------------------------------------- texto

def _brl(v):
    return S._brl(v)


def texto(r):
    p, o = r["plano"], r["odds"]
    L = []
    L.append("Máquina do tempo  %s %dm  %s às %s, zera %s%s" % (
        r["ativo"], r["tf"], p["data"], p["hora"], p["ate"],
        "  [DADOS FICTÍCIOS]" if r["ficticio"] else ""))
    vp = C.valor_pontos(r["ativo"], p["risco_pontos"])["resultado_reais"]
    va = C.valor_pontos(r["ativo"], p["alvo_pontos"])["resultado_reais"]
    L.append("  plano: %s em %s, stop %s (%s pts = %s), alvo %s (%s pts = %s), %.2fR  [por contrato]" % (
        p["lado"].upper(), _num(p["entrada"]), _num(p["stop"]), _num(p["risco_pontos"]), _brl(vp),
        _num(p["alvo"]), _num(p["alvo_pontos"]), _brl(va), p["rr"]))
    if p.get("origem"):
        L.append("  origem: %s" % p["origem"])
    L.append("  base: %d pregões completos de %s a %s, %d simulações (semente %s)" % (
        r["pregoes_usados"], r["pregoes_de"], r["pregoes_ate"], r["sessoes"], r["semente"]))
    L.append("")
    L.append("  alvo primeiro   %5.1f%%" % o["alvo"])
    L.append("  stop primeiro   %5.1f%%" % o["stop"])
    L.append("  nenhum até %s %5.1f%%" % (p["ate"], o["nenhum"]))
    L.append("  terminou no verde %4.1f%%" % o["verde"])
    pf = r["preco_final"]
    L.append("  preço às %s: mediana %s, 90%% entre %s e %s" % (
        p["ate"], _num(C.arredondar_tick(r["ativo"], pf["p50"])),
        _num(C.arredondar_tick(r["ativo"], pf["p5"])), _num(C.arredondar_tick(r["ativo"], pf["p95"]))))
    L.append("  resultado médio: %+.2fR = %+.1f pts = %s por contrato (bruto)" % (
        r["r_medio"], r["pontos_medio"], _brl(r["reais_medio_contrato"])))
    h = r["historico"]
    if h["pregoes"]:
        L.append("  nos %d pregões reais, entrando às %s: alvo %d, stop %d, nenhum %d, média %+.2fR" % (
            h["pregoes"], p["hora"], h["alvo"], h["stop"], h["nenhum"], h["r_medio"]))
    L.append("  veredito: %s" % r["veredito"]["texto"])
    L.append("")
    L.append("  leque de preços (5%, mediana, 95%):")
    passo = max(1, len(r["leque"]) // 8)
    linhas = r["leque"][::passo]
    if r["leque"][-1] not in linhas:
        linhas.append(r["leque"][-1])
    for f in linhas:
        L.append("    %s  %10s %10s %10s" % (f["hora"], _num(C.arredondar_tick(r["ativo"], f["p5"])),
                                             _num(C.arredondar_tick(r["ativo"], f["p50"])),
                                             _num(C.arredondar_tick(r["ativo"], f["p95"]))))
    if r["ficticio"]:
        L.append("")
        L.append("  Dados FICTÍCIOS: serve para testar o fluxo, nunca para decidir um trade.")
    L.append("  Simulação com candles de %d min: não vê o que acontece dentro do candle, nem notícia "
             "que não esteve nos últimos %d pregões. Resultado bruto, sem custos." % (
                 r["tf"], r["pregoes_usados"]))
    return "\n".join(L)


def salvar(r, caminho=None):
    caminho = caminho or os.path.join(PASTA_SAIDA, "%s_%dm_%s_%s.json" % (
        r["ativo"], r["tf"], r["plano"]["data"], r["plano"]["hora"].replace(":", "")))
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, caminho)
    return caminho


# ---------------------------------------------------------------------- CLI

def _data_hora_padrao(candles, tf):
    ult = candles[-1]
    prox = ult.data_hora + dt.timedelta(minutes=tf)
    h = C.horario(ult.ativo, ult.data_hora.date())
    if h and prox < dt.datetime.combine(ult.data_hora.date(), h[1]):
        return prox.date(), prox.time()
    return None, None


def main(argv=None):
    p = argparse.ArgumentParser(description="Máquina do tempo: simula um plano em milhares de "
                                            "pregões montados com candles reais.")
    p.add_argument("arquivo", help="candles da b3-dados (ex.: b3/dados/WIN_5m.csv)")
    p.add_argument("--tf", type=int, help="reamostrar antes (1 min vira 5 por padrão)")
    p.add_argument("--lado", choices=["compra", "venda"])
    p.add_argument("--entrada", type=float, help="preço de entrada (padrão: último fechamento)")
    p.add_argument("--stop", type=float)
    p.add_argument("--stop-pontos", type=float)
    p.add_argument("--alvo", type=float)
    p.add_argument("--alvo-pontos", type=float)
    p.add_argument("--rr", type=float, help="alvo em múltiplos do risco (padrão 2)")
    p.add_argument("--data", help="dia do plano, AAAA-MM-DD (padrão: o do último candle)")
    p.add_argument("--hora", help="horário da entrada, HH:MM (padrão: o candle seguinte ao último)")
    p.add_argument("--ate", default=None, help="horário de zerar (padrão: zerar_em da b3-sinais)")
    p.add_argument("--de-sinal", help="usa a posição ou a ordem de um arquivo de b3/sinais/")
    p.add_argument("--sessoes", type=int, default=10000)
    p.add_argument("--semente", type=int, default=19)
    p.add_argument("--janela", type=int, default=2, help="candles vizinhos no sorteio (± N)")
    p.add_argument("--dias", type=int, default=60, help="pregões de histórico usados")
    p.add_argument("--gravar", nargs="?", const="", help="grava o JSON (leque, caminhos, histograma)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        cs = D.ler(a.arquivo)
        if not cs:
            raise ValueError("%s está vazio" % a.arquivo)
        tf_arq = D.inferir_tf(cs)
        tf = a.tf or (5 if tf_arq == 1 else tf_arq)
        if tf != tf_arq:
            cs = D.reamostrar(cs, tf)
        ativo = cs[0].ativo
        ate = a.ate or S.PARAMS_GERAIS["zerar_em"]
        lado, entrada, stop, alvo, rr, origem = a.lado, a.entrada, a.stop, a.alvo, a.rr, None
        data = dt.date.fromisoformat(a.data) if a.data else None
        hora = S._hora(a.hora) if a.hora else None
        if a.de_sinal:
            sg = plano_do_sinal(a.de_sinal, cs, rr)
            lado = lado or sg["lado"]
            entrada = entrada if entrada is not None else sg["entrada"]
            stop = stop if stop is not None else sg["stop"]
            alvo = alvo if alvo is not None else sg["alvo"]
            rr = rr or sg.get("rr")
            data, hora, origem = data or sg["data"], hora or sg["hora"], sg["origem"]
        if data is None or hora is None:
            d0, h0 = _data_hora_padrao(cs, tf)
            if (data is None or hora is None) and d0 is None:
                raise ValueError("o último candle do arquivo é o fim do pregão: diga --data e --hora "
                                 "do plano (por exemplo --data 2026-10-30 --hora 09:15)")
            data, hora = data or d0, hora or h0
        if entrada is None:
            antes = [c for c in cs if c.data_hora < dt.datetime.combine(data, hora)]
            if not antes:
                raise ValueError("diga --entrada: não há candle antes de %s %s" % (data, hora))
            entrada = antes[-1].fechamento
        entrada = C.arredondar_tick(ativo, entrada)
        plano = montar_plano(ativo, lado, entrada, stop, alvo, a.stop_pontos, a.alvo_pontos, rr)
        if origem:
            if a.de_sinal and alvo is None and a.alvo_pontos is None:
                if sg.get("rr") and not a.rr:
                    origem += "; alvo de %sR, como na estratégia" % D._num(rr)
                else:
                    origem += ("; a estratégia não tem alvo fixo (sai por sinal), então o alvo "
                               "simulado é %sR" % D._num(rr or 2))
            plano["origem"] = origem
        r = simular(cs, plano, data, hora, ate=ate, sessoes=a.sessoes, semente=a.semente,
                    janela=a.janela, dias=a.dias, tf=tf)
        if a.gravar is not None:
            r["gravado_em"] = salvar(r, a.gravar or None)
        if a.json:
            leve = {k: v for k, v in r.items() if k not in ("caminhos", "leque", "histograma")}
            print(json.dumps(leve, ensure_ascii=False, indent=2, default=str))
        else:
            print(texto(r))
            if r.get("gravado_em"):
                print("  gravado em %s" % r["gravado_em"])
        return 0
    except (ValueError, OSError) as e:
        print("erro: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
