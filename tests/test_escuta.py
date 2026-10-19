import csv
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.basic_pitch import Note  # noqa: E402
from validation import escuta  # noqa: E402


def nota(onset, pitch, dur=1.0, score=0.5):
    return Note(onset, onset + dur, pitch, score, 0, 1)


class ClassificationTests(unittest.TestCase):
    def test_groups_contested_control_and_upstream_only(self):
        upstream = [nota(1.0, 60), nota(1.0, 64), nota(8.0, 70)]
        sem = [
            nota(1.0, 60),   # nas duas, dentro de acorde → controle
            nota(1.0, 64),   # nas duas, dentro de acorde → controle
            nota(1.02, 59),  # só sem supressão, vizinha C4 soando → contestada
            nota(1.5, 65),   # só sem supressão, E4 soando a um semitom → contestada
            nota(5.0, 67),   # só sem supressão, sozinha → nenhum grupo
        ]
        contestadas, controle, so_upstream = escuta.classificar(upstream, sem)
        self.assertEqual(contestadas, [2, 3])
        self.assertEqual(controle, [0, 1])
        self.assertEqual(so_upstream, 1)

    def test_simultaneous_minor_seconds(self):
        notas = [nota(1.0, 60), nota(1.03, 61), nota(1.0, 62), nota(3.0, 63), nota(3.2, 64)]
        self.assertEqual(escuta.segundas_menores(notas), 2)

    def test_sample_is_balanced_and_unique(self):
        escolhidos = escuta.amostrar(list(range(5)), list(range(100, 200)), 30, seed=1)
        grupos = [g for g, _ in escolhidos]
        self.assertEqual(grupos.count("contestada"), 5)
        self.assertEqual(grupos.count("controle"), 5)
        self.assertEqual(len({j for _, j in escolhidos}), 10)


class ListeningFileTests(unittest.TestCase):
    def test_sheet_hides_the_group_and_judgments_are_scored(self):
        notas = [nota(61.234, 60), nota(61.234, 61), nota(90.0, 64), nota(90.0, 67)]
        escolhidos = [("controle", 2), ("contestada", 1)]
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            escuta.escrever(pasta, notas, escolhidos, np.full(4, 0.7))
            with open(pasta / "escuta.csv", newline="", encoding="utf-8") as arquivo:
                linhas = list(csv.DictReader(arquivo))
            self.assertEqual(list(linhas[0]), ["n", "tempo", "nota", "ouvido"])
            self.assertEqual([(l["tempo"], l["nota"]) for l in linhas],
                             [("1:01.23", "C#4"), ("1:30.00", "E4")])

            linhas[0]["ouvido"] = "sim"
            linhas[1]["ouvido"] = "0"
            with open(pasta / "escuta.csv", "w", newline="", encoding="utf-8") as arquivo:
                saida = csv.DictWriter(arquivo, fieldnames=list(linhas[0]))
                saida.writeheader()
                saida.writerows(linhas)
            julgados = escuta.ler_julgamentos(pasta)
        self.assertEqual(julgados, {"contestada": [1], "controle": [0]})

    def test_answered_sheet_is_detected(self):
        from validation.notas import _ficha_respondida

        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            self.assertFalse(_ficha_respondida(pasta))
            escuta.escrever(pasta, [nota(1.0, 60), nota(1.0, 61)], [("controle", 0)], np.ones(2))
            self.assertFalse(_ficha_respondida(pasta))
            ficha = pasta / "escuta.csv"
            ficha.write_text(ficha.read_text().rstrip("\n") + "1\n", encoding="utf-8")
            self.assertTrue(_ficha_respondida(pasta))

    def test_wilson_interval(self):
        lo, hi = escuta.wilson(8, 10)
        self.assertAlmostEqual(lo, 0.4902, places=3)
        self.assertAlmostEqual(hi, 0.9433, places=3)
        self.assertTrue(all(np.isnan(escuta.wilson(0, 0))))


if __name__ == "__main__":
    unittest.main()
