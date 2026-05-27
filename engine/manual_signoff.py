"""Manuel mühendislik sign-off kaydı (MANUAL_ENGINEERING_SIGNOFF_V1).

Otomatik DOĞRULANAMAYAN maddeler (datasheet pinout, RF stackup dielektrik,
AC creepage sertifikasyon, SPICE/SI/PI/thermal modelleri) ancak GERÇEK bir
mühendis tarafindan acikca imzalanirsa 'verified' sayilir. Bu modul o imzayi
denetlenebilir bir dosyaya yazar — sistem imzayi ASLA kendisi uydurmaz.

Durustluk: imza, bir insanin sorumlulugu ustlendigini kaydeder; fiziksel
dogruluk garantisi DEGILDIR. Uretici DFM ve prototip yine onerilir.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SIGNOFF_SCHEMA = "MANUAL_ENGINEERING_SIGNOFF_V1"

REVIEW_ITEMS = (
    "datasheet_pinout_verified",
    "rf_stackup_dielectric_verified",
    "ac_creepage_certification_checked",
    "spice_si_pi_thermal_models_matched",
)


def write_signoff(*, engineer: str, items: list[str], notes: str,
                  project_root: Path) -> dict[str, Any]:
    if not engineer.strip():
        raise ValueError("Sign-off icin mühendis adi zorunludur (--engineer).")
    signed = {item: (item in items) for item in REVIEW_ITEMS}
    payload = {
        "schema": SIGNOFF_SCHEMA,
        "engineer": engineer.strip(),
        "date": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "signed_items": signed,
        "notes": notes.strip(),
        "disclaimer": ("Bu imza mühendis sorumlulugunu kaydeder; fiziksel %100 "
                       "dogruluk garantisi degildir. Üretici DFM + prototip onerilir."),
    }
    out = project_root / "outputs" / "engineering" / "manual_signoff.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    asset = project_root / "assets" / "generated" / "manual_signoff.json"
    try:
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniCircuit manuel mühendislik sign-off kaydi.")
    parser.add_argument("--engineer", required=True, help="Imzalayan mühendisin adi.")
    parser.add_argument("--all", action="store_true", help="Tüm manuel maddeleri imzala.")
    parser.add_argument("--items", nargs="*", default=[],
                        help=f"Tek tek imzalanacak maddeler. Secenekler: {', '.join(REVIEW_ITEMS)}")
    parser.add_argument("--notes", default="")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    items = list(REVIEW_ITEMS) if args.all else [i for i in args.items if i in REVIEW_ITEMS]
    payload = write_signoff(
        engineer=args.engineer, items=items, notes=args.notes,
        project_root=Path(args.project_root),
    )
    print(json.dumps({
        "schema": payload["schema"],
        "engineer": payload["engineer"],
        "date": payload["date"],
        "signed_items": payload["signed_items"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
