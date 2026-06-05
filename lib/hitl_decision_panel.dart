import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'services/hitl_service.dart';

class HitlDecisionPanel extends StatelessWidget {
  const HitlDecisionPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<HitlService>(
      builder: (context, service, _) {
        final state = service.activeState;
        if (state == null && service.lastError == null) {
          return const SizedBox(height: 16);
        }
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: state == null
              ? _HitlErrorPanel(message: service.lastError!)
              : _HitlDecisionBody(state: state),
        );
      },
    );
  }
}

class _HitlErrorPanel extends StatelessWidget {
  const _HitlErrorPanel({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7E5),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.orange.shade300),
      ),
      child: Row(
        children: [
          Icon(Icons.warning_amber, color: Colors.orange.shade800),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              'HITL durumu okunamadi: $message',
              style: TextStyle(
                color: Colors.orange.shade900,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HitlDecisionBody extends StatefulWidget {
  const _HitlDecisionBody({required this.state});

  final HitlState state;

  @override
  State<_HitlDecisionBody> createState() => _HitlDecisionBodyState();
}

class _HitlDecisionBodyState extends State<_HitlDecisionBody> {
  late final TextEditingController _rationaleController =
      TextEditingController();
  late final TextEditingController _manualDecisionController =
      TextEditingController();

  @override
  void didUpdateWidget(covariant _HitlDecisionBody oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state.sessionId != widget.state.sessionId) {
      _rationaleController.clear();
      _manualDecisionController.clear();
    }
  }

  @override
  void dispose() {
    _rationaleController.dispose();
    _manualDecisionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final service = context.watch<HitlService>();
    final state = widget.state;
    final contextText = const JsonEncoder.withIndent(
      '  ',
    ).convert(state.context);

    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF315C55), width: 1.3),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 18,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: const BoxDecoration(
              color: Color(0xFF1A2B27),
              borderRadius: BorderRadius.vertical(top: Radius.circular(8)),
            ),
            child: Row(
              children: [
                const Icon(Icons.engineering, color: Color(0xFFFFC857)),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Mühendislik Kararı Gerekli',
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      color: Colors.white,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                _BlockerChip(label: state.blockerType),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Wrap(
                  spacing: 10,
                  runSpacing: 8,
                  children: [
                    _MetaChip(
                      icon: Icons.fingerprint,
                      label: 'Session ${state.sessionId}',
                    ),
                    _MetaChip(icon: Icons.schedule, label: state.raisedAt),
                  ],
                ),
                const SizedBox(height: 14),
                Text(
                  'Soru',
                  style: Theme.of(
                    context,
                  ).textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                SelectableText(
                  state.question,
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    height: 1.35,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 14),
                if (state.context.isNotEmpty)
                  ExpansionTile(
                    tilePadding: EdgeInsets.zero,
                    childrenPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.data_object),
                    title: const Text('Mühendislik bağlamı'),
                    children: [
                      Container(
                        width: double.infinity,
                        constraints: const BoxConstraints(maxHeight: 220),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: const Color(0xFFF4F7F8),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: SingleChildScrollView(
                          child: SelectableText(
                            contextText,
                            style: const TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 12,
                              height: 1.35,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                const SizedBox(height: 14),
                TextField(
                  controller: _rationaleController,
                  minLines: 2,
                  maxLines: 4,
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    labelText: 'Rationale / mühendis gerekçesi',
                    hintText:
                        'Boş bırakılırsa seçilen karar ve sonucu gerekçe olarak yazılır.',
                    prefixIcon: Icon(Icons.edit_note),
                  ),
                ),
                const SizedBox(height: 14),
                if (state.choices.isEmpty)
                  _ManualDecisionControls(
                    controller: _manualDecisionController,
                    enabled: !service.isWriting,
                    onSubmit: (decision) => _submitManual(context, decision),
                  )
                else
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: [
                      for (final choice in state.choices)
                        _ChoiceButton(
                          choice: choice,
                          enabled: !service.isWriting,
                          onPressed: () => _submitChoice(context, choice),
                        ),
                    ],
                  ),
                if (service.isWriting) ...[
                  const SizedBox(height: 12),
                  const LinearProgressIndicator(minHeight: 3),
                ],
                if (service.lastError != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    service.lastError!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
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

  Future<void> _submitChoice(BuildContext context, HitlChoice choice) async {
    final rationale = _rationaleController.text.trim().isEmpty
        ? '${choice.label}. Consequence: ${choice.consequence}'
        : _rationaleController.text;
    await context.read<HitlService>().writeDecision(
      state: widget.state,
      decision: choice.id,
      rationale: rationale,
    );
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('HITL kararı yazıldı: ${choice.id}')),
    );
  }

  Future<void> _submitManual(BuildContext context, String decision) async {
    final trimmed = decision.trim();
    if (trimmed.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Karar alanı boş olamaz.')));
      return;
    }
    await context.read<HitlService>().writeDecision(
      state: widget.state,
      decision: trimmed,
      rationale: _rationaleController.text,
    );
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('HITL kararı yazıldı.')));
  }
}

class _ChoiceButton extends StatelessWidget {
  const _ChoiceButton({
    required this.choice,
    required this.enabled,
    required this.onPressed,
  });

  final HitlChoice choice;
  final bool enabled;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 320,
      child: OutlinedButton(
        style: OutlinedButton.styleFrom(
          alignment: Alignment.centerLeft,
          padding: const EdgeInsets.all(14),
          side: BorderSide(color: Theme.of(context).colorScheme.primary),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        onPressed: enabled ? onPressed : null,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CircleAvatar(
              radius: 16,
              backgroundColor: Theme.of(context).colorScheme.primary,
              child: Text(
                choice.id,
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w800,
                  fontSize: 12,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    choice.label,
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                  if (choice.consequence.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      choice.consequence,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ManualDecisionControls extends StatelessWidget {
  const _ManualDecisionControls({
    required this.controller,
    required this.enabled,
    required this.onSubmit,
  });

  final TextEditingController controller;
  final bool enabled;
  final ValueChanged<String> onSubmit;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: TextField(
            controller: controller,
            enabled: enabled,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              labelText: 'Serbest karar',
              prefixIcon: Icon(Icons.rule),
            ),
            onSubmitted: enabled ? onSubmit : null,
          ),
        ),
        const SizedBox(width: 10),
        FilledButton.icon(
          onPressed: enabled ? () => onSubmit(controller.text) : null,
          icon: const Icon(Icons.check),
          label: const Text('Yaz'),
        ),
      ],
    );
  }
}

class _BlockerChip extends StatelessWidget {
  const _BlockerChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Chip(
      side: BorderSide.none,
      backgroundColor: const Color(0xFFFFC857),
      label: Text(
        label.toUpperCase(),
        style: const TextStyle(
          color: Color(0xFF1A2B27),
          fontSize: 12,
          fontWeight: FontWeight.w900,
        ),
      ),
    );
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: const Color(0xFFF4F7F8),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 15, color: Colors.grey.shade700),
            const SizedBox(width: 6),
            Text(label, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
    );
  }
}
