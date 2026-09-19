# Transcreve

Ferramenta desktop para transcrição e estudo musical, desenvolvida em Python com PySide6.

## Recursos

- Importação de arquivos de áudio locais
- Download de áudio do YouTube com `yt-dlp`
- Visualização da waveform e navegação precisa
- Controle de velocidade com preservação de tom
- Loop A–B e cue point
- Marcadores de seções e anotações
- Persistência local em SQLite

## Requisitos

- Python 3.11 ou superior
- FFmpeg
- Rubber Band Library
- PortAudio e libsndfile

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Execução

```bash
python main.py
```

Os dados da biblioteca são armazenados localmente em `~/.local/share/transcreve/`.
