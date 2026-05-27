class AiNetlist {
  const AiNetlist({
    required this.schema,
    required this.projectName,
    required this.sourcePrompt,
    required this.components,
    required this.nets,
    required this.rules,
    required this.reasoningLog,
    required this.ercChecks,
    this.aiProvider = '',
    this.aiModel = '',
    this.elapsedSeconds = 0,
  });

  /// Python engine'in ürettiği JSON'dan AiNetlist oluştur.
  /// Python netlist şeması (snake_case) ile Dart modelini eşleştirir.
  factory AiNetlist.fromPythonJson(
    Map<String, dynamic> json, {
    String provider = '',
    String model = '',
    double elapsedSeconds = 0,
  }) {
    final components = (json['components'] as List? ?? [])
        .cast<Map<String, dynamic>>()
        .map(
          (c) => NetlistComponent(
            ref: c['ref'] as String? ?? '',
            type: c['type'] as String? ?? '',
            value: c['value'] as String? ?? '',
            partNumber: c['part_number'] as String? ?? '',
            reason: c['reason'] as String? ?? '',
          ),
        )
        .toList();

    final nets = (json['nets'] as List? ?? [])
        .cast<Map<String, dynamic>>()
        .map(
          (n) => NetConnection(
            net: n['net'] as String? ?? '',
            pins: (n['pins'] as List? ?? []).cast<String>(),
            netClass: n['net_class'] as String? ?? '',
            reason: n['reason'] as String? ?? '',
          ),
        )
        .toList();

    final rules = (json['rules'] as List? ?? [])
        .cast<Map<String, dynamic>>()
        .map(
          (r) => DesignRule(
            id: r['id'] as String? ?? '',
            severity: r['severity'] as String? ?? 'info',
            description: r['description'] as String? ?? '',
          ),
        )
        .toList();

    final reasoning = (json['reasoning_log'] as List? ?? [])
        .cast<Map<String, dynamic>>()
        .map(
          (r) => ReasoningEntry(
            level: r['level'] as String? ?? 'info',
            message: r['message'] as String? ?? '',
            outcome: r['outcome'] as String? ?? '',
          ),
        )
        .toList();

    final ercSummary = json['erc_summary'] as Map<String, dynamic>? ?? {};
    final ercChecks = (ercSummary['checks'] as List? ?? []).cast<String>();

    return AiNetlist(
      schema: json['schema'] as String? ?? 'AI_Netlist_v1',
      projectName: json['project_name'] as String? ?? '',
      sourcePrompt: json['source_prompt'] as String? ?? '',
      components: components,
      nets: nets,
      rules: rules,
      reasoningLog: reasoning,
      ercChecks: ercChecks,
      aiProvider: provider,
      aiModel: model,
      elapsedSeconds: elapsedSeconds,
    );
  }

  final String schema;
  final String projectName;
  final String sourcePrompt;
  final List<NetlistComponent> components;
  final List<NetConnection> nets;
  final List<DesignRule> rules;
  final List<ReasoningEntry> reasoningLog;
  final List<String> ercChecks;

  /// Gerçek AI provider ve model bilgisi (Ollama, Gemini vb.)
  final String aiProvider;
  final String aiModel;
  final double elapsedSeconds;

  /// Tam AI_Netlist_v1 JSON — Python kicad_automation_service bu formatı doğrudan okur.
  Map<String, dynamic> toJson() {
    return {
      'schema': schema,
      'project_name': projectName.isNotEmpty
          ? projectName
          : 'ESP32-S3 DWM3000 UWB Anchor with Relay Outputs',
      'generated_at': DateTime.now().toUtc().toIso8601String(),
      'source_prompt': sourcePrompt,
      'assumptions': const [
        'AC mains input is isolated before low-voltage logic.',
        'ESP32-S3 logic domain is 3.3V.',
        'DWM3000 logic and RF module domain is 1.8V.',
        'Relay coils are 5V and must not be driven directly from MCU pins.',
      ],
      'components': components.map((c) => c.toJson()).toList(),
      'nets': nets.map((n) => n.toJson()).toList(),
      'rules': rules.map((r) => r.toJson()).toList(),
      'reasoning_log': reasoningLog.map((e) => e.toJson()).toList(),
      'erc_summary': {
        'status': 'pass_with_engineering_review_required',
        'checks': ercChecks,
      },
    };
  }
}

class NetlistComponent {
  const NetlistComponent({
    required this.ref,
    required this.type,
    required this.value,
    required this.partNumber,
    required this.reason,
  });

  final String ref;
  final String type;
  final String value;
  final String partNumber;
  final String reason;

  Map<String, dynamic> toJson() {
    return {
      'ref': ref,
      'type': type,
      'value': value,
      'part_number': partNumber,
      'reason': reason,
    };
  }
}

class NetConnection {
  const NetConnection({
    required this.net,
    required this.pins,
    required this.netClass,
    required this.reason,
  });

  final String net;
  final List<String> pins;
  final String netClass;
  final String reason;

  Map<String, dynamic> toJson() {
    return {
      'net': net,
      'pins': pins,
      'net_class': netClass,
      'reason': reason,
    };
  }
}

class DesignRule {
  const DesignRule({
    required this.id,
    required this.severity,
    required this.description,
  });

  final String id;
  final String severity;
  final String description;

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'severity': severity,
      'description': description,
    };
  }
}

class ReasoningEntry {
  const ReasoningEntry({
    required this.level,
    required this.message,
    required this.outcome,
  });

  final String level;
  final String message;
  final String outcome;

  Map<String, dynamic> toJson() {
    return {
      'level': level,
      'message': message,
      'outcome': outcome,
    };
  }
}

/// AI-assisted correction proposal for a single netlist error.
class AiCorrectionProposal {
  const AiCorrectionProposal({
    required this.id,
    required this.sourceFindingId,
    required this.errorCategory,
    required this.errorSeverity,
    required this.humanReadable,
    required this.aiProposalText,
    required this.aiReasoning,
    required this.confidence,
    required this.isSafetyCritical,
    required this.aiUncertain,
    required this.autoApplicable,
    required this.status,
    this.safetyReason,
    this.kicadOperation,
  });

  final String id;
  final String sourceFindingId;
  final String errorCategory;
  final String errorSeverity;
  final String humanReadable;
  final String aiProposalText;
  final String aiReasoning;
  final double confidence;
  final bool isSafetyCritical;
  final bool aiUncertain;
  final bool autoApplicable;
  final String status; // pending | approved | rejected | applied | failed
  final String? safetyReason;
  final Map<String, dynamic>? kicadOperation;

  factory AiCorrectionProposal.fromJson(Map<String, dynamic> json) {
    return AiCorrectionProposal(
      id: json['id'] as String? ?? '',
      sourceFindingId: json['source_finding_id'] as String? ?? '',
      errorCategory: json['error_category'] as String? ?? '',
      errorSeverity: json['error_severity'] as String? ?? '',
      humanReadable: json['human_readable'] as String? ?? '',
      aiProposalText: json['ai_proposal_text'] as String? ?? '',
      aiReasoning: json['ai_reasoning'] as String? ?? '',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      isSafetyCritical: json['is_safety_critical'] as bool? ?? false,
      aiUncertain: json['ai_uncertain'] as bool? ?? false,
      autoApplicable: json['auto_applicable'] as bool? ?? false,
      status: json['status'] as String? ?? 'pending',
      safetyReason: json['safety_reason'] as String?,
      kicadOperation: json['kicad_operation'] as Map<String, dynamic>?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'source_finding_id': sourceFindingId,
      'error_category': errorCategory,
      'error_severity': errorSeverity,
      'human_readable': humanReadable,
      'ai_proposal_text': aiProposalText,
      'ai_reasoning': aiReasoning,
      'confidence': confidence,
      'is_safety_critical': isSafetyCritical,
      'ai_uncertain': aiUncertain,
      'auto_applicable': autoApplicable,
      'status': status,
      if (safetyReason != null) 'safety_reason': safetyReason,
      if (kicadOperation != null) 'kicad_operation': kicadOperation,
    };
  }
}

/// Collection of AI correction proposals for a netlist.
class AiCorrectionProposalsReport {
  const AiCorrectionProposalsReport({
    required this.generatedAt,
    required this.provider,
    required this.model,
    required this.proposals,
    required this.summary,
  });

  final String generatedAt;
  final String provider;
  final String model;
  final List<AiCorrectionProposal> proposals;
  final Map<String, int> summary; // {total, pending, auto_applicable, needs_user, safety_critical}

  bool get hasPending => proposals.any((p) => p.status == 'pending');
  List<AiCorrectionProposal> get autoApplicable =>
      proposals.where((p) => p.autoApplicable && p.status == 'pending').toList();

  int get totalCount => summary['total'] ?? 0;
  int get autoApplicableCount => summary['auto_applicable'] ?? 0;
  int get safetyCriticalCount => summary['safety_critical'] ?? 0;

  factory AiCorrectionProposalsReport.fromJson(Map<String, dynamic> json) {
    final proposals = (json['proposals'] as List? ?? [])
        .cast<Map<String, dynamic>>()
        .map(AiCorrectionProposal.fromJson)
        .toList();

    return AiCorrectionProposalsReport(
      generatedAt: json['generated_at'] as String? ?? '',
      provider: json['provider'] as String? ?? '',
      model: json['model'] as String? ?? '',
      proposals: proposals,
      summary: Map<String, int>.from(
        (json['summary'] as Map?)?.cast<String, int>() ?? {},
      ),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'generated_at': generatedAt,
      'provider': provider,
      'model': model,
      'proposals': proposals.map((p) => p.toJson()).toList(),
      'summary': summary,
    };
  }
}
