import datetime as dt
import os
import shutil
import tempfile
import unittest

from _load import FIX, load

D = load("b3-dados", "dados")
C = D.C


def niveis(probs, nivel):
    return [m for n, m in probs if n == nivel]


class Base(unittest.TestCase):
    def setUp(self):
        C.definir_config({})
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Mock(Base):
    def test_um_dia_de_win_tem_565_candles(self):
        cs = D.gerar_mock("WIN", "2026-10-28", "2026-10-28")
        self.assertEqual(len(cs), 565)
        self.assertEqual(cs[0].data_hora, dt.datetime(2026, 10, 28, 9, 0))
        self.assertEqual(cs[-1].data_hora, dt.datetime(2026, 10, 28, 18, 24))
        self.assertTrue(all(c.contrato == "WINZ26" and c.fonte == "mock" for c in cs))

    def test_pula_feriado_e_fim_de_semana(self):
        cs = D.gerar_mock("WDO", "2026-10-30", "2026-11-03")
        dias = sorted({c.data_hora.date() for c in cs})
        self.assertEqual(dias, [dt.date(2026, 10, 30), dt.date(2026, 11, 3)])

    def test_quarta_de_cinzas_abre_as_13(self):
        cs = D.gerar_mock("WIN", "2026-02-18", "2026-02-18")
        self.assertEqual(cs[0].data_hora.time(), dt.time(13, 0))

    def test_deterministico_e_valido(self):
        a = D.gerar_mock("WIN", "2026-09-01", "2026-09-10", semente=7)
        b = D.gerar_mock("WIN", "2026-09-01", "2026-09-10", semente=7)
        self.assertEqual([c.fechamento for c in a], [c.fechamento for c in b])
        probs = D.validar(a)
        self.assertEqual(niveis(probs, "erro"), [])
        self.assertEqual(niveis(probs, "aviso"), [])
        self.assertTrue(any("FICTÍCIOS" in m for m in niveis(probs, "info")))

    def test_rolagem_no_mock(self):
        cs = D.gerar_mock("WIN", "2026-10-07", "2026-10-16")
        contratos = []
        for c in cs:
            if not contratos or contratos[-1] != c.contrato:
                contratos.append(c.contrato)
        self.assertEqual(contratos, ["WINV26", "WINZ26"])
        self.assertEqual(D.validar(cs, 1) and niveis(D.validar(cs, 1), "aviso"), [])


class Reamostrar(Base):
    def setUp(self):
        super().setUp()
        self.um = D.gerar_mock("WIN", "2026-10-28", "2026-10-28")

    def test_contagens(self):
        self.assertEqual(len(D.reamostrar(self.um, 5)), 113)
        self.assertEqual(len(D.reamostrar(self.um, 15)), 38)
        self.assertEqual(len(D.reamostrar(self.um, 30)), 19)
        self.assertEqual(len(D.reamostrar(self.um, 60)), 10)

    def test_ohlc_agregado(self):
        h = D.reamostrar(self.um, 60)[0]
        hora = self.um[:60]
        self.assertEqual(h.data_hora, dt.datetime(2026, 10, 28, 9, 0))
        self.assertEqual(h.abertura, hora[0].abertura)
        self.assertEqual(h.fechamento, hora[-1].fechamento)
        self.assertEqual(h.maxima, max(c.maxima for c in hora))
        self.assertEqual(h.minima, min(c.minima for c in hora))
        self.assertEqual(h.volume, sum(c.volume for c in hora))
        ultimo = D.reamostrar(self.um, 60)[-1]
        self.assertEqual(ultimo.data_hora, dt.datetime(2026, 10, 28, 18, 0))

    def test_nao_junta_dias(self):
        dois = D.gerar_mock("WIN", "2026-10-27", "2026-10-28")
        hs = D.reamostrar(dois, 60)
        self.assertEqual(len(hs), 20)
        self.assertEqual(D.validar(hs, 60) and niveis(D.validar(hs, 60), "erro"), [])

    def test_ida_e_volta_pelo_arquivo(self):
        caminho = os.path.join(self.tmp, "WIN_1m.csv")
        D.escrever(caminho, self.um)
        lido = D.ler(caminho)
        self.assertEqual(len(lido), len(self.um))
        self.assertEqual(lido[10].fechamento, self.um[10].fechamento)
        self.assertEqual(D.inferir_tf(lido), 1)


class Validar(Base):
    def test_pega_os_problemas(self):
        cs = D.gerar_mock("WIN", "2026-10-28", "2026-10-28")[:100]
        cs[5].maxima = cs[5].minima - 5                     # OHLC incoerente
        cs[6].fechamento += 2                               # fora do tick
        cs.append(cs[7])                                    # duplicado e fora de ordem
        sabado = D.Candle(dt.datetime(2026, 10, 31, 10, 0), "WIN", "WINZ26",
                          130000, 130000, 130000, 130000, 1, "teste")
        cedo = D.Candle(dt.datetime(2026, 10, 29, 8, 30), "WIN", "WINZ26",
                        130000, 130000, 130000, 130000, 1, "teste")
        probs = D.validar(cs + [sabado, cedo], 1)
        erros, avisos = " | ".join(niveis(probs, "erro")), " | ".join(niveis(probs, "aviso"))
        self.assertIn("OHLC incoerente", erros)
        self.assertIn("duplicado", erros)
        self.assertIn("fora de ordem", erros)
        self.assertIn("dia sem pregão", erros)
        self.assertIn("fora do tick", avisos)
        self.assertIn("fora do horário", avisos)
        self.assertIn("faltam", avisos)                     # só 100 de 565 em 28/10

    def test_contrato_diferente_da_regra(self):
        cs = D.gerar_mock("WDO", "2026-10-29", "2026-10-29")
        for c in cs:
            c.contrato = "WDOX26"
        self.assertTrue(any("WDOZ26" in m for m in niveis(D.validar(cs), "aviso")))


class Continua(Base):
    def test_diferenca_remove_o_salto(self):
        cs = D.gerar_mock("WDO", "2026-09-24", "2026-09-30")
        self.assertEqual(len(D.rolagens(cs)), 1)
        i = D.rolagens(cs)[0]
        gap = cs[i].abertura - cs[i - 1].fechamento
        out, ajustes = D.serie_continua(cs, "diferenca")
        self.assertEqual(ajustes[0]["de"], "WDOV26")
        self.assertEqual(ajustes[0]["para"], "WDOX26")
        self.assertAlmostEqual(ajustes[0]["ajuste_pontos"], gap)
        self.assertAlmostEqual(out[i].abertura - out[i - 1].fechamento, 0)
        self.assertEqual(out[-1].fechamento, cs[-1].fechamento)   # trecho atual intacto
        self.assertEqual(out[0].contrato, "WDOV26")               # origem preservada

    def test_razao_e_nenhum(self):
        cs = D.gerar_mock("WIN", "2026-10-07", "2026-10-16")
        out, aj = D.serie_continua(cs, "razao")
        i = D.rolagens(cs)[0]
        self.assertAlmostEqual(out[i].abertura / out[i - 1].fechamento, 1, places=6)
        mesmo, aj = D.serie_continua(cs, "nenhum")
        self.assertEqual(aj, [])
        self.assertEqual(mesmo[0].abertura, cs[0].abertura)
        with self.assertRaises(ValueError):
            D.serie_continua(cs, "outro")


class Importar(Base):
    def test_mt5(self):
        cs = D.importar(os.path.join(FIX, "mt5_win_1m.csv"), "WIN")
        self.assertEqual(len(cs), 6)
        self.assertEqual(cs[0].data_hora, dt.datetime(2026, 10, 27, 9, 0))
        self.assertEqual((cs[0].abertura, cs[0].maxima, cs[0].minima, cs[0].fechamento),
                         (130125, 130210, 130090, 130180))
        self.assertEqual(cs[0].volume, 1834)        # VOL, não TICKVOL
        self.assertEqual(cs[0].contrato, "WINZ26")  # inferido pela regra
        self.assertEqual(cs[0].fonte, "mt5")
        self.assertEqual(niveis(D.validar(cs), "erro"), [])

    def test_profit(self):
        cs = D.importar(os.path.join(FIX, "profit_wdo_1m.csv"), "WDO")
        self.assertEqual(len(cs), 3)
        self.assertEqual(cs[0].abertura, 5412.5)
        self.assertEqual(cs[1].maxima, 5418.5)
        self.assertEqual(cs[0].volume, 900)          # Quantidade, não volume financeiro
        self.assertEqual(cs[0].contrato, "WDOZ26")   # do arquivo
        self.assertEqual(cs[0].fonte, "profit")

    def test_profit_sem_cabecalho(self):
        # Arquivo > Exportar Dados Históricos: sem cabeçalho, do mais novo para o mais antigo
        cs = D.importar(os.path.join(FIX, "profit_win_5m_sem_cabecalho.csv"), "WIN")
        self.assertEqual(len(cs), 3)
        self.assertEqual(cs[0].data_hora, dt.datetime(2026, 10, 28, 17, 50))
        self.assertEqual((cs[-1].abertura, cs[-1].maxima, cs[-1].minima, cs[-1].fechamento),
                         (173605, 173665, 173320, 173530))
        self.assertEqual(cs[-1].volume, 34310)       # Quantidade, não volume financeiro
        self.assertEqual(cs[0].contrato, "WINZ26")   # WINFUT não é contrato: regra de rolagem
        self.assertEqual(cs[0].fonte, "profit")

    def test_generico_em_ingles(self):
        caminho = os.path.join(self.tmp, "x.csv")
        with open(caminho, "w") as f:
            f.write("datetime,open,high,low,close,volume\n"
                    "2026-10-28 10:00,130000,130050,129990,130020,10\n")
        cs = D.importar(caminho, "WIN")
        self.assertEqual(cs[0].fechamento, 130020)
        self.assertEqual(cs[0].fonte, "generico")

    def test_padrao_volta_igual(self):
        um = D.gerar_mock("WIN", "2026-10-28", "2026-10-28")[:10]
        caminho = os.path.join(self.tmp, "WIN_1m.csv")
        D.escrever(caminho, um)
        self.assertEqual(len(D.importar(caminho, "WIN")), 10)

    def test_cabecalho_sem_preco(self):
        caminho = os.path.join(self.tmp, "ruim.csv")
        with open(caminho, "w") as f:
            f.write("data,hora,foo\n28/10/2026,10:00,1\n")
        with self.assertRaises(ValueError):
            D.importar(caminho, "WIN")


class CLI(Base):
    def test_fluxo_completo(self):
        pasta = os.path.join(self.tmp, "dados")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(D.main(["mock", "WIN", "--de", "2026-10-26", "--ate", "2026-10-28",
                                     "--pasta", pasta]), 0)
            for tf in (1, 5, 15, 30, 60):
                arq = os.path.join(pasta, "WIN_%dm.csv" % tf)
                self.assertTrue(os.path.exists(arq), arq)
                self.assertEqual(D.main(["validar", arq]), 0)
            self.assertEqual(D.main(["continua", os.path.join(pasta, "WIN_1m.csv")]), 0)
            self.assertEqual(D.main(["reamostrar", os.path.join(pasta, "WIN_1m_continua.csv"),
                                     "--tfs", "15"]), 0)
            self.assertTrue(os.path.exists(os.path.join(pasta, "WIN_15m_continua.csv")))
            self.assertEqual(D.main(["resumo", os.path.join(pasta, "WIN_5m.csv"), "--json"]), 0)

    def test_arquivo_fora_do_padrao_da_erro_claro(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(D.main(["validar", os.path.join(FIX, "mt5_win_1m.csv")]), 2)
        self.assertIn("importar", err.getvalue())


if __name__ == "__main__":
    unittest.main()
