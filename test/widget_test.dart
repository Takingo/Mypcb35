import 'package:flutter_test/flutter_test.dart';

import 'package:omnicircuit_ai/main.dart';

void main() {
  testWidgets('OmniCircuit dashboard generates phase 1 netlist', (
    tester,
  ) async {
    await tester.pumpWidget(const OmniCircuitApp());
    await tester.pumpAndSettle();

    expect(find.text('OmniCircuit AI'), findsWidgets);
    expect(find.text('Girdi Paneli'), findsOneWidget);
    expect(find.text('Ister Dosyasi'), findsOneWidget);
    expect(find.text('BOM Yukle'), findsOneWidget);
    expect(find.text('Teknik Not'), findsOneWidget);

    await tester.ensureVisible(find.text('BOM Yukle'));
    await tester.tap(find.text('BOM Yukle'));
    await tester.pumpAndSettle();
    expect(find.text('BOM dosyasi import et'), findsOneWidget);
    expect(find.text('Yoldan Yukle'), findsOneWidget);
    await tester.tap(find.text('Vazgec'));
    await tester.pumpAndSettle();

    await tester.ensureVisible(find.text('Tasarim Paketi Uret'));
    await tester.tap(find.text('Tasarim Paketi Uret'));
    for (var index = 0; index < 12; index++) {
      await tester.pump(const Duration(milliseconds: 150));
    }

    expect(find.text('AI_Netlist_v1'), findsOneWidget);
    expect(find.textContaining('TXB0104'), findsWidgets);
  });
}
