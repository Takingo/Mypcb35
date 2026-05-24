# PCB Notes and Manufacturing Constraints

## Stackup

- 4 layer FR4 PCB, 1.6mm total thickness.
- Layer 1: components and controlled signal routing.
- Layer 2: continuous solid ground plane.
- Layer 3: power distribution.
- Layer 4: secondary routing and ground pour.
- RF dielectric assumption: FR4, h=0.2mm, er=4.5 for top-layer microstrip calculation.

## RF Rules

- DWM3000 pin 23 to SMA connector J2 must be a 50 ohm impedance-controlled trace.
- RF trace width: 0.35mm.
- RF trace keep-out: 3mm from unrelated copper, components, vias, and test points.
- No vias, test points, or components are allowed on the RF trace.
- Continuous ground plane on Layer 2 is mandatory directly beneath the RF trace.
- Dense via stitching is required around the SMA connector and RF section.

## Power and Isolation

- Keep the 3-stage power chain: AC 100-240V to HLK-5M05 to TPS54331 to TPS780180.
- Maintain at least 8mm clearance around AC input and the HLK-5M05 primary side.
- Add a visible isolation line on silkscreen and copper keepout.
- Add warning text near the AC input: DANGER HIGH VOLTAGE.
- Place fuse, MOV/varistor, TVS diodes, and ferrite beads at the relevant entry or rail transition points.

## Level Shifting and Signal Integrity

- TXB0104 for SPI lines must be within 15mm of DWM3000.
- SN74LVC1T45 devices for IRQ and EXT_TX must be within 10mm of relevant DWM3000 pins.
- SPI trace lengths must match within +/-2mm.
- EXT_TX, EXT_RX, and IRQ traces must be shorter than 30mm.
- Pull-up and series resistors for RTLS pins must be close to DWM3000.

## Test Points

- TP1: AC_L after fuse.
- TP2: AC_N.
- TP3: isolated +5V.
- TP4: +3V3 buck output.
- TP5: +1V8 LDO output.
- TP6: ESP32 EN.
- TP7: ESP32 boot.
- TP8: SPI CS.
- TP9: SPI MOSI.
- TP10: SPI MISO.
- TP11: SPI CLK.
- TP12: DWM3000 IRQ.
- TP13: DWM3000 EXT_TX.
- TP14: DWM3000 EXT_RX.
- TP15: DWM3000 reset.
- TP16: I2C SDA.
- TP17: I2C SCL.
- TP18: system ground.

All test points must be near a PCB edge and accessible with a pogo pin or handheld probe.

## Manufacturing

- Target manufacturer profile: PCBWay-compatible Gerber, drill, BOM, CPL, assembly drawing, and fabrication drawing package.
- IPC class target: IPC-A-600 Class 2 minimum unless a project overrides it.
- Silkscreen reference designators must remain readable after assembly.
