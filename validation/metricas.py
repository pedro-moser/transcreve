"""Métricas da Fase 0: casamento nota a nota, curvas e calibração.

O casamento segue a regra de ``mir_eval.transcription`` com offsets
ignorados: mesma altura (±50 cents, ou seja, o mesmo MIDI) e onset a até
50 ms, com emparelhamento bipartido máximo.
"""

from dataclasses import dataclass

import numpy as np

from validation.roteiro import CLASSES, NotaRef

TOL_ONSET = 0.05
# A janela onde se procura a ativação de uma nota do gabarito.
JANELA_ATIVACAO = (-0.05, 0.15)


def casar(ref_onsets, ref_pitches, est_onsets, est_pitches, tol: float = TOL_ONSET):
    """Pares (índice no gabarito, índice na estimativa) do casamento máximo."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import maximum_bipartite_matching

    ref_onsets = np.asarray(ref_onsets, dtype=float)
    est_onsets = np.asarray(est_onsets, dtype=float)
    if len(ref_onsets) == 0 or len(est_onsets) == 0:
        return []
    distancia = np.abs(np.subtract.outer(ref_onsets, est_onsets)).round(4)
    acerto = (distancia <= tol) & np.equal.outer(
        np.asarray(ref_pitches), np.asarray(est_pitches)
    )
    if not acerto.any():
        return []
    par = maximum_bipartite_matching(csr_matrix(acerto), perm_type="column")
    return [(i, int(j)) for i, j in enumerate(par) if j >= 0]


def estimar_deslocamento(ref: list[NotaRef], est, busca: float = 1.0) -> float:
    """Atraso da gravação em relação ao gabarito, em segundos.

    Procura o deslocamento que maximiza os acertos e refina pela mediana
    dos erros de onset.
    """
    ref_on = np.array([n.onset for n in ref])
    ref_p = np.array([n.pitch for n in ref])
    est_on = np.array([n.onset for n in est])
    est_p = np.array([n.pitch for n in est])

    def acertos(delta):
        return len(casar(ref_on + delta, ref_p, est_on, est_p))

    grade = np.arange(-busca, busca + 1e-9, 0.01)
    contagens = [acertos(d) for d in grade]
    melhor = float(grade[int(np.argmax(contagens))])
    fina = np.arange(melhor - 0.01, melhor + 0.0101, 0.001)
    melhor = float(fina[int(np.argmax([acertos(d) for d in fina]))])
    pares = casar(ref_on + melhor, ref_p, est_on, est_p)
    if not pares:
        return 0.0
    erros = [est_on[j] - ref_on[i] for i, j in pares]
    return float(np.median(erros))


TIPOS_DE_ERRO = ("oitava", "semitom", "duplicada", "outra altura", "fora de tempo")


@dataclass
class Resultado:
    n_ref: int
    n_est: int
    acertos: list[tuple[int, int]]
    recall_por_classe: dict[str, tuple[int, int]]  # classe -> (acertos, total)
    tipo_est: list[str]  # "acerto" ou um TIPOS_DE_ERRO, por nota estimada

    @property
    def erros_est(self) -> dict[str, int]:
        return {tipo: self.tipo_est.count(tipo) for tipo in TIPOS_DE_ERRO}

    @property
    def precisao(self) -> float:
        return len(self.acertos) / self.n_est if self.n_est else float("nan")

    @property
    def recall(self) -> float:
        return len(self.acertos) / self.n_ref if self.n_ref else float("nan")

    @property
    def f(self) -> float:
        p, r = self.precisao, self.recall
        return 2 * p * r / (p + r) if p + r > 0 else 0.0


def avaliar(ref: list[NotaRef], est, tol: float = TOL_ONSET) -> Resultado:
    ref_on = np.array([n.onset for n in ref])
    ref_p = np.array([n.pitch for n in ref])
    est_on = np.array([n.onset for n in est])
    est_p = np.array([n.pitch for n in est])
    pares = casar(ref_on, ref_p, est_on, est_p, tol)

    casados_ref = {i for i, _ in pares}
    recall = {}
    for classe in CLASSES:
        membros = [i for i, n in enumerate(ref) if n.classe == classe]
        recall[classe] = (sum(i in casados_ref for i in membros), len(membros))

    casados_est = {j for _, j in pares}
    tipos = []
    for j in range(len(est)):
        if j in casados_est:
            tipos.append("acerto")
            continue
        perto = np.abs(ref_on - est_on[j]).round(4) <= tol
        if not perto.any():
            tipos.append("fora de tempo")
            continue
        distancias = np.abs(ref_p[perto] - est_p[j])
        if np.any(distancias == 0):  # a nota já foi casada com outra estimativa
            tipos.append("duplicada")
        elif np.any((distancias % 12 == 0) & (distancias > 0)):
            tipos.append("oitava")
        elif np.any(distancias == 1):
            tipos.append("semitom")
        else:
            tipos.append("outra altura")
    return Resultado(len(ref), len(est), pares, recall, tipos)


def erros_de_onset(ref: list[NotaRef], est, pares) -> tuple[np.ndarray, np.ndarray]:
    """(onset no gabarito, erro em segundos) de cada acerto."""
    t = np.array([ref[i].onset for i, _ in pares])
    erro = np.array([est[j].onset - ref[i].onset for i, j in pares])
    ordem = np.argsort(t)
    return t[ordem], erro[ordem]


def deriva(t: np.ndarray, erro: np.ndarray) -> float | None:
    """Inclinação do erro de onset em ms por minuto; None se a tomada for curta."""
    if len(t) < 10 or t[-1] - t[0] < 60:
        return None
    return float(np.polyfit(t, erro, 1)[0] * 60 * 1000)


def picos_de_ativacao(ref: list[NotaRef], note: np.ndarray, times: np.ndarray) -> np.ndarray:
    """Maior ativação de frame na altura de cada nota, perto do onset."""
    picos = np.full(len(ref), np.nan)
    for i, n in enumerate(ref):
        bin_ = n.pitch - 21
        if not 0 <= bin_ < note.shape[1]:
            continue
        janela = (times >= n.onset + JANELA_ATIVACAO[0]) & (times <= n.onset + JANELA_ATIVACAO[1])
        if janela.any():
            picos[i] = note[janela, bin_].max()
    return picos


def confiabilidade(prob: np.ndarray, acertou: np.ndarray, n_bins: int = 10):
    """Linhas (início, fim, n, média prevista, fração correta) por faixa."""
    bordas = np.linspace(0, 1, n_bins + 1)
    linhas = []
    for lo, hi in zip(bordas[:-1], bordas[1:]):
        dentro = (prob >= lo) & ((prob < hi) | (hi == 1.0))
        n = int(dentro.sum())
        if n:
            linhas.append((lo, hi, n, float(prob[dentro].mean()), float(acertou[dentro].mean())))
        else:
            linhas.append((lo, hi, 0, float("nan"), float("nan")))
    return linhas


def ece(prob: np.ndarray, acertou: np.ndarray, n_bins: int = 10) -> float:
    """Erro esperado de calibração: |previsto − observado| médio, pesado por faixa."""
    total = len(prob)
    if total == 0:
        return float("nan")
    return sum(
        n / total * abs(media - fracao)
        for _, _, n, media, fracao in confiabilidade(prob, acertou, n_bins)
        if n
    )


def calibrar(score: np.ndarray, acertou: np.ndarray, folds: int = 5, seed: int = 0) -> dict:
    """Regressão isotônica score → P(acerto).

    O ECE calibrado vem de validação cruzada; o mapa salvo usa todos os dados.
    """
    from sklearn.isotonic import IsotonicRegression

    score = np.asarray(score, dtype=float)
    acertou = np.asarray(acertou, dtype=float)

    def ajustar(x, y):
        return IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(x, y)

    prevista = np.full(len(score), np.nan)
    if len(score) >= 2 * folds:
        grupos = np.random.default_rng(seed).permutation(len(score)) % folds
        for g in range(folds):
            teste = grupos == g
            prevista[teste] = ajustar(score[~teste], acertou[~teste]).predict(score[teste])
    modelo = ajustar(score, acertou) if len(score) else None
    return {
        "n": int(len(score)),
        "ece_score_cru": ece(score, acertou),
        "ece_calibrado_cv": ece(prevista, acertou) if not np.isnan(prevista).any() else None,
        "mapa": {
            "score": modelo.X_thresholds_.tolist() if modelo else [],
            "p": modelo.y_thresholds_.tolist() if modelo else [],
        },
    }
