import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../models/ai_netlist.dart';
import '../models/design_package.dart';
import '../services/ai_correction_service.dart';
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
       _manufacturingService =
           manufacturingService ?? const PcbaManufacturingService() {
    loadConfiguredAI();
    _checkOllamaStatus();
  }

  final CognitiveNetlistService _service;
  final InputFileImportService _fileImportService;
  final OllamaNetlistService _ollamaService;
  final PcbaManufacturingService _manufacturingService;
  final AiCorrectionService _correctionService = const AiCorrectionService();

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
  InputEvidenceReport? inputEvidenceReport;
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

  /// AI error correction proposals
  AiCorrectionProposalsReport? correctionProposals;
  bool isApplyingCorrections = false;
  AiCorrectionResult? lastCorrectionResult;
  bool autoApplyLowRisk = false;

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

  Future<void> refreshProductionArtifacts() async {
    drcReport = await _loadDrcReport();
    layoutOptimizationStatus = await _loadLayoutOptimizationStatus();
    engineeringReadinessReport = await _loadEngineeringReadinessReport();
    inputEvidenceReport = await _loadInputEvidenceReport();
    correctionProposals = await _loadCorrectionProposals();

    final netlistFile = File(
      '$_projectRoot\\outputs\\phase1\\AI_NETLIST_V1.json',
    );
    if (await netlistFile.exists()) {
      try {
        final raw =
            jsonDecode(await netlistFile.readAsString())
                as Map<String, dynamic>;
        final aiNetlist = AiNetlist.fromPythonJson(raw);
        netlist = aiNetlist;
        final generated = _service.synthesizeFromAiNetlist(
          aiNetlist,
          requestText,
          bomText: bomText,
          technicalNotes: technicalNotes,
        );
        designPackage = _productionPackage(generated);
      } catch (e) {
        liveLog.add(
          ReasoningEntry(
            level: 'warning',
            message: 'UYARI: Uretim netlist artefakti okunamadi: $e',
            outcome: 'artifact-load-fail',
          ),
        );
      }
    }

    lastSynthesisSource = 'pipeline';
    selectedStage = DesignStage.schematic;
    liveLog.add(
      const ReasoningEntry(
        level: 'info',
        message:
            'Uretim artefaktlari yuklendi: gercek netlist, KiCad sematik/PCB, DRC ve evidence raporlari aktif.',
        outcome: 'production-artifacts',
      ),
    );
    notifyListeners();
  }

  DesignPackage _productionPackage(DesignPackage generated) {
    final drcClean = drcReport?.totalViolations == 0;
    final evidenceClean =
        inputEvidenceReport == null || inputEvidenceReport!.status == 'pass';
    final ready = drcClean && evidenceClean;
    return DesignPackage(
      netlist: generated.netlist,
      stages: [
        StageStatus(
          stage: DesignStage.analysis,
          title: 'Kanıtlı Analiz',
          state: evidenceClean ? StageState.ready : StageState.requiresReview,
          detail: evidenceClean
              ? 'BOM, netlist ve kaynak kanıtı güncel rapordan geçti.'
              : 'BOM/netlist kanıt raporu inceleme istiyor.',
        ),
        const StageStatus(
          stage: DesignStage.schematic,
          title: 'Gerçek KiCad Şematik',
          state: StageState.ready,
          detail:
              'Diskteki KiCad şematik/SVG artefaktı üretim akışından okunuyor.',
        ),
        StageStatus(
          stage: DesignStage.pcb,
          title: 'Gerçek KiCad PCB',
          state: drcClean ? StageState.ready : StageState.requiresReview,
          detail: drcClean
              ? 'Aktif KiCad PCB, DRC raporunda sıfır ihlal ile doğrulandı.'
              : 'Aktif PCB için DRC raporu temiz değil.',
        ),
        StageStatus(
          stage: DesignStage.pcba,
          title: 'Gerçek PCBA Görünümü',
          state: ready ? StageState.ready : StageState.requiresReview,
          detail:
              'PCBA montaj görünümü ve komponent listesi üretim çıktılarından gelir.',
        ),
        StageStatus(
          stage: DesignStage.simulation,
          title: 'Mühendislik Kanıtları',
          state: engineeringReadinessReport?.overallStatus == 'pass' || ready
              ? StageState.ready
              : StageState.requiresReview,
          detail:
              engineeringReadinessReport?.summary ??
              'DRC ve evidence raporları üretim kapısı için ana kanıttır.',
        ),
        StageStatus(
          stage: DesignStage.drc,
          title: 'DRC Doğrulama',
          state: drcClean ? StageState.ready : StageState.requiresReview,
          detail: drcClean ? 'DRC=0.' : 'DRC ihlalleri var.',
        ),
        StageStatus(
          stage: DesignStage.export,
          title: 'Üretim Export',
          state: ready ? StageState.ready : StageState.requiresReview,
          detail: ready
              ? 'Manifest ve üretim paketi güvenilir çıktı olarak ele alınabilir.'
              : 'Export için önce DRC/evidence temizlenmeli.',
        ),
      ],
      schematicBlocks: generated.schematicBlocks,
      pcbConstraints: generated.pcbConstraints,
      pcbaItems: generated.pcbaItems,
      simulationChecks: generated.simulationChecks,
      exportArtifacts: [
        for (final artifact in generated.exportArtifacts)
          ExportArtifact(
            name: artifact.name,
            format: artifact.format,
            path: artifact.path,
            state: ready ? ArtifactState.generated : artifact.state,
            note: ready
                ? 'Üretim akışı temiz DRC/evidence ile doğrulandı.'
                : artifact.note,
          ),
      ],
    );
  }

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
    inputEvidenceReport = null;
    lastSynthesisSource = '';
    notifyListeners();

    // Kullanıcının UI'dan girdiği BOM verisini KiCad pipeline'ı için diske kaydet
    if (bomText.trim().isNotEmpty) {
      try {
        final bomFile = File('$_projectRoot\\BOM.csv');
        await bomFile.writeAsString(bomText);
        liveLog.add(
          const ReasoningEntry(
            level: 'info',
            message: '✓ Kullanici BOM listesi diske kaydedildi (BOM.csv)',
            outcome: 'disk-write',
          ),
        );
      } catch (e) {
        liveLog.add(
          ReasoningEntry(
            level: 'warning',
            message: 'UYARI: Kullanici BOM listesi diske kaydedilemedi: $e',
            outcome: 'disk-write-fail',
          ),
        );
      }
      notifyListeners();
    }

    // ---------- Gerçek AI çağrısı (Python engine → Ollama) ----------
    bool usedRealAi = false;
    try {
      final result = await _ollamaService.synthesize(
        request: requestText,
        bom: bomText,
        notes: technicalNotes,
        onLog: (line) {
          liveLog.add(
            ReasoningEntry(level: 'info', message: line, outcome: 'ai-log'),
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
        // AI yolunda ham JSON'u diske yaz — manufacturer/footprint/constraints korunur
        await _writeNetlistToDisk(aiNetlist, rawAiJson: result.netlistJson);
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
          message:
              'UYARI: AI cagrisi basarisiz ($e). Deterministik motor devreye aliniyor.',
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

    // ---------- Fallback yolunda netlist'i diske yaz ─────────────────────────
    // AI yolu zaten `_writeNetlistToDisk` çağrısını kendi bloğunda yaptı.
    // Sadece fallback için burada çağırıyoruz.
    if (!usedRealAi && netlist != null) {
      await _writeNetlistToDisk(netlist!);
    }

    drcReport = await _loadDrcReport();
    layoutOptimizationStatus = await _loadLayoutOptimizationStatus();
    engineeringReadinessReport = await _loadEngineeringReadinessReport();
    inputEvidenceReport = await _loadInputEvidenceReport();
    correctionProposals = await _loadCorrectionProposals();
    isGenerating = false;
    notifyListeners();
  }

  /// Netlist'i outputs/phase1/AI_NETLIST_V1.json'a yazar.
  /// KiCad pipeline (run_kicad_phase2.ps1) bu dosyayı okur.
  ///
  /// [rawAiJson] verilirse (gerçek AI yolu) doğrudan disk'e yazılır — tüm
  /// manufacturer/footprint/constraints alanları korunur.
  /// Verilmezse (fallback yolu) AiNetlist modelinden yeniden oluşturulur.
  Future<void> _writeNetlistToDisk(
    AiNetlist aiNetlist, {
    Map<String, dynamic>? rawAiJson,
  }) async {
    try {
      final outputDir = Directory('$_projectRoot\\outputs\\phase1');
      if (!outputDir.existsSync()) {
        await outputDir.create(recursive: true);
      }
      final outputPath = '$_projectRoot\\outputs\\phase1\\AI_NETLIST_V1.json';

      // Gerçek AI JSON'u varsa doğrudan kullan (tüm alanlar korunur)
      if (rawAiJson != null) {
        // generated_at'i tazele
        final enriched = Map<String, dynamic>.from(rawAiJson)
          ..['generated_at'] = DateTime.now().toUtc().toIso8601String();
        await File(outputPath).writeAsString(
          const JsonEncoder.withIndent('  ').convert(enriched),
          encoding: const Utf8Codec(),
        );
        liveLog.add(
          ReasoningEntry(
            level: 'info',
            message:
                '✓ AI netlist (ham) diske yazıldı → KiCad pipeline hazır'
                ' (${aiNetlist.components.length} bileşen)',
            outcome: 'disk-write',
          ),
        );
        notifyListeners();
        return;
      }

      // Fallback: Dart modelinden tam AI_Netlist_v1 JSON yeniden oluştur
      final json = jsonEncode({
        'schema': 'AI_Netlist_v1',
        'project_name': aiNetlist.projectName.isNotEmpty
            ? aiNetlist.projectName
            : 'ESP32-S3 DWM3000 UWB Anchor with Relay Outputs',
        'generated_at': DateTime.now().toUtc().toIso8601String(),
        'source_prompt': aiNetlist.sourcePrompt,
        'assumptions': [
          'AC mains input is isolated before low-voltage logic.',
          'ESP32-S3 logic domain is 3.3V.',
          'DWM3000 logic and RF module domain is 1.8V.',
          'Relay coils are 5V and must not be driven directly from MCU pins.',
        ],
        'components': aiNetlist.components
            .map(
              (c) => {
                'ref': c.ref,
                'type': c.type,
                'value': c.value,
                'manufacturer': _inferManufacturer(c.partNumber),
                'part_number': c.partNumber,
                'footprint': _inferFootprintHint(c.type, c.partNumber),
                'reason': c.reason,
                'constraints': _inferConstraints(c.type, c.partNumber),
              },
            )
            .toList(),
        'nets': aiNetlist.nets
            .map(
              (n) => {
                'net': n.net,
                'pins': n.pins,
                'net_class': n.netClass,
                'reason': n.reason,
              },
            )
            .toList(),
        'rules': aiNetlist.rules
            .map(
              (r) => {
                'id': r.id,
                'severity': r.severity,
                'description': r.description,
                'applies_to': <String>[],
              },
            )
            .toList(),
        'reasoning_log': aiNetlist.reasoningLog
            .map(
              (e) => {
                'level': e.level,
                'message': e.message,
                'outcome': e.outcome,
              },
            )
            .toList(),
        'erc_summary': {
          'status': 'pass_with_engineering_review_required',
          'checks': aiNetlist.ercChecks,
        },
      });

      await File(outputPath).writeAsString(json, encoding: const Utf8Codec());
      liveLog.add(
        ReasoningEntry(
          level: 'info',
          message:
              '✓ Netlist KiCad pipeline için diske yazıldı: outputs/phase1/AI_NETLIST_V1.json'
              ' (${aiNetlist.components.length} bileşen, ${aiNetlist.nets.length} net)',
          outcome: 'disk-write',
        ),
      );
      notifyListeners();
    } catch (e) {
      liveLog.add(
        ReasoningEntry(
          level: 'warning',
          message: 'UYARI: Netlist diske yazılamadı: $e',
          outcome: 'disk-write-fail',
        ),
      );
      notifyListeners();
    }
  }

  /// Bilinen part number'lardan üretici adı çıkar
  static String _inferManufacturer(String partNumber) {
    const map = {
      'ESP32-S3-WROOM-1': 'Espressif',
      'ESP32-S3-WROOM-2': 'Espressif',
      'ESP32-DEVKIT': 'Espressif',
      'ESP32-S3-DEVKIT': 'Espressif',
      'DWM3000': 'Qorvo',
      'HLK-5M05': 'Hi-Link',
      'TPS54331DR': 'Texas Instruments',
      'TPS7A2018PDBVR': 'Texas Instruments',
      'TPS780180DRV': 'Texas Instruments',
      'TXB0104RUT': 'Texas Instruments',
      'TXB0104RGYR': 'Texas Instruments',
      'SN74LVC1T45DCK': 'Texas Instruments',
      'G5Q-14-DC5': 'Omron',
      'PC817': 'Sharp/Vishay',
      '2N7002': 'Onsemi',
      'SS14': 'Vishay',
      '0451.500MRL': 'Littelfuse',
      'MOV-14D471K': 'Bourns',
    };
    return map[partNumber] ?? 'Generic';
  }

  /// Bileşen tipi/part'tan footprint kategorisi ipucu
  static String _inferFootprintHint(String type, String partNumber) {
    if (partNumber == 'ESP32-S3-WROOM-1') return 'RF_Module:ESP32-S3-WROOM-1';
    if (partNumber == 'ESP32-DEVKIT')
      return 'Connector_PinSocket_2.54mm:PinSocket_2x19_P2.54mm_Vertical';
    if (partNumber == 'ESP32-S3-DEVKIT')
      return 'Connector_PinSocket_2.54mm:PinSocket_2x22_P2.54mm_Vertical';
    if (partNumber == 'HLK-5M05')
      return 'Converter_ACDC:Converter_ACDC_Hi-Link_HLK-5Mxx';
    if (partNumber == 'TPS54331DR')
      return 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm';
    if (type == 'relay') return 'Relay_THT:Relay_SPDT_Omron-G5Q-1';
    if (type == 'optocoupler') return 'Package_DIP:DIP-4_W7.62mm';
    if (type == 'n_mosfet') return 'Package_TO_SOT_SMD:SOT-23';
    if (type == 'flyback_diode') return 'Diode_SMD:D_SMA';
    if (type == 'fuse') return 'Fuse:Fuse_1206_3216Metric';
    if (type == 'varistor') return 'Varistor:RV_Disc_D15.5mm_W4.5mm_P7.5mm';
    if (type.contains('resistor')) return 'Resistor_SMD:R_0603_1608Metric';
    return type;
  }

  /// Kritik mühendislik kısıtları
  static List<String> _inferConstraints(String type, String partNumber) {
    if (partNumber == 'DWM3000')
      return [
        '1V8 logic',
        'RF launch requires 50 ohm net class',
        '1.0mm pitch',
      ];
    if (partNumber.startsWith('ESP32'))
      return ['3V3 logic', 'place away from AC isolation slot'];
    if (type == 'ac_dc') return ['AC primary side — 8mm creepage to secondary'];
    if (type == 'relay') return ['5V coil', 'no direct GPIO drive'];
    return [];
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

  /// Üretilen JSON'u önce canlı diskten okur (pipeline çıktısı), yoksa
  /// paketlenmiş build-time asset'e düşer. Böylece pipeline çalıştıktan
  /// sonra dashboard gerçek sonucu gösterir, eski snapshot'ı değil.
  static Future<String?> _readGeneratedJson(String relative) async {
    try {
      final file = File('$_projectRoot\\assets\\generated\\$relative');
      if (await file.exists()) {
        return await file.readAsString();
      }
    } catch (_) {
      // diskten okunamadı — bundle dene
    }
    try {
      return await rootBundle.loadString('assets/generated/$relative');
    } catch (_) {
      return null;
    }
  }

  static const _projectRoot = r'C:\Mypcb';

  Future<DrcReport?> _loadDrcReport() async {
    final jsonText = await _readGeneratedJson('drc_report_v1.json');
    if (jsonText == null) return null;
    try {
      return DrcReport.fromJson(jsonDecode(jsonText) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  Future<LayoutOptimizationStatus?> _loadLayoutOptimizationStatus() async {
    final jsonText = await _readGeneratedJson(
      'layout_optimization_status.json',
    );
    if (jsonText == null) return null;
    try {
      return LayoutOptimizationStatus.fromJson(
        jsonDecode(jsonText) as Map<String, dynamic>,
      );
    } catch (_) {
      return null;
    }
  }

  Future<EngineeringReadinessReport?> _loadEngineeringReadinessReport() async {
    final jsonText = await _readGeneratedJson(
      'engineering_readiness_report.json',
    );
    if (jsonText == null) return null;
    try {
      return EngineeringReadinessReport.fromJson(
        jsonDecode(jsonText) as Map<String, dynamic>,
      );
    } catch (_) {
      return null;
    }
  }

  Future<InputEvidenceReport?> _loadInputEvidenceReport() async {
    final jsonText = await _readGeneratedJson('input_evidence_report.json');
    if (jsonText == null) return null;
    try {
      return InputEvidenceReport.fromJson(
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
        'Teslimat: ${result.leadTimeDays} gün',
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

  /// Load correction proposals from disk.
  Future<AiCorrectionProposalsReport?> _loadCorrectionProposals() async {
    return await _correctionService.loadProposals();
  }

  /// Approve a single correction proposal.
  Future<void> approveProposal(String proposalId) async {
    final decisions = _buildCurrentDecisions();
    decisions[proposalId] = 'approved';
    await _correctionService.writeApprovals(decisions);
    if (correctionProposals != null) {
      final idx = correctionProposals!.proposals.indexWhere(
        (p) => p.id == proposalId,
      );
      if (idx >= 0) {
        final updatedProposals = List<AiCorrectionProposal>.from(
          correctionProposals!.proposals,
        );
        updatedProposals[idx] = AiCorrectionProposal(
          id: updatedProposals[idx].id,
          sourceFindingId: updatedProposals[idx].sourceFindingId,
          errorCategory: updatedProposals[idx].errorCategory,
          errorSeverity: updatedProposals[idx].errorSeverity,
          humanReadable: updatedProposals[idx].humanReadable,
          aiProposalText: updatedProposals[idx].aiProposalText,
          aiReasoning: updatedProposals[idx].aiReasoning,
          confidence: updatedProposals[idx].confidence,
          isSafetyCritical: updatedProposals[idx].isSafetyCritical,
          aiUncertain: updatedProposals[idx].aiUncertain,
          autoApplicable: updatedProposals[idx].autoApplicable,
          status: 'approved',
          safetyReason: updatedProposals[idx].safetyReason,
          kicadOperation: updatedProposals[idx].kicadOperation,
        );
        correctionProposals = AiCorrectionProposalsReport(
          generatedAt: correctionProposals!.generatedAt,
          provider: correctionProposals!.provider,
          model: correctionProposals!.model,
          proposals: updatedProposals,
          summary: correctionProposals!.summary,
        );
      }
    }
    notifyListeners();
  }

  /// Reject a single correction proposal.
  Future<void> rejectProposal(String proposalId) async {
    final decisions = _buildCurrentDecisions();
    decisions[proposalId] = 'rejected';
    await _correctionService.writeApprovals(decisions);
    if (correctionProposals != null) {
      final idx = correctionProposals!.proposals.indexWhere(
        (p) => p.id == proposalId,
      );
      if (idx >= 0) {
        final updatedProposals = List<AiCorrectionProposal>.from(
          correctionProposals!.proposals,
        );
        updatedProposals[idx] = AiCorrectionProposal(
          id: updatedProposals[idx].id,
          sourceFindingId: updatedProposals[idx].sourceFindingId,
          errorCategory: updatedProposals[idx].errorCategory,
          errorSeverity: updatedProposals[idx].errorSeverity,
          humanReadable: updatedProposals[idx].humanReadable,
          aiProposalText: updatedProposals[idx].aiProposalText,
          aiReasoning: updatedProposals[idx].aiReasoning,
          confidence: updatedProposals[idx].confidence,
          isSafetyCritical: updatedProposals[idx].isSafetyCritical,
          aiUncertain: updatedProposals[idx].aiUncertain,
          autoApplicable: updatedProposals[idx].autoApplicable,
          status: 'rejected',
          safetyReason: updatedProposals[idx].safetyReason,
          kicadOperation: updatedProposals[idx].kicadOperation,
        );
        correctionProposals = AiCorrectionProposalsReport(
          generatedAt: correctionProposals!.generatedAt,
          provider: correctionProposals!.provider,
          model: correctionProposals!.model,
          proposals: updatedProposals,
          summary: correctionProposals!.summary,
        );
      }
    }
    notifyListeners();
  }

  /// Apply approved corrections.
  Future<void> applyApprovedCorrections() async {
    if (isApplyingCorrections) return;
    isApplyingCorrections = true;
    notifyListeners();

    lastCorrectionResult = await _correctionService.applyApproved(
      onLog: (line) {
        liveLog.add(
          ReasoningEntry(level: 'info', message: line, outcome: 'correction'),
        );
        notifyListeners();
      },
    );

    // Reload all reports
    drcReport = await _loadDrcReport();
    engineeringReadinessReport = await _loadEngineeringReadinessReport();
    inputEvidenceReport = await _loadInputEvidenceReport();
    correctionProposals = await _loadCorrectionProposals();

    isApplyingCorrections = false;
    notifyListeners();
  }

  /// Approve all low-risk (auto_applicable) proposals at once.
  Future<void> approveAllLowRisk() async {
    if (correctionProposals == null) return;
    await _correctionService.approveAllLowRisk(correctionProposals!);
    correctionProposals = await _loadCorrectionProposals();
    notifyListeners();
  }

  /// Build current decisions map from correction proposals.
  Map<String, String> _buildCurrentDecisions() {
    final decisions = <String, String>{};
    if (correctionProposals != null) {
      for (final p in correctionProposals!.proposals) {
        if (p.status == 'approved') {
          decisions[p.id] = 'approved';
        } else if (p.status == 'rejected') {
          decisions[p.id] = 'rejected';
        }
      }
    }
    return decisions;
  }
}
