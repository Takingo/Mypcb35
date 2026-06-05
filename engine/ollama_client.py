import json
import urllib.request
import urllib.error
import subprocess
import time
import os
from typing import Any

class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434"):
        # Load settings from ai_settings.json in the same directory
        self.settings_path = os.path.join(os.path.dirname(__file__), "ai_settings.json")
        self.settings = self._load_settings()
        
        self.provider = self.settings.get("provider", "ollama").lower()
        self.model = self.settings.get("model", "gemma4")
        self.host = self.settings.get("base_url", host).rstrip("/")
        self.api_key = self.settings.get("api_key", "")
        self.temperature = self.settings.get("temperature", 0.2)
        # Yavas lokal modeller icin ayarlanabilir timeout (sn). Buyuk modeller
        # (orn. gemma4 9.6GB) varsayilan 300sn'yi asabilir; API modelleri hizlidir.
        self.timeout_seconds = int(self.settings.get("timeout_seconds", 300))

    def _load_settings(self) -> dict[str, Any]:
        """Load AI settings from settings JSON file.

        Uses utf-8-sig to handle both UTF-8-with-BOM (Windows PowerShell default)
        and plain UTF-8 (Flutter/Dart default) gracefully.
        """
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8-sig") as f:
                    settings = json.load(f)
                    provider = settings.get("provider", "?")
                    model = settings.get("model", "?")
                    has_key = bool(settings.get("api_key", ""))
                    print(f"[Settings] Yuklendi: provider={provider}, model={model}, api_key={'MEVCUT' if has_key else 'BOŞ'}", flush=True)
                    return settings
            except json.JSONDecodeError as e:
                print(f"[Settings HATA] Gecersiz JSON: {self.settings_path}: {e}", flush=True)
            except Exception as e:
                print(f"[Settings HATA] Dosya okunamadi: {self.settings_path}: {e}", flush=True)
        else:
            print(f"[Settings] Dosya bulunamadi: {self.settings_path}. Varsayilan ayarlar kullaniliyor.", flush=True)
        return {}

    def is_running(self) -> bool:
        """Check if Ollama server is currently responsive."""
        try:
            url = f"{self.host}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def _ensure_running(self) -> bool:
        """Ensure Ollama is running, launching it if necessary."""
        if self.is_running():
            return True

        print("Ollama is not running. Attempting to start Ollama automatically...")
        
        # 1. Try launching the Windows System Tray app
        app_path = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama app.exe")
        launched = False
        if os.path.exists(app_path):
            try:
                subprocess.Popen([app_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
                launched = True
                print(f"Launched Ollama App from {app_path}")
            except Exception as e:
                print(f"Failed to launch Ollama App tray executable: {e}")

        # 2. If app launch failed or path doesn't exist, fallback to 'ollama serve' command
        if not launched:
            try:
                creation_flags = 0
                if os.name == 'nt':
                    creation_flags = subprocess.CREATE_NO_WINDOW
                subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=creation_flags)
                launched = True
                print("Launched 'ollama serve' in background.")
            except Exception as e:
                print(f"Failed to launch 'ollama serve' command: {e}")

        if not launched:
            return False

        # Wait for the service to start (up to 10 seconds)
        print("Waiting for Ollama service to become responsive...")
        for i in range(10):
            time.sleep(1)
            if self.is_running():
                print("Ollama is now online and responsive.")
                return True
        
        print("Timed out waiting for Ollama to become responsive.")
        return False

    def _clean_markdown_json(self, text: str) -> str:
        """Clean up markdown code blocks (e.g. ```json ... ```) from model response."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def generate_json(self, model: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        """Send a prompt to the configured AI provider and expect a JSON response."""
        # Use settings if loaded, otherwise fallback to arguments
        target_model = self.model if self.model else model
        provider = self.provider

        print(f"Routing request to provider: {provider} (model: {target_model})")

        if provider == "ollama":
            self._ensure_running()
            url = f"{self.host}/api/generate"
            payload = {
                "model": target_model,
                "system": system_prompt,
                "prompt": user_prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": self.temperature
                }
            }
            result = self._send_http_request(url, payload)
            try:
                # Ollama returns output directly or in "response" key
                if isinstance(result, dict) and "response" in result:
                    return json.loads(self._clean_markdown_json(result["response"]))
                return result
            except (json.JSONDecodeError, TypeError) as e:
                raise ValueError(f"Failed to parse Ollama JSON response: {e}. Raw response: {result}")

        elif provider == "gemini":
            if not self.api_key:
                raise ValueError("API Key is missing for Gemini provider. Please configure it in settings.")
            
            gemini_model = target_model
            if not gemini_model.startswith("models/") and not gemini_model.startswith("gemini-"):
                gemini_model = f"gemini-{gemini_model}"
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": f"System Prompt:\n{system_prompt}\n\nUser Request:\n{user_prompt}"
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": self.temperature
                }
            }
            
            result = self._send_http_request(url, payload)
            try:
                text_response = result["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(self._clean_markdown_json(text_response))
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                raise ValueError(f"Failed to parse Gemini response: {e}. Raw response: {result}")

        elif provider in ["openai", "nvidia"]:
            if not self.api_key:
                raise ValueError(f"API Key is missing for {provider} provider. Please configure it in settings.")
            
            if provider == "openai":
                url = "https://api.openai.com/v1/chat/completions"
            else:
                # Custom host (Nvidia NIM, LM Studio, etc.)
                url = f"{self.host}/chat/completions"
                
            payload = {
                "model": target_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": self.temperature
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            
            result = self._send_http_request(url, payload, headers)
            try:
                text_response = result["choices"][0]["message"]["content"]
                return json.loads(self._clean_markdown_json(text_response))
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                raise ValueError(f"Failed to parse OpenAI-compatible response: {e}. Raw response: {result}")

        elif provider == "claude":
            if not self.api_key:
                raise ValueError("API Key is missing for Claude provider. Please configure it in settings.")
            
            url = "https://api.anthropic.com/v1/messages"
            payload = {
                "model": target_model,
                "max_tokens": self.settings.get("max_tokens", 2048),
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": self.temperature
            }
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            
            result = self._send_http_request(url, payload, headers)
            try:
                text_response = result["content"][0]["text"]
                return json.loads(self._clean_markdown_json(text_response))
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                raise ValueError(f"Failed to parse Claude response: {e}. Raw response: {result}")

        else:
            raise ValueError(f"Unknown AI Provider: {provider}")

    def _send_http_request(self, url: str, payload: dict, custom_headers: dict = None) -> dict[str, Any]:
        """Helper to send POST request and return JSON response.

        Raises ConnectionError with readable message on HTTP errors so that
        run_ai_synthesis.py can report the exact failure to Flutter UI.
        """
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if custom_headers:
            headers.update(custom_headers)

        req = urllib.request.Request(url, data=data, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as e:
            # Read the error body for a human-readable error
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass

            status = e.code
            # Provider-specific help messages
            if status == 401:
                provider_hint = {
                    "anthropic": "https://console.anthropic.com/settings/keys",
                    "openai":    "https://platform.openai.com/api-keys",
                    "nvidia":    "https://build.nvidia.com/",
                    "google":    "https://aistudio.google.com/app/apikey",
                }.get(
                    next((k for k in ("anthropic", "openai", "nvidia", "google") if k in url), ""),
                    ""
                )
                hint = f" API anahtarinizi kontrol edin: {provider_hint}" if provider_hint else ""
                raise ConnectionError(
                    f"API Anahtari gecersiz veya yetkisiz (HTTP 401).{hint}"
                ) from e
            elif status == 403:
                raise ConnectionError(
                    f"API erisimi reddedildi (HTTP 403). Bu modele erisiminiz olmayabilir. "
                    f"URL: {url}. Detay: {error_body[:300]}"
                ) from e
            elif status == 404:
                raise ConnectionError(
                    f"API endpoint veya model bulunamadi (HTTP 404). "
                    f"Model adi dogru mu? URL: {url}. Detay: {error_body[:300]}"
                ) from e
            elif status == 429:
                # Provider-specific quota/rate-limit message — detect from URL,
                # NOT from error body keywords (Gemini's 429 message contains
                # the substring "billing" too, which used to incorrectly trigger
                # the OpenAI-specific error message).
                lurl = url.lower()
                if "googleapis.com" in lurl:
                    raise ConnectionError(
                        f"Gemini API kotasi asildi (HTTP 429). "
                        f"https://aistudio.google.com/app/apikey adresinden plan/kullanimi kontrol edin. "
                        f"Alternatif: Ayarlar'dan farkli bir Gemini model (gemini-2.5-flash, gemini-1.5-flash) "
                        f"veya provider (Ollama/Claude) secin. Detay: {error_body[:200]}"
                    ) from e
                elif "openai.com" in lurl:
                    if "insufficient_quota" in error_body:
                        raise ConnectionError(
                            f"OpenAI hesabinda kredi yetersiz (insufficient_quota). "
                            f"https://platform.openai.com/account/billing adresinden kredi yukleyin. "
                            f"Alternatif: Ayarlar'dan Ollama (lokal) veya Claude/Gemini secin."
                        ) from e
                    raise ConnectionError(
                        f"OpenAI API rate limit asildi (HTTP 429). Birkac saniye bekleyip tekrar deneyin. "
                        f"Detay: {error_body[:200]}"
                    ) from e
                elif "anthropic.com" in lurl:
                    raise ConnectionError(
                        f"Anthropic Claude API rate limit asildi (HTTP 429). "
                        f"Detay: {error_body[:200]}"
                    ) from e
                elif "nvidia.com" in lurl or "build.nvidia" in lurl:
                    raise ConnectionError(
                        f"Nvidia NIM rate limit asildi (HTTP 429). "
                        f"Detay: {error_body[:200]}"
                    ) from e
                else:
                    raise ConnectionError(
                        f"API rate limit asildi (HTTP 429). URL: {url}. "
                        f"Birkac saniye bekleyip tekrar deneyin. Detay: {error_body[:200]}"
                    ) from e
            else:
                raise ConnectionError(
                    f"HTTP {status} hatasi. URL: {url}. Detay: {error_body[:500]}"
                ) from e

        except urllib.error.URLError as e:
            reason = str(e.reason) if hasattr(e, "reason") else str(e)
            if "Connection refused" in reason or "ECONNREFUSED" in reason:
                raise ConnectionError(
                    f"Baglanti reddedildi. Servis calismiyor mu? URL: {url}"
                ) from e
            elif "timed out" in reason.lower() or "timeout" in reason.lower():
                raise ConnectionError(
                    f"Baglanti zaman asimi. AI servisi cok yavas yanit veriyor. URL: {url}"
                ) from e
            raise ConnectionError(f"Ag hatasi ({reason}). URL: {url}") from e

        except json.JSONDecodeError as e:
            raise ValueError(f"Sunucu gecersiz JSON dondu: {e}") from e


