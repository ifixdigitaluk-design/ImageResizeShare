# Image Resize & Share (Windows)

A desktop app for resizing, cropping and converting images without losing quality, and for sending them on WhatsApp.

## Features

| Area | What it does |
|---|---|
| **Open** | JPG, PNG, WEBP, HEIC (iPhone), AVIF, BMP, GIF, TIFF. Open with the button, drag & drop, Ctrl+V paste, or right-click → "Edit with Image Resize & Share" |
| **Resize** | Width/height in **px, %, cm, mm or inches** at any DPI, with live **print size and area (sq ft / sq m)**. Aspect ratio lock (link button). Quick presets and menus for **WhatsApp, Instagram, YouTube, passport photos, 4×6, A4…** |
| **Different shape?** | **Fit** keeps the whole photo and adds a background (white/black/blurred/transparent/custom), so nothing is cut off. **Fit inside** adds no borders. **Fill** trims the edges. **Stretch** forces the size |
| **Enlarge** | Make small images bigger without blocky pixels: **Enhanced** (stepwise Lanczos + halo-free sharpening) or **AI Super-Resolution** (Real-ESRGAN, rebuilds detail 2–4×; second pass for up to 16×) |
| **Crop** | Drag a selection with handles, move it, zoom and pan. Ratios: 1:1, 4:5, 9:16, 16:9, passport, A4… Rule-of-thirds grid. Exact X/Y/W/H boxes |
| **Edit** | Rotate, flip, unlimited undo/redo, reset |
| **Preview** | Original and result side by side, mouse-wheel zoom, **100% view** to check sharpness, real output file size |
| **Close-up (loupe)** | A third panel shows **Before vs After** at the same magnification (100–800%) wherever you point the mouse; click to pin the spot. The inspected area is outlined on the preview. Shows the upscaling difference at a glance |
| **Upscale 2× / 3× / 4×** | One-click buttons that use AI Super-Resolution when available (Enhanced otherwise) |
| **Proof sheet** | "Preview with info" for customers: **size in inches** (or feet+inches / cm), **area in Sq.Ft** (or Sq.M), editable NOTE text, design in its exact print shape, optional **close-up inset**, **watermark** and footer (shop name / phone / order no.). Shows whether the resolution is good enough for that print size. Save as JPG/PNG/PDF, copy, or send on WhatsApp (Ctrl+P) |
| **Save** | JPG (4:4:4 colour, quality slider), PNG (lossless), WEBP (lossy or lossless), PDF (for printing). Optional **max file size** (e.g. ≤ 200 KB for online forms), print DPI embedded, colour profile kept, auto-rotation of phone photos, optional removal of GPS/camera info |
| **Share** | **Copy** button: paste with Ctrl+V into WhatsApp Web, email or Word. **Prepare + Open WhatsApp** saves the file, copies it, opens WhatsApp Web or Desktop (optionally straight to a phone number) and explains how to send it at full quality |
| **Batch** | Resize or convert a whole folder in one go |
| **Comfort** | Remembers your last folders and settings, auto file names (`photo_1080x810.jpg`), never overwrites an existing file, opens the folder after saving, keyboard shortcuts (F1) |

## Quick start (Windows)

1. Install **Python 3.12** from https://www.python.org/downloads/ and tick **"Add python.exe to PATH"**.
2. Unzip this project and double-click **`build.bat`**. It will:
   - install the libraries,
   - download the AI engine (about 45 MB),
   - run all tests,
   - build `dist\ImageResizeShare\ImageResizeShare.exe`.
3. Double-click **`ImageResizeShare.exe`**. You can copy the whole `dist\ImageResizeShare` folder to any PC.
4. *(Optional)* For a proper installer with Start-menu and desktop shortcuts plus the right-click menu, install [Inno Setup 6](https://jrsoftware.org/isinfo.php), open `installer.iss` and press **Compile**.

**Build without a Windows PC:** push the folder to a GitHub repository. The included workflow (`.github/workflows/build-windows.yml`) builds and tests the app, makes the installer, and attaches it under **Actions → Artifacts**.

**Run from source while developing:** `run.bat` (after `build.bat` has run once), or `python main.py`.

## About quality

* **Shrinking** uses Lanczos with light sharpening, which is as sharp as any professional editor.
* **Enlarging**: a small image has no hidden detail, so ordinary apps just blur it.
  * **Enhanced** enlarges in ≤2× steps and sharpens with *anti-halo clamping*: crisp edges with no white outlines. It works on every PC and is fast.
  * **AI Super-Resolution** uses Real-ESRGAN, a neural network that redraws realistic detail (hair, skin, text edges). Use **Photos** for photos and **Logos/artwork** for graphics, drawings and screenshots. It needs a graphics card with Vulkan support, which covers most PCs from 2016 onwards (Intel, AMD, NVIDIA). If there isn't one, the app automatically uses Enhanced and tells you.
  * The app shows the enlargement factor, and for printing the real pixels-per-inch, so you know when a photo is too small for the print size.
* **Nothing is cut off** unless you choose *Fill* or crop. The default *Fit* mode keeps the whole image.
* **JPG at 90–95%** cannot be told apart from the original. Use **PNG** for logos and screenshots.

## WhatsApp: what is (and isn't) possible

WhatsApp does not allow other programs to attach a file automatically. The app does everything else for you:

1. Saves the finished image to `Pictures\Image Resize & Share\WhatsApp\`.
2. Copies it to the clipboard (as pixels and as a file).
3. Opens WhatsApp Web or the Desktop app, optionally directly in a chat with a phone number (▾ menu).

Then **press Ctrl+V in the chat and Send**. WhatsApp compresses photos. **For full quality, send it as a Document** (+ → Document → pick the file).

## Project structure

```
main.py                     app entry point (+ --selftest)
app/core/imaging.py         image engine: load, orientation, resize, enlarge, crop, encode
app/core/ai_upscale.py      Real-ESRGAN wrapper with automatic fallback
app/core/presets.py         size and crop presets
app/core/proof.py           proof sheet renderer (size, sq ft, note, close-up)
app/ui/main_window.py       main window
app/ui/views.py             zoomable preview + interactive crop canvas
app/ui/batch.py             batch dialog
app/ui/proof_dialog.py      proof sheet dialog
app/ui/share.py             clipboard / folder / WhatsApp helpers
app/ui/style.py             look & feel
tests/test_imaging.py       unit tests for the engine (pytest)
build.bat, run.bat, ImageResizeShare.spec, installer.iss, .github/workflows/
```

## Licences

App code is yours. It uses Qt for Python (PySide6, LGPLv3), Pillow (MIT-CMU), pillow-heif (BSD-3), Liberation Sans font (SIL OFL 1.1, in `assets/fonts`) and Real-ESRGAN ncnn (BSD-3, by Xintao Wang et al.). Include these notices if you distribute the app.
