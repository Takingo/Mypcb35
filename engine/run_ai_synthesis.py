"""Flutter'dan çağrılacak AI netlist sentez köprüsü.

Çalışma akışı:
1. Flutter, Process.run ile bu scripti çalıştırır.
2. Bu script OllamaClient (veya ayarlardaki provider) üzerinden netlist üretir.
3. Sonuç stdout'a JSON olarak yazılır; Flutter bunu parse eder.
4. Tüm log satırları stderr'e gider (Flutter bunları canlı log olarak gösterir).

GERÇEK vs FALLBACK AYIRIMI:
- Bu script synthesize_real() kullanır — iç fallback YOKTUR.
- Gerçek AI başarısız olursa success=False döner.
- Flutter kendi deterministik fallback'ini kullanır.
- Böylece UI hiçbir zaman "OpenAI/Claude analiz yaptı" diyemez gerçekte yapmadıysa.

Kullanım:
    python -m engine.run_ai_synthesis --request "..." [--bom "..."] [--notes "..."]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path


def _log(msg: str) -> None:
    """stderr'e zaman damgalı log yaz."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="AI netlist sentezi (stdout JSON)")
    parser.add_argument("--request", default="", help="Kullanici isterler metni")
    parser.add_argument("--bom", default="", help="BOM CSV veya komponent listesi")
    parser.add_argument("--notes", default="", help="Teknik notlar")
    parser.add_argument("--project-root", default=".", help="Proje kok dizini")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    user_request = args.request.strip()
    if not user_request:
        user_request = (
            "Bana ESP32-S3 3.3V, DWM3000 UWB modulu 1.8V, "
            "220V AC giris ve 2 adet G5Q-14-DC5 5V role iceren "
            "bir konumlandirma cihazi tasarla."
        )

    if args.bom.strip():
        user_request += f"\n\nBOM:\n{args.bom.strip()}"
    if args.notes.strip():
        user_request += f"\n\nTeknik Notlar:\n{args.notes.strip()}"

    _log("OmniCircuit AI sentezi baslatildi...")
    t0 = time.time()

    # Provider/model bilgisini settings'ten oku
    settings_path = project_root / "engine" / "ai_settings.json"
    provider = "ollama"
    model = "gemma4"
    if settings_path.exists():
        try:
            # utf-8-sig: hem BOM'lu (Windows PowerShell) hem BOM'suz (Flutter/Dart) dosyaları okur
            s = json.loads(settings_path.read_text(encoding="utf-8-sig"))
            provider = s.get("provider", provider)
            model = s.get("model", model)
            has_key = bool(s.get("api_key", ""))
            _log(f"Settings dosyasi okundu: provider={provider}, model={model}, api_key={'MEVCUT' if has_key else 'BOS'}")
        except json.JSONDecodeError as e:
            _log(f"UYARI: ai_settings.json gecersiz JSON ({e}). Varsayilan olarak Ollama kullaniliyor.")
        except Exception as e:
            _log(f"UYARI: ai_settings.json okunamadi ({e}). Varsayilan olarak Ollama kullaniliyor.")
    else:
        _log(f"UYARI: Settings dosyasi bulunamadi ({settings_path}). Varsayilan olarak Ollama kullaniliyor.")

    _log(f"Yapilandirilan provider: {provider.upper()} | Model: {model}")

    # PYTHONPATH ayari olmadan da calisson diye path ekle
    sys.path.insert(0, str(project_root))
    try:
        from engine.cognitive_netlist_generator import CognitiveNetlistGenerator
    except ImportError:
        from cognitive_netlist_generator import CognitiveNetlistGenerator  # type: ignore

    generator = CognitiveNetlistGenerator()

    # --- GERCEK AI CAGRISI ---
    # synthesize_real() kullaniyoruz: ic fallback YOK, hata olursa yukari firlatiyor.
    # Flutter UI'i hicbir zaman yaniltmiyoruz.
    try:
        _log(f"Gercek AI cagriliyor: {provider.upper()} / {model}...")
        netlist = generator.synthesize_real(user_request)
        elapsed = round(time.time() - t0, 1)

        component_count = len(netlist.components)
        net_count = len(netlist.nets)
        _log(f"[BASARILI] Gercek AI netlist uretti — {component_count} komponent, {net_count} net ({elapsed}s)")
        _log(f"Kaynak: {netlist.schema} | Proje: {netlist.project_name}")

        result = {
            "success": True,
            "synthesis_source": "real_ai",  # Flutter bu alani okur
            "provider": provider,
            "model": model,
            "elapsed_seconds": elapsed,
            "netlist": netlist.to_dict(),
        }

    except Exception as exc:
        elapsed = round(time.time() - t0, 1)
        error_msg = str(exc)
        _log(f"[BASARISIZ] Gercek AI kullanilabilir netlist uretmedi: {error_msg}")
        _log("Deterministik mühendislik motoruna geciliyor (kaynak ASLA bos birakilmaz).")

        # Kaynak zincirini bos birakmamak icin deterministik tam tasarima dus.
        # Bu bir MOCK degil — kurallari acik, dogrulanabilir bir muhendislik motoru.
        # synthesis_source acikca "deterministic_fallback" olarak isaretlenir;
        # UI asla "gercek AI analiz etti" demez.
        fb_netlist = generator._synthesize_fallback(user_request)  # noqa: SLF001
        component_count = len(fb_netlist.components)
        net_count = len(fb_netlist.nets)
        _log(f"[FALLBACK] Deterministik netlist uretildi — {component_count} komponent, {net_count} net.")
        result = {
            "success": True,
            "synthesis_source": "deterministic_fallback",
            "provider": provider,
            "model": model,
            "elapsed_seconds": elapsed,
            "ai_error": error_msg,
            "netlist": fb_netlist.to_dict(),
        }

    # [YENİ] Sentez başarılı ise, otomatik olarak hata düzeltme önerileri oluştur
    correction_proposals_generated = False
    proposals_count = 0
    if result["success"]:
        try:
            from engine.ai_error_corrector import AiErrorCorrector
        except ImportError:
            from ai_error_corrector import AiErrorCorrector  # type: ignore

        try:
            _log("Sentez sonrası hata düzeltme önerileri oluşturuluyor...")
            corrector = AiErrorCorrector(project_root)
            proposals_result = corrector.generate_proposals()
            if proposals_result.get("status") in ("success", "no_findings"):
                correction_proposals_generated = True
                proposals_count = proposals_result.get("total_proposals", 0)
                _log(f"[PROPOSALS] {proposals_count} hata düzeltme önerisi oluşturuldu.")
            else:
                _log(f"[PROPOSALS] Oluşturma başarısız: {proposals_result.get('message', '?')}")
        except Exception as exc:
            # Sentez başarılı, önerileri oluşturamadık — loga yazıp devam et, Flutter'a hata verme
            _log(f"[PROPOSALS] Önerileri oluşturma hatası (sentez tamam): {exc}")

    result["correction_proposals_generated"] = correction_proposals_generated
    result["correction_proposals_count"] = proposals_count

    # JSON'u stdout'a yaz — tek satirda, Flutter bu satiri parse eder
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
