import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/design_package.dart';
import '../services/kicad_pipeline_service.dart';

/// KiCad EDA pipeline adımlarının durumunu ve logunu yöneten controller.
/// Flutter UI, bu controller'a dinleyerek gerçek zamanlı geri bildirim alır.
class KiCadPipelineController extends ChangeNotifier {
  KiCadPipelineController({KiCadPipelineService? service})
      : _service = service ?? const KiCadPipelineService();

  final KiCadPipelineService _service;

  /// Çalışmakta olan adım (null = boşta)
  PipelineStep? runningStep;

  /// Tüm çalıştırma geçmişi (en yeni en sonda)
  final List<PipelineStepResult> history = [];

  /// Aktif adım için canlı log satırları
  final List<String> liveLog = [];

  /// DRC raporunu diskten yeniden yüklemek isteyenler için
  DrcReport? freshDrcReport;

  /// Layout optimization status diskten
  LayoutOptimizationStatus? freshOptimizationStatus;

  bool get isRunning => runningStep != null;

  // ---------- Pipeline adımlarını tetikle ----------

  Future<PipelineStepResult> runStep(PipelineStep step) async {
    if (isRunning) {
      return PipelineStepResult(
        step: step,
        success: false,
        exitCode: -1,
        stdout: '',
        stderr: 'Başka bir adım çalışıyor, lütfen bekleyin.',
        duration: Duration.zero,
      );
    }

    runningStep = step;
    liveLog
      ..clear()
      ..add('▶ ${step.label} başlatılıyor...');
    notifyListeners();

    final result = await _dispatchStep(step);

    history.add(result);
    liveLog.add(result.success
        ? '✓ Tamamlandı (${result.duration.inMilliseconds}ms)'
        : '✗ Hata (exit ${result.exitCode})');

    if (result.stdout.trim().isNotEmpty) {
      liveLog.addAll(result.stdout.trim().split('\n').take(60));
    }
    if (!result.success && result.stderr.trim().isNotEmpty) {
      liveLog.addAll(result.stderr.trim().split('\n').take(20));
    }

    // DRC / optimizer güncellemelerini diskten yeniden oku
    if (result.success &&
        (step == PipelineStep.layoutOptimizer ||
            step == PipelineStep.kicadPhase2)) {
      await _reloadDrcFromDisk();
    }

    runningStep = null;
    notifyListeners();
    return result;
  }

  Future<void> reloadDrcFromDisk() => _reloadDrcFromDisk();

  // ---------- Yardımcı ----------

  Future<PipelineStepResult> _dispatchStep(PipelineStep step) {
    return switch (step) {
      PipelineStep.kicadPhase2 => _service.runKiCadPhase2(),
      PipelineStep.layoutOptimizer => _service.runLayoutOptimizer(),
      PipelineStep.pcbaExports => _service.runPcbaExports(),
      PipelineStep.fabricationPackage => _service.runFabricationPackage(),
      PipelineStep.engineeringAudit => _service.runEngineeringAudit(),
      PipelineStep.simulationChecks => _service.runSimulationChecks(),
      PipelineStep.fabricationDrawing => _service.runFabricationDrawing(),
    };
  }

  Future<void> _reloadDrcFromDisk() async {
    freshDrcReport = await _tryLoadDrcReport();
    freshOptimizationStatus = await _tryLoadOptimizationStatus();
    notifyListeners();
  }

  static Future<DrcReport?> _tryLoadDrcReport() async {
    const path = r'assets\generated\drc_report_v1.json';
    try {
      final file = File(path);
      if (!file.existsSync()) return null;
      final text = await file.readAsString();
      return DrcReport.fromJson(jsonDecode(text) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  static Future<LayoutOptimizationStatus?> _tryLoadOptimizationStatus() async {
    const path = r'assets\generated\layout_optimization_status.json';
    try {
      final file = File(path);
      if (!file.existsSync()) return null;
      final text = await file.readAsString();
      return LayoutOptimizationStatus.fromJson(
        jsonDecode(text) as Map<String, dynamic>,
      );
    } catch (_) {
      return null;
    }
  }

  void clearHistory() {
    history.clear();
    liveLog.clear();
    notifyListeners();
  }
}
