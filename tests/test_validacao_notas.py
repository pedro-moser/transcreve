from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from validation import metricas  # noqa: E402
from validation import roteiro as rot  # noqa: E402
from validation.notas import mixar  # noqa: E402
from validation.roteiro import NotaRef  # noqa: E402


class Est:
    """Nota estimada mínima para as métricas."""

    def __init__(self, onset, pitch, score=0.5):
        self.onset = onset
        self.pitch = pitch
        self.score = score


def ref(onset, pitch, classe="isolada", evento=0):
    return NotaRef(onset, onset + 1.0, pitch, evento, classe)


class RoteiroTests(unittest.TestCase):
    def test_note_names(self):
        self.assertEqual(rot.nome_para_midi("E2"), 40)
        self.assertEqual(rot.nome_para_midi("Bb1"), 34)
        self.assertEqual(rot.nome_para_midi("C#4"), 61)
        self.assertEqual(rot.nome_para_midi("C-1"), 0)

    def test_shapes_become_timed_and_classified_notes(self):
        r = rot.parse_roteiro("bpm 120\ncontagem 2\nx x 10 7 0 x\nx x x x x 5 | 4\n")
        cluster = [n for n in r.notas if n.evento == 0]
        self.assertEqual([n.pitch for n in cluster], [59, 60, 62])
        self.assertEqual([n.classe for n in cluster], ["2m", "2m", "2M"])
        self.assertEqual([(n.corda, n.casa) for n in cluster], [(2, 0), (4, 10), (3, 7)])
        self.assertEqual(cluster[0].onset, 1.0)  # duas batidas de contagem a 120 bpm
        (solo,) = [n for n in r.notas if n.evento == 1]
        self.assertEqual((solo.pitch, solo.classe, solo.onset), (69, "isolada", 2.0))
        self.assertEqual(r.duracao, 4.0)

    def test_unison_counts_once_and_warns(self):
        r = rot.parse_roteiro("x x x 4 0 x\n")  # B3 na corda 3 e na corda 2
        self.assertEqual([n.pitch for n in r.notas], [59])
        self.assertEqual(len(r.avisos), 1)

    def test_errors_name_the_line(self):
        with self.assertRaisesRegex(ValueError, "Linha 2"):
            rot.parse_roteiro("bpm 60\nx 3 2 0 1\n")
        with self.assertRaisesRegex(ValueError, "Linha 2: 'contagem'"):
            rot.parse_roteiro("x 3 2 0 1 0\ncontagem 4\n")

    def test_gabarito_round_trip_and_minimal_csv(self):
        r = rot.parse_roteiro("x 3 2 0 1 0\n")
        with tempfile.TemporaryDirectory() as temp:
            caminho = Path(temp) / "g.csv"
            rot.escrever_gabarito(r.notas, caminho)
            self.assertEqual(rot.ler_gabarito(caminho), r.notas)

            minimo = Path(temp) / "m.csv"
            minimo.write_text("onset,offset,pitch\n1.00,2,60\n1.02,2,61\n3.0,4,64\n")
            notas = rot.ler_gabarito(minimo)
        self.assertEqual([n.classe for n in notas], ["2m", "2m", "isolada"])
        self.assertEqual([n.evento for n in notas], [0, 0, 1])

    def test_click_track_marks_every_beat(self):
        r = rot.parse_roteiro("bpm 60\ncontagem 2\nbatidas 2\nx 3 2 0 1 0\n")
        clique = rot.faixa_de_clique(r, sr=8000)
        inicios = [t for t, _ in r.batidas]
        self.assertEqual(inicios, [0.0, 1.0, 2.0, 3.0])
        self.assertEqual([acento for _, acento in r.batidas], [False, False, True, False])
        for t in inicios:
            inicio = int(t * 8000)
            self.assertGreater(np.abs(clique[inicio : inicio + 40]).max(), 0.1)


class MatchingTests(unittest.TestCase):
    def test_matching_is_maximal_not_greedy(self):
        # O par mais próximo (0,04 ↔ 0,03) deixaria a outra referência sem par.
        pares = metricas.casar([0.00, 0.04], [60, 60], [0.03, 0.08], [60, 60])
        self.assertEqual(sorted(pares), [(0, 0), (1, 1)])

    def test_tolerance_boundary_and_pitch(self):
        self.assertEqual(metricas.casar([1.0], [60], [1.05], [60]), [(0, 0)])
        self.assertEqual(metricas.casar([1.0], [60], [1.0501], [60]), [])
        self.assertEqual(metricas.casar([1.0], [60], [1.0], [61]), [])

    def test_false_positives_are_typed(self):
        gabarito = [ref(1.0, 60, "2m"), ref(1.0, 61, "2m"), ref(3.0, 64)]
        estimadas = [Est(1.0, 60), Est(1.01, 60), Est(1.0, 72), Est(1.0, 62),
                     Est(3.0, 50), Est(5.0, 64)]
        r = metricas.avaliar(gabarito, estimadas)
        self.assertEqual(r.tipo_est, ["acerto", "duplicada", "oitava", "semitom",
                                      "outra altura", "fora de tempo"])
        self.assertEqual(r.recall_por_classe["2m"], (1, 2))
        self.assertEqual(r.recall_por_classe["isolada"], (0, 1))
        self.assertAlmostEqual(r.precisao, 1 / 6)

    def test_offset_estimate_recovers_a_known_delay(self):
        rng = np.random.default_rng(3)
        onsets = np.sort(rng.uniform(0, 60, 80))
        pitches = rng.integers(40, 80, 80)
        gabarito = [ref(t, int(p)) for t, p in zip(onsets, pitches)]
        estimadas = [Est(t + 0.123 + rng.normal(0, 0.004), int(p)) for t, p in zip(onsets, pitches)]
        self.assertAlmostEqual(metricas.estimar_deslocamento(gabarito, estimadas), 0.123, delta=0.003)

    def test_activation_peak_reads_the_window_after_the_onset(self):
        times = np.arange(0, 2, 0.01)
        note = np.zeros((len(times), 88))
        note[(times > 1.05) & (times < 1.1), 60 - 21] = 0.7
        note[times > 1.5, 60 - 21] = 0.95  # fora da janela
        picos = metricas.picos_de_ativacao([ref(1.0, 60), ref(1.0, 200)], note, times)
        self.assertAlmostEqual(picos[0], 0.7)
        self.assertTrue(np.isnan(picos[1]))


class CalibrationTests(unittest.TestCase):
    def test_ece_is_zero_when_scores_are_frequencies(self):
        prob = np.repeat([0.25, 0.75], 4)
        acertou = np.array([1, 0, 0, 0, 1, 1, 1, 0], dtype=float)
        self.assertAlmostEqual(metricas.ece(prob, acertou), 0.0)

    def test_isotonic_map_fixes_overconfident_scores(self):
        rng = np.random.default_rng(1)
        score = rng.uniform(0, 1, 4000)
        acertou = (rng.uniform(0, 1, 4000) < score**3).astype(float)  # score otimista
        resultado = metricas.calibrar(score, acertou)
        self.assertGreater(resultado["ece_score_cru"], 0.15)
        self.assertLess(resultado["ece_calibrado_cv"], 0.05)
        self.assertTrue(np.all(np.diff(resultado["mapa"]["p"]) >= 0))


class MixTests(unittest.TestCase):
    def test_mix_hits_the_requested_snr(self):
        rng = np.random.default_rng(2)
        guitarra = rng.normal(0, 0.05, (20_000, 2))
        acomp = rng.normal(0, 0.2, (20_000, 2))
        for snr in (0.0, -6.0, -12.0):
            mix = mixar(guitarra, acomp, snr)
            # mix = c_g·g + c_a·a; mínimos quadrados recuperam os dois ganhos,
            # mesmo quando a mistura foi normalizada para não clipar.
            base = np.stack([guitarra.ravel(), acomp.ravel()], axis=1)
            (c_g, c_a), *_ = np.linalg.lstsq(base, mix.ravel(), rcond=None)
            medido = 10 * np.log10(np.mean((c_g * guitarra) ** 2) / np.mean((c_a * acomp) ** 2))
            self.assertAlmostEqual(medido, snr, places=2)
            self.assertLessEqual(np.max(np.abs(mix)), 0.99 + 1e-6)


if __name__ == "__main__":
    unittest.main()
