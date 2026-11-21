import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';

import '../main.dart';
import '../theme.dart';
import 'results_screen.dart';

class CameraScreen extends StatefulWidget {
  const CameraScreen({super.key, required this.services});
  final AppServices services;

  @override
  State<CameraScreen> createState() => _CameraScreenState();
}

class _CameraScreenState extends State<CameraScreen> with WidgetsBindingObserver {
  CameraController? _controller;
  String? _error;
  bool _busy = false;
  bool _starting = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller?.dispose();
    super.dispose();
  }

  // Release the camera when the app is backgrounded and reopen it on return.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final controller = _controller;
    if (state == AppLifecycleState.inactive || state == AppLifecycleState.paused) {
      _controller = null;
      controller?.dispose();
      if (mounted) setState(() {});
    } else if (state == AppLifecycleState.resumed && controller == null) {
      _start();
    }
  }

  Future<void> _start() async {
    if (_starting) return;
    _starting = true;
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        setState(() => _error = 'No camera was found on this device.');
        return;
      }
      final back = cameras.firstWhere((c) => c.lensDirection == CameraLensDirection.back, orElse: () => cameras.first);
      final controller = CameraController(back, ResolutionPreset.high, enableAudio: false);
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() {
        _controller = controller;
        _error = null;
      });
    } on CameraException catch (e) {
      final denied = e.code.contains('AccessDenied') || e.code.contains('Restricted');
      setState(() => _error = denied
          ? 'Camera access was denied. Allow it in Settings > Apps > EcoRevive > Permissions.'
          : 'The camera could not start (${e.code}).');
    } finally {
      _starting = false;
    }
  }

  Future<void> _capture() async {
    final controller = _controller;
    final detector = widget.services.detector;
    if (controller == null || detector == null || _busy) return;
    setState(() => _busy = true);
    SemanticsService.sendAnnouncement(View.of(context), 'Scanning', TextDirection.ltr);
    try {
      final photo = await controller.takePicture();
      final bytes = await photo.readAsBytes();
      final result = await detector.scan(bytes, widget.services.shared.classes.length);
      if (!mounted) return;
      await Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => ResultsScreen(services: widget.services, result: result)),
      );
    } on CameraException catch (e) {
      _showError('Capture failed (${e.code}). Try again.');
    } on FormatException catch (e) {
      _showError(e.message);
    } catch (e) {
      _showError('The scan failed. Try again. ($e)');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    return Scaffold(
      appBar: AppBar(title: const Text('Scan')),
      body: Column(
        children: [
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(22),
                child: Container(
                  color: const Color(0xFF0C0B0F),
                  alignment: Alignment.center,
                  child: _error != null
                      ? Padding(
                          padding: const EdgeInsets.all(24),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.no_photography, color: Palette.aqua, size: 36),
                              const SizedBox(height: 12),
                              Text(_error!, textAlign: TextAlign.center, style: const TextStyle(color: Palette.muted)),
                              const SizedBox(height: 16),
                              OutlinedButton(onPressed: _start, child: const Text('Try again')),
                            ],
                          ),
                        )
                      : controller == null || !controller.value.isInitialized
                          ? const CircularProgressIndicator()
                          : Stack(
                              alignment: Alignment.center,
                              children: [
                                CameraPreview(controller),
                                if (_busy)
                                  Container(
                                    color: Colors.black54,
                                    alignment: Alignment.center,
                                    child: const Column(
                                      mainAxisSize: MainAxisSize.min,
                                      children: [
                                        CircularProgressIndicator(),
                                        SizedBox(height: 12),
                                        Text('Scanning on your phone…'),
                                      ],
                                    ),
                                  ),
                              ],
                            ),
                ),
              ),
            ),
          ),
          const Padding(
            padding: EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: Text('Fill the frame with one item, in good light.', style: TextStyle(color: Palette.muted)),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.only(bottom: 16, top: 8),
              child: Semantics(
                button: true,
                label: 'Capture and scan',
                child: GestureDetector(
                  onTap: controller == null || _busy ? null : _capture,
                  child: Container(
                    width: 76,
                    height: 76,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: Palette.lime, width: 4),
                    ),
                    alignment: Alignment.center,
                    child: Container(
                      width: 58,
                      height: 58,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: controller == null || _busy ? Palette.lime.withValues(alpha: 0.4) : Palette.lime,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
