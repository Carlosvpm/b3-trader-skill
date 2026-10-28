#!/usr/bin/env python3
"""b3-dados: candles de WIN e WDO num formato único, em 1, 5, 15, 30 e 60 minutos.

Só biblioteca padrão. Python 3.8+. Usa as regras de ../b3-contratos/contratos.py
(calendário, horário de pregão, contrato vigente, tick).

Uso:
  python3 dados.py mock WIN --de 2026-08-03 --ate 2026-10-27 --tfs 1,5,15,30,60
  python3 dados.py importar export_mt5.csv --ativo WIN [--formato auto|mt5|profit|padrao]
  python3 dados.py reamostrar b3/dados/WIN_1m.csv --tfs 5,15,30,60
  python3 dados.py validar b3/dados/WIN_5m.csv
  python3 dados.py continua b3/dados/WIN_1m.csv [--metodo diferenca|razao|nenhum]
  python3 dados.py resumo b3/dados/WIN_1m.csv

Formato padrão (CSV, vírgula, ponto decimal, horário de Brasília, hora = início do candle):
  data_hora,ativo,contrato,abertura,maxima,minima,fechamento,volume,fonte
  2026-10-27 09:00,WIN,WINZ26,130125,130210,130090,130180,1834,mock

A coluna `fonte` diz de onde veio o dado. `mock` = FICTÍCIO, só para testar o fluxo.
"""

import argparse
import csv
import datetime as dt
import json
import math
import os
import random
import re
import sys
import unicodedata

_AQUI = os.path.dirname(os.path.abspath(__file__))
_CONTRATOS_DIR = os.environ.get("B3_CONTRATOS_DIR",
                                os.path.join(_AQUI, "..", "b3-contratos"))
sys.path.insert(0, os.path.abspath(_CONTRATOS_DIR))
try:
    import contratos as C  # noqa: E402
except ImportError:  # pragma: no cover
    sys.exit("erro: não achei b3-contratos/contratos.py. Instale as duas skills lado a lado "
             "(ou defina B3_CONTRATOS_DIR).")

COLUNAS = ["data_hora", "ativo", "contrato", "abertura", "maxima", "minima",
           "fechamento", "volume", "fonte"]
TFS_PADRAO = [1, 5, 15, 30, 60]
PASTA_PADRAO = os.path.join("b3", "dados")

# Parâmetros do mock. Os níveis de preço são FICTÍCIOS, não são cotação real.
MOCK = {
    "WIN": {"preco": 130000.0, "vol_dia": 0.012, "premio_rolagem": 0.009, "volume": 1800},
    "WDO": {"preco": 5400.0, "vol_dia": 0.007, "premio_rolagem": 0.0045, "volume": 900},
}


# ------------------------------------------------------------- utilidades

class Candle(object):
    __slots__ = ("data_hora", "ativo", "contrato", "abertura", "maxima", "minima",
                 "fechamento", "volume", "fonte")

    def __init__(self, data_hora, ativo, contrato, abertura, maxima, minima,
                 fechamento, volume, fonte):
        self.data_hora = data_hora
        self.ativo = ativo
        self.contrato = contrato
        self.abertura = abertura
        self.maxima = maxima
        self.minima = minima
        self.fechamento = fechamento
        self.volume = volume
        self.fonte = fonte


def _num(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return ("%.4f" % v).rstrip("0").rstrip(".")


def escrever(caminho, candles):
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUNAS)
        for c in candles:
            w.writerow([c.data_hora.strftime("%Y-%m-%d %H:%M"), c.ativo, c.contrato,
                        _num(c.abertura), _num(c.maxima), _num(c.minima), _num(c.fechamento),
                        int(c.volume), c.fonte])


def ler(caminho):
    """Lê um CSV no formato padrão."""
    out = []
    with open(caminho, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        faltando = [c for c in COLUNAS if c not in (r.fieldnames or [])]
        if faltando:
            raise ValueError("%s não está no formato padrão (faltam: %s). Use `importar` antes."
                             % (caminho, ", ".join(faltando)))
        for i, row in enumerate(r, start=2):
            try:
                out.append(Candle(dt.datetime.strptime(row["data_hora"], "%Y-%m-%d %H:%M"),
                                  row["ativo"], row["contrato"],
                                  float(row["abertura"]), float(row["maxima"]),
                                  float(row["minima"]), float(row["fechamento"]),
                                  float(row["volume"] or 0), row["fonte"]))
            except (ValueError, TypeError) as e:
                raise ValueError("linha %d de %s inválida: %s" % (i, caminho, e))
    return out


def nome_arquivo(ativo, tf, pasta=PASTA_PADRAO, sufixo=""):
    return os.path.join(pasta, "%s_%dm%s.csv" % (ativo, tf, sufixo))


def _tfs(texto):
    tfs = sorted({int(x) for x in str(texto).split(",") if x.strip()})
    for t in tfs:
        if t < 1 or t > 600:
            raise ValueError("tempo gráfico inválido: %d minutos" % t)
    return tfs


def inferir_tf(candles):
    """Menor diferença, em minutos, entre candles do mesmo dia."""
    menor = None
    for a, b in zip(candles, candles[1:]):
        if a.data_hora.date() == b.data_hora.date():
            d = int((b.data_hora - a.data_hora).total_seconds() // 60)
            if d > 0 and (menor is None or d < menor):
                menor = d
    return menor or 1


# ------------------------------------------------------------------ mock

def _forma_u(frac):
    """Volatilidade intradiária em U: alta na abertura e no fechamento."""
    return 0.7 + 1.2 * (2 * frac - 1) ** 2 + (0.8 if frac < 0.03 else 0.0)


def gerar_mock(ativo, de, ate, semente=42, preco=None):
    """Candles de 1 minuto FICTÍCIOS, em dias e horários reais de pregão.

    Passeio aleatório com volatilidade em U ao longo do dia, gap na abertura,
    preço sempre no tick e um salto de prêmio na rolagem de contrato (para que a
    série contínua tenha o que ajustar, como nos dados reais)."""
    ativo = C._ativo(ativo)
    p = MOCK[ativo]
    rnd = random.Random(semente)
    px = float(preco or p["preco"])
    contrato_ant = None
    out = []
    dia = C._data(de)
    fim = C._data(ate)
    while dia <= fim:
        h = C.horario(ativo, dia)
        if h is None:
            dia += dt.timedelta(days=1)
            continue
        contrato = C.contrato_liquido(ativo, dia)
        if contrato_ant and contrato != contrato_ant:
            px *= 1 + p["premio_rolagem"]          # o próximo vencimento negocia com prêmio
        contrato_ant = contrato
        px *= math.exp(rnd.gauss(0, p["vol_dia"] * 0.35))  # gap de abertura
        n = C.minutos_de_pregao(ativo, dia)
        sig = p["vol_dia"] / math.sqrt(max(n, 1))
        inicio = dt.datetime.combine(dia, h[0])
        for i in range(n):
            frac = i / max(n - 1, 1)
            u = _forma_u(frac)
            o = C.arredondar_tick(ativo, px)
            fech = C.arredondar_tick(ativo, o * math.exp(rnd.gauss(0, sig * u)))
            sombra_a = abs(rnd.gauss(0, sig * u * 0.6))
            sombra_b = abs(rnd.gauss(0, sig * u * 0.6))
            maxi = C.arredondar_tick(ativo, max(o, fech) * math.exp(sombra_a))
            mini = C.arredondar_tick(ativo, min(o, fech) * math.exp(-sombra_b))
            maxi = max(maxi, o, fech)
            mini = min(mini, o, fech)
            vol = int(p["volume"] * u * rnd.lognormvariate(0, 0.35)) + 1
            out.append(Candle(inicio + dt.timedelta(minutes=i), ativo, contrato,
                              o, maxi, mini, fech, vol, "mock"))
            px = fech
        dia += dt.timedelta(days=1)
    return out


# ------------------------------------------------------------- reamostrar

def reamostrar(candles, tf):
    """Agrupa candles em `tf` minutos, alinhados à abertura do pregão de cada dia
    (60 min = 09:00, 10:00, ...). O último candle do dia pode ser parcial."""
    if tf == 1:
        return list(candles)
    out = []
    atual, chave = None, None
    for c in candles:
        h = C.horario(c.ativo, c.data_hora.date())
        abertura = dt.datetime.combine(c.data_hora.date(), h[0] if h else dt.time(0, 0))
        k = int((c.data_hora - abertura).total_seconds() // 60) // tf
        nova = (c.data_hora.date(), k)
        if nova != chave:
            if atual:
                out.append(atual)
            chave = nova
            atual = Candle(abertura + dt.timedelta(minutes=k * tf), c.ativo, c.contrato,
                           c.abertura, c.maxima, c.minima, c.fechamento, c.volume, c.fonte)
        else:
            atual.maxima = max(atual.maxima, c.maxima)
            atual.minima = min(atual.minima, c.minima)
            atual.fechamento = c.fechamento
            atual.volume += c.volume
    if atual:
        out.append(atual)
    return out


# ----------------------------------------------------------------- validar

def validar(candles, tf=None, cobertura_min=0.95):
    """Lista de problemas: (nivel, mensagem). nivel: erro | aviso | info."""
    probs = []
    if not candles:
        return [("erro", "arquivo vazio")]
    tf = tf or inferir_tf(candles)
    ativo = candles[0].ativo
    try:
        C._ativo(ativo)
    except ValueError as e:
        return [("erro", str(e))]
    if any(c.fonte == "mock" for c in candles):
        probs.append(("info", "dados FICTÍCIOS (fonte=mock): servem para testar o fluxo, "
                              "não para tirar conclusão sobre estratégia"))
    tick = C.ESPECIFICACOES[ativo]["tick"]
    vistos = set()
    por_dia = {}
    contrato_errado = {}
    ant = None
    for c in candles:
        t = c.data_hora.strftime("%Y-%m-%d %H:%M")
        if c.ativo != ativo:
            probs.append(("erro", "%s: ativo %s misturado com %s" % (t, c.ativo, ativo)))
        if c.data_hora in vistos:
            probs.append(("erro", "%s: candle duplicado" % t))
        vistos.add(c.data_hora)
        if ant and c.data_hora < ant.data_hora:
            probs.append(("erro", "%s: fora de ordem (vem depois de %s)"
                          % (t, ant.data_hora.strftime("%Y-%m-%d %H:%M"))))
        if min(c.abertura, c.maxima, c.minima, c.fechamento) <= 0:
            probs.append(("erro", "%s: preço zero ou negativo" % t))
        if c.maxima < max(c.abertura, c.fechamento, c.minima) or \
                c.minima > min(c.abertura, c.fechamento, c.maxima):
            probs.append(("erro", "%s: OHLC incoerente (máx %s, mín %s, abert %s, fech %s)"
                          % (t, _num(c.maxima), _num(c.minima), _num(c.abertura),
                             _num(c.fechamento))))
        for nome in ("abertura", "maxima", "minima", "fechamento"):
            v = getattr(c, nome)
            if abs(v / tick - round(v / tick)) > 1e-6:
                probs.append(("aviso", "%s: %s %s fora do tick de %s (série ajustada?)"
                              % (t, nome, _num(v), tick)))
                break
        dia = c.data_hora.date()
        h = C.horario(ativo, dia)
        if h is None:
            probs.append(("erro", "%s: candle em dia sem pregão" % t))
        else:
            abre = dt.datetime.combine(dia, h[0])
            fecha = dt.datetime.combine(dia, h[1])
            if not (abre <= c.data_hora < fecha):
                probs.append(("aviso", "%s: fora do horário de negociação (%s às %s). "
                                       "Confira os horários em b3/config.json"
                              % (t, h[0].strftime("%H:%M"), h[1].strftime("%H:%M"))))
            por_dia[dia] = por_dia.get(dia, 0) + 1
        esperado = C.contrato_liquido(ativo, dia)
        if c.contrato != esperado and c.contrato not in ("", ativo + "$", ativo + "$N"):
            contrato_errado.setdefault(dia, (c.contrato, esperado))
        if ant and ant.data_hora.date() == dia and ant.contrato == c.contrato:
            salto = abs(c.abertura / ant.fechamento - 1)
            limite = 0.01 * math.sqrt(tf)
            if salto > limite:
                probs.append(("aviso", "%s: salto de %.2f%% entre candles" % (t, salto * 100)))
        ant = c
    for dia, n in sorted(por_dia.items()):
        esperado = math.ceil(C.minutos_de_pregao(ativo, dia) / float(tf))
        if esperado and n < esperado * cobertura_min:
            probs.append(("aviso", "%s: %d de %d candles de %d min (faltam %d)"
                          % (dia, n, esperado, tf, esperado - n)))
    for dia, (tem, esp) in sorted(contrato_errado.items())[:10]:
        probs.append(("aviso", "%s: contrato %s, a regra de rolagem indicaria %s"
                      % (dia, tem, esp)))
    if len(contrato_errado) > 10:
        probs.append(("aviso", "... e mais %d dias com contrato diferente da regra"
                      % (len(contrato_errado) - 10)))
    return probs


# ----------------------------------------------------------------- contínua

def rolagens(candles):
    """Índices i onde candles[i] é o primeiro candle de um contrato novo."""
    return [i for i in range(1, len(candles))
            if candles[i].contrato != candles[i - 1].contrato]


def serie_continua(candles, metodo="diferenca"):
    """Série contínua com ajuste para trás: o trecho atual fica com preço real e o
    passado é deslocado pelo salto de cada rolagem.

    Aproximação: com um único arquivo, o salto medido na rolagem inclui o gap da
    noite. Se a plataforma oferece a série contínua pronta (ex.: WIN$N no MT5 ou
    no Profit), prefira importá-la."""
    if metodo not in ("diferenca", "razao", "nenhum"):
        raise ValueError("método deve ser diferenca, razao ou nenhum")
    out = [Candle(c.data_hora, c.ativo, c.contrato, c.abertura, c.maxima, c.minima,
                  c.fechamento, c.volume, c.fonte) for c in candles]
    ajustes = []
    if metodo == "nenhum":
        return out, ajustes
    for i in reversed(rolagens(out)):
        velho, novo = out[i - 1], out[i]
        if metodo == "diferenca":
            gap = novo.abertura - velho.fechamento
            for c in out[:i]:
                c.abertura += gap
                c.maxima += gap
                c.minima += gap
                c.fechamento += gap
            ajustes.append({"data_hora": novo.data_hora.strftime("%Y-%m-%d %H:%M"),
                            "de": velho.contrato, "para": novo.contrato,
                            "ajuste_pontos": round(gap, 4)})
        else:
            fator = novo.abertura / velho.fechamento
            for c in out[:i]:
                c.abertura *= fator
                c.maxima *= fator
                c.minima *= fator
                c.fechamento *= fator
            ajustes.append({"data_hora": novo.data_hora.strftime("%Y-%m-%d %H:%M"),
                            "de": velho.contrato, "para": novo.contrato,
                            "fator": round(fator, 6)})
    for c in out:
        c.abertura, c.maxima = round(c.abertura, 4), round(c.maxima, 4)
        c.minima, c.fechamento = round(c.minima, 4), round(c.fechamento, 4)
    return out, list(reversed(ajustes))


# ----------------------------------------------------------------- importar

def _sem_acento(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip().strip("<>")


SINONIMOS = {
    "data": ["date", "data", "dia"],
    "hora": ["time", "hora", "horario"],
    "data_hora": ["datetime", "data_hora", "data/hora", "timestamp", "data hora"],
    "abertura": ["open", "abertura", "abert"],
    "maxima": ["high", "maxima", "maximo", "max"],
    "minima": ["low", "minima", "minimo", "min"],
    "fechamento": ["close", "fechamento", "fech", "ultimo"],
    "volume": ["vol", "volume", "quantidade", "tickvol", "qtd", "negocios"],
    "contrato": ["ativo", "symbol", "ticker", "contrato", "papel", "codigo"],
}


def _mapear(cabecalho):
    norm = [_sem_acento(c) for c in cabecalho]
    m = {}
    for alvo, nomes in SINONIMOS.items():
        for nome in nomes:
            if nome in norm and alvo not in m:
                idx = norm.index(nome)
                if idx not in m.values():
                    m[alvo] = idx
                    break
    # MT5 tem TICKVOL e VOL; o Profit tem Volume (financeiro) e Quantidade.
    # Prefira a quantidade de contratos.
    for preferida in ("vol", "quantidade", "qtd"):
        if preferida in norm:
            m["volume"] = norm.index(preferida)
            break
    return m


def _numero(texto, virgula_decimal):
    t = texto.strip().replace(" ", "")
    if not t:
        return 0.0
    if virgula_decimal:
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", "")
    return float(t)


def _data_hora(texto_data, texto_hora):
    d = texto_data.strip()
    h = (texto_hora or "").strip()
    if " " in d and not h:
        d, h = d.split(" ", 1)
    if "T" in d and not h:
        d, h = d.split("T", 1)
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            data = dt.datetime.strptime(d, fmt).date()
            break
        except ValueError:
            continue
    else:
        raise ValueError("data não reconhecida: %r" % texto_data)
    h = h[:8] if h else "00:00"
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            hora = dt.datetime.strptime(h, fmt).time()
            break
        except ValueError:
            continue
    else:
        raise ValueError("hora não reconhecida: %r" % texto_hora)
    return dt.datetime.combine(data, hora.replace(second=0))


PROFIT_SEM_CABECALHO = ["Ativo", "Data", "Hora", "Abertura", "Máximo", "Mínimo", "Fechamento",
                        "Volume", "Quantidade"]


def detectar_formato(linhas):
    cab = linhas[0]
    if cab.startswith("<DATE>") or "<OPEN>" in cab:
        return "mt5"
    if all(c in cab for c in COLUNAS[:8]):
        return "padrao"
    if ";" in cab:
        return "profit"
    return "generico"


def importar(caminho, ativo, formato="auto", fonte=None):
    """Lê exportações do MetaTrader 5, do Profit ou CSV genérico e devolve candles
    no formato padrão. O contrato vem do arquivo quando há coluna de ativo com
    código completo (WINZ26); senão é inferido pela regra de rolagem."""
    ativo = C._ativo(ativo)
    with open(caminho, encoding="utf-8-sig", errors="replace") as f:
        texto = f.read()
    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        raise ValueError("arquivo vazio")
    if formato == "auto":
        formato = detectar_formato(linhas)
    if formato == "padrao":
        return ler(caminho)
    delim = "\t" if "\t" in linhas[0] else (";" if ";" in linhas[0] else ",")
    virgula = formato == "profit" or delim == ";"
    rows = list(csv.reader(linhas, delimiter=delim))
    if formato == "profit" and len(rows[0]) > 2 and re.fullmatch(r"\d{2}/\d{2}/\d{4}", rows[0][1].strip()):
        # "Exportar Dados Históricos" do Profit sai sem cabeçalho e do mais novo para o mais antigo
        rows.insert(0, PROFIT_SEM_CABECALHO[:len(rows[0])])
    cab, dados = rows[0], rows[1:]
    m = _mapear(cab)
    if "data_hora" not in m and "data" not in m:
        raise ValueError("não achei coluna de data no cabeçalho: %s" % cab)
    for k in ("abertura", "maxima", "minima", "fechamento"):
        if k not in m:
            raise ValueError("não achei a coluna %s no cabeçalho: %s" % (k, cab))
    fonte = fonte or formato
    out = []
    for n, r in enumerate(dados, start=2):
        if len(r) < len(cab) - 1:
            continue
        try:
            if "data_hora" in m:
                quando = _data_hora(r[m["data_hora"]], None)
            else:
                quando = _data_hora(r[m["data"]], r[m["hora"]] if "hora" in m else None)
            o, h, l, c = (_numero(r[m[k]], virgula)
                          for k in ("abertura", "maxima", "minima", "fechamento"))
            v = _numero(r[m["volume"]], virgula) if "volume" in m else 0.0
        except (ValueError, IndexError) as e:
            raise ValueError("linha %d: %s" % (n, e))
        contrato = r[m["contrato"]].strip().upper() if "contrato" in m else ""
        try:
            C.ler_codigo(contrato)
        except ValueError:
            contrato = C.contrato_liquido(ativo, quando.date())
        out.append(Candle(quando, ativo, contrato, o, h, l, c, v, fonte))
    out.sort(key=lambda x: x.data_hora)
    return out


# --------------------------------------------------------------------- CLI

def _imprimir_problemas(probs, como_json, arquivo):
    erros = sum(1 for p in probs if p[0] == "erro")
    avisos = sum(1 for p in probs if p[0] == "aviso")
    if como_json:
        print(json.dumps({"arquivo": arquivo, "erros": erros, "avisos": avisos,
                          "problemas": [{"nivel": n, "mensagem": m} for n, m in probs]},
                         ensure_ascii=False, indent=2))
    else:
        status = "OK" if not erros else "COM ERROS"
        print("%s: %s (%d erros, %d avisos)" % (arquivo, status, erros, avisos))
        for n, msg in probs[:40]:
            print("  [%s] %s" % (n, msg))
        if len(probs) > 40:
            print("  ... e mais %d" % (len(probs) - 40))
    return 1 if erros else 0


def resumo(candles, arquivo=""):
    if not candles:
        return {"arquivo": arquivo, "candles": 0}
    dias = sorted({c.data_hora.date() for c in candles})
    contratos = []
    for c in candles:
        if not contratos or contratos[-1] != c.contrato:
            contratos.append(c.contrato)
    return {
        "arquivo": arquivo,
        "ativo": candles[0].ativo,
        "candles": len(candles),
        "tempo_grafico_min": inferir_tf(candles),
        "de": candles[0].data_hora.strftime("%Y-%m-%d %H:%M"),
        "ate": candles[-1].data_hora.strftime("%Y-%m-%d %H:%M"),
        "pregoes": len(dias),
        "contratos": contratos,
        "rolagens": len(rolagens(candles)),
        "primeiro_preco": candles[0].abertura,
        "ultimo_preco": candles[-1].fechamento,
        "maxima": max(c.maxima for c in candles),
        "minima": min(c.minima for c in candles),
        "fontes": sorted({c.fonte for c in candles}),
        "ficticio": any(c.fonte == "mock" for c in candles),
    }


def _gravar_tfs(candles_1m, ativo, tfs, pasta, sufixo=""):
    base_tf = inferir_tf(candles_1m)
    feitos = []
    for tf in tfs:
        if tf % base_tf:
            print("  pulando %dm: não é múltiplo de %dm" % (tf, base_tf), file=sys.stderr)
            continue
        cs = reamostrar(candles_1m, tf) if tf != base_tf else candles_1m
        caminho = nome_arquivo(ativo, tf, pasta, sufixo)
        escrever(caminho, cs)
        feitos.append((tf, caminho, len(cs)))
    return feitos


def cmd_mock(a):
    ativo = C._ativo(a.ativo)
    ate = C._data(a.ate) if a.ate else dt.date.today()
    de = C._data(a.de) if a.de else ate - dt.timedelta(days=90)
    cs = gerar_mock(ativo, de, ate, a.semente, a.preco)
    if not cs:
        raise ValueError("nenhum pregão entre %s e %s" % (de, ate))
    feitos = _gravar_tfs(cs, ativo, _tfs(a.tfs), a.pasta)
    if a.json:
        print(json.dumps({"ativo": ativo, "ficticio": True, "semente": a.semente,
                          "arquivos": [{"tf": t, "arquivo": p, "candles": n} for t, p, n in feitos]},
                         ensure_ascii=False, indent=2))
        return 0
    print("Dados FICTÍCIOS de %s, %s a %s (semente %d):" % (ativo, de, ate, a.semente))
    for t, p, n in feitos:
        print("  %3dm  %6d candles  %s" % (t, n, p))
    return 0


def cmd_importar(a):
    ativo = C._ativo(a.ativo)
    cs = importar(a.arquivo, ativo, a.formato, a.fonte)
    probs = validar(cs)
    feitos = _gravar_tfs(cs, ativo, _tfs(a.tfs) if a.tfs else [inferir_tf(cs)], a.pasta)
    if not a.json:
        print("Importados %d candles de %s (%s):" % (len(cs), a.arquivo, cs[0].fonte if cs else "-"))
        for t, p, n in feitos:
            print("  %3dm  %6d candles  %s" % (t, n, p))
    return _imprimir_problemas(probs, a.json, feitos[0][1] if feitos else a.arquivo)


def cmd_reamostrar(a):
    cs = ler(a.arquivo)
    if not cs:
        raise ValueError("arquivo vazio")
    pasta = a.pasta or os.path.dirname(a.arquivo) or "."
    sufixo = "_continua" if a.arquivo.endswith("_continua.csv") else ""
    feitos = _gravar_tfs(cs, cs[0].ativo, _tfs(a.tfs), pasta, sufixo)
    if a.json:
        print(json.dumps([{"tf": t, "arquivo": p, "candles": n} for t, p, n in feitos],
                         ensure_ascii=False, indent=2))
    else:
        for t, p, n in feitos:
            print("  %3dm  %6d candles  %s" % (t, n, p))
    return 0


def cmd_validar(a):
    cs = ler(a.arquivo)
    return _imprimir_problemas(validar(cs, a.tf), a.json, a.arquivo)


def cmd_continua(a):
    cs = ler(a.arquivo)
    out, ajustes = serie_continua(cs, a.metodo)
    saida = a.saida or a.arquivo.replace(".csv", "_continua.csv")
    escrever(saida, out)
    if a.json:
        print(json.dumps({"arquivo": saida, "metodo": a.metodo, "ajustes": ajustes},
                         ensure_ascii=False, indent=2))
    else:
        print("Série contínua (%s): %s" % (a.metodo, saida))
        for x in ajustes:
            extra = ("%+.1f pontos" % x["ajuste_pontos"]) if "ajuste_pontos" in x \
                else ("fator %.6f" % x["fator"])
            print("  %s  %s -> %s  %s" % (x["data_hora"], x["de"], x["para"], extra))
        if not ajustes:
            print("  nenhuma rolagem no arquivo")
    return 0


def cmd_resumo(a):
    r = resumo(ler(a.arquivo), a.arquivo)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0
    print("%s%s" % (a.arquivo, "  [FICTÍCIO]" if r.get("ficticio") else ""))
    for k in ("ativo", "candles", "tempo_grafico_min", "de", "ate", "pregoes", "rolagens",
              "primeiro_preco", "ultimo_preco", "maxima", "minima"):
        print("  %-18s %s" % (k, r.get(k)))
    print("  %-18s %s" % ("contratos", " -> ".join(r.get("contratos", []))))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Candles de WIN e WDO num formato único.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def novo(nome, fn, ajuda):
        s = sub.add_parser(nome, help=ajuda)
        s.add_argument("--json", action="store_true")
        s.set_defaults(fn=fn)
        return s

    s = novo("mock", cmd_mock, "gera candles FICTÍCIOS em dias e horários reais de pregão")
    s.add_argument("ativo")
    s.add_argument("--de")
    s.add_argument("--ate")
    s.add_argument("--tfs", default="1,5,15,30,60")
    s.add_argument("--semente", type=int, default=42)
    s.add_argument("--preco", type=float, help="preço inicial (fictício)")
    s.add_argument("--pasta", default=PASTA_PADRAO)

    s = novo("importar", cmd_importar, "converte exportação do MT5/Profit/CSV para o formato padrão")
    s.add_argument("arquivo")
    s.add_argument("--ativo", required=True)
    s.add_argument("--formato", default="auto", choices=["auto", "mt5", "profit", "padrao", "generico"])
    s.add_argument("--tfs", help="também gerar estes tempos gráficos, ex.: 5,15,30,60")
    s.add_argument("--fonte", help="rótulo da origem (padrão: o formato)")
    s.add_argument("--pasta", default=PASTA_PADRAO)

    s = novo("reamostrar", cmd_reamostrar, "gera 5, 15, 30, 60 min a partir de 1 min")
    s.add_argument("arquivo")
    s.add_argument("--tfs", default="5,15,30,60")
    s.add_argument("--pasta")

    s = novo("validar", cmd_validar, "checa buracos, OHLC, tick, horário e contrato")
    s.add_argument("arquivo")
    s.add_argument("--tf", type=int)

    s = novo("continua", cmd_continua, "série contínua ajustada nas rolagens")
    s.add_argument("arquivo")
    s.add_argument("--metodo", default="diferenca", choices=["diferenca", "razao", "nenhum"])
    s.add_argument("--saida")

    s = novo("resumo", cmd_resumo, "período, contratos, preços")
    s.add_argument("arquivo")

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, OSError) as e:
        print("erro: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
