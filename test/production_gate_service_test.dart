import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:omnicircuit_ai/services/production_gate_service.dart';

void main() {
  group('ProductionGateSnapshot', () {
    test('allows manufacturing only when every hard gate passes', () {
      final snapshot = ProductionGateSnapshot.fromJson({
        'generated_at': '2026-06-02T13:54:01+00:00',
        'status': 'production_candidate',
        'manufacturing_ready': true,
        'total_findings': 0,
        'violation_count': 0,
        'unconnected_count': 0,
        'error_count': 0,
        'warning_count': 0,
        'source_evidence_pass': true,
        'production_model_pass': true,
        'evidence_summary': 'Design source evidence gate passed.',
        'pcb_sha256': 'pcb-hash',
        'drc_report_sha256': 'drc-hash',
      });

      expect(snapshot.allowsManufacturing, isTrue);
      expect(snapshot.blockers, isEmpty);
    });

    test('blocks stale package claims when manifest is blocked', () {
      final snapshot = ProductionGateSnapshot.fromJson({
        'status': 'blocked',
        'manufacturing_ready': false,
        'violation_count': 17,
        'unconnected_count': 2,
        'error_count': 7,
        'source_evidence_pass': false,
        'production_model_pass': true,
        'pcb_sha256': 'pcb-hash',
        'drc_report_sha256': 'drc-hash',
      });

      expect(snapshot.allowsManufacturing, isFalse);
      expect(snapshot.blockers.join(' '), contains('Manifest status=blocked'));
      expect(snapshot.blockers.join(' '), contains('DRC: 17 violation'));
      expect(
        snapshot.blockers.join(' '),
        contains('Source evidence gate failed'),
      );
    });
  });

  group('ProductionGateService', () {
    late Directory tempDir;

    setUp(() async {
      tempDir = await Directory.systemTemp.createTemp('production_gate_');
    });

    tearDown(() async {
      if (await tempDir.exists()) {
        await tempDir.delete(recursive: true);
      }
    });

    test('loads the live board verification manifest from disk', () async {
      final generatedDir = Directory('${tempDir.path}/assets/generated');
      await generatedDir.create(recursive: true);
      await File(
        '${generatedDir.path}/board_verification_manifest.json',
      ).writeAsString(
        jsonEncode({
          'status': 'blocked',
          'manufacturing_ready': false,
          'violation_count': 1,
          'source_evidence_pass': true,
          'production_model_pass': true,
        }),
      );

      final service = ProductionGateService(projectRoot: tempDir.path);
      final snapshot = await service.loadSnapshot();

      expect(snapshot, isNotNull);
      expect(snapshot!.status, 'blocked');
      expect(snapshot.allowsManufacturing, isFalse);
    });
  });
}
