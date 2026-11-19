import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

import 'shared_data.dart';

/// Same contract as the web client: POST /v1/guides on the EcoRevive backend.
const apiBase = String.fromEnvironment('API_BASE');

class Guide {
  Guide({
    required this.className,
    required this.kind,
    required this.title,
    required this.materials,
    required this.steps,
    required this.precautions,
    required this.source,
    required this.sourceDetail,
    required this.safetyNotice,
  });

  factory Guide.fromJson(Map<String, dynamic> json) => Guide(
        className: json['class_name'] as String,
        kind: json['kind'] as String,
        title: json['title'] as String,
        materials: (json['materials'] as List).cast<String>(),
        steps: (json['steps'] as List).cast<String>(),
        precautions: (json['precautions'] as List).cast<String>(),
        source: json['source'] as String,
        sourceDetail: json['source_detail'] as String,
        safetyNotice: json['safety_notice'] as String,
      );

  final String className;
  final String kind;
  final String title;
  final List<String> materials;
  final List<String> steps;
  final List<String> precautions;
  final String source;
  final String sourceDetail;
  final String safetyNotice;

  bool get isDisposal => kind == 'disposal';
}

class GuideService {
  GuideService(this.shared, {http.Client? client, this.baseUrl = apiBase})
      : _client = client ?? http.Client();

  final SharedData shared;
  final http.Client _client;
  final String baseUrl;

  Guide curated(String className, String detail) {
    final data = shared.curated['guides'][className] as Map<String, dynamic>;
    final mandatory = (shared.curated['mandatory_precautions'][className] as List).cast<String>();
    return Guide(
      className: className,
      kind: data['kind'] as String,
      title: data['title'] as String,
      materials: (data['materials'] as List).cast<String>(),
      steps: (data['steps'] as List).cast<String>(),
      precautions: [...mandatory, ...(data['precautions'] as List).cast<String>()],
      source: 'curated',
      sourceDetail: detail,
      safetyNotice: shared.curated['safety_notice'] as String,
    );
  }

  /// Hazardous items never leave the device: they always get the curated disposal guide.
  Future<Guide> fetch(String className, double confidence, {required bool confirmed}) async {
    if (className == 'Hazardous') {
      return curated(className, 'Hazardous items always get team-written safety guidance.');
    }
    if (baseUrl.isEmpty) {
      return curated(className, 'Offline guide. No EcoRevive server is configured in this build.');
    }
    final key = List.generate(24, (_) => Random.secure().nextInt(36).toRadixString(36)).join();
    final body = jsonEncode({'class_name': className, 'confidence': confidence, 'confirmed_by_user': confirmed});
    for (var attempt = 0; attempt < 2; attempt++) {
      try {
        final response = await _client
            .post(
              Uri.parse('$baseUrl/v1/guides'),
              headers: {'Content-Type': 'application/json', 'Idempotency-Key': key},
              body: body,
            )
            .timeout(const Duration(seconds: 20));
        if (response.statusCode == 200) {
          return Guide.fromJson((jsonDecode(response.body) as Map<String, dynamic>)['guide'] as Map<String, dynamic>);
        }
        final retryable = response.statusCode == 429 || response.statusCode >= 500;
        if (!retryable || attempt == 1) break;
      } on TimeoutException {
        if (attempt == 1) break;
      } on http.ClientException {
        if (attempt == 1) break;
      }
      await Future<void>.delayed(const Duration(seconds: 1));
    }
    return curated(className, 'Offline guide. The EcoRevive server could not be reached.');
  }
}
