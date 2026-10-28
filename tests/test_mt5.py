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


class Liquidez(unittest.TestCase):
    def _mt5(self, volumes):
        class Falso(object):
            TIMEFRAME_D1 = 16408

            def symbol_select(self, simb, ligar):
                return True

            def copy_rates_from_pos(self, simb, tf, pos, n):
                return [{"real_volume": volumes.get(simb, 0), "tick_volume": 0}]
        return Falso()

    def test_fica_no_atual_enquanto_ele_tem_mais_volume(self):
        mt5 = self._mt5({"WDOX26": 1192604, "WDOZ26": 17880})
        simb, motivo = M.simbolo_por_liquidez(mt5, "WDO", dt.date(2026, 10, 28))
        self.assertEqual(simb, "WDOX26")
        self.assertIn("liquidez", motivo)

    def test_vira_quando_o_proximo_passa(self):
        mt5 = self._mt5({"WDOX26": 300000, "WDOZ26": 900000})
        self.assertEqual(M.simbolo_por_liquidez(mt5, "WDO", dt.date(2026, 10, 29))[0], "WDOZ26")

    def test_leitura_falhou_nao_troca(self):
        mt5 = self._mt5({"WDOX26": 1192604})            # Z26 sem dado
        simb, motivo = M.simbolo_por_liquidez(mt5, "WDO", dt.date(2026, 10, 28))
        self.assertIsNone(simb)
        self.assertIn("sem volume", motivo)

    def test_longe_do_vencimento_usa_a_regra(self):
        mt5 = self._mt5({})
        self.assertEqual(M.simbolo_por_liquidez(mt5, "WIN", dt.date(2026, 10, 28)),
                         ("WINZ26", "regra"))

    def test_codigo_informado(self):
        self.assertEqual(M.simbolo_por_liquidez(None, "WDO", dt.date(2026, 10, 28), "wdox26")[0], "WDOX26")


class Cotacoes(unittest.TestCase):
    def test_lista_com_rotulo(self):
        self.assertEqual(M.ler_lista("IBOV, WDO$N=DÓLAR,,PETR4"),
                         [("IBOV", "IBOV"), ("WDO$N", "DÓLAR"), ("PETR4", "PETR4")])

    def test_variacao_contra_o_fechamento_anterior(self):
        info = type("I", (), {"session_close": 50.0, "price_change": 9.9, "digits": 2})()
        tick = type("T", (), {"last": 51.0, "bid": 50.9})()
        c = M.cotacao("PETR4", "PETR4", info, tick)
        self.assertAlmostEqual(c["variacao"], 2.0)
        self.assertEqual((c["ultimo"], c["anterior"], c["casas"]), (51.0, 50.0, 2))

    def test_sem_negocio_ainda(self):
        info = type("I", (), {"session_close": 0.0, "price_change": 0.0, "digits": 2})()
        tick = type("T", (), {"last": 0.0, "bid": 0.0})()
        c = M.cotacao("VALE3", "VALE3", info, tick)
        self.assertIsNone(c["ultimo"])
        self.assertIsNone(c["variacao"])


class Recuperar(unittest.TestCase):
    def _gravado(self, hhmm):
        return M.D.Candle(dt.datetime(2026, 10, 28, int(hhmm[:2]), int(hhmm[3:])), "WIN", "WINZ26",
                          1, 1, 1, 1, 1, "mt5")

    def test_normal_pede_3(self):
        self.assertEqual(M.candles_a_pedir([self._gravado("10:00")], dt.datetime(2026, 10, 28, 10, 1, 30)), 3)

    def test_depois_de_queda_pede_o_intervalo(self):
        self.assertEqual(M.candles_a_pedir([self._gravado("16:51")], dt.datetime(2026, 10, 28, 17, 17, 40)), 28)

    def test_outro_dia_ou_vazio(self):
        self.assertEqual(M.candles_a_pedir([], dt.datetime(2026, 10, 28, 9, 0)), 3)
        self.assertEqual(M.candles_a_pedir([self._gravado("18:20")], dt.datetime(2026, 10, 29, 9, 1)), 3)


class Vigia(unittest.TestCase):
    def test_reconecta_depois_de_vazias_seguidas(self):
        v = M.Vigia(3)
        self.assertEqual([v.leitura(False) for _ in range(3)], [False, False, True])
        self.assertFalse(v.leitura(False))   # zera depois de pedir a reconexão

    def test_leitura_boa_zera(self):
        v = M.Vigia(3)
        v.leitura(False), v.leitura(False), v.leitura(True)
        self.assertFalse(v.leitura(False))
        self.assertFalse(v.leitura(False))


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
