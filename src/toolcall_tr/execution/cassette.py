"""Cassette (record/replay) katmanı — yeniden üretilebilirliğin temeli.

Gerçek zamanlı bir API her çağrıda farklı veri döndürür; bu, doğrulanabilir bir
veri setiyle doğrudan çelişir. Cassette katmanı her HTTP yanıtını
içerik-adresli olarak saklar ve pipeline'ı replay modunda çalıştırır.

Üç tasarım kararı kasıtlıdır:

**Anahtar HTTP isteğinden türetilir, tool argümanından değil.**
    Tool şeması repodaki en oynak artefakttır. Cassette'leri ona bağlamak, bir
    parametre eklendiğinde ilgili tüm kayıtları yetim bırakır. İsteği
    hash'lemek ayrıca aynı endpoint'i kullanan iki tool'un tek kaydı
    paylaşmasını sağlar.

**Katman bir ``httpx.BaseTransport``'tur, executor değil.**
    Executor'lar cassette'ten habersizdir; kendilerine verilen istemciyi
    kullanırlar. M2 mock'unun ``ASGITransport``'u ile aynı şekle oturur.

**Depolama içerik-adreslidir ve shard'lıdır.**
    Aynı gövde (ör. sayısız boş ``[]`` yanıtı) tek blob olarak saklanır. 2
    karakterlik sharding Windows'ta MAX_PATH sorununu önler -- 64 karakterlik
    dosya adları + derin checkout sınıra yaklaşır.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import httpx

from toolcall_tr.canonical import CANONICAL_JSON_VERSION, canonical_bytes, sha256_hex, sha256_of

__all__ = [
    "SENSITIVE_HEADERS",
    "STORED_RESPONSE_HEADERS",
    "CassetteEntry",
    "CassetteLimitError",
    "CassetteMissError",
    "CassetteMode",
    "CassetteStore",
    "CassetteTransport",
    "NoNetworkTransport",
    "request_key",
]

#: Ne anahtara ne de diske girer. Kimlik bilgisi execution altyapısına aittir,
#: veriye değil.
SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "x-auth-token",
        "authentication",
    }
)

#: Yanıttan saklanan başlıklar. Beyaz liste: ``date``, ``server``, ``x-request-id``
#: gibi her çağrıda değişen başlıklar hash'i kirletir ve gereksiz diff üretir.
STORED_RESPONSE_HEADERS: frozenset[str] = frozenset(
    {"content-type", "expires", "last-modified", "etag"}
)

_MISS_MESSAGE = (
    "Cassette bulunamadı: {key}\n"
    "  {method} {url}\n"
    "Replay modunda ağa çıkılmaz. Kaydı oluşturmak için:\n"
    "  TOOLCALL_TR_CASSETTE_MODE=record uv run toolcall-tr cassette record"
)


class CassetteMode(StrEnum):
    """Cassette çalışma modu.

    ``bypass`` kasıtlı olarak yoktur: adı "footgun" olan bir moddu. Canlı
    çağrı gerekirse ``record`` kullanılır ve kayıt bırakılır.
    """

    #: Her istek ağa gider ve kaydedilir (mevcut kaydın üzerine yazar).
    RECORD = "record"
    #: Yalnızca kayıttan okunur. Kayıt yoksa hata. CI varsayılanı.
    REPLAY = "replay"
    #: Kayıt varsa oynatılır, yoksa ağa gidilip kaydedilir.
    RECORD_MISSING = "record_missing"


class CassetteMissError(RuntimeError):
    """Replay modunda kaydı olmayan bir istek yapıldı."""


class CassetteLimitError(RuntimeError):
    """Sağlayıcı için tanımlı kayıt üst sınırı aşıldı.

    Lisansı belirsiz kaynaklarda (bkz. ``LICENSE-DATA`` § 3) kayıt sayısı
    kasıtlı olarak sınırlıdır: toplu yeniden dağıtım riski taşır.
    """


def _scrub(headers: Mapping[str, str], keep: frozenset[str] | None = None) -> dict[str, str]:
    """Hassas başlıkları atar; ``keep`` verilirse yalnızca onları tutar."""
    out: dict[str, str] = {}
    for name, value in headers.items():
        lowered = name.lower()
        if lowered in SENSITIVE_HEADERS:
            continue
        if keep is not None and lowered not in keep:
            continue
        out[lowered] = value
    return out


def request_key(request: httpx.Request, *, header_allowlist: frozenset[str] = frozenset()) -> str:
    """İsteğin içerik kimliği.

    Query parametreleri sıralanır: ``?a=1&b=2`` ile ``?b=2&a=1`` aynı kaydı
    bulur. Gövde canonical JSON'a normalize edilebiliyorsa edilir, edilemiyorsa
    ham byte'ları hash'lenir.
    """
    url = request.url
    query: list[list[str]] = sorted([key, value] for key, value in url.params.multi_items())

    body: Any = None
    raw = request.content
    if raw:
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"__raw_sha256__": sha256_hex(raw)}

    return sha256_of(
        {
            "v": CANONICAL_JSON_VERSION,
            "method": request.method.upper(),
            "scheme": url.scheme,
            "host": url.netloc.decode("ascii"),
            "path": url.path,
            "query": query,
            "body": body,
            "headers": _scrub(request.headers, keep=header_allowlist),
        }
    )


def _encode_body(content: bytes, content_type: str) -> tuple[str, Any]:
    """Gövdeyi saklanabilir biçime çevirir.

    JSON gövdeler ayrıştırılarak saklanır: diff'lenebilir olurlar ve
    ``type_skeleton`` ile drift analizi yapılabilir.
    """
    if not content:
        return "empty", None
    if "json" in content_type:
        try:
            return "json", json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    try:
        return "text", content.decode("utf-8")
    except UnicodeDecodeError:
        return "base64", base64.b64encode(content).decode("ascii")


def _decode_body(encoding: str, body: Any) -> bytes:
    if encoding == "empty":
        return b""
    if encoding == "json":
        return canonical_bytes(body)
    if encoding == "text":
        return str(body).encode("utf-8")
    if encoding == "base64":
        return base64.b64decode(str(body))
    raise ValueError(f"bilinmeyen gövde kodlaması: {encoding!r}")


class CassetteEntry:
    """Index'teki tek bir kayıt. Blob gövdeleri ayrı dosyalarda tutulur."""

    __slots__ = ("blobs", "key", "metadata")

    def __init__(self, key: str, blobs: tuple[str, ...], metadata: dict[str, Any]) -> None:
        self.key = key
        self.blobs = blobs
        self.metadata = metadata

    def to_json(self) -> dict[str, Any]:
        return {"key": self.key, "blobs": list(self.blobs), **self.metadata}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CassetteEntry:
        payload = dict(data)
        key = str(payload.pop("key"))
        blobs = tuple(str(b) for b in payload.pop("blobs"))
        return cls(key=key, blobs=blobs, metadata=payload)


class CassetteStore:
    """Bir sağlayıcının kayıt deposu.

    Dizin yapısı::

        <root>/<namespace>/index.jsonl        anahtar -> blob + metadata
        <root>/<namespace>/blobs/ab/cdef....json
        <root>/MANIFEST.json                  sayım + global hash

    ``index.jsonl`` anahtara göre **sıralı** yazılır: deterministik ve PR'da
    okunabilir kalır.
    """

    def __init__(
        self,
        root: Path,
        namespace: str,
        *,
        license: str = "UNDETERMINED",
        attribution: str | None = None,
        max_entries: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.namespace = namespace
        self.license = license
        self.attribution = attribution
        self.max_entries = max_entries
        self._entries: dict[str, CassetteEntry] = {}
        self._dirty = False
        self.load()

    # -- yollar ------------------------------------------------------------

    @property
    def dir(self) -> Path:
        return self.root / self.namespace

    @property
    def index_path(self) -> Path:
        return self.dir / "index.jsonl"

    def blob_path(self, blob_id: str) -> Path:
        """Shard'lı blob yolu. Windows'ta MAX_PATH için zorunlu."""
        digest = blob_id.split(":", 1)[-1]
        return self.dir / "blobs" / digest[:2] / f"{digest[2:]}.json"

    # -- yükleme / kaydetme ------------------------------------------------

    def load(self) -> None:
        self._entries.clear()
        if not self.index_path.is_file():
            return
        with self.index_path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    entry = CassetteEntry.from_json(json.loads(stripped))
                    self._entries[entry.key] = entry

    def save(self) -> None:
        if not self._dirty:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(self._entries[key].to_json(), sort_keys=True, ensure_ascii=False)
            for key in sorted(self._entries)
        ]
        # LF sabit: .gitattributes cassette'lerde satır sonu dönüşümünü kapatır,
        # burada da platform bağımlı yazım yapılmaz.
        self.index_path.write_text(
            "".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n"
        )
        self._dirty = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.save()

    # -- okuma / yazma -----------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def keys(self) -> frozenset[str]:
        return frozenset(self._entries)

    def get(self, key: str) -> CassetteEntry | None:
        return self._entries.get(key)

    def read_blob(self, blob_id: str) -> dict[str, Any]:
        path = self.blob_path(blob_id)
        if not path.is_file():
            raise CassetteMissError(f"blob dosyası eksik: {blob_id} ({path})")
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        actual = sha256_of(data)
        if actual != blob_id:
            raise CassetteMissError(
                f"blob bütünlük hatası: beklenen {blob_id}, hesaplanan {actual} ({path})"
            )
        return data

    def write_blob(self, payload: dict[str, Any]) -> str:
        """Gövdeyi içerik-adresli olarak yazar; aynı içerik tek kez saklanır."""
        blob_id = sha256_of(payload)
        path = self.blob_path(blob_id)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        return blob_id

    def record(
        self,
        key: str,
        *,
        request: httpx.Request,
        response: httpx.Response,
        sequenced: bool = False,
        git_sha: str | None = None,
        recorder_version: str = "0.1.0",
    ) -> None:
        """Bir yanıtı kaydeder.

        ``sequenced`` verildiğinde aynı anahtar için yeni yanıt listeye eklenir
        (aynı episode içinde meşru olarak değişen tool'lar). Varsayılan davranış
        üzerine yazmaktır: örneklerin çoğu tek yanıtlıdır ve %5'lik durumun
        maliyetini hepsine ödetmeyiz.
        """
        existing = self._entries.get(key)
        if (
            existing is None
            and self.max_entries is not None
            and len(self._entries) >= self.max_entries
        ):
            raise CassetteLimitError(
                f"{self.namespace}: kayıt üst sınırı ({self.max_entries}) aşıldı. "
                "Lisansı belirsiz kaynaklarda kayıt sayısı kasıtlı olarak sınırlıdır."
            )

        content = response.content
        content_type = response.headers.get("content-type", "")
        encoding, body = _encode_body(content, content_type)

        blob_id = self.write_blob(
            {
                # Atıf her blob'un İÇİNDE tutulur: tek bir dosya depodan
                # çıkarıldığında dahi CC BY yükümlülüğünü taşısın.
                "attribution": {
                    "license": self.license,
                    "attribution": self.attribution,
                    "upstream_url": str(request.url),
                    "modified": (
                        "Canonical JSON'a normalize edildi; başlıklar beyaz listeye göre budandı."
                    ),
                },
                "status": response.status_code,
                "headers": _scrub(response.headers, keep=STORED_RESPONSE_HEADERS),
                "body_encoding": encoding,
                "body": body,
            }
        )

        blobs = (*existing.blobs, blob_id) if (sequenced and existing is not None) else (blob_id,)

        self._entries[key] = CassetteEntry(
            key=key,
            blobs=blobs,
            metadata={
                "method": request.method.upper(),
                "upstream_url": str(request.url),
                "http_status": response.status_code,
                "response_sha256": sha256_hex(content),
                "recorded_at": datetime.now(UTC).isoformat(),
                "recorder_version": recorder_version,
                "git_sha": git_sha,
                "license": self.license,
            },
        )
        self._dirty = True

    def prune(self, used_keys: Iterable[str]) -> tuple[str, ...]:
        """Kullanılmayan kayıtları ve artık başvurulmayan blob'ları siler.

        Yetim kayıt yalnızca ölü ağırlık değildir: lisansı belirsiz
        kaynaklarda (bkz. ``LICENSE-DATA`` § 3) gereksiz yere dağıtım
        yüzeyi büyütür. Bu yüzden blob dosyaları da temizlenir.
        """
        used = set(used_keys)
        orphans = tuple(sorted(set(self._entries) - used))
        if not orphans:
            return ()

        for key in orphans:
            del self._entries[key]
        self._dirty = True

        # Hiçbir kaydın başvurmadığı blob'lar da gitmeli.
        referenced = {blob for entry in self._entries.values() for blob in entry.blobs}
        blobs_dir = self.dir / "blobs"
        if blobs_dir.is_dir():
            for path in blobs_dir.rglob("*.json"):
                blob_id = f"sha256:{path.parent.name}{path.stem}"
                if blob_id not in referenced:
                    path.unlink()
            for shard in sorted(blobs_dir.iterdir(), reverse=True):
                if shard.is_dir() and not any(shard.iterdir()):
                    shard.rmdir()

        return orphans

    def orphans(self, used_keys: Iterable[str]) -> tuple[str, ...]:
        """Hiçbir örnek tarafından kullanılmayan kayıtlar."""
        return tuple(sorted(set(self._entries) - set(used_keys)))

    def index_hash(self) -> str:
        return sha256_of([self._entries[key].to_json() for key in sorted(self._entries)])

    def stats(self) -> dict[str, Any]:
        return {
            "count": len(self._entries),
            "index_hash": self.index_hash(),
            "license": self.license,
        }


def write_manifest(root: Path, stores: Iterable[CassetteStore]) -> str:
    """`MANIFEST.json` yazar ve global hash'i döner.

    Manifest elle düzenlemeyi yakalar ve ``EnvironmentFingerprint``'in
    ``cassette_manifest_hash`` alanını besler.
    """
    providers = {store.namespace: store.stats() for store in stores}
    payload: dict[str, Any] = {
        "canonical_json_version": CANONICAL_JSON_VERSION,
        "providers": dict(sorted(providers.items())),
    }
    payload["manifest_hash"] = sha256_of(payload)
    root.mkdir(parents=True, exist_ok=True)
    (root / "MANIFEST.json").write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return str(payload["manifest_hash"])


def read_manifest_hash(root: Path) -> str | None:
    path = root / "MANIFEST.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("manifest_hash")
    return str(value) if value is not None else None


class NoNetworkTransport(httpx.BaseTransport):
    """Her isteği reddeder.

    Replay modunda iç taşıma katmanı olarak kullanılır: bir yapılandırma
    regresyonu "doğrulanmış" bir derlemeyi sessizce canlı-getirme derlemesine
    çeviremesin.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raise CassetteMissError(
            f"Ağ erişimi kapalı ancak istek yapıldı: {request.method} {request.url}"
        )


class CassetteTransport(httpx.BaseTransport):
    """Cassette destekli HTTP taşıma katmanı."""

    def __init__(
        self,
        store: CassetteStore,
        mode: CassetteMode = CassetteMode.REPLAY,
        *,
        inner: httpx.BaseTransport | None = None,
        header_allowlist: frozenset[str] = frozenset(),
        sequenced_keys: frozenset[str] = frozenset(),
        git_sha: str | None = None,
    ) -> None:
        self.store = store
        self.mode = mode
        self.header_allowlist = header_allowlist
        #: Aynı episode içinde yanıtı meşru olarak değişen **istek anahtarları**.
        #: Tool kimliği değil: anahtar isteğe bağlıdır ve önceden bilinemez, bu
        #: yüzden executor `mark_sequenced()` ile çalışma anında bildirir.
        self.sequenced_keys: set[str] = set(sequenced_keys)
        self.git_sha = git_sha
        self._inner = inner if inner is not None else NoNetworkTransport()
        #: Episode başına sıralı yanıt imleci.
        self._cursor: dict[str, int] = {}
        self._response_sanitizers: dict[str, Callable[[Any], Any]] = {}
        #: Bu çalıştırmada gerçekten kullanılan anahtarlar -- yetim tespiti için.
        self.used_keys: set[str] = set()

    def reset_cursors(self) -> None:
        """Yeni episode başlarken sıralı yanıt imleçlerini sıfırlar."""
        self._cursor.clear()

    def mark_sequenced(self, key: str) -> None:
        """Bu isteğin yanıtının aynı episode içinde değişebileceğini bildirir.

        Kaydederken yeni yanıt üzerine yazmak yerine listeye eklenir.
        """
        self.sequenced_keys.add(key)

    def set_response_sanitizer(self, key: str, sanitizer: Callable[[Any], Any]) -> None:
        """Belirli isteğin gövdesini kayıt ve replay öncesi güvenli alt kümeye indirger."""
        self._response_sanitizers[key] = sanitizer

    def key_for(self, request: httpx.Request) -> str:
        return request_key(request, header_allowlist=self.header_allowlist)

    def payloads_for(self, keys: Iterable[str]) -> dict[str, Any]:
        """PII ve bütünlük doğrulaması için kullanılan ham gövdeleri döndür."""
        payloads: dict[str, Any] = {}
        for key in keys:
            entry = self.store.get(key)
            if entry is None:
                continue
            bodies = [self.store.read_blob(blob_id).get("body") for blob_id in entry.blobs]
            # Sağlayıcı adı yalnızca doğrulama bağlamıdır; gerçek cassette
            # anahtarı ve replay eşleşmesi değişmez.
            payloads[f"{self.store.namespace}:{key}"] = (
                bodies[0] if len(bodies) == 1 else bodies
            )
        return payloads

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        key = self.key_for(request)

        if self.mode is not CassetteMode.RECORD:
            replayed = self._replay(key, request)
            if replayed is not None:
                return replayed
            if self.mode is CassetteMode.REPLAY:
                raise CassetteMissError(
                    _MISS_MESSAGE.format(key=key, method=request.method, url=request.url)
                )

        response = self._inner.handle_request(request)
        response.read()
        sanitizer = self._response_sanitizers.get(key)
        if sanitizer is not None:
            try:
                sanitized = sanitizer(response.json())
            except (TypeError, ValueError, KeyError) as exc:
                raise RuntimeError(
                    f"{self.store.namespace}: cassette gövdesi güvenli alt kümeye indirgenemedi"
                ) from exc
            headers = dict(response.headers)
            headers.pop("content-length", None)
            headers.pop("content-encoding", None)
            response = httpx.Response(
                response.status_code,
                headers=headers,
                json=sanitized,
                request=request,
            )
        self.store.record(
            key,
            request=request,
            response=response,
            sequenced=key in self.sequenced_keys,
            git_sha=self.git_sha,
        )
        self.used_keys.add(key)
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )

    def _replay(self, key: str, request: httpx.Request) -> httpx.Response | None:
        entry = self.store.get(key)
        if entry is None:
            return None

        index = 0
        if len(entry.blobs) > 1:
            index = min(self._cursor.get(key, 0), len(entry.blobs) - 1)
            self._cursor[key] = index + 1

        blob = self.store.read_blob(entry.blobs[index])
        self.used_keys.add(key)
        return httpx.Response(
            status_code=int(blob["status"]),
            headers=dict(blob.get("headers", {})),
            content=_decode_body(str(blob["body_encoding"]), blob.get("body")),
            request=request,
        )
