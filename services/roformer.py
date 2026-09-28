"""Inference-only BS-RoFormer for the optional high-quality stem separation.

The architecture follows Phil Wang's BS-RoFormer (MIT) as adapted by
python-audio-separator (MIT), trimmed to what inference needs so the app does
not depend on beartype or rotary-embedding-torch. Module and parameter names
match the upstream ones so the published checkpoint loads with strict=True.

Checkpoint: "BS-Roformer-SW" (6 stems), downloaded on first use and verified
by SHA-256. The weights are not bundled with the installers.
"""

from collections.abc import Callable
import hashlib
from pathlib import Path
import urllib.request

import torch
from torch import nn
import torch.nn.functional as F
from einops import pack, rearrange, unpack

from app_paths import models_dir

CHECKPOINT_NAME = "BS-Roformer-SW.ckpt"
CHECKPOINT_URL = (
    "https://github.com/nomadkaraoke/python-audio-separator/releases/download/"
    "model-configs/BS-Roformer-SW.ckpt"
)
CHECKPOINT_SHA256 = "24e7d35ee9c64415673d3fd33e06a67cac2c103c5df6267ba1576459c775916e"
CHECKPOINT_BYTES = 699_412_152  # only used for progress messages

SAMPLE_RATE = 44_100
SOURCES = ["bass", "drums", "other", "vocals", "guitar", "piano"]

# BS-Roformer-SW.yaml: stft_hop_length * (inference.dim_t - 1), two windows overlap.
CHUNK_SIZE = 512 * (801 - 1)
CHUNK_STEP = CHUNK_SIZE // 2

FREQS_PER_BANDS = (
    (2,) * 24 + (4,) * 12 + (12,) * 8 + (24,) * 8 + (48,) * 8 + (128, 129)
)
MODEL_CONFIG = dict(
    dim=256,
    depth=12,
    num_stems=len(SOURCES),
    time_transformer_depth=1,
    freq_transformer_depth=1,
    dim_head=64,
    heads=8,
    mask_estimator_depth=2,
    mlp_expansion_factor=4,
)


class RMSNorm(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.scale = dim**0.5
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return F.normalize(x, dim=-1) * self.scale * self.gamma


class RotaryEmbedding(nn.Module):
    """Interleaved rotary embedding compatible with rotary-embedding-torch."""

    def __init__(self, dim: int, theta: float = 10_000):
        super().__init__()
        freqs = 1.0 / (theta ** (torch.arange(0, dim, 2).float() / dim))
        self.freqs = nn.Parameter(freqs, requires_grad=False)

    def rotate(self, t):
        positions = torch.arange(t.shape[-2], device=t.device, dtype=torch.float32)
        angles = torch.einsum("n, f -> n f", positions, self.freqs.float())
        angles = torch.repeat_interleave(angles, 2, dim=-1)
        pairs = rearrange(t, "... (d r) -> ... d r", r=2)
        x1, x2 = pairs.unbind(dim=-1)
        rotated_half = rearrange(torch.stack((-x2, x1), dim=-1), "... d r -> ... (d r)")
        return (t * angles.cos() + rotated_half * angles.sin()).to(t.dtype)


class Attention(nn.Module):
    def __init__(self, dim, heads, dim_head, rotary_embed):
        super().__init__()
        self.heads = heads
        dim_inner = heads * dim_head
        self.rotary_embed = rotary_embed
        self.norm = RMSNorm(dim)
        self.to_qkv = nn.Linear(dim, dim_inner * 3, bias=False)
        self.to_gates = nn.Linear(dim, heads)
        self.to_out = nn.Sequential(nn.Linear(dim_inner, dim, bias=False))

    def forward(self, x):
        x = self.norm(x)
        q, k, v = rearrange(
            self.to_qkv(x), "b n (qkv h d) -> qkv b h n d", qkv=3, h=self.heads
        )
        q = self.rotary_embed.rotate(q)
        k = self.rotary_embed.rotate(k)
        out = F.scaled_dot_product_attention(q, k, v)
        out = out * rearrange(self.to_gates(x), "b n h -> b h n 1").sigmoid()
        return self.to_out(rearrange(out, "b h n d -> b n (h d)"))


class FeedForward(nn.Module):
    def __init__(self, dim, mult=4):
        super().__init__()
        dim_inner = int(dim * mult)
        # Identity slots keep the checkpoint's Sequential indices (dropouts).
        self.net = nn.Sequential(
            RMSNorm(dim),
            nn.Linear(dim, dim_inner),
            nn.GELU(),
            nn.Identity(),
            nn.Linear(dim_inner, dim),
        )

    def forward(self, x):
        return self.net(x)


class Transformer(nn.Module):
    def __init__(self, *, dim, depth, dim_head, heads, rotary_embed):
        super().__init__()
        self.layers = nn.ModuleList(
            nn.ModuleList([
                Attention(dim, heads, dim_head, rotary_embed),
                FeedForward(dim),
            ])
            for _ in range(depth)
        )

    def forward(self, x):
        for attn, ff in self.layers:
            x = attn(x) + x
            x = ff(x) + x
        return x


class BandSplit(nn.Module):
    def __init__(self, dim, dim_inputs):
        super().__init__()
        self.dim_inputs = dim_inputs
        self.to_features = nn.ModuleList(
            nn.Sequential(RMSNorm(dim_in), nn.Linear(dim_in, dim)) for dim_in in dim_inputs
        )

    def forward(self, x):
        bands = x.split(self.dim_inputs, dim=-1)
        return torch.stack([net(band) for band, net in zip(bands, self.to_features)], dim=-2)


class MaskEstimator(nn.Module):
    def __init__(self, dim, dim_inputs, depth, mlp_expansion_factor):
        super().__init__()
        dim_hidden = dim * mlp_expansion_factor
        self.to_freqs = nn.ModuleList()
        for dim_in in dim_inputs:
            dims = (dim, *((dim_hidden,) * (depth - 1)), dim_in * 2)
            layers = []
            for index, (layer_in, layer_out) in enumerate(zip(dims[:-1], dims[1:])):
                layers.append(nn.Linear(layer_in, layer_out))
                if index < len(dims) - 2:
                    layers.append(nn.Tanh())
            self.to_freqs.append(nn.Sequential(nn.Sequential(*layers), nn.GLU(dim=-1)))

    def forward(self, x):
        return torch.cat(
            [mlp(band) for band, mlp in zip(x.unbind(dim=-2), self.to_freqs)], dim=-1
        )


class BSRoformer(nn.Module):
    audio_channels = 2
    n_fft = 2048
    hop_length = 512

    def __init__(
        self,
        *,
        dim,
        depth,
        num_stems,
        time_transformer_depth,
        freq_transformer_depth,
        dim_head,
        heads,
        mask_estimator_depth,
        mlp_expansion_factor,
        freqs_per_bands=FREQS_PER_BANDS,
    ):
        super().__init__()
        self.num_stems = num_stems
        time_rotary = RotaryEmbedding(dim_head)
        freq_rotary = RotaryEmbedding(dim_head)
        common = dict(dim=dim, dim_head=dim_head, heads=heads)
        self.layers = nn.ModuleList(
            nn.ModuleList([
                Transformer(depth=time_transformer_depth, rotary_embed=time_rotary, **common),
                Transformer(depth=freq_transformer_depth, rotary_embed=freq_rotary, **common),
            ])
            for _ in range(depth)
        )
        self.final_norm = RMSNorm(dim)

        assert sum(freqs_per_bands) == self.n_fft // 2 + 1
        dim_inputs = tuple(2 * f * self.audio_channels for f in freqs_per_bands)
        self.band_split = BandSplit(dim, dim_inputs)
        self.mask_estimators = nn.ModuleList(
            MaskEstimator(dim, dim_inputs, mask_estimator_depth, mlp_expansion_factor)
            for _ in range(num_stems)
        )
        self.register_buffer(
            "window", torch.hann_window(self.n_fft), persistent=False
        )

    def forward(self, audio):
        """audio: (batch, 2, samples) -> (batch, stems, 2, samples)"""
        samples = audio.shape[-1]
        stft_kwargs = dict(
            n_fft=self.n_fft, hop_length=self.hop_length, win_length=self.n_fft,
            window=self.window,
        )
        audio, packed_shape = pack([audio], "* t")
        spec = torch.view_as_real(torch.stft(audio, **stft_kwargs, return_complex=True))
        (spec,) = unpack(spec, packed_shape, "* f t c")
        spec = rearrange(spec, "b s f t c -> b (f s) t c")

        x = self.band_split(rearrange(spec, "b f t c -> b t (f c)"))
        for time_transformer, freq_transformer in self.layers:
            x = rearrange(x, "b t f d -> b f t d")
            x, ps = pack([x], "* t d")
            x = time_transformer(x)
            (x,) = unpack(x, ps, "* t d")
            x = rearrange(x, "b f t d -> b t f d")
            x, ps = pack([x], "* f d")
            x = freq_transformer(x)
            (x,) = unpack(x, ps, "* f d")
        x = self.final_norm(x)

        mask = torch.stack([estimate(x) for estimate in self.mask_estimators], dim=1)
        mask = torch.view_as_complex(rearrange(mask, "b n t (f c) -> b n f t c", c=2).contiguous())
        spec = torch.view_as_complex(rearrange(spec, "b f t c -> b 1 f t c").contiguous())
        spec = rearrange(spec * mask, "b n (f s) t -> (b n s) f t", s=self.audio_channels)
        # length= keeps the tail when the input is not a multiple of the hop.
        audio = torch.istft(spec, **stft_kwargs, length=samples)
        return rearrange(
            audio, "(b n s) t -> b n s t", s=self.audio_channels, n=self.num_stems
        )


def checkpoint_path() -> Path:
    return models_dir() / CHECKPOINT_NAME


def is_downloaded() -> bool:
    return checkpoint_path().is_file()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_checkpoint(progress: Callable[[str], None]) -> Path:
    """Download and verify the checkpoint once; later calls return the file."""
    destination = checkpoint_path()
    if destination.is_file():
        return destination

    temporary = destination.with_suffix(destination.suffix + ".download")
    temporary.unlink(missing_ok=True)
    total_mb = CHECKPOINT_BYTES // 1_000_000
    try:
        with urllib.request.urlopen(CHECKPOINT_URL, timeout=120) as response:
            with temporary.open("wb") as output:
                received = 0
                reported_mb = -1
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    received += len(chunk)
                    received_mb = received // 1_000_000
                    if received_mb // 10 != reported_mb // 10:
                        reported_mb = received_mb
                        progress(
                            f"Baixando modelo de alta qualidade... {received_mb}/{total_mb} MB"
                        )
        progress("Verificando modelo baixado...")
        if _sha256(temporary) != CHECKPOINT_SHA256:
            raise RuntimeError("O modelo baixado está corrompido (checksum não confere)")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def inference_device() -> torch.device:
    # MPS lacks some complex STFT ops this model needs; Apple uses the CPU.
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_model(path: Path, device: torch.device) -> BSRoformer:
    model = BSRoformer(**MODEL_CONFIG)
    state = torch.load(path, map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    return model.to(device).eval()


def chunk_starts(length: int) -> list[int]:
    """Chunk offsets covering ``length`` samples; the last one ends at the tail."""
    starts = []
    for offset in range(0, max(length, 1), CHUNK_STEP):
        if offset + CHUNK_SIZE >= length:
            tail = max(length - CHUNK_SIZE, 0)
            if not starts or starts[-1] != tail:
                starts.append(tail)
            break
        starts.append(offset)
    return starts


def demix(
    model: BSRoformer,
    mix: torch.Tensor,
    device: torch.device,
    progress: Callable[[int, int], None] | None = None,
) -> torch.Tensor:
    """Separate a (2, samples) mix at SAMPLE_RATE into (stems, 2, samples).

    Chunks overlap by half and are blended with a Hamming window, as in the
    reference inference code the checkpoint was validated with.
    """
    length = mix.shape[-1]
    window = torch.hamming_window(CHUNK_SIZE, periodic=False)
    result = torch.zeros((model.num_stems, *mix.shape), dtype=torch.float32)
    weight = torch.zeros(length, dtype=torch.float32)
    starts = chunk_starts(length)
    with torch.inference_mode():
        for index, start in enumerate(starts):
            part = mix[:, start : start + CHUNK_SIZE]
            size = part.shape[-1]
            estimate = model(part.unsqueeze(0).to(device))[0].float().cpu()
            result[..., start : start + size] += estimate * window[:size]
            weight[start : start + size] += window[:size]
            if progress:
                progress(index + 1, len(starts))
    return result / weight.clamp(min=1e-10)
