import datetime as dt
import io
import json
import unittest
from contextlib import redirect_stdout

from _load import load

C = load("b3-contratos", "contratos")
d = dt.date


class Base(unittest.TestCase):
    def setUp(self):
        C.definir_config({})


class Calendario(Base):
    def test_pascoa(self):
        self.assertEqual(C.pascoa(2026), d(2026, 4, 5))
        self.assertEqual(C.pascoa(2027), d(2027, 3, 28))
        self.assertEqual(C.pascoa(2024), d(2024, 3, 31))

    def test_calculado_bate_com_a_lista_oficial_de_2026(self):
        calc = {k.isoformat() for k in C.feriados_calculados(2026)}
        self.assertEqual(calc, set(C.FERIADOS_OFICIAIS[2026]))

    def test_2027_calculado(self):
        fer = C.feriados(2027)
        self.assertIn(d(2027, 2, 8), fer)          # Carnaval
        self.assertIn(d(2027, 3, 26), fer)         # Sexta-feira Santa
        self.assertIn(d(2027, 11, 15), fer)        # Proclamação, segunda-feira
        self.assertNotIn(d(2027, 11, 20), fer)     # cai num sábado
        self.assertEqual(fer[d(2027, 2, 8)][1], "calculado")

    def test_dia_util(self):
        self.assertFalse(C.eh_dia_util(d(2026, 11, 2)))   # Finados
        self.assertFalse(C.eh_dia_util(d(2026, 10, 31)))  # sábado
        self.assertTrue(C.eh_dia_util(d(2026, 7, 9)))     # 9 de julho: pregão normal
        self.assertEqual(C.proximo_dia_util(d(2026, 10, 31)), d(2026, 11, 3))
        self.assertEqual(C.dia_util_anterior(d(2026, 11, 3)), d(2026, 10, 30))

    def test_config_extra_e_dia_com_pregao(self):
        C.definir_config({"feriados_extras": {"2026-10-29": "teste"},
                          "dias_com_pregao": ["2026-11-20"]})
        self.assertFalse(C.eh_dia_util(d(2026, 10, 29)))
        self.assertTrue(C.eh_dia_util(d(2026, 11, 20)))


class Vencimentos(Base):
    def test_win_2026(self):
        datas = [c["vencimento"] for c in C.contratos_do_ano("WIN", 2026)]
        self.assertEqual(datas, ["2026-02-18", "2026-04-15", "2026-06-17",
                                 "2026-08-12", "2026-10-14", "2026-12-16"])

    def test_win_quarta_mais_proxima_do_15(self):
        for c in C.contratos_do_ano("WIN", 2027):
            v = dt.date.fromisoformat(c["vencimento"])
            self.assertEqual(v.weekday(), 2, c)
            self.assertLessEqual(abs(v.day - 15), 3, c)

    def test_wdo_vence_no_primeiro_dia_util(self):
        self.assertEqual(C.vencimento("WDO", 2026, 11), d(2026, 11, 3))   # 1º domingo, 2 Finados
        self.assertEqual(C.ultimo_dia_negociacao("WDO", 2026, 11), d(2026, 10, 30))
        self.assertEqual(C.vencimento("WDO", 2027, 1), d(2027, 1, 4))
        self.assertEqual(C.ultimo_dia_negociacao("WDO", 2027, 1), d(2026, 12, 30))

    def test_codigos(self):
        self.assertEqual(C.codigo("WIN", 2026, 12), "WINZ26")
        self.assertEqual(C.codigo("WDO", 2027, 1), "WDOF27")
        self.assertEqual(C.ler_codigo("WDOX26"), ("WDO", 2026, 11))
        with self.assertRaises(ValueError):
            C.ler_codigo("WINZ2")
        with self.assertRaises(ValueError):
            C.vencimento("WIN", 2026, 11)


class Vigente(Base):
    def test_win_outubro(self):
        r = C.vigente("WIN", d(2026, 10, 28))
        self.assertEqual(r["vigente"]["codigo"], "WINZ26")
        self.assertEqual(r["contrato_liquido"], "WINZ26")
        self.assertFalse(r["rolar_agora"])

    def test_win_no_dia_do_vencimento_ainda_e_o_mesmo(self):
        r = C.vigente("WIN", d(2026, 10, 14))
        self.assertEqual(r["vigente"]["codigo"], "WINV26")
        self.assertEqual(r["dias_uteis_ate_ultimo_dia"], 0)
        self.assertEqual(r["contrato_liquido"], "WINZ26")
        self.assertEqual(C.vigente("WIN", d(2026, 10, 15))["vigente"]["codigo"], "WINZ26")

    def test_rolagem_wdo(self):
        self.assertEqual(C.contrato_liquido("WDO", d(2026, 10, 27)), "WDOX26")
        self.assertEqual(C.contrato_liquido("WDO", d(2026, 10, 28)), "WDOZ26")

    def test_rolagem_configuravel(self):
        C.definir_config({"rolagem_dias_uteis": {"WDO": 0}})
        self.assertEqual(C.contrato_liquido("WDO", d(2026, 10, 29)), "WDOX26")
        self.assertEqual(C.contrato_liquido("WDO", d(2026, 10, 30)), "WDOZ26")

    def test_virada_de_ano(self):
        r = C.vigente("WIN", d(2026, 12, 20))
        self.assertEqual(r["vigente"]["codigo"], "WING27")


class Pregao(Base):
    def test_horarios(self):
        self.assertEqual(C.horario("WIN", d(2026, 10, 28)), (dt.time(9, 0), dt.time(18, 25)))
        self.assertEqual(C.horario("WDO", d(2026, 10, 28)), (dt.time(9, 0), dt.time(18, 30)))
        self.assertIsNone(C.horario("WIN", d(2026, 11, 2)))
        self.assertEqual(C.minutos_de_pregao("WIN", d(2026, 10, 28)), 565)

    def test_quarta_de_cinzas(self):
        self.assertEqual(C.horario("WIN", d(2026, 2, 18))[0], dt.time(13, 0))

    def test_status(self):
        s = C.status_pregao("WIN", dt.datetime(2026, 10, 28, 18, 27))
        self.assertFalse(s["aberto"])
        self.assertEqual(s["proxima_abertura"], "2026-10-29T09:00")
        s = C.status_pregao("WDO", dt.datetime(2026, 10, 28, 18, 27))
        self.assertTrue(s["aberto"])
        self.assertEqual(s["minutos_para_fechar"], 3)
        s = C.status_pregao("WIN", dt.datetime(2026, 11, 2, 10, 0))
        self.assertIn("Finados", s["motivo"])
        self.assertEqual(s["proxima_abertura"], "2026-11-03T09:00")

    def test_status_aceita_fuso(self):
        utc = dt.datetime(2026, 10, 28, 13, 0, tzinfo=dt.timezone.utc)  # 10:00 em Brasília
        self.assertTrue(C.status_pregao("WIN", utc)["aberto"])

    def test_horario_por_periodo(self):
        C.definir_config({"horarios": {"WIN": [
            {"desde": "2026-01-01", "abertura": "09:00", "fechamento": "18:30"},
            {"desde": "2026-03-09", "abertura": "09:00", "fechamento": "18:25"}]}})
        self.assertEqual(C.horario("WIN", d(2026, 3, 6))[1], dt.time(18, 30))
        self.assertEqual(C.horario("WIN", d(2026, 3, 9))[1], dt.time(18, 25))


class Valores(Base):
    def test_win(self):
        r = C.valor_pontos("WIN", 350, 2)
        self.assertEqual(r["resultado_reais"], 140.0)
        self.assertEqual(r["valor_tick"], 1.0)

    def test_wdo_venda(self):
        r = C.valor_operacao("WDO", 5412.5, 5398, "venda", 3)
        self.assertEqual(r["pontos"], 14.5)
        self.assertEqual(r["resultado_reais"], 435.0)
        r = C.valor_operacao("WDO", 5412.5, 5420, "venda", 1)
        self.assertEqual(r["resultado_reais"], -75.0)

    def test_tick(self):
        self.assertEqual(C.arredondar_tick("WIN", 130127), 130125)
        self.assertEqual(C.arredondar_tick("WDO", 5412.3), 5412.5)


class CLI(Base):
    def _json(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(C.main(list(args) + ["--json"]), 0)
        return json.loads(buf.getvalue())

    def test_comandos(self):
        self.assertEqual(self._json("info", "WDO")["valor_ponto"], 10.0)
        self.assertEqual(self._json("vigente", "WIN", "--data", "2026-10-28")["contrato_liquido"],
                         "WINZ26")
        self.assertEqual(len(self._json("vencimentos", "WDO", "--ano", "2026")), 12)
        self.assertTrue(self._json("pregao", "--ativo", "WIN", "--agora", "2026-10-28 10:00")["aberto"])
        self.assertEqual(len(self._json("feriados", "--ano", "2026")["sem_pregao"]), 14)
        self.assertEqual(self._json("valor", "WIN", "--pontos", "100")["resultado_reais"], 20.0)

    def test_ativo_invalido(self):
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(C.main(["info", "XYZ"]), 2)
        self.assertIn("WIN ou WDO", err.getvalue())


if __name__ == "__main__":
    unittest.main()
