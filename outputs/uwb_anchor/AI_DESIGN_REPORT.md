# ESP32-S3 + DWM3000 UWB Anchor AI Design Report

- Generated: 2026-05-24T04:39:04+00:00
- Overall status: pass
- Validation checks passed: 10/10

## Design Intent

This proof-of-concept pipeline converts the UWB anchor source package into a deterministic rule model. The next exporter stage should bind these constraints to KiCad board, schematic, netclass, and fabrication outputs.

## Critical Constraints

### RF: 50 ohm controlled RF trace from DWM3000 pin 23 to SMA

- Status: pass
- Evidence: All required source markers found.
- Next action: Preserve the specified microstrip geometry and keep the RF path free of vias, probes, and components.

### RF: Dense via stitching around SMA and RF section

- Status: pass
- Evidence: All required source markers found.
- Next action: Add explicit via fence coordinates during KiCad/PCBai placement export.

### Power: Three-stage isolated power architecture

- Status: pass
- Evidence: All required source markers found.
- Next action: Keep AC/DC isolation, 3.3V buck, and 1.8V LDO as separate validated power stages.

### Safety: 8mm AC isolation and high-voltage warning

- Status: pass
- Evidence: All required source markers found.
- Next action: Emit board keepout, silkscreen warning, and fabrication notes in the PCB exporter.

### Protection: ESD/EMI protection parts present

- Status: pass
- Evidence: All required BOM entries found.
- Next action: Keep fuse, MOV, TVS, and ferrite beads near entry and rail transition points.

### Level Shifting: Required SPI and RTLS level shifters present

- Status: pass
- Evidence: All required BOM entries found.
- Next action: Constrain TXB0104 within 15mm and SN74LVC1T45 devices within 10mm of DWM3000 pins.

### Signal Integrity: SPI length matching and series resistors

- Status: pass
- Evidence: All required source markers found.
- Next action: During routing, constrain SPI length skew to 2mm and lock series resistors near ESP32 pins.

### RTLS: Critical RTLS traces shorter than 30mm

- Status: pass
- Evidence: All required source markers found.
- Next action: Place RTLS translators and pull/series resistors close to the DWM3000 edge.

### Expansion: GPIO, I2C, UART, and power headers included

- Status: pass
- Evidence: All required BOM entries found.
- Next action: Keep expansion headers at board edges with readable silkscreen and ground return pins.

### Testability: All 18 named test points documented

- Status: pass
- Evidence: All required source markers found.
- Next action: Exporter should place TP1-TP18 near accessible board edges and include them in CPL exclusions.
