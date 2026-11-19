// On-device check of the bundled TFLite model: loads it through the app's own code path,
// scans a held-out photo and prints the detections for comparison with the server's ONNX model.
// Run: dart run tool/make_test_image.dart <jpg> && flutter test integration_test/model_test.dart -d <device>
import 'dart:convert';

import 'package:eco_revive_app/detection/detector.dart';
import 'package:eco_revive_app/detection/yolo.dart';
import 'package:eco_revive_app/shared_data.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'test_image.g.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('bundled TFLite model detects waste in a held-out photo', (tester) async {
    final shared = await SharedData.load();
    final detector = await WasteDetector.load(shared);
    expect(detector.inputSize, 640);
    expect(detector.outputShape, [1, 4 + shared.classes.length, 8400]);

    final result = await detector.scan(base64Decode(testImageBase64), shared.classes.length);
    final rows = [
      for (final d in result.detections)
        {
          'class': shared.classes[d.classId],
          'confidence': double.parse(d.confidence.toStringAsFixed(3)),
          'box': [d.box.x1, d.box.y1, d.box.x2, d.box.y2].map((v) => double.parse(v.toStringAsFixed(3))).toList(),
        },
    ];
    // ignore: avoid_print
    print('TFLITE_RESULT ${jsonEncode({
      'image': testImageName,
      'version': detector.version,
      'size': [result.width, result.height],
      'inference_ms': result.inferenceMs,
      'quality': assessScan(result.detections).name,
      'detections': rows,
    })}');
    expect(result.detections, isNotEmpty);
    detector.close();
  });
}
