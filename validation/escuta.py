"""Escuta às cegas para músicas sem gabarito.

Compara a decodificação do upstream com a sem supressão de vizinhos. As
notas *contestadas* existem só sem a supressão e soam junto com uma vizinha a
um semitom: são as que o upstream apaga. O *controle* são notas que as duas
decodificações mantêm e que soam dentro de um acorde. Uma amostra misturada
dos dois grupos vai para a escuta sem dizer qual é qual.
"""

import csv
from pathlib import Path

import numpy as np

from validation.metricas import TOL_ONSET, casar

NOMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def nome(pitch: int) -> str:
    return f"{NOMES[pitch % 12]}{pitch // 12 - 1}"


def tempo(segundos: float) -> str:
    minutos, resto = divmod(segundos, 60)
    return f"{int(minutos)}:{resto:05.2f}"


def _soando(notas, t: float) -> np.ndarray:
    """Máscara das notas que soam no instante t (com tolerância de onset)."""
    on = np.array([n.onset for n in notas])
    off = np.array([n.offset for n in notas])
    return (on <= t + TOL_ONSET) & (off > t)


def classificar(upstream, sem_supressao):
    """Índices em ``sem_supressao``: (contestadas, controle, só no upstream)."""
    pares = casar([n.onset for n in upstream], [n.pitch for n in upstream],
                  [n.onset for n in sem_supressao], [n.pitch for n in sem_supressao])
    em_ambas = {j for _, j in pares}
    so_upstream = len(upstream) - len(pares)
    pitches = np.array([n.pitch for n in sem_supressao])

    contestadas, controle = [], []
    for j, nota in enumerate(sem_supressao):
        juntas = _soando(sem_supressao, nota.onset)
        juntas[j] = False
        if j not in em_ambas:
            if np.any(np.abs(pitches[juntas] - nota.pitch) == 1):
                contestadas.append(j)
        elif juntas.any():
            controle.append(j)
    return contestadas, controle, so_upstream


def segundas_menores(notas) -> int:
    """Pares de notas a um semitom que começam juntas."""
    on = np.array([n.onset for n in notas])
    p = np.array([n.pitch for n in notas])
    total = 0
    for i in range(len(notas)):
        total += int(np.sum((np.abs(on[i + 1 :] - on[i]) <= TOL_ONSET)
                            & (np.abs(p[i + 1 :] - p[i]) == 1)))
    return total


def amostrar(contestadas: list[int], controle: list[int], tamanho: int, seed: int = 0):
    """Metade de cada grupo (ou o que houver), embaralhada e depois em ordem de tempo."""
    rng = np.random.default_rng(seed)
    n = min(tamanho // 2, len(contestadas), len(controle))
    escolhidas = [("contestada", int(j)) for j in rng.choice(contestadas, n, replace=False)]
    escolhidas += [("controle", int(j)) for j in rng.choice(controle, n, replace=False)]
    return escolhidas


def escrever(destino: Path, notas, escolhidas, picos: np.ndarray):
    destino.mkdir(parents=True, exist_ok=True)
    ordem = sorted(escolhidas, key=lambda item: notas[item[1]].onset)
    with open(destino / "escuta.csv", "w", newline="", encoding="utf-8") as arquivo:
        saida = csv.writer(arquivo)
        saida.writerow(["n", "tempo", "nota", "ouvido"])
        for i, (_, j) in enumerate(ordem, start=1):
            saida.writerow([i, tempo(notas[j].onset), nome(notas[j].pitch), ""])
    with open(destino / "chave.csv", "w", newline="", encoding="utf-8") as arquivo:
        saida = csv.writer(arquivo)
        saida.writerow(["n", "grupo", "onset", "pitch", "score", "pico_ativacao", "soando_junto"])
        for i, (grupo, j) in enumerate(ordem, start=1):
            nota = notas[j]
            juntas = _soando(notas, nota.onset)
            juntas[j] = False
            acorde = " ".join(nome(notas[k].pitch) for k in np.flatnonzero(juntas))
            saida.writerow([i, grupo, f"{nota.onset:.3f}", nota.pitch, f"{nota.score:.3f}",
                            f"{picos[j]:.3f}", acorde])


SIM = {"1", "s", "sim", "y"}
NAO = {"0", "n", "nao", "não"}


def ler_julgamentos(pasta: Path) -> dict[str, list[int]]:
    """Julgamentos por grupo (1 = a nota está lá); itens sem resposta clara ficam de fora."""
    with open(pasta / "chave.csv", newline="", encoding="utf-8") as arquivo:
        grupos = {linha["n"]: linha["grupo"] for linha in csv.DictReader(arquivo)}
    por_grupo: dict[str, list[int]] = {"contestada": [], "controle": []}
    with open(pasta / "escuta.csv", newline="", encoding="utf-8") as arquivo:
        for linha in csv.DictReader(arquivo):
            resposta = (linha.get("ouvido") or "").strip().lower()
            if resposta in SIM:
                por_grupo[grupos[linha["n"]]].append(1)
            elif resposta in NAO:
                por_grupo[grupos[linha["n"]]].append(0)
    return por_grupo


def wilson(acertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson (95% por padrão) para uma proporção."""
    if n == 0:
        return float("nan"), float("nan")
    p = acertos / n
    denominador = 1 + z**2 / n
    centro = (p + z**2 / (2 * n)) / denominador
    meia = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominador
    return centro - meia, centro + meia
