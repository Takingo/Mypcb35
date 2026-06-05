import 'dart:convert';
import 'dart:io';

import 'package:omnicircuit_ai/models/ai_netlist.dart';

/// Düzeltme önerilerini okur, onayları yazar, backend'i tetikler.
class AiCorrectionService {
  const AiCorrectionService({this.projectRoot = r'C:\Mypcb'});

  final String projectRoot;

  /// Proposals dosyasını diskten yükler.
  Future<AiCorrectionProposalsReport?> loadProposals() async {
    final file = File(
      '$projectRoot\\assets\\generated\\ai_correction_proposals.json',
    );
    if (!await file.exists()) return null;
    try {
      final data =
          jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      return AiCorrectionProposalsReport.fromJson(data);
    } catch (_) {
      return null;
    }
  }

  /// Onayları/redleri approvals dosyasına yazar.
  Future<void> writeApprovals(Map<String, String> decisions) async {
    // decisions: {proposalId -> 'approved' | 'rejected'}
    final now = DateTime.now().toUtc().toIso8601String();
    final decisionList = decisions.entries
        .map(
          (e) => {'proposal_id': e.key, 'decision': e.value, 'decided_at': now},
        )
        .toList();

    final approvalsData = {
      'schema': 'AI_CORRECTION_APPROVALS_V1',
      'generated_at': now,
      'proposals_file':
          '$projectRoot\\assets\\generated\\ai_correction_proposals.json',
      'decisions': decisionList,
    };

    final file = File(
      '$projectRoot\\assets\\generated\\ai_correction_approvals.json',
    );
    await file.writeAsString(
      const JsonEncoder.withIndent('  ').convert(approvalsData),
      encoding: const Utf8Codec(),
    );
  }

  /// run_ai_correction.ps1'i çalıştırır, log satırları callback'e gönderilir.
  Future<AiCorrectionResult> applyApproved({
    void Function(String line)? onLog,
  }) async {
    final scriptPath = '$projectRoot\\tool\\run_ai_correction.ps1';
    final process = await Process.start('powershell.exe', [
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      scriptPath,
      '-ProjectRoot',
      projectRoot,
    ], workingDirectory: projectRoot);

    process.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) => onLog?.call(line));

    final stdoutLines = await process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .toList();

    final exitCode = await process.exitCode;

    // Parse JSON result from stdout
    final jsonLine = stdoutLines.reversed.firstWhere(
      (l) => l.trim().startsWith('{'),
      orElse: () => '{}',
    );

    if (jsonLine.isEmpty || jsonLine == '{}') {
      return AiCorrectionResult(
        success: exitCode == 0,
        status: exitCode == 0 ? 'applied' : 'error',
        appliedCount: 0,
        failedCount: 0,
      );
    }

    try {
      final data = jsonDecode(jsonLine) as Map<String, dynamic>;
      return AiCorrectionResult(
        success: exitCode == 0,
        status: data['status'] as String? ?? 'unknown',
        appliedCount: (data['applied'] as num?)?.toInt() ?? 0,
        failedCount: (data['failed'] as num?)?.toInt() ?? 0,
        reverifyStatus: data['reverify'] as String?,
      );
    } catch (_) {
      return const AiCorrectionResult(
        success: false,
        status: 'parse_error',
        appliedCount: 0,
        failedCount: 0,
      );
    }
  }

  /// Auto-approval shortcut: writes approvals for all auto_applicable proposals.
  Future<void> approveAllLowRisk(AiCorrectionProposalsReport report) async {
    final decisions = <String, String>{};
    for (final p in report.autoApplicable) {
      decisions[p.id] = 'approved';
    }
    await writeApprovals(decisions);
  }
}

/// Result of applying approved corrections.
class AiCorrectionResult {
  const AiCorrectionResult({
    required this.success,
    required this.status,
    required this.appliedCount,
    required this.failedCount,
    this.reverifyStatus,
    this.error,
  });

  final bool success;
  final String status;
  final int appliedCount;
  final int failedCount;
  final String? reverifyStatus;
  final String? error;
}
