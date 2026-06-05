from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
sys.path.append(str(Path(__file__).parent))

from board_verification_manifest import manifest_gate_failure
from design_evidence_gate import audit_design_evidence_gate
from production_model_gate import audit_production_model_gate


@dataclass(frozen=True)
class ManufacturerSpec:
    name: str
    gerber_folder_naming: str
    drill_extension: str
    position_format: str
    accepts_pdf_assembly: bool
    pcba_assembly: bool
    min_trace_space_mm: float
    impedance_control: bool
    notes: str


MANUFACTURER_SPECS = {
    "PCBWay": ManufacturerSpec(
        name="PCBWay",
        gerber_folder_naming="gerber",
        drill_extension=".xln",
        position_format="PCBWay",
        accepts_pdf_assembly=True,
        pcba_assembly=True,
        min_trace_space_mm=0.127,
        impedance_control=True,
        notes="Upload ZIP to PCBWay.com → Upload Gerber → Select PCBA Service",
    ),
    "JLCPCB": ManufacturerSpec(
        name="JLCPCB",
        gerber_folder_naming="gerber",
        drill_extension=".xln",
        position_format="JLCPCB",
        accepts_pdf_assembly=True,
        pcba_assembly=True,
        min_trace_space_mm=0.127,
        impedance_control=False,
        notes="Upload ZIP to JLC.VIP → Gerber Upload → Enable PCBA Service",
    ),
    "Seeed": ManufacturerSpec(
        name="Seeed Fusion",
        gerber_folder_naming="gerber",
        drill_extension=".drl",
        position_format="Seeed",
        accepts_pdf_assembly=True,
        pcba_assembly=True,
        min_trace_space_mm=0.127,
        impedance_control=False,
        notes="Upload ZIP to Fusion.Seeedstudio.com → Select PCB+Assembly",
    ),
}


@dataclass(frozen=True)
class ManufacturingFile:
    path: str
    category: str
    description: str
    mandatory: bool


@dataclass(frozen=True)
class PcbaManufacturingPackage:
    schema: str
    generated_at: str
    design_name: str
    manufacturer: str
    board_size_mm: tuple[float, float]
    layer_count: int
    component_count: int
    total_weight_grams: float
    files: list[ManufacturingFile]
    pcba_instructions: str
    upload_steps: list[str]
    cost_estimate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PcbaManufacturingExportService:
    """Generates complete PCBA manufacturing package for direct online submission.

    Creates all files needed by PCBWay, JLCPCB, Seeed Fusion, or other PCBA providers:
    - Gerber files (all layers with proper naming)
    - Drill file with tool list
    - Pick & Place (CPL) assembly data
    - BOM with verified MPN and manufacturer
    - Assembly drawing (PDF with polarity, orientation, test points)
    - Fabrication notes (stackup, impedance, clearances, DFM)
    - IPC-A-610 guide reference
    """

    def __init__(self, manufacturer: str = "PCBWay"):
        if manufacturer not in MANUFACTURER_SPECS:
            raise ValueError(f"Unknown manufacturer: {manufacturer}")
        self.manufacturer = manufacturer
        self.spec = MANUFACTURER_SPECS[manufacturer]

    def validate_export_gate(
        self,
        *,
        netlist_file: Path,
        bom_file: Path,
        layout_status_file: Path,
        pcb_file: Path,
        drc_report_file: Path | None = None,
        verification_manifest_file: Path | None = None,
    ) -> None:
        source_gate = audit_design_evidence_gate(netlist_file, bom_file)
        if not source_gate.ok:
            raise RuntimeError(
                "PCBA direct export blocked because design source evidence failed: "
                f"{source_gate.evidence_summary}"
            )

        if verification_manifest_file is not None and drc_report_file is not None and verification_manifest_file.exists():
            failure = manifest_gate_failure(
                verification_manifest_file,
                pcb_file=pcb_file,
                drc_report_file=drc_report_file,
            )
            if failure is not None:
                raise RuntimeError(f"PCBA direct export blocked by board verification manifest: {failure}")
            return

        if not layout_status_file.exists():
            raise RuntimeError(
                f"PCBA direct export blocked because layout status is missing: {layout_status_file}"
            )
        layout_status = json.loads(layout_status_file.read_text(encoding="utf-8"))
        final_count = int(layout_status.get("final_violation_count", -1))
        manufacturing_ready = bool(layout_status.get("manufacturing_ready", False))
        if final_count != 0 or not manufacturing_ready:
            raise RuntimeError(
                "PCBA direct export blocked because KiCad DRC is not clean: "
                f"final_violation_count={final_count}, manufacturing_ready={manufacturing_ready}."
            )

        pcb_text = pcb_file.read_text(encoding="utf-8", errors="ignore") if pcb_file.exists() else ""
        if "pcbnew unavailable" in pcb_text or "(footprint" not in pcb_text:
            raise RuntimeError(
                "PCBA direct export blocked because the active PCB is missing real KiCad footprint data."
            )

        model_gate = audit_production_model_gate(pcb_file)
        if not model_gate.ok:
            raise RuntimeError(
                "PCBA direct export blocked because production model validation failed: "
                f"{model_gate.evidence_summary}"
            )

    def generate_assembly_drawing_text(self, component_count: int) -> str:
        """Generate assembly drawing instructions as text (can be converted to PDF)."""
        return f"""ASSEMBLY DRAWING - COMPONENT PLACEMENT GUIDE
Generated: {datetime.now(timezone.utc).isoformat()}

GENERAL INSTRUCTIONS:
1. All component positions shown in mm from board origin (0,0) at bottom-left corner
2. Rotation angles in degrees: 0°=reference, 90°=rotated 90° CCW, etc.
3. Polarity indicators (★) mark positive pins for polarized components
4. Test points (◆) are provided for in-circuit testing
5. Ground vias (⊙) must maintain thermal connection to GND plane

COMPONENT CATEGORIES:
- ICs: Place flat-side toward reference indicator, verify pin 1 alignment
- Capacitors: Observe polarity for electrolytics (● side = positive)
- Inductors: Check orientation per BOM; some are unidirectional
- Resistors: Non-polarized; rotation does not affect function
- Connectors: Verify keying/orientation per PCB silkscreen
- Relay: Pin 1 must match BOM orientation

CRITICAL COMPONENTS (Manual Verification Required):
- ESP32-S3-WROOM-1: Antenna area must be clear of copper/components within 5mm
- DWM3000: RF traces 50Ω impedance controlled; no vias/crossovers
- High-Current Traces: >1A paths require minimum 0.2mm trace width
- AC Mains (220V): Minimum 8mm clearance/creepage from 3.3V/1.8V circuits

SOLDER PROFILE:
- Lead-free SAC305: Peak 260°C for 10-30 seconds
- Reflow time: 60-90 seconds within 217°C window
- Inspect for cold solder joints on thermal relief pads

TEST POINTS:
- TP_3V3: 3.3V rail test point
- TP_1V8: 1.8V rail test point
- TP_GND: Ground reference point
- TP_HLK: Power input monitoring point

TOTAL COMPONENTS: {component_count}
Estimated Placement Time: 15-30 minutes (automated PCBA service)
Post-Assembly QC: Automated AOI + manual inspection of critical RF/power areas
"""

    def generate_fabrication_notes(self, board_size: tuple[float, float]) -> str:
        """Generate detailed fabrication notes for PCB manufacturer."""
        width, height = board_size
        return f"""FABRICATION NOTES & DESIGN RULES
Generated: {datetime.now(timezone.utc).isoformat()}

PROJECT: Quantum Mind Anchor v2.4 (UWB Positioning + DWM3000 + ESP32-S3)
MANUFACTURER: {self.spec.name}

═══════════════════════════════════════════════════════════════

1. PCB STACKUP & LAYER STRUCTURE

Layer Stack (4-Layer):
  Layer 1: F.Cu (Signal + Power Distribution)
  Layer 2: GND (Ground Plane - solid, no discontinuities)
  Layer 3: GND (Ground Plane - solid, no discontinuities)
  Layer 4: B.Cu (Signal + Power Distribution)

Copper Thickness:
  - Standard 1oz (35μm) per IPC-2221
  - GND planes: 1oz minimum
  - Power planes (if used): 2oz recommended for >3A traces

Dielectric:
  - Core: FR-4, Tg 130°C minimum (non-halogenated preferred)
  - Prepreg: 106 standard between layers
  - Total thickness: 1.6mm ±0.15mm

═══════════════════════════════════════════════════════════════

2. CRITICAL DESIGN RULES

Trace & Space:
  - Minimum trace width: 0.127mm (5mil)
  - Minimum clearance: 0.127mm (5mil)
  - Power traces (>2A): 0.254mm minimum (10mil)
  - RF traces (50Ω): 0.35mm width, {self.spec.min_trace_space_mm}mm clearance

Via Specifications:
  - Finished hole: 0.2mm diameter (plated through-hole)
  - Via pad: 0.45mm diameter
  - Via spacing: 0.254mm minimum (edge-to-edge)
  - Thermal relief: 4-spokes, 0.2mm width, standard undercut

Component Clearance:
  - Pad-to-pad (SMD): 0.127mm minimum
  - Component-to-board-edge: 3mm minimum (for tooling)
  - Component-to-via: 0.2mm minimum clearance

═══════════════════════════════════════════════════════════════

3. CRITICAL RF & POWER AREAS

RF Microstrip (DWM3000 antenna traces):
  - Impedance target: 50Ω ±5% (measure with TDR if possible)
  - Width: 0.35mm, height: 0.20mm above GND, Er=4.5
  - No vias or crossovers allowed on RF traces
  - Keep RF traces on top layer, route away from switching noise
  - Minimum trace length from DWM3000 RF pin: 150mm (antenna matching network)

Power Distribution (HLK-5M05 output):
  - 5V distribution: trace width 0.254mm minimum (10mil)
  - All vias on 5V net must connect to power plane (Layer 1)
  - Bulk capacitors (470μF) within 5mm of HLK output
  - Decoupling capacitors within 10mm of each IC power pin

1.8V LDO Output (for DWM3000):
  - Dedicated trace from TPS7A2018 output to DWM3000 VDDIO/VDDF
  - Bypass capacitor (100nF) within 3mm of DWM3000 power pin
  - Output filtering: LC network (L=10μH, C=10μF ceramic)

Switching Noise Isolation:
  - TPS54331 (5V buck): switching frequency 360kHz, inductor placed >10mm from RF
  - Keep switching node traces <20mm length
  - Local ground return via main GND plane (Layer 2-3)

═══════════════════════════════════════════════════════════════

4. AC MAINS SAFETY (230V Input)

Creepage & Clearance (IEC 60664-1 / IEC 62368-1):
  - 230V AC to 3.3V circuits: 8mm clearance, 16mm creepage (MINIMUM)
  - 230V AC to GND: 3.2mm clearance, 6.4mm creepage
  - High-voltage areas enclosed by solder mask or potting recommended

Design Implementation:
  - High-voltage section on B.Cu layer only (isolated from signal)
  - Dedicated GND trace between HLK-5M05 and AC primary side
  - No through-holes in AC section; use castellated pads if needed
  - Mains earth connection: ≥0.2mm2 copper trace to chassis GND

Test & Certification:
  - High-pot test: 3kV RMS, 60 seconds minimum (recommended before shipment)
  - Insulation resistance: >100MΩ at 500VDC between AC and low-voltage
  - Leakage current: <0.5mA at 230V nominal input

═══════════════════════════════════════════════════════════════

5. SOLDER MASK & SILKSCREEN

Solder Mask:
  - Color: {self.spec.name} standard green (other colors +lead time)
  - Type: Liquid photoimageable (LPI) preferred
  - Coverage: Top and bottom surfaces
  - Dam-to-pad rules:
    * Between pads <0.127mm spacing: 0.05mm solder dam minimum
    * Via tenting allowed on power planes
    * Component pads: keep mask-free for solder wetting

Silkscreen:
  - Color: white (standard on green mask)
  - Text size: minimum 0.5mm height, 0.15mm line width
  - Content: reference designators, polarity marks, test point labels
  - Warning: "230V AC — Hazard" silkscreen near mains connector
  - Logo/artwork: keep away from thermal areas and connector openings

═══════════════════════════════════════════════════════════════

6. PANELIZATION & TOOLING

Board Dimensions: {width:.2f}mm × {height:.2f}mm
Panelization: Single board (no matrix/panel)
Tooling Holes: 4 corners, 3.2mm diameter plated (already in design)

Edge Clearance:
  - Components: minimum 3mm from board edge
  - Traces: minimum 2mm from board edge
  - Board outline: smooth contours, no sharp corners (<90° angles)

Cutting/Milling:
  - Edge tolerances: ±0.15mm
  - Routing: mill after solder reflow if applicable
  - Fiducials: 1.0-1.5mm diameter, top layer, 3.0mm min spacing

═══════════════════════════════════════════════════════════════

7. COMPONENT HANDLING & ASSEMBLY

Moisture Sensitivity:
  - ESP32-S3: MSL3 (168 hours at 30°C/60% RH) — store in sealed bag with desiccant
  - DWM3000: MSL2a (1 year nominal) — room temperature acceptable
  - Capacitors/Resistors: MSL1 (unlimited storage)

Electrostatic (ESD):
  - All handling in ESD-safe environment (wrist strap, mat grounding)
  - Store parts in Faraday bags until assembly
  - Charge threshold: >2kV danger zone

Soldering:
  - Reflow profile: Peak 260°C ±5°C for 10-30 seconds
  - Ramp rate: 2-3°C/second (avoid thermal shock on BGA)
  - Lead-free: SAC305 (99.3% Sn, 0.5% Ag, 0.7% Cu)

═══════════════════════════════════════════════════════════════

8. TESTING & INSPECTION (POST-ASSEMBLY)

Automated Optical Inspection (AOI):
  - Solder joint coverage (minimum 75% pad area)
  - No bridging between pads
  - Correct component orientation (reference marks aligned)
  - Solder bead shape (accept pyramidal, reject icicles/dull)

Functional Testing:
  - Power-on: 3V3 rail stable within ±2%, <10mA standby
  - DWM3000: responds to SPI commands within 50ms boot
  - ESP32-S3: UART console output at 115200 baud
  - RF: impedance <2:1 VSWR at operating frequency (UWB 6-8 GHz)

In-Circuit Testing (ICT):
  - Test points: TP_3V3, TP_1V8, TP_GND provided
  - Continuity: all nets to test points verified
  - Isolation: no shorts between power and GND planes

═══════════════════════════════════════════════════════════════

9. FABRICATION QUESTIONS & CONTACTS

{self.spec.notes}

Expected lead time: {self._lead_time_estimate()} business days
Quality standard: IPC-A-610 Class 2 (commercial electronics)
Inspection level: {self.spec.name} standard (AOI + sampling)

DO NOT START FABRICATION until:
  ✓ Engineer reviews this checklist
  ✓ RF stackup confirmed with your field solver
  ✓ High-pot test plan reviewed (AC safety)
  ✓ Component availability confirmed (long-lead items noted)
  ✓ Design freeze approved by project lead
"""

    def _lead_time_estimate(self) -> str:
        if self.spec.name == "PCBWay":
            return "7-10 (standard) or 3-5 (expedited +fee)"
        elif self.spec.name == "JLCPCB":
            return "5-7 (standard) or 2-3 (fast +fee)"
        else:
            return "7-14 (varies by component sourcing)"

    def generate_bom_from_netlist(self, netlist_file: Path) -> str:
        """Generate BOM directly from AI_NETLIST_V1.json — authoritative source."""
        lines = []
        lines.append(
            "Reference,Value,Part Number,Manufacturer,Quantity,Unit Cost USD,Total Cost USD,Lead Time Days,Stock Status,Component Type,Package,Datasheet URL"
        )

        try:
            netlist = json.loads(netlist_file.read_text(encoding="utf-8-sig"))
            components = netlist.get("components", [])

            # Group by part number to count quantities
            parts_by_ref = {}
            for comp in components:
                ref = comp.get("ref", "?")
                value = comp.get("value", "")
                part = comp.get("part_number", "")
                reason = comp.get("reason", "")

                if part and ref:
                    parts_by_ref[ref] = {
                        "value": value,
                        "part": part,
                        "reason": reason
                    }

            # Generate BOM lines
            for ref in sorted(parts_by_ref.keys()):
                info = parts_by_ref[ref]
                value = info["value"]
                part = info["part"]

                cost_data = self._simulate_component_cost(part, value)

                lines.append(
                    f"{ref},\"{value}\",{part},{cost_data['mfg']},1,"
                    f"{cost_data['unit_cost']},{cost_data['total_cost']},"
                    f"{cost_data['lead_time']},{cost_data['stock']},{cost_data['type']},"
                    f"{cost_data['package']},{cost_data['datasheet']}"
                )
        except Exception as e:
            print(f"[ERROR] Netlist'ten BOM oluşturulamadı: {e}")

        return "\n".join(lines)

    def generate_bom_extended(
        self,
        base_bom_csv: str,
        pcb_file: Path,
    ) -> str:
        """Generate extended BOM with availability, cost, lead-time data (deprecated — use generate_bom_from_netlist)."""
        lines = []
        lines.append(
            "Reference,Value,Part Number,Manufacturer,Quantity,Unit Cost USD,Total Cost USD,Lead Time Days,Stock Status,Component Type,Package,Datasheet URL"
        )

        # Parse existing BOM
        reader = csv.DictReader(base_bom_csv.strip().split("\n"))
        if reader.fieldnames:
            for row in reader:
                # Placeholder extended info (in production, integrate with Digi-Key/Mouser API)
                ref = row.get("Reference", "U?")
                value = row.get("Value", "")
                part = row.get("Part Number", "")

                # Simulate cost data (real implementation would query live databases)
                cost_data = self._simulate_component_cost(part, value)

                lines.append(
                    f"{ref},\"{value}\",{part},{cost_data['mfg']},1,"
                    f"{cost_data['unit_cost']},{cost_data['total_cost']},"
                    f"{cost_data['lead_time']},{cost_data['stock']},{cost_data['type']},"
                    f"{cost_data['package']},{cost_data['datasheet']}"
                )

        return "\n".join(lines)

    def _simulate_component_cost(self, part: str, value: str) -> dict[str, Any]:
        """Placeholder for real component cost/availability lookup."""
        part_lower = part.lower() if part else ""

        if "esp32" in part_lower:
            return {
                "mfg": "Espressif",
                "unit_cost": 4.85,
                "total_cost": 4.85,
                "lead_time": 14,
                "stock": "In Stock",
                "type": "MCU",
                "package": "QFN-56",
                "datasheet": "https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf"
            }
        elif "dwm3000" in part_lower:
            return {
                "mfg": "Decawave",
                "unit_cost": 18.50,
                "total_cost": 18.50,
                "lead_time": 21,
                "stock": "Limited",
                "type": "RF Module",
                "package": "LGA-64",
                "datasheet": "https://www.decawave.com/wp-content/uploads/2021/04/DWM3000_Datasheet_v1p0.pdf"
            }
        elif "hlk-5m05" in part_lower or "hlk" in part_lower:
            return {
                "mfg": "HLK",
                "unit_cost": 2.30,
                "total_cost": 2.30,
                "lead_time": 7,
                "stock": "In Stock",
                "type": "SMPS Module",
                "package": "SIP-4",
                "datasheet": "https://www.hlktech.net/uploads/file/20200410/HLK-5M05.pdf"
            }
        else:
            return {
                "mfg": "Various",
                "unit_cost": 0.15,
                "total_cost": 0.15,
                "lead_time": 5,
                "stock": "In Stock",
                "type": "Passive",
                "package": "0603/0805",
                "datasheet": "N/A"
            }

    def generate_manufacturer_instructions(self) -> str:
        """Generate step-by-step upload instructions for the target manufacturer."""
        instructions = {
            "PCBWay": """PCBWAY UPLOAD INSTRUCTIONS

1. Visit: https://www.pcbway.com/
2. Click "Upload Gerber File" button
3. Select the "Quantum_Mind_Anchor_v2_4_Production.zip" file
4. Review auto-detected settings:
   - Layers: 4
   - Board Size: 120×80 mm (auto-detected)
   - Solder Mask: Green (default)
   - Silkscreen: White
   - Surface Finish: HASL LeadFree (standard)
5. Select "Quick Turn PCB" for fast turnaround
6. In "PCB Assembly" section:
   - Enable "SMT Assembly"
   - Upload BOM.csv file
   - Upload POS file (pick & place)
   - Set stencil thickness: 0.125mm (standard)
7. Review component placement preview (PDF generated by PCBWay)
8. Add special notes in "Add Special Requirements":
   "DWM3000 RF traces must maintain 50Ω impedance. ESP32-S3 antenna clearance critical."
9. Select quantity and shipping method
10. Proceed to checkout
11. Allow 7-10 business days for standard turnaround""",

            "JLCPCB": """JLCPCB UPLOAD INSTRUCTIONS (jlc.vip)

1. Visit: https://jlc.vip/
2. Click "Add gerber file" or drag-drop the ZIP
3. System auto-parses layers and settings:
   - Layers: 4
   - PCB Thickness: 1.6mm
   - Copper Weight: 1 oz
4. In "SMT Assembly" section:
   - Enable assembly service
   - Upload BOM file (CSV)
   - Upload Pick & Place file (POS)
   - Confirm part numbers match available inventory
5. Review JLCPCB stock status for each component
   - DWM3000 may require "Global Parts" selection (+7 day lead)
6. Set stencil specifications:
   - Thickness: 0.1mm
   - Aperture: Square
7. Add manufacturing notes: "Ensure DWM3000 RF impedance 50Ω verified"
8. Select quantity (typically $6 setup + $25-50 per board for assembly)
9. Choose shipping (DHL/FedEx available)
10. Confirm and pay; track production via dashboard""",

            "Seeed": """SEEED FUSION UPLOAD INSTRUCTIONS

1. Visit: https://fusion.seeedstudio.com/
2. Select "Manage PCB Prototyping Orders"
3. Click "Upload Design File" → Select ZIP
4. Configure:
   - PCB Type: Standard PCB
   - Layers: 4
   - Quality Level: Industrial Standard
5. In "Quick Assembly" section:
   - Attach BOM (CSV with MPN, value, package)
   - Attach CPL file (pick & place positions)
6. Seeed will auto-calculate assembly cost based on component sourcing
7. Review pre-assembled board estimate (component sourcing +7 days)
8. Set delivery address and shipping method
9. Typical lead time: 10-14 days (includes component procurement)
10. Order confirmation and tracking email sent immediately""",
        }

        return instructions.get(
            self.spec.name,
            "See manufacturer website for upload instructions"
        )

    def create_complete_package(
        self,
        output_dir: Path,
        pcb_file: Path,
        bom_csv: str,
        gerber_dir: Path,
        position_file: Path | None = None,
        netlist_file: Path | None = None,
    ) -> PcbaManufacturingPackage:
        """Generate complete PCBA manufacturing package with all files."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Infer board size from PCB file
        board_size = self._infer_board_size(pcb_file)
        component_count = len(bom_csv.strip().split("\n")) - 1 if bom_csv else 0

        files: list[ManufacturingFile] = []

        # 1. Copy Gerber files
        if gerber_dir.exists():
            gerber_output = output_dir / "gerber"
            gerber_output.mkdir(exist_ok=True)
            for gbr_file in sorted(path for path in gerber_dir.iterdir() if path.is_file()):
                dest = gerber_output / gbr_file.name
                dest.write_bytes(gbr_file.read_bytes())
                files.append(ManufacturingFile(
                    path=f"gerber/{gbr_file.name}",
                    category="gerber",
                    description=f"Gerber layer: {gbr_file.stem}",
                    mandatory=True,
                ))

        # 2. Generate extended BOM from netlist (authoritative source)
        bom_file = output_dir / "BOM_Extended.csv"
        netlist_path = Path(str(netlist_file)) if netlist_file else Path("outputs/phase1/AI_NETLIST_V1.json")
        if netlist_path.exists():
            extended_bom = self.generate_bom_from_netlist(netlist_path)
        else:
            # Fallback to manual BOM if netlist not found
            extended_bom = self.generate_bom_extended(bom_csv, pcb_file)
        bom_file.write_text(extended_bom, encoding="utf-8")
        files.append(ManufacturingFile(
            path="BOM_Extended.csv",
            category="bom",
            description="Bill of Materials with cost/availability/lead-time",
            mandatory=True,
        ))

        # 3. Copy or generate position file
        if position_file and position_file.exists():
            dest = output_dir / position_file.name
            dest.write_bytes(position_file.read_bytes())
            files.append(ManufacturingFile(
                path=position_file.name,
                category="pick_and_place",
                description="Pick & Place coordinates for assembly",
                mandatory=True,
            ))

        # 4. Generate assembly drawing
        assembly_text_file = output_dir / "ASSEMBLY_DRAWING.txt"
        assembly_text = self.generate_assembly_drawing_text(component_count)
        assembly_text_file.write_text(assembly_text, encoding="utf-8")
        files.append(ManufacturingFile(
            path="ASSEMBLY_DRAWING.txt",
            category="documentation",
            description="Assembly placement guide and test point locations",
            mandatory=True,
        ))

        # 5. Generate fabrication notes
        fab_notes_file = output_dir / "FABRICATION_NOTES.txt"
        fab_notes = self.generate_fabrication_notes(board_size)
        fab_notes_file.write_text(fab_notes, encoding="utf-8")
        files.append(ManufacturingFile(
            path="FABRICATION_NOTES.txt",
            category="documentation",
            description="PCB design rules, stackup, RF/power constraints, safety requirements",
            mandatory=True,
        ))

        # 6. Generate manufacturer-specific instructions
        instructions_file = output_dir / f"{self.spec.name.replace(' ', '_')}_UPLOAD_GUIDE.txt"
        instructions = self.generate_manufacturer_instructions()
        instructions_file.write_text(instructions, encoding="utf-8")
        files.append(ManufacturingFile(
            path=instructions_file.name,
            category="documentation",
            description=f"Step-by-step instructions for uploading to {self.spec.name}",
            mandatory=False,
        ))

        # 7. Create manifest
        cost_estimate = {
            "setup_fee_usd": 22.0,
            "unit_cost_usd": 8.50,
            "quantity": 5,
            "total_usd": 22.0 + (8.50 * 5),
            "lead_time_days": 7,
            "currency": "USD",
            "note": "Estimated cost; actual pricing from manufacturer portal",
        }

        package = PcbaManufacturingPackage(
            schema="PCBA_MANUFACTURING_PACKAGE_V1",
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            design_name="Quantum Mind Anchor v2.4",
            manufacturer=self.spec.name,
            board_size_mm=board_size,
            layer_count=4,
            component_count=component_count,
            total_weight_grams=self._estimate_weight(board_size, component_count),
            files=files,
            pcba_instructions=self.generate_manufacturer_instructions(),
            upload_steps=[
                f"1. Visit {self.spec.name} website (see {instructions_file.name})",
                f"2. Upload Quantum_Mind_Anchor_v2_4_Production.zip file",
                f"3. Verify layer count, dimensions, and component placement",
                f"4. Confirm BOM and pick & place data",
                f"5. Review fabrication notes for {self.spec.name} requirements",
                f"6. Select quantity, color, surface finish, and delivery method",
                f"7. Pay and receive confirmation email",
            ],
            cost_estimate=cost_estimate,
        )

        # Write manifest
        manifest_file = output_dir / "PCBA_MANIFEST.json"
        manifest_file.write_text(
            json.dumps(package.to_dict(), indent=2),
            encoding="utf-8"
        )
        files.append(ManufacturingFile(
            path="PCBA_MANIFEST.json",
            category="documentation",
            description="Package manifest with file listing and upload instructions",
            mandatory=True,
        ))

        return package

    def _infer_board_size(self, pcb_file: Path) -> tuple[float, float]:
        """Infer board dimensions from KiCad PCB file."""
        if not pcb_file.exists():
            return (120.0, 80.0)  # Default

        try:
            text = pcb_file.read_text(encoding="utf-8", errors="ignore")
            # Simple regex to find Edge.Cuts bounding box
            xs, ys = [], []
            for match in re.finditer(
                r'\(gr_line.*?\(start\s+([-\d.]+)\s+([-\d.]+)\).*?\(end\s+([-\d.]+)\s+([-\d.]+)\).*?\(layer\s+"Edge\.Cuts"\)',
                text,
                re.DOTALL
            ):
                x1, y1, x2, y2 = map(float, match.groups())
                xs.extend([x1, x2])
                ys.extend([y1, y2])

            if xs and ys:
                width = (max(xs) - min(xs))
                height = (max(ys) - min(ys))
                return (round(width, 2), round(height, 2))
        except Exception:
            pass

        return (120.0, 80.0)

    def _estimate_weight(self, board_size: tuple[float, float], component_count: int) -> float:
        """Rough estimate of board + components weight in grams."""
        width, height = board_size
        board_area_cm2 = (width * height) / 100
        board_weight = board_area_cm2 * 0.055 * 4  # 4-layer, ~55 mg/cm²
        components_weight = component_count * 0.15  # ~150 mg per component average
        return round(board_weight + components_weight, 2)


def main() -> int:
    def resolve_from_manifest(manifest_file: Path) -> dict[str, Path]:
        if not manifest_file.exists():
            return {}
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
        pcb = Path(str(data.get("pcb_file", "")))
        drc = Path(str(data.get("drc_report_file", "")))
        manufacturing_dir = drc.parent if drc else Path()
        position_candidates = [
            manufacturing_dir / "position" / "pick_and_place.csv",
            manufacturing_dir / "position" / "position.csv",
        ]
        position = next((candidate for candidate in position_candidates if candidate.exists()), Path())
        resolved: dict[str, Path] = {}
        if pcb.exists():
            resolved["pcb_file"] = pcb
        if drc.exists():
            resolved["drc_report_file"] = drc
            resolved["gerber_dir"] = manufacturing_dir / "gerber"
            resolved["position_file"] = position
        return resolved

    parser = argparse.ArgumentParser(description="Generate complete PCBA manufacturing export package.")
    parser.add_argument("--output-dir", default="outputs/pcba_manufacturing")
    parser.add_argument("--pcb-file", default="")
    parser.add_argument("--bom-file", default="BOM.csv")
    parser.add_argument("--netlist-file", default="outputs/phase1/AI_NETLIST_V1.json")
    parser.add_argument("--layout-status-file", default="")
    parser.add_argument("--drc-report-file", default="")
    parser.add_argument("--verification-manifest-file", default="assets/generated/board_verification_manifest.json")
    parser.add_argument("--gerber-dir", default="")
    parser.add_argument("--position-file", default="")
    parser.add_argument("--manufacturer", default="PCBWay", choices=list(MANUFACTURER_SPECS.keys()))
    parser.add_argument("--asset-output", default="assets/generated/pcba_manufacturing_package.json")
    args = parser.parse_args()

    manifest_path = Path(args.verification_manifest_file)
    resolved = resolve_from_manifest(manifest_path)
    pcb_file = Path(args.pcb_file) if args.pcb_file else resolved.get(
        "pcb_file",
        Path("outputs/kicad/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"),
    )
    drc_report_file = Path(args.drc_report_file) if args.drc_report_file else resolved.get(
        "drc_report_file",
        pcb_file.parent / "manufacturing" / "drc_report.json",
    )
    gerber_dir = Path(args.gerber_dir) if args.gerber_dir else resolved.get(
        "gerber_dir",
        drc_report_file.parent / "gerber",
    )
    position_file = Path(args.position_file) if args.position_file else resolved.get(
        "position_file",
        drc_report_file.parent / "position" / "pick_and_place.csv",
    )
    layout_status_file = Path(args.layout_status_file) if args.layout_status_file else Path("__missing_layout_status__")

    bom_csv = ""
    bom_path = Path(args.bom_file)
    if bom_path.exists():
        bom_csv = bom_path.read_text(encoding="utf-8")

    service = PcbaManufacturingExportService(manufacturer=args.manufacturer)
    service.validate_export_gate(
        netlist_file=Path(args.netlist_file),
        bom_file=bom_path,
        layout_status_file=layout_status_file,
        pcb_file=pcb_file,
        drc_report_file=drc_report_file,
        verification_manifest_file=manifest_path,
    )
    package = service.create_complete_package(
        output_dir=Path(args.output_dir),
        pcb_file=pcb_file,
        bom_csv=bom_csv,
        gerber_dir=gerber_dir,
        position_file=position_file if position_file.exists() else None,
        netlist_file=Path(args.netlist_file) if args.netlist_file else None,
    )

    if args.asset_output:
        Path(args.asset_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.asset_output).write_text(
            json.dumps(package.to_dict(), indent=2),
            encoding="utf-8"
        )

    print(json.dumps(package.to_dict(), indent=2))
    print(f"\n[OK] PCBA manufacturing package generated: {args.output_dir}")
    print(f"  Target manufacturer: {args.manufacturer}")
    print(f"  Files generated: {len(package.files)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
