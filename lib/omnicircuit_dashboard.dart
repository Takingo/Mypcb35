import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:flutter_svg/flutter_svg.dart';

import 'controllers/netlist_controller.dart';
import 'kicad_pipeline_panel.dart';
import 'manufacturing_dashboard.dart';
import 'models/ai_netlist.dart';
import 'models/design_package.dart';
import 'services/kicad_pipeline_service.dart';
import 'settings_screen.dart';

/// Canlı üretilen SVG'yi diskten okur; yoksa paketlenmiş asset'e düşer.
/// Pipeline her çalıştığında diskteki dosya güncellendiği için önizlemeler
/// gerçek üretim çıktısını yansıtır (build-time asset değil).
Future<String?> _loadLiveSvg(
  String absolutePath, {
  String? bundleFallback,
}) async {
  try {
    final file = File(absolutePath);
    if (await file.exists()) {
      return _cleanKiCadSvgText(await file.readAsString());
    }
  } catch (_) {
    // diskten okunamadı — bundle fallback dene
  }
  if (bundleFallback != null) {
    try {
      return _cleanKiCadSvgText(await rootBundle.loadString(bundleFallback));
    } catch (_) {
      // bundle'da da yok
    }
  }
  return null;
}

class OmniCircuitDashboard extends StatelessWidget {
  const OmniCircuitDashboard({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => NetlistController(),
      child: const _DashboardScaffold(),
    );
  }
}

class _DashboardScaffold extends StatelessWidget {
  const _DashboardScaffold();

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 1060;
        return Scaffold(
          appBar: AppBar(
            title: const Text('OmniCircuit AI'),
            actions: [
              IconButton(
                tooltip: 'Yapay Zeka Ayarlari',
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => const SettingsScreen(),
                  ),
                ),
                icon: const Icon(Icons.settings),
              ),
              IconButton(
                tooltip: 'Uretim ve siparis hazirligi',
                onPressed: () => _openManufacturingDashboard(context),
                icon: const Icon(Icons.local_shipping),
              ),
              IconButton(
                tooltip: 'AI_Netlist_v1 JSON kopyala',
                onPressed: () => _copyJson(context),
                icon: const Icon(Icons.copy_all),
              ),
            ],
          ),
          body: SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: compact ? const _CompactLayout() : const _WideLayout(),
            ),
          ),
        );
      },
    );
  }

  void _copyJson(BuildContext context) {
    final designPackage = context.read<NetlistController>().designPackage;
    if (designPackage == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Once tasarim paketi uretin.')),
      );
      return;
    }
    Clipboard.setData(
      ClipboardData(
        text: const JsonEncoder.withIndent(
          '  ',
        ).convert(designPackage.netlist.toJson()),
      ),
    );
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('AI_Netlist_v1 JSON panoya kopyalandi.')),
    );
  }

  void _openManufacturingDashboard(BuildContext context) {
    final controller = context.read<NetlistController>();
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ChangeNotifierProvider.value(
          value: controller,
          child: const ManufacturingDashboard(),
        ),
      ),
    );
  }
}

class _WideLayout extends StatelessWidget {
  const _WideLayout();

  @override
  Widget build(BuildContext context) {
    return const Column(
      children: [
        _WorkflowPanel(),
        SizedBox(height: 16),
        KiCadPipelinePanel(),
        SizedBox(height: 16),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              flex: 5,
              child: Column(
                children: [
                  _InputPanel(),
                  SizedBox(height: 16),
                  _ReasoningLogPanel(),
                ],
              ),
            ),
            SizedBox(width: 16),
            Expanded(
              flex: 4,
              child: Column(
                children: [
                  _SanityPanel(),
                  SizedBox(height: 16),
                  _OutputWorkspace(),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _CompactLayout extends StatelessWidget {
  const _CompactLayout();

  @override
  Widget build(BuildContext context) {
    return const Column(
      children: [
        _WorkflowPanel(),
        SizedBox(height: 16),
        KiCadPipelinePanel(),
        SizedBox(height: 16),
        _InputPanel(),
        SizedBox(height: 16),
        _ReasoningLogPanel(),
        SizedBox(height: 16),
        _AiCorrectionProposalsPanel(),
        SizedBox(height: 16),
        _SanityPanel(),
        SizedBox(height: 16),
        _OutputWorkspace(),
      ],
    );
  }
}

class _WorkflowPanel extends StatelessWidget {
  const _WorkflowPanel();

  @override
  Widget build(BuildContext context) {
    final designPackage = context.watch<NetlistController>().designPackage;
    final stages = designPackage?.stages ?? _emptyStages;
    return _Panel(
      title: 'EDA Uretim Hatti',
      icon: Icons.schema,
      child: Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [for (final stage in stages) _StageCard(stage: stage)],
      ),
    );
  }

  static const _emptyStages = [
    StageStatus(
      stage: DesignStage.analysis,
      title: 'Analiz',
      state: StageState.blocked,
      detail: 'Girdi bekleniyor.',
    ),
    StageStatus(
      stage: DesignStage.schematic,
      title: 'Sematik',
      state: StageState.blocked,
      detail: 'Netlist bekleniyor.',
    ),
    StageStatus(
      stage: DesignStage.pcb,
      title: 'PCB',
      state: StageState.blocked,
      detail: 'Sematik bekleniyor.',
    ),
    StageStatus(
      stage: DesignStage.pcba,
      title: 'PCBA',
      state: StageState.blocked,
      detail: 'PCB bekleniyor.',
    ),
    StageStatus(
      stage: DesignStage.simulation,
      title: 'Simulasyon',
      state: StageState.blocked,
      detail: 'Modeller bekleniyor.',
    ),
    StageStatus(
      stage: DesignStage.drc,
      title: 'DRC',
      state: StageState.blocked,
      detail: 'KiCad raporu bekleniyor.',
    ),
    StageStatus(
      stage: DesignStage.export,
      title: 'Export',
      state: StageState.blocked,
      detail: 'DRC/ERC bekleniyor.',
    ),
  ];
}

class _StageCard extends StatelessWidget {
  const _StageCard({required this.stage});

  final StageStatus stage;

  @override
  Widget build(BuildContext context) {
    final color = switch (stage.state) {
      StageState.ready => Colors.green.shade700,
      StageState.requiresReview => Colors.orange.shade700,
      StageState.blocked => Colors.grey.shade700,
    };
    final icon = switch (stage.state) {
      StageState.ready => Icons.check_circle,
      StageState.requiresReview => Icons.manage_search,
      StageState.blocked => Icons.lock,
    };
    return SizedBox(
      width: 180,
      child: DecoratedBox(
        decoration: BoxDecoration(
          border: Border.all(color: color.withValues(alpha: 0.35)),
          borderRadius: BorderRadius.circular(8),
          color: color.withValues(alpha: 0.06),
        ),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: color),
              const SizedBox(height: 8),
              Text(stage.title, style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(height: 4),
              Text(stage.detail, maxLines: 3, overflow: TextOverflow.ellipsis),
            ],
          ),
        ),
      ),
    );
  }
}

class _InputPanel extends StatelessWidget {
  const _InputPanel();

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<NetlistController>();
    return _Panel(
      title: 'Girdi Paneli',
      icon: Icons.input,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _SyncedTextArea(
            value: controller.requestText,
            minLines: 4,
            maxLines: 7,
            labelText: 'Urun isterleri',
            title: '1. Urun Isterleri',
            description:
                'Devrenin ne yapacagini, giris/cikislarini, ortam kosullarini ve ozel fonksiyonlarini yaz.',
            hintText:
                'Ornek: ESP32-S3 tabanli UWB anchor. 5V giris, 3.3V MCU, 1.8V UWB, iki role cikisi, Wi-Fi ayari, USB programlama, kutu icinde calisacak.',
            onChanged: controller.updateRequest,
          ),
          _ImportStatus(fileName: controller.requestFileName),
          const SizedBox(height: 12),
          _SyncedTextArea(
            value: controller.bomText,
            minLines: 3,
            maxLines: 6,
            labelText: 'BOM CSV veya komponent listesi',
            title: '2. BOM / Komponent Listesi',
            description:
                'Varsa resmi parca numaralariyla gir. CSV yukleyebilir veya satir satir yazabilirsin.',
            hintText:
                'Ornek CSV kolonlari: Reference, Quantity, Manufacturer, Part Number, Value, Package, Footprint, Notes\nU1,1,Espressif,ESP32-S3-WROOM-1,,Module,RF_Module:ESP32-S3-WROOM-1,MCU',
            onChanged: controller.updateBom,
          ),
          _ImportStatus(fileName: controller.bomFileName),
          const SizedBox(height: 12),
          _SyncedTextArea(
            value: controller.technicalNotes,
            minLines: 2,
            maxLines: 5,
            labelText: 'Teknik notlar: voltaj, RF, izolasyon, standartlar',
            title: '3. Teknik Notlar ve Uretim Kurallari',
            description:
                'Elektriksel limitleri, kart kurallarini, uretim tercihini ve dogrulanmasi gereken standartlari yaz.',
            hintText:
                'Ornek: 4 katman, 1.6mm FR4, RF net 50 ohm, AC bolge 8mm clearance, DRC=0 zorunlu, JLCPCB/PCBWay PCBA, kritik footprint datasheet ile dogrulansin.',
            onChanged: controller.updateTechnicalNotes,
          ),
          _ImportStatus(fileName: controller.technicalNotesFileName),
          const SizedBox(height: 12),
          _AiStatusBanner(controller: controller),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              FilledButton.icon(
                onPressed: controller.isGenerating ? null : controller.generate,
                icon: controller.isGenerating
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.auto_awesome),
                label: Text(
                  controller.isGenerating
                      ? 'Sentezleniyor'
                      : 'Tasarim Paketi Uret',
                ),
              ),
              OutlinedButton.icon(
                onPressed: () =>
                    controller.updateRequest(NetlistController.defaultRequest),
                icon: const Icon(Icons.restart_alt),
                label: const Text('Ornek Senaryo'),
              ),
              OutlinedButton.icon(
                onPressed: () => _showImportDialog(
                  context,
                  title: 'Ister dosyasi import et',
                  hintPath: r'C:\Mypcb\SCHEMATIC.md',
                  pickFile: controller.importRequestFile,
                  importPath: controller.importRequestFilePath,
                ),
                icon: const Icon(Icons.description),
                label: const Text('Ister Dosyasi'),
              ),
              OutlinedButton.icon(
                onPressed: () => _showImportDialog(
                  context,
                  title: 'BOM dosyasi import et',
                  hintPath: r'C:\Mypcb\BOM.csv',
                  pickFile: controller.importBomFile,
                  importPath: controller.importBomFilePath,
                ),
                icon: const Icon(Icons.table_chart),
                label: const Text('BOM Yukle'),
              ),
              OutlinedButton.icon(
                onPressed: () => _showImportDialog(
                  context,
                  title: 'Teknik not dosyasi import et',
                  hintPath: r'C:\Mypcb\PCB_NOTES.md',
                  pickFile: controller.importTechnicalNotesFile,
                  importPath: controller.importTechnicalNotesFilePath,
                ),
                icon: const Icon(Icons.rule_folder),
                label: const Text('Teknik Not'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _showImportDialog(
    BuildContext context, {
    required String title,
    required String hintPath,
    required Future<Object?> Function() pickFile,
    required Future<Object?> Function(String path) importPath,
  }) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => _FileImportDialog(
        title: title,
        hintPath: hintPath,
        pickFile: pickFile,
        importPath: importPath,
      ),
    );
  }
}

class _FileImportDialog extends StatefulWidget {
  const _FileImportDialog({
    required this.title,
    required this.hintPath,
    required this.pickFile,
    required this.importPath,
  });

  final String title;
  final String hintPath;
  final Future<Object?> Function() pickFile;
  final Future<Object?> Function(String path) importPath;

  @override
  State<_FileImportDialog> createState() => _FileImportDialogState();
}

class _FileImportDialogState extends State<_FileImportDialog> {
  late final TextEditingController _pathController = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _pathController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 560,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _pathController,
              decoration: InputDecoration(
                border: const OutlineInputBorder(),
                labelText: 'Dosya yolu',
                hintText: widget.hintPath,
                prefixIcon: const Icon(Icons.folder_open),
              ),
              onSubmitted: (_) => _loadFromPath(),
            ),
            const SizedBox(height: 10),
            Text(
              'Ornek: ${widget.hintPath}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (_error != null) ...[
              const SizedBox(height: 10),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _loading ? null : () => Navigator.of(context).pop(),
          child: const Text('Vazgec'),
        ),
        OutlinedButton.icon(
          onPressed: _loading ? null : _browse,
          icon: const Icon(Icons.search),
          label: const Text('Gozat'),
        ),
        FilledButton.icon(
          onPressed: _loading ? null : _loadFromPath,
          icon: _loading
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.upload_file),
          label: const Text('Yoldan Yukle'),
        ),
      ],
    );
  }

  Future<void> _browse() async {
    await _runImport(() => widget.pickFile());
  }

  Future<void> _loadFromPath() async {
    await _runImport(() => widget.importPath(_pathController.text));
  }

  Future<void> _runImport(Future<Object?> Function() action) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final imported = await action();
      if (!mounted) {
        return;
      }
      if (imported == null) {
        setState(() => _loading = false);
        return;
      }
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Dosya basariyla import edildi.')),
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _loading = false;
        _error = error.toString();
      });
    }
  }
}

class _SyncedTextArea extends StatefulWidget {
  const _SyncedTextArea({
    required this.value,
    required this.labelText,
    required this.title,
    required this.description,
    required this.hintText,
    required this.minLines,
    required this.maxLines,
    required this.onChanged,
  });

  final String value;
  final String labelText;
  final String title;
  final String description;
  final String hintText;
  final int minLines;
  final int maxLines;
  final ValueChanged<String> onChanged;

  @override
  State<_SyncedTextArea> createState() => _SyncedTextAreaState();
}

class _SyncedTextAreaState extends State<_SyncedTextArea> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.value,
  );

  @override
  void didUpdateWidget(covariant _SyncedTextArea oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != _controller.text) {
      _controller.value = TextEditingValue(
        text: widget.value,
        selection: TextSelection.collapsed(offset: widget.value.length),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.title,
          style: Theme.of(
            context,
          ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 4),
        Text(
          widget.description,
          style: Theme.of(
            context,
          ).textTheme.bodySmall?.copyWith(color: Colors.grey.shade700),
        ),
        const SizedBox(height: 8),
        TextFormField(
          controller: _controller,
          minLines: widget.minLines,
          maxLines: widget.maxLines,
          decoration: InputDecoration(
            border: const OutlineInputBorder(),
            labelText: widget.labelText,
            hintText: widget.hintText,
            alignLabelWithHint: true,
          ),
          onChanged: widget.onChanged,
        ),
      ],
    );
  }
}

class _ImportStatus extends StatelessWidget {
  const _ImportStatus({required this.fileName});

  final String? fileName;

  @override
  Widget build(BuildContext context) {
    if (fileName == null) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        children: [
          Icon(
            Icons.upload_file,
            size: 16,
            color: Theme.of(context).colorScheme.primary,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              'Yuklenen dosya: $fileName',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        ],
      ),
    );
  }
}

class _ReasoningLogPanel extends StatelessWidget {
  const _ReasoningLogPanel();

  @override
  Widget build(BuildContext context) {
    final log = context.watch<NetlistController>().liveLog;
    return _Panel(
      title: 'AI Muhendislik Akisi',
      icon: Icons.psychology_alt,
      child: log.isEmpty
          ? const _EmptyState(
              message:
                  'Analiz baslayinca eksik glue logic, guc agaci, seviye ceviriciler ve koruma kararlarini burada goreceksiniz.',
            )
          : Column(children: [for (final entry in log) _LogTile(entry: entry)]),
    );
  }
}

class _SanityPanel extends StatelessWidget {
  const _SanityPanel();

  @override
  Widget build(BuildContext context) {
    final designPackage = context.watch<NetlistController>().designPackage;
    final readinessReport = context
        .watch<NetlistController>()
        .engineeringReadinessReport;
    final inputEvidence = context
        .watch<NetlistController>()
        .inputEvidenceReport;
    return _Panel(
      title: 'Sanal Laboratuvar',
      icon: Icons.science,
      child: designPackage == null
          ? const _EmptyState(
              message:
                  'Guc, ERC, SI/RF, izolasyon ve uretim hazirlik kontrolleri burada gorunur.',
            )
          : Column(
              children: [
                if (readinessReport != null) ...[
                  _EngineeringReadinessPanel(report: readinessReport),
                  const Divider(height: 22),
                ],
                if (inputEvidence != null) ...[
                  _InputEvidencePanel(report: inputEvidence),
                  const Divider(height: 22),
                ],
                for (final check in designPackage.netlist.ercChecks)
                  _CheckRow(text: check),
                const Divider(height: 22),
                _CheckRow(
                  text:
                      '${designPackage.netlist.components.length} komponent sentezlendi',
                ),
                _CheckRow(
                  text:
                      '${designPackage.netlist.nets.length} net baglantisi olusturuldu',
                ),
                _CheckRow(
                  text:
                      '${designPackage.netlist.rules.length} DRC/ERC kurali uretildi',
                ),
                _ReviewRow(
                  text: designPackage.manufacturingReady
                      ? 'Uretim paketi hazir'
                      : 'Uretim exportu icin PCB geometri, DRC/ERC, RF ve guvenlik incelemesi gerekiyor',
                ),
              ],
            ),
    );
  }
}

class _InputEvidencePanel extends StatelessWidget {
  const _InputEvidencePanel({required this.report});

  final InputEvidenceReport report;

  @override
  Widget build(BuildContext context) {
    final hasError = report.errorCount > 0;
    final hasIssue = hasError || report.warnCount > 0 || report.reviewCount > 0;
    final color = hasError
        ? Colors.red.shade700
        : hasIssue
        ? Colors.orange.shade700
        : Colors.green.shade700;
    final bgColor = hasError
        ? const Color(0xFFFFECE8)
        : hasIssue
        ? const Color(0xFFFFF7E5)
        : const Color(0xFFEAF7EF);
    final icon = hasError
        ? Icons.report_problem
        : hasIssue
        ? Icons.fact_check
        : Icons.verified;
    final label = hasError
        ? 'GİRDİ HATASI — ${report.errorCount} kritik bulgu'
        : hasIssue
        ? 'GİRDİ İNCELEMESİ — ${report.warnCount} uyarı, ${report.reviewCount} inceleme'
        : 'GİRDİ TUTARLI';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Girdi Paneli Kanıt Denetimi: $label',
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
            ],
          ),
          if (report.questions.isNotEmpty) ...[
            const SizedBox(height: 8),
            const Text(
              'Kullanıcı onayı / düzeltmesi gereken maddeler:',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 4),
            for (final q in report.questions.take(6))
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      q.severity == 'error' ? '⛔ ' : '🔎 ',
                      style: const TextStyle(fontSize: 12),
                    ),
                    Expanded(
                      child: Text(
                        q.ask,
                        style: const TextStyle(fontSize: 12),
                      ),
                    ),
                  ],
                ),
              ),
            if (report.questions.length > 6)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '… ve ${report.questions.length - 6} madde daha',
                  style: const TextStyle(fontSize: 11, fontStyle: FontStyle.italic),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _EngineeringReadinessPanel extends StatelessWidget {
  const _EngineeringReadinessPanel({required this.report});

  final EngineeringReadinessReport report;

  @override
  Widget build(BuildContext context) {
    final blocked = report.overallStatus == 'blocked';
    final candidate = report.overallStatus == 'production_candidate';
    final review = report.overallStatus == 'review_required';

    final color = blocked
        ? Colors.red.shade700
        : review
        ? Colors.orange.shade700
        : Colors.green.shade700;
    final bgColor = blocked
        ? const Color(0xFFFFECE8)
        : review
        ? const Color(0xFFFFF7E5)
        : const Color(0xFFEAF7EF);
    final statusIcon = blocked
        ? Icons.gpp_bad
        : review
        ? Icons.manage_search
        : Icons.verified;
    final statusLabel = blocked
        ? 'BLOKE — Üretim Kilitli'
        : review
        ? 'İNCELEME GEREKLİ — Manuel mühendis onayı bekleniyor'
        : 'ÜRETİM ADAYI';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(statusIcon, color: color),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Mühendislik Gerçeklik Kapısı: %${report.readinessPercent} — $statusLabel',
                  style: Theme.of(
                    context,
                  ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(report.summary),
          if (review || blocked) ...[
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.07),
                borderRadius: BorderRadius.circular(6),
              ),
              child: const Text(
                '⚠️ Safety check, datasheet pinout, RF stackup ve SPICE modelleri '
                'otomatik doğrulanamaz. Gerçek üretime geçmeden önce '
                'elektronik mühendisi incelemesi zorunludur.',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w500),
              ),
            ),
          ],
          const SizedBox(height: 8),
          for (final check in report.checks.take(5))
            _ReadinessCheckRow(check: check),
          if (!candidate && report.checks.length > 5)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '+${report.checks.length - 5} kontrol daha — Mühendislik Denetimi butonuyla tam rapor üret.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
        ],
      ),
    );
  }
}

class _ReadinessCheckRow extends StatelessWidget {
  const _ReadinessCheckRow({required this.check});

  final EngineeringReadinessCheck check;

  @override
  Widget build(BuildContext context) {
    final icon = switch (check.status) {
      'pass' => Icons.check_circle,
      'warn' => Icons.manage_search,
      _ => Icons.error,
    };
    final color = switch (check.status) {
      'pass' => Colors.green.shade700,
      'warn' => Colors.orange.shade700,
      _ => Colors.red.shade700,
    };
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '${check.domain}: ${check.evidence}',
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}

class _OutputWorkspace extends StatelessWidget {
  const _OutputWorkspace();

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<NetlistController>();
    final designPackage = controller.designPackage;
    return _Panel(
      title: 'Sematik / PCB / PCBA / Export',
      icon: Icons.precision_manufacturing,
      child: designPackage == null
          ? const _EmptyState(
              message:
                  'Tasarim paketi uretildiginde sematik bloklar, PCB kurallari, PCBA ve export dosyalari burada acilir.',
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _StageSelector(
                  selected: controller.selectedStage,
                  onChanged: controller.selectStage,
                ),
                const SizedBox(height: 14),
                _StageBody(
                  designPackage: designPackage,
                  drcReport: controller.drcReport,
                  optimizationStatus: controller.layoutOptimizationStatus,
                  selectedStage: controller.selectedStage,
                ),
              ],
            ),
    );
  }
}

class _StageSelector extends StatelessWidget {
  const _StageSelector({required this.selected, required this.onChanged});

  final DesignStage selected;
  final ValueChanged<DesignStage> onChanged;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: SegmentedButton<DesignStage>(
        selected: {selected},
        onSelectionChanged: (value) => onChanged(value.first),
        segments: const [
          ButtonSegment(
            value: DesignStage.analysis,
            label: Text('Analiz'),
            icon: Icon(Icons.fact_check),
          ),
          ButtonSegment(
            value: DesignStage.schematic,
            label: Text('Sematik'),
            icon: Icon(Icons.account_tree),
          ),
          ButtonSegment(
            value: DesignStage.pcb,
            label: Text('PCB'),
            icon: Icon(Icons.developer_board),
          ),
          ButtonSegment(
            value: DesignStage.pcba,
            label: Text('PCBA'),
            icon: Icon(Icons.view_in_ar),
          ),
          ButtonSegment(
            value: DesignStage.simulation,
            label: Text('Sim'),
            icon: Icon(Icons.monitor_heart),
          ),
          ButtonSegment(
            value: DesignStage.drc,
            label: Text('DRC'),
            icon: Icon(Icons.bug_report),
          ),
          ButtonSegment(
            value: DesignStage.export,
            label: Text('Export'),
            icon: Icon(Icons.upload_file),
          ),
        ],
      ),
    );
  }
}

class _StageBody extends StatelessWidget {
  const _StageBody({
    required this.designPackage,
    required this.drcReport,
    required this.optimizationStatus,
    required this.selectedStage,
  });

  final DesignPackage designPackage;
  final DrcReport? drcReport;
  final LayoutOptimizationStatus? optimizationStatus;
  final DesignStage selectedStage;

  @override
  Widget build(BuildContext context) {
    return switch (selectedStage) {
      DesignStage.analysis => _NetlistPreview(netlist: designPackage.netlist),
      DesignStage.schematic => _SchematicPreview(
        blocks: designPackage.schematicBlocks,
      ),
      DesignStage.pcb => _PcbPreview(constraints: designPackage.pcbConstraints),
      DesignStage.pcba => _PcbaPreview(items: designPackage.pcbaItems),
      DesignStage.simulation => _SimulationPreview(
        checks: designPackage.simulationChecks,
      ),
      DesignStage.drc => _DrcAnalyzer(
        report: drcReport,
        optimizationStatus: optimizationStatus,
      ),
      DesignStage.export => _ExportPreview(
        artifacts: designPackage.exportArtifacts,
      ),
    };
  }
}

class _DrcAnalyzer extends StatefulWidget {
  const _DrcAnalyzer({required this.report, required this.optimizationStatus});

  final DrcReport? report;
  final LayoutOptimizationStatus? optimizationStatus;

  @override
  State<_DrcAnalyzer> createState() => _DrcAnalyzerState();
}

class _DrcAnalyzerState extends State<_DrcAnalyzer> {
  DrcViolation? selectedViolation;

  @override
  Widget build(BuildContext context) {
    final report = widget.report;
    if (report == null) {
      return const _EmptyState(
        message:
            'DRC_REPORT_V1.json bulunamadi. KiCad DRC parser calistirildiginda burada gorunecek.',
      );
    }
    final selected =
        selectedViolation ??
        (report.violations.isNotEmpty ? report.violations.first : null);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            _DrcMetric(
              label: 'Toplam',
              value: '${report.totalViolations}',
              icon: Icons.bug_report,
            ),
            if (widget.optimizationStatus != null)
              _DrcMetric(
                label: 'Üretim',
                value: widget.optimizationStatus!.manufacturingReady
                    ? 'hazır'
                    : 'kilitli',
                icon: widget.optimizationStatus!.manufacturingReady
                    ? Icons.verified
                    : Icons.lock,
              ),
            for (final entry in report.summaryByCategory.entries)
              _DrcMetric(
                label: entry.key,
                value: '${entry.value}',
                icon: Icons.category,
              ),
          ],
        ),
        const SizedBox(height: 14),
        if (widget.optimizationStatus != null)
          _OptimizationSummary(status: widget.optimizationStatus!),
        if (widget.optimizationStatus != null) const SizedBox(height: 14),
        if (selected != null) _DrcMap(violation: selected),
        const SizedBox(height: 14),
        for (final violation in report.violations.take(30))
          _DrcViolationTile(
            violation: violation,
            selected: selected?.id == violation.id,
            onTap: () => setState(() => selectedViolation = violation),
          ),
        if (report.violations.length > 30)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              '+${report.violations.length - 30} ek DRC ihlali raporda mevcut',
            ),
          ),
      ],
    );
  }
}

class _OptimizationSummary extends StatelessWidget {
  const _OptimizationSummary({required this.status});

  final LayoutOptimizationStatus status;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: status.manufacturingReady
            ? const Color(0xFFEAF7EF)
            : const Color(0xFFFFF7E5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            status.manufacturingReady
                ? 'Üretim Dosyaları Hazır'
                : 'Optimizasyon İncelemesi Gerekiyor',
            style: Theme.of(
              context,
            ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          Text('Final DRC ihlali: ${status.finalViolationCount}'),
          for (final iteration in status.iterations)
            Text(
              'Iterasyon ${iteration.iteration}: ${iteration.before} -> ${iteration.after} | ${iteration.actions.join(', ')}',
            ),
          for (final note in status.notes) Text(note),
        ],
      ),
    );
  }
}

class _DrcMetric extends StatelessWidget {
  const _DrcMetric({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Chip(avatar: Icon(icon, size: 16), label: Text('$label: $value'));
  }
}

class _DrcMap extends StatelessWidget {
  const _DrcMap({required this.violation});

  final DrcViolation violation;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 190,
      decoration: BoxDecoration(
        color: const Color(0xFF203B36),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Stack(
        children: [
          Positioned.fill(
            child: CustomPaint(painter: _DrcMapPainter(violation)),
          ),
          Positioned(
            left: 12,
            top: 12,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: Text('${violation.id} | ${violation.coordinateLabel}'),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DrcMapPainter extends CustomPainter {
  const _DrcMapPainter(this.violation);

  final DrcViolation violation;

  @override
  void paint(Canvas canvas, Size size) {
    final boardPaint = Paint()..color = const Color(0xFF2E5B52);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(14, 14, size.width - 28, size.height - 28),
        const Radius.circular(8),
      ),
      boardPaint,
    );
    final markerPaint = Paint()..color = const Color(0xFFE56B5D);
    for (final location in violation.locations) {
      if (location.x == null || location.y == null) {
        continue;
      }
      final x = 14 + (location.x!.clamp(0, 120) / 120) * (size.width - 28);
      final y = 14 + (location.y!.clamp(0, 80) / 80) * (size.height - 28);
      canvas.drawCircle(Offset(x, y), 7, markerPaint);
      canvas.drawCircle(
        Offset(x, y),
        14,
        markerPaint..color = const Color(0x55E56B5D),
      );
      markerPaint.color = const Color(0xFFE56B5D);
    }
  }

  @override
  bool shouldRepaint(covariant _DrcMapPainter oldDelegate) =>
      oldDelegate.violation.id != violation.id;
}

class _DrcViolationTile extends StatelessWidget {
  const _DrcViolationTile({
    required this.violation,
    required this.selected,
    required this.onTap,
  });

  final DrcViolation violation;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      selected: selected,
      contentPadding: EdgeInsets.zero,
      leading: Icon(
        violation.category == 'clearance'
            ? Icons.open_in_full
            : Icons.report_problem,
      ),
      title: Text(
        '${violation.id} ${violation.category} (${violation.severity})',
      ),
      subtitle: Text(
        '${violation.coordinateLabel}\n${violation.description}\n${violation.repairHint}',
      ),
      isThreeLine: true,
      onTap: onTap,
    );
  }
}

class _NetlistPreview extends StatelessWidget {
  const _NetlistPreview({required this.netlist});

  final AiNetlist netlist;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(netlist.schema, style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: 10),
        const _SectionTitle('Komponentler'),
        for (final component in netlist.components.take(12))
          _ComponentRow(component: component),
        if (netlist.components.length > 12)
          Text('+${netlist.components.length - 12} ek komponent'),
        const SizedBox(height: 12),
        const _SectionTitle('Netler'),
        for (final net in netlist.nets.take(10)) _NetRow(net: net),
      ],
    );
  }
}

/// KiCad SVG'sindeki çift-text sorununu düzeltir.
///
/// KiCad SVG export'u her metin için iki katman üretir:
/// 1) `opacity="0"` invisible `<text>` (ekran okuyucu/arama erişilebilirliği için)
/// 2) `<g class="stroked-text">` görünür path render'ı
///
/// flutter_svg bazı sürümlerde opacity="0" text'i gizlemez → çift render.
/// Bu fonksiyon invisible text elemanlarını SVG string'inden temizler.
String _cleanKiCadSvgText(String svg) {
  // <text ... opacity="0" stroke-opacity="0">...</text> kalıbını kaldır
  // (tek satır ve çok satırlı her ikisini de)
  return svg.replaceAll(
    RegExp(r'<text\b[^>]*\bopacity="0"[^>]*>.*?</text>', dotAll: true),
    '',
  );
}

class _SchematicPreview extends StatefulWidget {
  const _SchematicPreview({required this.blocks});

  final List<SchematicBlock> blocks;

  @override
  State<_SchematicPreview> createState() => _SchematicPreviewState();
}

class _SchematicPreviewState extends State<_SchematicPreview> {
  static const _svgAssetPath =
      'assets/generated/schematic.svg/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.svg';

  String? _cleanedSvg;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadSvg();
  }

  Future<void> _loadSvg() async {
    try {
      final raw = await rootBundle.loadString(_svgAssetPath);
      if (mounted) {
        setState(() {
          _cleanedSvg = _cleanKiCadSvgText(raw);
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Şematik güven uyarısı
        Container(
          width: double.infinity,
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: const Color(0xFFFFF3CD),
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: const Color(0xFFFFD966)),
          ),
          child: const Row(
            children: [
              Icon(Icons.warning_amber, color: Color(0xFF856404), size: 18),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Bu şematik AI + KiCad CLI tarafından üretilmiştir. '
                  'Gerçek üretimden önce footprint ve netlist doğrulaması gerekmektedir.',
                  style: TextStyle(fontSize: 12, color: Color(0xFF856404)),
                ),
              ),
            ],
          ),
        ),
        Container(
          height: 450,
          width: double.infinity,
          decoration: BoxDecoration(
            color: const Color(0xFFF0F0F0),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.grey.shade400),
          ),
          clipBehavior: Clip.hardEdge,
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? Center(
                  child: Text(
                    'SVG yüklenemedi:\n$_error',
                    textAlign: TextAlign.center,
                  ),
                )
              : Stack(
                  children: [
                    InteractiveViewer(
                      boundaryMargin: const EdgeInsets.all(200),
                      minScale: 0.05,
                      maxScale: 8.0,
                      constrained: false,
                      child: SizedBox(
                        width: 1800,
                        height: 1300,
                        child: SvgPicture.string(
                          _cleanedSvg!,
                          fit: BoxFit.contain,
                        ),
                      ),
                    ),
                    Positioned(
                      right: 16,
                      top: 16,
                      child: FloatingActionButton.small(
                        backgroundColor: Colors.white,
                        onPressed: () => _openFullscreen(context),
                        child: const Icon(
                          Icons.fullscreen,
                          color: Colors.black87,
                        ),
                      ),
                    ),
                  ],
                ),
        ),
      ],
    );
  }

  void _openFullscreen(BuildContext context) {
    final svg = _cleanedSvg;
    if (svg == null) return;
    showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        insetPadding: const EdgeInsets.all(12),
        child: Container(
          clipBehavior: Clip.hardEdge,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            color: const Color(0xFFF0F0F0),
          ),
          child: Stack(
            children: [
              InteractiveViewer(
                boundaryMargin: const EdgeInsets.all(500),
                minScale: 0.05,
                maxScale: 16.0,
                constrained: false,
                child: SvgPicture.string(svg),
              ),
              Positioned(
                right: 16,
                top: 16,
                child: IconButton(
                  icon: const Icon(Icons.close),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PcbPreview extends StatefulWidget {
  const _PcbPreview({required this.constraints});

  final List<PcbConstraint> constraints;

  @override
  State<_PcbPreview> createState() => _PcbPreviewState();
}

class _PcbPreviewState extends State<_PcbPreview> {
  static const _bundleFallback = 'assets/generated/pcb.svg';
  static const _service = KiCadPipelineService();

  String? _cleanedSvg;
  bool _loading = true;
  bool _rendering = false;
  bool _showBottom = false;

  @override
  void initState() {
    super.initState();
    _loadSvg();
  }

  Future<void> _loadSvg() async {
    setState(() => _loading = true);
    final path = _showBottom
        ? _service.pcbBottomSvgPath
        : _service.pcbTopSvgPath;
    final svg = await _loadLiveSvg(path, bundleFallback: _bundleFallback);
    if (mounted) {
      setState(() {
        _cleanedSvg = svg;
        _loading = false;
      });
    }
  }

  /// Diskte güncel tahta görünümü yoksa kicad-cli ile yeniden üret.
  Future<void> _regenerate() async {
    setState(() => _rendering = true);
    await _service.renderBoardViews();
    if (mounted) {
      setState(() => _rendering = false);
      await _loadSvg();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            SegmentedButton<bool>(
              selected: {_showBottom},
              onSelectionChanged: (v) {
                setState(() => _showBottom = v.first);
                _loadSvg();
              },
              segments: const [
                ButtonSegment(value: false, label: Text('Üst (Top)')),
                ButtonSegment(value: true, label: Text('Alt (Bottom)')),
              ],
            ),
            const Spacer(),
            IconButton.filledTonal(
              tooltip: 'Tam ekran ac',
              onPressed: _cleanedSvg == null
                  ? null
                  : () => _openFullscreen(context),
              icon: const Icon(Icons.fullscreen),
            ),
            const SizedBox(width: 8),
            OutlinedButton.icon(
              onPressed: _rendering ? null : _regenerate,
              icon: _rendering
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh, size: 16),
              label: const Text('Görünümü Yenile'),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Container(
          height: 450,
          width: double.infinity,
          decoration: BoxDecoration(
            color: const Color(0xFF1E1E1E),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.grey.shade400),
          ),
          clipBehavior: Clip.hardEdge,
          child: _loading
              ? const Center(
                  child: CircularProgressIndicator(color: Colors.white),
                )
              : _cleanedSvg == null
              ? _BoardEmptyState(rendering: _rendering, onRender: _regenerate)
              : Stack(
                  children: [
                    InteractiveViewer(
                      boundaryMargin: const EdgeInsets.all(200),
                      minScale: 0.05,
                      maxScale: 12.0,
                      constrained: false,
                      child: SizedBox(
                        width: 800,
                        height: 600,
                        child: SvgPicture.string(
                          _cleanedSvg!,
                          fit: BoxFit.contain,
                        ),
                      ),
                    ),
                    Positioned(
                      right: 16,
                      top: 16,
                      child: FloatingActionButton.small(
                        backgroundColor: Colors.white,
                        onPressed: () => _openFullscreen(context),
                        child: const Icon(
                          Icons.fullscreen,
                          color: Colors.black87,
                        ),
                      ),
                    ),
                  ],
                ),
        ),
        const SizedBox(height: 12),
        for (final constraint in widget.constraints)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Icon(
              constraint.severity == 'error' ? Icons.error : Icons.info,
            ),
            title: Text(constraint.id),
            subtitle: Text('${constraint.area}: ${constraint.rule}'),
          ),
      ],
    );
  }

  void _openFullscreen(BuildContext context) {
    final svg = _cleanedSvg;
    if (svg == null) return;
    showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        insetPadding: const EdgeInsets.all(20),
        child: Container(
          clipBehavior: Clip.hardEdge,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            color: const Color(0xFF1E1E1E),
          ),
          child: Stack(
            children: [
              InteractiveViewer(
                boundaryMargin: const EdgeInsets.all(500),
                minScale: 0.05,
                maxScale: 20.0,
                constrained: false,
                child: SvgPicture.string(svg),
              ),
              Positioned(
                right: 16,
                top: 16,
                child: IconButton(
                  icon: const Icon(Icons.close, color: Colors.white),
                  onPressed: () => Navigator.of(context).pop(),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Tahta görünümü diskte yokken gösterilen boş durum + üret butonu.
class _BoardEmptyState extends StatelessWidget {
  const _BoardEmptyState({required this.rendering, required this.onRender});

  final bool rendering;
  final VoidCallback onRender;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.developer_board, color: Colors.white38, size: 48),
          const SizedBox(height: 12),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 24),
            child: Text(
              'Tahta görünümü henüz üretilmedi. Önce "KiCad Üretimi" + '
              '"Optimizer + DRC" adımlarını çalıştırın, sonra görünümü üretin.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white70),
            ),
          ),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: rendering ? null : onRender,
            icon: rendering
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.auto_awesome),
            label: Text(rendering ? 'Üretiliyor...' : 'Tahta Görünümü Üret'),
          ),
        ],
      ),
    );
  }
}

class _PcbaPreview extends StatefulWidget {
  const _PcbaPreview({required this.items});

  final List<PcbaItem> items;

  @override
  State<_PcbaPreview> createState() => _PcbaPreviewState();
}

class _PcbaPreviewState extends State<_PcbaPreview> {
  static const _service = KiCadPipelineService();

  String? _cleanedSvg;
  bool _loading = true;
  bool _rendering = false;

  @override
  void initState() {
    super.initState();
    _loadSvg();
  }

  Future<void> _loadSvg() async {
    setState(() => _loading = true);
    final svg = await _loadLiveSvg(_service.pcbaAssemblySvgPath);
    if (mounted) {
      setState(() {
        _cleanedSvg = svg;
        _loading = false;
      });
    }
  }

  Future<void> _regenerate() async {
    setState(() => _rendering = true);
    await _service.renderBoardViews();
    if (mounted) {
      setState(() => _rendering = false);
      await _loadSvg();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              'Montaj Görünümü (komponent yerleşimi)',
              style: Theme.of(
                context,
              ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            const Spacer(),
            OutlinedButton.icon(
              onPressed: _rendering ? null : _regenerate,
              icon: _rendering
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh, size: 16),
              label: const Text('Görünümü Yenile'),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Container(
          height: 420,
          width: double.infinity,
          decoration: BoxDecoration(
            color: const Color(0xFF14201D),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.grey.shade400),
          ),
          clipBehavior: Clip.hardEdge,
          child: _loading
              ? const Center(
                  child: CircularProgressIndicator(color: Colors.white),
                )
              : _cleanedSvg == null
              ? _BoardEmptyState(rendering: _rendering, onRender: _regenerate)
              : Stack(
                  children: [
                    InteractiveViewer(
                      boundaryMargin: const EdgeInsets.all(200),
                      minScale: 0.05,
                      maxScale: 12.0,
                      constrained: false,
                      child: SizedBox(
                        width: 800,
                        height: 600,
                        child: SvgPicture.string(
                          _cleanedSvg!,
                          fit: BoxFit.contain,
                        ),
                      ),
                    ),
                    Positioned(
                      right: 12,
                      top: 12,
                      child: FloatingActionButton.small(
                        tooltip: 'Tam ekran ac',
                        backgroundColor: Colors.white,
                        onPressed: () => _openFullscreen(context),
                        child: const Icon(
                          Icons.fullscreen,
                          color: Colors.black87,
                        ),
                      ),
                    ),
                  ],
                ),
        ),
        const SizedBox(height: 12),
        const _SectionTitle('Komponent Yerleşim Listesi'),
        for (final item in widget.items.take(16))
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: const Icon(Icons.memory),
            title: Text('${item.ref} | ${item.partNumber}'),
            subtitle: Text('${item.placement}\n${item.assemblyNote}'),
            isThreeLine: true,
          ),
        if (widget.items.length > 16)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('+${widget.items.length - 16} ek komponent'),
          ),
      ],
    );
  }

  void _openFullscreen(BuildContext context) {
    final svg = _cleanedSvg;
    if (svg == null) return;
    showDialog<void>(
      context: context,
      builder: (_) => Dialog.fullscreen(
        backgroundColor: const Color(0xFF14201D),
        child: Stack(
          children: [
            Positioned.fill(
              child: InteractiveViewer(
                boundaryMargin: const EdgeInsets.all(800),
                minScale: 0.03,
                maxScale: 20.0,
                constrained: false,
                child: SizedBox(
                  width: 1400,
                  height: 1000,
                  child: SvgPicture.string(svg, fit: BoxFit.contain),
                ),
              ),
            ),
            Positioned(
              left: 20,
              top: 20,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                  child: Text(
                    'PCBA Montaj Gorunumu',
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ),
            ),
            Positioned(
              right: 20,
              top: 20,
              child: IconButton.filled(
                tooltip: 'Kapat',
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SimulationPreview extends StatelessWidget {
  const _SimulationPreview({required this.checks});

  final List<SimulationCheck> checks;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (final check in checks)
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(
              check.status == 'pass' ? Icons.check_circle : Icons.manage_search,
            ),
            title: Text('${check.name} (${check.domain})'),
            subtitle: Text(check.result),
          ),
      ],
    );
  }
}

class _ExportPreview extends StatelessWidget {
  const _ExportPreview({required this.artifacts});

  final List<ExportArtifact> artifacts;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          margin: const EdgeInsets.only(bottom: 12),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFFE3F2FD),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: const Color(0xFF90CAF9)),
          ),
          child: const Row(
            children: [
              Icon(Icons.info_outline, color: Color(0xFF0D47A1)),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Aşağıdaki dosyalar projenizin üretimi için KiCad tarafından oluşturulan temel çıktılardır. Dosya yollarını kopyalayabilir veya doğrudan klasörlerini açabilirsiniz.',
                  style: TextStyle(
                    color: Color(0xFF0D47A1),
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            ],
          ),
        ),
        for (final artifact in artifacts)
          Card(
            margin: const EdgeInsets.only(bottom: 8),
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
              side: BorderSide(color: Colors.grey.shade300),
            ),
            child: ListTile(
              leading: Icon(
                _artifactIcon(artifact.state),
                color: _artifactColor(artifact.state),
              ),
              title: Text(
                '${artifact.name} (${artifact.format})',
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
              subtitle: Text(
                'Konum: ${artifact.path}\nNot: ${artifact.note}',
                style: TextStyle(color: Colors.grey.shade700, height: 1.3),
              ),
              isThreeLine: true,
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    icon: const Icon(Icons.copy, size: 20),
                    tooltip: 'Yolu Kopyala',
                    onPressed: () {
                      final fullPath = artifact.path.startsWith('C:')
                          ? artifact.path
                          : 'C:\\Mypcb\\${artifact.path.replaceAll('/', '\\')}';
                      Clipboard.setData(ClipboardData(text: fullPath));
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text('${artifact.name} yolu kopyalandı.'),
                        ),
                      );
                    },
                  ),
                  IconButton(
                    icon: const Icon(Icons.folder_open, size: 20),
                    tooltip: 'Klasörü Aç',
                    onPressed: () async {
                      final fullPath = artifact.path.startsWith('C:')
                          ? artifact.path
                          : 'C:\\Mypcb\\${artifact.path.replaceAll('/', '\\')}';
                      try {
                        final file = File(fullPath);
                        String dirPath;
                        if (await FileSystemEntity.isDirectory(fullPath)) {
                          dirPath = fullPath;
                        } else {
                          dirPath = file.parent.path;
                        }
                        final dir = Directory(dirPath);
                        if (await dir.exists()) {
                          await Process.run('explorer.exe', [dirPath]);
                        } else {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text(
                                'Klasör bulunamadı. Önce üretimi çalıştırın.',
                              ),
                            ),
                          );
                        }
                      } catch (e) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text('Klasör açılamadı: $e')),
                        );
                      }
                    },
                  ),
                ],
              ),
            ),
          ),
        const SizedBox(height: 16),
        Center(
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              ElevatedButton.icon(
                icon: const Icon(Icons.folder_shared),
                label: const Text('Ana Çıktı Klasörünü Aç (outputs/)'),
                onPressed: () async {
                  final dir = Directory('C:\\Mypcb\\outputs');
                  if (await dir.exists()) {
                    await Process.run('explorer.exe', ['C:\\Mypcb\\outputs']);
                  } else {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Outputs klasörü bulunamadı.'),
                      ),
                    );
                  }
                },
              ),
              const SizedBox(width: 12),
              OutlinedButton.icon(
                icon: const Icon(Icons.rocket_launch),
                label: const Text('PCBA Sipariş Ekranına Git'),
                onPressed: () {
                  final controller = context.read<NetlistController>();
                  Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ChangeNotifierProvider.value(
                        value: controller,
                        child: const ManufacturingDashboard(),
                      ),
                    ),
                  );
                },
              ),
            ],
          ),
        ),
      ],
    );
  }

  IconData _artifactIcon(ArtifactState state) {
    return switch (state) {
      ArtifactState.generated => Icons.check_circle,
      ArtifactState.scaffolded => Icons.construction,
      ArtifactState.blocked => Icons.lock,
    };
  }

  Color _artifactColor(ArtifactState state) {
    return switch (state) {
      ArtifactState.generated => Colors.green.shade700,
      ArtifactState.scaffolded => Colors.orange.shade700,
      ArtifactState.blocked => Colors.red.shade700,
    };
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

class _LogTile extends StatelessWidget {
  const _LogTile({required this.entry});

  final ReasoningEntry entry;

  @override
  Widget build(BuildContext context) {
    final isAiLog = entry.outcome == 'ai-log' || entry.outcome == 'ai-complete';
    final color = entry.level == 'warning'
        ? Colors.orange.shade700
        : isAiLog
        ? const Color(0xFF1565C0)
        : Theme.of(context).colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            entry.level == 'warning'
                ? Icons.warning_amber
                : isAiLog
                ? Icons.psychology
                : Icons.check_circle,
            color: color,
            size: 20,
          ),
          const SizedBox(width: 10),
          Expanded(child: Text('${entry.message} [${entry.outcome}]')),
        ],
      ),
    );
  }
}

class _CheckRow extends StatelessWidget {
  const _CheckRow({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Icon(Icons.check_circle, color: Colors.green.shade700, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}

class _ReviewRow extends StatelessWidget {
  const _ReviewRow({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Icon(Icons.manage_search, color: Colors.orange.shade700, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}

class _ComponentRow extends StatelessWidget {
  const _ComponentRow({required this.component});

  final NetlistComponent component;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.memory),
      title: Text('${component.ref} - ${component.value}'),
      subtitle: Text('${component.type} | ${component.partNumber}'),
    );
  }
}

class _NetRow extends StatelessWidget {
  const _NetRow({required this.net});

  final NetConnection net;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.cable),
      title: Text(net.net),
      subtitle: Text('${net.netClass}: ${net.pins.join(' -> ')}'),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: Theme.of(
        context,
      ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w800),
    );
  }
}

// ---------------------------------------------------------------------------
// AI Durum Banneri — Ollama bağlantı durumunu ve son sentez kaynağını gösterir
// ---------------------------------------------------------------------------

class _AiStatusBanner extends StatelessWidget {
  const _AiStatusBanner({required this.controller});

  final NetlistController controller;

  @override
  Widget build(BuildContext context) {
    final status = controller.ollamaStatus;
    final source = controller.lastSynthesisSource;

    // Son sentezden sonra göster
    final showSource = source.isNotEmpty;
    final realAi = source == 'ai';

    Color bgColor;
    Color borderColor;
    IconData icon;
    String label;

    if (status == null) {
      bgColor = const Color(0xFFF4F7F8);
      borderColor = Colors.grey.shade400;
      icon = Icons.radio_button_unchecked;
      label =
          'AI durumu kontrol ediliyor... '
          '(${controller.configuredProvider.toUpperCase()} / ${controller.configuredModel})';
    } else if (status.connected) {
      bgColor = showSource && realAi
          ? const Color(0xFFE8F5E9)
          : const Color(0xFFEAF7EF);
      borderColor = Colors.green.shade400;
      icon = Icons.smart_toy;
      final modelLine = status.availableModels.isEmpty
          ? status.model
          : '${status.model} (${status.availableModels.length} model mevcut)';
      label =
          '${status.provider.toUpperCase()} bağlı — $modelLine'
          '${showSource ? (realAi ? " ✓ Son sentez GERÇEK AI" : " ⚡ Son sentez deterministik motor") : ""}';
    } else {
      bgColor = const Color(0xFFFFF7E5);
      borderColor = Colors.orange.shade400;
      icon = Icons.wifi_off;
      label =
          '${status.provider.toUpperCase()} bağlanamadı'
          '${status.error != null ? " — ${status.error}" : ""}'
          '. Deterministik motor kullanılacak.';
    }

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: borderColor),
      ),
      child: Row(
        children: [
          Icon(icon, size: 16, color: borderColor),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              label,
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
            ),
          ),
          IconButton(
            tooltip: 'AI bağlantısını yenile',
            constraints: const BoxConstraints(maxHeight: 28, maxWidth: 28),
            padding: EdgeInsets.zero,
            icon: const Icon(Icons.refresh, size: 16),
            onPressed: controller.refreshOllamaStatus,
          ),
        ],
      ),
    );
  }
}

/// AI Hata Düzeltme Önerileri Paneli
class _AiCorrectionProposalsPanel extends StatelessWidget {
  const _AiCorrectionProposalsPanel();

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<NetlistController>();
    final report = controller.correctionProposals;

    if (report == null || report.proposals.isEmpty) {
      return const SizedBox.shrink();
    }

    return _Panel(
      title: 'AI Hata Düzeltme Önerileri',
      icon: Icons.auto_fix_high,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Summary banner
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: report.proposals.any((p) => p.isSafetyCritical)
                  ? Colors.red.shade50
                  : Colors.orange.shade50,
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              '${report.totalCount} hata bulundu — '
              '${report.autoApplicableCount} düşük riskli, '
              '${report.safetyCriticalCount} güvenlik kritik',
              style: TextStyle(
                fontSize: 13,
                color: report.proposals.any((p) => p.isSafetyCritical)
                    ? Colors.red.shade900
                    : Colors.orange.shade900,
              ),
            ),
          ),
          const SizedBox(height: 12),
          // "Fix All Low-Risk" button
          if (report.autoApplicable.isNotEmpty)
            FilledButton.icon(
              onPressed: () => controller.approveAllLowRisk(),
              icon: const Icon(Icons.auto_fix_high),
              label: Text('${report.autoApplicableCount} Düşük Riskli Öneyi Onayla'),
            ),
          if (report.autoApplicable.isNotEmpty) const SizedBox(height: 12),
          // Per-proposal cards
          for (final proposal in report.proposals) _ProposalCard(proposal: proposal, controller: controller),
          const SizedBox(height: 12),
          // Apply button
          if (report.proposals.any((p) => p.status == 'approved'))
            FilledButton.tonal(
              onPressed: controller.isApplyingCorrections ? null : controller.applyApprovedCorrections,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  controller.isApplyingCorrections
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.check_circle),
                  const SizedBox(width: 8),
                  Text(
                    controller.isApplyingCorrections ? 'Uygulanıyor...' : 'Onaylanan Önerileri Uygula',
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Tek bir düzeltme önerisinin kartı
class _ProposalCard extends StatefulWidget {
  const _ProposalCard({
    required this.proposal,
    required this.controller,
  });

  final AiCorrectionProposal proposal;
  final NetlistController controller;

  @override
  State<_ProposalCard> createState() => _ProposalCardState();
}

class _ProposalCardState extends State<_ProposalCard> {
  bool _showReasoning = false;

  @override
  Widget build(BuildContext context) {
    final p = widget.proposal;

    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header: error badge + human readable
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Chip(
                  label: Text(p.errorCategory),
                  backgroundColor: p.isSafetyCritical ? Colors.red.shade100 : Colors.orange.shade100,
                  labelStyle: TextStyle(
                    fontSize: 11,
                    color: p.isSafetyCritical ? Colors.red.shade900 : Colors.orange.shade900,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    p.humanReadable,
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            // AI Proposal text
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Colors.blue.shade50,
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                p.aiProposalText,
                style: TextStyle(fontSize: 12, color: Colors.blue.shade900, fontStyle: FontStyle.italic),
              ),
            ),
            const SizedBox(height: 8),
            // Reasoning toggle
            GestureDetector(
              onTap: () => setState(() => _showReasoning = !_showReasoning),
              child: Row(
                children: [
                  Icon(_showReasoning ? Icons.expand_less : Icons.expand_more, size: 18),
                  const SizedBox(width: 4),
                  const Text('AI Gerekçesi', style: TextStyle(fontSize: 11, fontStyle: FontStyle.italic)),
                ],
              ),
            ),
            if (_showReasoning) ...[
              const SizedBox(height: 4),
              Text(
                p.aiReasoning,
                style: const TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ],
            const SizedBox(height: 8),
            // Confidence meter
            Row(
              children: [
                Expanded(
                  child: LinearProgressIndicator(
                    value: p.confidence,
                    backgroundColor: Colors.grey.shade300,
                    color: p.confidence >= 0.8
                        ? Colors.green
                        : p.confidence >= 0.6
                            ? Colors.orange
                            : Colors.red,
                    minHeight: 6,
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  'Güven: ${(p.confidence * 100).toInt()}%',
                  style: const TextStyle(fontSize: 11),
                ),
              ],
            ),
            const SizedBox(height: 8),
            // Safety and uncertain badges
            if (p.isSafetyCritical)
              Chip(
                label: const Text('⚠️ Güvenlik Kritik'),
                backgroundColor: Colors.red.shade100,
                labelStyle: TextStyle(fontSize: 11, color: Colors.red.shade900),
              ),
            if (p.aiUncertain) ...[
              if (p.isSafetyCritical) const SizedBox(height: 4),
              Chip(
                label: const Text('❓ Emin Değilim'),
                backgroundColor: Colors.amber.shade100,
                labelStyle: TextStyle(fontSize: 11, color: Colors.amber.shade900),
              ),
            ],
            const SizedBox(height: 8),
            // Action buttons
            if (p.status == 'pending')
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  FilledButton.tonal(
                    onPressed: () => widget.controller.rejectProposal(p.id),
                    child: const Text('Reddet'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: p.isSafetyCritical
                        ? () => ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text('Güvenlik kritik — manuel inceleme zorunlu')),
                            )
                        : () => widget.controller.approveProposal(p.id),
                    child: const Text('Onayla'),
                  ),
                ],
              )
            else
              Chip(
                label: Text(
                  p.status == 'approved'
                      ? '✓ Onaylandı'
                      : p.status == 'rejected'
                          ? '✗ Reddedildi'
                          : p.status,
                ),
                backgroundColor: p.status == 'approved'
                    ? Colors.green.shade100
                    : p.status == 'rejected'
                        ? Colors.grey.shade300
                        : Colors.blue.shade100,
              ),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFFF4F7F8),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(message),
    );
  }
}
