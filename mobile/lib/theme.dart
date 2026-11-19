import 'package:flutter/material.dart';

/// Same tokens as web/src/styles.css.
class Palette {
  static const bg = Color(0xFF141317);
  static const raised = Color(0xFF1C1A21);
  static const surface = Color(0xFF24212B);
  static const line = Color(0xFF34303D);
  static const violet = Color(0xFF5B2BD6);
  static const violetDeep = Color(0xFF3B1C92);
  static const violetSoft = Color(0xFF2A2140);
  static const lime = Color(0xFFC6F432);
  static const limeInk = Color(0xFF11140A);
  static const aqua = Color(0xFF49D6C8);
  static const amber = Color(0xFFFFB020);
  static const danger = Color(0xFFFF7A6B);
  static const text = Color(0xFFF4F2F8);
  static const muted = Color(0xFFB9B2C9);

  static const classColors = {
    'Plastic': Color(0xFF49D6C8),
    'Glass': Color(0xFFA9C8FF),
    'Metal': Color(0xFFE2DCEF),
    'Organic': Color(0xFFC6F432),
    'Hazardous': Color(0xFFFFB020),
  };
}

ThemeData buildTheme() {
  final base = ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    colorScheme: const ColorScheme.dark(
      primary: Palette.lime,
      onPrimary: Palette.limeInk,
      secondary: Palette.aqua,
      surface: Palette.raised,
      onSurface: Palette.text,
      error: Palette.danger,
    ),
    scaffoldBackgroundColor: Palette.bg,
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(bodyColor: Palette.text, displayColor: Palette.text),
    appBarTheme: const AppBarTheme(backgroundColor: Palette.bg, elevation: 0, centerTitle: false),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: Palette.lime,
        foregroundColor: Palette.limeInk,
        minimumSize: const Size(48, 52),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: Palette.text,
        side: const BorderSide(color: Palette.line),
        minimumSize: const Size(48, 48),
        shape: const StadiumBorder(),
      ),
    ),
  );
}
