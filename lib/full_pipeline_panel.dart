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
                'Guvenilir Uretim Akisi',
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
                  label: const Text('Guvenilir Tasarimi Uret'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'Tek akis: AI/netlist -> fiziksel uygunluk -> gercek KiCad sematik/PCB -> '
            'DRC/evidence/manifest -> PCBA ve uretim paketi. Guvenli cozulemeyen konuda durur ve sorar.',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          if (progress != null) ...[
            const Divider(height: 24),
            _PhaseList(progress: progress),
            if (progress.finalArtifact != null) ...[
              const SizedBox(height: 12),
              _SuccessBanner(artifact: progress.finalArtifact!),
            ],
            if (progress.error != null) ...[
              const SizedBox(height: 12),
              _ErrorBanner(message: progress.error!),
            ],
            if (blocker != null) ...[
              const SizedBox(height: 12),
              _HitlPrompt(blocker: blocker, onAnswer: _answerHitl),
            ],
          ],
        ],
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
    'kicad_generation': '3. KiCad PCB',
    'drc_cleanup': '4. DRC Temizlik',
    'drc_verify': '5. DRC Dogrula',
    'manifest_sign': '6. Manifest Imza',
    'fab_package': '7. Fab ZIP',
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
  const _ErrorBanner({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.red.shade50,
        border: Border.all(color: Colors.red.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          const Icon(Icons.error, color: Colors.red),
          const SizedBox(width: 10),
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}

class _HitlPrompt extends StatefulWidget {
  const _HitlPrompt({required this.blocker, required this.onAnswer});
  final Map<String, dynamic> blocker;
  final Future<void> Function(String decision, String rationale) onAnswer;

  @override
  State<_HitlPrompt> createState() => _HitlPromptState();
}

class _HitlPromptState extends State<_HitlPrompt> {
  final _rationaleCtrl = TextEditingController();
  String? _selected;

  @override
  void dispose() {
    _rationaleCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final choices = (widget.blocker['suggested_choices'] as List?) ?? [];
    final blockerType = widget.blocker['blocker_type'] as String? ?? '?';
    final question = widget.blocker['question'] as String? ?? '';
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.amber.shade50,
        border: Border.all(color: Colors.amber.shade400),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.help_outline, color: Colors.amber),
              const SizedBox(width: 8),
              Text(
                'Mühendis Kararı Gerekli — $blockerType',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(question),
          const SizedBox(height: 12),
          RadioGroup<String>(
            groupValue: _selected,
            onChanged: (v) => setState(() => _selected = v),
            child: Column(
              children: [
                for (final c in choices)
                  RadioListTile<String>(
                    dense: true,
                    value: c['id'] as String,
                    title: Text(c['label'] as String? ?? ''),
                    subtitle: Text(c['consequence'] as String? ?? ''),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          TextField(
            controller: _rationaleCtrl,
            decoration: const InputDecoration(
              labelText: 'Gerekçe (opsiyonel)',
              border: OutlineInputBorder(),
              isDense: true,
            ),
            maxLines: 2,
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.icon(
              onPressed: _selected == null
                  ? null
                  : () =>
                        widget.onAnswer(_selected!, _rationaleCtrl.text.trim()),
              icon: const Icon(Icons.send),
              label: const Text('Kararı Gönder'),
            ),
          ),
        ],
      ),
    );
  }
}
