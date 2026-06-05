import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

class HitlService extends ChangeNotifier {
  HitlService({
    this.projectRoot = r'C:\Mypcb',
    this.stateRelativePath = r'assets\generated\hitl_state.json',
    this.defaultAnswerRelativePath = r'assets\generated\hitl_answer.json',
    this.pollInterval = const Duration(seconds: 1),
  });

  final String projectRoot;
  final String stateRelativePath;
  final String defaultAnswerRelativePath;
  final Duration pollInterval;

  Timer? _timer;
  HitlState? _activeState;
  String? _lastError;
  bool _isWriting = false;
  final Set<String> _answeredSessionIds = <String>{};

  HitlState? get activeState => _activeState;
  String? get lastError => _lastError;
  bool get isWriting => _isWriting;
  bool get isPolling => _timer?.isActive ?? false;

  void startPolling() {
    if (isPolling) {
      return;
    }
    unawaited(pollOnce());
    _timer = Timer.periodic(pollInterval, (_) => unawaited(pollOnce()));
  }

  Future<void> pollOnce() async {
    final stateFile = File(_resolvePath(stateRelativePath));
    try {
      if (!await stateFile.exists()) {
        _setState(null, null);
        return;
      }

      final raw = await stateFile.readAsString(encoding: utf8);
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('hitl_state.json must contain an object.');
      }
      final state = HitlState.fromJson(decoded);
      if (_answeredSessionIds.contains(state.sessionId)) {
        _setState(null, null);
        return;
      }
      _setState(state, null);
    } on FormatException catch (error) {
      _setState(_activeState, error.message);
    } catch (error) {
      _setState(_activeState, error.toString());
    }
  }

  Future<void> writeDecision({
    required HitlState state,
    required String decision,
    required String rationale,
  }) async {
    _isWriting = true;
    _lastError = null;
    notifyListeners();

    try {
      final answerPath = state.answerPath.trim().isEmpty
          ? defaultAnswerRelativePath
          : state.answerPath;
      final answerFile = File(_resolvePath(answerPath));
      await answerFile.parent.create(recursive: true);
      final answer = {
        'session_id': state.sessionId,
        'decision': decision,
        'rationale': rationale.trim().isEmpty
            ? 'UI decision: $decision'
            : rationale.trim(),
        'decided_at': DateTime.now().toUtc().toIso8601String(),
      };
      await answerFile.writeAsString(
        const JsonEncoder.withIndent('  ').convert(answer),
        encoding: utf8,
      );
      _answeredSessionIds.add(state.sessionId);
      _setState(null, null);
    } catch (error) {
      _lastError = error.toString();
    } finally {
      _isWriting = false;
      notifyListeners();
    }
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

  void _setState(HitlState? state, String? error) {
    final changed =
        _activeState?.sessionId != state?.sessionId ||
        _activeState?.raisedAt != state?.raisedAt ||
        _lastError != error;
    _activeState = state;
    _lastError = error;
    if (changed) {
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}

class HitlState {
  const HitlState({
    required this.schema,
    required this.status,
    required this.blockerType,
    required this.sessionId,
    required this.raisedAt,
    required this.context,
    required this.question,
    required this.choices,
    required this.answerPath,
  });

  final String schema;
  final String status;
  final String blockerType;
  final String sessionId;
  final String raisedAt;
  final Map<String, dynamic> context;
  final String question;
  final List<HitlChoice> choices;
  final String answerPath;

  factory HitlState.fromJson(Map<String, dynamic> json) {
    final schema = _requiredString(json, 'schema');
    final status = _requiredString(json, 'status');
    if (schema != 'HITL_STATE_V1') {
      throw FormatException('Unsupported HITL schema: $schema');
    }
    if (status != 'awaiting_human_input') {
      throw FormatException('Unsupported HITL status: $status');
    }

    return HitlState(
      schema: schema,
      status: status,
      blockerType: _requiredString(json, 'blocker_type'),
      sessionId: _requiredString(json, 'session_id'),
      raisedAt: _requiredString(json, 'raised_at'),
      context: _mapOrEmpty(json['context']),
      question: _requiredString(json, 'question'),
      choices: [
        for (final choice
            in json['suggested_choices'] as List<dynamic>? ?? const [])
          if (choice is Map<String, dynamic>) HitlChoice.fromJson(choice),
      ],
      answerPath:
          json['answer_path'] as String? ??
          r'assets\generated\hitl_answer.json',
    );
  }

  static String _requiredString(Map<String, dynamic> json, String key) {
    final value = json[key];
    if (value is String && value.trim().isNotEmpty) {
      return value;
    }
    throw FormatException('Missing required HITL field: $key');
  }

  static Map<String, dynamic> _mapOrEmpty(Object? value) {
    if (value == null) {
      return const {};
    }
    if (value is Map) {
      return Map<String, dynamic>.from(value);
    }
    throw const FormatException('HITL context must be an object.');
  }
}

class HitlChoice {
  const HitlChoice({
    required this.id,
    required this.label,
    required this.consequence,
  });

  final String id;
  final String label;
  final String consequence;

  factory HitlChoice.fromJson(Map<String, dynamic> json) {
    return HitlChoice(
      id: json['id'] as String? ?? '',
      label: json['label'] as String? ?? '',
      consequence: json['consequence'] as String? ?? '',
    );
  }
}
