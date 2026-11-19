# EcoRevive Android app

Home → Camera → Results, with the YOLO11 TFLite model running on the phone. Guides come from the EcoRevive API when one is configured; otherwise the bundled curated guides are used and labelled "offline". Hazardous results always use the curated disposal guide and never call the server.

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

- Windows Application Control blocks the `sdkmanager.bat` wrapper. The Android Gradle Plugin's built-in downloader still works, and it installed NDK 28.2 and Platform 36 during the first build.
- `android/gradle.properties` sets `kotlin.jvm.target.validation.mode=warning`. `tflite_flutter` compiles its Java code for JVM 11 while Kotlin follows Android Studio's bundled JDK 25.
