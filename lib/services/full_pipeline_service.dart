import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Drives `engine/full_pipeline_orchestrator.py` and exposes its live progress.
///
/// The orchestrator writes `assets/generated/pipeline_progress.json` after
/// every phase; this service polls that file while the process runs and
/// notifies the UI via a Stream of [PipelineProgress] snapshots.
class FullPipelineService {
  const FullPipelineService({this.projectRoot = r'C:\Mypcb'});

  final String projectRoot;

  static const _kicadPython = r'C:\Program Files\KiCad\10.0\bin\python.exe';
  static const _systemPython = 'python';

  /// Run the full orchestrator. Streams progress snapshots and a final summary.
  Stream<PipelineProgress> run({
    required String request,
    String bom = '',
    String notes = '',
    bool skipSynthesis = false,
  }) async* {
    final progressFile = File('$projectRoot\\assets\\generated\\pipeline_progress.json');

    // Clear any previous progress so the UI starts fresh.
    if (progressFile.existsSync()) {
      try {
        await progressFile.delete();
      } catch (_) {}
    }

    final args = <String>[
      'engine\\full_pipeline_orchestrator.py',
      if (request.isNotEmpty) ...['--request', request],
      if (notes.isNotEmpty) ...['--notes', notes],
      if (skipSynthesis) '--skip-synthesis',
    ];

    // Pass BOM by file if provided, else inline empty.
    if (bom.isNotEmpty) {
      // Orchestrator accepts --bom-file; write to a temp file so we don't have
      // to embed a multiline BOM in argv.
      final tmp = File('$projectRoot\\.pipeline_bom.tmp.csv');
      await tmp.writeAsString(bom, encoding: utf8);
      args.addAll(['--bom-file', tmp.path]);
    }

    final python = _resolvePython();

    Process process;
    try {
      process = await Process.start(
        python,
        args,
        workingDirectory: projectRoot,
      );
    } catch (e) {
      yield PipelineProgress.error('Could not start orchestrator: $e');
      return;
    }

    // Drain stdout/stderr in the background so the OS pipe doesn't block.
    final stdoutLines = <String>[];
    final stderrLines = <String>[];
    final stdoutSub = process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen(stdoutLines.add);
    final stderrSub = process.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen(stderrLines.add);

    // Poll progress file while process is alive.
    PipelineProgress? lastSnapshot;
    final exitCodeFuture = process.exitCode;
    int? exitCode;
    var done = false;

    Future<void> waitFor() async {
      exitCode = await exitCodeFuture;
      done = true;
    }

    final waiter = waitFor();

    while (!done) {
      if (progressFile.existsSync()) {
        try {
          final raw = await progressFile.readAsString();
          final snapshot = PipelineProgress.fromJson(jsonDecode(raw) as Map<String, dynamic>);
          if (snapshot != lastSnapshot) {
            lastSnapshot = snapshot;
            yield snapshot;
          }
        } catch (_) {
          // mid-write or malformed; ignore and retry
        }
      }
      await Future<void>.delayed(const Duration(milliseconds: 400));
    }

    await waiter;
    await stdoutSub.cancel();
    await stderrSub.cancel();

    // Emit final snapshot
    if (progressFile.existsSync()) {
      try {
        final raw = await progressFile.readAsString();
        final snapshot = PipelineProgress.fromJson(jsonDecode(raw) as Map<String, dynamic>);
        lastSnapshot = snapshot;
        yield snapshot;
      } catch (_) {}
    }

    if (exitCode == 0 || lastSnapshot?.status == 'awaiting_human' || lastSnapshot?.status == 'completed') {
      return;
    }
    yield PipelineProgress.error(
      'orchestrator exit=${exitCode ?? await process.exitCode}\nstderr tail: ${stderrLines.take(5).join("\n")}',
    );
  }

  String _resolvePython() {
    if (File(_kicadPython).existsSync()) return _kicadPython;
    return _systemPython;
  }
}

class PipelineProgress {
  PipelineProgress({
    required this.status,
    required this.currentPhase,
    required this.phases,
    this.finalArtifact,
    this.hitlBlocker,
    this.error,
  });

  factory PipelineProgress.fromJson(Map<String, dynamic> json) {
    return PipelineProgress(
      status: json['status'] as String? ?? 'unknown',
      currentPhase: json['current_phase'] as String?,
      phases: (json['phases'] as List? ?? [])
          .map((p) => PipelinePhase.fromJson(p as Map<String, dynamic>))
          .toList(),
      finalArtifact: json['final_artifact'] as String?,
      hitlBlocker: json['hitl_blocker'] as Map<String, dynamic>?,
    );
  }

  factory PipelineProgress.error(String msg) {
    return PipelineProgress(
      status: 'failed',
      currentPhase: null,
      phases: const [],
      error: msg,
    );
  }

  final String status;
  final String? currentPhase;
  final List<PipelinePhase> phases;
  final String? finalArtifact;
  final Map<String, dynamic>? hitlBlocker;
  final String? error;

  bool get isRunning => status == 'running';
  bool get isComplete => status == 'completed';
  bool get isAwaitingHuman => status == 'awaiting_human';
  bool get isFailed => status == 'failed';

  @override
  bool operator ==(Object other) =>
      other is PipelineProgress &&
      other.status == status &&
      other.currentPhase == currentPhase &&
      other.phases.length == phases.length &&
      other.finalArtifact == finalArtifact;

  @override
  int get hashCode => Object.hash(status, currentPhase, phases.length, finalArtifact);
}

class PipelinePhase {
  PipelinePhase({
    required this.name,
    required this.status,
    required this.durationSeconds,
    required this.repairAttempts,
    required this.notes,
  });

  factory PipelinePhase.fromJson(Map<String, dynamic> json) {
    return PipelinePhase(
      name: json['name'] as String? ?? '?',
      status: json['status'] as String? ?? 'unknown',
      durationSeconds: (json['duration_s'] as num? ?? 0).toDouble(),
      repairAttempts: json['repair_attempts'] as int? ?? 0,
      notes: json['notes'] as String? ?? '',
    );
  }

  final String name;
  final String status;
  final double durationSeconds;
  final int repairAttempts;
  final String notes;

  bool get isSuccess => status == 'success' || status == 'success_fallback';
  bool get isRunning => status == 'running';
  bool get isFailed => status == 'failed';
}
