# Plano: Temas + Detecção de Acordes + Separação de Instrumentos

## Fase 1: Temas Selecionáveis

### Objetivo
Permitir trocar entre 4 temas: Catppuccin Mocha (atual), Catppuccin Latte (claro), Dracula, Nord.

### O que implementar

1. **Refatorar `theme.py`** para suportar múltiplos temas:
   - Criar um dict `THEMES` com 4 entradas, cada uma contendo os 15 color constants
   - Variáveis de módulo (BLUE, MANTLE, etc.) apontam para o tema ativo
   - Função `set_theme(name: str)` que atualiza as variáveis e regenera o QSS
   - Função `get_qss() -> str` que gera QSS a partir das variáveis atuais
   - Função `get_theme_names() -> list[str]` para popular o seletor
   - Persistir tema escolhido em `~/.local/share/transcreve/settings.json`

   Paletas:
   - **Catppuccin Mocha** (atual): BASE=#181825, MANTLE=#1E1E2E, TEXT=#CDD6F4, BLUE=#89B4FA...
   - **Catppuccin Latte** (claro): BASE=#EFF1F5, MANTLE=#E6E9EF, TEXT=#4C4F69, BLUE=#1E66F5...
   - **Dracula**: BASE=#282A36, MANTLE=#21222C, TEXT=#F8F8F2, BLUE=#8BE9FD...
   - **Nord**: BASE=#2E3440, MANTLE=#3B4252, TEXT=#ECEFF4, BLUE=#88C0D0...

2. **Adicionar seletor na toolbar da LibraryScreen**:
   - QComboBox com nomes dos temas
   - Ao trocar: chamar `theme.set_theme(name)`, reaplicar `app.setStyleSheet(theme.get_qss())`
   - Salvar escolha em settings.json

3. **Ajustar referências inline nos screens**:
   - As 29 referências inline (f-strings com `theme.BLUE` etc.) continuam funcionando
     pois as variáveis de módulo são atualizadas por `set_theme()`
   - O QSS global precisa ser reaplicado via `QApplication.instance().setStyleSheet()`
   - Para os estilos inline, precisam ser reaplicados — adicionar método `_apply_styles()` 
     nos screens que é chamado após troca de tema

4. **Waveform widget**: 
   - `pyqtgraph.setConfigOptions(background=...)` é chamado no import — precisa reconfigurar
   - Atualizar cores das curvas/markers ao trocar tema

### Verificação
- [ ] 4 temas disponíveis no combo box
- [ ] Trocar tema muda todas as cores (QSS + inline + waveform)
- [ ] Tema persiste ao reiniciar o app
- [ ] Tema claro (Latte) funciona sem texto invisível

---

## Fase 2: Detecção de Acordes

### Objetivo
Ao pressionar uma tecla (ex: D), exibir o acorde detectado na posição atual do playback.

### O que implementar

1. **Criar `services/chord_service.py`**:
   - Classe `ChordService` que recebe audio numpy array + sr
   - No `__init__`, computa chroma para o áudio inteiro:
     ```python
     import librosa
     # converter para mono se necessário
     mono = data.mean(axis=1) if data.ndim == 2 else data
     self._chroma = librosa.feature.chroma_cqt(y=mono, sr=sr, hop_length=512)
     # shape: (12, n_frames)
     self._sr = sr
     self._hop = 512
     ```
   - Método `detect_at(ms: int) -> str`:
     - Converter ms para frame: `frame = int(ms / 1000 * sr / hop_length)`
     - Extrair vetor chroma do frame (12 valores)
     - Comparar com 24 templates (12 major + 12 minor) via dot product
     - Retornar nome do acorde ("C", "Cm", "D", "Dm", etc.)
   - Templates: vetores binários de 12 elementos para cada acorde
     ```python
     # C major = [1,0,0,0,1,0,0,1,0,0,0,0]  (C, E, G)
     # C minor = [1,0,0,1,0,0,0,1,0,0,0,0]  (C, Eb, G)
     # rotacionar para cada nota raiz
     ```
   - Nota: computar chroma é ~2s para 480s de áudio — fazer em background thread

2. **Integrar no PlayerScreen**:
   - Adicionar `_chord_label` (QLabel) ao lado do `_pos_label` na time row
   - Estilo: font bold, cor accent (theme.GREEN ou similar), font-size 14px
   - Keyboard shortcut: **D** — chama `_detect_chord()` que:
     - Pega posição atual do AudioService
     - Chama `chord_service.detect_at(ms)`
     - Atualiza `_chord_label.setText(chord_name)`
   - Opcionalmente: atualizar chord label continuamente durante playback (a cada 500ms via timer)

3. **Computar chroma em background**:
   - Após áudio carregado (no `_on_loading(False)` callback), iniciar QThread
   - ChordService emite signal `ready` quando chroma estiver computado
   - Antes de ready, shortcut D mostra "..." ou "Analisando..."

### APIs (verificadas):
- `librosa.feature.chroma_cqt(y=mono, sr=sr, hop_length=512)` → ndarray (12, t)
- Frame para tempo: `frame * hop_length / sr` (em segundos)
- Template matching: `np.dot(templates, chroma_frame)` → argmax = acorde

### Verificação
- [ ] Chroma computa em background sem travar UI
- [ ] Pressionar D mostra nome do acorde na posição atual
- [ ] Acorde muda ao mover posição e pressionar D novamente
- [ ] Acordes básicos (C, G, Am, Em) são detectados corretamente em músicas reais

---

## Fase 3: Separação de Instrumentos (Demucs)

### Objetivo
Separar música em stems (vocals, drums, bass, other) e permitir mute/solo de cada stem durante playback.

### O que implementar

1. **Criar `services/separation_service.py`**:
   - Classe `SeparationService(QObject)` com signals:
     - `progress(str)` — mensagem de progresso
     - `finished(dict)` — dict com stems numpy arrays
     - `error(str)`
   - Método `separate(file_path: str)`:
     - Roda em QThread
     - Usa `demucs.api.Separator`:
       ```python
       from demucs.api import Separator
       separator = Separator(model="htdemucs", device="cpu")
       origin, separated = separator.separate_audio_file(file_path)
       # separated = {"vocals": tensor, "drums": tensor, "bass": tensor, "other": tensor}
       # converter para numpy: {name: tensor.numpy() for name, tensor in separated.items()}
       ```
     - Emite progresso e resultado
   - Cache: salvar stems em `~/.local/share/transcreve/stems/{song_id}/` como .npy
   - Na próxima vez, carregar do cache sem reprocessar

2. **Modificar AudioService para suportar stems**:
   - Novo método `load_stems(stems: dict[str, np.ndarray])`:
     - Armazena dict de stems (cada um é ndarray [frames, channels])
     - Cria array de mute flags: `_stem_muted: dict[str, bool]`
   - Modificar `_audio_callback` / `_fill_*` methods:
     - Se stems carregados: mixar apenas stems não-mutados
     - `output = sum(stems[name] for name in stems if not muted[name])`
     - Aplicar speed/loop/cue normalmente sobre o mix
   - Métodos: `toggle_stem(name)`, `solo_stem(name)`, `unsolo_all()`
   - O rubberband bridge/chunk precisa operar sobre o mix atual (recalcular ao mutar)

3. **UI no PlayerScreen**:
   - Botão "Separar" na toolbar do player (ao lado do título)
     - Desabilitado se já separado ou em processamento
     - Mostra progress bar durante processamento
   - **Stems panel**: row horizontal abaixo dos loop controls
     - 4 botões toggle: 🎤 Vocals, 🥁 Drums, 🎸 Bass, 🎹 Other
     - Click: toggle mute (dimmed quando muted)
     - Ctrl+Click: solo (só esse stem, outros muted)
     - Visível apenas quando stems estão carregados
   - Cada botão com cor distinta e estado visual claro (ativo/muted)

4. **Instalação de dependências**:
   - `pip install demucs torch torchaudio`
   - Demucs baixa modelo (~200MB) no primeiro uso
   - Aviso ao usuário sobre tempo de processamento (~1.5x duração da música em CPU)

### APIs (verificadas):
- `from demucs.api import Separator`
- `Separator(model="htdemucs", device="cpu")`
- `separator.separate_audio_file(path)` → `(origin_tensor, {"vocals": tensor, ...})`
- Tensors são torch, converter com `.numpy()`
- Stems são stereo, 44100 Hz

### Verificação
- [ ] Botão "Separar" inicia processamento em background
- [ ] Progress é exibido durante separação
- [ ] Stems são cacheados em disco (não reprocessar mesma música)
- [ ] Toggle mute/solo funciona em tempo real durante playback
- [ ] Mutar todos exceto vocals isola a voz corretamente
- [ ] Speed change (rubberband) funciona com stems mutados

---

## Ordem de Execução

```
Fase 1 (Temas) → Fase 2 (Acordes) → Fase 3 (Separação)
```

Cada fase é testável independentemente.

## Dependências Adicionais

```
librosa>=0.11.0          # Fase 2 (já instalado e verificado no Python 3.14)
torch                    # Fase 3
torchaudio               # Fase 3
demucs                   # Fase 3
```
