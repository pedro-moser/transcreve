# Plano de Portabilidade: Transcreve (Flutter → Python + PySide6)

## Visao Geral

Portar o app Transcreve de Flutter/Dart para Python + PySide6, mantendo todas as funcionalidades existentes e adicionando: waveform visualization, seekbar de alta precisao, time-stretching com rubberband, e arquitetura pronta para separacao de instrumentos com IA.

## Stack

| Componente | Biblioteca |
|------------|-----------|
| GUI | PySide6 (Qt6) |
| Audio I/O | sounddevice + soundfile |
| Time-stretch | pyrubberband (librubberband) |
| Waveform | pyqtgraph |
| YouTube | yt-dlp (Python API) |
| Persistencia | SQLite (via sqlite3 stdlib) |
| IDs | uuid (stdlib) |

## Estrutura de Diretórios (Alvo)

```
transcreve-py/
├── main.py                  # Entry point
├── requirements.txt
├── models/
│   ├── __init__.py
│   ├── song.py              # Song dataclass
│   └── section.py           # Section dataclass
├── services/
│   ├── __init__.py
│   ├── audio_service.py     # Playback engine (sounddevice + rubberband)
│   ├── storage_service.py   # SQLite persistence
│   └── youtube_service.py   # yt-dlp wrapper
├── screens/
│   ├── __init__.py
│   ├── library_screen.py    # Song list UI
│   └── player_screen.py     # Player + editor UI
├── widgets/
│   ├── __init__.py
│   ├── waveform_widget.py   # pyqtgraph waveform display
│   └── seekbar_widget.py    # Custom seekbar with markers
└── theme.py                 # Catppuccin colors + QSS
```

---

## Fase 1: Fundacao (Models + Storage + Theme)

### Objetivo
Criar a base do projeto: modelos de dados, persistencia SQLite, tema visual, e janela principal com navegacao entre telas.

### Tarefas

1. **Criar `requirements.txt`**
   ```
   PySide6>=6.6
   numpy
   soundfile
   sounddevice
   pyrubberband
   pyqtgraph
   yt-dlp
   ```

2. **Criar `models/song.py` e `models/section.py`**
   - Usar `@dataclass` com `dataclasses_json` ou conversao manual dict
   - Song: id, title, artist, file_path, youtube_url, sections, notes, duration_ms, added_at
   - Section: id, name, start_ms, end_ms, color_hex, notes
   - Manter os mesmos campos do Flutter

3. **Criar `services/storage_service.py`**
   - SQLite via `sqlite3` (stdlib, sem dependencia extra)
   - Tabelas: `songs`, `sections` (FK song_id)
   - Metodos: init(), get_songs(), save_song(), delete_song(), get_song()
   - Sections serializadas como JSON na tabela songs OU tabela separada
   - Ordenar por added_at DESC

4. **Criar `theme.py`**
   - Constantes de cores Catppuccin Mocha (mesmas do Flutter):
     - BASE=#181825, SURFACE=#1E1E2E, OVERLAY=#313244, SUBTEXT=#45475A
     - BLUE=#89B4FA, GREEN=#A6E3A1, PEACH=#FAB387, TEAL=#94E2D5, RED=#F38BA8
     - MAUVE=#CBA6F7, YELLOW=#F9E2AF
   - Funcao que retorna QSS string para aplicar no app
   - Estilizar: QMainWindow, QListWidget, QPushButton, QSlider, QTextEdit, QScrollBar

5. **Criar `main.py`**
   - QApplication + QMainWindow
   - QStackedWidget para alternar LibraryScreen <-> PlayerScreen
   - Inicializar StorageService
   - Aplicar tema QSS

### Verificacao
- [ ] `python main.py` abre janela vazia com tema dark Catppuccin
- [ ] StorageService cria banco SQLite, CRUD funciona (testar manualmente)
- [ ] Models serializam/deserializam corretamente

---

## Fase 2: Library Screen

### Objetivo
Recriar a tela de biblioteca com lista de musicas, import local, e placeholder para YouTube.

### Tarefas

1. **Criar `screens/library_screen.py`**
   - QWidget com QVBoxLayout
   - Toolbar: titulo "Transcreve", botoes "Abrir arquivo" (folder icon) e "YouTube" (link icon)
   - QListWidget com items customizados (QListWidgetItem + custom widget):
     - Icone music_note
     - Titulo (bold), Artista - Duracao - N secoes (subtitle)
     - Botao delete (icon)
   - Estado vazio: label centralizado "Biblioteca vazia"
   - Loading state: progress bar + status label

2. **Implementar import de arquivo local**
   - QFileDialog.getOpenFileName() com filtro de audio
   - Ler duracao via soundfile: `sf.info(path).duration`
   - Criar Song, salvar no storage, atualizar lista

3. **Implementar navegacao para PlayerScreen**
   - Sinal clicked na lista → emitir signal com Song
   - MainWindow recebe signal, troca QStackedWidget para PlayerScreen

### Verificacao
- [ ] Lista de musicas aparece com dados corretos
- [ ] Import de arquivo local funciona (MP3, WAV, FLAC)
- [ ] Delete remove musica da lista e do banco
- [ ] Click em musica abre PlayerScreen (mesmo que vazio)

---

## Fase 3: Audio Engine

### Objetivo
Implementar o servico de audio com playback via sounddevice, time-stretching via rubberband, e controle preciso de posicao.

### Tarefas

1. **Criar `services/audio_service.py`**
   - Carregar audio com soundfile: `data, sr = sf.read(path)` (todo em memoria para seeks rapidos)
   - Playback via `sounddevice.OutputStream` com callback
   - O callback le frames do buffer numpy, aplica speed se != 1.0
   
2. **Implementar controle de velocidade com rubberband**
   - Pre-processar chunks com `pyrb.time_stretch(chunk, sr, rate)`
   - Ou: manter buffer pre-processado para a velocidade atual
   - Estrategia: processar em blocos (ex: 4096 frames) no callback
   - Quando speed muda: reprocessar buffer a partir da posicao atual

3. **Implementar interface publica**
   - Signals Qt (PySide6 Signal):
     - `position_changed(int)` — posicao em ms
     - `duration_changed(int)` — duracao em ms  
     - `playing_changed(bool)` — estado play/pause
   - Metodos: load(), play(), pause(), toggle_play(), seek(ms), seek_relative(delta_ms)
   - Metodos: set_speed(float), get_speed(), get_position(), get_duration()
   - QTimer para emitir position_changed a cada ~30ms durante playback

4. **Implementar A-B Loop**
   - Propriedades: loop_start, loop_end, loop_enabled
   - No callback do sounddevice: se posicao >= loop_end, voltar para loop_start
   - Metodos: set_loop_start(), set_loop_end(), toggle_loop(), clear_loop()

5. **Implementar Cue Point**
   - Propriedade: cue_point (int ms ou None)
   - play() verifica cue_point antes de iniciar
   - Metodos: set_cue_point(), clear_cue_point()

### Verificacao
- [ ] Arquivo de audio toca sem distorcao
- [ ] Seek funciona com precisao de ~10ms
- [ ] Speed 0.5x e 1.5x soam naturais (qualidade rubberband)
- [ ] Loop A-B repete corretamente
- [ ] Cue point funciona ao dar play

### Notas Tecnicas
- sounddevice callback roda em thread separada — nao chamar Qt GUI de dentro dele
- rubberband pode ter latencia — considerar pre-buffer
- Para seeks instantaneos: manter indice de frame no array numpy

---

## Fase 4: Player Screen (Controles Basicos)

### Objetivo
Recriar a tela do player com controles de playback, speed, e loop.

### Tarefas

1. **Criar `screens/player_screen.py`**
   - Layout principal: QVBoxLayout
   - Header: botao voltar + titulo/artista
   - Area central: placeholder para seekbar + waveform (Fase 5)
   - Controles de playback: prev section, -5s, play/pause, +5s, next section
   - Controle de velocidade: QSlider horizontal (0.25-2.0) + label + reset "1x"
   - Controles de loop: botoes A, Loop toggle, B, Clear

2. **Conectar AudioService**
   - Signals do AudioService → atualizar UI (posicao, estado, duracao)
   - Botoes → chamar metodos do AudioService
   - Speed slider → set_speed()

3. **Implementar keyboard shortcuts**
   - Usar QShortcut + QKeySequence:
     - Space: toggle_play
     - Left/Right: seek +-5s
     - Ctrl+Left/Right: prev/next section
     - [ / ]: speed -/+ 0.1
     - L: toggle loop
     - A/B: set loop start/end
     - M: add section
     - C: set cue point
   - Shortcuts devem funcionar enquanto PlayerScreen estiver ativa

4. **Implementar painel de notas**
   - QTextEdit para notas da musica
   - Auto-save no onChanged (com debounce de 500ms via QTimer)

### Verificacao
- [ ] Todos os controles respondem e atualizam o AudioService
- [ ] Keyboard shortcuts funcionam
- [ ] Speed slider reflete valor correto
- [ ] Notas persistem apos fechar e reabrir

---

## Fase 5: Waveform + Seekbar (NOVO)

### Objetivo
Criar visualizacao de waveform com pyqtgraph e seekbar de alta precisao, substituindo o CustomPainter do Flutter.

### Tarefas

1. **Criar `widgets/waveform_widget.py`**
   - pyqtgraph.PlotWidget embutido
   - Ao carregar musica: ler amostras com soundfile, downsample para ~2000 pontos
   - Plotar waveform como curva (amplitude vs tempo)
   - Estilo: linha fina cyan/blue sobre fundo dark
   - Desabilitar eixos, grid, mouse interaction padrao

2. **Adicionar marcadores visuais ao waveform**
   - **Playhead**: pg.InfiniteLine vertical, branca, atualizada via QTimer (~30fps)
   - **Loop region**: pg.LinearRegionItem (peach, semi-transparente)
     - Draggable para ajustar loop com mouse
     - Sincronizado com AudioService.loop_start/loop_end
   - **Section markers**: pg.InfiniteLine para cada secao (cor da secao)
     - Label com nome da secao no topo
   - **Cue point**: pg.InfiniteLine (teal, tracejada)

3. **Implementar seek por click/drag no waveform**
   - Click no waveform → seek para posicao
   - Drag do playhead → scrub em tempo real
   - Precisao: converter pixel → sample → millisecond

4. **Criar `widgets/seekbar_widget.py`** (opcional, simplificado)
   - QSlider customizado com QSS para estilo minimal
   - Ou: reusar o waveform como seekbar principal (preferido)
   - Se waveform for o seekbar: adicionar time labels abaixo (posicao atual / duracao)

### Verificacao
- [ ] Waveform renderiza corretamente para arquivos MP3, WAV, FLAC
- [ ] Playhead se move suavemente durante playback
- [ ] Loop region aparece e e arrastavel
- [ ] Section markers aparecem nas posicoes corretas
- [ ] Click/drag no waveform faz seek preciso
- [ ] Performance: sem lag visivel em arquivos de 10+ minutos

### Notas Tecnicas
- Downsample o waveform para display: `np.abs(data[::step]).max(axis=1)` ou similar
- pyqtgraph PlotWidget aceita arrays numpy diretamente — sem conversao necessaria
- LinearRegionItem.sigRegionChangeFinished para atualizar loop no AudioService

---

## Fase 6: Sections + YouTube

### Objetivo
Implementar gerenciamento de secoes e download do YouTube.

### Tarefas

1. **Implementar secoes no PlayerScreen**
   - Painel lateral esquerdo (QWidget colapsavel):
     - Header: "Secoes" + botao add (+) + botao collapse
     - QListWidget com items: cor | nome | tempo
     - Context menu (right-click): Renomear, Mover para posicao, Excluir
     - Click: seek para secao + selecionar
   - Notas da secao: QTextEdit abaixo da lista (quando secao selecionada)
   - Cores ciclicas: mesma paleta Catppuccin do Flutter (7 cores)

2. **Criar `services/youtube_service.py`**
   - Usar yt-dlp como biblioteca Python (nao subprocess):
     ```python
     ydl_opts = {
         'format': 'bestaudio/best',
         'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '0'}],
         'outtmpl': f'{music_dir}/%(title)s.%(ext)s',
         'noplaylist': True,
         'progress_hooks': [progress_callback],
     }
     with yt_dlp.YoutubeDL(ydl_opts) as ydl:
         info = ydl.extract_info(url, download=True)
     ```
   - Extrair: title, uploader (artist), filepath
   - Progress hook → emitir signal para atualizar UI

3. **Integrar YouTube na LibraryScreen**
   - Dialog para URL (QInputDialog ou custom)
   - Download em QThread separada (nao bloquear UI)
   - Progress bar durante download
   - Ao concluir: criar Song, salvar, atualizar lista

### Verificacao
- [ ] Adicionar secao com M, aparece na lista e no waveform
- [ ] Renomear, mover, excluir secao funcionam
- [ ] Notas da secao persistem
- [ ] Download do YouTube funciona com progresso visivel
- [ ] Arquivo baixado aparece na biblioteca e toca normalmente

---

## Fase 7: Polish + Migracao de Dados

### Objetivo
Ajustes finais, migracao de dados do Hive, e preparacao para distribuicao.

### Tarefas

1. **Migrar dados do Hive (Flutter) para SQLite**
   - Script opcional: ler boxes Hive com Python (ou exportar JSON do Flutter)
   - Importar songs e sections para o novo banco SQLite

2. **Ajustes de UX**
   - Tooltips nos botoes
   - Feedback visual (hover, pressed states) via QSS
   - Confirmacao antes de deletar (QMessageBox)
   - Tratamento de erros com QMessageBox (arquivo nao encontrado, download falhou)
   - Redimensionamento da janela (splitter entre secoes e notas)

3. **Distribuicao**
   - Script com PyInstaller ou nuitka para gerar binario
   - Desktop file (.desktop) para integracao com Linux
   - Ou: simples `pip install -e .` com pyproject.toml

### Verificacao
- [ ] Dados antigos do Flutter migrados (se aplicavel)
- [ ] App inicia sem erros em instalacao limpa
- [ ] Todas as funcionalidades do Flutter original estao presentes
- [ ] Waveform e rubberband funcionam como esperado

---

## Fase Futura: Separacao de Instrumentos (IA)

### Objetivo (nao implementar agora, apenas preparar arquitetura)
Integrar Demucs ou similar para separar vocais, baixo, bateria, etc.

### Arquitetura preparada
- AudioService ja trabalha com numpy arrays → Demucs retorna numpy arrays
- Possivel adicionar: `services/separation_service.py`
  - `separate(audio_data, sr) → dict[str, ndarray]` (vocals, drums, bass, other)
  - Rodar em QThread com progress signal
- UI futura: toggles para mute/solo de cada stem no PlayerScreen
- O waveform pode exibir stems separados em cores diferentes

### Dependencias futuras
```
torch
demucs
```

---

## Ordem de Execucao

```
Fase 1 → Fase 2 → Fase 3 → Fase 4 → Fase 5 → Fase 6 → Fase 7
  |         |         |         |         |         |         |
  Base    Library   Audio    Player   Waveform  Sections  Polish
                    Engine   Controls           +YouTube
```

Cada fase e independente o suficiente para testar antes de avancar.
