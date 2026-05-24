import 'package:flutter/material.dart';

import 'omnicircuit_dashboard.dart';

void main() {
  runApp(const OmniCircuitApp());
}

class OmniCircuitApp extends StatelessWidget {
  const OmniCircuitApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'OmniCircuit AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1F7A6D),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF5F7F9),
      ),
      home: const OmniCircuitDashboard(),
    );
  }
}
