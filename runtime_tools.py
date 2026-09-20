import hashlib
import os
from pathlib import Path
import platform
import shutil
import sys
import urllib.request

from app_paths import tools_dir


FFMPEG_BASE_URL = (
    "https://raw.githubusercontent.com/imageio/imageio-binaries/master/ffmpeg"
)
FFMPEG_RELEASES = {
    ("win32", "x86_64"): (
        "ffmpeg-win-x86_64-v7.1.exe",
        "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3",
    ),
    ("darwin", "x86_64"): (
        "ffmpeg-macos-x86_64-v7.1",
        "4a4a968b98859588e98500ae25973d80a5ca5eed0724222b9f76360dcb72a001",
    ),
    ("darwin", "arm64"): (
        "ffmpeg-macos-aarch64-v7.1",
        "6d175a4743ca50256e89a8cdd731100f9cee33bd79aeea46894d209410dc6617",
    ),
}


def configure_standard_streams() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def bundle_root() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent


def resource_path(relative: str) -> Path:
    return bundle_root() / relative


def rubberband_executable() -> Path | None:
    configured = os.environ.get("TRANSCREVE_RUBBERBAND_PATH")
    if configured and Path(configured).is_file():
        return Path(configured)

    executable_name = "rubberband.exe" if os.name == "nt" else "rubberband"
    bundled = bundle_root() / "bin" / executable_name
    if bundled.is_file():
        return bundled
    system = shutil.which("rubberband")
    return Path(system) if system else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ffmpeg_platform_key() -> tuple[str, str]:
    machine = platform.machine().lower()
    aliases = {"amd64": "x86_64", "aarch64": "arm64"}
    return sys.platform, aliases.get(machine, machine)


def _download_ffmpeg() -> Path | None:
    release = FFMPEG_RELEASES.get(_ffmpeg_platform_key())
    if release is None:
        return None

    filename, expected_hash = release
    destination = tools_dir() / filename
    if destination.is_file() and _sha256(destination) == expected_hash:
        return destination

    temporary = destination.with_suffix(destination.suffix + ".download")
    temporary.unlink(missing_ok=True)
    url = f"{FFMPEG_BASE_URL}/{filename}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            with temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
        if _sha256(temporary) != expected_hash:
            raise RuntimeError("FFmpeg download checksum mismatch")
        temporary.chmod(0o755)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def ffmpeg_executable(*, allow_download: bool = True) -> Path | None:
    configured = os.environ.get("TRANSCREVE_FFMPEG_PATH")
    if configured and Path(configured).is_file():
        return Path(configured)

    system = shutil.which("ffmpeg")
    if system:
        return Path(system)
    if allow_download:
        return _download_ffmpeg()
    return None


def configure_rubberband() -> Path | None:
    executable = rubberband_executable()
    if executable is None:
        return None

    import pyrubberband.pyrb as pyrb

    setattr(pyrb, "__RUBBERBAND_UTIL", str(executable))
    binary_dir = str(executable.parent)
    current_path = os.environ.get("PATH", "")
    if binary_dir not in current_path.split(os.pathsep):
        os.environ["PATH"] = binary_dir + os.pathsep + current_path
    return executable


def configure_runtime_tools(*, prepare_ffmpeg: bool = False) -> dict[str, Path | None]:
    return {
        "rubberband": configure_rubberband(),
        "ffmpeg": ffmpeg_executable(allow_download=prepare_ffmpeg),
    }
