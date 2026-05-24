# Simulation Report

Generated: 2026-05-24T07:23:56+00:00
Overall status: review_required

## Power Budget

- Domain: PI
- Status: pass
- Evidence: First-order current budget from BOM assumptions.
- Recommendation: Power rails have first-order current margin.
- Metrics:
  - relay_count: 0
  - five_volt_load_ma: 420.0
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

## AC Safety Clearance & Engineering Reality

- Domain: safety
- Status: review
- Evidence: PCB dosyası footprint içeriyor. AC rule area: VAR. datasheet_pinout, RF stackup, AC sertifikasyon ve SPICE modelleri BU ARAÇ TARAFINDAN OTOMATİK DOĞRULANAMAZ — manuel mühendis incelemesi zorunludur.
- Recommendation: GEREKLİ MANUEL KONTROLLER:
1. Her komponentin datasheet pinout'unu KiCad sembolüyle karşılaştır.
2. Üretici stackup field solver ile RF microstrip empedansını hesaplat.
3. IEC 60664-1 / IEC 62368-1 tablolarında 230VAC için creepage+clearance değerlerini doğrula.
4. TPS54331DR, TPS7A2018, HLK-5M05 için gerçek SPICE modelleri ile transient simülasyon yap.
5. DWM3000 1.0mm pitch footprint'ini datasheet land pattern ile karşılaştır.
- Metrics:
  - required_ac_clearance_mm: 8.0
  - pcb_rule_area_found: True
  - pcb_edge_cuts_found: True
  - pcb_footprints_present: True
  - datasheet_pinout_verified: False
  - rf_stackup_dielectric_verified: False
  - ac_creepage_certification_checked: False
  - spice_si_pi_thermal_models_matched: False
  - note: UYARI: datasheet_pinout, rf_stackup, ac_creepage ve spice_models kalemleri otomatik dogrulanamaz. Gercek uretimden once bir elektronik muhendisi tarafindan manuel olarak onaylanmalidir.
