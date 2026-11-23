import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'detection/yolo.dart';
import 'guides.dart' show apiBase;

/// Likely resin code: the number inside the recycling triangle.
class PlasticType {
  const PlasticType(this.number, this.type, {required this.certain});
  final int number;
  final String type;
  final bool certain;

  String get label => '#$number $type${certain ? '' : ' (likely)'}';
}

/// One box after the server's AI check: the detector box plus what Gemini sees in it.
class CheckedDetection {
  const CheckedDetection({
    required this.detection,
    this.itemName,
    this.aiChecked = false,
    this.plasticType,
    this.catalogCode,
  });

  final Detection detection;
  final String? itemName;
  final bool aiChecked;
  final PlasticType? plasticType;
  final String? catalogCode;

  /// "Plastic 1", "Plastic 2": numbered from the most confident, as on the website.
  int get number => detection.id + 1;
}

/// The server's answer to "does this photo contain plastic?" with per-box names.
class CheckedScan {
  const CheckedScan({
    required this.detections,
    required this.containsPlastic,
    required this.decidedByAi,
    required this.message,
    required this.removed,
    required this.plasticItems,
    required this.modelVersion,
    this.scanId,
  });

  final List<CheckedDetection> detections;
  final bool containsPlastic;
  final bool decidedByAi;
  final String message;
  final List<String> removed;
  final List<String> plasticItems;
  final String modelVersion;
  final String? scanId;

  static CheckedScan fromJson(Map<String, dynamic> json, List<String> classes) {
    final verdict = json['verdict'] as Map<String, dynamic>?;
    final detections = <CheckedDetection>[];
    for (final raw in (json['detections'] as List).cast<Map<String, dynamic>>()) {
      final box = raw['box'] as Map<String, dynamic>;
      final type = raw['plastic_type'] as Map<String, dynamic>?;
      detections.add(CheckedDetection(
        detection: Detection(
          id: raw['id'] as int,
          classId: classes.indexOf(raw['class_name'] as String),
          confidence: (raw['confidence'] as num).toDouble(),
          box: NormBox(
            (box['x1'] as num).toDouble(),
            (box['y1'] as num).toDouble(),
            (box['x2'] as num).toDouble(),
            (box['y2'] as num).toDouble(),
          ),
        ),
        itemName: raw['item_name'] as String?,
        aiChecked: raw['ai_checked'] as bool? ?? false,
        plasticType: type == null
            ? null
            : PlasticType(type['number'] as int, type['type'] as String, certain: type['certain'] as bool? ?? false),
        catalogCode: raw['catalog_code'] as String?,
      ));
    }
    return CheckedScan(
      detections: [for (final d in detections) if (d.detection.classId >= 0) d],
      containsPlastic: verdict?['contains_plastic'] as bool? ?? detections.isNotEmpty,
      decidedByAi: verdict?['decided_by'] == 'gemini',
      message: verdict?['message'] as String? ?? '',
      removed: ((json['ai_removed'] as List?) ?? const []).cast<String>(),
      plasticItems: ((verdict?['plastic_items'] as List?) ?? const []).cast<String>(),
      modelVersion: (json['model'] as Map<String, dynamic>)['version'] as String,
      scanId: json['scan_id'] as String?,
    );
  }
}

/// The website's AI check, used by the app when an EcoRevive server is configured and online.
/// Detection itself always runs on the phone first; this only adds names, plastic types and the
/// Gemini verdict. It never throws: when the server cannot help it returns null.
class VisionService {
  VisionService({http.Client? client, this.baseUrl = apiBase, String? clientId})
      : _client = client ?? http.Client(),
        clientId = clientId ?? _newId();

  final http.Client _client;
  final String baseUrl;

  /// Anonymous id for this app session; feedback is grouped by it, never linked to a person.
  final String clientId;

  bool get enabled => baseUrl.isNotEmpty;

  static String _newId() => 'app-${List.generate(20, (_) => Random.secure().nextInt(36).toRadixString(36)).join()}';

  Future<CheckedScan?> check(Uint8List jpeg, List<String> classes) async {
    if (!enabled) return null;
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/v1/detect?verify=true'),
            headers: {'Content-Type': 'image/jpeg', 'X-Client-Id': clientId},
            body: jpeg,
          )
          .timeout(const Duration(seconds: 25));
      if (response.statusCode != 200) return null;
      return CheckedScan.fromJson(jsonDecode(response.body) as Map<String, dynamic>, classes);
    } catch (_) {
      return null;
    }
  }

  /// "Was it right?" for the adaptive learning loop. The app never shares the photo.
  Future<bool> sendFeedback(CheckedDetection item, {required bool correct, required String modelVersion}) async {
    if (!enabled) return false;
    final box = item.detection.box;
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/v1/feedback'),
            headers: {'Content-Type': 'application/json', 'X-Client-Id': clientId},
            body: jsonEncode({
              'correct': correct,
              'class_name': 'Plastic',
              'confidence': item.detection.confidence,
              'box': {'x1': box.x1, 'y1': box.y1, 'x2': box.x2, 'y2': box.y2},
              'model_version': modelVersion,
              'item_name': item.itemName,
              'share_photo': false,
            }),
          )
          .timeout(const Duration(seconds: 15));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}
