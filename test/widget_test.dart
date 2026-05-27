import 'package:flutter_test/flutter_test.dart';

import 'package:omnicircuit_ai/main.dart';

void main() {
  testWidgets('OmniCircuit dashboard opens PCBA direct export tab', (
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

    await tester.tap(find.byTooltip('Uretim ve siparis hazirligi'));
    await tester.pumpAndSettle();

    expect(find.text('Uretim ve Siparis Hazirligi'), findsOneWidget);
    expect(find.text('PCBA Direkt Export'), findsOneWidget);

    await tester.tap(find.text('PCBA Direkt Export'));
    await tester.pumpAndSettle();

    expect(
      find.text('PCBA Uretim Paketi (Direkt Online Uretim)'),
      findsOneWidget,
    );
    expect(find.text('PCBA Uretim Paketini Olustur'), findsOneWidget);
  });
}
