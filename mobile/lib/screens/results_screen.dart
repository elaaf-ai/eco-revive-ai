import 'package:flutter/material.dart';

import '../detection/pipeline.dart';
import '../detection/yolo.dart';
import '../guides.dart';
import '../main.dart';
import '../theme.dart';

class ResultsScreen extends StatefulWidget {
  const ResultsScreen({super.key, required this.services, required this.result});
  final AppServices services;
  final ScanResult result;

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends State<ResultsScreen> {
  int? _selected;
  String? _material;
  bool _confirming = false;
  Future<Guide>? _guide;

  List<String> get _classes => widget.services.shared.classes;
  ScanQuality get _quality => assessScan(widget.result.detections);
  bool get _uncertain => _quality == ScanQuality.lowConfidence || _quality == ScanQuality.ambiguous;

  @override
  void initState() {
    super.initState();
    if (widget.result.detections.length == 1) _select(0);
  }

  void _select(int id) {
    final detection = widget.result.detections.firstWhere((d) => d.id == id);
    setState(() {
      _selected = id;
      _material = _classes[detection.classId];
      _confirming = _uncertain || detection.confidence < 0.5;
      _guide = _confirming ? null : widget.services.guides.fetch(_material!, detection.confidence, confirmed: false);
    });
  }

  void _confirm() {
    final detection = widget.result.detections.firstWhere((d) => d.id == _selected);
    setState(() {
      _confirming = false;
      _guide = widget.services.guides.fetch(_material!, detection.confidence, confirmed: true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final result = widget.result;
    return Scaffold(
      appBar: AppBar(title: const Text('Results')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(22),
            child: AspectRatio(
              aspectRatio: result.width / result.height,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  Image.memory(result.jpeg, fit: BoxFit.fill, semanticLabel: 'Scanned photo'),
                  CustomPaint(painter: _BoxPainter(result.detections, _classes, _selected)),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          if (result.detections.isEmpty) ..._empty() else ..._results(),
        ],
      ),
    );
  }

  List<Widget> _empty() => [
        const Text('Nothing recognised', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        const Text('Fill the frame with one item on a plain background, in good light.',
            style: TextStyle(color: Palette.muted)),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: () => Navigator.of(context).pop(),
          icon: const Icon(Icons.refresh),
          label: const Text('Retake'),
        ),
      ];

  List<Widget> _results() {
    final detections = widget.result.detections;
    return [
      Row(
        children: [
          Expanded(
            child: Text('${detections.length} ${detections.length == 1 ? 'item' : 'items'} found',
                style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
          ),
          OutlinedButton.icon(
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.refresh, size: 18),
            label: const Text('Retake'),
          ),
        ],
      ),
      Text('Ran on this phone in ${widget.result.inferenceMs} ms', style: const TextStyle(color: Palette.muted)),
      if (_uncertain) ...[
        const SizedBox(height: 10),
        _banner('The scan is not sure. Retake the photo closer, in good light, or confirm the material.', Palette.amber),
      ],
      const SizedBox(height: 12),
      for (final d in detections) _detectionTile(d),
      const SizedBox(height: 12),
      if (_selected == null) const Text('Select an item to see its guide.', style: TextStyle(color: Palette.muted)),
      if (_selected != null && _confirming) _confirmCard(),
      if (_selected != null && !_confirming && _guide != null)
        FutureBuilder<Guide>(
          future: _guide,
          builder: (context, snapshot) => snapshot.hasData
              ? _GuideCard(guide: snapshot.data!)
              : const Padding(
                  padding: EdgeInsets.all(16),
                  child: Row(children: [
                    SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                    SizedBox(width: 10),
                    Text('Preparing the guide…'),
                  ]),
                ),
        ),
    ];
  }

  Widget _detectionTile(Detection d) {
    final name = _classes[d.classId];
    final color = Palette.classColors[name]!;
    final active = d.id == _selected;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: active ? Palette.violetSoft : Palette.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: BorderSide(color: active ? Palette.lime : Palette.line),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () => _select(d.id),
          child: Semantics(
            selected: active,
            label: '$name ${(d.confidence * 100).round()} percent',
            child: Padding(
              padding: const EdgeInsets.all(10),
              child: Row(children: [
                Container(
                  width: 40,
                  height: 40,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(12)),
                  child: Text(name.substring(0, 2).toUpperCase(),
                      style: const TextStyle(color: Palette.limeInk, fontWeight: FontWeight.w800)),
                ),
                const SizedBox(width: 12),
                Expanded(child: Text(name, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700))),
                Text('${(d.confidence * 100).round()}%',
                    style: const TextStyle(color: Palette.muted, fontWeight: FontWeight.w700)),
              ]),
            ),
          ),
        ),
      ),
    );
  }

  Widget _confirmCard() => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Palette.surface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Palette.line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('What is this item made of?', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final cls in _classes)
                  ChoiceChip(
                    label: Text(cls),
                    selected: _material == cls,
                    onSelected: (_) => setState(() => _material = cls),
                  ),
              ],
            ),
            const SizedBox(height: 14),
            FilledButton(onPressed: _material == null ? null : _confirm, child: Text('Show guide for $_material')),
          ],
        ),
      );

  Widget _banner(String text, Color color) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: color.withValues(alpha: 0.45)),
        ),
        child: Text(text, style: TextStyle(color: color, fontWeight: FontWeight.w600)),
      );
}

class _BoxPainter extends CustomPainter {
  _BoxPainter(this.detections, this.classes, this.selected);
  final List<Detection> detections;
  final List<String> classes;
  final int? selected;

  @override
  void paint(Canvas canvas, Size size) {
    for (final d in detections) {
      final name = classes[d.classId];
      final color = Palette.classColors[name]!;
      final rect = Rect.fromLTRB(d.box.x1 * size.width, d.box.y1 * size.height, d.box.x2 * size.width, d.box.y2 * size.height);
      final isSelected = d.id == selected;
      canvas.drawRRect(
        RRect.fromRectAndRadius(rect, const Radius.circular(8)),
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = isSelected ? 3.5 : 2
          ..color = color,
      );
      final label = TextPainter(
        text: TextSpan(
          text: '$name ${(d.confidence * 100).round()}%',
          style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      final top = rect.top - label.height - 6 < 0 ? rect.top + 4 : rect.top - label.height - 6;
      final bg = Rect.fromLTWH(rect.left, top, label.width + 12, label.height + 4);
      canvas.drawRRect(RRect.fromRectAndRadius(bg, const Radius.circular(6)), Paint()..color = const Color(0xE60C0B0F));
      label.paint(canvas, Offset(bg.left + 6, bg.top + 2));
    }
  }

  @override
  bool shouldRepaint(covariant _BoxPainter old) => old.selected != selected || old.detections != detections;
}

class _GuideCard extends StatelessWidget {
  const _GuideCard({required this.guide});
  final Guide guide;

  @override
  Widget build(BuildContext context) {
    final accent = guide.isDisposal ? Palette.amber : Palette.lime;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Palette.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border(top: BorderSide(color: accent, width: 4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(guide.isDisposal ? 'SAFE DISPOSAL' : 'UPCYCLING IDEA',
              style: TextStyle(color: guide.isDisposal ? Palette.amber : Palette.muted, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 1)),
          const SizedBox(height: 6),
          Text(guide.title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 6),
          Text('${guide.source == 'gemini' ? 'AI-generated' : 'Curated guide'} · ${guide.sourceDetail}',
              style: const TextStyle(color: Palette.muted, fontSize: 13)),
          const SizedBox(height: 14),
          const Text('You need', style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Wrap(spacing: 6, runSpacing: 6, children: [for (final m in guide.materials) Chip(label: Text(m))]),
          const SizedBox(height: 14),
          const Text('Steps', style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          for (var i = 0; i < guide.steps.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                CircleAvatar(radius: 14, backgroundColor: Palette.violet, child: Text('${i + 1}', style: const TextStyle(color: Colors.white))),
                const SizedBox(width: 10),
                Expanded(child: Text(guide.steps[i])),
              ]),
            ),
          if (guide.precautions.isNotEmpty) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Palette.amber.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: Palette.amber.withValues(alpha: 0.35)),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Precautions', style: TextStyle(color: Palette.amber, fontWeight: FontWeight.w700)),
                const SizedBox(height: 6),
                for (final p in guide.precautions) Text('• $p'),
              ]),
            ),
          ],
          const SizedBox(height: 12),
          Text(guide.safetyNotice, style: const TextStyle(color: Palette.muted, fontSize: 13)),
        ],
      ),
    );
  }
}
