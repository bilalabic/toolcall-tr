"""Deterministik seed türetimi — yaprak yardımcı modül.

Seed **sıradan bağımsızdır**: doğrudan kimlikten türetilir, çalışma sırasına
göre ilerleyen global bir RNG'den değil. Aksi hâlde blueprint #21 eklemek
#1-20'nin verisini değiştirirdi.

`canonical` gibi bu da bir yaprak: hem `groundtruth` hem `generation`
tarafından import edilebilir, dolayısıyla iki katman aynı seed'i üretir.
"""

from __future__ import annotations

import hashlib
import random

__all__ = ["episode_rng", "episode_seed"]


def episode_seed(root_seed: int, blueprint_id: str, variant_index: int = 0) -> int:
    """`(root_seed, blueprint_id, variant_index)` -> 64 bitlik seed."""
    digest = hashlib.sha256(f"{root_seed}:{blueprint_id}:{variant_index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def episode_rng(root_seed: int, blueprint_id: str, variant_index: int = 0) -> random.Random:
    """Episode'a özgü, yalıtılmış RNG.

    Global `random` modülü **kullanılmaz**: paylaşılan durum, çalışma sırasına
    bağımlılık üretir.
    """
    return random.Random(episode_seed(root_seed, blueprint_id, variant_index))
