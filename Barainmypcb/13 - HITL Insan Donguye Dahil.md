---
title: HITL - Insan Donguye Dahil Protokolu
tags:
  - hitl
  - architecture
  - human-in-the-loop
  - omnicircuit
status: active
updated: 2026-05-30
---

# HITL — Insan Donguye Dahil Protokolu

OmniCircuit AI, manufacturability'yi ya da elektriksel dogrulugu etkileyen
hicbir karar icin **tahmin yapmaz**. Belirsizlik var ise insan muhendise sorar.
Bu dosya o kontratin tek dogru kaynagidir.

## Neden Bu Sistem Var

2026-05-30 oturumunda U1 SMD ESP32-S3-WROOM-1 → ESP32-S3-DevKitC-1 socket
swap'i denendi. Pcbnew Python API ile yapilan auto-relocation + auto-routing
girisimi:

- 43 DRC violation ile basladi
- "Smart fix" iterasyonu sonrasi 196 violation'a yukseldi (DIVERGENCE)
- Pcbnew API push-and-shove router'a sahip olmadigi icin dense bir layout'ta
  guvenli surgical auto-routing imkansiz oldugu kanitlandi

Ders: agir layout/routing kararlari insan muhendis judgment'i ister. Sistem
"binbir yola sahip" davranisindan "soruyu cevapla, sonra devam et"
modeline gecti.

## Arayuz

**Dosya:** [`engine/hitl_manager.py`](../engine/hitl_manager.py)

**Public API:**

```python
from engine.hitl_manager import ask_human_engineer, emit_blocker, wait_for_answer

decision = ask_human_engineer(
    blocker_type="placement",   # routing | pinout | clearance | placement | constraint | bom
    question="<tek somut teknik soru>",
    context={...muhendis-okur fact'ler...},
    suggested_choices=[
        {"id": "A", "label": "...", "consequence": "..."},
        {"id": "B", "label": "...", "consequence": "..."},
    ],
    timeout_s=None,  # block indefinitely; sayi verirsen TimeoutError firlatir
)
# Doner: {"session_id", "decision", "rationale", "decided_at"}
```

## JSON Kontratı

Engine `assets/generated/hitl_state.json` yazar; Flutter UI bunu poll eder:

```json
{
  "schema": "HITL_STATE_V1",
  "status": "awaiting_human_input",
  "blocker_type": "routing|pinout|clearance|placement|constraint|bom",
  "session_id": "<uuid4>",
  "raised_at": "<iso8601-utc>",
  "context": { ... },
  "question": "<tek somut teknik soru>",
  "suggested_choices": [
    {"id": "A", "label": "...", "consequence": "..."}
  ],
  "answer_path": "assets/generated/hitl_answer.json"
}
```

Muhendis ya da UI `assets/generated/hitl_answer.json` yazar:

```json
{
  "session_id": "<state ile ayni uuid>",
  "decision": "A",
  "rationale": "<muhendis aciklamasi>",
  "decided_at": "<iso8601-utc>"
}
```

Engine eslesen session_id'yi gorunce dosyayi tuketir, kararı log'a yazar ve
state dosyasini siler.

## Blocker Tipleri

| Tip | Ne Zaman | Ornek |
|-----|----------|-------|
| `routing` | Cogul gecerli yol var, hangisi? | "DWM_IRQ icin L1 mi yoksa L4 mu?" |
| `pinout` | Datasheet/AI pinout cesitli | "ESP32 dev board hangi varyanti?" |
| `clearance` | Default rule overrule edilecek mi? | "AC creepage 8mm yerine 6mm yapayim mi?" |
| `placement` | Bir komponent nereye gitsin? | "DevKit (28x56mm) nereye yerlesecek?" |
| `constraint` | Eksik tasarim sarti | "+1V8 zone hangi ic katmanda?" |
| `bom` | BOM-PCB mismatch | "MOV1 vs RV1 — hangisi kullanilacak?" |

## Audit Trail

Her karar `assets/generated/hitl_decisions.log` dosyasina JSON Lines olarak
appended. Bir session sonu eski kararlar dahil tam izlenebilir.

```jsonl
{"session_id":"...","blocker_type":"placement","raised_at":"...","decided_at":"...",
 "question":"...","context":{...},"decision":"A","rationale":"..."}
```

## Mevcut Aktif Blocker (2026-05-30)

```text
blocker_type: placement
question: DevKit ESP32-S3-DevKitC-1 sockets (28×56mm) do not fit at the
         current U1 SMD location (94, 62) without colliding with R10-R13
         and K2. Where should the sockets go?
suggested_choices:
  A: Place at top-left (40,30), pins horizontal
  B: Place at top-right (120,30), pins horizontal
  C: Expand board to 175x100, place at (167,50)
  D: Keep SMD WROOM (skip DevKit conversion)
```

Engine bu blocker'i `hitl_state.json`'a yazdi. Engineer cevap verene kadar
DevKit swap pipeline'i pause durumunda. Production ZIP (SMD WROOM versiyonu)
bu pause'dan etkilenmez — disk uzerinde valid.

## Calisma Prensipleri

1. **NEVER GUESS.** Manufacturability/elektriksel dogruluk etkileniyorsa sor.
2. **Concrete questions only.** "Ne yapayim" degil, "Pin 8 IO7 mi IO15 mi?"
3. **Bring context.** Coordinates, refs, net names — muhendis hizli cevap versin diye.
4. **Log everything.** Karar + rationale kalici. Audit edilebilir.
5. **Timeout opsiyonel.** Batch run'larda `timeout_s` ile blocking'i sinirla.

## Ilgili Dosyalar

- [`engine/hitl_manager.py`](../engine/hitl_manager.py) — module kaynak
- `assets/generated/hitl_state.json` — aktif blocker (yoksa dosya yok)
- `assets/generated/hitl_answer.json` — engineer cevabi (consume edildikten sonra silinmez ama session_id ile reuse engellenir)
- `assets/generated/hitl_decisions.log` — JSONL audit trail

## Ilgili

- [[10 - Mühendislik Gerçeklik Kapısı]] — neden tahmin yapmadigimiz felsefe
- [[12 - AI Tamir Döngüsü]] — AI proposal'i ile HITL farki
- [[08 - Sonraki İşler]] — HITL'i pipeline'in diger noktalarina entegre etme planlari
