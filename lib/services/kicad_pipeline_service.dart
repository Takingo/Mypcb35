import 'dart:io';

/// KiCad pipeline adımlarını PowerShell scriptleri üzerinden tetikleyen servis.
/// Windows'ta [Process.run] ile çalışır; platformdan bağımsız test için
/// kolayca mock'lanabilecek şekilde tasarlanmıştır.
class KiCadPipelineService {
  const KiCadPipelineService({this.projectRoot = r'C:\Mypcb'});

  final String projectRoot;

  /// KiCad PCB/şematik üretimi (Faz 2)
  Future<PipelineStepResult> runKiCadPhase2() => _runScript(
    step: PipelineStep.kicadPhase2,
    scriptPath: r'tool\run_kicad_phase2.ps1',
  );

  /// Layout optimizasyonu + DRC kapalı döngüsü (Faz 4)
  Future<PipelineStepResult> runLayoutOptimizer() => _runScript(
    step: PipelineStep.layoutOptimizer,
    scriptPath: r'tool\run_layout_optimizer.ps1',
  );

  /// PCBA görsel export: PDF/SVG/GLB (Faz 4 sonrası)
  Future<PipelineStepResult> runPcbaExports() => _runScript(
    step: PipelineStep.pcbaExports,
    scriptPath: r'tool\run_pcba_exports.ps1',
  );

  /// Üretim ZIP paketi oluşturma (Faz 5)
  Future<PipelineStepResult> runFabricationPackage({
    int quantity = 5,
    String manufacturer = 'PCBWay',
    String solderMaskColor = 'Green',
  }) => _runScript(
    step: PipelineStep.fabricationPackage,
    scriptPath: r'tool\run_fabrication_package.ps1',
    args: [
      '-Quantity', '$quantity',
      '-Manufacturer', manufacturer,
      '-SolderMaskColor', solderMaskColor,
    ],
  );

  /// Mühendislik gerçeklik kapısı denetimi
  Future<PipelineStepResult> runEngineeringAudit() => _runScript(
    step: PipelineStep.engineeringAudit,
    scriptPath: r'tool\run_engineering_audit.ps1',
  );

  /// Simülasyon kontrolleri
  Future<PipelineStepResult> runSimulationChecks() => _runScript(
    step: PipelineStep.simulationChecks,
    scriptPath: r'tool\run_simulation_checks.ps1',
  );

  /// Fabrication drawing üretimi
  Future<PipelineStepResult> runFabricationDrawing() => _runScript(
    step: PipelineStep.fabricationDrawing,
    scriptPath: r'tool\run_fabrication_drawing.ps1',
  );

  /// Birleşik tahta görünümlerini (pcb_top/bottom/pcba_assembly SVG) yeniden üretir.
  /// PCB/PCBA önizleme "Görünümü Yenile" butonu için kullanılır.
  Future<bool> renderBoardViews() async {
    final result = await _runScript(
      step: PipelineStep.pcbaExports,
      scriptPath: r'tool\render_board_views.ps1',
    );
    return result.success;
  }

  /// Birleşik tahta görünümlerinin mutlak disk yolları.
  String get pcbTopSvgPath => '$projectRoot\\outputs\\assembly\\pcb_top.svg';
  String get pcbBottomSvgPath =>
      '$projectRoot\\outputs\\assembly\\pcb_bottom.svg';
  String get pcbaAssemblySvgPath =>
      '$projectRoot\\outputs\\assembly\\pcba_assembly.svg';

  Future<PipelineStepResult> _runScript({
    required PipelineStep step,
    required String scriptPath,
    List<String> args = const [],
  }) async {
    final fullPath = '$projectRoot\\$scriptPath';
    final start = DateTime.now();
    try {
      final result = await Process.run(
        'powershell.exe',
        [
          '-NonInteractive',
          '-ExecutionPolicy', 'Bypass',
          '-File', fullPath,
          ...args,
        ],
        workingDirectory: projectRoot,
        runInShell: false,
      );
      final elapsed = DateTime.now().difference(start);
      final success = result.exitCode == 0;
      return PipelineStepResult(
        step: step,
        success: success,
        exitCode: result.exitCode,
        stdout: result.stdout.toString(),
        stderr: result.stderr.toString(),
        duration: elapsed,
      );
    } on ProcessException catch (e) {
      final elapsed = DateTime.now().difference(start);
      return PipelineStepResult(
        step: step,
        success: false,
        exitCode: -1,
        stdout: '',
        stderr: 'Process hatası: ${e.message}',
        duration: elapsed,
      );
    } catch (e) {
      final elapsed = DateTime.now().difference(start);
      return PipelineStepResult(
        step: step,
        success: false,
        exitCode: -1,
        stdout: '',
        stderr: 'Beklenmeyen hata: $e',
        duration: elapsed,
      );
    }
  }
}

enum PipelineStep {
  kicadPhase2,
  layoutOptimizer,
  pcbaExports,
  fabricationPackage,
  engineeringAudit,
  simulationChecks,
  fabricationDrawing;

  String get label => switch (this) {
    PipelineStep.kicadPhase2 => 'KiCad Proje Üretimi',
    PipelineStep.layoutOptimizer => 'Layout Optimizer + DRC',
    PipelineStep.pcbaExports => 'PCBA Export (PDF/SVG/GLB)',
    PipelineStep.fabricationPackage => 'Üretim ZIP Paketi',
    PipelineStep.engineeringAudit => 'Mühendislik Denetimi',
    PipelineStep.simulationChecks => 'Simülasyon Kontrolleri',
    PipelineStep.fabricationDrawing => 'Fabrication Drawing',
  };

  String get scriptFile => switch (this) {
    PipelineStep.kicadPhase2 => 'run_kicad_phase2.ps1',
    PipelineStep.layoutOptimizer => 'run_layout_optimizer.ps1',
    PipelineStep.pcbaExports => 'run_pcba_exports.ps1',
    PipelineStep.fabricationPackage => 'run_fabrication_package.ps1',
    PipelineStep.engineeringAudit => 'run_engineering_audit.ps1',
    PipelineStep.simulationChecks => 'run_simulation_checks.ps1',
    PipelineStep.fabricationDrawing => 'run_fabrication_drawing.ps1',
  };
}

class PipelineStepResult {
  const PipelineStepResult({
    required this.step,
    required this.success,
    required this.exitCode,
    required this.stdout,
    required this.stderr,
    required this.duration,
  });

  final PipelineStep step;
  final bool success;
  final int exitCode;
  final String stdout;
  final String stderr;
  final Duration duration;

  String get summary {
    final status = success ? '✓' : '✗';
    final ms = duration.inMilliseconds;
    return '$status ${step.label} (${ms}ms)';
  }

  String get combinedOutput {
    final parts = <String>[];
    if (stdout.trim().isNotEmpty) parts.add(stdout.trim());
    if (stderr.trim().isNotEmpty) parts.add('[STDERR] ${stderr.trim()}');
    return parts.join('\n');
  }
}
