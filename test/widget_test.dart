import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:omnicircuit_ai/controllers/netlist_controller.dart';
import 'package:omnicircuit_ai/main.dart';
import 'package:omnicircuit_ai/manufacturing_dashboard.dart';

void main() {
  Future<void> pumpUi(WidgetTester tester) async {
    await tester.pump(const Duration(milliseconds: 500));
  }

  testWidgets('OmniCircuit dashboard renders PCBA direct export tab', (
    tester,
  ) async {
    await tester.pumpWidget(const OmniCircuitApp());
    await pumpUi(tester);

    expect(find.text('OmniCircuit AI'), findsWidgets);
    expect(find.text('Girdi Paneli'), findsOneWidget);
    expect(find.text('Ister Dosyasi'), findsOneWidget);
    expect(find.text('BOM Yukle'), findsOneWidget);
    expect(find.text('Teknik Not'), findsOneWidget);

    await tester.ensureVisible(find.text('BOM Yukle'));
    await tester.tap(find.text('BOM Yukle'));
    await pumpUi(tester);
    expect(find.text('BOM dosyasi import et'), findsOneWidget);
    expect(find.text('Yoldan Yukle'), findsOneWidget);
    await tester.tap(find.text('Vazgec'));
    await pumpUi(tester);

    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => NetlistController(),
        child: const MaterialApp(
          home: ManufacturingDashboard(initialTabIndex: 1),
        ),
      ),
    );
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('Uretim ve Siparis Hazirligi'), findsOneWidget);
    expect(find.text('PCBA Direkt Export'), findsOneWidget);

    expect(
      find.text(
        'PCBA Uretim Paketi (Direkt Online Uretim)',
        skipOffstage: false,
      ),
      findsOneWidget,
    );
    expect(
      find.text('PCBA Uretim Paketini Olustur', skipOffstage: false),
      findsOneWidget,
    );
  });
}
