# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


PROJECT_ROOT = Path(SPECPATH).parent
VENDOR_DIR = PROJECT_ROOT / "packaging" / "vendor"
APP_VERSION = os.environ.get("TRANSCREVE_VERSION", "2.1.0-beta.1")
BUNDLE_VERSION = APP_VERSION.replace("-beta.", ".").replace("-", ".")

binaries = []
vendor_bin = VENDOR_DIR / "bin"
if vendor_bin.exists():
    for binary in vendor_bin.iterdir():
        if binary.is_file():
            binaries.append((str(binary), "bin"))

datas = [
    (str(PROJECT_ROOT / "assets" / "transcreve-icon.png"), "assets"),
    (str(PROJECT_ROOT / "LICENSE"), "."),
    (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]

vendor_licenses = VENDOR_DIR / "licenses"
if vendor_licenses.exists():
    datas.append((str(vendor_licenses), "licenses"))

hiddenimports = []
for package in [
    "demucs",
    "dora",
    "julius",
    "librosa",
    "openunmix",
    "torchaudio",
    "pyrubberband",
    "sounddevice",
    "soundfile",
    "yt_dlp",
]:
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception:
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

for distribution in [
    "demucs",
    "dora-search",
    "librosa",
    "pyrubberband",
    "sounddevice",
    "soundfile",
    "torch",
    "torchaudio",
    "yt-dlp",
]:
    try:
        datas += copy_metadata(distribution, recursive=True)
    except Exception:
        pass

hiddenimports += collect_submodules("demucs")
hiddenimports += collect_submodules("yt_dlp")
hiddenimports += [
    "einops",
    "yaml",
    "tqdm",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors._partition_nodes",
    "sklearn.tree._utils",
    "soxr",
]

analysis = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib.tests", "numpy.tests", "scipy.tests"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

icon = (
    PROJECT_ROOT / "packaging" / "generated" / "transcreve.icns"
    if sys.platform == "darwin"
    else PROJECT_ROOT / "assets" / "transcreve-icon.ico"
)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Transcreve",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon),
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Transcreve",
)

if sys.platform == "darwin":
    app = BUNDLE(
        collect,
        name="Transcreve.app",
        icon=str(icon),
        bundle_identifier="com.pedromoser.transcreve",
        info_plist={
            "CFBundleDisplayName": "Transcreve",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": BUNDLE_VERSION,
            "NSHighResolutionCapable": True,
        },
    )
