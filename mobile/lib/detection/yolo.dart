/// Pure-Dart YOLO post-processing shared by the TFLite pipeline and tests.
///
/// Handles Ultralytics detection outputs shaped [1, 4 + C, N] (default export) or
/// [1, N, 4 + C], with box centres in input pixels or normalised to 0..1 (TFLite exports
/// are normalised). Results are mapped back to normalised coordinates of the source image.
library;

import 'dart:math' as math;

class Letterbox {
  const Letterbox(this.scale, this.padX, this.padY, this.sourceWidth, this.sourceHeight, this.size);

  /// Same geometry as backend/app/imaging.py: scale to fit, centre with grey padding.
  factory Letterbox.fit(int sourceWidth, int sourceHeight, int size) {
    final scale = math.min(size / sourceWidth, size / sourceHeight);
    final newW = (sourceWidth * scale).round();
    final newH = (sourceHeight * scale).round();
    return Letterbox(scale, (size - newW) ~/ 2, (size - newH) ~/ 2, sourceWidth, sourceHeight, size);
  }

  final double scale;
  final int padX;
  final int padY;
  final int sourceWidth;
  final int sourceHeight;
  final int size;

  int get scaledWidth => (sourceWidth * scale).round();
  int get scaledHeight => (sourceHeight * scale).round();
}

class NormBox {
  const NormBox(this.x1, this.y1, this.x2, this.y2);
  final double x1;
  final double y1;
  final double x2;
  final double y2;

  double get area => math.max(0, x2 - x1) * math.max(0, y2 - y1);

  @override
  String toString() => 'NormBox($x1, $y1, $x2, $y2)';
}

class Detection {
  const Detection({required this.id, required this.classId, required this.confidence, required this.box});
  final int id;
  final int classId;
  final double confidence;
  final NormBox box;
}

double iou(NormBox a, NormBox b) {
  final x1 = math.max(a.x1, b.x1);
  final y1 = math.max(a.y1, b.y1);
  final x2 = math.min(a.x2, b.x2);
  final y2 = math.min(a.y2, b.y2);
  final inter = math.max(0.0, x2 - x1) * math.max(0.0, y2 - y1);
  final union = a.area + b.area - inter;
  return union <= 0 ? 0 : inter / union;
}

/// Decodes a flat output buffer. [shape] is the output tensor shape.
List<Detection> decodeYolo({
  required List<double> output,
  required List<int> shape,
  required int numClasses,
  required Letterbox letterbox,
  double confThreshold = 0.25,
  double iouThreshold = 0.45,
  int maxDetections = 20,
}) {
  if (shape.length != 3 || shape[0] != 1) {
    throw ArgumentError('Unexpected output shape $shape');
  }
  final channels = 4 + numClasses;
  final bool channelsFirst;
  final int anchors;
  if (shape[1] == channels) {
    channelsFirst = true;
    anchors = shape[2];
  } else if (shape[2] == channels) {
    channelsFirst = false;
    anchors = shape[1];
  } else {
    throw ArgumentError('Output shape $shape does not match $numClasses classes');
  }
  double at(int anchor, int channel) =>
      channelsFirst ? output[channel * anchors + anchor] : output[anchor * channels + channel];

  // Normalised exports have all box coordinates within about 0..1.
  var maxCoord = 0.0;
  for (var a = 0; a < anchors; a++) {
    maxCoord = math.max(maxCoord, math.max(at(a, 0), at(a, 1)));
  }
  final coordScale = maxCoord <= 1.5 ? letterbox.size.toDouble() : 1.0;

  final candidates = <({int cls, double score, NormBox box})>[];
  for (var a = 0; a < anchors; a++) {
    var best = 0;
    var bestScore = at(a, 4);
    for (var c = 1; c < numClasses; c++) {
      final s = at(a, 4 + c);
      if (s > bestScore) {
        bestScore = s;
        best = c;
      }
    }
    if (bestScore < confThreshold) continue;
    final cx = at(a, 0) * coordScale;
    final cy = at(a, 1) * coordScale;
    final w = at(a, 2) * coordScale;
    final h = at(a, 3) * coordScale;
    final box = _toSource(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, letterbox);
    if (box.x2 - box.x1 < 1e-3 || box.y2 - box.y1 < 1e-3) continue;
    candidates.add((cls: best, score: bestScore, box: box));
  }

  candidates.sort((a, b) => b.score.compareTo(a.score));
  final kept = <({int cls, double score, NormBox box})>[];
  for (final candidate in candidates) {
    final suppressed = kept.any((k) => k.cls == candidate.cls && iou(k.box, candidate.box) > iouThreshold);
    if (!suppressed) kept.add(candidate);
    if (kept.length == maxDetections) break;
  }
  return [
    for (var i = 0; i < kept.length; i++)
      Detection(id: i, classId: kept[i].cls, confidence: kept[i].score, box: kept[i].box),
  ];
}

NormBox _toSource(double x1, double y1, double x2, double y2, Letterbox lb) {
  double clamp(double v) => v.clamp(0.0, 1.0);
  return NormBox(
    clamp((x1 - lb.padX) / lb.scale / lb.sourceWidth),
    clamp((y1 - lb.padY) / lb.scale / lb.sourceHeight),
    clamp((x2 - lb.padX) / lb.scale / lb.sourceWidth),
    clamp((y2 - lb.padY) / lb.scale / lb.sourceHeight),
  );
}

enum ScanQuality { ok, noDetections, lowConfidence, ambiguous }

/// Mirrors the backend's assess(): flags scans that need a retake or confirmation.
/// [competitors] may include hidden classes, so an overlapping, equally likely box of another
/// class still makes the scan ambiguous.
ScanQuality assessScan(List<Detection> detections, {double lowConfidence = 0.5, List<Detection>? competitors}) {
  if (detections.isEmpty) return ScanQuality.noDetections;
  final ranked = [...detections]..sort((a, b) => b.confidence.compareTo(a.confidence));
  final top = ranked.first;
  for (final other in competitors ?? ranked.skip(1)) {
    if (identical(other, top)) continue;
    if (other.classId != top.classId && iou(top.box, other.box) > 0.6 && top.confidence - other.confidence < 0.15) {
      return ScanQuality.ambiguous;
    }
  }
  return top.confidence < lowConfidence ? ScanQuality.lowConfidence : ScanQuality.ok;
}
