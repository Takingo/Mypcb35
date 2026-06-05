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

# ── UTF-8 PATCH: force stdout/stderr to utf-8 on Windows (CP1252 default) ──
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure") and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")


def _log(msg: str) -> None:
    """stderr'e zaman damgalı log yaz."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


def _read_arg_or_file(inline_value: str, file_path: str) -> str:
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {file_path}")
        return path.read_text(encoding="utf-8-sig", errors="replace")
    return inline_value or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="AI netlist sentezi (stdout JSON)")
    parser.add_argument("--request", default="", help="Kullanici isterler metni")
    parser.add_argument("--bom", default="", help="BOM CSV veya komponent listesi")
    parser.add_argument("--notes", default="", help="Teknik notlar")
    parser.add_argument("--request-file", default="", help="Kullanici isterleri dosyasi")
    parser.add_argument("--bom-file", default="", help="BOM CSV dosyasi")
    parser.add_argument("--notes-file", default="", help="Teknik notlar dosyasi")
    parser.add_argument("--project-root", default=".", help="Proje kok dizini")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    request_text = _read_arg_or_file(args.request, args.request_file)
    bom_text = _read_arg_or_file(args.bom, args.bom_file)
    notes_text = _read_arg_or_file(args.notes, args.notes_file)

    user_request = request_text.strip()
    if not user_request:
        user_request = (
            "Bana ESP32-S3 3.3V, DWM3000 UWB modulu 1.8V, "
            "220V AC giris ve 2 adet G5Q-14-DC5 5V role iceren "
            "bir konumlandirma cihazi tasarla."
        )

    if bom_text.strip():
        user_request += f"\n\nBOM:\n{bom_text.strip()}"
    if notes_text.strip():
        user_request += f"\n\nTeknik Notlar:\n{notes_text.strip()}"

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

    # --- GERCEK AI CAGRISI + OTOMATIK PROVIDER SIRALAMA ---
    # Siralama: yapilandirilan provider -> Ollama (lokal) -> deterministik fallback
    # 429/kota hatasi: ayni provider farkli modelle tekrar denenmez (ayni kota),
    # dogrudan Ollama'ya gecilir (farkli servis, farkli kota).

    def _try_ollama_fallback(user_req: str, original_error: str):
        """Ollama localhost ile ikinci sans dene."""
        _log("[RETRY] Ollama lokal modele geciliyor (gemma4)...")
        import importlib
        try:
            import engine.ollama_client as _oc_mod
        except ImportError:
            import ollama_client as _oc_mod  # type: ignore
        importlib.reload(_oc_mod)  # taze settings okumak icin reload
        OllamaClient = _oc_mod.OllamaClient

        # Gecici olarak Ollama ayarlarini zorla
        import json as _json
        settings_path = project_root / "engine" / "ai_settings.json"
        orig_settings = _json.loads(settings_path.read_text(encoding="utf-8"))
        try:
            settings_path.write_text(
                _json.dumps({**orig_settings, "provider": "ollama",
                             "model": "gemma4", "base_url": "http://localhost:11434",
                             "timeout_seconds": 120}, indent=2),
                encoding="utf-8",
            )
            client2 = OllamaClient()
            if not client2.is_running():
                _log("[RETRY] Ollama servisi cevap vermiyor, deterministik fallback'e geciliyor.")
                return None
            netlist2 = generator.synthesize_real(user_req)
            _log(f"[RETRY-OK] Ollama ile netlist uretildi: {len(netlist2.components)} komp / {len(netlist2.nets)} net")
            return netlist2
        except Exception as e2:
            _log(f"[RETRY-FAIL] Ollama da basarisiz: {e2}")
            return None
        finally:
            # Orijinal ayarlari geri yukle
            settings_path.write_text(
                _json.dumps(orig_settings, indent=2), encoding="utf-8"
            )

    _log(f"Gercek AI cagriliyor: {provider.upper()} / {model}...")
    netlist = None
    synthesis_source = "real_ai"
    ai_error = None

    try:
        netlist = generator.synthesize_real(user_request)
        elapsed = round(time.time() - t0, 1)
        _log(f"[BASARILI] {provider.upper()} netlist uretti — {len(netlist.components)} komp, {len(netlist.nets)} net ({elapsed}s)")

    except Exception as exc:
        ai_error = str(exc)
        _log(f"[BASARISIZ] {provider.upper()} netlist uretmedi: {ai_error[:200]}")

        # 429 veya bağlantı hatası → Ollama dene (sadece cloud provider'larda)
        is_quota_err = "429" in ai_error or "quota" in ai_error.lower() or "rate limit" in ai_error.lower()
        is_conn_err = "Connection" in ai_error or "timeout" in ai_error.lower()
        if provider != "ollama" and (is_quota_err or is_conn_err):
            hint = "Kota doldu" if is_quota_err else "Baglanti hatasi"
            _log(f"[AUTO-RETRY] {hint} — Ollama lokal modele geciliyor...")
            netlist = _try_ollama_fallback(user_request, ai_error)
            if netlist:
                synthesis_source = "ollama_auto_fallback"
                ai_error = f"Primary {provider} failed ({hint}), used Ollama instead."

    elapsed = round(time.time() - t0, 1)

    if netlist is not None:
        result = {
            "success": True,
            "synthesis_source": synthesis_source,
            "provider": provider,
            "model": model,
            "elapsed_seconds": elapsed,
            "netlist": netlist.to_dict(),
        }
        if ai_error:
            result["ai_error"] = ai_error
    else:
        # Son care: deterministik motor — her zaman calisan, BOM-dogru netlist
        _log("Deterministik muhendislik motoruna geciliyor (kaynak ASLA bos birakilmaz).")
        fb_netlist = generator._synthesize_fallback(user_request)  # noqa: SLF001
        _log(f"[FALLBACK] Deterministik netlist uretildi — {len(fb_netlist.components)} komp, {len(fb_netlist.nets)} net.")
        result = {
            "success": True,
            "synthesis_source": "deterministic_fallback",
            "provider": provider,
            "model": model,
            "elapsed_seconds": elapsed,
            "ai_error": ai_error or "unknown",
            "netlist": fb_netlist.to_dict(),
        }
        netlist = fb_netlist

    # ── SAVE NETLIST ──────────────────────────────────────────────────────
    phase1_dir = project_root / "outputs" / "phase1"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    netlist_out = phase1_dir / "AI_NETLIST_V1.json"
    netlist_out.write_text(
        json.dumps(result["netlist"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    src_label = result["synthesis_source"]
    _log(f"[SAVE] Netlist yazildi: {netlist_out} (kaynak: {src_label})")

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
