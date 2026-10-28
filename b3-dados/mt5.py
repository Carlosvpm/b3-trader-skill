#!/usr/bin/env python3
"""b3-dados / mt5.py: puxa candles do MetaTrader 5 para o formato padrão.

Precisa do terminal MetaTrader 5 aberto e logado na sua corretora. Duas formas:

  Windows: pacote oficial `MetaTrader5` (pip install MetaTrader5), na mesma
           máquina do terminal.
  Linux:   o terminal roda no Wine (instalador oficial da MetaQuotes) com o
           mt5server.exe do projeto mt5linux ligado, e aqui `pip install mt5linux==1.0.11`.
           Escolhido sozinho quando o pacote oficial não existe, ou com --ponte.

Este script NÃO envia ordens: só lê cotações.

Uso:
  python mt5.py simbolo WIN                       # qual código pedir ao MT5 hoje
  python mt5.py exportar WIN --de 2026-09-01 --ate 2026-10-27 [--simbolo WIN$N]
  python mt5.py ao-vivo WIN [--segundos 2]        # grava candles de 1 min fechados
  python mt5.py cotacoes [--simbolos IBOV,WDO$N=DÓLAR,PETR4,VALE3]   # lista de monitoramento

O ao-vivo escreve:
  b3/dados/WIN_1m_aovivo.csv      candles de 1 min já fechados (formato padrão)
  b3/estado/WIN_ultimo.json       último preço, bid, ask e o candle em formação

O cotacoes escreve b3/estado/cotacoes.json (código, último, variação do dia),
que a coluna do painel mostra no lugar das caixas de WIN e WDO.

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


PONTE_HOST = os.environ.get("B3_MT5_HOST", "localhost")
PONTE_PORTA = int(os.environ.get("B3_MT5_PORTA", "18812"))

AJUDA_LINUX = """No Linux:
  1. instale o MT5 pelo script oficial (roda no Wine):
     wget https://download.terminal.free/cdn/web/metaquotes.software.corp/mt5/mt5linux.sh
     chmod +x mt5linux.sh && ./mt5linux.sh
  2. abra o MT5, faça login na sua conta e deixe aberto
  3. baixe o mt5server.exe em github.com/lucas-campagna/mt5linux/releases e rode:
     wine mt5server.exe --host 127.0.0.1 -p 18812
  4. aqui: pip install mt5linux==1.0.11
     (num venv se o pip do sistema recusar; da 1.1 em diante o cliente ignora o
     mt5server.exe e sobe um contêiner Docker por conta própria)"""

PONTE_MAX = (1, 1)  # mt5linux >= 1.1 troca a conexão direta por contêiner Docker


def versao_mt5linux():
    """Versão instalada do mt5linux como tupla, ou None se não der para saber."""
    try:
        from importlib.metadata import version
        return tuple(int(x) for x in version("mt5linux").split(".")[:2])
    except Exception:
        return None


def escolher_modulo(ponte=None, host=None, porta=None, importar=None, versao=versao_mt5linux):
    """Devolve (modulo, origem). origem: 'oficial' ou 'ponte host:porta'.

    ponte=None decide sozinho: o pacote oficial se existir, senão a ponte mt5linux."""
    importar = importar or __import__
    if not ponte:
        try:
            return importar("MetaTrader5"), "oficial"
        except ImportError:
            if ponte is False:
                raise
    try:
        mod = importar("mt5linux")
    except ImportError:
        raise ImportError("nem o pacote MetaTrader5 (Windows) nem o mt5linux (Linux) estão instalados")
    v = versao()
    if v and v >= PONTE_MAX:
        raise ImportError("mt5linux %d.%d instalado; a partir da 1.1 ele sobe um contêiner Docker em vez "
                          "de falar com o mt5server.exe. Use: pip install mt5linux==1.0.11" % v)
    host, porta = host or PONTE_HOST, porta or PONTE_PORTA
    return mod.MetaTrader5(host=host, port=porta), "ponte %s:%d" % (host, porta)


def _mt5(ponte=None, host=None, porta=None):
    try:
        mt5, origem = escolher_modulo(ponte, host, porta)
    except ImportError as e:
        sys.exit("erro: %s.\n\nNo Windows: pip install MetaTrader5\n\n%s" % (e, AJUDA_LINUX))
    except Exception as e:  # a ponte não respondeu
        sys.exit("erro: não consegui falar com o mt5server.exe em %s:%s (%s).\n"
                 "Ele está rodando no Wine?\n\n%s" % (host or PONTE_HOST, porta or PONTE_PORTA, e, AJUDA_LINUX))
    if not mt5.initialize():
        erro = mt5.last_error()
        mt5.shutdown()
        sys.exit("erro: não consegui conectar ao terminal MT5 via %s (%s). Ele está aberto e logado?"
                 % (origem, erro))
    print("conectado ao MT5 (%s)" % origem, file=sys.stderr)
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
    # Array numpy (local ou pela ponte): copia tudo de uma vez com tolist(),
    # em vez de ler campo a campo (pela ponte, cada leitura é uma ida à rede).
    try:
        nomes = list(rates.dtype.names)
        rates = [dict(zip(nomes, linha)) for linha in rates.tolist()]
    except AttributeError:
        pass
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
    mt5 = _mt5(a.ponte, a.host, a.porta)
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
    mt5 = _mt5(a.ponte, a.host, a.porta)
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


MONITOR_PADRAO = ("IBOV,WDO$N=DÓLAR,PETR4,VALE3,ITUB4,BBDC4,BBAS3,B3SA3,ABEV3,"
                  "WEGE3,ELET3,SUZB3,RENT3,PRIO3")


def ler_lista(texto):
    """'IBOV,WDO$N=DÓLAR' -> [('IBOV', 'IBOV'), ('WDO$N', 'DÓLAR')]"""
    itens = []
    for parte in texto.split(","):
        parte = parte.strip()
        if not parte:
            continue
        simb, _, rotulo = parte.partition("=")
        itens.append((simb.strip(), (rotulo or simb).strip()))
    return itens


def cotacao(simbolo, rotulo, info, tick):
    """Uma linha da lista. Variação contra o fechamento anterior (session_close)."""
    ultimo = getattr(tick, "last", 0) or getattr(tick, "bid", 0) or None
    anterior = getattr(info, "session_close", 0) or None
    if ultimo and anterior:
        variacao = (ultimo / anterior - 1) * 100
    else:
        variacao = getattr(info, "price_change", None) if ultimo else None
    return {"codigo": rotulo, "simbolo": simbolo, "ultimo": ultimo, "anterior": anterior,
            "variacao": variacao, "casas": getattr(info, "digits", 2)}


def cmd_cotacoes(a):
    mt5 = _mt5(a.ponte, a.host, a.porta)
    lista = ler_lista(a.simbolos)
    for simb, _ in lista:
        if not mt5.symbol_select(simb, True):
            print("aviso: %s não existe nesta corretora" % simb, file=sys.stderr)
    destino = os.path.join("b3", "estado", "cotacoes.json")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    print("Cotações de %d símbolos -> %s (Ctrl+C para parar)" % (len(lista), destino))
    try:
        while True:
            agora = dt.datetime.now(C.BRT).replace(tzinfo=None)
            itens = []
            for simb, rotulo in lista:
                info = mt5.symbol_info(simb)
                if info is None:
                    continue
                itens.append(cotacao(simb, rotulo, info, mt5.symbol_info_tick(simb)))
            tmp = destino + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"atualizado": agora.isoformat(timespec="seconds"), "itens": itens},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, destino)
            if not a.silencioso:
                print("%s %d cotações" % (agora.strftime("%H:%M:%S"), len(itens)))
            aberto = C.status_pregao("WIN", agora)["aberto"]
            time.sleep(a.segundos if aberto else max(a.segundos, 30))
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
        s.add_argument("--ponte", action="store_const", const=True, default=None,
                       help="Linux: usar a ponte mt5linux mesmo se o pacote oficial existir")
        s.add_argument("--host", help="host do mt5server.exe (padrão: localhost ou B3_MT5_HOST)")
        s.add_argument("--porta", type=int, help="porta do mt5server.exe (padrão: 18812 ou B3_MT5_PORTA)")
        s.set_defaults(fn=fn)
        if nome == "exportar":
            s.add_argument("--de", required=True)
            s.add_argument("--ate")
            s.add_argument("--tfs", default="1,5,15,30,60")
        else:
            s.add_argument("--segundos", type=float, default=2.0)
            s.add_argument("--silencioso", action="store_true")

    s = sub.add_parser("cotacoes", help="lista de monitoramento para o painel")
    s.add_argument("--simbolos", default=MONITOR_PADRAO,
                   help="códigos separados por vírgula; CODIGO=RÓTULO muda o nome mostrado")
    s.add_argument("--segundos", type=float, default=2.0)
    s.add_argument("--silencioso", action="store_true")
    s.add_argument("--ponte", action="store_const", const=True, default=None)
    s.add_argument("--host")
    s.add_argument("--porta", type=int)
    s.set_defaults(fn=cmd_cotacoes)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
