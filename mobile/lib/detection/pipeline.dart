import 'dart:isolate';
import 'dart:typed_data';

import 'package:image/image.dart' as img;
import 'package:tflite_flutter/tflite_flutter.dart';

import 'yolo.dart';

const padValue = 114;

class ScanResult {
  ScanResult({
    required this.detections,
    required this.width,
    required this.height,
    required this.jpeg,
    required this.inferenceMs,
  });
  final List<Detection> detections;
  final int width;
  final int height;

  /// Upright, metadata-free copy of the photo that the boxes refer to.
  final Uint8List jpeg;
  final int inferenceMs;
}

/// Decode, apply EXIF rotation, and drop metadata. Returns null for unreadable data.
img.Image? decodeUpright(Uint8List bytes) {
  final decoded = img.decodeImage(bytes);
  if (decoded == null) return null;
  final upright = img.bakeOrientation(decoded);
  upright.exif = img.ExifData();
  return upright;
}

/// Letterbox to size x size as float32 in 0..1. [channelsFirst] gives NCHW ([1, 3, H, W], what this
/// project's Ultralytics TFLite export uses); otherwise NHWC ([1, H, W, 3]).
Float32List letterboxTensor(img.Image source, Letterbox lb, {bool channelsFirst = false}) {
  final resized = img.copyResize(
    source,
    width: lb.scaledWidth,
    height: lb.scaledHeight,
    interpolation: img.Interpolation.linear,
  );
  final size = lb.size;
  final tensor = Float32List(size * size * 3)..fillRange(0, size * size * 3, padValue / 255.0);
  for (var y = 0; y < resized.height; y++) {
    final row = (y + lb.padY) * size;
    for (var x = 0; x < resized.width; x++) {
      final pixel = resized.getPixel(x, y);
      final index = row + x + lb.padX;
      if (channelsFirst) {
        final plane = size * size;
        tensor[index] = pixel.r / 255.0;
        tensor[plane + index] = pixel.g / 255.0;
        tensor[2 * plane + index] = pixel.b / 255.0;
      } else {
        final offset = index * 3;
        tensor[offset] = pixel.r / 255.0;
        tensor[offset + 1] = pixel.g / 255.0;
        tensor[offset + 2] = pixel.b / 255.0;
      }
    }
  }
  return tensor;
}

/// Runs the whole pipeline off the UI thread on an interpreter created in the main isolate.
Future<ScanResult> runScan({
  required int interpreterAddress,
  required Uint8List photo,
  required int inputSize,
  required List<int> outputShape,
  bool channelsFirst = false,
  required int numClasses,
  double confThreshold = 0.25,
}) {
  return Isolate.run(() {
    final image = decodeUpright(photo);
    if (image == null) throw const FormatException('The photo could not be read.');
    final lb = Letterbox.fit(image.width, image.height, inputSize);
    final input = letterboxTensor(image, lb, channelsFirst: channelsFirst);
    final outputLength = outputShape.reduce((a, b) => a * b);
    final output = Float32List(outputLength);

    final interpreter = Interpreter.fromAddress(interpreterAddress);
    final started = DateTime.now();
    interpreter.run(input.buffer, output.buffer);
    final elapsed = DateTime.now().difference(started).inMilliseconds;

    final detections = decodeYolo(
      output: output,
      shape: outputShape,
      numClasses: numClasses,
      letterbox: lb,
      confThreshold: confThreshold,
    );
    final jpeg = Uint8List.fromList(img.encodeJpg(image, quality: 88));
    return ScanResult(
      detections: detections,
      width: image.width,
      height: image.height,
      jpeg: jpeg,
      inferenceMs: elapsed,
    );
  });
}
