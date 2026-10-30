import contextlib
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import load

TM = load("b3-timemachine", "timemachine")
S, D, C = TM.S, TM.D, TM.C


def pregao(data, passo, ativo="WIN", inicio=100000.0, tf=5):
    """Um pregão completo de `tf` min: cada candle anda `passo` (fração) do anterior."""
    h = C.horario(ativo, data)
    t, fim = dt.datetime.combine(data, h[0]), dt.datetime.combine(data, h[1])
    px, out = inicio, []
    while t < fim:
        o, c = px, px * (1 + passo)
        out.append(D.Candle(t, ativo, C.contrato_liquido(ativo, data), o, max(o, c), min(o, c), c,
                            100, "teste"))
        px, t = c, t + dt.timedelta(minutes=tf)
    return out


def pregoes(n, passo, ativo="WIN", ate=dt.date(2026, 10, 29)):
    dias, d = [], ate
    while len(dias) < n:
        d -= dt.timedelta(days=1)
        if C.horario(ativo, d) and d != C.quarta_de_cinzas(d.year):
            dias.append(d)
    out = []
    for d in sorted(dias):
        out += pregao(d, passo, ativo)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        C.definir_config({})
        self.tmp = tempfile.mkdtemp()
        self.antes = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.antes)
        shutil.rmtree(self.tmp, ignore_errors=True)


class Plano(Base):
    def test_rr_padrao_e_tick(self):
        p = TM.montar_plano("WIN", "compra", 130000, stop_pontos=302)
        self.assertEqual(p["stop"], 129700)        # 129698 vai para o tick de 5
        self.assertEqual(p["alvo"], 130600)        # 2 x 300
        self.assertEqual(p["rr"], 2.0)
        v = TM.montar_plano("WDO", "venda", 5400, stop_pontos=8, alvo_pontos=12)
        self.assertEqual((v["stop"], v["alvo"], v["rr"]), (5408, 5388, 1.5))

    def test_stop_e_alvo_do_lado_errado(self):
        with self.assertRaises(ValueError):
            TM.montar_plano("WIN", "compra", 130000, stop=130100)
        with self.assertRaises(ValueError):
            TM.montar_plano("WIN", "venda", 130000, stop=130300, alvo=130100 + 500)
        with self.assertRaises(ValueError):
            TM.montar_plano("WIN", None, 130000, stop=129000)

    def test_caminhar_stop_antes_do_alvo(self):
        r = TM.caminhar([(100, 101, 99, 100), (100, 120, 80, 100)], "compra", 100, 90, 110)
        self.assertEqual(r[:2], ("stop", 90))
        # gap abaixo do stop: sai na abertura, pior que o stop
        r = TM.caminhar([(100, 101, 99, 100), (85, 86, 84, 85)], "compra", 100, 90, 110)
        self.assertEqual(r[:2], ("stop", 85))
        r = TM.caminhar([(100, 101, 99, 100), (100, 102, 99, 101)], "venda", 100, 105, 95)
        self.assertEqual(r[0], "nenhum")


class Pregoes(Base):
    def test_descarta_dia_com_buraco(self):
        cs = pregao(dt.date(2026, 10, 27), 0.0) + pregao(dt.date(2026, 10, 28), 0.0)
        del cs[-10]
        ok, fora = TM.separar_pregoes(cs, 5)
        self.assertEqual([d for d, _ in ok], [dt.date(2026, 10, 27)])
        self.assertEqual(fora, [dt.date(2026, 10, 28)])
        self.assertEqual(len(ok[0][1]), 113)        # 09:00 a 18:25 em 5 min

    def test_razoes_ignoram_o_gap_da_noite(self):
        p = pregao(dt.date(2026, 10, 27), 0.001)
        rz = TM.razoes(p)
        self.assertEqual(rz[0][0][0], 1.0)
        self.assertAlmostEqual(rz[5][0][3], 1.001)


class Simulacao(Base):
    def test_mercado_que_so_sobe(self):
        cs = pregoes(25, 0.0005)
        plano = TM.montar_plano("WIN", "compra", 100000, stop_pontos=200, rr=2)
        r = TM.simular(cs, plano, dt.date(2026, 10, 29), dt.time(10, 0), sessoes=500)
        self.assertEqual(r["odds"]["alvo"], 100.0)
        self.assertEqual(r["odds"]["verde"], 100.0)
        self.assertGreaterEqual(r["r_medio"], 2.0)
        self.assertEqual(r["historico"]["alvo"], 25)
        venda = TM.montar_plano("WIN", "venda", 100000, stop_pontos=200, rr=2)
        r = TM.simular(cs, venda, dt.date(2026, 10, 29), dt.time(10, 0), sessoes=500)
        self.assertEqual(r["odds"]["stop"], 100.0)
        self.assertIn("contra", r["veredito"]["texto"])

    def test_mercado_parado(self):
        cs = pregoes(25, 0.0)
        plano = TM.montar_plano("WIN", "compra", 100000, stop_pontos=200)
        r = TM.simular(cs, plano, dt.date(2026, 10, 29), dt.time(10, 0), sessoes=200)
        self.assertEqual(r["odds"]["nenhum"], 100.0)
        self.assertEqual(r["r_medio"], 0.0)

    def test_nao_usa_o_dia_do_plano_nem_depois(self):
        cs = pregoes(30, 0.0) + pregao(dt.date(2026, 10, 29), 0.01) + pregao(dt.date(2026, 10, 30), 0.01)
        plano = TM.montar_plano("WIN", "compra", 100000, stop_pontos=200)
        r = TM.simular(cs, plano, dt.date(2026, 10, 29), dt.time(10, 0), sessoes=200, dias=60)
        self.assertLess(r["pregoes_ate"], "2026-10-29")
        self.assertEqual(r["odds"]["nenhum"], 100.0)   # os dias que sobem ficaram de fora

    def test_mesma_semente_mesmo_resultado(self):
        cs = D.reamostrar(D.gerar_mock("WDO", "2026-08-03", "2026-09-30"), 5)
        plano = TM.montar_plano("WDO", "compra", cs[-1].fechamento, stop_pontos=8)
        a = TM.simular(cs, plano, dt.date(2026, 9, 30), dt.time(11, 0), sessoes=800)
        b = TM.simular(cs, plano, dt.date(2026, 9, 30), dt.time(11, 0), sessoes=800)
        self.assertEqual(a["odds"], b["odds"])
        self.assertAlmostEqual(sum(a["odds"][k] for k in ("alvo", "stop", "nenhum")), 100.0, 0)
        self.assertTrue(a["ficticio"])
        self.assertEqual(a["leque"][0]["hora"], "11:00")
        self.assertEqual(a["leque"][-1]["hora"], "17:50")

    def test_poucos_pregoes(self):
        cs = pregoes(5, 0.0)
        plano = TM.montar_plano("WIN", "compra", 100000, stop_pontos=200)
        with self.assertRaises(ValueError):
            TM.simular(cs, plano, dt.date(2026, 10, 29), dt.time(10, 0))

    def test_entrada_depois_de_zerar(self):
        cs = pregoes(25, 0.0)
        plano = TM.montar_plano("WIN", "compra", 100000, stop_pontos=200)
        with self.assertRaises(ValueError):
            TM.simular(cs, plano, dt.date(2026, 10, 29), dt.time(18, 0))


class DoSinal(Base):
    def test_ordem_pendente_e_posicao(self):
        cs = pregoes(25, 0.0005)
        hoje = [c for c in pregao(dt.date(2026, 10, 29), 0.0005)][:8]
        r = S.simular(cs + hoje, "rompimento_abertura")
        self.assertIsNotNone(r["aberta"])
        caminho = S.salvar(r)
        sg = TM.plano_do_sinal(caminho, cs + hoje)
        self.assertEqual(sg["lado"], "compra")
        self.assertEqual(sg["hora"], dt.time(9, 40))
        self.assertIn("posição aberta", sg["origem"])


class CLI(Base):
    def test_rodar_e_gravar(self):
        os.makedirs("b3/dados")
        D.escrever("b3/dados/WIN_5m.csv", pregoes(25, 0.0005))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ret = TM.main(["b3/dados/WIN_5m.csv", "--lado", "compra", "--stop-pontos", "200",
                           "--data", "2026-10-29", "--hora", "10:00", "--sessoes", "300", "--gravar"])
        self.assertEqual(ret, 0)
        self.assertIn("alvo primeiro", out.getvalue())
        arq = [f for f in os.listdir("b3/timemachine")]
        self.assertEqual(len(arq), 1)
        with open(os.path.join("b3/timemachine", arq[0]), encoding="utf-8") as f:
            j = json.load(f)
        self.assertEqual(len(j["caminhos"]), 160)
        self.assertEqual(sum(b["n"] for b in j["histograma"]), 300)

    def test_erro_claro_no_fim_do_pregao(self):
        os.makedirs("b3/dados")
        D.escrever("b3/dados/WIN_5m.csv", pregoes(25, 0.0))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(TM.main(["b3/dados/WIN_5m.csv", "--lado", "compra", "--stop-pontos", "200"]), 2)
        self.assertIn("--data e --hora", err.getvalue())


if __name__ == "__main__":
    unittest.main()
