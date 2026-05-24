---
title: Güvenlik ve Üretime Hazırlık
tags:
  - safety
  - manufacturing
  - pcbway
  - review
status: active
---

# Güvenlik ve Üretime Hazırlık

Bu not, üretim öncesi kontrol kapılarını açık tutmak için yazılmıştır.

> [!danger] Nihai Üretim Uyarısı
> DRC=0 olması, tasarımın otomatik olarak gerçek dünyada güvenli ve kusursuz olduğu anlamına gelmez. Özellikle AC şebeke, RF ve regülatör termali için mühendis onayı gerekir.

## Üretim İçin Gerekli Dosyalar

| Dosya | Durum |
| --- | --- |
| Gerber | `outputs/phase4/gerber/` |
| Drill | `outputs/phase4/drill/` |
| Pick and Place | `outputs/phase4/position/pick_and_place.csv` |
| BOM | `BOM.csv` ve `outputs/uwb_anchor/manufacturing/BOM_PCBA.csv` |
| KiCad PCB | `outputs/kicad/.../*.kicad_pcb` |
| DRC status | `outputs/phase4/layout_optimization_status.json` |

## Üretim Öncesi Kontrol Listesi

- [ ] DRC=0 doğrulandı.
- [ ] ERC raporu üretildi.
- [ ] Gerçek üretici footprint’leri doğrulandı.
- [ ] DWM3000 footprint pitch değeri 1.0mm doğrulandı.
- [ ] UWB RF trace 50 ohm stackup ile doğrulandı.
- [ ] RF trace üzerinde via/test point/component olmadığı doğrulandı.
- [ ] AC primer ve düşük voltaj tarafı arasında 8mm clearance/creepage doğrulandı.
- [ ] HLK-5M05 datasheet izolasyon gereksinimleri kontrol edildi.
- [ ] Röle kontak izolasyonu ve yük akımı doğrulandı.
- [ ] Regülatör akım/ısı hesabı yapıldı.
- [ ] Pick and Place koordinatları gerçek footprint merkezleriyle doğrulandı.
- [ ] BOM üretici parça numaraları ve stok durumu kontrol edildi.
- [ ] PCBWay/JLCPCB üretici kurallarıyla DFM kontrolü yapıldı.

## Güvenli Export Mantığı

Sistem sadece şu durumda `manufacturing_ready: true` kabul eder:

```text
final_violation_count == 0
```

Bu bayrak:

```text
outputs/phase4/layout_optimization_status.json
```

dosyasında tutulur.

## Üreticiye Gönderirken

PCBWay gibi üreticiye gönderilecek paket:

- Gerber zip
- Drill
- BOM
- CPL / Pick and Place
- Assembly drawing
- Fabrication drawing
- Stackup / impedance notları

> [!todo]
> Bir sonraki fazda Gerber klasörünü otomatik zipleyen ve BOM/CPL ile tek “manufacturer package” oluşturan servis eklenmeli.
