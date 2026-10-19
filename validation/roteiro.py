"""Roteiro de voicings: gabarito, classes de intervalo e faixa de clique.

Formato do roteiro (uma diretiva ou um voicing por linha; ``#`` comenta):

    bpm 60
    batidas 2                     # batidas por voicing (padrão 2)
    contagem 4                    # batidas de clique antes do primeiro voicing
    afinacao E2 A2 D3 G3 B3 E4    # grave → agudo (padrão: E padrão)
    x x 10 7 0 x                  # casa por corda, grave → agudo; x = não toca
    x 3 2 0 1 0 | 4               # "| n": este voicing dura n batidas

``bpm`` e ``batidas`` valem para os voicings seguintes; ``contagem`` e
``afinacao`` só podem vir antes do primeiro voicing.
"""

from collections import Counter
import csv
from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np

CLASSES = ("2m", "2M", "3+", "isolada")
AFINACAO_PADRAO = (40, 45, 50, 55, 59, 64)  # E2 A2 D3 G3 B3 E4
# Notas com onsets mais próximos que isto contam como simultâneas quando o
# gabarito não diz a que evento cada nota pertence.
TOL_SIMULTANEO = 0.05

_LETRAS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


@dataclass(frozen=True)
class NotaRef:
    onset: float
    offset: float
    pitch: int  # MIDI, soando
    evento: int
    classe: str
    corda: int | None = None  # 1 = mais aguda, como na tab
    casa: int | None = None


@dataclass
class Roteiro:
    notas: list[NotaRef]
    batidas: list[tuple[float, bool]]  # (tempo, começa voicing)
    duracao: float
    avisos: list[str]


def nome_para_midi(nome: str) -> int:
    m = re.fullmatch(r"([A-Ga-g])([#b]*)(-?\d)", nome.strip())
    if not m:
        raise ValueError(f"Nota inválida: {nome!r} (use, por exemplo, E2, F#3 ou Bb1)")
    letra, acidentes, oitava = m.groups()
    alteracao = acidentes.count("#") - acidentes.count("b")
    return 12 * (int(oitava) + 1) + _LETRAS[letra.upper()] + alteracao


def classe_de(distancia: int | None) -> str:
    """Classe pela menor distância, em semitons, a outra nota simultânea."""
    if distancia is None:
        return "isolada"
    if distancia == 1:
        return "2m"
    if distancia == 2:
        return "2M"
    return "3+"


def classificar(pitches: list[int]) -> list[str]:
    classes = []
    for i, p in enumerate(pitches):
        outras = [abs(p - q) for j, q in enumerate(pitches) if j != i and q != p]
        classes.append(classe_de(min(outras) if outras else None))
    return classes


def ler_roteiro(caminho: Path | str) -> Roteiro:
    texto = Path(caminho).read_text(encoding="utf-8")
    return parse_roteiro(texto)


def parse_roteiro(texto: str) -> Roteiro:
    bpm = 60.0
    batidas_por_voicing = 2.0
    contagem = 4
    afinacao = AFINACAO_PADRAO
    tempo = None  # início do próximo voicing; definido no primeiro voicing
    notas: list[NotaRef] = []
    batidas: list[tuple[float, bool]] = []
    avisos: list[str] = []
    evento = 0

    for numero, bruta in enumerate(texto.splitlines(), start=1):
        linha = bruta.split("#", 1)[0].strip()
        if not linha:
            continue
        campos = linha.split()
        diretiva = campos[0].lower()
        try:
            if diretiva == "bpm":
                bpm = float(campos[1])
                continue
            if diretiva == "batidas":
                batidas_por_voicing = float(campos[1])
                continue
            if diretiva in ("contagem", "afinacao") and tempo is not None:
                raise ValueError(f"'{diretiva}' só pode vir antes do primeiro voicing")
            if diretiva == "contagem":
                contagem = int(campos[1])
                continue
            if diretiva == "afinacao":
                afinacao = tuple(nome_para_midi(n) for n in campos[1:])
                continue

            forma, _, duracao_txt = linha.partition("|")
            casas = forma.split()
            if len(casas) != len(afinacao):
                raise ValueError(
                    f"o voicing tem {len(casas)} cordas; a afinação tem {len(afinacao)}"
                )
            valores = [None if c.lower() == "x" else int(c) for c in casas]
            if any(v is not None and v < 0 for v in valores):
                raise ValueError("casa negativa")
            n_batidas = float(duracao_txt) if duracao_txt.strip() else batidas_por_voicing
        except (IndexError, ValueError) as erro:
            raise ValueError(f"Linha {numero}: {erro}") from None

        batida = 60.0 / bpm
        if tempo is None:
            batidas.extend((i * batida, False) for i in range(contagem))
            tempo = contagem * batida

        tocadas: dict[int, tuple[int, int]] = {}  # pitch -> (corda, casa)
        for indice, casa in enumerate(valores):
            if casa is None:
                continue
            pitch = afinacao[indice] + casa
            corda = len(afinacao) - indice
            if pitch in tocadas:
                avisos.append(
                    f"Linha {numero}: uníssono em {pitch} (cordas {tocadas[pitch][0]} e "
                    f"{corda}); conta como uma nota só"
                )
                continue
            tocadas[pitch] = (corda, casa)
        if not tocadas:
            raise ValueError(f"Linha {numero}: voicing sem nenhuma corda tocada")

        duracao = n_batidas * batida
        pitches = sorted(tocadas)
        for pitch, classe in zip(pitches, classificar(pitches)):
            corda, casa = tocadas[pitch]
            notas.append(NotaRef(tempo, tempo + duracao, pitch, evento, classe, corda, casa))
        inteiras = int(np.ceil(n_batidas - 1e-9))
        batidas.extend((tempo + i * batida, i == 0) for i in range(inteiras))
        tempo += duracao
        evento += 1

    if tempo is None:
        raise ValueError("O roteiro não tem nenhum voicing")
    return Roteiro(notas, batidas, tempo, avisos)


def classificar_por_onset(onsets: np.ndarray, pitches: np.ndarray) -> tuple[list[int], list[str]]:
    """Agrupa onsets próximos em eventos e classifica cada nota."""
    ordem = np.argsort(onsets, kind="stable")
    eventos = np.empty(len(onsets), dtype=int)
    evento = -1
    inicio = -np.inf
    for i in ordem:
        if onsets[i] - inicio > TOL_SIMULTANEO:
            evento += 1
            inicio = onsets[i]
        eventos[i] = evento
    classes = [""] * len(onsets)
    for e in range(evento + 1):
        membros = np.flatnonzero(eventos == e)
        for i, classe in zip(membros, classificar([int(pitches[m]) for m in membros])):
            classes[i] = classe
    return eventos.tolist(), classes


def escrever_gabarito(notas: list[NotaRef], caminho: Path | str):
    with open(caminho, "w", newline="", encoding="utf-8") as arquivo:
        saida = csv.writer(arquivo)
        saida.writerow(["onset", "offset", "pitch", "evento", "classe", "corda", "casa"])
        for n in notas:
            saida.writerow([
                f"{n.onset:.4f}", f"{n.offset:.4f}", n.pitch, n.evento, n.classe,
                "" if n.corda is None else n.corda, "" if n.casa is None else n.casa,
            ])


def ler_gabarito(caminho: Path | str) -> list[NotaRef]:
    """Lê um gabarito CSV. Só onset, offset e pitch são obrigatórios.

    Sem as colunas ``evento`` e ``classe``, notas com onsets a até 50 ms umas
    das outras contam como simultâneas.
    """
    with open(caminho, newline="", encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    if not linhas:
        raise ValueError(f"Gabarito vazio: {caminho}")
    onsets = np.array([float(l["onset"]) for l in linhas])
    pitches = np.array([int(l["pitch"]) for l in linhas])
    if linhas[0].get("evento") and linhas[0].get("classe"):
        eventos = [int(l["evento"]) for l in linhas]
        classes = [l["classe"] for l in linhas]
    else:
        eventos, classes = classificar_por_onset(onsets, pitches)

    def inteiro(valor):
        return int(valor) if valor not in (None, "") else None

    return [
        NotaRef(
            float(l["onset"]), float(l["offset"]), int(l["pitch"]), eventos[i], classes[i],
            inteiro(l.get("corda")), inteiro(l.get("casa")),
        )
        for i, l in enumerate(linhas)
    ]


def contar_classes(notas: list[NotaRef]) -> dict[str, int]:
    contagem = Counter(n.classe for n in notas)
    return {classe: contagem.get(classe, 0) for classe in CLASSES}


def faixa_de_clique(roteiro: Roteiro, sr: int = 44_100) -> np.ndarray:
    """Clique em cada batida; agudo onde começa um voicing."""
    total = int((roteiro.duracao + 1.0) * sr)
    saida = np.zeros(total, dtype=np.float32)
    n = int(0.03 * sr)
    t = np.arange(n) / sr
    envelope = np.exp(-t / 0.006)
    for tempo, acento in roteiro.batidas:
        freq = 1600.0 if acento else 1000.0
        inicio = int(round(tempo * sr))
        trecho = saida[inicio : inicio + n]
        trecho += (0.6 * envelope * np.sin(2 * np.pi * freq * t))[: len(trecho)]
    return saida
