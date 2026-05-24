import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../models/ai_netlist.dart';
import '../models/design_package.dart';
import '../services/cognitive_netlist_service.dart';
import '../services/input_file_import_service.dart';
import '../services/ollama_netlist_service.dart';
import '../services/pcba_manufacturing_service.dart';

class NetlistController extends ChangeNotifier {
  NetlistController({
    CognitiveNetlistService? service,
    InputFileImportService? fileImportService,
    OllamaNetlistService? ollamaService,
    PcbaManufacturingService? manufacturingService,
  }) : _service = service ?? CognitiveNetlistService(),
       _fileImportService = fileImportService ?? InputFileImportService(),
       _ollamaService = ollamaService ?? const OllamaNetlistService(),
       _manufacturingService = manufacturingService ?? const PcbaManufacturingService() {
    loadConfiguredAI();
    _checkOllamaStatus();
  }

  final CognitiveNetlistService _service;
  final InputFileImportService _fileImportService;
  final OllamaNetlistService _ollamaService;
  final PcbaManufacturingService _manufacturingService;

  static const defaultRequest =
      'Bana ESP32-S3 3.3V, DWM3000 UWB modulu 1.8V, 220V AC giris ve 2 adet G5Q-14-DC5 5V role iceren bir konumlandirma cihazi tasarla.';

  String requestText = defaultRequest;
  String bomText = '';
  String technicalNotes = '';
  String? requestFileName;
  String? bomFileName;
  String? technicalNotesFileName;
  bool isGenerating = false;
  AiNetlist? netlist;
  DesignPackage? designPackage;
  DrcReport? drcReport;
  LayoutOptimizationStatus? layoutOptimizationStatus;
  EngineeringReadinessReport? engineeringReadinessReport;
  DesignStage selectedStage = DesignStage.analysis;
  final List<ReasoningEntry> liveLog = [];

  String configuredProvider = 'ollama';
  String configuredModel = 'gemma4';

  /// Ollama/AI bağlantı durumu
  OllamaStatus? ollamaStatus;

  /// Son AI sentez kaynağı: 'ai' (gerçek) | 'fallback' (statik)
  String lastSynthesisSource = '';

  /// Manufacturing export properties
  String selectedManufacturer = 'PCBWay';
  bool isExportingManufacturing = false;
  PcbaManufacturingExportResult? lastManufacturingExport;
  final List<String> manufacturingLog = [];

  Future<void> loadConfiguredAI() async {
    try {
      final file = File('engine/ai_settings.json');
      if (await file.exists()) {
        final content = await file.readAsString();
        final json = jsonDecode(content) as Map<String, dynamic>;
        configuredProvider = json['provider'] ?? 'ollama';
        configuredModel = json['model'] ?? 'gemma4';
      }
    } catch (_) {
      configuredProvider = 'ollama';
      configuredModel = 'gemma4';
    }
    notifyListeners();
  }

  Future<void> _checkOllamaStatus() async {
    final status = await _ollamaService.checkConnection();
    ollamaStatus = status;
    notifyListeners();
  }

  Future<void> refreshOllamaStatus() => _checkOllamaStatus();

  Future<void> generate() async {
    if (isGenerating) return;
    await loadConfiguredAI();
    isGenerating = true;
    liveLog.clear();
    netlist = null;
    designPackage = null;
    drcReport = null;
    layoutOptimizationStatus = null;
    engineeringReadinessReport = null;
    lastSynthesisSource = '';
    notifyListeners();

    // ---------- Gerçek AI çağrısı (Python engine → Ollama) ----------
    bool usedRealAi = false;
    try {
      final result = await _ollamaService.synthesize(
        request: requestText,
        bom: bomText,
        notes: technicalNotes,
        onLog: (line) {
          liveLog.add(
            ReasoningEntry(
              level: 'info',
              message: line,
              outcome: 'ai-log',
            ),
          );
          notifyListeners();
        },
      );

      // synthesis_source = 'real_ai' → gerçek provider kullandı
      // synthesis_source = 'failed'  → provider yanıt vermedi, fallback gerekli
      if (result.success && result.netlistJson != null && result.usedRealAi) {
        usedRealAi = true;
        lastSynthesisSource = 'ai';
        final aiNetlist = AiNetlist.fromPythonJson(
          result.netlistJson!,
          provider: result.provider,
          model: result.model,
          elapsedSeconds: result.elapsedSeconds,
        );

        // Design package'i AI netlist'ten oluştur
        final generated = _service.synthesizeFromAiNetlist(
          aiNetlist,
          requestText,
          bomText: bomText,
          technicalNotes: technicalNotes,
        );

        designPackage = generated;
        netlist = aiNetlist;
        liveLog.add(
          ReasoningEntry(
            level: 'info',
            message:
                '✓ GERCEK AI sentezi tamamlandi — '
                '${result.provider.toUpperCase()} / ${result.model} '
                '(${result.elapsedSeconds.toStringAsFixed(1)}s)',
            outcome: 'ai-complete',
          ),
        );
        notifyListeners();
      } else {
        // Gerçek AI başarısız veya synthesis_source != real_ai → dürüst uyarı
        final reason = result.error != null
            ? '${result.provider.toUpperCase()} hatasi: ${result.error}'
            : 'synthesis_source=${result.synthesisSource}';
        liveLog.add(
          ReasoningEntry(
            level: 'warning',
            message:
                'UYARI: ${result.provider.toUpperCase()} / ${result.model} yanit vermedi '
                '($reason). '
                'Deterministik motor devreye aliniyor...',
            outcome: 'fallback',
          ),
        );
        notifyListeners();
      }
    } catch (e) {
      liveLog.add(
        ReasoningEntry(
          level: 'warning',
          message: 'UYARI: AI cagrisi basarisiz ($e). Deterministik motor devreye aliniyor.',
          outcome: 'fallback',
        ),
      );
      notifyListeners();
    }

    // ---------- Deterministik fallback (her zaman çalışır) ----------
    if (!usedRealAi) {
      lastSynthesisSource = 'fallback';
      final generated = _service.synthesize(
        requestText,
        bomText: bomText,
        technicalNotes: technicalNotes,
      );
      // Fallback log satırlarını ekle
      for (final entry in generated.netlist.reasoningLog) {
        await Future<void>.delayed(const Duration(milliseconds: 80));
        liveLog.add(entry);
        notifyListeners();
      }
      designPackage = generated;
      netlist = generated.netlist;
    }

    drcReport = await _loadDrcReport();
    layoutOptimizationStatus = await _loadLayoutOptimizationStatus();
    engineeringReadinessReport = await _loadEngineeringReadinessReport();
    isGenerating = false;
    notifyListeners();
  }

  void updateRequest(String value) {
    requestText = value;
    requestFileName = null;
    notifyListeners();
  }

  void updateBom(String value) {
    bomText = value;
    bomFileName = null;
    notifyListeners();
  }

  void updateTechnicalNotes(String value) {
    technicalNotes = value;
    technicalNotesFileName = null;
    notifyListeners();
  }

  Future<InputFileImport?> importRequestFile() async {
    final imported = await _fileImportService.pickTextFile(
      dialogTitle: 'Devre isterleri veya sematik notu sec',
      allowedExtensions: InputFileImportService.designExtensions,
    );
    if (imported == null) {
      return null;
    }
    requestText = imported.content;
    requestFileName = imported.fileName;
    notifyListeners();
    return imported;
  }

  Future<InputFileImport> importRequestFilePath(String path) async {
    final imported = await _fileImportService.importFromPath(
      path: path,
      allowedExtensions: InputFileImportService.designExtensions,
    );
    requestText = imported.content;
    requestFileName = imported.fileName;
    notifyListeners();
    return imported;
  }

  Future<InputFileImport?> importBomFile() async {
    final imported = await _fileImportService.pickTextFile(
      dialogTitle: 'BOM dosyasi sec',
      allowedExtensions: InputFileImportService.bomExtensions,
    );
    if (imported == null) {
      return null;
    }
    bomText = imported.content;
    bomFileName = imported.fileName;
    notifyListeners();
    return imported;
  }

  Future<InputFileImport> importBomFilePath(String path) async {
    final imported = await _fileImportService.importFromPath(
      path: path,
      allowedExtensions: InputFileImportService.bomExtensions,
    );
    bomText = imported.content;
    bomFileName = imported.fileName;
    notifyListeners();
    return imported;
  }

  Future<InputFileImport?> importTechnicalNotesFile() async {
    final imported = await _fileImportService.pickTextFile(
      dialogTitle: 'Teknik not veya PCB kurallari dosyasi sec',
      allowedExtensions: InputFileImportService.designExtensions,
    );
    if (imported == null) {
      return null;
    }
    technicalNotes = imported.content;
    technicalNotesFileName = imported.fileName;
    notifyListeners();
    return imported;
  }

  Future<InputFileImport> importTechnicalNotesFilePath(String path) async {
    final imported = await _fileImportService.importFromPath(
      path: path,
      allowedExtensions: InputFileImportService.designExtensions,
    );
    technicalNotes = imported.content;
    technicalNotesFileName = imported.fileName;
    notifyListeners();
    return imported;
  }

  void selectStage(DesignStage stage) {
    selectedStage = stage;
    notifyListeners();
  }

  Future<DrcReport?> _loadDrcReport() async {
    try {
      final jsonText = await rootBundle.loadString(
        'assets/generated/drc_report_v1.json',
      );
      return DrcReport.fromJson(jsonDecode(jsonText) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<LayoutOptimizationStatus?> _loadLayoutOptimizationStatus() async {
    try {
      final jsonText = await rootBundle.loadString(
        'assets/generated/layout_optimization_status.json',
      );
      return LayoutOptimizationStatus.fromJson(
        jsonDecode(jsonText) as Map<String, dynamic>,
      );
    } catch (_) {
      return null;
    }
  }

  Future<EngineeringReadinessReport?> _loadEngineeringReadinessReport() async {
    try {
      final jsonText = await rootBundle.loadString(
        'assets/generated/engineering_readiness_report.json',
      );
      return EngineeringReadinessReport.fromJson(
        jsonDecode(jsonText) as Map<String, dynamic>,
      );
    } catch (_) {
      return null;
    }
  }

  Future<void> exportManufacturingPackage() async {
    if (isExportingManufacturing) return;

    isExportingManufacturing = true;
    manufacturingLog.clear();
    lastManufacturingExport = null;
    notifyListeners();

    manufacturingLog.add('Üretim paketi oluşturuluyor: $selectedManufacturer');
    notifyListeners();

    final result = await _manufacturingService.generateManufacturingPackage(
      manufacturer: selectedManufacturer,
      onProgress: (message) {
        manufacturingLog.add(message);
        notifyListeners();
      },
    );

    lastManufacturingExport = result;

    if (result.success) {
      manufacturingLog.add(
        '✓ Başarılı! ${result.fileCount} dosya oluşturuldu. '
        'Boyut: ${result.boardWidthMm.toStringAsFixed(1)} × ${result.boardHeightMm.toStringAsFixed(1)} mm, '
        'Bileşen: ${result.componentCount}, '
        'Maliyet: \$${result.costEstimateUsd.toStringAsFixed(2)}, '
        'Teslimat: ${result.leadTimeDays} gün'
      );
    } else {
      manufacturingLog.add('✗ Hata: ${result.error}');
    }

    isExportingManufacturing = false;
    notifyListeners();
  }

  void selectManufacturer(String manufacturer) {
    selectedManufacturer = manufacturer;
    notifyListeners();
  }
}
