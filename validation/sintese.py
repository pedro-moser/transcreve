"""Corda dedilhada sintética (Karplus-Strong) para ensaiar o pipeline.

Serve para testar o harness de ponta a ponta antes de gravar. Não substitui
gravação real: o timbre é simples demais para medir o Basic Pitch.
"""

import numpy as np
from scipy.signal import lfilter

from validation.roteiro import NotaRef


def corda(pitch: int, duracao: float, sr: int, rng: np.random.Generator,
          t60: float = 3.0, brilho: float = 0.6) -> np.ndarray:
    """Uma nota de ``duracao`` segundos, abafada no fim em 30 ms."""
    freq = 440.0 * 2 ** ((pitch - 69) / 12)
    periodo = sr / freq
    # O laço tem atraso N + 0,5 (média de dois pontos) + d (passa-tudo de
    # primeira ordem), o que afina a nota sem erro de arredondamento.
    n = int(np.floor(periodo - 0.5))
    d = periodo - 0.5 - n
    if d < 0.1:  # o passa-tudo fica mal condicionado perto de zero
        n -= 1
        d += 1.0
    c = (1 - d) / (1 + d)
    g = 10 ** (-3 / (freq * t60))

    a = np.zeros(n + 3)
    a[0] = 1.0
    a[1] += c
    a[n] -= g / 2 * c
    a[n + 1] -= g / 2 * (1 + c)
    a[n + 2] -= g / 2

    tamanho = int(duracao * sr)
    excitacao = np.zeros(tamanho)
    rajada = rng.uniform(-1, 1, n)
    excitacao[:n] = lfilter([brilho], [1, brilho - 1], rajada)  # passa-baixas
    saida = lfilter([1.0, c], a, excitacao)

    abafar = min(int(0.03 * sr), tamanho)
    saida[tamanho - abafar :] *= np.linspace(1, 0, abafar)
    return saida


def sintetizar(notas: list[NotaRef], duracao: float, sr: int = 44_100,
               espalhamento: float = 0.0, seed: int = 0) -> tuple[np.ndarray, list[NotaRef]]:
    """Renderiza o gabarito; devolve o áudio e o gabarito com os onsets usados.

    ``espalhamento`` (s) atrasa cada corda em relação à mais grave do evento,
    como num strum para baixo.
    """
    rng = np.random.default_rng(seed)
    saida = np.zeros(int((duracao + 1.0) * sr))
    usadas = []
    for nota in notas:
        atraso = 0.0
        if espalhamento and nota.corda is not None:
            atraso = espalhamento * max(0, 6 - nota.corda) / 5
        onset = nota.onset + atraso
        som = corda(nota.pitch, nota.offset - onset, sr, rng)
        som *= rng.uniform(0.6, 1.0)
        inicio = int(round(onset * sr))
        trecho = saida[inicio : inicio + len(som)]
        trecho += som[: len(trecho)]
        usadas.append(NotaRef(onset, nota.offset, nota.pitch, nota.evento, nota.classe,
                              nota.corda, nota.casa))
    pico = np.max(np.abs(saida))
    if pico > 0:
        saida *= 0.8 / pico
    return saida.astype(np.float32), usadas
