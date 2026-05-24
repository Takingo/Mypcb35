class AnalysisSummary {
  const AnalysisSummary({
    required this.projectId,
    required this.projectName,
    required this.generatedAt,
    required this.overallStatus,
    required this.checks,
    required this.artifacts,
  });

  final String projectId;
  final String projectName;
  final String generatedAt;
  final String overallStatus;
  final List<ValidationCheck> checks;
  final List<DesignArtifact> artifacts;

  factory AnalysisSummary.fromJson(Map<String, dynamic> json) {
    final checksJson = json['checks'] as List<dynamic>? ?? const [];
    final artifactsJson = json['artifacts'] as List<dynamic>? ?? const [];
    return AnalysisSummary(
      projectId: json['project_id'] as String? ?? 'unknown',
      projectName: json['project_name'] as String? ?? 'Untitled project',
      generatedAt: json['generated_at'] as String? ?? '',
      overallStatus: json['overall_status'] as String? ?? 'unknown',
      checks: checksJson
          .whereType<Map<String, dynamic>>()
          .map(ValidationCheck.fromJson)
          .toList(growable: false),
      artifacts: artifactsJson
          .whereType<Map<String, dynamic>>()
          .map(DesignArtifact.fromJson)
          .toList(growable: false),
    );
  }

  int get passedChecks => checks.where((check) => check.status == 'pass').length;

  int get warningChecks => checks.where((check) => check.status != 'pass').length;

  List<String> get categories {
    final names = checks.map((check) => check.category).toSet().toList();
    names.sort();
    return names;
  }
}

class ValidationCheck {
  const ValidationCheck({
    required this.category,
    required this.requirement,
    required this.status,
    required this.evidence,
    required this.recommendation,
  });

  final String category;
  final String requirement;
  final String status;
  final String evidence;
  final String recommendation;

  factory ValidationCheck.fromJson(Map<String, dynamic> json) {
    return ValidationCheck(
      category: json['category'] as String? ?? 'General',
      requirement: json['requirement'] as String? ?? '',
      status: json['status'] as String? ?? 'unknown',
      evidence: json['evidence'] as String? ?? '',
      recommendation: json['recommendation'] as String? ?? '',
    );
  }
}

class DesignArtifact {
  const DesignArtifact({
    required this.name,
    required this.path,
    required this.status,
    required this.description,
  });

  final String name;
  final String path;
  final String status;
  final String description;

  factory DesignArtifact.fromJson(Map<String, dynamic> json) {
    return DesignArtifact(
      name: json['name'] as String? ?? '',
      path: json['path'] as String? ?? '',
      status: json['status'] as String? ?? '',
      description: json['description'] as String? ?? '',
    );
  }
}
