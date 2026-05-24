import 'package:flutter_test/flutter_test.dart';
import 'package:omnicircuit_ai/models/design_package.dart';

void main() {
  test('DrcReport parses category summary and violation coordinates', () {
    final report = DrcReport.fromJson({
      'schema': 'DRC_REPORT_V1',
      'source': 'board.kicad_pcb',
      'total_violations': 1,
      'summary_by_category': {'clearance': 1},
      'violations': [
        {
          'id': 'DRC-0001',
          'category': 'clearance',
          'severity': 'error',
          'description': 'Clearance violation',
          'repair_hint': 'Move items apart',
          'locations': [
            {
              'x': 12.5,
              'y': 8.25,
              'layer': 'F.Cu',
              'item': 'Pad 1 of U2',
              'component': 'U2',
            }
          ],
        }
      ],
    });

    expect(report.totalViolations, 1);
    expect(report.summaryByCategory['clearance'], 1);
    expect(report.violations.single.coordinateLabel, 'x=12.50mm, y=8.25mm');
  });
}
