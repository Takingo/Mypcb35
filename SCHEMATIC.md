# ESP32-S3 + DWM3000 UWB Anchor Schematic Specification

## System Overview

The board is an isolated AC-powered UWB anchor using an ESP32-S3 host controller and a DWM3000 UWB module. The design exposes full GPIO expansion, I2C, UART, and power headers for field installation and debugging.

## Power Tree

- AC input: 100-240 VAC through fused and surge-protected input network.
- Isolated AC/DC: HLK-5M05 generates isolated +5V.
- Buck regulator: TPS54331 generates +3V3 from +5V.
- LDO regulator: TPS780180 generates +1V8 for DWM3000.
- Protection: fuse, MOV/varistor, TVS diodes, ferrite beads, and bulk/ceramic decoupling are required.

## Core Components

- U1: ESP32-S3-WROOM-1 host MCU, 3.3V logic.
- U2: DWM3000 UWB module, 1.8V logic and RF output.
- U3: TXB0104 SPI level shifter between ESP32-S3 and DWM3000.
- U4: SN74LVC1T45 IRQ level shifter.
- U5: SN74LVC1T45 EXT TX level shifter.
- U6: HLK-5M05 isolated AC/DC module.
- U7: TPS54331 3.3V buck regulator.
- U8: TPS780180 1.8V LDO regulator.
- J1: AC input terminal.
- J2: SMA connector for UWB antenna.

## DWM3000 Connections

- Pin 23 RF: route to J2 SMA through a 50 ohm controlled impedance trace.
- SPI CS: DWM3000 SPI_CS through U3 to ESP32-S3 GPIO10.
- SPI MOSI: DWM3000 SPI_MOSI through U3 to ESP32-S3 GPIO11.
- SPI CLK: DWM3000 SPI_CLK through U3 to ESP32-S3 GPIO12.
- SPI MISO: DWM3000 SPI_MISO through U3 to ESP32-S3 GPIO13.
- IRQ: DWM3000 IRQ through U4 to ESP32-S3 GPIO14.
- EXT_TX: DWM3000 EXT_TX through U5 to ESP32-S3 GPIO15.
- EXT_RX: DWM3000 EXT_RX to ESP32-S3 GPIO16 through short controlled routing.
- RST: DWM3000 reset to ESP32-S3 GPIO9.
- VDDIO: +1V8.
- GND: solid reference to system ground.

## Signal Conditioning

- R10-R13: 100 ohm SPI series resistors placed close to ESP32-S3 side.
- R20: IRQ pull-up close to DWM3000.
- R21: EXT_TX series resistor close to DWM3000.
- Level shifter U3 must be close to DWM3000.
- U4 and U5 must be very close to the relevant DWM3000 pins.

## Expansion Headers

- J6: GPIO header bank A.
- J7: GPIO header bank B.
- J8: GPIO header bank C.
- J9: GPIO header bank D.
- J10: GPIO header bank E.
- J11: GPIO header bank F.
- J12: GPIO header bank G.
- J13: GPIO header bank H.
- J14: I2C header, SDA, SCL, 3V3, GND.
- J15: UART header, TX, RX, 3V3, GND.
- J16: Power distribution header, 5V, 3V3, 1V8, GND.
