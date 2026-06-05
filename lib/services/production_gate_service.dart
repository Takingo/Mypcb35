import 'dart:convert';
import 'dart:io';

class ProductionGateSnapshot {
  const ProductionGateSnapshot({
    required this.generatedAt,
    required this.status,
    required this.manufacturingReady,
    required this.totalFindings,
    required this.violationCount,
    required this.unconnectedCount,
    required this.errorCount,
    required this.warningCount,
    required this.sourceEvidencePass,
    required this.productionModelPass,
    required this.evidenceSummary,
    required this.pcbSha256,
    required this.drcReportSha256,
    this.manifestPath = '',
  });

  final String generatedAt;
  final String status;
  final bool manufacturingReady;
  final int totalFindings;
  final int violationCount;
  final int unconnectedCount;
  final int errorCount;
  final int warningCount;
  final bool sourceEvidencePass;
  final bool productionModelPass;
  final String evidenceSummary;
  final String pcbSha256;
  final String drcReportSha256;
  final String manifestPath;

  bool get allowsManufacturing {
    return status == 'production_candidate' &&
        manufacturingReady &&
        violationCount == 0 &&
        unconnectedCount == 0 &&
        errorCount == 0 &&
        sourceEvidencePass &&
        productionModelPass &&
        pcbSha256.isNotEmpty &&
        drcReportSha256.isNotEmpty;
  }

  List<String> get blockers {
    final items = <String>[];
    if (status != 'production_candidate') {
      items.add('Manifest status=$status');
    }
    if (!manufacturingReady) {
      items.add('manufacturing_ready=false');
    }
    if (violationCount > 0 || unconnectedCount > 0 || errorCount > 0) {
      items.add(
        'DRC: $violationCount violation, $unconnectedCount unconnected, $errorCount error',
      );
    }
    if (!sourceEvidencePass) {
      items.add('Source evidence gate failed');
    }
    if (!productionModelPass) {
      items.add('Production model gate failed');
    }
    if (pcbSha256.isEmpty || drcReportSha256.isEmpty) {
      items.add('Board/DRC hash evidence missing');
    }
    return items;
  }

  factory ProductionGateSnapshot.fromJson(
    Map<String, dynamic> json, {
    String manifestPath = '',
  }) {
    return ProductionGateSnapshot(
      generatedAt: json['generated_at'] as String? ?? '',
      status: json['status'] as String? ?? 'unknown',
      manufacturingReady: json['manufacturing_ready'] as bool? ?? false,
      totalFindings: (json['total_findings'] as num?)?.toInt() ?? 0,
      violationCount: (json['violation_count'] as num?)?.toInt() ?? 0,
      unconnectedCount: (json['unconnected_count'] as num?)?.toInt() ?? 0,
      errorCount: (json['error_count'] as num?)?.toInt() ?? 0,
      warningCount: (json['warning_count'] as num?)?.toInt() ?? 0,
      sourceEvidencePass: json['source_evidence_pass'] as bool? ?? false,
      productionModelPass: json['production_model_pass'] as bool? ?? false,
      evidenceSummary: json['evidence_summary'] as String? ?? '',
      pcbSha256: json['pcb_sha256'] as String? ?? '',
      drcReportSha256: json['drc_report_sha256'] as String? ?? '',
      manifestPath: manifestPath,
    );
  }
}

class ProductionGateService {
  const ProductionGateService({
    this.projectRoot = r'C:\Mypcb',
    this.manifestRelativePath =
        r'assets\generated\board_verification_manifest.json',
  });

  final String projectRoot;
  final String manifestRelativePath;

  Future<ProductionGateSnapshot?> loadSnapshot() async {
    final path = _resolvePath(manifestRelativePath);
    final file = File(path);
    if (!await file.exists()) {
      return null;
    }
    final data =
        jsonDecode(await file.readAsString(encoding: utf8))
            as Map<String, dynamic>;
    return ProductionGateSnapshot.fromJson(data, manifestPath: path);
  }

  String _resolvePath(String path) {
    final normalized = path
        .split(RegExp(r'[\\/]'))
        .where((part) => part.isNotEmpty)
        .join(Platform.pathSeparator);
    final file = File(normalized);
    if (file.isAbsolute) {
      return normalized;
    }
    return [
      projectRoot,
      ...normalized.split(Platform.pathSeparator),
    ].join(Platform.pathSeparator);
  }
}
