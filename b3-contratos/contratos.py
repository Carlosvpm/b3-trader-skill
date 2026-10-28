#!/usr/bin/env python3
"""b3-contratos: regras dos contratos futuros WIN (mini índice) e WDO (mini dólar).

Só biblioteca padrão. Python 3.8+.

Responde, sem chutar:
  - qual é o contrato vigente numa data (WINZ26, WDOX26...)
  - quando ele vence, qual o último dia de negociação e quando rolar
  - se o pregão está aberto, e quando abre de novo
  - quais dias não têm pregão (feriados B3)
  - quanto vale uma variação de pontos em reais

Uso:
  python3 contratos.py info WIN
  python3 contratos.py vigente WIN [--data 2026-10-28]
  python3 contratos.py vencimentos WDO --ano 2026
  python3 contratos.py pregao [--ativo WIN] [--agora "2026-10-28 10:15"]
  python3 contratos.py feriados --ano 2026
  python3 contratos.py valor WIN --pontos 350 --contratos 2
  python3 contratos.py valor WDO --de 5412.5 --para 5398 --lado venda

Acrescente --json a qualquer comando para saída em JSON.

Horários e feriados podem ser ajustados em b3/config.json (veja config.example.json).
"""

import argparse
import datetime as dt
import json
import os
import sys

# Brasil não tem horário de verão desde 2019: horário de Brasília = UTC-3 fixo.
BRT = dt.timezone(dt.timedelta(hours=-3), "BRT")

MESES_LETRA = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
               7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
LETRA_MES = {v: k for k, v in MESES_LETRA.items()}

# Especificações (fonte: páginas de produto da B3; confira antes de operar).
ESPECIFICACOES = {
    "WIN": {
        "nome": "Futuro Mini de Ibovespa",
        "objeto": "Índice Bovespa",
        "valor_ponto": 0.20,          # R$ por ponto, por contrato
        "tick": 5.0,                  # variação mínima em pontos
        "meses": [2, 4, 6, 8, 10, 12],
        "regra_vencimento": "quarta-feira mais próxima do dia 15 do mês de vencimento "
                            "(se não houver pregão, o próximo dia útil)",
        "ultimo_dia": "o próprio dia do vencimento",
        "liquidacao": "financeira",
        "casas_decimais": 0,
    },
    "WDO": {
        "nome": "Futuro Mini de Dólar",
        "objeto": "US$ 10.000 (taxa de câmbio R$/US$, cotada em R$ por US$ 1.000)",
        "valor_ponto": 10.00,
        "tick": 0.5,
        "meses": list(range(1, 13)),
        "regra_vencimento": "primeiro dia útil do mês de vencimento",
        "ultimo_dia": "último dia útil do mês anterior ao vencimento",
        "liquidacao": "financeira",
        "casas_decimais": 1,
    },
}

# Horário de negociação (Brasília). A B3 muda isso algumas vezes por ano,
# em geral junto do horário de verão dos EUA. Cada período vale a partir
# da data "desde". Se o seu dado for de antes, ajuste em b3/config.json.
HORARIOS_PADRAO = {
    "WIN": [{"desde": "2026-03-09", "abertura": "09:00", "fechamento": "18:25"}],
    "WDO": [{"desde": "2026-03-09", "abertura": "09:00", "fechamento": "18:30"}],
}
# Quarta-feira de Cinzas: negociação só a partir das 13h.
ABERTURA_CINZAS = "13:00"

# Lista oficial publicada pela B3 (calendário de negociação 2026).
# Para outros anos o calendário é calculado (feriados nacionais fixos,
# móveis pela Páscoa, 24/12 e 31/12) e marcado como "calculado".
FERIADOS_OFICIAIS = {
    2026: {
        "2026-01-01": "Confraternização Universal",
        "2026-02-16": "Carnaval",
        "2026-02-17": "Carnaval",
        "2026-04-03": "Sexta-feira Santa",
        "2026-04-21": "Tiradentes",
        "2026-05-01": "Dia do Trabalho",
        "2026-06-04": "Corpus Christi",
        "2026-09-07": "Independência do Brasil",
        "2026-10-12": "Nossa Senhora Aparecida",
        "2026-11-02": "Finados",
        "2026-11-20": "Dia Nacional de Zumbi e da Consciência Negra",
        "2026-12-24": "Véspera de Natal",
        "2026-12-25": "Natal",
        "2026-12-31": "Véspera de Ano Novo",
    },
}

ROLAGEM_PADRAO = {"WIN": 2, "WDO": 2}  # dias úteis antes do último dia


# ---------------------------------------------------------------- config

def _caminho_config():
    return os.environ.get("B3_CONFIG", os.path.join("b3", "config.json"))


def carregar_config(caminho=None):
    caminho = caminho or _caminho_config()
    if not os.path.exists(caminho):
        return {}
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


_CONFIG = None


def config():
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = carregar_config()
    return _CONFIG


def definir_config(cfg):
    """Usado pelos testes e por outros scripts para injetar uma config."""
    global _CONFIG
    _CONFIG = cfg or {}
    _cache_feriados.clear()


# --------------------------------------------------------------- datas

def _data(valor):
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    return dt.date.fromisoformat(str(valor)[:10])


def pascoa(ano):
    """Domingo de Páscoa (algoritmo gregoriano anônimo)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(ano, mes, dia)


def quarta_de_cinzas(ano):
    return pascoa(ano) - dt.timedelta(days=46)


def feriados_calculados(ano):
    p = pascoa(ano)
    fer = {
        dt.date(ano, 1, 1): "Confraternização Universal",
        p - dt.timedelta(days=48): "Carnaval",
        p - dt.timedelta(days=47): "Carnaval",
        p - dt.timedelta(days=2): "Sexta-feira Santa",
        dt.date(ano, 4, 21): "Tiradentes",
        dt.date(ano, 5, 1): "Dia do Trabalho",
        p + dt.timedelta(days=60): "Corpus Christi",
        dt.date(ano, 9, 7): "Independência do Brasil",
        dt.date(ano, 10, 12): "Nossa Senhora Aparecida",
        dt.date(ano, 11, 2): "Finados",
        dt.date(ano, 11, 15): "Proclamação da República",
        dt.date(ano, 12, 24): "Véspera de Natal",
        dt.date(ano, 12, 25): "Natal",
        dt.date(ano, 12, 31): "Véspera de Ano Novo",
    }
    if ano >= 2024:
        fer[dt.date(ano, 11, 20)] = "Dia Nacional de Zumbi e da Consciência Negra"
    # Só interessam os que caem em dia de semana.
    return {d: n for d, n in fer.items() if d.weekday() < 5}


_cache_feriados = {}


def feriados(ano):
    """{data: (nome, origem)} dos dias de semana sem pregão."""
    if ano in _cache_feriados:
        return _cache_feriados[ano]
    if ano in FERIADOS_OFICIAIS:
        base = {_data(d): (n, "oficial B3") for d, n in FERIADOS_OFICIAIS[ano].items()}
    else:
        base = {d: (n, "calculado") for d, n in feriados_calculados(ano).items()}
    cfg = config()
    for d, n in cfg.get("feriados_extras", {}).items():
        dd = _data(d)
        if dd.year == ano:
            base[dd] = (n, "config")
    for d in cfg.get("dias_com_pregao", []):
        base.pop(_data(d), None)
    _cache_feriados[ano] = dict(sorted(base.items()))
    return _cache_feriados[ano]


def eh_dia_util(data):
    data = _data(data)
    return data.weekday() < 5 and data not in feriados(data.year)


def proximo_dia_util(data, incluir=True):
    data = _data(data)
    if not incluir:
        data += dt.timedelta(days=1)
    while not eh_dia_util(data):
        data += dt.timedelta(days=1)
    return data


def dia_util_anterior(data, incluir=False):
    data = _data(data)
    if not incluir:
        data -= dt.timedelta(days=1)
    while not eh_dia_util(data):
        data -= dt.timedelta(days=1)
    return data


def somar_dias_uteis(data, n):
    data = _data(data)
    passo = 1 if n >= 0 else -1
    restantes = abs(n)
    while restantes:
        data += dt.timedelta(days=passo)
        if eh_dia_util(data):
            restantes -= 1
    return data


def dias_uteis_entre(inicio, fim):
    """Dias úteis em (inicio, fim]. Negativo se fim < inicio."""
    inicio, fim = _data(inicio), _data(fim)
    if fim < inicio:
        return -dias_uteis_entre(fim, inicio)
    n, d = 0, inicio
    while d < fim:
        d += dt.timedelta(days=1)
        if eh_dia_util(d):
            n += 1
    return n


# ------------------------------------------------------------ horários

def _hora(texto):
    h, m = texto.split(":")
    return dt.time(int(h), int(m))


def horario(ativo, data):
    """(abertura, fechamento) como datetime.time, ou None se não há pregão."""
    ativo = _ativo(ativo)
    data = _data(data)
    if not eh_dia_util(data):
        return None
    periodos = config().get("horarios", {}).get(ativo) or HORARIOS_PADRAO[ativo]
    periodos = sorted(periodos, key=lambda p: p["desde"])
    escolhido = periodos[0]
    for p in periodos:
        if _data(p["desde"]) <= data:
            escolhido = p
    abertura = _hora(escolhido["abertura"])
    if data == quarta_de_cinzas(data.year):
        abertura = max(abertura, _hora(config().get("abertura_cinzas", ABERTURA_CINZAS)))
    return abertura, _hora(escolhido["fechamento"])


def minutos_de_pregao(ativo, data):
    h = horario(ativo, data)
    if h is None:
        return 0
    a, f = h
    return (f.hour * 60 + f.minute) - (a.hour * 60 + a.minute)


def status_pregao(ativo, agora):
    """Diz se o pregão está aberto em `agora` (datetime ingênuo = Brasília)."""
    ativo = _ativo(ativo)
    if agora.tzinfo is not None:
        agora = agora.astimezone(BRT).replace(tzinfo=None)
    hoje = agora.date()
    h = horario(ativo, hoje)
    if h is not None:
        abre = dt.datetime.combine(hoje, h[0])
        fecha = dt.datetime.combine(hoje, h[1])
        if abre <= agora < fecha:
            return {"ativo": ativo, "aberto": True, "agora": agora.isoformat(timespec="minutes"),
                    "fecha_em": fecha.isoformat(timespec="minutes"),
                    "minutos_para_fechar": int((fecha - agora).total_seconds() // 60)}
        if agora < abre:
            return {"ativo": ativo, "aberto": False, "agora": agora.isoformat(timespec="minutes"),
                    "motivo": "antes da abertura",
                    "proxima_abertura": abre.isoformat(timespec="minutes")}
        motivo = "pregão encerrado"
    else:
        fer = feriados(hoje.year).get(hoje)
        motivo = "feriado: " + fer[0] if fer else "fim de semana"
    prox = proximo_dia_util(hoje, incluir=False)
    abre = dt.datetime.combine(prox, horario(ativo, prox)[0])
    return {"ativo": ativo, "aberto": False, "agora": agora.isoformat(timespec="minutes"),
            "motivo": motivo, "proxima_abertura": abre.isoformat(timespec="minutes")}


# ---------------------------------------------------------- contratos

def _ativo(ativo):
    a = str(ativo).upper().strip()
    if a not in ESPECIFICACOES:
        raise ValueError("ativo desconhecido: %r (use WIN ou WDO)" % ativo)
    return a


def codigo(ativo, ano, mes):
    return "%s%s%02d" % (_ativo(ativo), MESES_LETRA[mes], ano % 100)


def ler_codigo(texto):
    """'WINZ26' -> ('WIN', 2026, 12)."""
    t = texto.upper().strip()
    ativo, letra, aa = t[:3], t[3:4], t[4:6]
    if ativo not in ESPECIFICACOES or letra not in LETRA_MES or not aa.isdigit() or len(t) != 6:
        raise ValueError("código de contrato inválido: %r (ex.: WINZ26, WDOX26)" % texto)
    return ativo, 2000 + int(aa), LETRA_MES[letra]


def vencimento(ativo, ano, mes):
    ativo = _ativo(ativo)
    if mes not in ESPECIFICACOES[ativo]["meses"]:
        raise ValueError("%s não vence no mês %d" % (ativo, mes))
    if ativo == "WIN":
        quartas = [dt.date(ano, mes, d) for d in range(12, 19)
                   if dt.date(ano, mes, d).weekday() == 2]
        quarta = min(quartas, key=lambda d: abs(d.day - 15))
        return proximo_dia_util(quarta)
    return proximo_dia_util(dt.date(ano, mes, 1))


def ultimo_dia_negociacao(ativo, ano, mes):
    ativo = _ativo(ativo)
    v = vencimento(ativo, ano, mes)
    if ativo == "WIN":
        return v
    return dia_util_anterior(v)


def dias_rolagem(ativo):
    return int(config().get("rolagem_dias_uteis", {}).get(ativo, ROLAGEM_PADRAO[ativo]))


def _contrato(ativo, ano, mes):
    ult = ultimo_dia_negociacao(ativo, ano, mes)
    return {
        "codigo": codigo(ativo, ano, mes),
        "ativo": ativo,
        "mes": mes,
        "ano": ano,
        "vencimento": vencimento(ativo, ano, mes).isoformat(),
        "ultimo_dia_negociacao": ult.isoformat(),
        "rolar_em": somar_dias_uteis(ult, -dias_rolagem(ativo)).isoformat(),
    }


def contratos_do_ano(ativo, ano):
    ativo = _ativo(ativo)
    return [_contrato(ativo, ano, m) for m in ESPECIFICACOES[ativo]["meses"]]


def _seguintes(ativo, data):
    """Contratos cujo último dia de negociação é >= data, em ordem."""
    ativo = _ativo(ativo)
    data = _data(data)
    ano = data.year
    out = []
    while len(out) < 3:
        for c in contratos_do_ano(ativo, ano):
            if _data(c["ultimo_dia_negociacao"]) >= data:
                out.append(c)
        ano += 1
    return out[:3]


def vigente(ativo, data):
    """O contrato que ainda negocia mais próximo do vencimento (o 'cheio' de liquidez,
    a não ser que a data já passou do ponto de rolagem)."""
    data = _data(data)
    atual, proximo = _seguintes(ativo, data)[:2]
    du = dias_uteis_entre(data, atual["ultimo_dia_negociacao"])
    rolar = data >= _data(atual["rolar_em"])
    return {
        "data": data.isoformat(),
        "dia_util": eh_dia_util(data),
        "vigente": atual,
        "proximo": proximo,
        "dias_uteis_ate_ultimo_dia": du,
        "rolar_agora": rolar,
        "contrato_liquido": proximo["codigo"] if rolar else atual["codigo"],
        "nota": ("Já passou do ponto de rolagem: a liquidez costuma migrar para %s."
                 % proximo["codigo"]) if rolar else
                ("Rolagem sugerida em %s (%d dias úteis antes do último dia)."
                 % (atual["rolar_em"], dias_rolagem(_ativo(ativo)))),
    }


def contrato_liquido(ativo, data):
    """Código do contrato a usar numa data, já aplicando a regra de rolagem."""
    return vigente(ativo, data)["contrato_liquido"]


# --------------------------------------------------------------- valores

def arredondar_tick(ativo, preco):
    tick = ESPECIFICACOES[_ativo(ativo)]["tick"]
    return round(round(preco / tick) * tick, 4)


def valor_pontos(ativo, pontos, contratos=1):
    ativo = _ativo(ativo)
    esp = ESPECIFICACOES[ativo]
    reais = pontos * esp["valor_ponto"] * contratos
    return {
        "ativo": ativo,
        "pontos": pontos,
        "contratos": contratos,
        "ticks": round(pontos / esp["tick"], 4),
        "valor_ponto": esp["valor_ponto"],
        "valor_tick": round(esp["tick"] * esp["valor_ponto"], 2),
        "resultado_reais": round(reais, 2),
    }


def valor_operacao(ativo, de, para, lado="compra", contratos=1):
    lado = lado.lower()
    if lado not in ("compra", "venda"):
        raise ValueError("lado deve ser compra ou venda")
    pontos = (para - de) if lado == "compra" else (de - para)
    r = valor_pontos(ativo, round(pontos, 4), contratos)
    r.update({"lado": lado, "entrada": de, "saida": para})
    return r


# ------------------------------------------------------------------- CLI

def _imprimir(obj, como_json, texto):
    if como_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(texto)


def _brl(v):
    s = "{:,.2f}".format(abs(v)).replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def cmd_info(a):
    ativo = _ativo(a.ativo)
    esp = dict(ESPECIFICACOES[ativo])
    esp["ativo"] = ativo
    esp["valor_tick"] = round(esp["tick"] * esp["valor_ponto"], 2)
    esp["horarios"] = config().get("horarios", {}).get(ativo) or HORARIOS_PADRAO[ativo]
    esp["rolagem_dias_uteis"] = dias_rolagem(ativo)
    meses = ", ".join("%s (%s)" % (MESES_LETRA[m], m) for m in esp["meses"])
    h = esp["horarios"][-1]
    txt = "\n".join([
        "%s  %s" % (ativo, esp["nome"]),
        "  objeto:        %s" % esp["objeto"],
        "  valor do ponto: %s por contrato" % _brl(esp["valor_ponto"]),
        "  tick:          %s pontos = %s" % (esp["tick"], _brl(esp["valor_tick"])),
        "  vencimentos:   %s" % meses,
        "  regra:         %s" % esp["regra_vencimento"],
        "  último dia:    %s" % esp["ultimo_dia"],
        "  horário:       %s às %s (desde %s, Brasília)" % (h["abertura"], h["fechamento"], h["desde"]),
        "  rolagem:       %d dias úteis antes do último dia" % esp["rolagem_dias_uteis"],
    ])
    _imprimir(esp, a.json, txt)


def cmd_vigente(a):
    r = vigente(a.ativo, a.data or dt.datetime.now(BRT).date())
    v, p = r["vigente"], r["proximo"]
    txt = "\n".join([
        "%s em %s%s" % (_ativo(a.ativo), r["data"], "" if r["dia_util"] else " (sem pregão)"),
        "  vigente:  %s  vence %s, último dia %s (%d dias úteis)"
        % (v["codigo"], v["vencimento"], v["ultimo_dia_negociacao"], r["dias_uteis_ate_ultimo_dia"]),
        "  próximo:  %s  vence %s" % (p["codigo"], p["vencimento"]),
        "  use:      %s" % r["contrato_liquido"],
        "  %s" % r["nota"],
    ])
    _imprimir(r, a.json, txt)


def cmd_vencimentos(a):
    lst = contratos_do_ano(a.ativo, a.ano)
    linhas = ["%s %d" % (_ativo(a.ativo), a.ano),
              "  código  vencimento  último dia  rolar em"]
    for c in lst:
        linhas.append("  %s  %s  %s  %s" % (c["codigo"], c["vencimento"],
                                            c["ultimo_dia_negociacao"], c["rolar_em"]))
    _imprimir(lst, a.json, "\n".join(linhas))


def cmd_pregao(a):
    if a.agora:
        agora = dt.datetime.fromisoformat(a.agora)
    else:
        agora = dt.datetime.now(BRT).replace(tzinfo=None)
    ativos = [a.ativo] if a.ativo else ["WIN", "WDO"]
    res = [status_pregao(x, agora) for x in ativos]
    linhas = []
    for r in res:
        if r["aberto"]:
            linhas.append("%s: ABERTO, fecha %s (%d min)" % (r["ativo"], r["fecha_em"][11:],
                                                             r["minutos_para_fechar"]))
        else:
            linhas.append("%s: FECHADO (%s), abre %s" % (r["ativo"], r["motivo"],
                                                         r["proxima_abertura"].replace("T", " ")))
    _imprimir(res if len(res) > 1 else res[0], a.json, "\n".join(linhas))


def cmd_feriados(a):
    fer = feriados(a.ano)
    cinzas = quarta_de_cinzas(a.ano)
    lst = [{"data": d.isoformat(), "nome": n, "origem": o} for d, (n, o) in fer.items()]
    origem = "oficial B3" if a.ano in FERIADOS_OFICIAIS else \
        "calculado: confira quando a B3 publicar o calendário"
    linhas = ["Dias sem pregão em %d (%s)" % (a.ano, origem)]
    linhas += ["  %s  %s" % (x["data"], x["nome"]) for x in lst]
    linhas.append("  %s  Quarta-feira de Cinzas: abre às %s" % (cinzas.isoformat(),
                                                                 config().get("abertura_cinzas", ABERTURA_CINZAS)))
    _imprimir({"ano": a.ano, "sem_pregao": lst,
               "horario_especial": [{"data": cinzas.isoformat(), "abertura": ABERTURA_CINZAS,
                                     "nome": "Quarta-feira de Cinzas"}]}, a.json, "\n".join(linhas))


def cmd_valor(a):
    if a.pontos is not None:
        r = valor_pontos(a.ativo, a.pontos, a.contratos)
        txt = "%s: %s pontos x %d contrato(s) = %s" % (r["ativo"], r["pontos"], r["contratos"],
                                                       _brl(r["resultado_reais"]))
    elif a.de is not None and a.para is not None:
        r = valor_operacao(a.ativo, a.de, a.para, a.lado, a.contratos)
        txt = "%s %s de %s para %s, %d contrato(s): %s pontos = %s" % (
            r["ativo"], r["lado"], r["entrada"], r["saida"], r["contratos"], r["pontos"],
            _brl(r["resultado_reais"]))
    else:
        raise SystemExit("informe --pontos, ou --de e --para")
    _imprimir(r, a.json, txt)


def main(argv=None):
    p = argparse.ArgumentParser(description="Regras dos contratos WIN e WDO da B3.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def novo(nome, fn, ajuda):
        s = sub.add_parser(nome, help=ajuda)
        s.add_argument("--json", action="store_true", help="saída em JSON")
        s.set_defaults(fn=fn)
        return s

    s = novo("info", cmd_info, "especificações do contrato")
    s.add_argument("ativo")
    s = novo("vigente", cmd_vigente, "contrato vigente e rolagem numa data")
    s.add_argument("ativo")
    s.add_argument("--data", help="AAAA-MM-DD (padrão: hoje)")
    s = novo("vencimentos", cmd_vencimentos, "todos os vencimentos de um ano")
    s.add_argument("ativo")
    s.add_argument("--ano", type=int, default=dt.date.today().year)
    s = novo("pregao", cmd_pregao, "o pregão está aberto?")
    s.add_argument("--ativo")
    s.add_argument("--agora", help='"AAAA-MM-DD HH:MM" em horário de Brasília')
    s = novo("feriados", cmd_feriados, "dias sem pregão")
    s.add_argument("--ano", type=int, default=dt.date.today().year)
    s = novo("valor", cmd_valor, "converte pontos em reais")
    s.add_argument("ativo")
    s.add_argument("--pontos", type=float)
    s.add_argument("--de", type=float, help="preço de entrada")
    s.add_argument("--para", type=float, help="preço de saída")
    s.add_argument("--lado", default="compra", choices=["compra", "venda"])
    s.add_argument("--contratos", type=int, default=1)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except ValueError as e:
        print("erro: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
