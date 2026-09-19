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
- Detecção de acordes e separação de instrumentos na instalação completa

## Antes de começar

O Transcreve ainda não possui instalador de um clique (`.exe`, `.dmg` ou AppImage). A instalação é feita com alguns comandos, mas não exige conhecimento de programação. Escolha abaixo as instruções do seu sistema operacional e copie cada comando exatamente como aparece.

Requer **Python 3.11 ou superior**. Para seguir os comandos abaixo, recomenda-se o **Python 3.12**. A instalação básica já permite baixar músicas do YouTube, reproduzir, alterar a velocidade, criar loops, marcar seções e fazer anotações.

## 1. Baixar o Transcreve

Este passo é igual no Windows, macOS e Linux:

1. Abra <https://github.com/pedro-moser/transcreve>.
2. Clique no botão verde **Code**.
3. Clique em **Download ZIP**.
4. Quando o download terminar, extraia o arquivo ZIP.
5. Será criada uma pasta com nome parecido com `transcreve-main`. Não apague essa pasta depois da instalação.

Depois disso, siga apenas a seção correspondente ao seu sistema.

---

## Windows 10 ou 11

### 2. Instalar Python, FFmpeg e Rubber Band

1. Abra o menu Iniciar.
2. Digite **PowerShell**.
3. Abra o **Windows PowerShell** normalmente. Não é necessário executar como administrador.
4. Cole os comandos abaixo, um de cada vez, pressionando Enter depois de cada comando:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

```powershell
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression
```

```powershell
scoop bucket add versions
```

```powershell
scoop install versions/python312 ffmpeg rubberband
```

Esses comandos usam o [Scoop](https://scoop.sh/), um instalador de programas para Windows. Quando terminarem, feche e abra o PowerShell novamente.

Confira se tudo foi instalado:

```powershell
python --version
ffmpeg -version
rubberband --version
```

O primeiro comando deve mostrar `Python 3.12`.

### 3. Abrir o PowerShell na pasta do Transcreve

1. Abra no Explorador de Arquivos a pasta `transcreve-main` extraída anteriormente.
2. Clique na barra de endereço da pasta.
3. Digite `powershell` e pressione Enter.
4. Uma janela do PowerShell será aberta já na pasta correta.

### 4. Instalar o Transcreve

Cole os comandos abaixo, um de cada vez:

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

A instalação pode levar alguns minutos.

### 5. Abrir o Transcreve

Ainda dentro da pasta, execute:

```powershell
.\.venv\Scripts\python.exe main.py
```

Nas próximas vezes, basta abrir o PowerShell nessa pasta e repetir somente o último comando.

---

## macOS

As instruções funcionam em Macs com Apple Silicon e em Macs Intel ainda compatíveis com o Homebrew.

### 2. Instalar o Homebrew

1. Abra **Aplicativos → Utilitários → Terminal**.
2. Cole o comando abaixo e pressione Enter:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

O instalador pode pedir a senha do Mac. Enquanto você digita, nenhum caractere aparece na tela; isso é normal.

Ao terminar, o Homebrew pode mostrar uma seção chamada **Next steps**. Se ela aparecer, copie e execute os comandos indicados antes de continuar. Mais informações estão no [site oficial do Homebrew](https://brew.sh/).

### 3. Instalar Python, FFmpeg e Rubber Band

No Terminal, execute:

```bash
brew install python@3.12 ffmpeg rubberband portaudio libsndfile
```

Confira a instalação:

```bash
python3.12 --version
ffmpeg -version
rubberband --version
```

### 4. Abrir a pasta do Transcreve no Terminal

1. Digite `cd ` no Terminal, incluindo o espaço depois de `cd`.
2. Arraste a pasta `transcreve-main` do Finder para dentro da janela do Terminal.
3. Pressione Enter.

### 5. Instalar o Transcreve

Execute os comandos abaixo, um de cada vez:

```bash
python3.12 -m venv .venv
```

```bash
./.venv/bin/python -m pip install --upgrade pip
```

```bash
./.venv/bin/python -m pip install -r requirements.txt
```

### 6. Abrir o Transcreve

```bash
./.venv/bin/python main.py
```

Nas próximas vezes, abra o Terminal na pasta do Transcreve e repita somente esse último comando.

---

## Linux

### Ubuntu, Debian ou Linux Mint

1. Abra o Terminal.
2. Instale os programas necessários:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg rubberband-cli libportaudio2 libsndfile1 libxcb-cursor0
```

### Arch Linux, CachyOS ou Manjaro

```bash
sudo pacman -S --needed python python-pip ffmpeg rubberband portaudio libsndfile
```

### Instalar o Transcreve

Depois de baixar e extrair o ZIP:

1. Abra a pasta `transcreve-main` no gerenciador de arquivos.
2. Clique com o botão direito em uma área vazia e escolha **Abrir no Terminal**. O nome da opção pode variar conforme o ambiente gráfico.
3. Execute os comandos abaixo:

```bash
python3 -m venv .venv
```

```bash
./.venv/bin/python -m pip install --upgrade pip
```

```bash
./.venv/bin/python -m pip install -r requirements.txt
```

### Abrir o Transcreve

```bash
./.venv/bin/python main.py
```

Nas próximas vezes, abra o Terminal nessa pasta e repita somente o último comando.

---

## Instalação completa: acordes e separação de instrumentos

Esta etapa é opcional. Ela instala `librosa`, PyTorch e Demucs para ativar a detecção de acordes e a separação da música em voz, bateria, baixo e outros instrumentos.

> A instalação completa baixa arquivos grandes e pode ocupar vários gigabytes. A primeira separação também baixa o modelo do Demucs e pode demorar bastante em computadores sem GPU.

No **Windows**, execute dentro da pasta do Transcreve:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-full.txt
```

No **macOS ou Linux**:

```bash
./.venv/bin/python -m pip install -r requirements-full.txt
```

Depois, abra o programa normalmente.

## Atualizar o Transcreve

As músicas, marcações e anotações ficam fora da pasta do programa, em `.local/share/transcreve` dentro da pasta pessoal do usuário. Por isso, atualizar o código não apaga a biblioteca.

Para atualizar:

1. Baixe novamente o ZIP mais recente no GitHub.
2. Extraia a nova pasta.
3. Repita os passos de criação do `.venv` e instalação das dependências.
4. Abra o programa pela nova pasta.
5. Depois de confirmar que está funcionando, a pasta antiga pode ser apagada.

## Solução de problemas

### O download do YouTube parou de funcionar

O YouTube muda com frequência. Atualize o `yt-dlp`.

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade yt-dlp
```

macOS ou Linux:

```bash
./.venv/bin/python -m pip install --upgrade yt-dlp
```

### A velocidade diferente de 1× não funciona

Confira se o Rubber Band está instalado:

```bash
rubberband --version
```

Se o comando não existir, repita a etapa de instalação de programas do seu sistema operacional.

### O download termina, mas o áudio não é convertido

Confira o FFmpeg:

```bash
ffmpeg -version
```

Se o comando não existir, repita a instalação do FFmpeg.

### O Windows diz que `python` não foi encontrado

Feche todas as janelas do PowerShell, abra uma nova e tente novamente. Se ainda não funcionar, repita:

```powershell
scoop install versions/python312
```

### O Linux mostra erro relacionado a `xcb`

Em Ubuntu, Debian ou Linux Mint, execute:

```bash
sudo apt install libxcb-cursor0
```

## Onde ficam os dados

O Transcreve guarda banco de dados, músicas baixadas e cache em uma pasta oculta dentro da pasta pessoal do usuário:

- **Windows:** `C:\Users\SEU_NOME\.local\share\transcreve\`
- **macOS:** `/Users/SEU_NOME/.local/share/transcreve/`
- **Linux:** `/home/SEU_NOME/.local/share/transcreve/`, também representada por `~/.local/share/transcreve/`

Esses dados não são enviados ao GitHub. Faça backup dessa pasta para preservar toda a biblioteca.
