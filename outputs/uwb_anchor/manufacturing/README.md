# Manufacturing Handoff

This directory is the PCBWay-compatible output target.

Expected final files:

- `gerbers.zip`: Gerber and drill package.
- `BOM_PCBA.csv`: Assembly bill of materials.
- `CPL_PLACEHOLDER.csv`: Pick and place file to be replaced by PCB CAD export.
- Assembly drawings: top, bottom, and 3D render.
- Fabrication drawing: board outline, stackup, tolerances, materials, and controlled impedance notes.

The current proof of concept intentionally does not claim fabrication readiness until a KiCad/PCBai exporter produces geometry and DRC/ERC pass artifacts.