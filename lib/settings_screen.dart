import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _formKey = GlobalKey<FormState>();
  final _modelCtrl = TextEditingController();
  final _baseUrlCtrl = TextEditingController();
  final _apiKeyCtrl = TextEditingController();
  final _maxTokensCtrl = TextEditingController();
  final _timeoutCtrl = TextEditingController();

  String _provider = 'ollama';
  double _temperature = _defaultTemperature;
  bool _loading = true;
  bool _saving = false;
  String? _error;
  bool _obscureApiKey = true;

  // Varsayılan değerler — tek yerden yönetilir
  static const int _defaultMaxTokens = 16384;
  static const double _defaultTemperature = 0.15;
  static const int _defaultTimeoutSeconds = 600;

  // Connection testing state
  bool _testingConnection = false;
  String? _connectionSuccess;
  String? _connectionError;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  @override
  void dispose() {
    _modelCtrl.dispose();
    _baseUrlCtrl.dispose();
    _apiKeyCtrl.dispose();
    _maxTokensCtrl.dispose();
    _timeoutCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadSettings() async {
    try {
      final file = File('engine/ai_settings.json');
      if (await file.exists()) {
        final content = await file.readAsString();
        final json = jsonDecode(content) as Map<String, dynamic>;
        setState(() {
          _provider = json['provider'] ?? 'ollama';
          _modelCtrl.text = json['model'] ?? '';
          _baseUrlCtrl.text = json['base_url'] ?? '';
          // _comment_* anahtarlarını API key alanına yansıtma
          final rawKey = json['api_key'] ?? '';
          _apiKeyCtrl.text = rawKey is String && !rawKey.startsWith('_') ? rawKey : '';
          _temperature = (json['temperature'] as num?)?.toDouble() ?? _defaultTemperature;
          _maxTokensCtrl.text = (json['max_tokens'] ?? _defaultMaxTokens).toString();
          _timeoutCtrl.text = (json['timeout_seconds'] ?? _defaultTimeoutSeconds).toString();
          _loading = false;
        });
      } else {
        setState(() {
          _provider = 'ollama';
          _modelCtrl.text = 'gemma4';
          _baseUrlCtrl.text = 'http://localhost:11434';
          _apiKeyCtrl.text = '';
          _temperature = _defaultTemperature;
          _maxTokensCtrl.text = _defaultMaxTokens.toString();
          _timeoutCtrl.text = _defaultTimeoutSeconds.toString();
          _loading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = 'Ayarlar yuklenirken hata olustu: $e';
        _loading = false;
      });
    }
  }

  Future<void> _testConnection() async {
    setState(() {
      _testingConnection = true;
      _connectionError = null;
      _connectionSuccess = null;
    });

    final provider = _provider;
    final model = _modelCtrl.text.trim();
    final baseUrl = _baseUrlCtrl.text.trim().replaceAll(RegExp(r'/$'), '');
    final apiKey = _apiKeyCtrl.text.trim();

    // Cloud provider'lar için 15 saniye timeout (ağ gecikmesi olabilir)
    const cloudTimeout = Duration(seconds: 15);
    const localTimeout = Duration(seconds: 5);

    try {
      if (provider == 'ollama') {
        final url = Uri.parse('$baseUrl/api/tags');
        final response = await http.get(url).timeout(localTimeout);
        if (response.statusCode == 200) {
          // Model listesini göster
          try {
            final data = jsonDecode(response.body) as Map<String, dynamic>;
            final models =
                (data['models'] as List?)
                    ?.map((m) => (m as Map)['name'] as String? ?? '')
                    .where((m) => m.isNotEmpty)
                    .toList() ??
                [];
            final modelList = models.take(5).join(', ');
            setState(
              () => _connectionSuccess =
                  'Ollama baglanti basarili! ✓\nYuklu modeller: $modelList',
            );
          } catch (_) {
            setState(
              () => _connectionSuccess = 'Ollama baglantisi basarili! ✓',
            );
          }
        } else {
          setState(
            () => _connectionError =
                'Ollama baglantisi basarisiz. HTTP ${response.statusCode}\nOllama calistigindan emin olun: ollama serve',
          );
        }
      } else if (provider == 'gemini') {
        if (apiKey.isEmpty) throw Exception('API Anahtari bos birakilamaz');
        var geminiModel = model;
        if (!geminiModel.startsWith('models/') &&
            !geminiModel.startsWith('gemini-')) {
          geminiModel = 'gemini-$geminiModel';
        }
        final url = Uri.parse(
          'https://generativelanguage.googleapis.com/v1beta/models/$geminiModel:generateContent?key=$apiKey',
        );
        final response = await http
            .post(
              url,
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({
                'contents': [
                  {
                    'parts': [
                      {'text': 'hi'},
                    ],
                  },
                ],
                'generationConfig': {'maxOutputTokens': 5},
              }),
            )
            .timeout(cloudTimeout);
        if (response.statusCode == 200) {
          setState(
            () => _connectionSuccess =
                'Gemini baglantisi basarili! ✓\nModel: $geminiModel',
          );
        } else if (response.statusCode == 400 || response.statusCode == 403) {
          final body = response.body;
          if (body.contains('API_KEY_INVALID') ||
              body.contains('invalid') ||
              body.contains('INVALID_ARGUMENT')) {
            setState(
              () => _connectionError =
                  'Gemini API Anahtari gecersiz.\nDogrulama: https://aistudio.google.com/app/apikey',
            );
          } else {
            setState(
              () => _connectionError =
                  'Gemini hatasi (${response.statusCode}): $body',
            );
          }
        } else {
          setState(
            () => _connectionError =
                'Gemini yanit kodu: ${response.statusCode}\n${response.body.substring(0, response.body.length.clamp(0, 300))}',
          );
        }
      } else if (provider == 'openai') {
        if (apiKey.isEmpty) throw Exception('API Anahtari bos birakilamaz');
        // Önce modeli /v1/models ile dogrula (chat completion yerine — daha ucuz)
        final modelsUrl = Uri.parse('https://api.openai.com/v1/models/$model');
        final modelsResp = await http
            .get(modelsUrl, headers: {'Authorization': 'Bearer $apiKey'})
            .timeout(cloudTimeout);

        if (modelsResp.statusCode == 200) {
          setState(
            () => _connectionSuccess =
                'OpenAI baglantisi basarili! ✓\nModel dogrulandi: $model',
          );
        } else if (modelsResp.statusCode == 401) {
          setState(
            () => _connectionError =
                'OpenAI API Anahtari gecersiz (401 Unauthorized).\nDogrulama: https://platform.openai.com/api-keys',
          );
        } else if (modelsResp.statusCode == 404) {
          // Model bulunamadi ama API key geçerli — küçük bir mesaj gönder
          final chatUrl = Uri.parse(
            'https://api.openai.com/v1/chat/completions',
          );
          final chatResp = await http
              .post(
                chatUrl,
                headers: {
                  'Content-Type': 'application/json',
                  'Authorization': 'Bearer $apiKey',
                },
                body: jsonEncode({
                  'model': model,
                  'messages': [
                    {'role': 'user', 'content': 'hi'},
                  ],
                  'max_tokens': 1,
                }),
              )
              .timeout(cloudTimeout);
          if (chatResp.statusCode == 200) {
            setState(
              () => _connectionSuccess =
                  'OpenAI baglantisi basarili! ✓\nModel: $model',
            );
          } else if (chatResp.statusCode == 401) {
            setState(
              () => _connectionError =
                  'OpenAI API Anahtari gecersiz (401).\nhttps://platform.openai.com/api-keys',
            );
          } else {
            final body = chatResp.body;
            setState(
              () => _connectionError =
                  'OpenAI hatasi (${chatResp.statusCode}): ${body.substring(0, body.length.clamp(0, 400))}',
            );
          }
        } else {
          setState(
            () => _connectionError = 'OpenAI yanit: ${modelsResp.statusCode}',
          );
        }
      } else if (provider == 'nvidia') {
        if (apiKey.isEmpty) throw Exception('API Anahtari bos birakilamaz');
        final url = Uri.parse('$baseUrl/chat/completions');
        final response = await http
            .post(
              url,
              headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer $apiKey',
              },
              body: jsonEncode({
                'model': model,
                'messages': [
                  {'role': 'user', 'content': 'hi'},
                ],
                'max_tokens': 1,
              }),
            )
            .timeout(cloudTimeout);
        if (response.statusCode == 200) {
          setState(
            () => _connectionSuccess =
                'Nvidia NIM baglantisi basarili! ✓\nModel: $model',
          );
        } else if (response.statusCode == 401) {
          setState(
            () => _connectionError =
                'Nvidia NIM API Anahtari gecersiz (401).\nhttps://build.nvidia.com/explore/reasoning',
          );
        } else {
          setState(
            () => _connectionError =
                'Nvidia NIM hatasi (${response.statusCode}): ${response.body.substring(0, response.body.length.clamp(0, 300))}',
          );
        }
      } else if (provider == 'claude') {
        if (apiKey.isEmpty) throw Exception('API Anahtari bos birakilamaz');
        final url = Uri.parse('https://api.anthropic.com/v1/messages');
        final response = await http
            .post(
              url,
              headers: {
                'x-api-key': apiKey,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
              },
              body: jsonEncode({
                'model': model,
                'max_tokens': 5,
                'messages': [
                  {'role': 'user', 'content': 'hi'},
                ],
              }),
            )
            .timeout(cloudTimeout);

        if (response.statusCode == 200) {
          setState(
            () => _connectionSuccess =
                'Claude (Anthropic) baglantisi basarili! ✓\nModel: $model',
          );
        } else if (response.statusCode == 401) {
          setState(
            () => _connectionError =
                'Claude API Anahtari gecersiz (401 Unauthorized).\nDogrulama: https://console.anthropic.com/settings/keys',
          );
        } else if (response.statusCode == 400) {
          final body = response.body;
          if (body.contains('invalid_api_key')) {
            setState(
              () => _connectionError =
                  'Claude API Anahtari gecersiz.\nhttps://console.anthropic.com/settings/keys',
            );
          } else if (body.contains('not_found_error') ||
              body.contains('model')) {
            setState(
              () => _connectionError =
                  'Claude model bulunamadi: "$model"\nOrnek: claude-3-5-sonnet-20241022, claude-3-haiku-20240307',
            );
          } else {
            setState(
              () => _connectionError =
                  'Claude 400 hatasi: ${body.substring(0, body.length.clamp(0, 400))}',
            );
          }
        } else if (response.statusCode == 403) {
          setState(
            () => _connectionError =
                'Claude erisim reddedildi (403).\nBu modele erisim izniniz olmayabilir.',
          );
        } else {
          setState(
            () => _connectionError =
                'Claude hatasi (${response.statusCode}): ${response.body.substring(0, response.body.length.clamp(0, 400))}',
          );
        }
      }
    } on TimeoutException catch (_) {
      setState(
        () => _connectionError =
            '$provider baglanti zaman asimi (${provider == 'ollama' ? '5' : '15'} saniye).\n'
            'Lutfen internet baglantinizi ve API adresini kontrol edin.',
      );
    } catch (e) {
      String errMsg = e.toString();
      // Kullanici dostu hatalar
      if (errMsg.contains('SocketException') ||
          errMsg.contains('Connection refused')) {
        if (provider == 'ollama') {
          errMsg =
              'Ollama servisi bulunamadi. "ollama serve" komutu ile baslatiniz.';
        } else {
          errMsg =
              'Ag baglantisi kurulamadi. Internet baglantinizi kontrol edin.';
        }
      } else if (errMsg.contains('HandshakeException') ||
          errMsg.contains('Certificate')) {
        errMsg =
            'SSL/TLS hatasi. Sistem sertifikalari guncellenmis olmayabilir.';
      }
      setState(() => _connectionError = 'Baglanti hatasi: $errMsg');
    } finally {
      setState(() => _testingConnection = false);
    }
  }

  Future<void> _saveSettings() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });

    try {
      final settings = {
        'provider': _provider,
        'model': _modelCtrl.text.trim(),
        'base_url': _baseUrlCtrl.text.trim(),
        'api_key': _apiKeyCtrl.text.trim(),
        'temperature': _temperature,
        'max_tokens': int.tryParse(_maxTokensCtrl.text.trim()) ?? _defaultMaxTokens,
        'timeout_seconds': int.tryParse(_timeoutCtrl.text.trim()) ?? _defaultTimeoutSeconds,
      };

      final file = File('engine/ai_settings.json');
      const encoder = JsonEncoder.withIndent('  ');
      await file.writeAsString(encoder.convert(settings));

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Yapay zeka ayarlari kaydedildi ✓'),
            backgroundColor: Color(0xFF1F7A6D),
          ),
        );
        Navigator.of(context).pop();
      }
    } catch (e) {
      setState(() {
        _error = 'Ayarlar kaydedilirken hata olustu: $e';
        _saving = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Saglayici Ayarlari'),
        actions: [
          IconButton(
            tooltip: 'Kaydet',
            icon: _saving
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.save),
            onPressed: _saving ? null : _saveSettings,
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (_error != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red.shade50,
                    border: Border.all(color: Colors.red.shade200),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _error!,
                    style: TextStyle(color: Colors.red.shade700),
                  ),
                ),
                const SizedBox(height: 20),
              ],
              _buildSectionTitle('AI SAĞLAYICI SEÇİMİ'),
              const SizedBox(height: 12),
              _buildProviderSelector(),
              const SizedBox(height: 24),
              _buildSectionTitle('PARAMETRELER VE BAĞLANTI'),
              const SizedBox(height: 16),
              if (_provider == 'ollama' || _provider == 'nvidia') ...[
                TextFormField(
                  controller: _baseUrlCtrl,
                  decoration: InputDecoration(
                    labelText: _provider == 'ollama'
                        ? 'Sunucu Adresi (Base URL)'
                        : 'Nvidia NIM Sunucu Adresi',
                    prefixIcon: const Icon(Icons.link),
                    border: const OutlineInputBorder(),
                  ),
                  validator: (v) => v == null || v.trim().isEmpty
                      ? 'Sunucu adresi bos birakilamaz'
                      : null,
                ),
                const SizedBox(height: 16),
              ],
              TextFormField(
                controller: _modelCtrl,
                decoration: const InputDecoration(
                  labelText: 'Model Adi',
                  prefixIcon: Icon(Icons.memory),
                  border: OutlineInputBorder(),
                  helperText:
                      'Ornek: gemma4, gemini-3.5-flash, gpt-4o, claude-3-5-sonnet-20241022, minimax/minimax-01',
                ),
                validator: (v) => v == null || v.trim().isEmpty
                    ? 'Model adi bos birakilamaz'
                    : null,
              ),
              if (_provider != 'ollama') ...[
                const SizedBox(height: 16),
                TextFormField(
                  controller: _apiKeyCtrl,
                  obscureText: _obscureApiKey,
                  decoration: InputDecoration(
                    labelText: 'API Anahtarı (API Key)',
                    prefixIcon: const Icon(Icons.key),
                    border: const OutlineInputBorder(),
                    suffixIcon: IconButton(
                      icon: Icon(
                        _obscureApiKey
                            ? Icons.visibility
                            : Icons.visibility_off,
                      ),
                      onPressed: () =>
                          setState(() => _obscureApiKey = !_obscureApiKey),
                    ),
                  ),
                  validator: (v) => v == null || v.trim().isEmpty
                      ? 'API anahtari girilmesi zorunludur'
                      : null,
                ),
              ],
              const SizedBox(height: 24),
              // Connection Test Result Display
              if (_connectionSuccess != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.green.shade50,
                    border: Border.all(color: Colors.green.shade200),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _connectionSuccess!,
                    style: TextStyle(
                      color: Colors.green.shade800,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                const SizedBox(height: 16),
              ],
              if (_connectionError != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red.shade50,
                    border: Border.all(color: Colors.red.shade200),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    _connectionError!,
                    style: TextStyle(color: Colors.red.shade800),
                  ),
                ),
                const SizedBox(height: 16),
              ],
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _testingConnection ? null : _testConnection,
                  icon: _testingConnection
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.wifi_tethering),
                  label: Text(
                    _testingConnection
                        ? 'Baglanti Test Ediliyor...'
                        : 'Baglantiyi Test Et',
                  ),
                ),
              ),
              const SizedBox(height: 24),
              _buildSectionTitle('İLERİ DÜZEY AYARLAR'),
              const SizedBox(height: 16),
              Row(
                children: [
                  const Text('Sicaklik (Temperature)'),
                  const Spacer(),
                  Text(
                    _temperature.toStringAsFixed(2),
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ],
              ),
              Slider(
                value: _temperature,
                min: 0.0,
                max: 1.0,
                divisions: 10,
                onChanged: (v) => setState(() => _temperature = v),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _maxTokensCtrl,
                decoration: const InputDecoration(
                  labelText: 'Maksimum Yanit Token (Max Tokens)',
                  prefixIcon: Icon(Icons.format_list_numbered),
                  border: OutlineInputBorder(),
                  helperText: 'Tam netlist üretimi için min 16384 gereklidir (89 BOM komponenti ~12000 token)',
                ),
                keyboardType: TextInputType.number,
                validator: (v) {
                  if (v == null || int.tryParse(v) == null) return 'Geçerli bir sayı girin';
                  final n = int.parse(v);
                  if (n < 4096) return 'Uyarı: 4096 altında netlist eksik üretilir. Min 16384 önerilir.';
                  return null;
                },
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _timeoutCtrl,
                decoration: const InputDecoration(
                  labelText: 'AI Zaman Aşımı (saniye)',
                  prefixIcon: Icon(Icons.timer),
                  border: OutlineInputBorder(),
                  helperText: 'Ollama/lokal modeller için 600sn, bulut API için 60sn yeterli',
                ),
                keyboardType: TextInputType.number,
                validator: (v) => v == null || int.tryParse(v) == null
                    ? 'Geçerli bir sayı girin'
                    : null,
              ),
              const SizedBox(height: 36),
              FilledButton.icon(
                onPressed: _saving ? null : _saveSettings,
                icon: const Icon(Icons.save),
                label: const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Text('AYARLARI KAYDET'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: const TextStyle(
        fontSize: 12,
        fontWeight: FontWeight.bold,
        letterSpacing: 1.5,
        color: Color(0xFF1F7A6D),
      ),
    );
  }

  Widget _buildProviderSelector() {
    return Column(
      children: [
        _buildProviderRadio(
          id: 'ollama',
          name: 'Ollama (Lokal)',
          description: 'Yerel bilgisayarinizda calisan yapay zeka (Gemma 4).',
          icon: Icons.computer,
        ),
        const SizedBox(height: 8),
        _buildProviderRadio(
          id: 'gemini',
          name: 'Google Gemini',
          description: 'Google AI bulut servisi (API Anahtari gerektirir).',
          icon: Icons.auto_awesome,
        ),
        const SizedBox(height: 8),
        _buildProviderRadio(
          id: 'openai',
          name: 'OpenAI (GPT)',
          description: 'OpenAI GPT modelleri (API Anahtari gerektirir).',
          icon: Icons.psychology,
        ),
        const SizedBox(height: 8),
        _buildProviderRadio(
          id: 'claude',
          name: 'Anthropic Claude',
          description: 'Anthropic Claude modelleri (API Anahtari gerektirir).',
          icon: Icons.filter_drama,
        ),
        const SizedBox(height: 8),
        _buildProviderRadio(
          id: 'nvidia',
          name: 'Nvidia NIM / Minimax / Kimi',
          description:
              'Nvidia NIM OpenAI uyumlu bulut platformu (API Anahtari gerektirir).',
          icon: Icons.layers,
        ),
      ],
    );
  }

  Widget _buildProviderRadio({
    required String id,
    required String name,
    required String description,
    required IconData icon,
  }) {
    final isSelected = _provider == id;
    final color = isSelected ? const Color(0xFF1F7A6D) : Colors.grey.shade400;

    return InkWell(
      onTap: () {
        setState(() {
          _provider = id;
          _connectionError = null;
          _connectionSuccess = null;
          if (id == 'ollama') {
            _modelCtrl.text = 'gemma4';
            _baseUrlCtrl.text = 'http://localhost:11434';
          } else if (id == 'gemini') {
            _modelCtrl.text = 'gemini-2.5-flash';
            _baseUrlCtrl.text = '';
          } else if (id == 'openai') {
            _modelCtrl.text = 'gpt-4o-mini';
            _baseUrlCtrl.text = '';
          } else if (id == 'claude') {
            _modelCtrl.text = 'claude-sonnet-4-6';
            _baseUrlCtrl.text = '';
          } else if (id == 'nvidia') {
            _modelCtrl.text = 'minimax/minimax-01';
            _baseUrlCtrl.text = 'https://integrate.api.nvidia.com/v1';
          }
        });
      },
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected ? const Color(0xFF1F7A6D) : Colors.grey.shade300,
            width: isSelected ? 2 : 1,
          ),
          color: isSelected
              ? const Color(0xFF1F7A6D).withValues(alpha: 0.05)
              : Colors.transparent,
        ),
        child: Row(
          children: [
            Icon(icon, color: color, size: 28),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name,
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 15,
                      color: isSelected
                          ? const Color(0xFF1F7A6D)
                          : Colors.black87,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    description,
                    style: TextStyle(color: Colors.grey.shade600, fontSize: 12),
                  ),
                ],
              ),
            ),
            Radio<String>(
              value: id,
              // ignore: deprecated_member_use
              groupValue: _provider,
              activeColor: const Color(0xFF1F7A6D),
              // ignore: deprecated_member_use
              onChanged: (v) {
                if (v != null) {
                  setState(() {
                    _provider = v;
                    _connectionError = null;
                    _connectionSuccess = null;
                    if (v == 'ollama') {
                      _modelCtrl.text = 'gemma4';
                      _baseUrlCtrl.text = 'http://localhost:11434';
                    } else if (v == 'gemini') {
                      _modelCtrl.text = 'gemini-2.5-flash';
                      _baseUrlCtrl.text = '';
                    } else if (v == 'openai') {
                      _modelCtrl.text = 'gpt-4o-mini';
                      _baseUrlCtrl.text = '';
                    } else if (v == 'claude') {
                      _modelCtrl.text = 'claude-sonnet-4-6';
                      _baseUrlCtrl.text = '';
                    } else if (v == 'nvidia') {
                      _modelCtrl.text = 'minimax/minimax-01';
                      _baseUrlCtrl.text = 'https://integrate.api.nvidia.com/v1';
                    }
                  });
                }
              },
            ),
          ],
        ),
      ),
    );
  }
}
