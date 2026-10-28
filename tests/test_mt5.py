"""mt5.py sem o MetaTrader: só as funções puras (o pacote MetaTrader5 é só Windows)."""

import datetime as dt
import unittest

from _load import load

M = load("b3-dados", "mt5")


def rate(hhmm, o, h, l, c, real=10, tick=3):
    quando = dt.datetime(2026, 10, 28, int(hhmm[:2]), int(hhmm[3:]))
    epoch = int((quando - dt.datetime(1970, 1, 1)).total_seconds())
    return {"time": epoch, "open": o, "high": h, "low": l, "close": c,
            "tick_volume": tick, "spread": 5, "real_volume": real}


class MT5(unittest.TestCase):
    def setUp(self):
        M.C.definir_config({})

    def test_simbolo_do_dia(self):
        self.assertEqual(M.simbolo_do_dia("WIN", dt.date(2026, 10, 28)), "WINZ26")
        self.assertEqual(M.simbolo_do_dia("WDO", dt.date(2026, 10, 28)), "WDOZ26")
        self.assertEqual(M.simbolo_do_dia("WIN", dt.date(2026, 10, 28), "win$n"), "WIN$N")

    def test_rates_para_candles(self):
        cs = M.rates_para_candles([rate("09:00", 130000, 130050, 129995, 130020)], "WIN", "WINZ26")
        self.assertEqual(cs[0].data_hora, dt.datetime(2026, 10, 28, 9, 0))
        self.assertEqual(cs[0].volume, 10)
        self.assertEqual(cs[0].fonte, "mt5")
        sem_real = M.rates_para_candles([rate("09:00", 1, 1, 1, 1, real=0, tick=7)], "WIN", "WINZ26")
        self.assertEqual(sem_real[0].volume, 7)
        fuso = M.rates_para_candles([rate("12:00", 1, 1, 1, 1)], "WIN", "WINZ26", fuso_servidor=-3)
        self.assertEqual(fuso[0].data_hora.hour, 9)

    def test_ao_vivo_so_grava_fechados(self):
        rates = [rate("10:00", 1, 1, 1, 1), rate("10:01", 2, 2, 2, 2), rate("10:02", 3, 3, 3, 3)]
        cs = M.rates_para_candles(rates, "WIN", "WINZ26")
        fechados, formando = M.separar_fechados(cs, dt.datetime(2026, 10, 28, 10, 2, 40))
        self.assertEqual([c.data_hora.minute for c in fechados], [0, 1])
        self.assertEqual(formando.data_hora.minute, 2)

    def test_mesclar_atualiza_sem_duplicar(self):
        a = M.rates_para_candles([rate("10:00", 1, 1, 1, 1), rate("10:01", 2, 2, 2, 2)], "WIN", "X")
        b = M.rates_para_candles([rate("10:01", 9, 9, 9, 9), rate("10:02", 3, 3, 3, 3)], "WIN", "X")
        m = M.mesclar(a, b)
        self.assertEqual([c.abertura for c in m], [1, 9, 3])


if __name__ == "__main__":
    unittest.main()
