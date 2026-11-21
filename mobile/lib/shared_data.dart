import 'dart:convert';

import 'package:flutter/services.dart';

/// Copies of shared/classes.json and shared/curated_guides.json, checked by a test.
class SharedData {
  SharedData({required this.classes, required this.curated, List<String>? enabledClasses})
      : enabledClasses = enabledClasses ?? classes;

  final List<String> classes;

  /// Classes the product shows (shared/product.json). Detections of other classes are hidden.
  final List<String> enabledClasses;
  final Map<String, dynamic> curated;

  static Future<SharedData> load([AssetBundle? bundle]) async {
    final assets = bundle ?? rootBundle;
    return SharedData.fromJson(
      await assets.loadString('assets/shared/classes.json'),
      await assets.loadString('assets/shared/curated_guides.json'),
      productJson: await assets.loadString('assets/shared/product.json'),
    );
  }

  factory SharedData.fromJson(String classesJson, String curatedJson, {String? productJson}) {
    final classes = (jsonDecode(classesJson)['classes'] as List).cast<Map<String, dynamic>>()
      ..sort((a, b) => (a['id'] as int).compareTo(b['id'] as int));
    final names = [for (final c in classes) c['name'] as String];
    final enabled = productJson == null
        ? names
        : ((jsonDecode(productJson) as Map<String, dynamic>)['enabled_classes'] as List).cast<String>();
    return SharedData(
      classes: names,
      curated: jsonDecode(curatedJson) as Map<String, dynamic>,
      enabledClasses: enabled.where(names.contains).toList(),
    );
  }
}
