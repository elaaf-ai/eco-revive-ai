import 'dart:io';
import 'dart:typed_data';

import 'package:eco_revive_app/detection/pipeline.dart';
import 'package:eco_revive_app/detection/yolo.dart';
import 'package:eco_revive_app/guides.dart';
import 'package:eco_revive_app/shared_data.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;

const classes = 5;
const anchors = 8;

/// Builds an output in [1, 9, anchors] layout, matching the backend fixture model.
List<double> channelsFirst(List<List<double>> perAnchor) {
  final out = List<double>.filled((4 + classes) * anchors, 0);
  for (var a = 0; a < perAnchor.length; a++) {
    for (var c = 0; c < perAnchor[a].length; c++) {
      out[c * anchors + a] = perAnchor[a][c];
    }
  }
  return out;
}

void main() {
  final lb = Letterbox.fit(1280, 640, 640);

  test('letterbox matches the backend geometry', () {
    expect(lb.scale, 0.5);
    expect([lb.padX, lb.padY], [0, 160]);
    final portrait = Letterbox.fit(480, 640, 640);
    expect([portrait.padX, portrait.padY], [80, 0]);
  });

  test('decodes pixel-space boxes, applies NMS and maps to the source image', () {
    final output = channelsFirst([
      [320, 320, 200, 100, 0.9, 0, 0, 0, 0],
      [322, 321, 198, 102, 0.8, 0, 0, 0, 0],
      [100, 250, 60, 60, 0, 0, 0, 0, 0.6],
      [500, 400, 50, 50, 0, 0, 0.1, 0, 0],
    ]);
    final detections = decodeYolo(output: output, shape: const [1, 9, anchors], numClasses: classes, letterbox: lb);
    expect(detections.map((d) => d.classId), [0, 4]);
    final box = detections.first.box;
    expect(box.x1, closeTo(440 / 1280, 1e-6));
    expect(box.y1, closeTo(220 / 640, 1e-6));
    expect(box.x2, closeTo(840 / 1280, 1e-6));
    expect(box.y2, closeTo(420 / 640, 1e-6));
  });

  test('decodes normalised TFLite boxes to the same result', () {
    final output = channelsFirst([
      [0.5, 0.5, 200 / 640, 100 / 640, 0.9, 0, 0, 0, 0],
    ]);
    final detections = decodeYolo(output: output, shape: const [1, 9, anchors], numClasses: classes, letterbox: lb);
    expect(detections.single.box.x1, closeTo(440 / 1280, 1e-6));
  });

  test('accepts the transposed [1, N, 4 + C] layout', () {
    final row = <double>[320, 320, 200, 100, 0, 0, 0.7, 0, 0];
    final output = [...row, ...List<double>.filled(9 * (anchors - 1), 0)];
    final detections = decodeYolo(output: output, shape: const [1, anchors, 9], numClasses: classes, letterbox: lb);
    expect(detections.single.classId, 2);
  });

  test('rejects outputs for a different class count', () {
    expect(
      () => decodeYolo(output: List.filled(8 * 4, 0), shape: const [1, 8, 4], numClasses: classes, letterbox: lb),
      throwsArgumentError,
    );
  });

  test('scan quality flags empty, uncertain and ambiguous results', () {
    const box = NormBox(0.1, 0.1, 0.5, 0.5);
    expect(assessScan(const []), ScanQuality.noDetections);
    expect(assessScan(const [Detection(id: 0, classId: 0, confidence: 0.3, box: box)]), ScanQuality.lowConfidence);
    expect(
      assessScan(const [
        Detection(id: 0, classId: 0, confidence: 0.8, box: box),
        Detection(id: 1, classId: 1, confidence: 0.75, box: box),
      ]),
      ScanQuality.ambiguous,
    );
    expect(assessScan(const [Detection(id: 0, classId: 0, confidence: 0.9, box: box)]), ScanQuality.ok);
  });

  test('preprocessing bakes EXIF rotation and fills padding', () {
    final source = img.Image(width: 40, height: 20);
    img.fill(source, color: img.ColorRgb8(255, 0, 0));
    source.exif.imageIfd['Orientation'] = 6;
    final upright = decodeUpright(Uint8List.fromList(img.encodeJpg(source)))!;
    expect([upright.width, upright.height], [20, 40]);

    final tensor = letterboxTensor(upright, Letterbox.fit(upright.width, upright.height, 64));
    expect(tensor.length, 64 * 64 * 3);
    expect(tensor[0], closeTo(114 / 255, 1e-6)); // left padding
    final centre = (32 * 64 + 32) * 3;
    expect(tensor[centre], greaterThan(0.9)); // red channel of the photo

    // The exported TFLite model is NCHW: three full planes, red first.
    final chw = letterboxTensor(upright, Letterbox.fit(upright.width, upright.height, 64), channelsFirst: true);
    const plane = 64 * 64;
    expect(chw[0], closeTo(114 / 255, 1e-6));
    expect(chw[32 * 64 + 32], greaterThan(0.9)); // red plane
    expect(chw[plane + 32 * 64 + 32], lessThan(0.1)); // green plane
    expect(chw[2 * plane + 32 * 64 + 32], lessThan(0.1)); // blue plane
  });

  group('shared data', () {
    final shared = SharedData.fromJson(
      File('assets/shared/classes.json').readAsStringSync(),
      File('assets/shared/curated_guides.json').readAsStringSync(),
    );

    test('bundled copies match the repository source of truth', () {
      expect(File('assets/shared/classes.json').readAsStringSync(), File('../shared/classes.json').readAsStringSync());
      expect(
        File('assets/shared/curated_guides.json').readAsStringSync(),
        File('../shared/curated_guides.json').readAsStringSync(),
      );
      expect(shared.classes, ['Plastic', 'Glass', 'Metal', 'Organic', 'Hazardous']);
    });

    test('hazardous guidance is curated disposal and never calls the server', () async {
      final service = GuideService(shared, baseUrl: 'http://example.invalid');
      final guide = await service.fetch('Hazardous', 0.95, confirmed: false);
      expect(guide.isDisposal, isTrue);
      expect(guide.source, 'curated');
    });

    test('glass guide always carries the broken-glass precaution', () async {
      final guide = await GuideService(shared, baseUrl: '').fetch('Glass', 0.9, confirmed: false);
      expect(guide.precautions.first, contains('chipped'));
      expect(guide.sourceDetail, contains('Offline'));
    });
  });
}
