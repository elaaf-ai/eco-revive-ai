import 'package:flutter/material.dart';

import '../main.dart';
import '../theme.dart';
import 'camera_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.services});
  final AppServices services;

  @override
  Widget build(BuildContext context) {
    final detector = services.detector;
    final preview = detector == null || detector.status != 'released';
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            Row(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(color: Palette.violet, borderRadius: BorderRadius.circular(9)),
                  child: const Icon(Icons.eco, color: Palette.lime, size: 20),
                ),
                const SizedBox(width: 10),
                const Text('EcoRevive', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
              ],
            ),
            const SizedBox(height: 20),
            Container(
              padding: const EdgeInsets.all(22),
              decoration: BoxDecoration(color: Palette.violet, borderRadius: BorderRadius.circular(22)),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('WASTE SCANNER',
                      style: TextStyle(letterSpacing: 1.2, fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xFFE4DCFF))),
                  const SizedBox(height: 10),
                  RichText(
                    text: const TextSpan(
                      style: TextStyle(fontSize: 32, height: 1.1, fontWeight: FontWeight.w800, color: Palette.text),
                      children: [
                        TextSpan(text: 'Point. Scan. '),
                        TextSpan(text: 'Give it a second life.', style: TextStyle(color: Palette.lime)),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'Spots plastic, glass, metal, organic and hazardous waste on your phone, then shows a reuse '
                    'project or how to dispose of it safely.',
                    style: TextStyle(color: Color(0xFFECE6FF), fontSize: 15, height: 1.4),
                  ),
                  const SizedBox(height: 18),
                  FilledButton.icon(
                    onPressed: detector == null
                        ? null
                        : () => Navigator.of(context).push(
                              MaterialPageRoute<void>(builder: (_) => CameraScreen(services: services)),
                            ),
                    icon: const Icon(Icons.photo_camera),
                    label: const Text('Start a scan'),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            if (detector == null)
              _Notice(color: Palette.danger, text: services.modelError ?? 'The model is not available.')
            else
              _Notice(
                color: preview ? Palette.amber : Palette.aqua,
                text: 'Model ${detector.version} runs on this phone. '
                    '${preview ? 'Preview: accuracy not yet verified.' : 'Evaluated release.'}',
              ),
            const SizedBox(height: 12),
            const _Notice(
              color: Palette.aqua,
              text: 'A scan is a guess, not a safety check. A photo cannot tell whether something is broken, sharp '
                  'or contains chemicals. Batteries and aerosols always get disposal steps.',
            ),
          ],
        ),
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({required this.color, required this.text});
  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Palette.raised,
          borderRadius: BorderRadius.circular(16),
          border: Border(left: BorderSide(color: color, width: 4)),
        ),
        child: Text(text, style: const TextStyle(color: Palette.muted, height: 1.4)),
      );
}
