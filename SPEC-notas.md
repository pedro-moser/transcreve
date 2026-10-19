# Transcreve — spec de visualização de notas

15 out 2026 · @Pedro · rev. 2, auditada contra o código (`local/alta-qualidade`, 2da36ff)

## Objetivo e princípios

Mostrar as notas detectadas alinhadas à waveform do Transcreve, como apoio para tirar de ouvido, não como transcrição automática.

- **Eixo de tempo real, sem quantização rítmica.** As notas aparecem onde soam, alinhadas à waveform, ao loop A–B e às seções.
- **Incerteza visível e calibrada.** Opacidade e limiar usam a probabilidade de acerto medida na validação, não a ativação crua do modelo.
- **Evidência além do modelo.** Uma camada mostra o sinal (CQT) independentemente do que o modelo acha. É ela que socorre o ouvido onde o modelo é cego.
- **O usuário decide, e a decisão sobrevive.** Posição, grafia e tonalidade, e também rejeitar, adicionar e corrigir notas. As edições sobrevivem a reanálise e a mudança de limiar.
- **Um dado, várias vistas.** Piano-roll, tab e partitura saem do mesmo pitch soando.

## Fases

| Fase | Entrega | Depende de |
| --- | --- | --- |
| 0 | Validação offline (script, sem UI). Ferramentas prontas em `validation/`; falta gravar | — |
| 1 | Faixa piano-roll (CQT/posteriorgrama + notas) com vista de detalhe. Versão mínima feita (ver Decisões, item 4); faltam CQT/posteriorgrama, calibração e edição | Fase 0 decidir a camada principal |
| 2 | Tab (Viterbi + fixar posição). Versão inicial feita (ver Decisões, item 5); faltam afinação e capotraste por música | Fase 1 |
| 3 | Partitura sem compasso, grafia e tonalidade | Fase 1 |
| 4 | Instrumentos transpositores | Fase 3, e só se houver uso real |

As fases 2 e 3 são independentes entre si.

## Pipeline de análise

Roda uma vez por música. O resultado fica em `analysis/{song_id}/` na pasta de dados do app, ao lado de `stems/{song_id}/`.

1. **Stem de guitarra.** Usa o stem que estiver em cache: `htdemucs_6s` (Padrão) ou BS-RoFormer SW (Alta qualidade). A análise registra qual stem usou e é invalidada quando a separação é refeita ou promovida para Alta qualidade. Se a Fase 0 mostrar que a separação não ajuda, roda no mix.
2. **Afinação global.** `librosa.estimate_tuning` no stem. Se o desvio passar de ~15 cents, reamostra a entrada para corrigir antes do modelo e reescala os tempos pelo mesmo fator. Sem isso, disco antigo fora de A440 cai entre semitons.
3. **Basic Pitch** via `nmp.onnx` + onnxruntime, não pelo pacote `basic-pitch` (ver Dependências). Feito em `services/basic_pitch.py`, que porta o janelamento (`inference.py`) e a extração de notas (`note_creation.py`). Com os mesmos parâmetros, a extração dá as mesmas notas que o código original. Duas correções em relação ao upstream:
   - o upstream corta a saída em `floor(n × 86 / 22050)` frames, mas o grid real anda a ~86,6 fps, e por isso os últimos ~0,7% do áudio (2 s em 5 min) nunca eram transcritos;
   - o tempo de cada frame vem das janelas, não do `model_frames_to_time` do upstream, que aproxima com um "magic number" e deixa um dente de serra de ±8 ms. No sintético, o desvio-padrão do erro de onset caiu de 5,6 para 3,9 ms.
4. **Guardar as matrizes e o vetor de tempos:**
   - ativação de nota (frames × 88), de onset (frames × 88) e contour (frames × 264, 1/3 de semitom);
   - `times[]`, o tempo de cada frame. O grid não é uniforme: frames a um hop de distância dentro da janela, com um salto a cada 142 frames. Desenhar o mapa com espaçamento uniforme o desalinha das notas em ~1,5 s ao fim de 5 min;
   - quantizado em uint8 num `.npz`: ~11 MB crus para 5 min, menos depois de comprimido.
5. **CQT do stem** (36 bins por oitava, só a extensão da afinação) para a camada de sinal, no mesmo cache.
6. **Extrair as notas uma vez, com parâmetros permissivos** (limiares de onset e frame baixos, duração mínima curta). O limiar da interface **filtra** essas notas por probabilidade calibrada e não re-segmenta. A lista fica estável e as edições não ficam órfãs.
   - Os defaults do Basic Pitch não servem para jazz: uma nota precisa de mais de 11 frames (≥ ~139 ms) para sobreviver. Em legato, colcheia some acima de ~215 bpm e semicolcheia acima de ~108 bpm.
   - **O decoder do upstream apaga 2ª menor por construção.** Depois de extrair cada nota, ele zera a energia restante dos semitons vizinhos durante toda a nota. Numa 2ª menor simultânea, a nota decodificada depois (a de baixo, quando os onsets coincidem) é descartada, por mais forte que seja a ativação dela. No sintético, o B3 do cluster B3–C4–D4 tinha pico 0,78 e sumiu. A extração do app desliga essa supressão (`neighbor_suppression=False`), e a Fase 0 mede quanto isso custa em falsos positivos.
   - Os parâmetros finais saem da Fase 0.

## Modelo de dados

**Notas detectadas.** São derivadas e recalculáveis, nunca editadas diretamente.

| Campo | Tipo | Origem |
| --- | --- | --- |
| `id` | hash de (pitch, frame de onset, versão da análise) | derivado |
| `onset`, `offset` | segundos, tempo da música | Basic Pitch + `times[]` |
| `pitch` | MIDI, soando | Basic Pitch |
| `score` | 0–1, ativação média de frame ao longo da nota | Basic Pitch (é o que ele chama de amplitude e usa como velocity) |
| `p` | 0–1, probabilidade de a nota estar certa | `score` passado pelo mapa de calibração da Fase 0 |

**Edições do usuário.** Ficam numa tabela própria no SQLite.

| Tipo | Dados |
| --- | --- |
| `posicao` | corda, casa |
| `grafia` | letra + acidente, em concert |
| `rejeitar` | — |
| `pitch` | pitch corrigido (erro de oitava, semitom vizinho) |
| `adicionar` | onset, offset, pitch (nota que o modelo perdeu) |

Cada edição se ancora em (pitch, onset) com tolerância de ~50 ms, não no `id`. Ao reanalisar, as edições são re-ancoradas. As que ficarem sem nota correspondente aparecem como órfãs para o usuário resolver e nunca somem caladas. `adicionar` não precisa de âncora.

**Nível da música.** Hoje `Song` só guarda seções e anotações; isto entra numa tabela nova.

- tonalidade: tônica + modo (maior/menor), default C maior;
- afinação (MIDI de cada corda, default E padrão) e capotraste;
- limiar de exibição;
- instrumento da partitura (Fase 4; até lá, guitarra);
- metadados da análise: modelo do stem, hash do `nmp.onnx`, parâmetros de extração, desvio de afinação, versão.

O override de grafia é salvo em concert, para sobreviver a trocas de instrumento.

## Visualização

O app é PySide6 + pyqtgraph, sem canvas nem SVG. VexFlow e alphaTab são bibliotecas JS e não se aplicam. Os glifos de partitura vêm da fonte SMuFL Bravura (OFL, compatível com GPL).

**Pré-requisito: vista de detalhe.** A waveform atual mostra sempre a música inteira em 120 px de altura (`setMouseEnabled(x=False)`, `setXRange(0, duration)`). Com 5 min numa janela de 1400 px, isso dá ~5 px/s, e um número de casa precisa de ~8 px. A proposta:

- a waveform atual vira **visão geral**, com um retângulo marcando a janela visível;
- abaixo dela, **faixas de detalhe** num `GraphicsLayoutWidget` com eixo X ligado (`setXLink`). A janela é o loop A–B quando ele está ativo; senão, ±N s em torno do playhead, acompanhando a reprodução. Zoom com a roda;
- clicar nas faixas de detalhe edita notas, e clicar na visão geral continua sendo seek. Assim a edição não briga com o seek por clique que existe hoje.

**Faixas.** Cada faixa tem seu próprio eixo Y; o eixo X é compartilhado.

1. **Piano-roll**, com Y em semitons recortado na extensão da afinação (E2–E6 em E padrão):
   - fundo: CQT (sinal) ou posteriorgrama (modelo), alternável;
   - por cima: notas acima do limiar, com opacidade por `p`.
2. **Tab.**
3. **Partitura sem compasso.**

Cada faixa pode ser ligada ou desligada. Abaixo de uma densidade mínima de px/s, tab e partitura mostram só as barras de duração, sem números nem cabeças. O colormap do mapa de calor precisa funcionar no tema claro (Latte) e nos escuros.

**Tab**

- Número da casa no onset, seguido de uma barra até o offset.
- A posição vem de um Viterbi sobre eventos: notas com onsets a até ~30–50 ms umas das outras (ajustável) formam o mesmo evento, cobrindo o strum.
- Restrições duras: uma nota por corda; a corda fica ocupada enquanto a nota soa; abertura máxima da mão (~4–5 casas, sem contar cordas soltas).
- Custo: deslocamento da mão, sem preferência por posições baixas (ver Decisões, item 5), com pesos ajustáveis.
- Evento impossível de digitar (geralmente uma nota espúria) é marcado, não forçado.
- Fixar a posição de uma nota vira restrição dura e o Viterbi roda de novo, para as vizinhas se reorganizarem em volta.

**Partitura sem compasso**

- Cabeça de nota no tempo real, com a duração como linha horizontal, igual à tab.
- Como não há compasso, a regra de que o acidente vale até a barra não existe: acidente em toda nota fora da armadura, com bequadro explícito.
- Segundas simultâneas levam as cabeças deslocadas para lados opostos, como na notação convencional. É exatamente o caso dos clusters.
- Guitarra: clave de sol com 8 embaixo, fixa. Clave e 8va automáticas só entram na Fase 4.

**Controles**

- Slider de limiar (filtra por `p`).
- Liga/desliga das faixas e alternância CQT/posteriorgrama.
- Tonalidade (tônica + modo), afinação e capotraste.
- Atalhos novos não podem usar Espaço, setas, `[`, `]`, A, B, C, D, L e M, que já estão em uso.

## Grafia e tonalidade

**Regra default (sem override), em ordem**

1. Nota diatônica segue a armadura.
2. Nota cromática em trecho monofônico, com vizinha a um semitom: direção melódica. Sobe com #, desce com b. Vale em qualquer tom, não só em C.
3. Nota cromática em simultaneidade ou sem direção definida: tabela fixa por grau.
   - Maior: b2, b3, #4, b6, b7.
   - Menor: 3ª, 6ª e 7ª maiores como alteração ascendente da própria letra (F#, B e C# em Ré menor; nunca Db), e b2 e #4 como no maior.

**Override manual**

- Um gesto na nota alterna entre as grafias enarmônicas possíveis (C# / Db / B##).
- O override fica salvo em concert, na tabela de edições.
- Trocar a tonalidade recalcula só as notas sem override.

## Transposição (Fase 4)

O instrumento é definido pelo intervalo de transposição como par (passos de letra, semitons), não só pelo nome. Saxofone tenor e clarinete são ambos Bb, mas ficam em oitavas diferentes.

| Instrumento | Escrito em relação ao som | Intervalo | Concert C vira |
| --- | --- | --- | --- |
| C (flauta, piano, voz) | igual | (0, 0) | C |
| Guitarra, contrabaixo | 8ª acima | (7, 12) | C |
| Trompete, clarinete, sax soprano (Bb) | 2ª maior acima | (1, 2) | D |
| Sax tenor, clarone (Bb) | 9ª maior acima | (8, 14) | D |
| Sax alto (Eb) | 6ª maior acima | (5, 9) | A |
| Sax barítono (Eb) | 6ª maior + 8ª acima | (12, 21) | A |
| Trompa (F) | 5ª justa acima | (4, 7) | G |

**Regras**

- Transpor aplica o intervalo a todas as notas e à armadura, com os overrides junto. Eb concert vira F no instrumento em Bb, nunca E#.
- A escolha enarmônica da armadura troca o intervalo por um enarmônico de mesmos semitons. Com concert E maior no instrumento em Bb, fica F# maior por 2ª maior (1, 2) ou Gb maior por 3ª diminuta (2, 2). O G# concert vira A# no primeiro caso e Bb no segundo. Aplicada a todas as notas, essa regra é a que concilia "preservar a grafia" com "escolher Gb".
- Se a transposição passar de dois acidentes (B## + 2ª maior = C###), a nota é reescrita na enarmônica com menos acidentes.
- A extensão escrita de cada instrumento decide clave e 8va.
- A tab não muda com o instrumento: é sempre da guitarra.

## Fase 0: validação

**Hipótese central.** O Basic Pitch, rodando no stem de guitarra, detecta notas em clusters de 2ª com recall e precisão úteis.

**Corpus**

- **Voicings roteirizados**, tocados com clique, com posição e onset conhecidos. O gabarito sai do roteiro.
  - Classes pela menor distância a uma nota simultânea: 2ª menor, 2ª maior, 3ª ou mais, e nota isolada.
  - Pelo menos 40 instâncias por classe (intervalo de confiança de ±15 pp no recall), espalhadas por região do braço e registro.
  - Uma tomada longa (≥ 5 min) para medir deriva temporal.
- **Mixes sintéticos**: a gravação isolada somada a baixo + bateria de um multitrack, em SNR controlada (por exemplo 0, −6 e −12 dB). O gabarito é o mesmo e não é preciso gravar um trio. Baixo andando no registro grave da guitarra é o confundidor real.
- **Faixas reais** (Lage Lund etc.), só para checagem qualitativa.

**Condições.** Isolado; mix → `htdemucs_6s`; mix → BS-RoFormer; mix sem separação. Cada condição é cruzada com as decodificações de `EXTRACOES` (`validation/notas.py`): a do upstream, duração mínima de 5 frames, sem melodia trick, sem supressão de vizinhos, uma permissiva e a do app (`app`), que é a que o limiar do app filtra e a que a calibração usa.

**Medidas**

- Precisão, recall e F por nota com `mir_eval.transcription` (onset ±50 ms, offset ignorado), por classe de intervalo e por condição. Precisão importa tanto quanto recall: uma nota fantasma sólida engana o ouvido.
- Curva precisão-recall varrendo o limiar, em vez de recall num limiar só. Ao lado dela, a fração de notas do gabarito cujo pico de ativação passa de cada limiar: o modelo vê a nota? Essa medida separa modelo cego de limiar mal posto e de decoder que descarta a nota.
- Erros de oitava e de semitom vizinho com `score` alto.
- Viés e deriva de onset ao longo da tomada longa, para conferir `times[]`.
- Calibração: diagrama de confiabilidade (`score` × acerto), ajuste isotônico que gera o mapa `score → p` usado pelo app, e ECE antes e depois.

**Regras de decisão** (os números são fixados antes de rodar)

- Se o recall de 2ª menor no isolado for ≥ __ com precisão ≥ __, as notas sólidas são a camada principal.
- Se a 2ª menor some no `upstream` mas aparece em `sem-supressao`, o problema é o decoder: o app decodifica sem supressão, e a escolha passa pela precisão.
- Se o recall for baixo no limiar de operação mas a ativação passar do limiar, o posteriorgrama vira a camada principal: o modelo vê, o limiar esconde.
- Se for baixo nos dois, o modelo é cego para clusters. O posteriorgrama não resolve, porque é a mesma evidência. A CQT vira a camada principal, e passa a valer testar outro modelo.
- Se mix → stem for muito pior que o isolado, o gargalo é a separação: comparar os dois separadores e o mix cru.

**Outro modelo.** TabCNN e FretNet não têm checkpoint pronto: exigem treino no GuitarSet, que é violão de aço gravado em estúdio, longe da guitarra elétrica de jazz. O candidato mais relevante é Riley, Edwards & Dixon (ICASSP 2024), treinado em transcrições de guitarra jazz e com resultado zero-shot de ponta no GuitarSet. Falta confirmar se há checkpoint público. Só vale o esforço se a Fase 0 mostrar o Basic Pitch cego.

## Dependências e distribuição

- `basic-pitch` 0.4.0, a última versão no PyPI, exige `tensorflow<2.15.1` em Python ≥ 3.11. Esse TensorFlow não tem wheel para 3.12 (CI) nem 3.14 (venv local), então o pacote não instala.
- Feito: o `nmp.onnx` do próprio wheel (Apache-2.0, compatível com GPL-3) está em `assets/models/`, com LICENSE e NOTICE do Basic Pitch. O `onnxruntime` está em `requirements-full*.txt`, fixado por plataforma: 1.31.0, ou 1.23.2 no macOS, onde é a última com wheel para macOS 13 + Python 3.12 (há wheel x86_64 e arm64). O modelo e as licenças entram no `transcreve.spec`, e o smoke test do pacote roda o modelo.
- O `mir_eval` não é necessário: `validation/metricas.py` reproduz a regra de casamento dele com o `scipy`.
- Alternativa sem dependência nova: rodar a rede em torch, que já é distribuído para o Demucs. Existem ports comunitários com paridade numérica declarada.
- Basic Pitch (Apache-2.0) já está no `THIRD_PARTY_NOTICES.md`; Bravura (OFL) entra com a Fase 3.

## Fora de escopo

- Quantização rítmica, compassos e figuras rítmicas.
- Exportação para Guitar Pro ou PDF.
- Transcrição de outros instrumentos além da guitarra.
- Articulações (bend, slide, vibrato, hammer-on). O contour fica guardado; até lá, um slide aparece como sequência de notas curtas.
- Separação de vozes e mais de uma guitarra no mesmo stem.

## Decisões tomadas nesta revisão

1. **Prior de acorde removido.** O detector atual (`services/chord_service.py`) compara o chroma do mix com 24 tríades, maiores e menores. Num cluster 1–2–7, a 2ª e a 7ª são incompatíveis com qualquer tríade, então o prior apagaria justamente as notas que a Fase 0 quer achar. Pelo mesmo motivo saiu o refinamento de grafia por função no acorde: o detector não consegue dizer E7. Volta se houver um detector com tétrades.
2. **Edição de notas incluída** (rejeitar, adicionar, corrigir pitch). Sem ela, "o usuário decide" para na grafia e na posição, e um erro de oitava fica sem conserto.
3. **Transposição adiada** para a Fase 4, porque só a guitarra é transcrita. O modelo de dados já fica pronto para ela (pitch e grafia em concert).
4. **Fase 1 mínima antes do fim da Fase 0** (19 out 2026, decisão do Pedro depois de uma tomada piloto de guitarra limpa, gravada no celular, com voicings sem fundamental). Na tomada, a supressão de vizinhos apagou o G4 do voicing C#4–G4–G#4 nas duas vezes em que ele soou, com score 0,72 e 0,66, maior que o do G#4; sem a supressão, ele volta com o onset certo. O app (`services/note_detection_service.py`) decodifica com onset 0,5, frame 0,3, mais de 5 frames e sem supressão, e filtra pelo score cru, sem calibração. A decodificação `permissiva` do passo 6 ficou de fora: com onset 0,3, a ondulação da ativação de onset numa nota sustentada abre notas novas, e um G4 de 3 s virou um fragmento de 0,07 s (528 notas na tomada, contra 192). O mapa de calibração da Fase 0 precisa ser medido com a decodificação que o app usa. A vista mínima tem piano-roll com zoom pela roda, segue o playhead ou mostra o loop A–B e usa o stem de guitarra do cache, sem CQT, posteriorgrama, calibração ou edição.
5. **Tab com mão parada** (19 out 2026, escolha do Pedro). O SPEC preferia casas baixas e cordas soltas, o que não combina com voicings fechados sem fundamental. Em `services/fretting.py`:
   - **Mão:** o estado do Viterbi inclui a posição da mão (indicador na casa h, cobrindo até h + 4), e cada casa de deslocamento custa 1. Medir só a distância entre formas consecutivas deixava a mão escorregar de casa em casa até a primeira posição sem custo nenhum.
   - **Corda solta:** custa 2 e não move a mão.
   - **Acima da casa 12:** cada casa custa 0,5. Sem isso, harmônicos agudos com score acima do limiar (um A5 só cabe na corda e, casa 17) levantavam a mão, e a passagem inteira ficava lá: em One More Song, 44% das notas acima da casa 12, contra 14% agora.
   - **Notas fora da forma:** um acorde pode deixar uma nota fora da digitação, a 10 × score, e ela aparece em vermelho. Com mais de 6 notas ou forma impossível, saem as de menor score.
   - **Eventos:** onsets encadeados a até 50 ms um do outro, com no máximo 120 ms, e a mesma nota duas vezes no evento vira uma. Fragmentos em eventos diferentes não são emendados, porque engoliriam notas repetidas.
   - **Correção:** clicar num número oferece as outras posições. A escolha vira restrição dura, guardada em `note_edits` (`kind = 'posicao'`, âncora em pitch + onset ±50 ms). Numa mesma corda do mesmo acorde, a correção mais nova vence; as órfãs aparecem na contagem.
   - **Afinação:** E padrão fixo, sem capotraste.
