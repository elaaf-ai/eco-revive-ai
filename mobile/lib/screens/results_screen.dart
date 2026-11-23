import 'package:flutter/material.dart';

import '../detection/pipeline.dart';
import '../detection/yolo.dart';
import '../guides.dart';
import '../main.dart';
import '../theme.dart';
import '../vision.dart';

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

  /// The server's AI check: null while waiting or when unavailable (then the phone's result stands).
  CheckedScan? _checked;
  bool _checking = false;
  final Map<int, bool> _feedbackSent = {};

  List<String> get _classes => widget.services.shared.classes;
  List<String> get _enabled => widget.services.shared.enabledClasses;
  late List<Detection> _shown = _onDevice();

  List<Detection> _onDevice() {
    final kept = [
      for (final d in widget.result.detections)
        if (_enabled.contains(_classes[d.classId])) d,
    ]..sort((a, b) => b.confidence.compareTo(a.confidence));
    // Renumber from the most confident so labels read "Plastic 1", "Plastic 2" like the website.
    return [
      for (var i = 0; i < kept.length; i++)
        Detection(id: i, classId: kept[i].classId, confidence: kept[i].confidence, box: kept[i].box),
    ];
  }

  ScanQuality get _quality => assessScan(_shown, competitors: widget.result.detections);
  bool get _uncertain => _quality == ScanQuality.lowConfidence || _quality == ScanQuality.ambiguous;

  CheckedDetection? _info(int id) {
    for (final c in _checked?.detections ?? const <CheckedDetection>[]) {
      if (c.detection.id == id) return c;
    }
    return null;
  }

  @override
  void initState() {
    super.initState();
    if (_shown.length == 1) _select(_shown.first.id);
    final vision = widget.services.vision;
    if (vision.enabled) {
      _checking = true;
      vision.check(widget.result.jpeg, _classes).then((checked) {
        if (!mounted) return;
        setState(() {
          _checking = false;
          if (checked == null) return;
          _checked = checked;
          _shown = [for (final c in checked.detections) if (_enabled.contains(_classes[c.detection.classId])) c.detection];
          _selected = null;
          _guide = null;
          _confirming = false;
        });
        if (_shown.length == 1) _select(_shown.first.id);
      });
    }
  }

  void _select(int id) {
    final detection = _shown.firstWhere((d) => d.id == id);
    final info = _info(id);
    setState(() {
      _selected = id;
      _material = _classes[detection.classId];
      // A box the AI check confirmed needs no manual confirmation.
      _confirming = !(info?.aiChecked ?? false) && (_uncertain || detection.confidence < 0.5);
      _guide = _confirming
          ? null
          : widget.services.guides.fetch(_material!, detection.confidence,
              confirmed: info?.aiChecked ?? false, itemHint: info?.itemName);
    });
  }

  void _confirm() {
    final detection = _shown.firstWhere((d) => d.id == _selected);
    setState(() {
      _confirming = false;
      _guide = widget.services.guides.fetch(_material!, detection.confidence,
          confirmed: true, itemHint: _info(detection.id)?.itemName);
    });
  }

  Future<void> _sendFeedback(CheckedDetection item, bool correct) async {
    final ok = await widget.services.vision
        .sendFeedback(item, correct: correct, modelVersion: _checked?.modelVersion ?? 'unknown');
    if (!mounted) return;
    setState(() => _feedbackSent[item.detection.id] = ok);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(ok ? 'Thanks! Your answer will help train the next model.' : 'Could not send your answer.'),
    ));
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
                  CustomPaint(painter: _BoxPainter(_shown, _classes, _selected, _checked)),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          if (_checking)
            const Padding(
              padding: EdgeInsets.only(bottom: 10),
              child: Row(children: [
                SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                SizedBox(width: 10),
                Text('Checking each item with the AI…', style: TextStyle(color: Palette.muted)),
              ]),
            ),
          if (_checked != null && _checked!.decidedByAi) ...[
            _banner(_checked!.message, _checked!.containsPlastic ? Palette.lime : Palette.amber),
            const SizedBox(height: 8),
          ],
          if (_checked != null && _checked!.removed.isNotEmpty) ...[
            Text(
                'The AI check removed ${_checked!.removed.length} box${_checked!.removed.length == 1 ? '' : 'es'} '
                'that were not plastic (${_checked!.removed.join(', ')}).',
                style: const TextStyle(color: Palette.muted, fontSize: 13)),
            const SizedBox(height: 8),
          ],
          if (_shown.isEmpty) ..._empty() else ..._results(),
        ],
      ),
    );
  }

  List<Widget> _empty() => [
        Text(_enabled.length == 1 ? 'No ${_enabled.first.toLowerCase()} recognised' : 'Nothing recognised',
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
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
    final detections = _shown;
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
      Text(
          _checked == null
              ? 'Ran on this phone in ${widget.result.inferenceMs} ms'
              : 'Ran on this phone in ${widget.result.inferenceMs} ms, then checked by the AI',
          style: const TextStyle(color: Palette.muted)),
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
          key: ValueKey(_guide),
          future: _guide,
          builder: (context, snapshot) => snapshot.hasData
              ? _GuideCard(guide: snapshot.data!)
              : snapshot.hasError
                  ? _GuideCard(
                      guide: widget.services.guides
                          .curated(_material!, 'Offline guide. The AI guide could not be loaded.'),
                    )
                  : const Padding(
                  padding: EdgeInsets.all(16),
                  child: Row(children: [
                    SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                    SizedBox(width: 10),
                    Text('Preparing the guide…'),
                  ]),
                ),
        ),
      if (_selected != null && _info(_selected!) != null) _feedbackCard(_info(_selected!)!),
    ];
  }

  Widget _feedbackCard(CheckedDetection item) {
    final sent = _feedbackSent[item.detection.id];
    final label = 'Plastic ${item.number}${item.itemName != null ? ' (${item.itemName})' : ''}';
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Palette.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Palette.line),
      ),
      child: sent == true
          ? const Text('Thanks! Your answer will help train the next model.',
              style: TextStyle(color: Palette.aqua, fontWeight: FontWeight.w700))
          : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Was $label right?', style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              Wrap(spacing: 8, children: [
                OutlinedButton.icon(
                    onPressed: () => _sendFeedback(item, true), icon: const Icon(Icons.check), label: const Text('Yes')),
                OutlinedButton.icon(
                    onPressed: () => _sendFeedback(item, false),
                    icon: const Icon(Icons.close),
                    label: const Text("No, it's wrong")),
              ]),
            ]),
    );
  }

  Widget _detectionTile(Detection d) {
    final name = _classes[d.classId];
    final info = _info(d.id);
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
            label: '$name ${d.id + 1} ${info?.itemName ?? ''} ${(d.confidence * 100).round()} percent',
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
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('$name ${d.id + 1}', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                    if (info?.itemName != null)
                      Text(info!.itemName!, style: const TextStyle(color: Palette.aqua, fontWeight: FontWeight.w600)),
                    if (info?.plasticType != null)
                      Text(
                          '${info!.plasticType!.label}${info.catalogCode != null ? ' · item ${info.catalogCode}' : ''}',
                          style: const TextStyle(color: Palette.lime, fontSize: 12, fontWeight: FontWeight.w700)),
                    if (info?.aiChecked ?? false)
                      const Row(children: [
                        Icon(Icons.verified, size: 14, color: Palette.lime),
                        SizedBox(width: 4),
                        Text('AI-checked', style: TextStyle(color: Palette.lime, fontSize: 12, fontWeight: FontWeight.w700)),
                      ]),
                  ]),
                ),
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
            Text(
                _enabled.length == 1
                    ? 'Is this item ${_enabled.first.toLowerCase()}?'
                    : 'What is this item made of?',
                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final cls in _enabled)
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
  _BoxPainter(this.detections, this.classes, this.selected, this.checked);
  final List<Detection> detections;
  final List<String> classes;
  final int? selected;
  final CheckedScan? checked;

  String _label(Detection d, String name) {
    for (final c in checked?.detections ?? const <CheckedDetection>[]) {
      if (c.detection.id == d.id && c.itemName != null) {
        return '$name ${d.id + 1} · ${c.itemName}${c.aiChecked ? ' ✓' : ''}';
      }
    }
    return '$name ${d.id + 1} ${(d.confidence * 100).round()}%';
  }

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
          text: _label(d, name),
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
  bool shouldRepaint(covariant _BoxPainter old) =>
      old.selected != selected || old.detections != detections || old.checked != checked;
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
