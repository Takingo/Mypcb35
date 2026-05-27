import 'ai_netlist.dart';

enum DesignStage { analysis, schematic, pcb, pcba, simulation, drc, export }

class DesignPackage {
  const DesignPackage({
    required this.netlist,
    required this.stages,
    required this.schematicBlocks,
    required this.pcbConstraints,
    required this.pcbaItems,
    required this.simulationChecks,
    required this.exportArtifacts,
  });

  final AiNetlist netlist;
  final List<StageStatus> stages;
  final List<SchematicBlock> schematicBlocks;
  final List<PcbConstraint> pcbConstraints;
  final List<PcbaItem> pcbaItems;
  final List<SimulationCheck> simulationChecks;
  final List<ExportArtifact> exportArtifacts;

  int get completedStageCount =>
      stages.where((stage) => stage.state == StageState.ready).length;

  bool get manufacturingReady {
    return stages.every((stage) => stage.state == StageState.ready) &&
        exportArtifacts.every(
          (artifact) => artifact.state == ArtifactState.generated,
        );
  }
}

enum StageState { ready, blocked, requiresReview }

class StageStatus {
  const StageStatus({
    required this.stage,
    required this.title,
    required this.state,
    required this.detail,
  });

  final DesignStage stage;
  final String title;
  final StageState state;
  final String detail;
}

class SchematicBlock {
  const SchematicBlock({
    required this.name,
    required this.intent,
    required this.nets,
  });

  final String name;
  final String intent;
  final List<String> nets;
}

class PcbConstraint {
  const PcbConstraint({
    required this.id,
    required this.area,
    required this.rule,
    required this.severity,
  });

  final String id;
  final String area;
  final String rule;
  final String severity;
}

class PcbaItem {
  const PcbaItem({
    required this.ref,
    required this.partNumber,
    required this.placement,
    required this.assemblyNote,
  });

  final String ref;
  final String partNumber;
  final String placement;
  final String assemblyNote;
}

class SimulationCheck {
  const SimulationCheck({
    required this.name,
    required this.domain,
    required this.status,
    required this.result,
  });

  final String name;
  final String domain;
  final String status;
  final String result;
}

enum ArtifactState { generated, scaffolded, blocked }

class ExportArtifact {
  const ExportArtifact({
    required this.name,
    required this.format,
    required this.path,
    required this.state,
    required this.note,
  });

  final String name;
  final String format;
  final String path;
  final ArtifactState state;
  final String note;
}

class DrcReport {
  const DrcReport({
    required this.schema,
    required this.source,
    required this.totalViolations,
    required this.summaryByCategory,
    required this.violations,
  });

  final String schema;
  final String source;
  final int totalViolations;
  final Map<String, int> summaryByCategory;
  final List<DrcViolation> violations;

  factory DrcReport.fromJson(Map<String, dynamic> json) {
    final summary = <String, int>{};
    final rawSummary =
        json['summary_by_category'] as Map<String, dynamic>? ?? const {};
    for (final entry in rawSummary.entries) {
      summary[entry.key] = (entry.value as num?)?.toInt() ?? 0;
    }
    final rawViolations = json['violations'] as List<dynamic>? ?? const [];
    return DrcReport(
      schema: json['schema'] as String? ?? 'DRC_REPORT_V1',
      source: json['source'] as String? ?? '',
      totalViolations:
          (json['total_violations'] as num?)?.toInt() ?? rawViolations.length,
      summaryByCategory: summary,
      violations: rawViolations
          .whereType<Map<String, dynamic>>()
          .map(DrcViolation.fromJson)
          .toList(growable: false),
    );
  }
}

class DrcViolation {
  const DrcViolation({
    required this.id,
    required this.category,
    required this.severity,
    required this.description,
    required this.locations,
    required this.repairHint,
  });

  final String id;
  final String category;
  final String severity;
  final String description;
  final List<DrcLocation> locations;
  final String repairHint;

  factory DrcViolation.fromJson(Map<String, dynamic> json) {
    final rawLocations = json['locations'] as List<dynamic>? ?? const [];
    return DrcViolation(
      id: json['id'] as String? ?? '',
      category: json['category'] as String? ?? 'other',
      severity: json['severity'] as String? ?? 'unknown',
      description: json['description'] as String? ?? '',
      locations: rawLocations
          .whereType<Map<String, dynamic>>()
          .map(DrcLocation.fromJson)
          .toList(growable: false),
      repairHint: json['repair_hint'] as String? ?? '',
    );
  }

  String get coordinateLabel {
    if (locations.isEmpty ||
        locations.first.x == null ||
        locations.first.y == null) {
      return 'No coordinate';
    }
    final first = locations.first;
    return 'x=${first.x!.toStringAsFixed(2)}mm, y=${first.y!.toStringAsFixed(2)}mm';
  }
}

class DrcLocation {
  const DrcLocation({
    required this.x,
    required this.y,
    required this.layer,
    required this.item,
    required this.component,
  });

  final double? x;
  final double? y;
  final String? layer;
  final String item;
  final String? component;

  factory DrcLocation.fromJson(Map<String, dynamic> json) {
    return DrcLocation(
      x: (json['x'] as num?)?.toDouble(),
      y: (json['y'] as num?)?.toDouble(),
      layer: json['layer'] as String?,
      item: json['item'] as String? ?? '',
      component: json['component'] as String?,
    );
  }
}

class LayoutOptimizationStatus {
  const LayoutOptimizationStatus({
    required this.schema,
    required this.finalViolationCount,
    required this.manufacturingReady,
    required this.iterations,
    required this.notes,
  });

  final String schema;
  final int finalViolationCount;
  final bool manufacturingReady;
  final List<LayoutOptimizationIteration> iterations;
  final List<String> notes;

  factory LayoutOptimizationStatus.fromJson(Map<String, dynamic> json) {
    final rawIterations = json['iterations'] as List<dynamic>? ?? const [];
    final rawNotes = json['notes'] as List<dynamic>? ?? const [];
    return LayoutOptimizationStatus(
      schema: json['schema'] as String? ?? 'LAYOUT_OPTIMIZATION_RUN_V1',
      finalViolationCount:
          (json['final_violation_count'] as num?)?.toInt() ?? 0,
      manufacturingReady: json['manufacturing_ready'] as bool? ?? false,
      iterations: rawIterations
          .whereType<Map<String, dynamic>>()
          .map(LayoutOptimizationIteration.fromJson)
          .toList(growable: false),
      notes: rawNotes.whereType<String>().toList(growable: false),
    );
  }
}

class LayoutOptimizationIteration {
  const LayoutOptimizationIteration({
    required this.iteration,
    required this.before,
    required this.after,
    required this.actions,
  });

  final int iteration;
  final int before;
  final int after;
  final List<String> actions;

  factory LayoutOptimizationIteration.fromJson(Map<String, dynamic> json) {
    final rawActions = json['actions'] as List<dynamic>? ?? const [];
    return LayoutOptimizationIteration(
      iteration: (json['iteration'] as num?)?.toInt() ?? 0,
      before: (json['violation_count_before'] as num?)?.toInt() ?? 0,
      after: (json['violation_count_after'] as num?)?.toInt() ?? 0,
      actions: rawActions
          .whereType<Map<String, dynamic>>()
          .map((action) => '${action['action_type']}: ${action['target']}')
          .toList(growable: false),
    );
  }
}

class EngineeringReadinessReport {
  const EngineeringReadinessReport({
    required this.schema,
    required this.overallStatus,
    required this.readinessPercent,
    required this.summary,
    required this.checks,
  });

  final String schema;
  final String overallStatus;
  final int readinessPercent;
  final String summary;
  final List<EngineeringReadinessCheck> checks;

  factory EngineeringReadinessReport.fromJson(Map<String, dynamic> json) {
    final rawChecks = json['checks'] as List<dynamic>? ?? const [];
    return EngineeringReadinessReport(
      schema: json['schema'] as String? ?? 'ENGINEERING_READINESS_V1',
      overallStatus: json['overall_status'] as String? ?? 'unknown',
      readinessPercent: (json['readiness_percent'] as num?)?.toInt() ?? 0,
      summary: json['summary'] as String? ?? '',
      checks: rawChecks
          .whereType<Map<String, dynamic>>()
          .map(EngineeringReadinessCheck.fromJson)
          .toList(growable: false),
    );
  }
}

class EngineeringReadinessCheck {
  const EngineeringReadinessCheck({
    required this.id,
    required this.domain,
    required this.status,
    required this.severity,
    required this.evidence,
    required this.requiredAction,
  });

  final String id;
  final String domain;
  final String status;
  final String severity;
  final String evidence;
  final String requiredAction;

  factory EngineeringReadinessCheck.fromJson(Map<String, dynamic> json) {
    return EngineeringReadinessCheck(
      id: json['id'] as String? ?? '',
      domain: json['domain'] as String? ?? '',
      status: json['status'] as String? ?? 'unknown',
      severity: json['severity'] as String? ?? 'info',
      evidence: json['evidence'] as String? ?? '',
      requiredAction: json['required_action'] as String? ?? '',
    );
  }
}

/// Girdi Paneli (BOM/istek/netlist) kanit dogrulama raporu — INPUT_EVIDENCE_V1.
/// Kullanicinin verdigi listede hata varsa burada gorunur; "sorulacaklar"
/// listesi kullanici onayina/duzeltmesine yonlendirir.
class InputEvidenceReport {
  const InputEvidenceReport({
    required this.status,
    required this.errorCount,
    required this.warnCount,
    required this.reviewCount,
    required this.questions,
  });

  final String status; // pass | review | fail
  final int errorCount;
  final int warnCount;
  final int reviewCount;
  final List<InputEvidenceQuestion> questions;

  factory InputEvidenceReport.fromJson(Map<String, dynamic> json) {
    final counts = (json['counts'] as Map<String, dynamic>?) ?? const {};
    final rawQuestions = json['missing_questions'] as List<dynamic>? ?? const [];
    return InputEvidenceReport(
      status: json['status'] as String? ?? 'unknown',
      errorCount: (counts['error'] as num?)?.toInt() ?? 0,
      warnCount: (counts['warn'] as num?)?.toInt() ?? 0,
      reviewCount: (counts['review'] as num?)?.toInt() ?? 0,
      questions: rawQuestions
          .whereType<Map<String, dynamic>>()
          .map(InputEvidenceQuestion.fromJson)
          .toList(growable: false),
    );
  }
}

class InputEvidenceQuestion {
  const InputEvidenceQuestion({
    required this.id,
    required this.category,
    required this.severity,
    required this.ask,
  });

  final String id;
  final String category;
  final String severity;
  final String ask;

  factory InputEvidenceQuestion.fromJson(Map<String, dynamic> json) {
    return InputEvidenceQuestion(
      id: json['id'] as String? ?? '',
      category: json['category'] as String? ?? '',
      severity: json['severity'] as String? ?? 'info',
      ask: json['ask'] as String? ?? '',
    );
  }
}
