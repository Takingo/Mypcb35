import 'package:flutter_test/flutter_test.dart';
import 'package:omnicircuit_ai/models/analysis_summary.dart';

void main() {
  test('AnalysisSummary counts pass and warning checks', () {
    final summary = AnalysisSummary.fromJson({
      'project_id': 'uwb_anchor',
      'project_name': 'Anchor',
      'generated_at': '2026-05-23T00:00:00+00:00',
      'overall_status': 'warning',
      'checks': [
        {
          'category': 'RF',
          'requirement': 'Controlled impedance',
          'status': 'pass',
          'evidence': 'Found',
          'recommendation': 'Route with constraints',
        },
        {
          'category': 'Safety',
          'requirement': 'Isolation',
          'status': 'warning',
          'evidence': 'Missing marker',
          'recommendation': 'Add keepout',
        },
      ],
      'artifacts': [
        {
          'name': 'Report',
          'path': 'outputs/report.md',
          'status': 'generated',
          'description': 'Validation report',
        }
      ],
    });

    expect(summary.passedChecks, 1);
    expect(summary.warningChecks, 1);
    expect(summary.categories, ['RF', 'Safety']);
    expect(summary.artifacts.single.name, 'Report');
  });
}
