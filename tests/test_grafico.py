import contextlib
import datetime as dt
import io
import os
import shutil
import tempfile
import unittest

from _load import load

G = load("b3-grafico", "grafico")
P = load("b3-grafico", "painel")
T = load("b3-grafico", "tela")
S, D, C = G.S, G.D, G.C


def texto(tela):
    return "\n".join("".join(linha) for linha in tela.ch)


class Base(unittest.TestCase):
    def setUp(self):
        C.definir_config({})
        self.tmp = tempfile.mkdtemp()
        self.antes = os.getcwd()
        os.chdir(self.tmp)
        self.um = D.gerar_mock("WIN", "2026-10-26", "2026-10-28", semente=11)
        self.cinco = D.reamostrar(self.um, 5)

    def tearDown(self):
        os.chdir(self.antes)
        shutil.rmtree(self.tmp, ignore_errors=True)


class Grafico(Base):
    def test_tamanho_e_cabecalho(self):
        t = G.desenhar(self.cinco, 120, 34, G.Opcoes())
        self.assertEqual((t.w, t.h), (120, 34))
        tudo = texto(t)
        self.assertIn("WINZ26 5m", tudo)
        self.assertIn("FICTÍCIO", tudo)
        self.assertIn("MME9", tudo)
        self.assertTrue(any(ch in tudo for ch in "┃╽╿"))     # tem velas
        self.assertIn("28/10", tudo)                          # eixo do tempo

    def test_ultimo_preco_na_escala(self):
        t = G.desenhar(self.cinco, 120, 34, G.Opcoes())
        self.assertIn(T.preco_fmt("WIN", self.cinco[-1].fechamento), texto(t))

    def test_estrategia_marca_entradas_e_saidas(self):
        r = S.simular(self.cinco, "hilo")
        self.assertTrue(r["operacoes"])
        t = G.desenhar(self.cinco, 240, 40, G.Opcoes(estrategia="hilo"), r)
        tudo = texto(t)
        self.assertTrue("▲" in tudo or "▼" in tudo)
        self.assertIn("✕", tudo)
        self.assertIn("Hi-Lo Activator", tudo)

    def test_posicao_aberta_desenha_stop(self):
        r = S.simular(self.cinco, "hilo")
        r["aberta"] = {"lado": "compra", "preco": self.cinco[-3].fechamento,
                       "stop": self.cinco[-3].fechamento - 100, "alvo": None,
                       "entrada": {"data_hora": self.cinco[-3].data_hora.strftime("%Y-%m-%d %H:%M")},
                       "pontos_abertos": 25.0}
        tudo = texto(G.desenhar(self.cinco, 120, 34, G.Opcoes(), r))
        self.assertIn("COMPRADO", tudo)
        self.assertIn("╌", tudo)

    def test_terminal_pequeno_nao_quebra(self):
        for w, h in ((20, 6), (40, 10), (300, 80)):
            G.desenhar(self.cinco, w, h, G.Opcoes(vwap=True, hilo=8))
        G.desenhar([], 80, 20, G.Opcoes())

    def test_ansi_svg_e_volta(self):
        t = G.desenhar(self.cinco, 100, 30, G.Opcoes(vwap=True))
        a = t.ansi(True)
        self.assertIn("\x1b[", a)
        self.assertNotIn("\x1b[", t.ansi(False))
        self.assertTrue(t.svg().startswith("<svg"))
        volta = T.de_ansi(a, 100, 30)
        self.assertEqual(texto(volta), texto(t))
        self.assertEqual(volta.fg[0][2], t.fg[0][2])

    def test_carregar_junta_o_candle_em_formacao(self):
        os.makedirs(os.path.join("b3", "dados"))
        os.makedirs(os.path.join("b3", "estado"))
        arq = os.path.join("b3", "dados", "WIN_1m_aovivo.csv")
        D.escrever(arq, self.um[:30])
        prox = self.um[30]
        with open(os.path.join("b3", "estado", "WIN_ultimo.json"), "w") as f:
            f.write('{"candle_formando": {"data_hora": "%s", "abertura": %s, "maxima": %s, '
                    '"minima": %s, "fechamento": %s, "volume": 5}}' % (
                        prox.data_hora.strftime("%Y-%m-%d %H:%M"), prox.abertura, prox.maxima,
                        prox.minima, prox.fechamento))
        self.assertEqual(len(G.carregar(arq)), 31)
        self.assertEqual(len(G.carregar(arq, tf=5)), 7)

    def test_cli_uma_vez(self):
        os.makedirs(os.path.join("b3", "dados"))
        arq = os.path.join("b3", "dados", "WIN_5m.csv")
        D.escrever(arq, self.cinco)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(G.main([arq, "-e", "vwap", "--vwap", "--largura", "90", "--altura", "28",
                                     "--sem-cor"]), 0)
            self.assertEqual(G.main([arq, "--svg", "g.svg", "--largura", "90", "--altura", "28"]), 0)
        self.assertIn("VWAP", out.getvalue())
        self.assertTrue(os.path.exists("g.svg"))


class Painel(Base):
    def test_coleta_e_desenho(self):
        os.makedirs(os.path.join("b3", "dados"))
        D.escrever(os.path.join("b3", "dados", "WIN_1m.csv"), self.um)
        ests = list(S.ESTRATEGIAS)
        agora = dt.datetime(2026, 10, 28, 15, 0)
        info = P.coletar(["WIN", "WDO"], 5, ests, 3, agora=agora)
        win, wdo = info["ativos"]
        self.assertEqual(win["contrato"], "WINZ26")
        self.assertTrue(win["pregao"]["aberto"])
        self.assertEqual(set(win["estrategias"]), set(ests))
        self.assertIn("erro", wdo)                           # sem arquivo de WDO
        tudo = texto(P.desenhar(info, 46, 40, 5, ests))
        self.assertIn("WIN · WINZ26", tudo)
        self.assertIn("Estratégias 5m", tudo)
        self.assertIn("ORB", tudo)
        self.assertIn("sem dados", tudo)

    def test_replay_corta_no_horario_publicado(self):
        os.makedirs(os.path.join("b3", "dados"))
        os.makedirs(os.path.join("b3", "estado"))
        D.escrever(os.path.join("b3", "dados", "WIN_1m.csv"), self.um)
        with open(os.path.join("b3", "estado", "WIN_replay.json"), "w") as f:
            f.write('{"ate": "2026-10-27 11:00", "ativo": "WIN"}')
        info = P.coletar(["WIN"], 5, ["vwap"], 3, replay=True)
        self.assertEqual(info["ativos"][0]["hora"], dt.datetime(2026, 10, 27, 11, 0))


if __name__ == "__main__":
    unittest.main()
