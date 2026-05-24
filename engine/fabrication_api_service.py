from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PRODUCTION_ZIP_NAME = "Quantum_Mind_Anchor_v2_4_Production.zip"


@dataclass(frozen=True)
class BoardSize:
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class CheckoutSelection:
    manufacturer: str
    quantity: int
    layers: int
    solder_mask_color: str
    includes_assembly: bool


@dataclass(frozen=True)
class ProductionFile:
    name: str
    category: str
    path: str
    size_bytes: int


@dataclass(frozen=True)
class LocalCostEstimate:
    unit_price_usd: float
    total_usd: float
    lead_time_days: int
    note: str


@dataclass(frozen=True)
class FabricationPackageSummary:
    schema: str
    generated_at: str
    status: str
    message: str
    production_zip: str
    production_zip_size_bytes: int
    board_width_mm: float
    board_height_mm: float
    checkout: CheckoutSelection
    files: list[ProductionFile]
    estimate: LocalCostEstimate

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FabricationPackageService:
    """Builds a local manufacturing handoff package.

    The service intentionally does not create an external API payload or claim
    that an order has been placed. It prepares the archive, summarizes the
    contents, and gives the Flutter UI enough data for a practical checkout
    review before a human uploads the ZIP to PCBWay, JLCPCB, or another fab.
    """

    def create_production_zip(
        self,
        phase4_dir: Path,
        output_zip: Path,
        *,
        bom_file: Path | None = None,
    ) -> tuple[Path, list[ProductionFile]]:
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        files = self._collect_production_files(phase4_dir, bom_file=bom_file)
        if not files:
            raise FileNotFoundError(f"No fabrication files found under {phase4_dir}")

        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in files:
                archive_name = self._archive_name(file_path, phase4_dir, bom_file)
                archive.write(file_path, archive_name)

        manifest = [
            ProductionFile(
                name=file_path.name,
                category=self._category_for(file_path, phase4_dir, bom_file),
                path=str(file_path),
                size_bytes=file_path.stat().st_size,
            )
            for file_path in files
        ]
        return output_zip, manifest

    def infer_board_size(self, pcb_file: Path) -> BoardSize:
        text_size = self._infer_board_size_from_text(pcb_file)
        if text_size is not None:
            return text_size
        try:
            return self._infer_board_size_with_pcbnew(pcb_file)
        except Exception:
            return BoardSize(width_mm=120.0, height_mm=80.0)

    def build_summary(
        self,
        *,
        production_zip: Path,
        board_size: BoardSize,
        files: list[ProductionFile],
        checkout: CheckoutSelection,
    ) -> FabricationPackageSummary:
        estimate = self._local_cost_estimate(board_size, checkout)
        return FabricationPackageSummary(
            schema="FABRICATION_PACKAGE_V1",
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            status="package_ready",
            message="Tasarim, Dogrulama ve Uretim Hazirligi Tamamlandi. Uretim paketi hazir.",
            production_zip=str(production_zip),
            production_zip_size_bytes=production_zip.stat().st_size,
            board_width_mm=round(board_size.width_mm, 2),
            board_height_mm=round(board_size.height_mm, 2),
            checkout=checkout,
            files=files,
            estimate=estimate,
        )

    def write_summary(self, summary: FabricationPackageSummary, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")

    def _collect_production_files(self, phase4_dir: Path, *, bom_file: Path | None) -> list[Path]:
        candidates = [
            phase4_dir / "gerber",
            phase4_dir / "drill",
            phase4_dir / "position",
        ]
        files: list[Path] = []
        for candidate in candidates:
            if candidate.exists():
                files.extend(sorted(path for path in candidate.rglob("*") if path.is_file()))
        if bom_file and bom_file.exists():
            files.append(bom_file)
        return files

    def _archive_name(self, file_path: Path, phase4_dir: Path, bom_file: Path | None) -> str:
        if bom_file and file_path.resolve() == bom_file.resolve():
            return f"bom/{file_path.name}"
        return file_path.relative_to(phase4_dir).as_posix()

    def _category_for(self, file_path: Path, phase4_dir: Path, bom_file: Path | None) -> str:
        if bom_file and file_path.resolve() == bom_file.resolve():
            return "bom"
        try:
            top_level = file_path.relative_to(phase4_dir).parts[0]
        except ValueError:
            return "other"
        return {
            "gerber": "gerber",
            "drill": "drill",
            "position": "pick_and_place",
        }.get(top_level, "other")

    def _local_cost_estimate(self, board_size: BoardSize, checkout: CheckoutSelection) -> LocalCostEstimate:
        area_cm2 = (board_size.width_mm * board_size.height_mm) / 100.0
        layer_multiplier = 1.0 + max(checkout.layers - 2, 0) * 0.28
        color_multiplier = 1.0 if checkout.solder_mask_color.lower() == "green" else 1.08
        assembly_fee = 38.0 if checkout.includes_assembly else 0.0
        setup_fee = 22.0 + assembly_fee
        board_cost = max(2.4, area_cm2 * 0.018 * layer_multiplier * color_multiplier)
        total = setup_fee + board_cost * checkout.quantity
        lead_time = 5 + (2 if checkout.layers >= 4 else 0) + (2 if checkout.includes_assembly else 0)
        return LocalCostEstimate(
            unit_price_usd=round(total / max(checkout.quantity, 1), 2),
            total_usd=round(total, 2),
            lead_time_days=lead_time,
            note="Yerel tahmindir; nihai fiyat uretici panelinde dogrulanmalidir.",
        )

    def _infer_board_size_from_text(self, pcb_file: Path) -> BoardSize | None:
        if not pcb_file.exists():
            return None
        text = pcb_file.read_text(encoding="utf-8", errors="ignore")
        edge_blocks = re.findall(
            r"\(gr_line\s+\(start\s+([-0-9.]+)\s+([-0-9.]+)\)\s+\(end\s+([-0-9.]+)\s+([-0-9.]+)\).*?\(layer\s+\"Edge\.Cuts\"\)",
            text,
            flags=re.DOTALL,
        )
        if not edge_blocks:
            return None
        xs: list[float] = []
        ys: list[float] = []
        for x1, y1, x2, y2 in edge_blocks:
            xs.extend([float(x1), float(x2)])
            ys.extend([float(y1), float(y2)])
        return BoardSize(width_mm=max(xs) - min(xs), height_mm=max(ys) - min(ys))

    def _infer_board_size_with_pcbnew(self, pcb_file: Path) -> BoardSize:
        import pcbnew  # type: ignore[import-not-found]

        board = pcbnew.LoadBoard(str(pcb_file))
        bbox = board.GetBoardEdgesBoundingBox()
        width = pcbnew.ToMM(bbox.GetWidth()) if hasattr(pcbnew, "ToMM") else bbox.GetWidth() / 1_000_000
        height = pcbnew.ToMM(bbox.GetHeight()) if hasattr(pcbnew, "ToMM") else bbox.GetHeight() / 1_000_000
        return BoardSize(width_mm=float(width), height_mm=float(height))


def run(
    *,
    phase4_dir: Path,
    pcb_file: Path,
    bom_file: Path,
    output_dir: Path,
    manufacturer: str,
    quantity: int,
    layers: int,
    solder_mask_color: str,
    asset_output: Path | None,
) -> FabricationPackageSummary:
    service = FabricationPackageService()
    checkout = CheckoutSelection(
        manufacturer=manufacturer,
        quantity=quantity,
        layers=layers,
        solder_mask_color=solder_mask_color,
        includes_assembly=True,
    )
    output_zip, files = service.create_production_zip(
        phase4_dir,
        output_dir / PRODUCTION_ZIP_NAME,
        bom_file=bom_file,
    )
    summary = service.build_summary(
        production_zip=output_zip,
        board_size=service.infer_board_size(pcb_file),
        files=files,
        checkout=checkout,
    )
    service.write_summary(summary, output_dir / "fabrication_package.json")
    if asset_output is not None:
        service.write_summary(summary, asset_output)
    print(summary.message)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Package phase 4 production files for local fabrication checkout.")
    parser.add_argument("--phase4-dir", default="outputs/phase4")
    parser.add_argument("--pcb-file", default="outputs/kicad/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb")
    parser.add_argument("--bom-file", default="BOM.csv")
    parser.add_argument("--output-dir", default="outputs/fabrication")
    parser.add_argument("--manufacturer", default="PCBWay")
    parser.add_argument("--quantity", type=int, default=5)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--solder-mask-color", default="Green")
    parser.add_argument("--asset-output", default="assets/generated/fabrication_package.json")
    args = parser.parse_args()
    result = run(
        phase4_dir=Path(args.phase4_dir),
        pcb_file=Path(args.pcb_file),
        bom_file=Path(args.bom_file),
        output_dir=Path(args.output_dir),
        manufacturer=args.manufacturer,
        quantity=args.quantity,
        layers=args.layers,
        solder_mask_color=args.solder_mask_color,
        asset_output=Path(args.asset_output) if args.asset_output else None,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
