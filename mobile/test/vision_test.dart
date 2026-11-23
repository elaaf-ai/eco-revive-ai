import 'dart:convert';
import 'dart:typed_data';

import 'package:eco_revive_app/guides.dart';
import 'package:eco_revive_app/shared_data.dart';
import 'package:eco_revive_app/vision.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const classes = ['Plastic', 'Glass', 'Metal', 'Organic', 'Hazardous'];

Map<String, dynamic> serverScan() => {
      'model': {'version': '0.2.0-preview-small'},
      'scan_id': null,
      'verdict': {
        'contains_plastic': true,
        'decided_by': 'gemini',
        'message': 'Plastic confirmed by the AI check: plastic cup.',
        'plastic_items': ['plastic cup'],
      },
      'detections': [
        {
          'id': 0,
          'class_name': 'Plastic',
          'confidence': 0.52,
          'box': {'x1': 0.1, 'y1': 0.1, 'x2': 0.5, 'y2': 0.6},
          'item_name': 'plastic cup',
          'ai_checked': true,
          'plastic_type': {'number': 1, 'type': 'PET', 'certain': false, 'source': 'gemini'},
          'catalog_code': '010',
        },
      ],
      'ai_removed': ['person', 'wall'],
    };

void main() {
  final jpeg = Uint8List.fromList([0xff, 0xd8, 0xff, 0xd9]);

  test('reads the AI check: names, plastic type, removed boxes', () async {
    late http.Request sent;
    final service = VisionService(
      baseUrl: 'https://example.test',
      clientId: 'app-test-0001',
      client: MockClient((request) async {
        sent = request;
        return http.Response(jsonEncode(serverScan()), 200);
      }),
    );
    final scan = (await service.check(jpeg, classes))!;
    expect(sent.url.toString(), 'https://example.test/v1/detect?verify=true');
    expect(sent.headers['X-Client-Id'], 'app-test-0001');
    expect(scan.containsPlastic, isTrue);
    expect(scan.decidedByAi, isTrue);
    expect(scan.removed, ['person', 'wall']);
    final cup = scan.detections.single;
    expect(cup.number, 1);
    expect(cup.itemName, 'plastic cup');
    expect(cup.aiChecked, isTrue);
    expect(cup.plasticType!.label, '#1 PET (likely)');
    expect(cup.catalogCode, '010');
  });

  test('server errors and no server both fall back to the phone result', () async {
    final failing = VisionService(baseUrl: 'https://example.test', client: MockClient((_) async => http.Response('', 503)));
    expect(await failing.check(jpeg, classes), isNull);
    final offline = VisionService(baseUrl: '');
    expect(offline.enabled, isFalse);
    expect(await offline.check(jpeg, classes), isNull);
  });

  test('feedback never shares the photo from the app', () async {
    late Map<String, dynamic> body;
    final service = VisionService(
      baseUrl: 'https://example.test',
      client: MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(jsonEncode({'id': 'f1', 'photo_saved': false}), 200);
      }),
    );
    final scan = CheckedScan.fromJson(serverScan(), classes);
    expect(await service.sendFeedback(scan.detections.single, correct: false, modelVersion: scan.modelVersion), isTrue);
    expect(body['correct'], isFalse);
    expect(body['share_photo'], isFalse);
    expect(body.containsKey('image'), isFalse);
    expect(body['item_name'], 'plastic cup');
  });

  test('guides are requested for the named item', () async {
    late Map<String, dynamic> body;
    final shared = SharedData.fromJson('{"classes":[{"id":0,"name":"Plastic"}]}', '{"guides":{},"mandatory_precautions":{},"safety_notice":""}');
    final guides = GuideService(
      shared,
      baseUrl: 'https://example.test',
      client: MockClient((request) async {
        body = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
            jsonEncode({
              'guide': {
                'class_name': 'Plastic', 'kind': 'upcycle', 'title': 'Cup seed starter', 'materials': ['cup'],
                'steps': ['a', 'b', 'c'], 'precautions': [], 'source': 'gemini', 'source_detail': 'x', 'safety_notice': 'y',
              },
            }),
            200);
      }),
    );
    final guide = await guides.fetch('Plastic', 0.52, confirmed: true, itemHint: 'plastic cup');
    expect(body['item_hint'], 'plastic cup');
    expect(guide.title, 'Cup seed starter');
  });
}
