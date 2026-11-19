import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:tflite_flutter/tflite_flutter.dart';

import '../shared_data.dart';
import 'pipeline.dart';

const modelAsset = 'assets/model/model.tflite';
const manifestAsset = 'assets/model/manifest.json';

class ModelUnavailable implements Exception {
  ModelUnavailable(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Loads the bundled TFLite model once and verifies it matches the canonical classes.
class WasteDetector {
  WasteDetector._(this._interpreter, this.version, this.status, this.inputSize, this.outputShape);

  final Interpreter _interpreter;
  final String version;
  final String status;
  final int inputSize;
  final List<int> outputShape;

  static Future<WasteDetector> load(SharedData shared) async {
    final Map<String, dynamic> manifest;
    try {
      manifest = jsonDecode(await rootBundle.loadString(manifestAsset)) as Map<String, dynamic>;
    } catch (_) {
      throw ModelUnavailable('No model is bundled in this build. See mobile/README.md to add one.');
    }
    final classes = (manifest['classes'] as List).cast<String>();
    if (classes.join(',') != shared.classes.join(',')) {
      throw ModelUnavailable('The bundled model has classes $classes, expected ${shared.classes}.');
    }

    final Interpreter interpreter;
    try {
      interpreter = await Interpreter.fromAsset(modelAsset, options: InterpreterOptions()..threads = 4);
    } catch (error) {
      throw ModelUnavailable('The model file could not be loaded: $error');
    }
    final inputShape = interpreter.getInputTensor(0).shape;
    final outputShape = interpreter.getOutputTensor(0).shape;
    if (inputShape.length != 4 || inputShape[3] != 3 || inputShape[1] != inputShape[2]) {
      interpreter.close();
      throw ModelUnavailable('Unexpected model input shape $inputShape.');
    }
    return WasteDetector._(
      interpreter,
      manifest['version'] as String? ?? 'unknown',
      manifest['status'] as String? ?? 'preview',
      inputShape[1],
      outputShape,
    );
  }

  Future<ScanResult> scan(Uint8List photo, int numClasses) => runScan(
        interpreterAddress: _interpreter.address,
        photo: photo,
        inputSize: inputSize,
        outputShape: outputShape,
        numClasses: numClasses,
      );

  void close() => _interpreter.close();
}
