import 'dart:convert';

import 'package:flutter/services.dart';

/// Copies of shared/classes.json and shared/curated_guides.json, checked by a test.
class SharedData {
  SharedData({required this.classes, required this.curated});

  final List<String> classes;
  final Map<String, dynamic> curated;

  static Future<SharedData> load([AssetBundle? bundle]) async {
    final assets = bundle ?? rootBundle;
    return SharedData.fromJson(
      await assets.loadString('assets/shared/classes.json'),
      await assets.loadString('assets/shared/curated_guides.json'),
    );
  }

  factory SharedData.fromJson(String classesJson, String curatedJson) {
    final classes = (jsonDecode(classesJson)['classes'] as List).cast<Map<String, dynamic>>()
      ..sort((a, b) => (a['id'] as int).compareTo(b['id'] as int));
    return SharedData(
      classes: [for (final c in classes) c['name'] as String],
      curated: jsonDecode(curatedJson) as Map<String, dynamic>,
    );
  }
}
