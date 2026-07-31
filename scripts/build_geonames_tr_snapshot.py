"""GeoNames Türkiye dump'larından sürümlü yerel coğrafya snapshot'ı üret.

Kaynaklar:

* https://download.geonames.org/export/dump/TR.zip
* https://download.geonames.org/export/zip/TR.zip

Her iki kaynak da GeoNames tarafından CC BY 4.0 altında yayımlanır. Script,
ana dump'tan 81 il merkezini; posta kodu dump'ından ise posta kodu/il/ilçe
gruplarını çıkarır. Çalışma zamanında ağ erişimi yapılmaz.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import Any


def _canonical_line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _read_admin_capitals(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_admin1: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 19:
                continue
            feature_code = fields[7]
            country_code = fields[8]
            admin1_code = fields[10]
            if country_code != "TR" or feature_code not in {"PPLA", "PPLC"}:
                continue
            if not admin1_code:
                continue
            if admin1_code in seen_admin1:
                raise ValueError(f"birden fazla il merkezi bulundu: admin1={admin1_code}")
            seen_admin1.add(admin1_code)
            rows.append(
                {
                    "admin1_code": admin1_code,
                    "alternate_names": sorted(
                        {
                            item.strip()
                            for item in fields[3].split(",")
                            if item.strip() and len(item.strip()) <= 80
                        }
                    )[:40],
                    "ascii_name": fields[2],
                    "country_code": country_code,
                    "feature_code": feature_code,
                    "geoname_id": int(fields[0]),
                    "latitude": float(fields[4]),
                    "longitude": float(fields[5]),
                    "name": fields[1],
                    "population": int(fields[14] or 0),
                    "timezone": fields[17],
                }
            )
    if len(rows) != 81:
        raise ValueError(f"81 il merkezi bekleniyordu, {len(rows)} bulundu")
    return sorted(rows, key=lambda row: (row["name"], row["geoname_id"]))


def _read_postal_groups(path: Path) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"names": set(), "coordinates": []}
    )
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 12 or fields[0] != "TR":
                continue
            postal_code = fields[1].strip()
            province = fields[3].strip()
            province_code = fields[4].strip()
            district = fields[5].strip()
            key = (postal_code, province, province_code, district)
            if fields[2].strip():
                grouped[key]["names"].add(fields[2].strip())
            with suppress(ValueError):
                grouped[key]["coordinates"].append((float(fields[9]), float(fields[10])))

    rows: list[dict[str, Any]] = []
    for (postal_code, province, province_code, district), values in grouped.items():
        coordinates = values["coordinates"]
        latitude = (
            round(sum(item[0] for item in coordinates) / len(coordinates), 6)
            if coordinates
            else None
        )
        longitude = (
            round(sum(item[1] for item in coordinates) / len(coordinates), 6)
            if coordinates
            else None
        )
        names = sorted(values["names"])
        rows.append(
            {
                "district": district or None,
                "latitude": latitude,
                "longitude": longitude,
                "place_count": len(names),
                "place_names": names,
                "postal_code": postal_code,
                "province": province,
                "province_code": province_code,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["postal_code"],
            row["province"],
            row["district"] or "",
        ),
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(f"{_canonical_line(row)}\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def build(*, places_source: Path, postal_source: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    places = _read_admin_capitals(places_source)
    postal_groups = _read_postal_groups(postal_source)

    places_path = output_dir / "places.jsonl"
    postal_path = output_dir / "postal_codes.jsonl"
    _write_jsonl(places_path, places)
    _write_jsonl(postal_path, postal_groups)

    manifest = {
        "attribution": "GeoNames geographical database, CC BY 4.0",
        "files": {
            "places.jsonl": {
                "content_hash": _sha256(places_path),
                "row_count": len(places),
            },
            "postal_codes.jsonl": {
                "content_hash": _sha256(postal_path),
                "row_count": len(postal_groups),
            },
        },
        "license": "CC-BY-4.0",
        "license_url": "https://www.geonames.org/about.html",
        "modifications": [
            "Ana dump'tan PPLA/PPLC türündeki 81 il merkezi seçildi.",
            "Posta kodu kayıtları posta kodu, il ve ilçe seviyesinde gruplandı.",
            "Koordinatlar grup içindeki geçerli kayıtların aritmetik ortalamasıdır.",
            "Alanlar araçların ihtiyaç duyduğu metadata ile sınırlandı.",
        ],
        "name": "geonames_tr",
        "retrieved_at": date(2026, 7, 29).isoformat(),
        "source": {
            "places": "https://download.geonames.org/export/dump/TR.zip",
            "postal_codes": "https://download.geonames.org/export/zip/TR.zip",
        },
        "status": "production snapshot",
    }
    (output_dir / "SNAPSHOT.json").write_text(
        f"{json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--places-source", type=Path, required=True)
    parser.add_argument("--postal-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    build(
        places_source=args.places_source,
        postal_source=args.postal_source,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
