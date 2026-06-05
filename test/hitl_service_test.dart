import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:omnicircuit_ai/services/hitl_service.dart';

void main() {
  group('HitlState', () {
    test('parses a valid HITL_STATE_V1 blocker', () {
      final state = HitlState.fromJson({
        'schema': 'HITL_STATE_V1',
        'status': 'awaiting_human_input',
        'blocker_type': 'placement',
        'session_id': 'abc-123',
        'raised_at': '2026-05-30T07:31:44+00:00',
        'context': {
          'refs': ['U1', 'R10'],
        },
        'question': 'Where should the sockets go?',
        'suggested_choices': [
          {
            'id': 'A',
            'label': 'Place at top-left',
            'consequence': 'Longer SPI routes',
          },
        ],
        'answer_path': 'assets/generated/hitl_answer.json',
      });

      expect(state.sessionId, 'abc-123');
      expect(state.blockerType, 'placement');
      expect(state.question, 'Where should the sockets go?');
      expect(state.choices.single.id, 'A');
      expect(state.choices.single.label, 'Place at top-left');
      expect(state.choices.single.consequence, 'Longer SPI routes');
    });

    test('rejects non-awaiting or wrong-schema files', () {
      expect(
        () => HitlState.fromJson({
          'schema': 'OTHER',
          'status': 'awaiting_human_input',
          'session_id': 'abc-123',
          'blocker_type': 'routing',
          'question': 'Route?',
        }),
        throwsA(isA<FormatException>()),
      );

      expect(
        () => HitlState.fromJson({
          'schema': 'HITL_STATE_V1',
          'status': 'resolved',
          'session_id': 'abc-123',
          'blocker_type': 'routing',
          'question': 'Route?',
        }),
        throwsA(isA<FormatException>()),
      );
    });
  });

  group('HitlService', () {
    late Directory tempDir;

    setUp(() async {
      tempDir = await Directory.systemTemp.createTemp('hitl_service_test_');
    });

    tearDown(() async {
      if (await tempDir.exists()) {
        await tempDir.delete(recursive: true);
      }
    });

    test('pollOnce loads active state from disk', () async {
      final generatedDir = Directory('${tempDir.path}/assets/generated');
      await generatedDir.create(recursive: true);
      await File('${generatedDir.path}/hitl_state.json').writeAsString(
        jsonEncode({
          'schema': 'HITL_STATE_V1',
          'status': 'awaiting_human_input',
          'blocker_type': 'bom',
          'session_id': 'sid-1',
          'raised_at': '2026-05-30T07:31:44+00:00',
          'context': const {},
          'question': 'MOV1 or RV1?',
          'suggested_choices': const [],
          'answer_path': 'assets/generated/hitl_answer.json',
        }),
      );

      final service = HitlService(projectRoot: tempDir.path);
      await service.pollOnce();

      expect(service.activeState?.sessionId, 'sid-1');
      expect(service.activeState?.blockerType, 'bom');
      expect(service.lastError, isNull);
    });

    test('writeDecision serializes the required HITL answer schema', () async {
      final service = HitlService(projectRoot: tempDir.path);
      final state = HitlState.fromJson({
        'schema': 'HITL_STATE_V1',
        'status': 'awaiting_human_input',
        'blocker_type': 'routing',
        'session_id': 'sid-2',
        'raised_at': '2026-05-30T07:31:44+00:00',
        'context': const {},
        'question': 'Layer?',
        'suggested_choices': const [],
        'answer_path': 'assets/generated/hitl_answer.json',
      });

      await service.writeDecision(
        state: state,
        decision: 'A',
        rationale: 'Use top layer to preserve return path.',
      );

      final answerFile = File(
        '${tempDir.path}/assets/generated/hitl_answer.json',
      );
      final answer =
          jsonDecode(await answerFile.readAsString()) as Map<String, dynamic>;

      expect(answer['session_id'], 'sid-2');
      expect(answer['decision'], 'A');
      expect(answer['rationale'], 'Use top layer to preserve return path.');
      expect(DateTime.parse(answer['decided_at'] as String).isUtc, isTrue);
    });
  });
}
