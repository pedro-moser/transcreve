# Validação das notas (Fase 0)

Ferramentas para medir se o Basic Pitch acha as notas dos clusters antes de construir a interface. O protocolo e as regras de decisão estão em [`SPEC-notas.md`](../SPEC-notas.md). Os números das regras de decisão são fixados **antes** de rodar a avaliação.

Instalação, a partir da raiz do repositório. Num venv que já tem a instalação completa, basta o runtime ONNX (no macOS, use 1.23.2):

```
.venv/bin/python -m pip install onnxruntime==1.31.0
```

Num ambiente novo com Python 3.12, `-r requirements-validation.txt` instala tudo com as versões fixadas do app.

Todos os comandos rodam da raiz: `.venv/bin/python -m validation.notas <comando> --help`.

## 1. Roteiro e gravação

Escreva os voicings como shapes de tab. O formato está em `roteiro.py` e há um exemplo em `exemplo-roteiro.txt`. Busque pelo menos 40 notas por classe (2ª menor, 2ª maior, 3ª ou mais, isolada), variando região do braço e registro, e inclua uma tomada longa (≥ 5 min) para medir deriva.

```
.venv/bin/python -m validation.notas roteiro meu-roteiro.txt --saida gravacao/
```

Isso gera `gabarito.csv` e `clique.wav`. Grave a guitarra limpa tocando junto com o clique. O ideal é gravar no mesmo projeto do DAW, com a gravação começando junto com o clique. Se não der, a avaliação estima o atraso (até ±1 s).

Para ensaiar o fluxo antes de gravar, `sintetizar` renderiza o roteiro com uma corda sintética. O ensaio não serve para medir a separação, porque os separadores não reconhecem a corda sintética como guitarra.

## 2. Mixes e separação

Use baixo e bateria de um multitrack sem guitarra. A SNR é a potência da guitarra sobre a do acompanhamento, medida na duração inteira.

```
.venv/bin/python -m validation.notas mix gravacao/take.wav --acomp baixo.wav bateria.wav --saida mixes/
.venv/bin/python -m validation.notas separar mixes/mix_snr-6dB.wav --modelo htdemucs_6s --saida stems/demucs-6dB.wav
.venv/bin/python -m validation.notas separar mixes/mix_snr-6dB.wav --modelo bs_roformer_sw --saida stems/roformer-6dB.wav
```

A separação usa o código do app e não toca no cache de stems dele.

## 3. Avaliação

Liste primeiro a tomada isolada de cada gabarito. O atraso é estimado nela e herdado pelos mixes e stems, que saem alinhados amostra a amostra com ela. Casos com o mesmo rótulo são somados.

```
.venv/bin/python -m validation.notas avaliar --saida resultado/ \
    --caso isolado gravacao/take.wav gravacao/gabarito.csv \
    --caso mix-cru-6dB mixes/mix_snr-6dB.wav gravacao/gabarito.csv \
    --caso demucs-6dB stems/demucs-6dB.wav gravacao/gabarito.csv \
    --caso roformer-6dB stems/roformer-6dB.wav gravacao/gabarito.csv
```

`resultado/resumo.txt` traz, por rótulo:

- precisão, recall e F de cada decodificação, com recall por classe e falsos positivos por tipo;
- o recall por limiar de score, lado a lado com a fração de notas do gabarito cujo pico de ativação passa do limiar. Se a ativação existe mas a nota não sai, o problema é o decoder, não o modelo;
- o ECE do score cru e o ECE depois da calibração isotônica.

Os CSVs têm os mesmos números em detalhe, nota a nota em `referencias.csv` e `deteccoes.csv`. `calibracao.json` guarda o mapa score → probabilidade que o app vai usar.

As decodificações comparadas estão em `EXTRACOES`, no início de `notas.py`:

| Nome | O que muda em relação ao upstream |
| --- | --- |
| `upstream` | nada (onset 0,5; frame 0,3; nota com mais de 11 frames; melodia; supressão de vizinhos) |
| `curta` | nota com mais de 5 frames |
| `sem-melodia` | sem o melodia trick |
| `sem-supressao` | sem zerar os semitons vizinhos de cada nota |
| `permissiva` | onset 0,3; frame 0,2; mais de 5 frames; sem supressão |
| `app` | a do Transcreve (`services/note_detection_service.py`): mais de 5 frames, sem supressão. A curva P-R e a calibração usam esta |

## Músicas do app, sem gabarito

As músicas da biblioteca não têm gabarito, então não dão precisão nem recall. Elas respondem a uma pergunta mais estreita, por escuta às cegas: as notas que a supressão de vizinhos apaga existem de verdade?

```
.venv/bin/python -m validation.notas biblioteca            # lista músicas e stems
.venv/bin/python -m validation.notas biblioteca --todas    # ou um trecho do título
```

O comando lê o banco do app em modo só-leitura e usa o stem de guitarra do cache, sem separar nada de novo. Para cada música, decodifica com e sem a supressão e sorteia itens de dois grupos:

- **contestadas**: notas que só aparecem sem a supressão e soam junto com uma vizinha a um semitom;
- **controle**: notas que as duas decodificações mantêm e que soam dentro de um acorde.

A amostra vai, misturada, para `validation/escuta/<música>/escuta.csv`, com só tempo e nota. O grupo de cada item fica em `chave.csv`: não abra antes de terminar.

No Transcreve, vá a cada tempo com o stem de guitarra solo (Ctrl+clique) e preencha `ouvido` com 1 (a nota está lá) ou 0 (não está). Deixe vazio quando não der para saber. Depois:

```
.venv/bin/python -m validation.notas conferir validation/escuta/*/
```

Se a proporção de contestadas presentes chega perto da do controle, a supressão apaga notas reais.
