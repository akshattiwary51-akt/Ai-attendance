"""Turn a folder dataset (``root/<person>/<file>``) into per-person embeddings using a face engine or voice backend.

Files that cannot be used (unreadable, no face, several faces, unusable audio) are counted, never guessed at.
Embeddings stay in memory: they are not written to disk or logged.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def _files(root: Path, exts: set[str]) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in exts)
        if files:
            out[d.name] = files
    return out


def face_embeddings(root: Path, engine, max_side: int = 1600) -> tuple[dict[str, list[list[float]]], Counter]:
    """One embedding per photo that contains exactly one face."""
    skipped: Counter = Counter()
    result: dict[str, list[list[float]]] = {}
    for person, files in _files(root, IMAGE_EXT).items():
        for f in files:
            try:
                with Image.open(f) as im:
                    im = im.convert("RGB")
                    im.thumbnail((max_side, max_side))
                    faces = engine.detect_and_embed(np.asarray(im))
            except Exception:  # unreadable file or engine failure: count and move on
                skipped["unreadable"] += 1
                continue
            if len(faces) != 1:
                skipped["no_face" if not faces else "several_faces"] += 1
                continue
            result.setdefault(person, []).append(np.asarray(faces[0].embedding, dtype=float).tolist())
    return result, skipped


def voice_embeddings(root: Path, backend, assess: Callable | None = None) -> tuple[dict[str, list[list[float]]], Counter]:
    """One embedding per recording that passes ``assess(wav)`` (an object with ``.ok``), when given."""
    skipped: Counter = Counter()
    result: dict[str, list[list[float]]] = {}
    for person, files in _files(root, AUDIO_EXT).items():
        for f in files:
            try:
                wav = backend.decode(f.read_bytes())
                if assess is not None and not assess(wav).ok:
                    skipped["poor_audio"] += 1
                    continue
                emb = backend.embed(wav)
            except Exception:
                skipped["unreadable"] += 1
                continue
            result.setdefault(person, []).append(np.asarray(emb, dtype=float).tolist())
    return result, skipped
