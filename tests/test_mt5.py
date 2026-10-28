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

    def test_array_estruturado(self):
        class Arr(object):           # imita o array numpy que o MT5 devolve
            class dtype(object):
                names = ("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume")

            def __init__(self, linhas):
                self.linhas = linhas

            def tolist(self):
                return self.linhas
        r = rate("09:05", 130000, 130050, 129995, 130020, real=12)
        arr = Arr([tuple(r[k] for k in Arr.dtype.names)])
        cs = M.rates_para_candles(arr, "WIN", "WINZ26")
        self.assertEqual((cs[0].data_hora.minute, cs[0].fechamento, cs[0].volume), (5, 130020, 12))

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


class Ponte(unittest.TestCase):
    def _importar(self, disponiveis):
        class Falso(object):
            def __init__(self, host=None, port=None):
                self.host, self.port = host, port

        def importar(nome):
            if nome not in disponiveis:
                raise ImportError(nome)
            if nome == "mt5linux":
                m = type("m", (), {})()
                m.MetaTrader5 = Falso
                return m
            return "oficial"
        return importar

    def test_prefere_o_oficial(self):
        mod, origem = M.escolher_modulo(importar=self._importar({"MetaTrader5", "mt5linux"}))
        self.assertEqual((mod, origem), ("oficial", "oficial"))

    def test_linux_cai_na_ponte(self):
        mod, origem = M.escolher_modulo(importar=self._importar({"mt5linux"}))
        self.assertEqual(origem, "ponte localhost:18812")
        self.assertEqual((mod.host, mod.port), ("localhost", 18812))

    def test_ponte_forcada_com_host(self):
        mod, origem = M.escolher_modulo(True, "192.168.0.10", 9000,
                                        importar=self._importar({"MetaTrader5", "mt5linux"}))
        self.assertEqual(origem, "ponte 192.168.0.10:9000")

    def test_nenhum_instalado(self):
        with self.assertRaises(ImportError):
            M.escolher_modulo(importar=self._importar(set()))

    def test_recusa_mt5linux_com_docker(self):
        with self.assertRaises(ImportError) as e:
            M.escolher_modulo(importar=self._importar({"mt5linux"}), versao=lambda: (1, 1))
        self.assertIn("1.0.11", str(e.exception))

    def test_aceita_mt5linux_1_0(self):
        mod, origem = M.escolher_modulo(importar=self._importar({"mt5linux"}), versao=lambda: (1, 0))
        self.assertEqual(origem, "ponte localhost:18812")


if __name__ == "__main__":
    unittest.main()
