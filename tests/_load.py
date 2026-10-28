"""Carrega os scripts das pastas das skills (os nomes têm hífen)."""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")


def load(folder, name):
    pasta = os.path.join(ROOT, folder)
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    path = os.path.join(pasta, name + ".py")
    spec = importlib.util.spec_from_file_location("b3_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
