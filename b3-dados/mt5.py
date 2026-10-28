#!/usr/bin/env python3
"""b3-dados / mt5.py: puxa candles do MetaTrader 5 para o formato padrão.

Precisa do terminal MetaTrader 5 aberto e logado na sua corretora, e do pacote
oficial `MetaTrader5` (pip install MetaTrader5). Esse pacote só roda no Windows,
na mesma máquina do terminal. Este script NÃO envia ordens: só lê cotações.

Uso:
  python mt5.py simbolo WIN                       # qual código pedir ao MT5 hoje
  python mt5.py exportar WIN --de 2026-09-01 --ate 2026-10-27 [--simbolo WIN$N]
  python mt5.py ao-vivo WIN [--segundos 2]        # grava candles de 1 min fechados

O ao-vivo escreve:
  b3/dados/WIN_1m_aovivo.csv      candles de 1 min já fechados (formato padrão)
  b3/estado/WIN_ultimo.json       último preço, bid, ask e o candle em formação

Horário: o MT5 devolve o horário do servidor da corretora. Nas corretoras da B3
ele costuma ser o de Brasília. Se não for, use --fuso-servidor (horas a somar).
"""

import argparse
import datetime as dt
import json
import os
import sys
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
import dados as D  # noqa: E402
C = D.C


def _mt5():
    try:
        import MetaTrader5 as mt5  # noqa: N813
    except ImportError:
        sys.exit("erro: pacote MetaTrader5 não instalado. Rode `pip install MetaTrader5` "
                 "no Windows, na máquina onde o terminal MT5 está aberto.")
    if not mt5.initialize():
        erro = mt5.last_error()
        mt5.shutdown()
        sys.exit("erro: não consegui conectar ao terminal MT5 (%s). Ele está aberto e logado?"
                 % (erro,))
    return mt5


def simbolo_do_dia(ativo, data, simbolo=None):
    """Código a pedir ao MT5: o informado, ou o contrato líquido pela regra de rolagem."""
    if simbolo and simbolo.lower() != "auto":
        return simbolo.upper()
    return C.contrato_liquido(ativo, data)


def _campo(r, nome):
    try:
        return r[nome]
    except (KeyError, IndexError, TypeError, ValueError):
        return getattr(r, nome)


def rates_para_candles(rates, ativo, contrato, fonte="mt5", fuso_servidor=0.0):
    """Converte o retorno de copy_rates_* (array numpy estruturado ou lista de dicts
    com time/open/high/low/close/tick_volume/real_volume) em Candles."""
    out = []
    for r in rates:
        quando = dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(_campo(r, "time")),
                                                        hours=fuso_servidor)
        vol = float(_campo(r, "real_volume") or 0) or float(_campo(r, "tick_volume") or 0)
        out.append(D.Candle(quando.replace(second=0, microsecond=0), ativo, contrato,
                            float(_campo(r, "open")), float(_campo(r, "high")),
                            float(_campo(r, "low")), float(_campo(r, "close")), vol, fonte))
    return out


def mesclar(existentes, novos):
    """Junta candles pela data_hora; o mais novo substitui o antigo."""
    por_hora = {c.data_hora: c for c in existentes}
    for c in novos:
        por_hora[c.data_hora] = c
    return [por_hora[k] for k in sorted(por_hora)]


def separar_fechados(candles, agora):
    """(fechados, em_formacao): um candle de 1 min fecha quando o minuto seguinte começa."""
    minuto = agora.replace(second=0, microsecond=0)
    fechados = [c for c in candles if c.data_hora < minuto]
    formando = [c for c in candles if c.data_hora >= minuto]
    return fechados, (formando[-1] if formando else None)


# ------------------------------------------------------------------- comandos

def cmd_simbolo(a):
    data = C._data(a.data) if a.data else dt.date.today()
    v = C.vigente(a.ativo, data)
    print(json.dumps({"ativo": C._ativo(a.ativo), "data": data.isoformat(),
                      "simbolo": v["contrato_liquido"], "nota": v["nota"],
                      "continuo_mt5": C._ativo(a.ativo) + "$N"},
                     ensure_ascii=False, indent=2) if a.json else
          "%s em %s: peça %s ao MT5 (%s)" % (C._ativo(a.ativo), data, v["contrato_liquido"],
                                              v["nota"]))
    return 0


def cmd_exportar(a):
    ativo = C._ativo(a.ativo)
    mt5 = _mt5()
    de, ate = C._data(a.de), C._data(a.ate or dt.date.today())
    todos = []
    try:
        dia = de
        while dia <= ate:
            h = C.horario(ativo, dia)
            if h is None:
                dia += dt.timedelta(days=1)
                continue
            simb = simbolo_do_dia(ativo, dia, a.simbolo)
            mt5.symbol_select(simb, True)
            ini = dt.datetime.combine(dia, dt.time(0, 0)) - dt.timedelta(hours=a.fuso_servidor)
            fim = ini + dt.timedelta(days=1)
            rates = mt5.copy_rates_range(simb, mt5.TIMEFRAME_M1, ini, fim)
            if rates is None or len(rates) == 0:
                print("  %s %s: sem dados no MT5 (%s)" % (dia, simb, mt5.last_error()),
                      file=sys.stderr)
            else:
                contrato = C.contrato_liquido(ativo, dia) if "$" in simb else simb
                todos += rates_para_candles(rates, ativo, contrato, "mt5", a.fuso_servidor)
            dia += dt.timedelta(days=1)
    finally:
        mt5.shutdown()
    if not todos:
        print("erro: nada exportado", file=sys.stderr)
        return 2
    feitos = D._gravar_tfs(todos, ativo, D._tfs(a.tfs), a.pasta)
    for t, p, n in feitos:
        print("  %3dm  %6d candles  %s" % (t, n, p))
    return D._imprimir_problemas(D.validar(todos), False, feitos[0][1])


def cmd_ao_vivo(a):
    ativo = C._ativo(a.ativo)
    mt5 = _mt5()
    arq = os.path.join(a.pasta, "%s_1m_aovivo.csv" % ativo)
    estado = os.path.join("b3", "estado", "%s_ultimo.json" % ativo)
    os.makedirs(os.path.dirname(estado), exist_ok=True)
    gravados = D.ler(arq) if os.path.exists(arq) else []
    print("Ao vivo %s -> %s (Ctrl+C para parar)" % (ativo, arq))
    try:
        while True:
            agora = dt.datetime.now(C.BRT).replace(tzinfo=None)
            simb = simbolo_do_dia(ativo, agora.date(), a.simbolo)
            mt5.symbol_select(simb, True)
            st = C.status_pregao(ativo, agora)
            rates = mt5.copy_rates_from_pos(simb, mt5.TIMEFRAME_M1, 0, 3)
            tick = mt5.symbol_info_tick(simb)
            if rates is not None and len(rates):
                contrato = C.contrato_liquido(ativo, agora.date()) if "$" in simb else simb
                novos = rates_para_candles(rates, ativo, contrato, "mt5", a.fuso_servidor)
                fechados, formando = separar_fechados(novos, agora)
                antes = len(gravados)
                gravados = mesclar(gravados, fechados)
                if len(gravados) != antes or fechados:
                    D.escrever(arq, gravados)
                info = {
                    "ativo": ativo, "simbolo": simb, "atualizado": agora.isoformat(timespec="seconds"),
                    "pregao_aberto": st["aberto"],
                    "ultimo": getattr(tick, "last", None), "bid": getattr(tick, "bid", None),
                    "ask": getattr(tick, "ask", None),
                    "candle_formando": None if formando is None else {
                        "data_hora": formando.data_hora.strftime("%Y-%m-%d %H:%M"),
                        "abertura": formando.abertura, "maxima": formando.maxima,
                        "minima": formando.minima, "fechamento": formando.fechamento,
                        "volume": formando.volume},
                }
                tmp = estado + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(info, f, ensure_ascii=False, indent=2)
                os.replace(tmp, estado)
                if not a.silencioso:
                    print("%s %s último %s bid %s ask %s" % (agora.strftime("%H:%M:%S"), simb,
                                                             info["ultimo"], info["bid"], info["ask"]))
            time.sleep(a.segundos if st["aberto"] else max(a.segundos, 30))
    except KeyboardInterrupt:
        print("Encerrado.")
    finally:
        mt5.shutdown()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Candles do MetaTrader 5 no formato padrão (só leitura).")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simbolo", help="qual código pedir ao MT5")
    s.add_argument("ativo")
    s.add_argument("--data")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_simbolo)

    for nome, fn in (("exportar", cmd_exportar), ("ao-vivo", cmd_ao_vivo)):
        s = sub.add_parser(nome)
        s.add_argument("ativo")
        s.add_argument("--simbolo", default="auto",
                       help="auto (contrato vigente), um código como WINZ26, ou WIN$N")
        s.add_argument("--fuso-servidor", type=float, default=0.0,
                       help="horas a somar ao horário do servidor para chegar em Brasília")
        s.add_argument("--pasta", default=D.PASTA_PADRAO)
        s.set_defaults(fn=fn)
        if nome == "exportar":
            s.add_argument("--de", required=True)
            s.add_argument("--ate")
            s.add_argument("--tfs", default="1,5,15,30,60")
        else:
            s.add_argument("--segundos", type=float, default=2.0)
            s.add_argument("--silencioso", action="store_true")

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
