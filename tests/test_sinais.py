import contextlib
import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest

from _load import load

S = load("b3-sinais", "sinais")
D, C, I = S.D, S.C, S.I


def dia(precos, data=dt.date(2026, 10, 28), tf=5, inicio=dt.time(9, 0), resto=None, ativo="WIN"):
    """Candles de `tf` min a partir das 09:00. `resto` completa o dia com um candle fixo."""
    out = []
    t = dt.datetime.combine(data, inicio)
    fim = dt.datetime.combine(data, C.horario(ativo, data)[1])
    lista = list(precos)
    while t < fim and (lista or resto):
        o, h, l, c = lista.pop(0) if lista else resto
        out.append(D.Candle(t, ativo, C.contrato_liquido(ativo, data), o, h, l, c, 100, "teste"))
        t += dt.timedelta(minutes=tf)
    return out


FAIXA = [(1000, 1020, 990, 1010), (1010, 1030, 1000, 1020), (1020, 1025, 995, 1000)]
ROMPE = (1000, 1045, 1000, 1040)   # fecha acima de 1030 + 1 tick


class Base(unittest.TestCase):
    def setUp(self):
        C.definir_config({})
        self.tmp = tempfile.mkdtemp()
        self.antes = os.getcwd()
        os.chdir(self.tmp)                      # nenhum b3/estrategias.json por perto

    def tearDown(self):
        os.chdir(self.antes)
        shutil.rmtree(self.tmp, ignore_errors=True)


class Indicadores(Base):
    def test_medias(self):
        self.assertEqual(I.mms([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])
        m = I.mme([1, 2, 3, 4, 5], 3)
        self.assertEqual(m[:2], [None, None])
        self.assertAlmostEqual(m[2], 2.0)
        self.assertAlmostEqual(m[3], 3.0)
        self.assertAlmostEqual(m[4], 4.0)

    def test_ifr(self):
        self.assertEqual(I.ifr([1, 2, 3, 4], 2)[3], 100.0)
        self.assertEqual(I.ifr([4, 3, 2, 1], 2)[3], 0.0)

    def test_vwap_zera_por_dia(self):
        cs = dia([(10, 10, 10, 10), (20, 20, 20, 20)]) + \
            dia([(30, 30, 30, 30)], data=dt.date(2026, 10, 29))
        self.assertEqual(I.vwap(cs), [10.0, 15.0, 30.0])

    def test_hilo(self):
        subida = [(100 + 10 * k, 105 + 10 * k, 95 + 10 * k, 104 + 10 * k) for k in range(12)]
        linha, tend = I.hilo(dia(subida), 3)
        self.assertEqual(tend[-1], 1)
        self.assertLess(linha[-1], subida[-1][3])


class Simulacao(Base):
    def test_orb_alvo(self):
        cs = dia(FAIXA + [ROMPE, (1040, 1050, 1035, 1045), (1045, 1145, 1040, 1140)])
        r = S.simular(cs, "rompimento_abertura")
        o = r["operacoes"][0]
        self.assertEqual(o["lado"], "compra")
        self.assertEqual(o["entrada"]["data_hora"], "2026-10-28 09:20")
        self.assertEqual(o["preco"], 1040)          # abertura do candle seguinte ao sinal
        self.assertEqual(o["stop_inicial"], 990)    # mínima da faixa
        self.assertEqual(o["alvo"], 1140)           # 2 x o risco de 50
        self.assertEqual(o["saida"]["motivo"], "alvo")
        self.assertEqual(o["pontos"], 100)
        self.assertEqual(o["reais"], 20.0)          # 100 pontos x R$ 0,20

    def test_stop_ganha_do_alvo_no_mesmo_candle(self):
        cs = dia(FAIXA + [ROMPE, (1040, 1050, 1035, 1045), (1045, 1145, 985, 1100)])
        o = S.simular(cs, "rompimento_abertura")["operacoes"][0]
        self.assertEqual(o["saida"]["motivo"], "stop")
        self.assertEqual(o["pontos"], -50)

    def test_gap_no_stop_sai_na_abertura(self):
        cs = dia(FAIXA + [ROMPE, (1040, 1050, 1035, 1045), (980, 1000, 970, 995)])
        o = S.simular(cs, "rompimento_abertura")["operacoes"][0]
        self.assertEqual(o["saida"]["preco"], 980)
        self.assertEqual(o["pontos"], -60)

    def test_zera_no_horario(self):
        cs = dia(FAIXA + [ROMPE], resto=(1050, 1060, 1045, 1055))
        r = S.simular(cs, "rompimento_abertura")
        self.assertEqual(len(r["operacoes"]), 1)
        o = r["operacoes"][0]
        self.assertEqual(o["saida"]["data_hora"], "2026-10-28 17:55")
        self.assertEqual(o["saida"]["motivo"], "zerada às 17:55")
        self.assertEqual((o["preco"], o["saida"]["preco"]), (1050, 1050))   # aberturas
        self.assertIsNone(r["aberta"])

    def test_zera_no_fim_do_dia_e_nao_leva_ordem(self):
        cs = dia(FAIXA + [ROMPE], resto=(1050, 1060, 1045, 1055))
        cs += dia(FAIXA, data=dt.date(2026, 10, 29))
        r = S.simular(cs, "rompimento_abertura", {"zerar_em": "23:59"})
        self.assertEqual(r["operacoes"][0]["saida"]["motivo"], "zerada no fim do dia")
        self.assertEqual(r["operacoes"][0]["saida"]["data_hora"], "2026-10-28 18:20")

    def test_uma_operacao_por_dia_no_orb(self):
        cs = dia(FAIXA + [ROMPE, (1040, 1040, 980, 985), (985, 1050, 985, 1045),
                          (1045, 1050, 1040, 1045)])
        self.assertEqual(len(S.simular(cs, "rompimento_abertura")["operacoes"]), 1)

    def test_nao_entra_depois_do_horario(self):
        cs = dia(FAIXA + [ROMPE], inicio=dt.time(17, 15))
        r = S.simular(cs, "rompimento_abertura", {"minutos": 15})
        self.assertEqual(r["operacoes"], [])
        self.assertIsNone(r["pendente"])

    def test_sinal_no_ultimo_candle_fica_pendente(self):
        r = S.simular(dia(FAIXA + [ROMPE]), "rompimento_abertura")
        self.assertEqual(r["operacoes"], [])
        self.assertEqual(r["pendente"]["lado"], "compra")
        self.assertEqual(r["pendente"]["tipo"], "mercado")

    def test_posicao_aberta_no_fim_do_arquivo(self):
        r = S.simular(dia(FAIXA + [ROMPE, (1040, 1050, 1035, 1045)]), "rompimento_abertura")
        self.assertEqual(r["aberta"]["lado"], "compra")
        self.assertEqual(r["aberta"]["pontos_abertos"], 5)

    def test_parametros(self):
        p = S.parametros(S.estrategia("setup_9_1"), {"vender": "false", "validade": "3"})
        self.assertIs(p["vender"], False)
        self.assertEqual(p["validade"], 3)
        with self.assertRaises(ValueError):
            S.parametros(S.estrategia("setup_9_1"), {"nao_existe": 1})
        with self.assertRaises(ValueError):
            S.estrategia("outra")

    def test_arquivo_de_parametros(self):
        os.makedirs("b3")
        with open(os.path.join("b3", "estrategias.json"), "w") as f:
            json.dump({"geral": {"contratos": 3}, "hilo": {"periodo": 5}}, f)
        p = S.parametros(S.estrategia("hilo"))
        self.assertEqual((p["contratos"], p["periodo"]), (3, 5))


class SemOlharOFuturo(Base):
    """Cortar o arquivo num ponto não pode mudar as operações fechadas antes dele."""

    def test_todas_as_estrategias(self):
        cs = D.reamostrar(D.gerar_mock("WIN", "2026-10-19", "2026-10-23", semente=3), 5)
        corte = cs[len(cs) // 2].data_hora.strftime("%Y-%m-%d %H:%M")
        parcial = [c for c in cs if c.data_hora.strftime("%Y-%m-%d %H:%M") <= corte]
        for nome in S.ESTRATEGIAS:
            cheio = S.simular(cs, nome)["operacoes"]
            meio = S.simular(parcial, nome)["operacoes"]
            antes = [o for o in cheio if o["saida"]["data_hora"] < corte]
            self.assertEqual([json.dumps(o, sort_keys=True) for o in antes],
                             [json.dumps(o, sort_keys=True) for o in meio
                              if o["saida"]["data_hora"] < corte], nome)

    def test_todas_rodam_e_respeitam_o_day_trade(self):
        cs = D.reamostrar(D.gerar_mock("WDO", "2026-09-01", "2026-10-27", semente=5), 15)
        for nome in S.ESTRATEGIAS:
            r = S.simular(cs, nome)
            for o in r["operacoes"]:
                self.assertEqual(o["entrada"]["data_hora"][:10], o["saida"]["data_hora"][:10], nome)
                self.assertLess(o["entrada"]["data_hora"][11:], "17:30", nome)
                if o["stop_inicial"] is not None:
                    if o["lado"] == "compra":
                        self.assertLess(o["stop_inicial"], o["preco"], nome)
                    else:
                        self.assertGreater(o["stop_inicial"], o["preco"], nome)
            self.assertTrue(r["ficticio"])


class CLI(Base):
    def test_rodar_comparar_agora(self):
        cs = D.gerar_mock("WIN", "2026-10-26", "2026-10-28")
        D.escrever(os.path.join("b3", "dados", "WIN_1m.csv"), cs)
        arq = os.path.join("b3", "dados", "WIN_1m.csv")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(S.main(["listar"]), 0)
            self.assertEqual(S.main(["rodar", arq, "--tf", "5", "-e", "vwap"]), 0)
            self.assertEqual(S.main(["comparar", arq, "--tf", "15"]), 0)
            self.assertEqual(S.main(["agora", arq, "--tf", "5", "-e", "hilo", "--json"]), 0)
        self.assertIn("FICTÍCIOS", out.getvalue())
        self.assertTrue(os.path.exists(os.path.join("b3", "sinais", "WIN_5m_vwap.json")))
        self.assertTrue(os.path.exists(os.path.join("b3", "sinais", "WIN_15m_ifr2.json")))

    def test_erro_claro(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(S.main(["rodar", "nao_existe.csv", "-e", "vwap"]), 2)
        self.assertIn("erro", err.getvalue())


if __name__ == "__main__":
    unittest.main()
