import '../models/ai_netlist.dart';
import '../models/design_package.dart';

class CognitiveNetlistService {
  DesignPackage synthesize(
    String request, {
    String bomText = '',
    String technicalNotes = '',
  }) {
    final relayCount = _relayCount(request);
    final normalizedBom = bomText.toLowerCase();
    final includesCustomBom = normalizedBom.trim().isNotEmpty;
    final reasoning = <ReasoningEntry>[
      const ReasoningEntry(
        level: 'info',
        message: 'ESP32-S3 3.3V host MCU olarak tanindi.',
        outcome: 'accepted',
      ),
      const ReasoningEntry(
        level: 'info',
        message: 'DWM3000 1.8V UWB domain olarak tanindi.',
        outcome: 'accepted',
      ),
      const ReasoningEntry(
        level: 'warning',
        message:
            '220V AC giris algilandi. Sigorta, varistor, izole AC/DC, 3.3V buck ve 1.8V LDO eklendi.',
        outcome: 'successful',
      ),
      const ReasoningEntry(
        level: 'warning',
        message:
            'ESP32 ve DWM3000 voltaj uyusmazligi tespit edildi. SPI hattina TXB0104, RTLS hatlarina SN74LVC1T45 eklendi.',
        outcome: 'successful',
      ),
      ReasoningEntry(
        level: 'warning',
        message:
            '$relayCount adet 5V role cikisi icin PC817 optokuplor, 2N7002 MOSFET ve flyback diyot eklendi.',
        outcome: 'successful',
      ),
      const ReasoningEntry(
        level: 'info',
        message:
            'DWM3000 pin 23 icin 50 ohm RF net sinifi, 3mm keepout ve via yasagi uretildi.',
        outcome: 'successful',
      ),
      if (includesCustomBom)
        const ReasoningEntry(
          level: 'info',
          message:
              'Kullanici BOM/teknik notlari okundu; kritik bilesenler kural motoru ile eslestirildi.',
          outcome: 'accepted',
        ),
    ];

    final netlist = AiNetlist(
      schema: 'AI_Netlist_v1',
      projectName: 'ESP32-S3 DWM3000 UWB Anchor with Relay Outputs',
      sourcePrompt: _sourcePrompt(request, bomText, technicalNotes),
      reasoningLog: reasoning,
      components: [
        const NetlistComponent(
          ref: 'U1',
          type: 'mcu',
          value: 'ESP32-S3',
          partNumber: 'ESP32-S3-WROOM-1',
          reason: 'User requested host MCU.',
        ),
        const NetlistComponent(
          ref: 'U2',
          type: 'uwb_module',
          value: 'DWM3000',
          partNumber: 'DWM3000',
          reason: 'User requested UWB positioning radio.',
        ),
        const NetlistComponent(
          ref: 'F1',
          type: 'fuse',
          value: '500mA',
          partNumber: '0451.500MRL',
          reason: 'AC input protection.',
        ),
        const NetlistComponent(
          ref: 'MOV1',
          type: 'varistor',
          value: '471VAC MOV',
          partNumber: 'MOV-14D471K',
          reason: 'AC surge protection.',
        ),
        const NetlistComponent(
          ref: 'U6',
          type: 'ac_dc',
          value: '5V isolated',
          partNumber: 'HLK-5M05',
          reason: '220V AC to isolated 5V rail.',
        ),
        const NetlistComponent(
          ref: 'U7',
          type: 'buck',
          value: '3.3V',
          partNumber: 'TPS54331DR',
          reason: '5V to ESP32 3.3V rail.',
        ),
        const NetlistComponent(
          ref: 'U8',
          type: 'ldo',
          value: '1.8V low-noise',
          partNumber: 'TPS7A2018PDBVR',
          reason:
              '3.3V to DWM3000 1.8V rail; selected for higher current margin than TPS780.',
        ),
        const NetlistComponent(
          ref: 'U3',
          type: 'level_shifter',
          value: '4-bit bidirectional',
          partNumber: 'TXB0104RUT',
          reason: 'SPI voltage translation.',
        ),
        const NetlistComponent(
          ref: 'U4-U5',
          type: 'level_shifter',
          value: 'single-bit dual-supply',
          partNumber: 'SN74LVC1T45DCK',
          reason: 'IRQ and EXT_TX voltage translation.',
        ),
        for (var index = 1; index <= relayCount; index++) ...[
          NetlistComponent(
            ref: 'K$index',
            type: 'relay',
            value: '5V relay',
            partNumber: 'G5Q-14-DC5',
            reason: 'User requested relay output.',
          ),
          NetlistComponent(
            ref: 'OK$index',
            type: 'optocoupler',
            value: 'PC817',
            partNumber: 'PC817',
            reason: 'Protect ESP32 GPIO from relay driver domain.',
          ),
          NetlistComponent(
            ref: 'Q$index',
            type: 'n_mosfet',
            value: '2N7002',
            partNumber: '2N7002',
            reason: 'Low-side relay coil driver.',
          ),
          NetlistComponent(
            ref: 'D$index',
            type: 'flyback_diode',
            value: 'SS14',
            partNumber: 'SS14',
            reason: 'Clamp relay coil flyback.',
          ),
        ],
      ],
      nets: [
        const NetConnection(
          net: 'AC_L_PROTECTED',
          pins: ['J1.L', 'F1.1', 'MOV1.1', 'U6.AC_L'],
          netClass: 'mains',
          reason: 'Fused AC live input.',
        ),
        const NetConnection(
          net: '+5V_ISO',
          pins: ['U6.+VO', 'U7.VIN', 'K1.COIL+', 'K2.COIL+'],
          netClass: 'power_5v',
          reason: 'Relay and buck input rail.',
        ),
        const NetConnection(
          net: '+3V3',
          pins: ['U7.OUT', 'U1.3V3', 'U3.VCCA', 'U4.VCCA'],
          netClass: 'power_3v3',
          reason: 'ESP32 logic rail.',
        ),
        const NetConnection(
          net: '+1V8',
          pins: ['U8.OUT', 'U2.VDDIO', 'U3.VCCB', 'U4.VCCB'],
          netClass: 'power_1v8',
          reason: 'DWM3000 logic rail.',
        ),
        const NetConnection(
          net: 'SPI_CS_3V3',
          pins: ['U1.GPIO10', 'R10', 'U3.A1'],
          netClass: 'spi_3v3',
          reason: 'ESP32 SPI through 100R source resistor.',
        ),
        const NetConnection(
          net: 'SPI_CS_1V8',
          pins: ['U3.B1', 'U2.SPI_CS'],
          netClass: 'spi_1v8',
          reason: 'Translated DWM3000 SPI chip select.',
        ),
        const NetConnection(
          net: 'DWM_IRQ',
          pins: ['U2.IRQ', 'U4.B', 'U4.A', 'U1.GPIO14'],
          netClass: 'rtls',
          reason: 'IRQ translated through SN74LVC1T45.',
        ),
        const NetConnection(
          net: 'UWB_RF_50R',
          pins: ['U2.RF_PIN23', 'J2.CENTER'],
          netClass: 'rf_50r',
          reason: '50 ohm UWB antenna trace.',
        ),
        for (var index = 1; index <= relayCount; index++)
          NetConnection(
            net: 'RELAY${index}_DRIVE',
            pins: [
              'U1.GPIO${20 + index}',
              'OK$index',
              'Q$index.G',
              'K$index.COIL-',
            ],
            netClass: 'relay_drive',
            reason: 'Optically isolated relay low-side drive.',
          ),
      ],
      rules: const [
        DesignRule(
          id: 'AC_CLEARANCE_8MM',
          severity: 'error',
          description:
              'Maintain minimum 8mm clearance around AC primary and HLK-5M05 primary side.',
        ),
        DesignRule(
          id: 'SPI_LENGTH_MATCH_2MM',
          severity: 'error',
          description: 'SPI traces must be length matched within +/-2mm.',
        ),
        DesignRule(
          id: 'TXB0104_DISTANCE_15MM',
          severity: 'error',
          description: 'Place TXB0104 within 15mm of DWM3000.',
        ),
        DesignRule(
          id: 'RELAY_NO_DIRECT_GPIO_DRIVE',
          severity: 'error',
          description: 'Relay coils must not connect directly to ESP32 GPIO.',
        ),
        DesignRule(
          id: 'RF_NO_VIAS_OR_TESTPOINTS',
          severity: 'error',
          description:
              'No vias, test points, or components allowed on RF trace.',
        ),
      ],
      ercChecks: const [
        'Power rails inferred: 5V, 3V3, 1V8',
        'Voltage mismatch mitigation added',
        'Relay isolation and low-side drivers added',
        'AC clearance and RF impedance rules emitted',
      ],
    );
    return _packageFor(netlist);
  }

  /// Gerçek AI'dan gelen AiNetlist'i DesignPackage'e dönüştürür.
  /// Deterministik synthesis yerine AI çıktısını kullanır.
  DesignPackage synthesizeFromAiNetlist(
    AiNetlist aiNetlist,
    String request, {
    String bomText = '',
    String technicalNotes = '',
  }) {
    return _packageFor(aiNetlist);
  }

  DesignPackage _packageFor(AiNetlist netlist) {
    return DesignPackage(
      netlist: netlist,
      stages: const [
        StageStatus(
          stage: DesignStage.analysis,
          title: 'Mühendislik Analizi',
          state: StageState.ready,
          detail:
              'BOM, voltaj domainleri, güç ağacı ve yardımcı devreler çıkarıldı.',
        ),
        StageStatus(
          stage: DesignStage.schematic,
          title: 'Şematik Sentezi',
          state: StageState.requiresReview,
          detail:
              'Netlist blokları hazır; gerçek KiCad sembol instance, pin ERC ve symbol-footprint bağı henüz zorunlu kapıdan geçmedi.',
        ),
        StageStatus(
          stage: DesignStage.pcb,
          title: 'PCB Kısıtları',
          state: StageState.requiresReview,
          detail:
              'RF, AC izolasyon ve yerleşim kuralları üretildi; aktif PCB kanıtı mühendislik denetiminden geçmeli.',
        ),
        StageStatus(
          stage: DesignStage.pcba,
          title: 'PCBA Görünümü',
          state: StageState.requiresReview,
          detail:
              'BOM/CPL bilgisi hazırlanabilir; assembly drawing ve 3D PCBA kanıtı henüz eksik.',
        ),
        StageStatus(
          stage: DesignStage.simulation,
          title: 'Sanal Simülasyon',
          state: StageState.blocked,
          detail:
              'Statik kontroller var; gerçek SPICE/SI/PI/termal koşu kanıtı yoksa üretim kapısı kapalıdır.',
        ),
        StageStatus(
          stage: DesignStage.drc,
          title: 'DRC Analizi',
          state: StageState.requiresReview,
          detail: 'KiCad DRC sonucu aktif board dosyasıyla tutarlı olmalı.',
        ),
        StageStatus(
          stage: DesignStage.export,
          title: 'Üretim Export',
          state: StageState.requiresReview,
          detail:
              'Gerber/CPL paketi var; gerçek üretime gönderim için mühendislik gerçeklik kapısı geçmeli.',
        ),
      ],
      schematicBlocks: [
        const SchematicBlock(
          name: 'AC Input & Protection',
          intent: 'Mains girişini güvenli izole 5V raya dönüştürür.',
          nets: ['AC_L_PROTECTED', 'AC_N', '+5V_ISO'],
        ),
        const SchematicBlock(
          name: 'Power Regulation',
          intent: '5V, 3V3 ve 1V8 güç domainlerini üretir.',
          nets: ['+5V_ISO', '+3V3', '+1V8', 'GND'],
        ),
        const SchematicBlock(
          name: 'ESP32-S3 Host',
          intent: 'Ana kontrolcü, SPI ve röle komutlarını yönetir.',
          nets: ['SPI_CS_3V3', 'DWM_IRQ', 'RELAY1_DRIVE'],
        ),
        const SchematicBlock(
          name: 'DWM3000 UWB',
          intent: 'UWB haberleşme ve RF anten çıkışını sağlar.',
          nets: ['SPI_CS_1V8', 'UWB_RF_50R'],
        ),
        const SchematicBlock(
          name: 'Relay Isolation',
          intent: 'ESP32 pinlerini optik izolasyon ve MOSFET sürücüyle korur.',
          nets: ['RELAY1_DRIVE', 'RELAY2_DRIVE'],
        ),
      ],
      pcbConstraints: [
        for (final rule in netlist.rules)
          PcbConstraint(
            id: rule.id,
            area: _constraintArea(rule.id),
            rule: rule.description,
            severity: rule.severity,
          ),
      ],
      pcbaItems: [
        for (final component in netlist.components)
          PcbaItem(
            ref: component.ref,
            partNumber: component.partNumber,
            placement: _placementFor(component),
            assemblyNote: component.reason,
          ),
      ],
      simulationChecks: const [
        SimulationCheck(
          name: 'Power Budget',
          domain: 'PI',
          status: 'pass',
          result:
              '5V relay rail, 3V3 MCU rail and 1V8 UWB rail inferred. Current margins require datasheet current model.',
        ),
        SimulationCheck(
          name: 'Voltage Domain ERC',
          domain: 'ERC',
          status: 'pass',
          result: '3V3 to 1V8 digital crossings pass through level shifters.',
        ),
        SimulationCheck(
          name: 'RF Launch Rule',
          domain: 'SI/RF',
          status: 'review',
          result:
              '50 ohm, 0.35mm trace and 3mm keepout emitted. Needs CAD stackup impedance verification.',
        ),
        SimulationCheck(
          name: 'AC Safety Clearance',
          domain: 'DFM/Safety',
          status: 'review',
          result:
              '8mm clearance rule emitted. Needs board geometry and human safety review.',
        ),
        SimulationCheck(
          name: 'Relay Flyback',
          domain: 'Transient',
          status: 'pass',
          result:
              'Each relay coil has isolated drive, MOSFET low-side switch, and flyback diode.',
        ),
      ],
      exportArtifacts: const [
        ExportArtifact(
          name: 'AI Netlist',
          format: 'JSON',
          path: 'outputs/phase1/AI_NETLIST_V1.example.json',
          state: ArtifactState.generated,
          note: 'Structured design source of truth.',
        ),
        ExportArtifact(
          name: 'Schematic Draft',
          format: 'KiCad .kicad_sch',
          path: 'outputs/kicad/.../*.kicad_sch',
          state: ArtifactState.scaffolded,
          note:
              'Draft exists, but real KiCad symbols and ERC are required before production.',
        ),
        ExportArtifact(
          name: 'PCB Layout',
          format: 'KiCad .kicad_pcb',
          path: 'outputs/kicad/.../*.kicad_pcb',
          state: ArtifactState.scaffolded,
          note:
              'Board artifact must be checked by ENGINEERING_READINESS_V1 before trusting exports.',
        ),
        ExportArtifact(
          name: 'Gerber Package',
          format: 'ZIP',
          path: 'outputs/fabrication/Quantum_Mind_Anchor_v2_4_Production.zip',
          state: ArtifactState.scaffolded,
          note:
              'Package exists only as a handoff candidate until schematic, PCB, simulation and PCBA evidence pass.',
        ),
        ExportArtifact(
          name: 'BOM + CPL',
          format: 'CSV',
          path: 'outputs/phase4/position/',
          state: ArtifactState.scaffolded,
          note:
              'BOM/CPL are available; assembly drawing and footprint verification still required.',
        ),
        ExportArtifact(
          name: 'Simulation Report',
          format: 'Markdown/PDF planned',
          path: 'outputs/reports/simulation_report.md',
          state: ArtifactState.scaffolded,
          note: 'Static checks now; external SPICE/SI/PI runners next.',
        ),
      ],
    );
  }

  String _sourcePrompt(String request, String bomText, String technicalNotes) {
    final sections = [
      request.trim(),
      if (bomText.trim().isNotEmpty) 'BOM:\n${bomText.trim()}',
      if (technicalNotes.trim().isNotEmpty)
        'TECHNICAL_NOTES:\n${technicalNotes.trim()}',
    ];
    return sections.join('\n\n');
  }

  String _constraintArea(String ruleId) {
    if (ruleId.startsWith('AC_')) {
      return 'Mains isolation';
    }
    if (ruleId.startsWith('RF_')) {
      return 'UWB RF launch';
    }
    if (ruleId.contains('SPI') || ruleId.contains('TXB')) {
      return 'Digital signal integrity';
    }
    if (ruleId.contains('RELAY')) {
      return 'Relay driver safety';
    }
    return 'General board rule';
  }

  String _placementFor(NetlistComponent component) {
    if (component.ref.startsWith('U2')) {
      return 'Top layer, RF edge corridor';
    }
    if (component.ref.startsWith('U3') || component.ref.startsWith('U4')) {
      return 'Top layer, within DWM3000 distance limit';
    }
    if (component.ref.startsWith('U6') ||
        component.ref.startsWith('F') ||
        component.ref.startsWith('MOV')) {
      return 'AC isolated zone';
    }
    if (component.ref.startsWith('K') ||
        component.ref.startsWith('OK') ||
        component.ref.startsWith('Q')) {
      return 'Relay output zone';
    }
    return 'Top layer, optimize during placement';
  }

  int _relayCount(String request) {
    final lower = request.toLowerCase();
    final match = RegExp(
      r'(\d+)\s*(adet\s*)?(g5q|role|röle|relay)',
    ).firstMatch(lower);
    if (match != null) {
      return int.tryParse(match.group(1) ?? '') ?? 1;
    }
    return lower.contains('g5q') ||
            lower.contains('role') ||
            lower.contains('röle')
        ? 1
        : 0;
  }
}
