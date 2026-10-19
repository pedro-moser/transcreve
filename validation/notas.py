"""Fase 0 de SPEC-notas.md: o Basic Pitch acha as notas dos clusters?

Fluxo (rodar da raiz do repositório):

    python -m validation.notas roteiro voicings.txt --saida gravacao/
        → gabarito.csv e clique.wav; grave tocando junto com o clique
    python -m validation.notas mix take.wav --acomp baixo.wav bateria.wav --saida mixes/
        → mix_snr+0dB.wav, mix_snr-6dB.wav, mix_snr-12dB.wav
    python -m validation.notas separar mixes/mix_snr-6dB.wav --modelo bs_roformer_sw --saida g.wav
    python -m validation.notas avaliar --saida resultado/ \\
        --caso isolado take.wav gravacao/gabarito.csv \\
        --caso roformer-6dB g.wav gravacao/gabarito.csv

``sintetizar`` renderiza o roteiro com uma corda sintética, para ensaiar o
fluxo inteiro antes de gravar. ``biblioteca`` e ``conferir`` usam as músicas
do app, que não têm gabarito, numa escuta às cegas (ver validation/escuta.py).
"""

import argparse
from collections import defaultdict
import csv
from dataclasses import replace
import json
from pathlib import Path
import sys

import numpy as np

from services.note_detection_service import EXTRACTION as EXTRACAO_APP
from validation import metricas, roteiro as rot
from validation.roteiro import CLASSES

# Decodificações comparadas. "upstream" são os defaults do Basic Pitch e "app"
# é a do Transcreve. A curva P-R e a calibração usam "app", porque é ela que o
# limiar do app filtra (SPEC-notas.md, decisão 4). A extensão vem de --extensao.
EXTRACOES = {
    "upstream": {},
    "curta": {"min_frames": 5},
    "sem-melodia": {"melodia": False},
    "sem-supressao": {"neighbor_suppression": False},
    "permissiva": {
        "onset_threshold": 0.3,
        "frame_threshold": 0.2,
        "min_frames": 5,
        "neighbor_suppression": False,
    },
    "app": {k: v for k, v in EXTRACAO_APP.items() if k not in ("min_pitch", "max_pitch")},
}
REFERENCIA = "upstream"  # usada para alinhar a gravação ao gabarito
VARREDURA = "app"
LIMIARES = np.round(np.arange(0.1, 0.951, 0.05), 2)
MINIMO_POR_CLASSE = 40


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m validation.notas", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("roteiro", help="gabarito e faixa de clique a partir do roteiro")
    p.add_argument("roteiro", type=Path)
    p.add_argument("--saida", type=Path, required=True)
    p.set_defaults(func=cmd_roteiro)

    p = sub.add_parser("sintetizar", help="ensaio sintético do roteiro")
    p.add_argument("roteiro", type=Path)
    p.add_argument("--saida", type=Path, required=True)
    p.add_argument("--espalhamento", type=float, default=0.015,
                   help="atraso do strum entre a corda grave e a aguda, em s (padrão 0,015)")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_sintetizar)

    p = sub.add_parser("mix", help="soma a guitarra ao acompanhamento em SNRs fixas")
    p.add_argument("guitarra", type=Path)
    p.add_argument("--acomp", type=Path, nargs="+", required=True)
    p.add_argument("--snr", type=float, nargs="+", default=[0.0, -6.0, -12.0],
                   help="potência da guitarra sobre a do acompanhamento, em dB")
    p.add_argument("--saida", type=Path, required=True)
    p.set_defaults(func=cmd_mix)

    p = sub.add_parser("separar", help="stem de guitarra com os separadores do app")
    p.add_argument("audio", type=Path)
    p.add_argument("--modelo", choices=["htdemucs_6s", "bs_roformer_sw"], required=True)
    p.add_argument("--saida", type=Path, required=True)
    p.set_defaults(func=cmd_separar)

    p = sub.add_parser("avaliar", help="roda o Basic Pitch e mede contra o gabarito")
    p.add_argument("--caso", nargs=3, action="append", required=True,
                   metavar=("ROTULO", "AUDIO", "GABARITO"),
                   help="repita para cada tomada; casos com o mesmo rótulo são somados")
    p.add_argument("--saida", type=Path, required=True)
    p.add_argument("--deslocamento", type=float, default=None,
                   help="atraso da gravação em s; sem isto, é estimado por caso")
    p.add_argument("--extensao", type=int, nargs=2, default=[40, 88], metavar=("MIN", "MAX"),
                   help="faixa de MIDI decodificada (padrão 40 88: E2–E6)")
    p.set_defaults(func=cmd_avaliar)

    p = sub.add_parser("biblioteca", help="músicas do app sem gabarito: escuta às cegas")
    p.add_argument("busca", nargs="?", help="trecho do título/artista ou início do id; "
                   "sem isto, lista as músicas")
    p.add_argument("--todas", action="store_true", help="todas as músicas com stems")
    p.add_argument("--saida", type=Path, default=Path("validation/escuta"))
    p.add_argument("--amostra", type=int, default=30,
                   help="itens de escuta por música, metade de cada grupo (padrão 30)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--alta-qualidade", action="store_true",
                   help="antes, separa no cache do app com o BS-RoFormer, como o botão "
                   "Alta qualidade do player")
    p.set_defaults(func=cmd_biblioteca)

    p = sub.add_parser("conferir", help="resultado da escuta às cegas")
    p.add_argument("pastas", type=Path, nargs="+", help="pastas com escuta.csv e chave.csv")
    p.set_defaults(func=cmd_conferir)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as erro:
        parser.exit(1, f"erro: {erro}\n")


# ── roteiro e síntese ───────────────────────────────────────────────

def cmd_roteiro(args):
    import soundfile as sf

    r = rot.ler_roteiro(args.roteiro)
    args.saida.mkdir(parents=True, exist_ok=True)
    rot.escrever_gabarito(r.notas, args.saida / "gabarito.csv")
    sf.write(args.saida / "clique.wav", rot.faixa_de_clique(r), 44_100)
    _relatar_roteiro(r)
    print(f"Gravados {args.saida / 'gabarito.csv'} e {args.saida / 'clique.wav'}")


def cmd_sintetizar(args):
    import soundfile as sf
    from validation.sintese import sintetizar

    r = rot.ler_roteiro(args.roteiro)
    audio, usadas = sintetizar(r.notas, r.duracao, espalhamento=args.espalhamento, seed=args.seed)
    args.saida.mkdir(parents=True, exist_ok=True)
    rot.escrever_gabarito(usadas, args.saida / "gabarito.csv")
    sf.write(args.saida / "ensaio.wav", audio, 44_100)
    _relatar_roteiro(r)
    print(f"Gravados {args.saida / 'gabarito.csv'} e {args.saida / 'ensaio.wav'}")


def _relatar_roteiro(r: rot.Roteiro):
    for aviso in r.avisos:
        print(f"aviso: {aviso}")
    contagem = rot.contar_classes(r.notas)
    eventos = len({n.evento for n in r.notas})
    print(f"{eventos} voicings, {len(r.notas)} notas, {r.duracao:.1f} s")
    print("notas por classe: " + " · ".join(f"{c} {n}" for c, n in contagem.items()))
    poucas = [c for c, n in contagem.items() if n < MINIMO_POR_CLASSE]
    if poucas:
        print(f"aviso: menos de {MINIMO_POR_CLASSE} notas em {', '.join(poucas)} "
              f"(IC de recall fica maior que ±15 pp)")


# ── mix e separação ─────────────────────────────────────────────────

def mixar(guitarra: np.ndarray, acomp: np.ndarray, snr_db: float) -> np.ndarray:
    """Guitarra + acompanhamento com a razão de potências pedida."""
    p_guitarra = float(np.mean(guitarra**2))
    p_acomp = float(np.mean(acomp**2))
    if p_guitarra == 0 or p_acomp == 0:
        raise ValueError("guitarra ou acompanhamento em silêncio")
    ganho = np.sqrt(p_guitarra / (p_acomp * 10 ** (snr_db / 10)))
    mix = guitarra + ganho * acomp
    pico = float(np.max(np.abs(mix)))
    if pico > 0.99:  # o mesmo fator nos dois preserva a SNR
        mix *= 0.99 / pico
    return mix.astype(np.float32)


def _ler(caminho: Path, sr: int | None = None, canais: int | None = None):
    import soundfile as sf

    dados, taxa = sf.read(caminho, dtype="float32", always_2d=True)
    if sr is not None and taxa != sr:
        import soxr

        dados = soxr.resample(dados, taxa, sr, quality="HQ").astype(np.float32)
        taxa = sr
    if canais is not None and dados.shape[1] != canais:
        mono = dados.mean(axis=1, keepdims=True)
        dados = np.repeat(mono, canais, axis=1)
    return dados, taxa


def cmd_mix(args):
    import soundfile as sf

    guitarra, sr = _ler(args.guitarra)
    acomp = np.zeros_like(guitarra)
    for caminho in args.acomp:
        dados, _ = _ler(caminho, sr, guitarra.shape[1])
        n = min(len(dados), len(acomp))
        if len(dados) < len(acomp):
            print(f"aviso: {caminho.name} é mais curto que a guitarra; o resto fica em silêncio")
        acomp[:n] += dados[:n]
    args.saida.mkdir(parents=True, exist_ok=True)
    for snr in args.snr:
        destino = args.saida / f"mix_snr{snr:+g}dB.wav"
        sf.write(destino, mixar(guitarra, acomp, snr), sr)
        print(f"Gravado {destino}")


def cmd_separar(args):
    import soundfile as sf
    import torch
    import torchaudio
    from services import separation_service

    dados, sr = _ler(args.audio)
    canais = dados.shape[1]
    onda = torch.from_numpy(dados.T.copy())
    if onda.shape[0] == 1:
        onda = onda.repeat(2, 1)
    # Reusa o código de separação do app sem passar pelo cache de stems.
    worker = separation_service._SepWorker(str(args.audio), "validacao", args.modelo)
    worker.progress.connect(print)
    if args.modelo == separation_service.HQ_MODEL:
        fontes, taxa, estimativas = worker._separate_roformer(onda, sr)
    else:
        fontes, taxa, estimativas = worker._separate_demucs(onda, sr)
    guitarra = estimativas[list(fontes).index("guitar")]
    if taxa != sr:
        guitarra = torchaudio.functional.resample(guitarra, taxa, sr)
    guitarra = guitarra.numpy().T[: len(dados)]
    if canais == 1:
        guitarra = guitarra.mean(axis=1, keepdims=True)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.saida, guitarra, sr)
    print(f"Gravado {args.saida}")


# ── avaliação ───────────────────────────────────────────────────────

def cmd_avaliar(args):
    from services import basic_pitch as bp

    sessao = bp.load_session()
    min_pitch, max_pitch = args.extensao
    por_rotulo: dict[str, list[dict]] = defaultdict(list)
    # Mixes e stems saem alinhados amostra a amostra com a tomada isolada, e
    # neles o alinhamento automático pode casar notas espúrias. Por isso o
    # deslocamento é estimado no primeiro caso de cada gabarito e herdado.
    deslocamentos: dict[str, tuple[float, str]] = {}
    for rotulo, audio_path, gabarito_path in args.caso:
        print(f"[{rotulo}] {audio_path}")
        dados, sr = _ler(Path(audio_path))
        ref = rot.ler_gabarito(gabarito_path)
        act = bp.infer(dados, sr, sessao)
        notas = {
            nome: bp.extract_notes(act, min_pitch=min_pitch, max_pitch=max_pitch, **cfg)
            for nome, cfg in EXTRACOES.items()
        }
        chave = str(Path(gabarito_path).resolve())
        estimado_aqui = False
        if args.deslocamento is not None:
            deslocamento, origem = args.deslocamento, "--deslocamento"
        elif chave in deslocamentos:
            deslocamento, origem = deslocamentos[chave]
        else:
            deslocamento = metricas.estimar_deslocamento(ref, notas[REFERENCIA])
            origem = f"estimado em {Path(audio_path).stem}"
            deslocamentos[chave] = (deslocamento, origem)
            estimado_aqui = True
        ref = [replace(n, onset=n.onset + deslocamento, offset=n.offset + deslocamento)
               for n in ref]
        resultados = {nome: metricas.avaliar(ref, est) for nome, est in notas.items()}
        if estimado_aqui and resultados[REFERENCIA].recall < 0.5:
            print(f"aviso: só {resultados[REFERENCIA].recall:.0%} das notas casam no "
                  f"deslocamento estimado ({deslocamento * 1000:+.0f} ms); confira o "
                  "alinhamento ou passe --deslocamento")
        t, erro = metricas.erros_de_onset(ref, notas[REFERENCIA], resultados[REFERENCIA].acertos)
        varredura = []
        for limiar in LIMIARES:
            filtradas = [n for n in notas[VARREDURA] if n.score >= limiar]
            varredura.append(metricas.avaliar(ref, filtradas))
        por_rotulo[rotulo].append({
            "caso": Path(audio_path).stem,
            "audio": audio_path,
            "gabarito": gabarito_path,
            "ref": ref,
            "notas": notas,
            "resultados": resultados,
            "deslocamento": deslocamento,
            "origem_deslocamento": origem,
            "erro_onset": erro,
            "deriva": metricas.deriva(t, erro),
            "picos": metricas.picos_de_ativacao(ref, act.note, act.times),
            "varredura": varredura,
        })

    args.saida.mkdir(parents=True, exist_ok=True)
    resumo = []
    calibracoes = {}
    linhas = defaultdict(list)
    for rotulo, casos in por_rotulo.items():
        resumo.extend(_resumir(rotulo, casos))
        calibracoes[rotulo] = _calibrar(rotulo, casos, linhas)
        _tabelar(rotulo, casos, linhas)
        resumo.append(
            f"calibração ({VARREDURA}, n={calibracoes[rotulo]['n']}): ECE do score cru "
            f"{_fmt(calibracoes[rotulo]['ece_score_cru'])} → isotônica (validação cruzada) "
            f"{_fmt(calibracoes[rotulo]['ece_calibrado_cv'])}"
        )
        resumo.append("")

    for nome, (cabecalho, dados) in _arquivos(linhas).items():
        with open(args.saida / nome, "w", newline="", encoding="utf-8") as arquivo:
            saida = csv.writer(arquivo)
            saida.writerow(cabecalho)
            saida.writerows(dados)
    (args.saida / "calibracao.json").write_text(
        json.dumps({"extracao": VARREDURA, "parametros": EXTRACOES[VARREDURA], **calibracoes},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    texto = "\n".join(resumo)
    (args.saida / "resumo.txt").write_text(texto + "\n", encoding="utf-8")
    print()
    print(texto)
    print(f"Tabelas em {args.saida}/")


def _somar(resultados: list[metricas.Resultado]):
    acertos = sum(len(r.acertos) for r in resultados)
    n_ref = sum(r.n_ref for r in resultados)
    n_est = sum(r.n_est for r in resultados)
    classes = {
        c: (sum(r.recall_por_classe[c][0] for r in resultados),
            sum(r.recall_por_classe[c][1] for r in resultados))
        for c in CLASSES
    }
    erros = {t: sum(r.erros_est[t] for r in resultados) for t in metricas.TIPOS_DE_ERRO}
    return acertos, n_ref, n_est, classes, erros


def _razao(a, b):
    return a / b if b else float("nan")


def _fmt(valor, casas=2):
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return "—"
    return f"{valor:.{casas}f}"


def _num(valor, casas=4):
    """Número para CSV; vazio quando ausente."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return ""
    return f"{valor:.{casas}f}"


def _resumir(rotulo: str, casos: list[dict]) -> list[str]:
    todas = [n for c in casos for n in c["ref"]]
    contagem = rot.contar_classes(todas)
    out = [f"== {rotulo} ({len(casos)} caso(s), {len(todas)} notas no gabarito)"]
    out.append("classes: " + " · ".join(f"{c} {n}" for c, n in contagem.items()))
    poucas = [c for c, n in contagem.items() if 0 < n < MINIMO_POR_CLASSE]
    if poucas:
        out.append(f"aviso: menos de {MINIMO_POR_CLASSE} notas em {', '.join(poucas)}")
    for c in casos:
        erro = c["erro_onset"] * 1000
        deriva = c["deriva"]
        out.append(
            f"{c['caso']}: deslocamento {c['deslocamento'] * 1000:+.0f} ms "
            f"({c['origem_deslocamento']}); onset "
            f"mediana {_fmt(np.median(erro) if len(erro) else None, 1)} ms, "
            f"dp {_fmt(np.std(erro) if len(erro) else None, 1)} ms"
            + (f"; deriva {deriva:+.2f} ms/min" if deriva is not None else "")
        )

    def linha(rotulo_linha, valores, largura=8):
        return f"{rotulo_linha:<14s}" + "".join(f"{v:>{largura}s}" for v in valores)

    out.append("")
    out.append(f"{'':72s}│ falsos positivos por tipo")
    out.append(linha("", ["P", "R", "F", *(f"R {c[:3]}" for c in CLASSES)]) + "  │"
               + "".join(f"{e:>8s}" for e in ["oitava", "semitom", "duplic.", "outra", "f.tempo"]))
    for nome in EXTRACOES:
        acertos, n_ref, n_est, classes, erros = _somar([c["resultados"][nome] for c in casos])
        p, r = _razao(acertos, n_est), _razao(acertos, n_ref)
        f = 2 * p * r / (p + r) if p + r > 0 else 0.0
        valores = [_fmt(p), _fmt(r), _fmt(f), *(_fmt(_razao(*classes[c])) for c in CLASSES)]
        out.append(linha(nome, valores) + "  │"
                   + "".join(f"{erros[t]:>8d}" for t in metricas.TIPOS_DE_ERRO))

    out.append("")
    out.append(f"Esquerda: notas '{VARREDURA}' com score (ativação média da nota) ≥ limiar.")
    out.append("Direita: notas do gabarito com pico de ativação ≥ limiar, ou seja, se o modelo")
    out.append("vê a nota. As duas escalas diferem (média × pico); compare classes, não limiares.")
    out.append(linha("limiar", ["P", "R", *(c[:3] for c in CLASSES)]) + "  │"
               + "".join(f"{c[:3]:>8s}" for c in CLASSES))
    picos = np.concatenate([c["picos"] for c in casos])
    classes_ref = np.array([n.classe for c in casos for n in c["ref"]])
    for k, limiar in enumerate(LIMIARES):
        if round(limiar * 100) % 10:
            continue  # o resumo mostra de 0,1 em 0,1; o CSV tem tudo
        acertos, n_ref, n_est, classes, _ = _somar([c["varredura"][k] for c in casos])
        ativ = [
            _razao(np.sum(picos[classes_ref == cl] >= limiar), np.sum(classes_ref == cl))
            for cl in CLASSES
        ]
        valores = [_fmt(_razao(acertos, n_est)), _fmt(_razao(acertos, n_ref)),
                   *(_fmt(_razao(*classes[c])) for c in CLASSES)]
        out.append(linha(f"{limiar:.2f}", valores) + "  │"
                   + "".join(f"{_fmt(a):>8s}" for a in ativ))
    return out


def _calibrar(rotulo: str, casos: list[dict], linhas) -> dict:
    score = np.array([n.score for c in casos for n in c["notas"][VARREDURA]])
    acertou = np.array([t == "acerto" for c in casos for t in c["resultados"][VARREDURA].tipo_est])
    for lo, hi, n, media, fracao in metricas.confiabilidade(score, acertou):
        linhas["confiabilidade.csv"].append(
            [rotulo, f"{lo:.1f}", f"{hi:.1f}", n, _num(media, 4), _num(fracao, 4)])
    return metricas.calibrar(score, acertou)


def _tabelar(rotulo: str, casos: list[dict], linhas):
    for nome in EXTRACOES:
        acertos, n_ref, n_est, classes, erros = _somar([c["resultados"][nome] for c in casos])
        p, r = _razao(acertos, n_est), _razao(acertos, n_ref)
        f = 2 * p * r / (p + r) if p + r > 0 else 0.0
        linhas["metricas.csv"].append(
            [rotulo, nome, "todas", acertos, n_ref, n_est, _num(p, 4), _num(r, 4), _num(f, 4)]
            + [erros[t] for t in metricas.TIPOS_DE_ERRO])
        for c in CLASSES:
            a, total = classes[c]
            linhas["metricas.csv"].append(
                [rotulo, nome, c, a, total, "", "", _num(_razao(a, total), 4), ""]
                + [""] * len(metricas.TIPOS_DE_ERRO))

    picos = np.concatenate([c["picos"] for c in casos])
    classes_ref = np.array([n.classe for c in casos for n in c["ref"]])
    for k, limiar in enumerate(LIMIARES):
        acertos, n_ref, n_est, classes, _ = _somar([c["varredura"][k] for c in casos])
        linhas["pr.csv"].append([rotulo, limiar, "todas", n_est, _num(_razao(acertos, n_est), 4),
                                 _num(_razao(acertos, n_ref), 4)])
        for c in CLASSES:
            linhas["pr.csv"].append([rotulo, limiar, c, "", "", _num(_razao(*classes[c]), 4)])
        for c in ("todas", *CLASSES):
            membros = classes_ref == c if c != "todas" else np.ones(len(picos), bool)
            linhas["ativacao.csv"].append(
                [rotulo, limiar, c, int(membros.sum()),
                 _num(_razao(np.sum(picos[membros] >= limiar), membros.sum()), 4)])

    for c in casos:
        erro = c["erro_onset"] * 1000
        linhas["casos.csv"].append([
            rotulo, c["caso"], c["audio"], c["gabarito"], len(c["ref"]),
            f"{c['deslocamento'] * 1000:.1f}", c["origem_deslocamento"],
            _num(np.median(erro) if len(erro) else None, 1),
            _num(np.std(erro) if len(erro) else None, 1),
            _num(c["deriva"], 2),
        ])
        casados = {nome: {i for i, _ in c["resultados"][nome].acertos} for nome in EXTRACOES}
        for i, n in enumerate(c["ref"]):
            linhas["referencias.csv"].append(
                [rotulo, c["caso"], f"{n.onset:.4f}", n.pitch, n.evento, n.classe,
                 "" if n.corda is None else n.corda, "" if n.casa is None else n.casa,
                 _num(c["picos"][i], 4)]
                + [int(i in casados[nome]) for nome in EXTRACOES])
        for nome in EXTRACOES:
            for n, tipo in zip(c["notas"][nome], c["resultados"][nome].tipo_est):
                linhas["deteccoes.csv"].append(
                    [rotulo, c["caso"], nome, f"{n.onset:.4f}", f"{n.offset:.4f}", n.pitch,
                     f"{n.score:.4f}", tipo])


def _arquivos(linhas) -> dict[str, tuple[list[str], list]]:
    erros = list(metricas.TIPOS_DE_ERRO)
    return {
        "casos.csv": (["rotulo", "caso", "audio", "gabarito", "n_ref", "deslocamento_ms",
                       "origem_deslocamento",
                       "erro_onset_mediana_ms", "erro_onset_dp_ms", "deriva_ms_min"],
                      linhas["casos.csv"]),
        "metricas.csv": (["rotulo", "extracao", "classe", "acertos", "n_ref", "n_est",
                          "precisao", "recall", "f"] + erros, linhas["metricas.csv"]),
        "pr.csv": (["rotulo", "limiar", "classe", "n_est", "precisao", "recall"],
                   linhas["pr.csv"]),
        "ativacao.csv": (["rotulo", "limiar", "classe", "n_ref", "recall_ativacao"],
                         linhas["ativacao.csv"]),
        "confiabilidade.csv": (["rotulo", "inicio", "fim", "n", "score_medio",
                                "fracao_correta"], linhas["confiabilidade.csv"]),
        "referencias.csv": (["rotulo", "caso", "onset", "pitch", "evento", "classe", "corda",
                             "casa", "pico_ativacao"] + [f"acerto_{n}" for n in EXTRACOES],
                            linhas["referencias.csv"]),
        "deteccoes.csv": (["rotulo", "caso", "extracao", "onset", "offset", "pitch", "score",
                           "tipo"], linhas["deteccoes.csv"]),
    }


# ── biblioteca do app ───────────────────────────────────────────────

def _musicas() -> list[dict]:
    import sqlite3
    from app_paths import database_path, stems_dir
    from services.separation_service import cached_model

    conexao = sqlite3.connect(f"file:{database_path()}?mode=ro", uri=True)
    conexao.row_factory = sqlite3.Row
    try:
        linhas = conexao.execute(
            "SELECT id, title, artist, file_path, duration_ms FROM songs ORDER BY title"
        ).fetchall()
    finally:
        conexao.close()
    musicas = []
    for linha in linhas:
        cache = stems_dir() / linha["id"]
        guitarra = cache / "guitar.npy"
        musicas.append({
            **dict(linha),
            "guitarra": guitarra if guitarra.exists() else None,
            "modelo": cached_model(cache) if guitarra.exists() else None,
            "cache": cache,
        })
    return musicas


def _stem_de_guitarra(musica: dict) -> tuple[np.ndarray, int]:
    metadados_path = musica["cache"] / "metadata.json"
    taxa = None
    if metadados_path.exists():
        taxa = json.loads(metadados_path.read_text()).get("sample_rate")
    if not taxa:
        import soundfile as sf

        taxa = sf.info(musica["file_path"]).samplerate
    return np.load(musica["guitarra"]), int(taxa)


def _pasta(musica: dict) -> str:
    import re

    nome = re.sub(r"[^\w]+", "-", musica["title"].casefold()).strip("-")
    return f"{nome[:40]}-{musica['id'][:8]}"


def _separar_no_cache(musica: dict):
    """Separa em alta qualidade pelo worker do app, que grava o cache dele."""
    import re
    from services import separation_service as ss

    erros = []
    worker = ss._SepWorker(musica["file_path"], musica["id"], ss.HQ_MODEL)

    def progresso(mensagem):
        parte = re.search(r"(\d+)/(\d+)$", mensagem)
        if not parte or int(parte[1]) % 10 == 0 or parte[1] == parte[2]:
            print(f"  {mensagem}")

    worker.progress.connect(progresso)
    worker.error.connect(erros.append)
    worker.run()
    if erros:
        raise ValueError(f"a separação de {musica['title']} falhou: {erros[0]}")
    musica["modelo"] = ss.cached_model(musica["cache"])


def _ficha_respondida(pasta: Path) -> bool:
    ficha = pasta / "escuta.csv"
    if not ficha.exists():
        return False
    with open(ficha, newline="", encoding="utf-8") as arquivo:
        return any((linha.get("ouvido") or "").strip() for linha in csv.DictReader(arquivo))


def cmd_biblioteca(args):
    from services import basic_pitch as bp
    from services.separation_service import HQ_MODEL
    from validation import escuta

    musicas = _musicas()
    if not args.busca and not args.todas:
        for m in musicas:
            stem = m["modelo"] or "sem stem de guitarra"
            print(f"{m['id'][:8]}  {m['duration_ms'] // 60000}:{m['duration_ms'] // 1000 % 60:02d}"
                  f"  {m['title']}  [{stem}]")
        return
    termo = (args.busca or "").casefold()
    escolhidas = [
        m for m in musicas
        if m["guitarra"] is not None and (
            args.todas or m["id"].startswith(termo) or termo in m["title"].casefold()
            or termo in (m["artist"] or "").casefold())
    ]
    if not escolhidas:
        raise ValueError("nenhuma música com stem de guitarra bate com a busca; "
                         "rode sem argumentos para listar")

    if args.alta_qualidade:
        for m in escolhidas:
            if m["modelo"] != HQ_MODEL:
                print(f"[{m['title']}] separando em alta qualidade...")
                _separar_no_cache(m)

    sessao = bp.load_session()
    resumo = [f"{'música':42s} {'stem':14s} {'notas':>6s} {'2m simult.':>11s} "
              f"{'contestadas':>12s} {'controle':>9s} {'só upstream':>12s}",
              f"{'':42s} {'':14s} {'':>6s} {'up → sem':>11s}"]
    for m in escolhidas:
        print(f"[{m['title']}] analisando o stem de guitarra ({m['modelo']})...")
        stem, taxa = _stem_de_guitarra(m)
        act = bp.infer(stem, taxa, sessao)
        faixa = {"min_pitch": 40, "max_pitch": 88}
        upstream = bp.extract_notes(act, **faixa)
        sem = bp.extract_notes(act, neighbor_suppression=False, **faixa)
        contestadas, controle, so_upstream = escuta.classificar(upstream, sem)
        picos = np.array([act.note[n.start_frame : max(n.end_frame, n.start_frame + 1),
                                   n.pitch - bp.MIDI_OFFSET].max() for n in sem])
        escolhidos = escuta.amostrar(contestadas, controle, args.amostra, args.seed)
        destino = args.saida / _pasta(m)
        if _ficha_respondida(destino):
            print(f"  aviso: {destino}/escuta.csv já tem respostas; mantida como está")
        else:
            escuta.escrever(destino, sem, escolhidos, picos)
            print(f"  {len(escolhidos)} itens de escuta em {destino}/escuta.csv")
        resumo.append(
            f"{m['title'][:42]:42s} {m['modelo']:14s} {len(upstream):6d} "
            f"{escuta.segundas_menores(upstream):4d} → {escuta.segundas_menores(sem):<4d} "
            f"{len(contestadas):12d} {len(controle):9d} {so_upstream:12d}"
        )

    print()
    print("\n".join(resumo))
    print()
    print("2m simult.: pares a um semitom que começam juntos, no upstream e sem a supressão.")
    print("contestadas: notas que só existem sem a supressão e soam junto com uma vizinha a")
    print("um semitom. Controle: notas mantidas pelos dois que soam dentro de um acorde.")
    print()
    print("Escuta: abra cada escuta.csv, vá ao tempo indicado no Transcreve com o stem de")
    print("guitarra solo, e preencha 'ouvido' com 1 (a nota está lá), 0 (não está) ou deixe")
    print("vazio se não der para saber. Não abra chave.csv antes de terminar. Depois:")
    print(f"  python -m validation.notas conferir {args.saida}/*/")


def cmd_conferir(args):
    from validation import escuta

    total = {"contestada": [], "controle": []}
    for pasta in args.pastas:
        julgados = escuta.ler_julgamentos(pasta)
        for grupo, valores in julgados.items():
            total[grupo].extend(valores)
        partes = [f"{g} {sum(v)}/{len(v)}" for g, v in julgados.items()]
        print(f"{pasta.name}: " + ", ".join(partes))
    print()
    for grupo, valores in total.items():
        n, presentes = len(valores), sum(valores)
        lo, hi = escuta.wilson(presentes, n)
        taxa = _fmt(_razao(presentes, n))
        print(f"{grupo:11s} {presentes}/{n} presentes = {taxa}  (IC 95% {_fmt(lo)}–{_fmt(hi)})")
    print()
    print("Se as contestadas estão presentes quase tanto quanto o controle, a supressão de")
    print("vizinhos apaga notas reais e o app deve decodificar sem ela.")


if __name__ == "__main__":
    sys.exit(main())
