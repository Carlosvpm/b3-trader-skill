"""Indicadores técnicos, só biblioteca padrão. Cada função recebe a lista de
candles (objetos com abertura, maxima, minima, fechamento, volume, data_hora)
e devolve uma lista do mesmo tamanho, com None onde ainda não há dado.

Usado por sinais.py e pelo gráfico (b3-grafico)."""


def _fech(candles):
    return [c.fechamento for c in candles]


def mms(valores, n):
    """Média móvel simples."""
    out, soma = [], 0.0
    for i, v in enumerate(valores):
        soma += v
        if i >= n:
            soma -= valores[i - n]
        out.append(soma / n if i >= n - 1 else None)
    return out


def mme(valores, n):
    """Média móvel exponencial, semeada pela média simples dos n primeiros."""
    out = [None] * len(valores)
    if len(valores) < n:
        return out
    k = 2.0 / (n + 1)
    atual = sum(valores[:n]) / n
    out[n - 1] = atual
    for i in range(n, len(valores)):
        atual = valores[i] * k + atual * (1 - k)
        out[i] = atual
    return out


def ifr(valores, n=2):
    """Índice de Força Relativa (RSI) de Wilder."""
    out = [None] * len(valores)
    if len(valores) <= n:
        return out
    ganhos = perdas = 0.0
    for i in range(1, n + 1):
        d = valores[i] - valores[i - 1]
        ganhos += max(d, 0)
        perdas += max(-d, 0)
    mg, mp = ganhos / n, perdas / n

    def calc(g, p):
        if p == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / p)

    out[n] = calc(mg, mp)
    for i in range(n + 1, len(valores)):
        d = valores[i] - valores[i - 1]
        mg = (mg * (n - 1) + max(d, 0)) / n
        mp = (mp * (n - 1) + max(-d, 0)) / n
        out[i] = calc(mg, mp)
    return out


def vwap(candles):
    """VWAP intradiária: zera a cada pregão. Preço típico (máx+mín+fech)/3."""
    out, dia, pv, vol = [], None, 0.0, 0.0
    for c in candles:
        d = c.data_hora.date()
        if d != dia:
            dia, pv, vol = d, 0.0, 0.0
        v = c.volume or 1.0
        pv += (c.maxima + c.minima + c.fechamento) / 3.0 * v
        vol += v
        out.append(pv / vol)
    return out


def hilo(candles, n=8):
    """Hi-Lo Activator. Devolve (linha, tendencia): tendência 1 (alta) quando o
    fechamento passa acima da média das máximas dos n candles anteriores, -1
    (baixa) quando passa abaixo da média das mínimas. Em alta a linha é a média
    das mínimas (serve de stop); em baixa, a das máximas."""
    altas = mms([c.maxima for c in candles], n)
    baixas = mms([c.minima for c in candles], n)
    linha, tend = [None] * len(candles), [0] * len(candles)
    t = 0
    for i in range(1, len(candles)):
        ma, mb = altas[i - 1], baixas[i - 1]
        if ma is None:
            continue
        f = candles[i].fechamento
        if f > ma:
            t = 1
        elif f < mb:
            t = -1
        tend[i] = t
        if t == 1:
            linha[i] = baixas[i]
        elif t == -1:
            linha[i] = altas[i]
    return linha, tend


def atr(candles, n=14):
    """Average True Range (média simples dos true ranges)."""
    trs = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c.maxima - c.minima)
        else:
            p = candles[i - 1].fechamento
            trs.append(max(c.maxima - c.minima, abs(c.maxima - p), abs(c.minima - p)))
    return mms(trs, n)


def fechamentos(candles):
    return _fech(candles)
