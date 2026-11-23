# EcoRevive Android app

Home → Camera → Results, with the YOLO11 TFLite model running on the phone. Guides come from the EcoRevive API when one is configured; otherwise the bundled curated guides are used and labelled "offline". Hazardous results always use the curated disposal guide and never call the server.

**AI check (when online):** after the on-device scan, the app sends the photo to `POST /v1/detect?verify=true`. When the answer arrives, the results switch to the server's checked boxes: numbered and named ("Plastic 1 · plastic cup ✓"), with the likely resin code (#1 PET) and item code, wrong boxes removed, and the Gemini verdict. If the server cannot be reached, the phone's own result stays. Each AI-checked item asks "Was it right?"; the app sends the answer for the adaptive learning loop but never the photo.

**Current APK:** `build/app/outputs/flutter-apk/app-debug.apk`, built with `--dart-define=API_BASE=https://ecorevive-ai.vercel.app`.

## Add the model

Copy two files from the Colab export (`My Drive/FYP/ecorevive/artifacts/<version>/`) into `assets/model/`:

- `model.tflite`
- `manifest.json`

The app checks the manifest's classes against `assets/shared/classes.json` and refuses a mismatched model. Model files are not committed, so they stay in approved storage.

## Build and run

```powershell
flutter pub get
flutter analyze
flutter test
flutter run                                                          # emulator or USB device
flutter build apk --release --dart-define=API_BASE=https://<your-host>   # omit API_BASE for offline guides
```

The APK is written to `build/app/outputs/flutter-apk/app-release.apk`. It is **signed with the debug key** (the Flutter template default). It is fine for sideloading onto team phones, but not for the Play Store. To sign properly, create a keystore, add `android/key.properties` (gitignored), and set a `release` signing config.

## How detection works on the phone

`lib/detection/pipeline.dart` runs these steps in a background isolate:

1. Decode the photo and apply its EXIF rotation.
2. Letterbox it to the model's input size with grey padding, the same geometry as the backend.
3. Build an NHWC float tensor from 0 to 1.
4. Run TFLite.
5. Decode `[1, 4+C, N]` (or `[1, N, 4+C]`), with boxes normalised or in pixels.
6. Apply class-aware non-maximum suppression.
7. Map the boxes back to the upright photo.

`test/yolo_test.dart` covers each step.

## Build notes for the team laptop

- **Debug APK only.** Smart App Control blocks Flutter's release compiler (`gen_snapshot`) and shader compiler (`impellerc`) on this laptop. Use `flutter build apk --debug` here, and run unit tests with `flutter test --no-test-assets`. A release APK can be built on any machine without Smart App Control, or in CI if the model file is made available there.

- Windows Application Control blocks the `sdkmanager.bat` wrapper. The Android Gradle Plugin's built-in downloader still works, and it installed NDK 28.2 and Platform 36 during the first build.
- `android/gradle.properties` sets `kotlin.jvm.target.validation.mode=warning`. `tflite_flutter` compiles its Java code for JVM 11 while Kotlin follows Android Studio's bundled JDK 25.
