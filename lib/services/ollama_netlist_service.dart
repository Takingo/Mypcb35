import 'dart:convert';
import 'dart:io';

/// Ollama veya yapılandırılmış AI provider üzerinden Python engine'i çağırır.
///
/// `engine/run_ai_synthesis.py` scripti:
///   - stderr → canlı log satırları
///   - stdout → tek JSON satırı (başarı/hata + netlist)
class OllamaNetlistService {
  const OllamaNetlistService({this.projectRoot = r'C:\Mypcb'});

  final String projectRoot;

  static const _kicadPythonPaths = [
    r'C:\Program Files\KiCad\10.0\bin\python.exe',
    r'C:\Program Files\KiCad\10.0\bin\python3.exe',
  ];

  /// Ollama/AI bağlantı durumunu kontrol eder.
  /// Ollama varsayılan olarak 11434'te çalışır.
  Future<OllamaStatus> checkConnection() async {
    try {
      final settings = await _loadSettings();
      final provider = settings['provider'] as String? ?? 'ollama';
      final model = settings['model'] as String? ?? 'gemma4';
      final baseUrl = settings['base_url'] as String? ?? 'http://localhost:11434';

      if (provider == 'ollama') {
        final client = HttpClient()..connectionTimeout = const Duration(seconds: 3);
        try {
          final uri = Uri.parse('$baseUrl/api/tags');
          final req = await client.getUrl(uri);
          final res = await req.close().timeout(const Duration(seconds: 3));
          final body = await res.transform(utf8.decoder).join();
          client.close();
          if (res.statusCode == 200) {
            final data = jsonDecode(body) as Map<String, dynamic>;
            final models = (data['models'] as List?)
                    ?.map((m) => (m as Map)['name'] as String? ?? '')
                    .toList() ??
                [];
            // Model eşleşmesi toleranslı: Ollama "gemma4:latest" listeler ama
            // ayar "gemma4" olabilir. Önce tam eşleşme, sonra ":latest"/prefix
            // eşleşmesi, en son ilk model. Böylece yapilandirilan model gercekten
            // kullanilir (yanlislikla minik bir modele dusmez).
            String _resolveModel() {
              if (models.contains(model)) return model;
              final prefixMatch = models.firstWhere(
                (m) => m == '$model:latest' || m.split(':').first == model,
                orElse: () => '',
              );
              if (prefixMatch.isNotEmpty) return prefixMatch;
              return models.isNotEmpty ? models.first : model;
            }

            final active = _resolveModel();
            return OllamaStatus(
              connected: true,
              provider: provider,
              model: active,
              availableModels: models,
              baseUrl: baseUrl,
            );
          }
        } catch (_) {
          client.close();
        }
        return OllamaStatus(
          connected: false,
          provider: provider,
          model: model,
          baseUrl: baseUrl,
        );
      }

      // Ollama dışı provider'lar için bağlantı kontrolü (API key varlığı)
      final apiKey = settings['api_key'] as String? ?? '';
      return OllamaStatus(
        connected: apiKey.isNotEmpty,
        provider: provider,
        model: model,
        baseUrl: baseUrl,
      );
    } catch (e) {
      return OllamaStatus(
        connected: false,
        provider: 'ollama',
        model: 'gemma4',
        error: e.toString(),
      );
    }
  }

  /// Python engine'i çalıştırarak AI netlist üretir.
  /// [onLog] callback'i canlı log satırları için (stderr'den)
  Future<AiSynthesisResult> synthesize({
    required String request,
    String bom = '',
    String notes = '',
    void Function(String line)? onLog,
  }) async {
    final python = _findPython();
    final scriptPath = '$projectRoot\\engine\\run_ai_synthesis.py';

    final process = await Process.start(
      python,
      [
        scriptPath,
        '--request', request,
        '--bom', bom,
        '--notes', notes,
        '--project-root', projectRoot,
      ],
      workingDirectory: projectRoot,
    );

    // stderr → canlı log
    process.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) => onLog?.call(line));

    // stdout → JSON sonuç (son satır)
    final stdoutLines = await process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .toList();

    await process.exitCode;

    // Son satır JSON
    final jsonLine = stdoutLines.reversed.firstWhere(
      (l) => l.trim().startsWith('{'),
      orElse: () => '',
    );

    if (jsonLine.isEmpty) {
      return const AiSynthesisResult(
        success: false,
        error: 'Python script JSON çıktısı üretmedi.',
      );
    }

    try {
      final data = jsonDecode(jsonLine) as Map<String, dynamic>;
      final success = data['success'] as bool? ?? false;
      final provider = data['provider'] as String? ?? '';
      final model = data['model'] as String? ?? '';
      final elapsed = (data['elapsed_seconds'] as num?)?.toDouble() ?? 0.0;
      final error = data['error'] as String?;
      final netlistJson = data['netlist'] as Map<String, dynamic>?;
      // 'synthesis_source' Python'dan geliyor — real_ai veya failed
      final synthesisSource = data['synthesis_source'] as String? ?? 'unknown';

      if (!success || netlistJson == null) {
        return AiSynthesisResult(
          success: false,
          provider: provider,
          model: model,
          elapsedSeconds: elapsed,
          error: error ?? 'Bilinmeyen hata',
          synthesisSource: synthesisSource,
        );
      }

      return AiSynthesisResult(
        success: true,
        provider: provider,
        model: model,
        elapsedSeconds: elapsed,
        netlistJson: netlistJson,
        synthesisSource: synthesisSource,
      );
    } catch (e) {
      return AiSynthesisResult(
        success: false,
        error: 'JSON parse hatasi: $e\n$jsonLine',
        synthesisSource: 'failed',
      );
    }
  }

  Future<Map<String, dynamic>> _loadSettings() async {
    final file = File('$projectRoot\\engine\\ai_settings.json');
    if (await file.exists()) {
      try {
        return jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      } catch (_) {}
    }
    return {};
  }

  String _findPython() {
    for (final p in _kicadPythonPaths) {
      if (File(p).existsSync()) return p;
    }
    // KiCad Python yoksa sistem Python'u dene
    return 'python';
  }
}

// ---------- Veri sınıfları ----------

class OllamaStatus {
  const OllamaStatus({
    required this.connected,
    required this.provider,
    required this.model,
    this.baseUrl = '',
    this.availableModels = const [],
    this.error,
  });

  final bool connected;
  final String provider;
  final String model;
  final String baseUrl;
  final List<String> availableModels;
  final String? error;

  String get statusLabel {
    if (connected) return '${provider.toUpperCase()} bağlı — $model';
    return '${provider.toUpperCase()} bağlanamadı';
  }
}

class AiSynthesisResult {
  const AiSynthesisResult({
    required this.success,
    this.provider = '',
    this.model = '',
    this.elapsedSeconds = 0,
    this.netlistJson,
    this.error,
    this.synthesisSource = 'unknown',
  });

  final bool success;
  final String provider;
  final String model;
  final double elapsedSeconds;
  final Map<String, dynamic>? netlistJson;
  final String? error;

  /// 'real_ai' = gerçek provider kullanıldı
  /// 'failed'  = provider yanıt vermedi (Flutter fallback kullanmalı)
  /// 'unknown' = eski Python versiyonu, alan yok
  final String synthesisSource;

  bool get usedRealAi => synthesisSource == 'real_ai';
}
