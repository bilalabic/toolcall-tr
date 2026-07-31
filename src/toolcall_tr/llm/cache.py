"""LLM yanıt önbelleği.

Yeniden çalıştırmayı bedava yapar; bu, iterasyon isteğini doğrudan değiştirir.
Prompt'u bir kez ayarlayıp korpusu on kez yeniden üretmek pahalıysa kimse
prompt'u ayarlamaz.

Anahtar `(prompt_version, blueprint_id, variant_index)` üçlüsüdür: prompt
sürümü artınca önbellek doğal olarak geçersizleşir.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from toolcall_tr.canonical import sha256_of, short_hash
from toolcall_tr.llm.base import LLMResponse

__all__ = ["LLMCache"]


class LLMCache:
    """Disk tabanlı, içerik-adresli yanıt önbelleği."""

    def __init__(self, root: Path, *, enabled: bool = True) -> None:
        self.root = Path(root)
        self.enabled = enabled

    def key(
        self,
        *,
        prompt_version: str,
        blueprint_id: str,
        variant_index: int,
        provider: str,
        model: str,
    ) -> str:
        """Önbellek anahtarı.

        ``provider`` ve ``model`` anahtara **dahildir**. Olmasaydı model
        karşılaştırması sessizce bozulurdu: ilk modelin yanıtı ikinciye
        servis edilir ve tablo anlamsızlaşırdı.
        """
        return sha256_of(
            {
                "prompt_version": prompt_version,
                "blueprint_id": blueprint_id,
                "variant_index": variant_index,
                "provider": provider,
                "model": model,
            }
        )

    def _path(self, key: str) -> Path:
        digest = short_hash(key, 64)
        return self.root / digest[:2] / f"{digest[2:]}.json"

    def get(self, key: str) -> LLMResponse | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResponse(**{**data, "cached": True})

    def put(self, key: str, response: LLMResponse) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(response)
        payload["cached"] = False
        path.write_text(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
