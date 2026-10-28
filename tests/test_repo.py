import json
import os
import re
import unittest

from _load import ROOT

SKILLS = ["b3-contratos", "b3-dados"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def arquivos_de_texto():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "b3")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_pastas_de_skill_na_raiz(self):
        achadas = sorted(d for d in os.listdir(ROOT)
                         if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(achadas, sorted(SKILLS))

    def test_frontmatter(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 300, "%s: descrição curta demais" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_toda_skill_tem_bloco_de_seguranca(self):
        for s in SKILLS:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("não é recomendação de investimento", low, s)
            self.assertIn("nunca envia ordem", low, s)

    def test_manifesto_do_plugin(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "b3-trader-skill")
        self.assertEqual(plugin["skills"], "./")
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
            mk = json.load(fh)
        self.assertEqual(mk["plugins"][0]["name"], "b3-trader-skill")
        self.assertEqual(mk["plugins"][0]["source"], "./")

    def test_readme_cita_todas_as_skills(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = fh.read()
        for s in SKILLS:
            self.assertIn("/" + s, readme, s)

    def test_scripts_so_biblioteca_padrao(self):
        permitidos = {"argparse", "csv", "datetime", "json", "math", "os", "random", "sys",
                      "time", "unicodedata", "contratos", "dados", "MetaTrader5"}
        for s in SKILLS:
            for f in os.listdir(os.path.join(ROOT, s)):
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(ROOT, s, f), encoding="utf-8") as fh:
                    src = fh.read()
                for m in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z0-9_]+)", src, re.M):
                    self.assertIn(m.group(1), permitidos, "%s/%s importa %s" % (s, f, m.group(1)))

    def test_nenhum_segredo_versionado(self):
        padrao = re.compile(r"(api[_-]?key|secret|senha|password|token)\s*[:=]\s*['\"][^'\"]{8,}",
                            re.I)
        for p in arquivos_de_texto():
            with open(p, encoding="utf-8", errors="replace") as fh:
                self.assertIsNone(padrao.search(fh.read()), p)


if __name__ == "__main__":
    unittest.main()
