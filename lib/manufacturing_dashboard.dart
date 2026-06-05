import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'controllers/netlist_controller.dart';
import 'services/pcba_manufacturing_service.dart';
import 'services/production_gate_service.dart';

class ManufacturingDashboard extends StatefulWidget {
  const ManufacturingDashboard({super.key, this.initialTabIndex = 0});

  final int initialTabIndex;

  @override
  State<ManufacturingDashboard> createState() => _ManufacturingDashboardState();
}

class _ManufacturingDashboardState extends State<ManufacturingDashboard> {
  late final Future<_ManufacturingPackageState> _packageFuture = _loadPackage();
  int _quantity = 5;
  String _manufacturer = 'PCBWay';
  String _solderMaskColor = 'Green';

  Future<_ManufacturingPackageState> _loadPackage() async {
    final raw = await _readGeneratedJson('fabrication_package.json');
    final jsonMap = jsonDecode(raw) as Map<String, dynamic>;
    final package = FabricationPackage.fromJson(jsonMap);
    final gate = await const ProductionGateService().loadSnapshot();
    _quantity = package.checkout.quantity;
    _manufacturer = package.checkout.manufacturer;
    _solderMaskColor = package.checkout.solderMaskColor;
    return _ManufacturingPackageState(package: package, gate: gate);
  }

  Future<String> _readGeneratedJson(String name) async {
    final liveFile = File(r'C:\Mypcb\assets\generated\' + name);
    if (await liveFile.exists()) {
      return liveFile.readAsString(encoding: utf8);
    }
    return rootBundle.loadString('assets/generated/$name');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Uretim ve Siparis Hazirligi')),
      body: SafeArea(
        child: DefaultTabController(
          length: 2,
          initialIndex: widget.initialTabIndex,
          child: Column(
            children: [
              const TabBar(
                tabs: [
                  Tab(text: 'Temel Uretim Paketi'),
                  Tab(text: 'PCBA Direkt Export'),
                ],
              ),
              Expanded(
                child: TabBarView(
                  children: [_buildBasicPackageView(), _buildPcbaExportView()],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBasicPackageView() {
    return FutureBuilder<_ManufacturingPackageState>(
      future: _packageFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError || !snapshot.hasData) {
          return const Padding(
            padding: EdgeInsets.all(16),
            child: _Panel(
              title: 'Uretim paketi bulunamadi',
              icon: Icons.folder_off,
              child: Text(
                'Once tool/run_fabrication_package.ps1 calistirilip fabrication_package.json uretilmeli.',
              ),
            ),
          );
        }
        final state = snapshot.data!;
        final package = state.package;
        final gate = state.gate;
        return LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < 980;
            final content = compact
                ? Column(
                    children: [
                      if (gate != null) ...[
                        _ProductionGateBanner(gate: gate),
                        const SizedBox(height: 16),
                      ],
                      _PackagePreview(package: package, gate: gate),
                      const SizedBox(height: 16),
                      _CheckoutPanel(
                        package: package,
                        gate: gate,
                        quantity: _quantity,
                        manufacturer: _manufacturer,
                        solderMaskColor: _solderMaskColor,
                        onQuantityChanged: (value) =>
                            setState(() => _quantity = value),
                        onManufacturerChanged: (value) =>
                            setState(() => _manufacturer = value),
                        onSolderMaskChanged: (value) =>
                            setState(() => _solderMaskColor = value),
                      ),
                    ],
                  )
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        flex: 5,
                        child: Column(
                          children: [
                            if (gate != null) ...[
                              _ProductionGateBanner(gate: gate),
                              const SizedBox(height: 16),
                            ],
                            _PackagePreview(package: package, gate: gate),
                          ],
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        flex: 4,
                        child: _CheckoutPanel(
                          package: package,
                          gate: gate,
                          quantity: _quantity,
                          manufacturer: _manufacturer,
                          solderMaskColor: _solderMaskColor,
                          onQuantityChanged: (value) =>
                              setState(() => _quantity = value),
                          onManufacturerChanged: (value) =>
                              setState(() => _manufacturer = value),
                          onSolderMaskChanged: (value) =>
                              setState(() => _solderMaskColor = value),
                        ),
                      ),
                    ],
                  );
            return SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: content,
            );
          },
        );
      },
    );
  }

  Widget _buildPcbaExportView() {
    try {
      context.read<NetlistController>();
      return const _PcbaExportPanel();
    } on ProviderNotFoundException {
      return ChangeNotifierProvider(
        create: (_) => NetlistController(),
        child: const _PcbaExportPanel(),
      );
    }
  }
}

class _PcbaExportPanel extends StatelessWidget {
  const _PcbaExportPanel();

  @override
  Widget build(BuildContext context) {
    return Consumer<NetlistController>(
      builder: (context, controller, _) {
        return SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              _Panel(
                title: 'PCBA Uretim Paketi (Direkt Online Uretim)',
                icon: Icons.cloud_upload,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Text(
                      'Tum dosyalari iceren uretim paketini olustur ve online bir PCBA hizmeti saglayicisina direkt gondermek icin hazirla. '
                      'Surec sematik, PCB, DRC, simulator ve imalat kontrolleri dahil 0-100% uretim hazirligi kapsaminda calisir.',
                    ),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<String>(
                      initialValue: controller.selectedManufacturer,
                      decoration: const InputDecoration(
                        labelText: 'Hedef PCBA Uretim Firmasi',
                        border: OutlineInputBorder(),
                      ),
                      items: const [
                        DropdownMenuItem(
                          value: 'PCBWay',
                          child: Text('PCBWay (tavsiye edilen)'),
                        ),
                        DropdownMenuItem(
                          value: 'JLCPCB',
                          child: Text('JLCPCB'),
                        ),
                        DropdownMenuItem(
                          value: 'Seeed',
                          child: Text('Seeed Fusion'),
                        ),
                      ],
                      onChanged: (value) {
                        if (value != null) {
                          controller.selectManufacturer(value);
                        }
                      },
                    ),
                    const SizedBox(height: 16),
                    if (controller.lastManufacturingExport != null) ...[
                      _ManufacturingExportResult(
                        result: controller.lastManufacturingExport!,
                      ),
                      const SizedBox(height: 16),
                    ],
                    FilledButton.icon(
                      onPressed: controller.isExportingManufacturing
                          ? null
                          : controller.exportManufacturingPackage,
                      icon: controller.isExportingManufacturing
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.publish),
                      label: Text(
                        controller.isExportingManufacturing
                            ? 'Export Devam Ediyor...'
                            : 'PCBA Uretim Paketini Olustur',
                      ),
                    ),
                    const SizedBox(height: 16),
                    if (controller.manufacturingLog.isNotEmpty) ...[
                      const Divider(),
                      const SizedBox(height: 12),
                      Text(
                        'Export Günlüğü:',
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      const SizedBox(height: 8),
                      Container(
                        decoration: BoxDecoration(
                          color: Colors.grey.shade100,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        padding: const EdgeInsets.all(12),
                        constraints: const BoxConstraints(
                          maxHeight: 240,
                          minHeight: 100,
                        ),
                        child: SingleChildScrollView(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              for (final log in controller.manufacturingLog)
                                Padding(
                                  padding: const EdgeInsets.symmetric(
                                    vertical: 4,
                                  ),
                                  child: Text(
                                    log,
                                    style: const TextStyle(fontSize: 12),
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _PackagePreview extends StatelessWidget {
  const _PackagePreview({required this.package, required this.gate});

  final FabricationPackage package;
  final ProductionGateSnapshot? gate;

  @override
  Widget build(BuildContext context) {
    final fileGroups = <String, List<ProductionFile>>{};
    for (final file in package.files) {
      fileGroups.putIfAbsent(file.category, () => []).add(file);
    }
    return _Panel(
      title: 'Uretim Paketi',
      icon: Icons.inventory_2,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _GerberPreview(package: package),
          const SizedBox(height: 16),
          _StatusRow(
            icon: gate?.allowsManufacturing == true
                ? Icons.verified
                : Icons.lock,
            text: gate?.allowsManufacturing == true
                ? package.message
                : 'Uretim kilitli: canli manifest uretim kapisini gecmedi.',
          ),
          _StatusRow(icon: Icons.archive, text: package.productionZip),
          _StatusRow(
            icon: Icons.straighten,
            text:
                '${package.boardWidthMm} mm x ${package.boardHeightMm} mm | ${package.checkout.layers} katman',
          ),
          const Divider(height: 26),
          for (final entry in fileGroups.entries)
            _FileGroup(title: entry.key, files: entry.value),
        ],
      ),
    );
  }
}

class _GerberPreview extends StatelessWidget {
  const _GerberPreview({required this.package});

  final FabricationPackage package;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 240,
      width: double.infinity,
      decoration: BoxDecoration(
        color: const Color(0xFF1E3B36),
        borderRadius: BorderRadius.circular(8),
      ),
      child: CustomPaint(
        painter: _GerberPreviewPainter(),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Align(
            alignment: Alignment.topLeft,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Text(
                  'Gerber + Drill + CPL\n${_formatBytes(package.productionZipSizeBytes)}',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _CheckoutPanel extends StatelessWidget {
  const _CheckoutPanel({
    required this.package,
    required this.gate,
    required this.quantity,
    required this.manufacturer,
    required this.solderMaskColor,
    required this.onQuantityChanged,
    required this.onManufacturerChanged,
    required this.onSolderMaskChanged,
  });

  final FabricationPackage package;
  final ProductionGateSnapshot? gate;
  final int quantity;
  final String manufacturer;
  final String solderMaskColor;
  final ValueChanged<int> onQuantityChanged;
  final ValueChanged<String> onManufacturerChanged;
  final ValueChanged<String> onSolderMaskChanged;

  @override
  Widget build(BuildContext context) {
    final estimate = _estimate(package, quantity, solderMaskColor);
    return _Panel(
      title: 'Checkout Hazirligi',
      icon: Icons.fact_check,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          DropdownButtonFormField<String>(
            initialValue: manufacturer,
            decoration: const InputDecoration(
              labelText: 'Uretici',
              border: OutlineInputBorder(),
            ),
            items: const [
              DropdownMenuItem(value: 'PCBWay', child: Text('PCBWay')),
              DropdownMenuItem(value: 'JLCPCB', child: Text('JLCPCB')),
              DropdownMenuItem(
                value: 'Manual Review',
                child: Text('Manual Review'),
              ),
            ],
            onChanged: (value) {
              if (value != null) onManufacturerChanged(value);
            },
          ),
          const SizedBox(height: 12),
          TextFormField(
            initialValue: '$quantity',
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Miktar',
              border: OutlineInputBorder(),
            ),
            onChanged: (value) =>
                onQuantityChanged(int.tryParse(value) ?? quantity),
          ),
          const SizedBox(height: 12),
          const TextField(
            readOnly: true,
            controller: null,
            decoration: InputDecoration(
              labelText: 'Katman',
              hintText: '4',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: solderMaskColor,
            decoration: const InputDecoration(
              labelText: 'Lehim Maskesi Rengi',
              border: OutlineInputBorder(),
            ),
            items: const [
              DropdownMenuItem(value: 'Green', child: Text('Green')),
              DropdownMenuItem(value: 'Black', child: Text('Black')),
              DropdownMenuItem(value: 'Blue', child: Text('Blue')),
              DropdownMenuItem(value: 'Red', child: Text('Red')),
              DropdownMenuItem(value: 'White', child: Text('White')),
            ],
            onChanged: (value) {
              if (value != null) onSolderMaskChanged(value);
            },
          ),
          const SizedBox(height: 16),
          _EstimateBox(
            manufacturer: manufacturer,
            totalUsd: estimate.$1,
            unitUsd: estimate.$2,
            leadDays: estimate.$3,
          ),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: gate?.allowsManufacturing == true
                ? () => _copyPackagePath(context, package)
                : null,
            icon: gate?.allowsManufacturing == true
                ? const Icon(Icons.copy)
                : const Icon(Icons.lock),
            label: Text(
              gate?.allowsManufacturing == true
                  ? 'Paket yolunu kopyala'
                  : 'Uretim kapisi kilitli',
            ),
          ),
          const SizedBox(height: 10),
          Text(
            gate?.allowsManufacturing == true
                ? 'Not: Bu ekran dis servise veri gondermez. Uretim ZIP paketi hazirdir; son fiyat ve siparis uretici panelinde dogrulanir.'
                : 'Not: Canli manifest DRC/source/model kapilarini gecmeden ZIP yolu paylasilmaz ve uretim exportu baslatilmaz.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }

  (double, double, int) _estimate(
    FabricationPackage package,
    int quantity,
    String color,
  ) {
    final areaCm2 = (package.boardWidthMm * package.boardHeightMm) / 100.0;
    final layerMultiplier =
        1.0 + (package.checkout.layers - 2).clamp(0, 20) * 0.28;
    final colorMultiplier = color.toLowerCase() == 'green' ? 1.0 : 1.08;
    final total =
        60.0 +
        (areaCm2 * 0.018 * layerMultiplier * colorMultiplier).clamp(2.4, 999) *
            quantity;
    final leadDays = 9;
    return (
      double.parse(total.toStringAsFixed(2)),
      double.parse((total / quantity.clamp(1, 999)).toStringAsFixed(2)),
      leadDays,
    );
  }

  void _copyPackagePath(BuildContext context, FabricationPackage package) {
    Clipboard.setData(ClipboardData(text: package.productionZip));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Uretim paketi yolu kopyalandi.')),
    );
  }
}

class _ProductionGateBanner extends StatelessWidget {
  const _ProductionGateBanner({required this.gate});

  final ProductionGateSnapshot gate;

  @override
  Widget build(BuildContext context) {
    final passed = gate.allowsManufacturing;
    final color = passed ? Colors.green : Colors.red;
    final title = passed ? 'Uretim Kapisi Acik' : 'Uretim Kapisi Kilitli';
    final details = passed
        ? 'Manifest production_candidate. DRC=0, source evidence ve production model kapilari gecti.'
        : gate.blockers.join(' | ');
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.shade50,
        border: Border.all(color: color.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                passed ? Icons.shield : Icons.report_gmailerrorred,
                color: color.shade700,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(
                    color: color.shade800,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(details),
          if (gate.evidenceSummary.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              gate.evidenceSummary,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ],
      ),
    );
  }
}

class _ManufacturingPackageState {
  const _ManufacturingPackageState({required this.package, required this.gate});

  final FabricationPackage package;
  final ProductionGateSnapshot? gate;
}

class _EstimateBox extends StatelessWidget {
  const _EstimateBox({
    required this.manufacturer,
    required this.totalUsd,
    required this.unitUsd,
    required this.leadDays,
  });

  final String manufacturer;
  final double totalUsd;
  final double unitUsd;
  final int leadDays;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFEAF7EF),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            manufacturer,
            style: Theme.of(
              context,
            ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 8),
          Text('Tahmini toplam: \$${totalUsd.toStringAsFixed(2)}'),
          Text('Kart basina: \$${unitUsd.toStringAsFixed(2)}'),
          Text('Tahmini sure: $leadDays gun'),
        ],
      ),
    );
  }
}

class _FileGroup extends StatelessWidget {
  const _FileGroup({required this.title, required this.files});

  final String title;
  final List<ProductionFile> files;

  @override
  Widget build(BuildContext context) {
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      leading: const Icon(Icons.folder_zip),
      title: Text('$title (${files.length})'),
      children: [
        for (final file in files.take(12))
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.insert_drive_file),
            title: Text(file.name),
            subtitle: Text(_formatBytes(file.sizeBytes)),
          ),
      ],
    );
  }
}

class _StatusRow extends StatelessWidget {
  const _StatusRow({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: Theme.of(context).colorScheme.primary, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.title, required this.icon, required this.child});

  final String title;
  final IconData icon;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: Theme.of(context).colorScheme.primary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

class _GerberPreviewPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final board = RRect.fromRectAndRadius(
      Rect.fromLTWH(18, 18, size.width - 36, size.height - 36),
      const Radius.circular(8),
    );
    canvas.drawRRect(board, Paint()..color = const Color(0xFF2B6258));

    final copper = Paint()
      ..color = const Color(0xFFE8C84C)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(
      Offset(size.width * 0.18, size.height * 0.68),
      Offset(size.width * 0.82, size.height * 0.28),
      copper,
    );
    canvas.drawLine(
      Offset(size.width * 0.24, size.height * 0.32),
      Offset(size.width * 0.72, size.height * 0.70),
      copper,
    );

    final padPaint = Paint()..color = const Color(0xFFDCEFE8);
    for (final offset in [
      Offset(size.width * 0.18, size.height * 0.68),
      Offset(size.width * 0.82, size.height * 0.28),
      Offset(size.width * 0.24, size.height * 0.32),
      Offset(size.width * 0.72, size.height * 0.70),
    ]) {
      canvas.drawCircle(offset, 9, padPaint);
    }

    final silkPaint = Paint()
      ..color = Colors.white70
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;
    canvas.drawRect(
      Rect.fromLTWH(size.width * 0.36, size.height * 0.38, 92, 52),
      silkPaint,
    );
    canvas.drawRect(
      Rect.fromLTWH(size.width * 0.08, size.height * 0.16, 112, 64),
      silkPaint,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _ManufacturingExportResult extends StatelessWidget {
  const _ManufacturingExportResult({required this.result});

  final PcbaManufacturingExportResult result;

  @override
  Widget build(BuildContext context) {
    if (!result.success) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.red.shade50,
          border: Border.all(color: Colors.red.shade300),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.error, color: Colors.red.shade700),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Export Başarısız',
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      color: Colors.red.shade700,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(result.error ?? 'Bilinmeyen hata'),
          ],
        ),
      );
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.green.shade50,
        border: Border.all(color: Colors.green.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.check_circle, color: Colors.green.shade700),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '✓ Export Başarılı',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.green.shade700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _ExportDetailRow(
            icon: Icons.factory,
            label: 'Üretim Firması:',
            value: result.manufacturer,
          ),
          _ExportDetailRow(
            icon: Icons.folder,
            label: 'Klasör:',
            value: result.outputDir,
          ),
          _ExportDetailRow(
            icon: Icons.description,
            label: 'Dosya Sayısı:',
            value: '${result.fileCount}',
          ),
          _ExportDetailRow(
            icon: Icons.straighten,
            label: 'PCB Boyutu:',
            value:
                '${result.boardWidthMm.toStringAsFixed(1)} × ${result.boardHeightMm.toStringAsFixed(1)} mm',
          ),
          _ExportDetailRow(
            icon: Icons.widgets,
            label: 'Bileşen Sayısı:',
            value: '${result.componentCount}',
          ),
          _ExportDetailRow(
            icon: Icons.attach_money,
            label: 'Tahmini Maliyet:',
            value: '\$${result.costEstimateUsd.toStringAsFixed(2)}',
          ),
          _ExportDetailRow(
            icon: Icons.schedule,
            label: 'Tahmini Teslimat:',
            value: '${result.leadTimeDays} gün',
          ),
          const SizedBox(height: 10),
          Text(
            'Tüm dosyalar ${result.outputDir} klasöründe hazırdır. '
            'Adımları izleyerek ${result.manufacturer} web sitesine yükleme yapabilirsiniz.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _ExportDetailRow extends StatelessWidget {
  const _ExportDetailRow({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Icon(icon, size: 16, color: Colors.grey.shade600),
          const SizedBox(width: 8),
          Text(label, style: const TextStyle(fontWeight: FontWeight.w500)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(value, style: const TextStyle(color: Colors.black87)),
          ),
        ],
      ),
    );
  }
}

class FabricationPackage {
  const FabricationPackage({
    required this.message,
    required this.productionZip,
    required this.productionZipSizeBytes,
    required this.boardWidthMm,
    required this.boardHeightMm,
    required this.checkout,
    required this.files,
  });

  final String message;
  final String productionZip;
  final int productionZipSizeBytes;
  final double boardWidthMm;
  final double boardHeightMm;
  final CheckoutSelection checkout;
  final List<ProductionFile> files;

  factory FabricationPackage.fromJson(Map<String, dynamic> json) {
    return FabricationPackage(
      message: json['message'] as String? ?? 'Uretim paketi hazir.',
      productionZip: json['production_zip'] as String? ?? '',
      productionZipSizeBytes: json['production_zip_size_bytes'] as int? ?? 0,
      boardWidthMm: (json['board_width_mm'] as num?)?.toDouble() ?? 0,
      boardHeightMm: (json['board_height_mm'] as num?)?.toDouble() ?? 0,
      checkout: CheckoutSelection.fromJson(
        json['checkout'] as Map<String, dynamic>? ?? const {},
      ),
      files: [
        for (final item in json['files'] as List<dynamic>? ?? const [])
          ProductionFile.fromJson(item as Map<String, dynamic>),
      ],
    );
  }
}

class CheckoutSelection {
  const CheckoutSelection({
    required this.manufacturer,
    required this.quantity,
    required this.layers,
    required this.solderMaskColor,
  });

  final String manufacturer;
  final int quantity;
  final int layers;
  final String solderMaskColor;

  factory CheckoutSelection.fromJson(Map<String, dynamic> json) {
    return CheckoutSelection(
      manufacturer: json['manufacturer'] as String? ?? 'PCBWay',
      quantity: json['quantity'] as int? ?? 5,
      layers: json['layers'] as int? ?? 4,
      solderMaskColor: json['solder_mask_color'] as String? ?? 'Green',
    );
  }
}

class ProductionFile {
  const ProductionFile({
    required this.name,
    required this.category,
    required this.sizeBytes,
  });

  final String name;
  final String category;
  final int sizeBytes;

  factory ProductionFile.fromJson(Map<String, dynamic> json) {
    return ProductionFile(
      name: json['name'] as String? ?? 'unknown',
      category: json['category'] as String? ?? 'other',
      sizeBytes: json['size_bytes'] as int? ?? 0,
    );
  }
}

String _formatBytes(int bytes) {
  if (bytes >= 1024 * 1024) {
    return '${(bytes / (1024 * 1024)).toStringAsFixed(2)} MB';
  }
  if (bytes >= 1024) {
    return '${(bytes / 1024).toStringAsFixed(1)} KB';
  }
  return '$bytes B';
}
