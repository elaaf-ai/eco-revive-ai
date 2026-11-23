import 'package:flutter/material.dart';

import 'detection/detector.dart';
import 'guides.dart';
import 'screens/home_screen.dart';
import 'shared_data.dart';
import 'theme.dart';
import 'vision.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const EcoReviveApp());
}

/// Loads shared data and the on-device model once, then exposes them to the screens.
class AppServices {
  AppServices(this.shared, this.guides, this.detector, this.modelError, {VisionService? vision})
      : vision = vision ?? VisionService();
  final SharedData shared;
  final GuideService guides;
  final VisionService vision;
  final WasteDetector? detector;
  final String? modelError;

  static Future<AppServices> load() async {
    final shared = await SharedData.load();
    WasteDetector? detector;
    String? error;
    try {
      detector = await WasteDetector.load(shared);
    } on ModelUnavailable catch (e) {
      error = e.message;
    }
    return AppServices(shared, GuideService(shared), detector, error);
  }
}

class EcoReviveApp extends StatefulWidget {
  const EcoReviveApp({super.key, this.services});
  final Future<AppServices>? services;

  @override
  State<EcoReviveApp> createState() => _EcoReviveAppState();
}

class _EcoReviveAppState extends State<EcoReviveApp> {
  late final Future<AppServices> _services = widget.services ?? AppServices.load();

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'EcoRevive',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: FutureBuilder<AppServices>(
        future: _services,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Scaffold(body: Center(child: Text('EcoRevive could not start: ${snapshot.error}')));
          }
          if (!snapshot.hasData) {
            return const Scaffold(body: Center(child: CircularProgressIndicator()));
          }
          return HomeScreen(services: snapshot.data!);
        },
      ),
    );
  }
}
