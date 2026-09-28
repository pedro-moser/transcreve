# Third-party notices

Transcreve is distributed under the GNU General Public License v3.0 or later. The installers bundle third-party components under their own licenses.

## Rubber Band Library 4.0.0

- Project: <https://breakfastquay.com/rubberband/>
- License: GNU GPL v2.0 or later
- Binary downloads: <https://breakfastquay.com/rubberband/>
- Corresponding source: <https://breakfastquay.com/files/releases/rubberband-4.0.0.tar.bz2>

The release workflow places the unmodified Rubber Band source archive beside the bundled executable under the installer's `licenses` directory.

## FFmpeg

Transcreve installers do not contain FFmpeg. On first launch, when no system FFmpeg is available, the application downloads an unmodified platform binary directly from the public `imageio-binaries` repository and verifies its SHA-256 checksum.

- Project: <https://ffmpeg.org/>
- Binary repository: <https://github.com/imageio/imageio-binaries/tree/master/ffmpeg>
- Source and licensing information: <https://ffmpeg.org/download.html#get-sources>

The downloaded FFmpeg binary is a separate program and remains governed by its upstream license and build configuration.

## BS-RoFormer (optional high-quality separation)

`services/roformer.py` adapts the BS-RoFormer implementation by Phil Wang and its inference code from python-audio-separator, both under the MIT License:

- BS-RoFormer: <https://github.com/lucidrains/BS-RoFormer>, Copyright (c) 2023 Phil Wang
- python-audio-separator: <https://github.com/nomadkaraoke/python-audio-separator>, Copyright (c) 2023 karaokenerds

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The installers do not contain model weights. When a user selects "Alta qualidade", the application downloads the community "BS-Roformer-SW" checkpoint from the python-audio-separator release assets and verifies its SHA-256 checksum. No license is published for these weights.

## Python libraries

The application also bundles Python, PySide6, NumPy, SciPy, SoundFile, SoundDevice, pyqtgraph, yt-dlp, librosa, PyTorch, TorchAudio, Demucs and their transitive dependencies. Their license metadata and notices remain available in the Python package distributions and upstream repositories.

Notable upstream projects:

- PySide6: <https://doc.qt.io/qtforpython-6/licenses.html>
- PyTorch and TorchAudio: <https://github.com/pytorch/pytorch>
- Demucs: <https://github.com/adefossez/demucs>
- librosa: <https://github.com/librosa/librosa>
- yt-dlp: <https://github.com/yt-dlp/yt-dlp>

The complete source code and build scripts for Transcreve are available at <https://github.com/pedro-moser/transcreve>.
