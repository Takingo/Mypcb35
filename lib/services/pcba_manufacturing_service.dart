import 'dart:convert';
import 'dart:io';

import 'production_gate_service.dart';

class PcbaManufacturingExportResult {
  const PcbaManufacturingExportResult({
    required this.success,
    required this.manufacturer,
    required this.outputDir,
    required this.fileCount,
    required this.boardWidthMm,
    required this.boardHeightMm,
    required this.componentCount,
    this.costEstimateUsd = 0.0,
    this.leadTimeDays = 0,
    this.error,
  });

  final bool success;
  final String manufacturer;
  final String outputDir;
  final int fileCount;
  final double boardWidthMm;
  final double boardHeightMm;
  final int componentCount;
  final double costEstimateUsd;
  final int leadTimeDays;
  final String? error;
}

class PcbaManufacturingService {
  const PcbaManufacturingService({
    this.projectRoot = r'C:\Mypcb',
    this.kicadPython = r'C:\Program Files\KiCad\10.0\bin\python.exe',
    this.productionGateService,
  });

  final String projectRoot;
  final String kicadPython;
  final ProductionGateService? productionGateService;

  /// Generate complete PCBA manufacturing package for direct online submission.
  /// Supports: PCBWay, JLCPCB, Seeed Fusion
  Future<PcbaManufacturingExportResult> generateManufacturingPackage({
    required String manufacturer,
    String outputDir = r'outputs\pcba_manufacturing',
    void Function(String)? onProgress,
  }) async {
    onProgress?.call('Starting PCBA manufacturing export for $manufacturer...');

    final gateService =
        productionGateService ??
        ProductionGateService(projectRoot: projectRoot);
    final gate = await gateService.loadSnapshot();
    if (gate == null) {
      return PcbaManufacturingExportResult(
        success: false,
        manufacturer: manufacturer,
        outputDir: outputDir,
        fileCount: 0,
        boardWidthMm: 0,
        boardHeightMm: 0,
        componentCount: 0,
        error:
            'Production gate manifest not found. Run board verification before PCBA export.',
      );
    }
    if (!gate.allowsManufacturing) {
      return PcbaManufacturingExportResult(
        success: false,
        manufacturer: manufacturer,
        outputDir: outputDir,
        fileCount: 0,
        boardWidthMm: 0,
        boardHeightMm: 0,
        componentCount: 0,
        error:
            'Production gate is locked: ${gate.blockers.join(' | ')}. ${gate.evidenceSummary}',
      );
    }

    final scriptPath =
        '$projectRoot\\engine\\pcba_manufacturing_export_service.py';
    if (!File(scriptPath).existsSync()) {
      return PcbaManufacturingExportResult(
        success: false,
        manufacturer: manufacturer,
        outputDir: outputDir,
        fileCount: 0,
        boardWidthMm: 0,
        boardHeightMm: 0,
        componentCount: 0,
        error: 'Manufacturing export script not found at $scriptPath',
      );
    }

    try {
      final process = await Process.start(kicadPython, [
        scriptPath,
        '--manufacturer',
        manufacturer,
        '--output-dir',
        outputDir,
        '--asset-output',
        'assets/generated/pcba_manufacturing_package.json',
      ], workingDirectory: projectRoot);

      final outputLines = <String>[];
      final stderrLines = <String>[];

      process.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
            outputLines.add(line);
            onProgress?.call(line);
          });

      process.stderr
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((line) {
            stderrLines.add(line);
            onProgress?.call('ERROR: $line');
          });

      final exitCode = await process.exitCode;

      if (exitCode != 0) {
        return PcbaManufacturingExportResult(
          success: false,
          manufacturer: manufacturer,
          outputDir: outputDir,
          fileCount: 0,
          boardWidthMm: 0,
          boardHeightMm: 0,
          componentCount: 0,
          error:
              'Python script exited with code $exitCode: ${stderrLines.join('\n')}',
        );
      }

      final data = _decodeJsonObject(outputLines.join('\n'));
      if (data == null) {
        return PcbaManufacturingExportResult(
          success: false,
          manufacturer: manufacturer,
          outputDir: outputDir,
          fileCount: 0,
          boardWidthMm: 0,
          boardHeightMm: 0,
          componentCount: 0,
          error: 'No JSON output from Python script',
        );
      }

      final files = (data['files'] as List?)?.length ?? 0;
      final boardSizeList =
          (data['board_size_mm'] as List?)
              ?.map((v) => (v as num).toDouble())
              .toList() ??
          <double>[0.0, 0.0];
      final componentCount = (data['component_count'] as num?)?.toInt() ?? 0;
      final costMap = data['cost_estimate'] as Map<String, dynamic>?;
      final costEstimate = (costMap?['total_usd'] as num?)?.toDouble() ?? 0.0;
      final leadTime = (costMap?['lead_time_days'] as num?)?.toInt() ?? 0;

      return PcbaManufacturingExportResult(
        success: true,
        manufacturer: manufacturer,
        outputDir: outputDir,
        fileCount: files,
        boardWidthMm: boardSizeList.isNotEmpty ? boardSizeList[0] : 0,
        boardHeightMm: boardSizeList.length > 1 ? boardSizeList[1] : 0,
        componentCount: componentCount,
        costEstimateUsd: costEstimate,
        leadTimeDays: leadTime,
      );
    } catch (e) {
      return PcbaManufacturingExportResult(
        success: false,
        manufacturer: manufacturer,
        outputDir: outputDir,
        fileCount: 0,
        boardWidthMm: 0,
        boardHeightMm: 0,
        componentCount: 0,
        error: 'Exception: $e',
      );
    }
  }

  Map<String, dynamic>? _decodeJsonObject(String output) {
    final start = output.indexOf('{');
    final end = output.lastIndexOf('}');
    if (start < 0 || end <= start) {
      return null;
    }
    try {
      return jsonDecode(output.substring(start, end + 1))
          as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }
}
