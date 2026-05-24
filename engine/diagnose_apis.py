"""API bağlantı tanılama aracı — her provider için detaylı test."""
from __future__ import annotations
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

SETTINGS_FILE = Path(r"C:\Mypcb\engine\ai_settings.json")


def read_settings() -> dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    return {}


def test_gemini(api_key: str, model: str = "gemini-1.5-flash") -> None:
    print("\n=== GEMINI TESTI ===")
    if not api_key:
        print("HATA: API key bos!")
        return

    # Tam model adı
    if not model.startswith("models/") and not model.startswith("gemini-"):
        model = f"gemini-{model}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": "Reply with exactly: OK"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }).encode()

    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            print(f"BASARILI! Yanit: {text!r}")
            print(f"Model: {model}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        status = e.code
        print(f"HATA HTTP {status}")
        try:
            err = json.loads(body)
            msg = err.get("error", {}).get("message", body[:300])
            code = err.get("error", {}).get("code", status)
            print(f"Hata kodu: {code}")
            print(f"Mesaj: {msg}")
            if "API_KEY_INVALID" in msg or "API key" in msg:
                print("\nCOZUM: Google AI Studio'dan yeni key alin:")
                print("  https://aistudio.google.com/app/apikey")
            elif "USER_LOCATION_INVALID" in msg or "not supported" in msg.lower():
                print("\nCOZUM: Turkiye'den Gemini API kisitli olabilir.")
                print("  VPN deneyin VEYA Google Cloud AI proxy kullanin.")
            elif "quota" in msg.lower() or "RESOURCE_EXHAUSTED" in msg:
                print("\nCOZUM: Gemini ucretsiz kotasi doldu.")
                print("  Yarin tekrar deneyin veya Google Cloud billing ekleyin.")
        except Exception:
            print(f"Detay: {body[:400]}")
    except Exception as e:
        print(f"Ag hatasi: {e}")
        if "Connection refused" in str(e):
            print("Servis erisilemez. VPN veya internet baglantisi kontrol edin.")


def test_claude(api_key: str, model: str = "claude-3-5-sonnet-20241022") -> None:
    print("\n=== CLAUDE (ANTHROPIC) TESTI ===")
    if not api_key:
        print("HATA: API key bos!")
        return

    url = "https://api.anthropic.com/v1/messages"
    payload = json.dumps({
        "model": model,
        "max_tokens": 5,
        "messages": [{"role": "user", "content": "Reply with: OK"}],
    }).encode()

    try:
        req = urllib.request.Request(url, data=payload, headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            text = data["content"][0]["text"]
            print(f"BASARILI! Yanit: {text!r}")
            print(f"Model: {model}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        status = e.code
        print(f"HATA HTTP {status}")
        try:
            err = json.loads(body)
            etype = err.get("error", {}).get("type", "")
            msg = err.get("error", {}).get("message", body[:300])
            print(f"Hata tipi: {etype}")
            print(f"Mesaj: {msg}")
            if status == 401 or "authentication_error" in etype or "invalid_api_key" in etype:
                print("\nCOZUM: API key yanlis veya iptal edilmis.")
                print("  Yeni key olusturun: https://console.anthropic.com/settings/keys")
            elif "credit_balance_too_low" in msg or "billing" in msg.lower():
                print("\nCOZUM: Hesabinizda kredi YOK (USD 0.00)!")
                print("  Adimlar:")
                print("  1. https://console.anthropic.com/settings/billing")
                print("  2. 'Add funds' ile min $5 yukleyin")
                print("  3. Kart dogrulandiktan sonra API calisir")
                print("\n  NOT: 'Free tier' gosterisi rate limit tanimlari icin.")
                print("  API icin MUTLAKA kredi gerekiyor.")
            elif status == 403 or "permission" in etype:
                print("\nCOZUM: Model erisim izni yok veya hesap kısıtlı.")
                print(f"  Daha basit model deneyin: claude-3-haiku-20240307")
        except Exception:
            print(f"Detay: {body[:400]}")
    except Exception as e:
        print(f"Ag hatasi: {e}")


def main() -> None:
    settings = read_settings()
    provider = settings.get("provider", "ollama")
    model = settings.get("model", "")
    api_key = settings.get("api_key", "")

    print("=" * 60)
    print("OmniCircuit AI Baglanti Tanilama")
    print("=" * 60)
    print(f"Mevcut provider: {provider}")
    print(f"Mevcut model:    {model}")
    print(f"API key:         {'MEVCUT (' + api_key[:12] + '...)' if api_key else 'BOŞ'}")
    print()

    # Hangisini test etmek istiyoruz?
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
        key_arg = sys.argv[2] if len(sys.argv) > 2 else api_key
        if target == "gemini":
            test_gemini(key_arg, "gemini-1.5-flash")
        elif target == "claude":
            test_claude(key_arg, "claude-3-5-sonnet-20241022")
        elif target == "openai":
            print("OpenAI: insufficient_quota hatasi zaten bilinen sorun. Kredi yukleyin.")
    else:
        # Mevcut ayarlari test et
        if provider == "gemini":
            test_gemini(api_key, model)
        elif provider == "claude":
            test_claude(api_key, model)
        elif provider == "openai":
            print("OpenAI: insufficient_quota — platform.openai.com/billing")
        elif provider == "ollama":
            print("Ollama: Lokal servis, internet gerekmez.")

    print("\n" + "=" * 60)
    print("TAVSIYE EDILEN COZUMLER:")
    print("=" * 60)
    print()
    print("SECNEK 1 — GEMINI (En ucuz, ucretsiz kota var):")
    print("  1. https://aistudio.google.com/app/apikey → API key olustur")
    print("  2. Uygulama Ayarlar → Google Gemini")
    print("  3. Model: gemini-1.5-flash (ucretsiz)")
    print("  4. API key yapistir → Test et")
    print()
    print("SECNEK 2 — CLAUDE (Ekleme yapilmali):")
    print("  1. console.anthropic.com/settings/billing → $5+ yukle")
    print("  2. Uygulama Ayarlar → Anthropic Claude")
    print("  3. Model: claude-3-haiku-20240307 (en ucuz)")
    print("  4. API key yapistir → Test et")
    print()
    print("SECNEK 3 — OLLAMA (Ucretsiz, lokal):")
    print("  Zaten calisiyor! Ayarlar → Ollama → gemma4")
    print()


if __name__ == "__main__":
    main()
