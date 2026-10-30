import contextlib
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import load

SC = load("b3-scanner", "scanner")
S, D, C = SC.S, SC.D, SC.C
DATA = dt.date(2026, 10, 28)


def velas(lista, data=DATA, tf=5, ativo="WIN"):
    """Candles de `tf` min a partir da abertura, de uma lista (o, h, l, c)."""
    t = dt.datetime.combine(data, C.horario(ativo, data)[0])
    out = []
    for o, h, l, c in lista:
        out.append(D.Candle(t, ativo, C.contrato_liquido(ativo, data), o, h, l, c, 100, "teste"))
        t += dt.timedelta(minutes=tf)
    return out


def plano(n, preco=1000):
    return [(preco, preco + 10, preco - 10, preco)] * n


class Base(unittest.TestCase):
    def setUp(self):
        C.definir_config({})
        self.p = dict(SC.PARAMS)
        self.tmp = tempfile.mkdtemp()
        self.antes = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.antes)
        shutil.rmtree(self.tmp, ignore_errors=True)


class Setups(Base):
    def test_rompimento_dos_dois_lados(self):
        cs = velas(plano(20) + [(1000, 1040, 1000, 1035)])
        h = SC.s_rompimento(cs, 5, self.p)
        self.assertEqual((h[0]["direcao"], h[0]["nivel"]), ("alta", 1010))
        cs = velas(plano(20) + [(1000, 1000, 960, 965)])
        self.assertEqual(SC.s_rompimento(cs, 5, self.p)[0]["direcao"], "baixa")
        cs = velas(plano(20) + [(1000, 1040, 1000, 1005)])   # pavio acima, fechou dentro
        self.assertEqual(SC.s_rompimento(cs, 5, self.p), [])

    def test_retomada_da_media(self):
        cs = velas(plano(20) + [(1000, 1000, 980, 985), (985, 1020, 985, 1015)])
        self.assertEqual(SC.s_retomada_media(cs, 5, self.p)[0]["direcao"], "alta")

    def test_ifr_e_repique(self):
        queda = [(1000 - 10 * k, 1000 - 10 * k, 990 - 10 * k, 990 - 10 * k) for k in range(20)]
        cs = velas(queda)
        self.assertEqual(SC.s_ifr_extremo(cs, 5, self.p)[0]["direcao"], "sobrevendido")
        cs = velas(queda + [(800, 820, 800, 815)])
        self.assertEqual(SC.s_repique(cs, 5, self.p)[0]["direcao"], "alta")

    def test_bandeira(self):
        base = plano(15)
        mastro = [(1000 + 30 * k, 1030 + 30 * k, 995 + 30 * k, 1030 + 30 * k) for k in range(10)]
        bandeira = [(1300, 1310, 1290, 1300)] * 5
        h = SC.s_bandeira(velas(base + mastro + bandeira), 5, self.p)
        self.assertEqual(h[0]["direcao"], "alta")
        # bandeira que devolve mais da metade do mastro não conta
        caiu = [(1300, 1310, 1100, 1120)] + [(1120, 1130, 1110, 1120)] * 4
        self.assertEqual(SC.s_bandeira(velas(base + mastro + caiu), 5, self.p), [])


class Abertura(Base):
    def test_orb_formando_dentro_e_rompeu(self):
        faixa = [(1000, 1020, 990, 1010), (1010, 1030, 1000, 1020), (1020, 1025, 995, 1000)]
        self.assertEqual(SC.orb(velas(faixa[:2]), 5, self.p)["situacao"], "formando")
        self.assertEqual(SC.orb(velas(faixa + plano(3)), 5, self.p)["situacao"], "dentro")
        o = SC.orb(velas(faixa + plano(2) + [(1000, 1045, 1000, 1040)]), 5, self.p)
        self.assertEqual(o["situacao"], "rompeu para cima")
        self.assertEqual(o["hora"], "09:30")
        self.assertEqual(o["plano"]["stop"], 990)
        self.assertEqual((o["pontos"], o["reais"]), (40, 8.0))

    def test_orb_em_1_minuto_confirma_no_fechamento_de_5(self):
        um = velas([(1000, 1030, 990, 1000)] * 15 + [(1000, 1000, 1000, 1000)] * 2 +
                   [(1000, 1040, 1000, 1040)], tf=1)
        # 09:15 a 09:17: o candle de 5 min das 09:15 ainda não fechou
        self.assertEqual(SC.orb(um, 1, self.p)["situacao"], "dentro")
        resto = [D.Candle(dt.datetime(2026, 10, 28, 9, 18 + k), "WIN", um[0].contrato,
                          1040, 1040, 1040, 1040, 1, "teste") for k in range(2)]
        o = SC.orb(um + resto, 1, self.p)
        self.assertEqual((o["situacao"], o["hora"]), ("rompeu para cima", "09:20"))


class Grade(Base):
    def test_tira_candle_em_formacao(self):
        um = velas(plano(7), tf=1)                   # 09:00 a 09:06
        cinco = D.reamostrar(um, 5)
        self.assertEqual(len(cinco), 2)
        fim = um[-1].data_hora + dt.timedelta(minutes=1)
        self.assertEqual(len(SC.fechados(cinco, 5, fim)), 1)

    def test_diario_so_com_dia_completo(self):
        ontem = velas(plano(113), data=dt.date(2026, 10, 27))
        hoje = velas(plano(30))
        d = SC.diario(ontem + hoje, 5)
        self.assertEqual([c.data_hora.date() for c in d], [dt.date(2026, 10, 27)])


class Varredura(Base):
    def test_relogio_fixo_nao_olha_o_futuro(self):
        cs = D.reamostrar(D.gerar_mock("WIN", "2026-09-01", "2026-10-28"), 5)
        agora = dt.datetime(2026, 10, 28, 11, 0)
        a = SC.varrer({"WIN": cs}, [5, 15, SC.DIARIO], agora=agora)
        corte = [c for c in cs if c.data_hora + dt.timedelta(minutes=5) <= agora]
        b = SC.varrer({"WIN": corte}, [5, 15, SC.DIARIO], agora=agora)
        self.assertEqual(a["hits"], b["hits"])
        self.assertTrue(a["ficticio"])
        self.assertTrue(all(v["ultimo"] < "2026-10-28 11:00" for v in a["varridos"]))
        self.assertEqual([v["ultimo"] for v in a["varridos"] if v["tf"] == SC.DIARIO], ["2026-10-27"])

    def test_cli_grava_e_codigo_de_saida(self):
        os.makedirs("b3/dados")
        D.escrever("b3/dados/WIN_5m.csv", velas(plano(40)))
        with contextlib.redirect_stdout(io.StringIO()):
            ret = SC.main(["--ativos", "WIN", "--tfs", "5", "--sem-estrategias",
                           "--agora", "2026-10-28 18:30"])
        self.assertEqual(ret, 1)                     # mercado parado: nada a mostrar
        with open("b3/scanner/varredura.json", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["hits"], [])
        D.escrever("b3/dados/WIN_5m.csv", velas(plano(40) + [(1000, 1040, 1000, 1035)]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ret = SC.main(["--ativos", "WIN", "--tfs", "5", "--setups", "rompimento",
                           "--agora", "2026-10-28 18:30"])
        self.assertEqual(ret, 0)
        self.assertIn("rompimento", out.getvalue())

    def test_erros_claros(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(SC.main(["--ativos", "WIN"]), 2)
            self.assertEqual(SC.main(["--setups", "xyz"]), 2)
            self.assertEqual(SC.main(["-p", "naoexiste=1"]), 2)
        self.assertIn("b3-dados", err.getvalue())

    def test_comando_para_a_timemachine(self):
        h = {"ativo": "WIN", "tf": 5, "plano": {"lado": "compra", "entrada": 1040, "stop": 990,
                                                "rr": 2.0, "data": "2026-10-28", "hora": "09:30"}}
        cmd = SC.comando_timemachine(h, {"WIN": "b3/dados/WIN_1m.csv"})
        self.assertIn("--tf 5 --lado compra --entrada 1040 --stop 990 --rr 2", cmd)
        self.assertIn("--hora 09:30", cmd)


if __name__ == "__main__":
    unittest.main()
