// Regression tests for the QA bug report of 2026-11-20 (mobile items B-15 and B-18).
import 'dart:io';

import 'package:eco_revive_app/detection/yolo.dart';
import 'package:eco_revive_app/guides.dart';
import 'package:eco_revive_app/shared_data.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

SharedData loadShared() => SharedData.fromJson(
      File('assets/shared/classes.json').readAsStringSync(),
      File('assets/shared/curated_guides.json').readAsStringSync(),
      productJson: File('assets/shared/product.json').readAsStringSync(),
    );

void main() {
  test('B-18: enabled classes come from the shared product file and match the repository copy', () {
    expect(File('assets/shared/product.json').readAsStringSync(), File('../shared/product.json').readAsStringSync());
    expect(loadShared().enabledClasses, ['Plastic']);
  });

  test('B-18: a 4xx reply shows the server reason, not "offline"', () async {
    final client = MockClient((_) async => http.Response(
          '{"error":{"code":"class_not_enabled","message":"This app only gives guides for: Plastic."}}',
          422,
        ));
    final guide = await GuideService(loadShared(), client: client, baseUrl: 'https://example.test')
        .fetch('Metal', 0.9, confirmed: false);
    expect(guide.source, 'curated');
    expect(guide.sourceDetail, contains('only gives guides for: Plastic'));
    expect(guide.sourceDetail, isNot(contains('could not be reached')));
  });

  test('B-15: a malformed 200 reply becomes a labelled fallback instead of an error', () async {
    final client = MockClient((_) async => http.Response('{"not": "a guide"}', 200));
    final guide = await GuideService(loadShared(), client: client, baseUrl: 'https://example.test')
        .fetch('Plastic', 0.9, confirmed: false);
    expect(guide.source, 'curated');
    expect(guide.steps, hasLength(3));
  });

  test('B-15: a transport error becomes a labelled fallback', () async {
    final client = MockClient((_) async => throw const SocketException('TLS handshake failed'));
    final guide = await GuideService(loadShared(), client: client, baseUrl: 'https://example.test')
        .fetch('Plastic', 0.9, confirmed: false);
    expect(guide.source, 'curated');
  });

  test('B-18: a shown plastic box overlapping an equally likely hidden metal box is ambiguous', () {
    const box = NormBox(0.1, 0.1, 0.5, 0.5);
    const plastic = Detection(id: 0, classId: 0, confidence: 0.82, box: box);
    const metal = Detection(id: 1, classId: 2, confidence: 0.80, box: box);
    expect(assessScan(const [plastic], competitors: const [plastic, metal]), ScanQuality.ambiguous);
    expect(assessScan(const [plastic]), ScanQuality.ok);
  });
}
