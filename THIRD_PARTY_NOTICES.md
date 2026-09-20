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

## Python libraries

The application also bundles Python, PySide6, NumPy, SciPy, SoundFile, SoundDevice, pyqtgraph, yt-dlp, librosa, PyTorch, TorchAudio, Demucs and their transitive dependencies. Their license metadata and notices remain available in the Python package distributions and upstream repositories.

Notable upstream projects:

- PySide6: <https://doc.qt.io/qtforpython-6/licenses.html>
- PyTorch and TorchAudio: <https://github.com/pytorch/pytorch>
- Demucs: <https://github.com/adefossez/demucs>
- librosa: <https://github.com/librosa/librosa>
- yt-dlp: <https://github.com/yt-dlp/yt-dlp>

The complete source code and build scripts for Transcreve are available at <https://github.com/pedro-moser/transcreve>.
