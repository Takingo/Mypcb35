import 'package:flutter_test/flutter_test.dart';
import 'package:omnicircuit_ai/services/cognitive_netlist_service.dart';

void main() {
  test('CognitiveNetlistService adds power, level shifting, and relay isolation', () {
    final service = CognitiveNetlistService();
    final designPackage = service.synthesize(
      'ESP32-S3, DWM3000 UWB, 220V AC ve 2 adet G5Q-14-DC5 5V role iceren cihaz',
    );
    final netlist = designPackage.netlist;

    expect(netlist.schema, 'AI_Netlist_v1');
    expect(netlist.components.any((component) => component.partNumber == 'HLK-5M05'), isTrue);
    expect(netlist.components.any((component) => component.partNumber == 'TXB0104RUT'), isTrue);
    expect(netlist.components.where((component) => component.partNumber == 'PC817'), hasLength(2));
    expect(netlist.rules.any((rule) => rule.id == 'AC_CLEARANCE_8MM'), isTrue);
    expect(netlist.nets.any((net) => net.net == 'UWB_RF_50R'), isTrue);
    expect(designPackage.exportArtifacts.any((artifact) => artifact.name == 'Gerber Package'), isTrue);
  });
}
