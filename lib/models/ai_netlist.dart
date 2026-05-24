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

  Map<String, dynamic> toJson() {
    return {
      'schema': schema,
      'project_name': projectName,
      'source_prompt': sourcePrompt,
      'components': components.map((component) => component.toJson()).toList(),
      'nets': nets.map((net) => net.toJson()).toList(),
      'rules': rules.map((rule) => rule.toJson()).toList(),
      'reasoning_log': reasoningLog.map((entry) => entry.toJson()).toList(),
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
