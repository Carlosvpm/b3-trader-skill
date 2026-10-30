#!/usr/bin/env python3
"""b3-scanner: varre WIN e WDO em vários tempos gráficos e lista os setups que
aparecem no último candle fechado. NÃO envia ordens.

Só biblioteca padrão. Python 3.8+.

Uso:
  python3 scanner.py                                  # WIN e WDO, diário + 5, 15 e 60 min
  python3 scanner.py --ativos WIN --tfs 5,15
  python3 scanner.py --aovivo                         # usa b3/dados/*_1m_aovivo.csv
  python3 scanner.py --setups rompimento,orb -p rompimento_n=30
  python3 scanner.py --sem-estrategias --json
  python3 scanner.py listar

Uma varredura é uma lista de gráficos que batem com uma regra, não uma lista
de compras. Os setups olham os dois lados, porque no futuro dá para vender.

Saída: b3/scanner/varredura.json. Código de saída 0 quando acha algo, 1
quando não acha nada, 2 em erro.
"""

import argparse
import datetime as dt
import json
import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.environ.get("B3_SINAIS_DIR", os.path.join(_AQUI, "..", "b3-sinais"))))
try:
    import sinais as S  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit("erro: não achei b3-sinais/sinais.py. Instale b3-contratos, b3-dados, b3-sinais e "
             "b3-scanner lado a lado.")
D, C, I = S.D, S.C, S.I

PASTA_SAIDA = os.path.join("b3", "scanner")
DIARIO = "D"

PARAMS = {
    "rompimento_n": 20,          # candles anteriores para a máxima/mínima
    "media": 20,                 # média simples para a retomada
    "ifr_periodo": 14,
    "ifr_baixo": 30,
    "ifr_alto": 70,
    "atr": 14,
    "bandeira_impulso": 10,      # candles do mastro
    "bandeira_consolidacao": 5,  # candles da bandeira
    "bandeira_impulso_atr": 3.0,  # mastro mínimo, em ATRs
    "bandeira_faixa_atr": 1.5,   # faixa máxima da bandeira, em ATRs
    "orb_minutos": 15,
    "orb_tf": 5,                 # candle que confirma o rompimento da abertura
    "dias": 40,                  # pregões lidos para os tempos intradiários
}

SETUPS = {
    "rompimento": "fechou acima da máxima (ou abaixo da mínima) dos `rompimento_n` candles anteriores",
    "bandeira": "mastro de `bandeira_impulso_atr` ATRs seguido de `bandeira_consolidacao` candles "
                "numa faixa de até `bandeira_faixa_atr` ATRs, sem devolver metade do mastro",
    "retomada_media": "fechou do outro lado da média de `media` candles",
    "ifr_extremo": "IFR(`ifr_periodo`) abaixo de `ifr_baixo` ou acima de `ifr_alto`",
    "repique": "IFR estava no extremo no candle anterior e este fechou virando",
    "orb": "rompimento da faixa dos primeiros `orb_minutos` do pregão de hoje, confirmado por "
           "um candle de `orb_tf` min fechando fora (só no último pregão do arquivo)",
    "estrategias": "situação das seis estratégias da b3-sinais no último candle: posição, "
                   "ordem armada, sinal ou saída",
}


# ---------------------------------------------------------------- arquivos

def arquivo_base(ativo, pasta, aovivo=False):
    """O arquivo mais fino disponível. Devolve (caminho, tf) ou (None, None)."""
    nomes = ["%s_1m_aovivo.csv"] if aovivo else []
    nomes += ["%s_1m.csv", "%s_5m.csv", "%s_15m.csv", "%s_60m.csv"]
    for n in nomes:
        p = os.path.join(pasta, n % ativo)
        if os.path.exists(p):
            return p, None
    return None, None


def so_ultimos_dias(candles, dias):
    datas = sorted({c.data_hora.date() for c in candles})
    if len(datas) <= dias:
        return candles
    corte = datas[-dias]
    return [c for c in candles if c.data_hora.date() >= corte]


def fechados(res, tf, fim_base):
    """Tira o último candle reamostrado se ele ainda está se formando: o dado de
    base acaba antes do fim do candle e antes do fim do pregão."""
    if not res:
        return res
    u = res[-1]
    h = C.horario(u.ativo, u.data_hora.date())
    fim_pregao = dt.datetime.combine(u.data_hora.date(), h[1]) if h else u.data_hora
    if fim_base < min(u.data_hora + dt.timedelta(minutes=tf), fim_pregao):
        return res[:-1]
    return res


def diario(candles, tf_base):
    """Um candle por pregão. O último dia só entra se estiver completo."""
    out, por_dia = [], {}
    for c in candles:
        por_dia.setdefault(c.data_hora.date(), []).append(c)
    for d in sorted(por_dia):
        cs = por_dia[d]
        h = C.horario(cs[0].ativo, d)
        if h is None:
            continue
        fim = cs[-1].data_hora + dt.timedelta(minutes=tf_base)
        completo = fim >= dt.datetime.combine(d, h[1]) - dt.timedelta(minutes=tf_base)
        if not completo and d == max(por_dia):
            continue
        out.append(D.Candle(dt.datetime.combine(d, h[0]), cs[0].ativo, cs[-1].contrato,
                            cs[0].abertura, max(c.maxima for c in cs), min(c.minima for c in cs),
                            cs[-1].fechamento, sum(c.volume for c in cs), cs[-1].fonte))
    return out


# ------------------------------------------------------------------ setups

def _hit(cs, tf, setup, direcao, detalhe, nivel=None, plano=None):
    c = cs[-1]
    h = {"ativo": c.ativo, "tf": tf, "setup": setup, "direcao": direcao,
         "candle": c.data_hora.strftime("%Y-%m-%d" if tf == DIARIO else "%Y-%m-%d %H:%M"),
         "preco": c.fechamento, "contrato": c.contrato, "detalhe": detalhe}
    if nivel is not None:
        h["nivel"] = nivel
    if plano:
        h["plano"] = plano
    return h


def s_rompimento(cs, tf, p):
    n = int(p["rompimento_n"])
    if len(cs) < n + 1:
        return []
    ant, c = cs[-n - 1:-1], cs[-1]
    alta, baixa = max(x.maxima for x in ant), min(x.minima for x in ant)
    if c.fechamento > alta:
        return [_hit(cs, tf, "rompimento", "alta", "fechou %s acima da máxima de %d candles (%s)"
                     % (D._num(c.fechamento - alta), n, D._num(alta)), alta)]
    if c.fechamento < baixa:
        return [_hit(cs, tf, "rompimento", "baixa", "fechou %s abaixo da mínima de %d candles (%s)"
                     % (D._num(baixa - c.fechamento), n, D._num(baixa)), baixa)]
    return []


def s_bandeira(cs, tf, p):
    m, k = int(p["bandeira_impulso"]), int(p["bandeira_consolidacao"])
    if len(cs) < m + k + int(p["atr"]) + 1:
        return []
    atr = I.atr(cs, int(p["atr"]))[-k - 1]
    if not atr:
        return []
    ini, topo = cs[-k - m - 1].fechamento, cs[-k - 1].fechamento
    mastro = topo - ini
    flag = cs[-k:]
    faixa = max(x.maxima for x in flag) - min(x.minima for x in flag)
    if abs(mastro) < float(p["bandeira_impulso_atr"]) * atr or faixa > float(p["bandeira_faixa_atr"]) * atr:
        return []
    if mastro > 0 and min(x.minima for x in flag) > ini + mastro / 2.0:
        return [_hit(cs, tf, "bandeira", "alta", "mastro de %s pts (%.1f ATR) e %d candles numa faixa de %s"
                     % (D._num(mastro), mastro / atr, k, D._num(faixa)), max(x.maxima for x in flag))]
    if mastro < 0 and max(x.maxima for x in flag) < ini + mastro / 2.0:
        return [_hit(cs, tf, "bandeira", "baixa", "mastro de %s pts (%.1f ATR) e %d candles numa faixa de %s"
                     % (D._num(-mastro), -mastro / atr, k, D._num(faixa)), min(x.minima for x in flag))]
    return []


def s_retomada_media(cs, tf, p):
    n = int(p["media"])
    if len(cs) < n + 1:
        return []
    mm = I.mms(I.fechamentos(cs), n)
    a, b = cs[-2].fechamento, cs[-1].fechamento
    if a < mm[-2] and b > mm[-1]:
        return [_hit(cs, tf, "retomada_media", "alta", "voltou acima da média de %d (%s)"
                     % (n, D._num(round(mm[-1], 1))), round(mm[-1], 1))]
    if a > mm[-2] and b < mm[-1]:
        return [_hit(cs, tf, "retomada_media", "baixa", "perdeu a média de %d (%s)"
                     % (n, D._num(round(mm[-1], 1))), round(mm[-1], 1))]
    return []


def _ifr(cs, p):
    return I.ifr(I.fechamentos(cs), int(p["ifr_periodo"]))


def s_ifr_extremo(cs, tf, p):
    x = _ifr(cs, p)[-1]
    if x is None:
        return []
    if x < float(p["ifr_baixo"]):
        return [_hit(cs, tf, "ifr_extremo", "sobrevendido", "IFR%d em %.0f" % (p["ifr_periodo"], x))]
    if x > float(p["ifr_alto"]):
        return [_hit(cs, tf, "ifr_extremo", "sobrecomprado", "IFR%d em %.0f" % (p["ifr_periodo"], x))]
    return []


def s_repique(cs, tf, p):
    v = _ifr(cs, p)
    if len(cs) < 2 or v[-2] is None:
        return []
    a, b = cs[-2].fechamento, cs[-1].fechamento
    if v[-2] < float(p["ifr_baixo"]) and b > a:
        return [_hit(cs, tf, "repique", "alta", "IFR%d estava em %.0f e fechou subindo %s"
                     % (p["ifr_periodo"], v[-2], D._num(b - a)))]
    if v[-2] > float(p["ifr_alto"]) and b < a:
        return [_hit(cs, tf, "repique", "baixa", "IFR%d estava em %.0f e fechou caindo %s"
                     % (p["ifr_periodo"], v[-2], D._num(a - b)))]
    return []


INTRA = [("rompimento", s_rompimento), ("bandeira", s_bandeira),
         ("retomada_media", s_retomada_media), ("ifr_extremo", s_ifr_extremo),
         ("repique", s_repique)]


def orb(base, tf_base, p):
    """Faixa de abertura do último pregão do arquivo e o primeiro candle de
    `orb_tf` min que fechou fora dela."""
    if not base:
        return None
    hoje = base[-1].data_hora.date()
    cs = [c for c in base if c.data_hora.date() == hoje]
    h = C.horario(cs[0].ativo, hoje)
    if h is None:
        return None
    abre = dt.datetime.combine(hoje, h[0])
    fim_faixa = abre + dt.timedelta(minutes=int(p["orb_minutos"]))
    fim_base = cs[-1].data_hora + dt.timedelta(minutes=tf_base)
    ativo = cs[0].ativo
    faixa = [c for c in cs if c.data_hora < fim_faixa]
    st = {"ativo": ativo, "data": hoje.isoformat(), "minutos": int(p["orb_minutos"])}
    if not faixa or fim_base < fim_faixa:
        st["situacao"] = "formando"
        return st
    alta, baixa = max(c.maxima for c in faixa), min(c.minima for c in faixa)
    st.update({"alta": alta, "baixa": baixa, "pontos": round(alta - baixa, 4),
               "reais": C.valor_pontos(ativo, alta - baixa)["resultado_reais"]})
    tf = max(int(p["orb_tf"]), tf_base)
    depois = fechados(D.reamostrar([c for c in cs if c.data_hora >= fim_faixa], tf)
                      if tf != tf_base else [c for c in cs if c.data_hora >= fim_faixa], tf, fim_base)
    st["situacao"] = "dentro"
    for c in depois:
        if c.data_hora < fim_faixa:
            continue
        if c.fechamento > alta or c.fechamento < baixa:
            compra = c.fechamento > alta
            st.update({"situacao": "rompeu para cima" if compra else "rompeu para baixo",
                       "hora": (c.data_hora + dt.timedelta(minutes=tf)).strftime("%H:%M"),
                       "preco": c.fechamento})
            st["plano"] = {"lado": "compra" if compra else "venda", "entrada": c.fechamento,
                           "stop": baixa if compra else alta, "rr": 2.0,
                           "hora": st["hora"], "data": hoje.isoformat()}
            break
    return st


def estrategias(cs, tf):
    out = []
    prox = cs[-1].data_hora + dt.timedelta(minutes=tf)
    quando = {"data": prox.date().isoformat(), "hora": prox.strftime("%H:%M")}
    for nome in S.ESTRATEGIAS:
        r = S.simular(cs, nome)
        a, pe, u = r["aberta"], r["pendente"], r["ultimo_sinal"]
        if a:
            out.append(_hit(cs, tf, "estrategias", a["lado"],
                            "%s: posição %s desde %s, %+.1f pts" % (nome, a["lado"], a["entrada"]["data_hora"][11:],
                                                                   a["pontos_abertos"]),
                            plano={"lado": a["lado"], "entrada": cs[-1].fechamento, "stop": a.get("stop"),
                                   "alvo": a.get("alvo"), "estrategia": nome, **quando}))
            if u.get("sair"):
                out[-1]["detalhe"] += "; SAÍDA no próximo candle (%s)" % u["sair"]
        elif pe:
            if pe["tipo"] == "stop":
                det = "%s: ordem %s armada em %s, stop %s" % (nome, pe["lado"], D._num(pe["gatilho"]),
                                                              D._num(pe["stop"]))
                ent = pe["gatilho"]
            else:
                det = "%s: sinal de %s a mercado no próximo candle (%s)" % (nome, pe["lado"], pe["motivo"])
                ent = cs[-1].fechamento
            plano = {"lado": pe["lado"], "entrada": ent, "stop": pe.get("stop"), "alvo": pe.get("alvo"),
                     "estrategia": nome, **quando}
            if pe.get("rr"):
                plano["rr"] = pe["rr"]
            out.append(_hit(cs, tf, "estrategias", pe["lado"], det, plano=plano))
    return out


# --------------------------------------------------------------- varredura

def parametros(extras=None):
    p = dict(PARAMS)
    for k, v in (extras or {}).items():
        if k not in p:
            raise ValueError("parâmetro %r não existe (tem: %s)" % (k, ", ".join(p)))
        p[k] = type(p[k])(float(v)) if isinstance(p[k], (int, float)) else v
    return p


def _tfs(texto):
    out = []
    for x in str(texto).split(","):
        x = x.strip().upper()
        if not x:
            continue
        out.append(DIARIO if x in ("D", "DIARIO", "DIÁRIO") else int(x))
    return out


def varrer(base_por_ativo, tfs, setups=None, p=None, agora=None):
    """`base_por_ativo`: {ativo: candles do arquivo mais fino}. Devolve o dicionário
    da varredura."""
    p = p or dict(PARAMS)
    setups = set(setups or SETUPS)
    hits, avisos, orbs, varridos = [], [], {}, []
    ficticio = False
    replay = agora is not None
    agora = agora or dt.datetime.now(C.BRT).replace(tzinfo=None)
    for ativo, base in base_por_ativo.items():
        if base and replay:
            # relógio fixo: só o que já tinha fechado naquele momento
            tfb = D.inferir_tf(base)
            base = [c for c in base if c.data_hora + dt.timedelta(minutes=tfb) <= agora]
        if not base:
            avisos.append("%s: sem candles" % ativo)
            continue
        ficticio = ficticio or any(c.fonte == "mock" for c in base[-50:])
        tf_base = D.inferir_tf(base)
        fim_base = base[-1].data_hora + dt.timedelta(minutes=tf_base)
        pg = C.status_pregao(ativo, agora)
        if pg["aberto"] and not replay and (agora - fim_base).total_seconds() > 15 * 60:
            avisos.append("%s: pregão aberto, mas o último candle é de %s. O dado está parado?"
                          % (ativo, base[-1].data_hora.strftime("%Y-%m-%d %H:%M")))
        recente = so_ultimos_dias(base, int(p["dias"]))
        for tf in tfs:
            if tf == DIARIO:
                cs = diario(base, tf_base)
            else:
                if tf < tf_base:
                    avisos.append("%s: não dá para fazer %d min a partir de %d min" % (ativo, tf, tf_base))
                    continue
                cs = recente if tf == tf_base else fechados(D.reamostrar(recente, tf), tf, fim_base)
            if len(cs) < 3:
                avisos.append("%s %s: poucos candles (%d)" % (ativo, _tf_txt(tf), len(cs)))
                continue
            varridos.append({"ativo": ativo, "tf": tf, "candles": len(cs),
                             "ultimo": cs[-1].data_hora.strftime("%Y-%m-%d" if tf == DIARIO
                                                                 else "%Y-%m-%d %H:%M")})
            for nome, fn in INTRA:
                if nome in setups:
                    hits.extend(fn(cs, tf, p))
            if "estrategias" in setups and tf != DIARIO:
                hits.extend(estrategias(cs, tf))
        if "orb" in setups:
            o = orb(base, tf_base, p)
            if o:
                orbs[ativo] = o
                if o["situacao"].startswith("rompeu"):
                    hits.append({"ativo": ativo, "tf": max(int(p["orb_tf"]), tf_base), "setup": "orb",
                                 "direcao": "alta" if "cima" in o["situacao"] else "baixa",
                                 "candle": "%s %s" % (o["data"], o["hora"]), "preco": o["preco"],
                                 "contrato": base[-1].contrato, "nivel": o["alta"] if "cima" in o["situacao"]
                                 else o["baixa"],
                                 "detalhe": "%s da faixa %s-%s (%s pts) às %s" % (
                                     o["situacao"], D._num(o["baixa"]), D._num(o["alta"]),
                                     D._num(o["pontos"]), o["hora"]),
                                 "plano": o["plano"]})
    ordem_tf = lambda t: -1 if t == DIARIO else t  # noqa: E731
    ordem_setup = list(SETUPS)
    hits.sort(key=lambda h: (h["ativo"], ordem_tf(h["tf"]), ordem_setup.index(h["setup"])))
    return {"as_of": agora.strftime("%Y-%m-%d %H:%M"), "ficticio": ficticio, "parametros": p,
            "setups": sorted(setups, key=ordem_setup.index), "varridos": varridos, "orb": orbs,
            "hits": hits, "avisos": avisos}


def _tf_txt(tf):
    return "diário" if tf == DIARIO else "%dm" % tf


def comando_timemachine(h, arquivos):
    """Linha pronta para testar o plano na b3-timemachine."""
    pl = h.get("plano")
    arq = arquivos.get(h["ativo"])
    if not pl or pl.get("stop") is None or not arq or h["tf"] == DIARIO:
        return None
    partes = ["timemachine.py", arq, "--tf", str(h["tf"]),
              "--lado", pl["lado"], "--entrada", D._num(pl["entrada"]), "--stop", D._num(pl["stop"])]
    if pl.get("alvo") is not None:
        partes += ["--alvo", D._num(pl["alvo"])]
    else:
        partes += ["--rr", D._num(pl.get("rr") or 2)]
    if pl.get("data") and pl.get("hora"):
        partes += ["--data", pl["data"], "--hora", pl["hora"]]
    return " ".join(partes)


def texto(r, mostrar=40):
    L = ["Varredura %s  (%s)%s" % (r["as_of"], ", ".join(r["setups"]),
                                     "  [DADOS FICTÍCIOS]" if r["ficticio"] else "")]
    for v in r["varridos"]:
        L.append("  %s %-6s %4d candles, último %s" % (v["ativo"], _tf_txt(v["tf"]), v["candles"], v["ultimo"]))
    for ativo, o in r["orb"].items():
        if o["situacao"] == "formando":
            L.append("  ORB %s %s: faixa dos primeiros %d min ainda se formando" % (ativo, o["data"], o["minutos"]))
        else:
            L.append("  ORB %s %s: faixa %s-%s (%s pts = %s), %s%s" % (
                ativo, o["data"], D._num(o["baixa"]), D._num(o["alta"]), D._num(o["pontos"]),
                S._brl(o["reais"]), o["situacao"], (" às %s" % o["hora"]) if o.get("hora") else ""))
    L.append("")
    if not r["hits"]:
        L.append("  nenhum setup no último candle fechado")
    for h in r["hits"][:mostrar]:
        L.append("  %s %-6s %-15s %-13s %s  %s" % (h["ativo"], _tf_txt(h["tf"]), h["setup"], h["direcao"],
                                                   h["candle"], h["detalhe"]))
    if len(r["hits"]) > mostrar:
        L.append("  ... e mais %d (use --mostrar ou --json)" % (len(r["hits"]) - mostrar))
    planos = [comando_timemachine(h, r.get("arquivos", {})) for h in r["hits"]]
    planos = [x for x in planos if x]
    if planos:
        L.append("")
        L.append("  para testar um plano na máquina do tempo (b3-timemachine):")
        for x in planos[:3]:
            L.append("    %s" % x)
    for a in r["avisos"]:
        L.append("  aviso: %s" % a)
    L.append("")
    L.append("  Uma varredura lista gráficos que batem com uma regra. Não é recomendação de compra "
             "ou venda, e o resultado vence quando o preço anda: rode de novo antes de agir.")
    return "\n".join(L)


def salvar(r, caminho=None):
    caminho = caminho or os.path.join(PASTA_SAIDA, "varredura.json")
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)
    return caminho


# --------------------------------------------------------------------- CLI

def _params_cli(lista):
    out = {}
    for item in lista or []:
        if "=" not in item:
            raise ValueError("use -p nome=valor (recebi %r)" % item)
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cmd_listar(a):
    if a.json:
        print(json.dumps({"setups": SETUPS, "parametros": PARAMS}, ensure_ascii=False, indent=2))
        return 0
    for k, v in SETUPS.items():
        print("%-15s %s" % (k, v))
    print("\nParâmetros: %s" % ", ".join("%s=%s" % kv for kv in PARAMS.items()))
    return 0


def cmd_varrer(a):
    p = parametros(_params_cli(a.param))
    setups = [s.strip() for s in a.setups.split(",")] if a.setups else list(SETUPS)
    if a.sem_estrategias and "estrategias" in setups:
        setups.remove("estrategias")
    for s in setups:
        if s not in SETUPS:
            raise ValueError("setup desconhecido: %s (use: %s)" % (s, ", ".join(SETUPS)))
    base, arquivos = {}, {}
    for ativo in [x.strip().upper() for x in a.ativos.split(",") if x.strip()]:
        if a.arquivo:
            caminho = a.arquivo
        else:
            caminho, _ = arquivo_base(ativo, a.pasta, a.aovivo)
        if not caminho:
            raise ValueError("não achei candles de %s em %s. Rode a b3-dados antes (mock serve para "
                             "testar)." % (ativo, a.pasta))
        cs = D.ler(caminho)
        if a.arquivo:
            ativo = cs[0].ativo if cs else ativo
        base[ativo] = cs
        arquivos[ativo] = caminho
        if a.arquivo:
            break
    agora = dt.datetime.strptime(a.agora, "%Y-%m-%d %H:%M") if a.agora else None
    r = varrer(base, _tfs(a.tfs), setups, p, agora)
    r["arquivos"] = arquivos
    if not a.no_write:
        r["gravado_em"] = salvar(r)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(texto(r, a.mostrar))
        if r.get("gravado_em"):
            print("  gravado em %s" % r["gravado_em"])
    return 0 if r["hits"] else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["listar"]:
        p = argparse.ArgumentParser(prog="scanner.py listar")
        p.add_argument("--json", action="store_true")
        return cmd_listar(p.parse_args(argv[1:]))
    if argv[:1] == ["varrer"]:
        argv = argv[1:]
    p = argparse.ArgumentParser(description="Varre WIN e WDO atrás de setups no último candle fechado. "
                                            "Use `scanner.py listar` para ver os setups.")
    p.add_argument("--ativos", default="WIN,WDO")
    p.add_argument("--tfs", default="D,5,15,60", help="tempos gráficos; D = diário")
    p.add_argument("--setups", help="lista separada por vírgula (padrão: todos)")
    p.add_argument("--sem-estrategias", action="store_true", help="não roda as estratégias da b3-sinais")
    p.add_argument("--param", "-p", action="append", help="nome=valor (pode repetir)")
    p.add_argument("--pasta", default=D.PASTA_PADRAO)
    p.add_argument("--arquivo", help="um arquivo só, em vez de procurar na pasta")
    p.add_argument("--aovivo", action="store_true", help="prefere b3/dados/ATIVO_1m_aovivo.csv")
    p.add_argument("--agora", help="fixa o relógio, AAAA-MM-DD HH:MM (horário de Brasília)")
    p.add_argument("--mostrar", type=int, default=40)
    p.add_argument("--no-write", action="store_true", help="não grava b3/scanner/varredura.json")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        return cmd_varrer(a)
    except (ValueError, OSError) as e:
        print("erro: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
