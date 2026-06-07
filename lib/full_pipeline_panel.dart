import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'controllers/netlist_controller.dart';
import 'services/full_pipeline_service.dart';

/// Single-button panel that runs the entire OmniCircuit pipeline end-to-end.
///
/// Replaces the legacy 7-button EDA Pipeline panel.  The orchestrator runs:
///   ai_synthesis -> design_feasibility -> kicad_generation -> drc_cleanup
///   -> drc_verify -> manifest_sign -> fab_package
/// auto-repairing recoverable errors and pausing with a HITL blocker only
/// when human judgment is genuinely required.
class FullPipelinePanel extends StatefulWidget {
  const FullPipelinePanel({super.key});

  @override
  State<FullPipelinePanel> createState() => _FullPipelinePanelState();
}

class _FullPipelinePanelState extends State<FullPipelinePanel> {
  static const _service = FullPipelineService();

  PipelineProgress? _progress;
  StreamSubscription<PipelineProgress>? _sub;
  bool _running = false;
  bool _loadedProductionArtifacts = false;

  Future<void> _runPipeline({required bool skipSynthesis}) async {
    final controller = context.read<NetlistController>();
    setState(() {
      _running = true;
      _progress = null;
      _loadedProductionArtifacts = false;
    });

    try {
      _sub = _service
          .run(
            request: controller.requestText,
            bom: controller.bomText,
            notes: controller.technicalNotes,
            skipSynthesis: skipSynthesis,
          )
          .listen(
            _handleProgress,
            onDone: () => setState(() => _running = false),
            onError: (Object e) {
              setState(() {
                _running = false;
                _progress = PipelineProgress.error(e.toString());
              });
            },
          );
    } catch (e) {
      setState(() {
        _running = false;
        _progress = PipelineProgress.error('Failed to start: $e');
      });
    }
  }

  void _handleProgress(PipelineProgress snapshot) {
    setState(() => _progress = snapshot);
    if (!snapshot.isComplete || _loadedProductionArtifacts) return;
    _loadedProductionArtifacts = true;
    context.read<NetlistController>().refreshProductionArtifacts();
  }

  Future<void> _answerHitl(String decision, String rationale) async {
    final blocker = _progress?.hitlBlocker;
    if (blocker == null) return;
    final answer = {
      'session_id': blocker['session_id'],
      'decision': decision,
      'rationale': rationale,
      'decided_at':
          DateTime.now().toUtc().toIso8601String().split('.').first + 'Z',
    };
    final path =
        blocker['answer_path'] as String? ??
        'assets/generated/hitl_answer.json';
    final file = File(path.replaceAll('/', '\\'));
    await file.parent.create(recursive: true);
    await file.writeAsString(
      const JsonEncoder.withIndent('  ').convert(answer),
    );
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Karar kaydedildi: $decision — pipeline tekrar başlatılıyor...',
          ),
        ),
      );
    }
    // After answering, kick off the pipeline again (skipSynthesis=true since
    // the netlist is already there from the previous run).
    await Future<void>.delayed(const Duration(milliseconds: 600));
    await _runPipeline(skipSynthesis: true);
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final progress = _progress;
    final blocker = progress?.hitlBlocker;

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.rocket_launch, size: 22),
              const SizedBox(width: 8),
              Text(
                'Güvenilir Üretim Akışı',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              const Spacer(),
              if (_running) ...[
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: 8),
                Text(
                  progress?.currentPhase ?? 'starting...',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: _running
                      ? null
                      : () => _runPipeline(skipSynthesis: false),
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Güvenilir Tasarımı Üret'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Tek akış: AI/netlist → fiziksel uygunluk → gerçek KiCad şematik/PCB → '
            'DRC/evidence/manifest → PCBA ve üretim paketi. Güvenli çözülemeyen konuda durur ve sorar.',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          if (progress != null) ...[
            const Divider(height: 24),
            _ProgressOverview(progress: progress),
            const SizedBox(height: 12),
            _PhaseList(progress: progress),
            // ── Autonomous routing loop progress indicator ──
            if (_running && progress.currentPhase == 'drc_verify')
              _RoutingLoopIndicator(progress: progress),
            if (progress.finalArtifact != null) ...[
              const SizedBox(height: 12),
              _SuccessBanner(artifact: progress.finalArtifact!),
            ],
            if (progress.error != null || progress.errorDetails != null) ...[
              const SizedBox(height: 12),
              _ErrorBanner(
                message: progress.error ?? 'Pipeline hata ile durdu',
                details: progress.errorDetails,
              ),
            ],
            if (blocker != null) ...[
              const SizedBox(height: 12),
              _UserFriendlyDecisionCard(
                blocker: blocker,
                onAnswer: _answerHitl,
              ),
            ],
          ],
        ],
      ),
    );
  }
}

/// Shows which autonomous correction step the routing loop is on.
class _RoutingLoopIndicator extends StatelessWidget {
  const _RoutingLoopIndicator({required this.progress});
  final PipelineProgress progress;

  @override
  Widget build(BuildContext context) {
    // Count retry notes to determine which attempt we're on
    final drcPhases = progress.phases.where((p) => p.name == 'drc_verify');
    final retryCount = drcPhases.fold<int>(0, (sum, p) => sum + p.repairAttempts);
    final strategies = [
      'Via boyutunu küçültme',
      'Pasif bileşenleri arka yüze taşıma',
      'Kart boyutunu %10 büyütme',
      'Kart boyutunu %20 büyütme',
      'Manuel müdahale bekleniyor',
    ];
    final currentIdx = retryCount.clamp(0, strategies.length - 1);

    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: Colors.blue.shade50,
          border: Border.all(color: Colors.blue.shade200),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.auto_fix_high, size: 18, color: Colors.blue.shade700),
                const SizedBox(width: 6),
                Text(
                  'Otonom Düzeltme Çalışıyor...',
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: Colors.blue.shade900,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            for (var i = 0; i < strategies.length; i++)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    Icon(
                      i < currentIdx
                          ? Icons.check_circle
                          : (i == currentIdx
                              ? Icons.pending
                              : Icons.circle_outlined),
                      size: 14,
                      color: i < currentIdx
                          ? Colors.green
                          : (i == currentIdx ? Colors.blue : Colors.grey),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      '${i + 1}. ${strategies[i]}',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight:
                            i == currentIdx ? FontWeight.w600 : FontWeight.normal,
                        color: i <= currentIdx ? Colors.black87 : Colors.grey,
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _PhaseList extends StatelessWidget {
  const _PhaseList({required this.progress});
  final PipelineProgress progress;

  static const _labels = {
    'ai_synthesis': '1. AI Netlist',
    'design_feasibility': '2. Fiziksel Uygunluk',
    'component_resolution': '3. Bileşen Kütüphanesi',
    'kicad_generation': '4. KiCad PCB',
    'drc_cleanup': '5. DRC Temizlik',
    'drc_verify': '6. DRC Doğrula',
    'manifest_sign': '7. Manifest İmza',
    'fab_package': '8. Fab ZIP',
  };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final phase in progress.phases)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _phaseIcon(phase),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _labels[phase.name] ?? phase.name,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      if (phase.notes.isNotEmpty)
                        Text(
                          phase.notes,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                    ],
                  ),
                ),
                if (phase.repairAttempts > 0) ...[
                  const SizedBox(width: 6),
                  Chip(
                    label: Text('${phase.repairAttempts}x retry'),
                    visualDensity: VisualDensity.compact,
                  ),
                ],
                const SizedBox(width: 6),
                Text(
                  '${phase.durationSeconds.toStringAsFixed(1)}s',
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _phaseIcon(PipelinePhase phase) {
    if (phase.isRunning) {
      return const SizedBox(
        width: 18,
        height: 18,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
    }
    if (phase.isSuccess) {
      return const Icon(Icons.check_circle, color: Colors.green, size: 20);
    }
    if (phase.isFailed) {
      return const Icon(Icons.error, color: Colors.red, size: 20);
    }
    return const Icon(Icons.circle_outlined, size: 20);
  }
}

class _ProgressOverview extends StatelessWidget {
  const _ProgressOverview({required this.progress});
  final PipelineProgress progress;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final value = progress.progressPercent.clamp(0, 100);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.45),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(
                progress.isAwaitingHuman
                    ? Icons.pan_tool_alt
                    : progress.isFailed
                        ? Icons.error_outline
                        : Icons.sync,
                size: 18,
                color: progress.isFailed
                    ? theme.colorScheme.error
                    : theme.colorScheme.primary,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  progress.statusMessage.isEmpty
                      ? (progress.currentPhase ?? progress.status)
                      : progress.statusMessage,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              Text(
                '$value%',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              minHeight: 8,
              value: value / 100,
              backgroundColor: theme.colorScheme.surface,
            ),
          ),
          if (progress.currentPhase != null) ...[
            const SizedBox(height: 6),
            Text(
              'Aktif aşama: ${progress.currentPhase}',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _SuccessBanner extends StatelessWidget {
  const _SuccessBanner({required this.artifact});
  final String artifact;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.green.shade50,
        border: Border.all(color: Colors.green.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          const Icon(Icons.check_circle, color: Colors.green),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'ÜRETİM HAZIR ✓',
                  style: TextStyle(fontWeight: FontWeight.w600),
                ),
                Text(artifact, style: const TextStyle(fontSize: 12)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message, this.details});
  final String message;
  final String? details;

  @override
  Widget build(BuildContext context) {
    final detailText = details?.trim();
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.red.shade50,
        border: Border.all(color: Colors.red.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error, color: Colors.red),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  message,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                if (detailText != null && detailText.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Container(
                    constraints: const BoxConstraints(maxHeight: 220),
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.72),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: SingleChildScrollView(
                      child: SelectableText(
                        detailText,
                        style: const TextStyle(
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
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
  }
}

// ──────────────────────────────────────────────────────────────────────────────
// User-friendly decision card — replaces the old technical _HitlPrompt
// ──────────────────────────────────────────────────────────────────────────────

/// Maps blocker types to user-friendly card configurations.
class _DecisionCardConfig {
  final String title;
  final IconData icon;
  final Color primaryColor;
  final Color bgColor;
  final Color borderColor;
  final String primaryLabel;
  final String secondaryLabel;

  const _DecisionCardConfig({
    required this.title,
    required this.icon,
    required this.primaryColor,
    required this.bgColor,
    required this.borderColor,
    required this.primaryLabel,
    required this.secondaryLabel,
  });

  static _DecisionCardConfig forBlockerType(String type) {
    switch (type) {
      case 'placement':
        return _DecisionCardConfig(
          title: 'Küçük Bir Ayarlama Gerekiyor!',
          icon: Icons.tune,
          primaryColor: Colors.orange.shade800,
          bgColor: Colors.orange.shade50,
          borderColor: Colors.orange.shade400,
          primaryLabel: 'Evet, Güncelle (Önerilen)',
          secondaryLabel: 'Hayır, Bileşen Çıkar',
        );
      case 'routing':
        return _DecisionCardConfig(
          title: 'Bağlantı Sorunu Çözülüyor',
          icon: Icons.route,
          primaryColor: Colors.blue.shade800,
          bgColor: Colors.blue.shade50,
          borderColor: Colors.blue.shade400,
          primaryLabel: 'Tekrar Denesin',
          secondaryLabel: 'Manuel Düzelt',
        );
      case 'constraint':
        return _DecisionCardConfig(
          title: 'Mühendislik Kararı Gerekli',
          icon: Icons.settings_suggest,
          primaryColor: Colors.deepPurple.shade800,
          bgColor: Colors.deepPurple.shade50,
          borderColor: Colors.deepPurple.shade300,
          primaryLabel: 'Önerilen Seçenek',
          secondaryLabel: 'Diğer Seçenek',
        );
      default:
        return _DecisionCardConfig(
          title: 'Karar Gerekli',
          icon: Icons.help_outline,
          primaryColor: Colors.amber.shade800,
          bgColor: Colors.amber.shade50,
          borderColor: Colors.amber.shade400,
          primaryLabel: 'Onayla',
          secondaryLabel: 'Reddet',
        );
    }
  }
}

class _UserFriendlyDecisionCard extends StatefulWidget {
  const _UserFriendlyDecisionCard({
    required this.blocker,
    required this.onAnswer,
  });
  final Map<String, dynamic> blocker;
  final Future<void> Function(String decision, String rationale) onAnswer;

  @override
  State<_UserFriendlyDecisionCard> createState() =>
      _UserFriendlyDecisionCardState();
}

class _UserFriendlyDecisionCardState extends State<_UserFriendlyDecisionCard>
    with SingleTickerProviderStateMixin {
  bool _showComponentPicker = false;
  late final AnimationController _pulseController;
  late final Animation<double> _pulseAnimation;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat(reverse: true);
    _pulseAnimation = Tween<double>(begin: 0.95, end: 1.0).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  String _buildUserFriendlyExplanation() {
    final type = widget.blocker['blocker_type'] as String? ?? '?';
    final context = widget.blocker['context'] as Map<String, dynamic>? ?? {};
    final question = widget.blocker['question'] as String? ?? '';

    switch (type) {
      case 'placement':
        final boardSize = context['board_size_mm'] as List?;
        if (boardSize != null && boardSize.length >= 2) {
          return 'Bileşenleriniz seçtiğiniz ${boardSize[0]}x${boardSize[1]}mm '
              'kart boyutuna sığmıyor. Kartı büyütmemiz veya bazı bileşenleri '
              'çıkarmamız gerekiyor. Bu işlem tüm bileşenlerin güvenle '
              'çalışmasını sağlayacaktır.';
        }
        return question;
      case 'routing':
        final unconn = context['unconnected_count'] ?? 0;
        return 'Otomatik yönlendirme tamamlandı ancak $unconn bağlantı '
            'tamamlanamadı. Sistem 5 farklı strateji denedi ama manuel '
            'müdahale gerekiyor. KiCad\'da açarak düzeltebilir veya '
            'mevcut haliyle devam edebilirsiniz.';
      default:
        return question;
    }
  }

  @override
  Widget build(BuildContext context) {
    final type = widget.blocker['blocker_type'] as String? ?? '?';
    final config = _DecisionCardConfig.forBlockerType(type);
    final choices =
        (widget.blocker['suggested_choices'] as List?) ?? [];

    if (_showComponentPicker) {
      return _ComponentPickerCard(
        onConfirm: (refs) {
          widget.onAnswer(
            'reduce_scope',
            'Kullanıcı şu bileşenleri çıkarmayı seçti: ${refs.join(", ")}',
          );
        },
        onCancel: () => setState(() => _showComponentPicker = false),
        candidates: widget.blocker['context']
                ?['optional_reduction_candidates'] as Map<String, dynamic>? ??
            {},
      );
    }

    return AnimatedBuilder(
      animation: _pulseAnimation,
      builder: (context, child) => Transform.scale(
        scale: _pulseAnimation.value,
        child: child,
      ),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [config.bgColor, config.bgColor.withValues(alpha: 0.7)],
          ),
          border: Border.all(color: config.borderColor, width: 2),
          borderRadius: BorderRadius.circular(12),
          boxShadow: [
            BoxShadow(
              color: config.borderColor.withValues(alpha: 0.3),
              blurRadius: 8,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ── Title row ──
            Row(
              children: [
                Icon(config.icon, size: 28, color: config.primaryColor),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    config.title,
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: config.primaryColor,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),

            // ── Explanation ──
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.7),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                _buildUserFriendlyExplanation(),
                style: const TextStyle(fontSize: 14, height: 1.4),
              ),
            ),
            const SizedBox(height: 16),

            // ── Action buttons ──
            if (choices.isNotEmpty) ...[
              // Primary choice (first one = recommended)
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: () => widget.onAnswer(
                    choices[0]['id'] as String,
                    'Kullanıcı önerilen seçeneği onayladı',
                  ),
                  icon: const Icon(Icons.check_circle_outline),
                  label: Text(
                    type == 'placement'
                        ? config.primaryLabel
                        : (choices[0]['label'] as String? ?? config.primaryLabel),
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.green.shade600,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 8),
              // Secondary choices
              for (final choice in choices.skip(1))
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: () {
                        final id = choice['id'] as String;
                        if (id == 'reduce_scope') {
                          setState(() => _showComponentPicker = true);
                          return;
                        }
                        widget.onAnswer(id, '');
                      },
                      icon: Icon(
                        (choice['id'] as String) == 'abort'
                            ? Icons.cancel_outlined
                            : Icons.arrow_forward,
                        size: 18,
                      ),
                      label: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            (choice['id'] as String) == 'reduce_scope'
                                ? config.secondaryLabel
                                : (choice['label'] as String? ?? ''),
                            style: const TextStyle(fontWeight: FontWeight.w500),
                          ),
                          if ((choice['consequence'] as String?)?.isNotEmpty ??
                              false)
                            Padding(
                              padding: const EdgeInsets.only(top: 2),
                              child: Text(
                                'Sonuç: ${choice['consequence']}',
                                style: TextStyle(
                                  fontSize: 11,
                                  color: Colors.grey.shade600,
                                ),
                              ),
                            ),
                        ],
                      ),
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(
                          vertical: 10,
                          horizontal: 12,
                        ),
                        alignment: Alignment.centerLeft,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Component picker shown when user chooses "Bileşen Çıkar".
class _ComponentPickerCard extends StatefulWidget {
  const _ComponentPickerCard({
    required this.onConfirm,
    required this.onCancel,
    required this.candidates,
  });
  final void Function(List<String> refs) onConfirm;
  final VoidCallback onCancel;
  final Map<String, dynamic> candidates;

  @override
  State<_ComponentPickerCard> createState() => _ComponentPickerCardState();
}

class _ComponentPickerCardState extends State<_ComponentPickerCard> {
  final Set<String> _selected = {};

  @override
  Widget build(BuildContext context) {
    final allRefs = <String>[];
    widget.candidates.forEach((type, refs) {
      if (refs is List) {
        for (final r in refs) {
          allRefs.add(r.toString());
        }
      }
    });

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.orange.shade50,
        border: Border.all(color: Colors.orange.shade400, width: 2),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Icon(Icons.remove_circle_outline, color: Colors.orange.shade900),
              const SizedBox(width: 8),
              Text(
                'Hangilerini Çıkaralım?',
                style: TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.bold,
                  color: Colors.orange.shade900,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Aşağıdaki bileşenler opsiyoneldir — kaldırılması kartın çalışmasını etkilemez. '
            'Çıkarmak istediklerinizi seçin:',
            style: TextStyle(fontSize: 13, color: Colors.grey.shade700),
          ),
          const SizedBox(height: 12),
          ...widget.candidates.entries.map((entry) {
            final type = entry.key;
            final refs = (entry.value as List?)?.cast<String>() ?? [];
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(bottom: 4, top: 8),
                  child: Text(
                    type.toUpperCase(),
                    style: TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 12,
                      color: Colors.orange.shade800,
                    ),
                  ),
                ),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: refs.map((ref) {
                    final isSelected = _selected.contains(ref);
                    return FilterChip(
                      label: Text(ref),
                      selected: isSelected,
                      onSelected: (v) {
                        setState(() {
                          if (v) {
                            _selected.add(ref);
                          } else {
                            _selected.remove(ref);
                          }
                        });
                      },
                      selectedColor: Colors.orange.shade200,
                    );
                  }).toList(),
                ),
              ],
            );
          }),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: widget.onCancel,
                  child: const Text('Geri'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: FilledButton.icon(
                  onPressed: _selected.isEmpty
                      ? null
                      : () => widget.onConfirm(_selected.toList()),
                  icon: const Icon(Icons.delete_outline),
                  label: Text('${_selected.length} Bileşen Çıkar'),
                  style: FilledButton.styleFrom(
                    backgroundColor: Colors.red.shade600,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
