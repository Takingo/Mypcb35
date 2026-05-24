import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'controllers/kicad_pipeline_controller.dart';
import 'services/kicad_pipeline_service.dart';

/// KiCad EDA pipeline adımlarını Flutter içinden tetikleyip izlemeyi sağlar.
/// OmniCircuit dashboard'a ayrı bir panel olarak eklenir.
class KiCadPipelinePanel extends StatelessWidget {
  const KiCadPipelinePanel({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => KiCadPipelineController(),
      child: const _PipelineBody(),
    );
  }
}

class _PipelineBody extends StatelessWidget {
  const _PipelineBody();

  @override
  Widget build(BuildContext context) {
    return const _Panel(
      title: 'EDA Pipeline Kontrolü',
      icon: Icons.engineering,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _ManufacturingBanner(),
          SizedBox(height: 14),
          _StepGrid(),
          SizedBox(height: 14),
          _LiveLogArea(),
          SizedBox(height: 10),
          _HistoryBar(),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Üretim hazır banner
// ---------------------------------------------------------------------------

class _ManufacturingBanner extends StatelessWidget {
  const _ManufacturingBanner();

  @override
  Widget build(BuildContext context) {
    final ctrl = context.watch<KiCadPipelineController>();
    final status = ctrl.freshOptimizationStatus;

    if (status == null) {
      return _InfoBanner(
        icon: Icons.info_outline,
        color: Colors.blueGrey.shade700,
        bgColor: const Color(0xFFEEF3F6),
        message:
            'Layout optimizer henüz çalıştırılmadı. '
            '"Layout Optimizer + DRC" adımını başlatın.',
      );
    }

    if (status.manufacturingReady) {
      return _InfoBanner(
        icon: Icons.verified,
        color: Colors.green.shade700,
        bgColor: const Color(0xFFEAF7EF),
        message:
            'ÜRETİM HAZIR ✓  '
            'Son DRC ihlali: ${status.finalViolationCount} | '
            'Gerber + Drill + Pick & Place export edildi.',
      );
    }

    return _InfoBanner(
      icon: Icons.lock_outline,
      color: Colors.orange.shade700,
      bgColor: const Color(0xFFFFF7E5),
      message:
          'Üretim kilidi açık değil. '
          'DRC ihlali: ${status.finalViolationCount}. '
          'Layout optimizer\'ı tekrar çalıştırın.',
    );
  }
}

class _InfoBanner extends StatelessWidget {
  const _InfoBanner({
    required this.icon,
    required this.color,
    required this.bgColor,
    required this.message,
  });

  final IconData icon;
  final Color color;
  final Color bgColor;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.30)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: color,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Adım butonları grid
// ---------------------------------------------------------------------------

class _StepGrid extends StatelessWidget {
  const _StepGrid();

  static const _steps = [
    (PipelineStep.kicadPhase2, Icons.schema, 'KiCad Üretimi'),
    (PipelineStep.layoutOptimizer, Icons.auto_fix_high, 'Optimizer + DRC'),
    (PipelineStep.pcbaExports, Icons.view_in_ar, 'PCBA Export'),
    (PipelineStep.fabricationPackage, Icons.inventory_2, 'Üretim ZIP'),
    (PipelineStep.simulationChecks, Icons.monitor_heart, 'Simülasyon'),
    (PipelineStep.engineeringAudit, Icons.fact_check, 'Müh. Denetim'),
    (PipelineStep.fabricationDrawing, Icons.picture_as_pdf, 'Fab Drawing'),
  ];

  @override
  Widget build(BuildContext context) {
    final ctrl = context.watch<KiCadPipelineController>();
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        for (final (step, icon, label) in _steps)
          _StepButton(
            step: step,
            icon: icon,
            label: label,
            running: ctrl.runningStep == step,
            disabled: ctrl.isRunning && ctrl.runningStep != step,
            lastResult: ctrl.history.cast<PipelineStepResult?>().lastWhere(
              (r) => r?.step == step,
              orElse: () => null,
            ),
            onPressed: () => ctrl.runStep(step),
          ),
        // DRC reload butonu
        _DrcReloadButton(ctrl: ctrl),
      ],
    );
  }
}

class _StepButton extends StatelessWidget {
  const _StepButton({
    required this.step,
    required this.icon,
    required this.label,
    required this.running,
    required this.disabled,
    required this.lastResult,
    required this.onPressed,
  });

  final PipelineStep step;
  final IconData icon;
  final String label;
  final bool running;
  final bool disabled;
  final PipelineStepResult? lastResult;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final result = lastResult;
    final statusColor = result == null
        ? Colors.grey.shade600
        : result.success
            ? Colors.green.shade700
            : Colors.red.shade700;
    final statusIcon = result == null
        ? null
        : result.success
            ? Icons.check_circle
            : Icons.error;

    return Tooltip(
      message: result == null
          ? 'Henüz çalıştırılmadı'
          : result.success
              ? 'Son çalışma başarılı (${result.duration.inMilliseconds}ms)'
              : 'Son çalışma başarısız: exit ${result.exitCode}',
      child: SizedBox(
        width: 160,
        child: OutlinedButton.icon(
          style: OutlinedButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 10),
            side: BorderSide(color: statusColor.withValues(alpha: 0.50)),
            backgroundColor: running
                ? Theme.of(context).colorScheme.primaryContainer
                : null,
          ),
          onPressed: disabled ? null : onPressed,
          icon: running
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : Stack(
                  clipBehavior: Clip.none,
                  children: [
                    Icon(icon, size: 20),
                    if (statusIcon != null)
                      Positioned(
                        right: -6,
                        top: -6,
                        child: Icon(statusIcon, size: 12, color: statusColor),
                      ),
                  ],
                ),
          label: Text(label, style: const TextStyle(fontSize: 12)),
        ),
      ),
    );
  }
}

class _DrcReloadButton extends StatelessWidget {
  const _DrcReloadButton({required this.ctrl});

  final KiCadPipelineController ctrl;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: 'DRC + optimizer raporunu diskten yeniden yükle',
      child: SizedBox(
        width: 160,
        child: OutlinedButton.icon(
          style: OutlinedButton.styleFrom(
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 10),
          ),
          onPressed: ctrl.isRunning ? null : ctrl.reloadDrcFromDisk,
          icon: const Icon(Icons.refresh, size: 20),
          label: const Text('DRC Yenile', style: TextStyle(fontSize: 12)),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Canlı log alanı
// ---------------------------------------------------------------------------

class _LiveLogArea extends StatelessWidget {
  const _LiveLogArea();

  @override
  Widget build(BuildContext context) {
    final ctrl = context.watch<KiCadPipelineController>();
    final log = ctrl.liveLog;

    if (log.isEmpty) {
      return const SizedBox.shrink();
    }

    return Container(
      constraints: const BoxConstraints(maxHeight: 220),
      width: double.infinity,
      decoration: BoxDecoration(
        color: const Color(0xFF1A2B27),
        borderRadius: BorderRadius.circular(8),
      ),
      padding: const EdgeInsets.all(12),
      child: SingleChildScrollView(
        reverse: true,
        child: SelectableText(
          log.join('\n'),
          style: const TextStyle(
            fontFamily: 'monospace',
            fontSize: 12,
            color: Color(0xFFB8E0D0),
            height: 1.5,
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Geçmiş özet bar
// ---------------------------------------------------------------------------

class _HistoryBar extends StatelessWidget {
  const _HistoryBar();

  @override
  Widget build(BuildContext context) {
    final ctrl = context.watch<KiCadPipelineController>();
    if (ctrl.history.isEmpty) return const SizedBox.shrink();

    return Row(
      children: [
        Expanded(
          child: Text(
            'Son ${ctrl.history.length} işlem — '
            '${ctrl.history.where((r) => r.success).length} başarılı, '
            '${ctrl.history.where((r) => !r.success).length} hatalı',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
        TextButton.icon(
          onPressed: ctrl.clearHistory,
          icon: const Icon(Icons.delete_sweep, size: 16),
          label: const Text('Geçmişi Temizle', style: TextStyle(fontSize: 12)),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Ortak panel bileşeni
// ---------------------------------------------------------------------------

class _Panel extends StatelessWidget {
  const _Panel({
    required this.title,
    required this.icon,
    required this.child,
  });

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
