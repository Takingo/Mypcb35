# Simulation Report

Generated: 2026-05-30T08:03:35+00:00
Overall status: pass

## Power Budget

- Domain: PI
- Status: pass
- Evidence: First-order current budget from BOM assumptions.
- Recommendation: Power rails have first-order current margin.
- Metrics:
  - relay_count: 1
  - five_volt_load_ma: 500.0
  - hlk_5m05_capacity_ma: 1000.0
  - three_v_three_load_ma: 440.0
  - tps54331_capacity_ma: 3000.0
  - one_v_eight_load_ma: 220.0
  - ldo_part: TPS7A2018PDBVR
  - ldo_capacity_ma: 300.0
  - ldo_margin_ma: 80.0

## RF Microstrip Impedance

- Domain: SI/RF
- Status: pass
- Evidence: Closed-form Hammerstad-style microstrip estimate for the specified stackup.
- Recommendation: Confirm with manufacturer stackup field solver and keep RF trace via-free on top layer.
- Metrics:
  - trace_width_mm: 0.35
  - dielectric_height_mm: 0.2
  - er: 4.5
  - estimated_z0_ohm: 52.39
  - target_ohm: 50.0

## Thermal Estimate

- Domain: thermal
- Status: pass
- Evidence: First-order junction temperature estimate.
- Recommendation: Validate with real load current and copper area once final footprints are bound.
- Metrics:
  - buck_loss_w: 0.45
  - ldo_loss_w: 0.18
  - ambient_c: 40.0
  - estimated_ldo_temp_c: 61.6

## Decoupling Coverage

- Domain: PI
- Status: pass
- Evidence: Ilk-derece decoupling kapsama analizi (board): 9 kondansator / 8 aktif IC.
- Recommendation: Decoupling kapsama ilk-derece yeterli; yerlesim mesafesi PCB'de dogrulanmali.
- Metrics:
  - source: board
  - active_ic_count: 8
  - decoupling_caps: 9
  - ratio_caps_per_ic: 1.12

## AC Safety Clearance & Engineering Reality

- Domain: safety
- Status: pass
- Evidence: Tüm manuel mühendislik maddeleri Abraham (Bas Muhendis) tarafından 2026-05-26T18:51:03+00:00 tarihinde imzalandı (datasheet pinout, RF stackup, AC sertifikasyon, SPICE). AC rule area: VAR.
- Recommendation: Sign-off kaydedildi. Yine de fiziksel üretim öncesi üretici DFM ve prototip doğrulaması önerilir.
- Metrics:
  - required_ac_clearance_mm: 8.0
  - pcb_rule_area_found: True
  - pcb_edge_cuts_found: True
  - pcb_footprints_present: True
  - datasheet_pinout_verified: True
  - rf_stackup_dielectric_verified: True
  - ac_creepage_certification_checked: True
  - spice_si_pi_thermal_models_matched: True
  - manual_signoff_engineer: Abraham (Bas Muhendis)
  - manual_signoff_date: 2026-05-26T18:51:03+00:00
  - pending_manual_items: []
