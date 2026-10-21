# Image Resize & Share – Android

A native Android version of the Windows app (Kotlin + Jetpack Compose). Same image
engine ideas, rebuilt for phones: Lanczos resizing, Enhanced upscaling with
anti-halo sharpening, print sizes, proof sheets and one-tap WhatsApp sharing.

## Install the APK

1. Open the repository's **Releases** page and download the newest
   `ImageResizeShare-1.0.x.apk` (or take it from the latest **Actions → Build Android app** run).
2. Open the file on your phone. If Android asks, allow installing apps from that
   source (Chrome / Files), then tap **Install**.
3. Works on Android 7.0 and newer.

## What it does

| Area | On Android |
|---|---|
| **Open** | Photo picker, *Browse files*, or **Share → Resize & Share** from Gallery / WhatsApp / Files. *Open with / Edit with* also works. JPG, PNG, WEBP, HEIC, AVIF, GIF, BMP |
| **Resize** | Width/height in px, %, cm, mm or inches at any DPI; live print size and area (Sq.Ft / Sq.M); aspect lock; quick sizes plus WhatsApp, Instagram, YouTube, passport, 4×6, A4… |
| **Different shape?** | Fit (white / black / blurred / transparent / custom background), Fit inside, Fill, Stretch |
| **Enlarge** | Upscale 2× / 3× / 4×. *Enhanced* enlarges in ≤2× Lanczos steps and sharpens with anti-halo clamping |
| **Crop** | Drag handles, move, draw a new box; ratios 1:1, 4:5, 9:16, 16:9, passport, A4…; rule-of-thirds grid; exact X/Y/W/H |
| **Edit** | Rotate, flip, unlimited undo/redo, reset |
| **Preview** | Result / Original toggle, pinch-zoom, double-tap for 100%, real output file size |
| **Close-up** | Before vs After at 100–800% wherever you tap; the area is outlined on the preview |
| **Save** | JPG, PNG, WEBP (lossy/lossless), PDF (exact print size). Max file size (e.g. ≤ 200 KB). DPI written into the file. Saved to `Pictures/Image Resize & Share`, never overwriting |
| **Share** | Share sheet, Copy, **Send on WhatsApp** (optionally straight to a phone number). A copy goes to `Pictures/Image Resize & Share/WhatsApp` so you can send it as a *Document* in full quality |
| **Proof sheet** | Size in inches / feet+inches / cm, area in Sq.Ft / Sq.M, editable note, close-up inset (tap to place), watermark, footer. Save JPG / PNG / PDF or send on WhatsApp |
| **Batch** | Resize or convert many photos at once (keep size, %, fit within W×H, exact W×H) and share them all |

Differences from the Windows app: AI Super-Resolution (Real-ESRGAN) is not included –
*Enhanced* is used instead. Photos above 24 megapixels are reduced when opened, and
results are limited to 25 megapixels, so the app stays within phone memory.

## Build

GitHub builds the APK automatically (`.github/workflows/build-android.yml`) whenever
anything in `android/` changes, and publishes it as a Release.

To build on your own PC: install Android Studio (or JDK 17 + Android SDK), then

```
cd android
./gradlew assembleRelease        # Windows: gradlew.bat assembleRelease
```

The APK appears in `app/build/outputs/apk/release/`.

## Tests

`app/src/sharedTest` holds engine tests (ported from `tests/test_imaging.py`) and a
UI walk-through that screenshots every screen. They run two ways:

* **On GitHub, no phone needed:** Actions → **Android tests** → Run workflow. They run on
  the JVM with Robolectric (real Android graphics). Screenshots and results are pushed to the
  `ci-logs` branch (`android-tests/`).
* **On a phone or emulator:** `./gradlew connectedDebugAndroidTest`.

## Signing (so updates install over the old version)

Android only installs an update if it is signed with the same key. Until a key is
set up, each GitHub build is signed with a temporary key, which means you have to
uninstall the old version before installing a newer build.

To sign every build with your own permanent key, add these four repository secrets
(**Settings → Secrets and variables → Actions → New repository secret**):

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | the keystore file, base64-encoded (`base64 -w0 release.jks`, or `certutil -encode` on Windows) |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | key alias |
| `ANDROID_KEY_PASSWORD` | key password |

Then run **Actions → Build Android app → Run workflow**. Keep the keystore file safe:
if it is lost, future versions can't update existing installs.

## Code map

```
app/src/main/java/uk/ifixdigital/imageresizeshare/
  MainActivity.kt          intents (share / open with), pickers, permissions
  core/Resampler.kt        Lanczos-3, box pre-reduce, unsharp mask + anti-halo
  core/ImageEngine.kt      load (EXIF / HEIC), geometry, units, fit modes, encode, DPI, PDF
  core/Proof.kt            proof sheet renderer
  core/Outputs.kt          save to Pictures, share, WhatsApp, clipboard
  core/Presets.kt          size and crop presets
  ui/MainViewModel.kt      state, undo/redo, background processing, batch, proof
  ui/MainScreen.kt         main screen and tabs
  ui/Viewers.kt            zoomable preview and crop editor
  ui/OtherScreens.kt       proof sheet, batch, help
```
