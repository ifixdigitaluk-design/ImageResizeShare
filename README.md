# Image Resize, Crop & Share (Windows)

A desktop app for wallpaper, mural and print shops: resize, crop and **AI-upscale** designs without losing
quality, show customers a preview with the exact print size and area, check sharpness close up, download the
print file and send it on WhatsApp.

> **Android version:** the `android/` folder holds a native Android app with the same basic tools
> (resize presets, print sizes, crop, Enhanced upscaling, proof sheets, batch, WhatsApp sharing).
> GitHub builds the APK automatically – download it from the repository's **Releases** page.
> See [android/README.md](android/README.md).

## What's new in 3.1.1 (reliability update)

**Faster and easier**

* **Big prints edit instantly.** While you change settings, the Image Editor shows a screen-sized preview
  (about 2 seconds per change at 250 MP instead of minutes). The close-up shows the real print pixels, and
  Download / Share / Print make the full size once. The file size shown while editing is an estimate (≈).
* **AI-enhance the print files** (Send to Print): each panel is made with the AI upscaler straight from
  your design, so even walls too big to upscale in one file get sharp detail.
* **AI Upscale shows its progress** (e.g. "AI upscaling… 40%"), has a **Cancel** button, and no longer
  seems to load forever: if the graphics card stops responding, it retries with smaller pieces and then
  finishes with Enhanced, telling you why (updating the graphics driver usually helps).
* **No more "Not responding"**: opening big pictures, the test strip, Expand to fit and the options sheet
  work in the background with a progress box.
* **Help** button (Jobs page): **Send an error report** (a small zip with the error list and PC details –
  no pictures or customer details), **Check for updates** (also quietly once a day; can be turned off)
  and **About**. The app's error message also offers "Send error report".

**Fixed and hardened**

Every button, box and window was tested by a robot that clicks everything with odd values and odd files,
plus real-life problems on Windows. Fixed and hardened:

* **No crashes**: any unexpected problem shows a short, clear message and is written to `Logs/errors.log`.
* **Your work is safe**: every job keeps a backup copy of its file, saving never leaves half-written files,
  and closing the app while a print package or backup is being made asks first.
* **Clear messages** for damaged or empty pictures, files open in another program, a full disk, a missing
  USB/network data folder, and Windows blocking the Documents folder.
* **Big prints use far less memory**; huge sizes are capped with a message instead of failing.
* **Small laptop screens** (1366×768, 150 % scaling) work: pages and windows scroll instead of being cut off.
* **One copy of the app at a time**, so two windows can't overwrite each other's jobs.
* Room view, proofs and installer sheets work with any item size (a 1 cm door no longer breaks them).
* Faster Text & Logo window (fonts are remembered), safer AI-engine messages on any Windows language.
* **A job that can't be saved is never thrown away**: New job or opening another job asks first.
* **Undo of a design change** brings back the old picture too.
* **Measure from photo** refuses impossible sizes (a typo like 4200 m) and understands "4,2 m".
* **Very big murals and long walls** (test strip, room mockup, expand to fit, text and logos, a tiny logo on
  a big wall, CMYK print panels) stay within what an 8 GB PC can handle. If a panel is too big to make on
  this PC, Send to Print says so and suggests a lower DPI or a 50 % scale preset.
* **Faster proofs**: the watermark on a big proof is drawn in under a second.

## What's new in 3.1

* **Measure from Photo is smarter**
  * **Find corners**: the 4 wall corners are placed automatically from the wall's edges – you only check them.
  * **Lens fix**: photos taken with the 0.5× wide-angle camera bend straight lines; the app finds the bend and
    straightens the photo (automatic for ultra-wide photos, or press *Lens fix* and adjust the slider).
  * **Long walls**: help for measuring a wall in parts (each part as its own wall with a *Flat* corner).
* **Walls that aren't rectangles** – Wall & Items → *Shape*: **sloped ceiling (attic)**, **gable end**,
  **staircase** and **arched top**. Areas, the wall plan, proofs, installation and survey sheets and room
  mockups follow the shape, and **each panel is only as long as the wall needs** (plus bleed), which saves
  media. Lower walls in a run are trimmed the same way.
* **Expand to fit the wall** – when a picture is narrower or shorter than the wall, add new picture at the edges
  instead of cropping it: *Soft mirror*, *Stretch edges*, *Blurred background* (offline, free) or **AI – new
  picture content** through your Replicate account. The original pixels are never changed. Print Checks warn
  when *Fill the wall* would cut off more than 15 % of a design.
* **Text & logo** on the design – names for kids' rooms, café slogans, shop logos – in real sizes (e.g. 20 cm
  letters), any font on the PC, colour, outline, shadow; logos with automatic white-background removal. They
  appear on the wall plan, proofs, mockups and print sharp in the panel files.
* **Installs** (Jobs → Installs): fitting dates and times, installer, a list of upcoming fittings and of approved
  jobs that still need a date, a **WhatsApp reminder** typed in for you, **photos of the finished wall**,
  *Mark installed*, and **before / after posts** (square, story, landscape) with your name and phone plus a
  ready caption.
* **Data & Backup** (Jobs → Backup): keep jobs in a **OneDrive / Google Drive / Dropbox or shared folder** so
  two shop PCs see the same jobs, **back up** everything to a zip (print packages optional), **automatic
  backups** every N days (last 5 kept), and **restore** (merges – newer jobs win, nothing else overwritten).

## What's new in 3.0 – Wall Studio (wallpaper & mural jobs, ready for print)

The top bar now has three modes: **Image Editor** (as before), **Wall Studio** and **Jobs**.

**Measure from Photo**
* Open a phone photo of the wall, drag the **4 corner points** (a magnifier helps you hit the corner exactly) and
  type **one tape measurement** – width or height, in m, cm, mm, feet + inches or inches (`4.2`, `420 cm`, `13' 9"`).
* Type both and the app **checks your accuracy** (photo vs tape, e.g. "0.4 % – excellent").
* No tape? Use a **known object** instead: A4/Letter/A3 sheet, bank card, standard UK/EU/US door, UK socket or any size.
* **Doors, windows and furniture are found automatically** (sofa, bed, TV, table, chair, cabinet, plant …) and
  measured: width × height, distance from the left and from the floor, sill height, gap to the ceiling.
* The straightened wall shows **dimension lines**; drag items to correct them, draw new ones on the photo, or use
  **Measure a distance** to measure anything on the wall.
* **Survey sheet** (PDF + JPG) with the photo, the measured elevation and an items table; **Use in Wall Plan**.

**Wall plan, panels and print files**
* Several walls in a row (inside / outside corners), doors, windows, sockets, radiators and furniture.
* Design placement: fill, fit width/height, or drag and Ctrl+wheel; mirror; background colour.
* **Panels**: media width (53 cm … 160 cm or custom), overlap, bleed, equal / full-width / manual seams,
  hang left→right or right→left. **Place seams safely** moves joins away from faces and fine detail.
* **Print checks** (preflight) with one-click fixes: resolution for the viewing distance, coverage, bleed,
  panels vs media, seams through faces, out-of-gamut colours, customer approval, file size and disk space.
* **Send to Print**: panel files (TIFF/PDF/JPG, RGB or CMYK with ICC profile, 100–150 dpi or 50 % scale for very
  large walls), labels with panel number, ▲ TOP, QR code, crop and overlap marks, **installation sheet**,
  the approved proof, an A4 **test strip** with colour patches, job ticket, README, zip and optional RIP hot folder.
* **Output presets** for your print shop or RIP (format, colour profile, intent, DPI, scale, mirror, slug, hot folder).

**Customer side**
* **Customer Proof** (A3 PDF + JPG): the design on the wall with sizes, a room preview, the colour note, watermark
  and an approval box; version numbers; **record the approval**; send on WhatsApp.
* **Room Mockup**: living room, bedroom, office, café, empty room – at true scale with the wall's doors and
  furniture – or **on the customer's own photo**. Material close-up (non-woven, vinyl, canvas, sand, silk, linen,
  peel & stick) and finish (matte / satin / gloss). **Options sheet**: the design in 4 rooms or 4 colourways.
* **Colour**: soft-proof "as printed" (FOGRA39, FOGRA29, GRACoL, SWOP or your print shop's ICC), out-of-range
  highlight, match colours to a colour book (import paint / brand lists as CSV), replace colours, 12 colourways,
  hue / saturation / brightness / warmth – saved as a new design version.
* **Repeating Pattern**: tile + real repeat size, straight / half-drop / brick / mirror match, make seamless,
  3 × 3 join check, save one repeat for step-and-repeat RIPs.
* **AI Upscale for this wall** (offline Real-ESRGAN) pre-filled with the wall size and print DPI.
  *Optional*: online creative upscale with your own Replicate account (Settings → Online Upscaling).

**Jobs**
* Every job has a number (JOB-2026-0001), customer, phone, room, status (Enquiry → Measured → Designing →
  Proof sent → Approved → Printing → Printed → Installed → Completed), history and its own folder in
  `Documents\Image Resize & Share\Jobs` with designs (every version kept), survey photos, proofs, mockups and print packages.
* Search and filter jobs, **duplicate for a reprint**, open the folder.
* **Design Library** with tags, and a full-screen **Showroom** for customers (choose a design, see it in a room at
  their wall size, start a job from it).
* **Business details** (name, phone, logo, terms) printed on proofs, survey and installation sheets.

## What's new in 2.0

* **New layout** matching the design mockups: top tab bar (Image Editor · Resize · Crop · AI Upscale · Preview ·
  Download · Print Preview · WhatsApp Share) and five numbered panels – 1 Upload, 2 Resize & Crop,
  3 Image Preview, 4 Crop Image, 5 Download & Share.
* **AI Upscale studio** (Lupa-style): modes *High Fidelity*, *Balanced*, *Creative Detail*, *Illustration & Anime*;
  one-click presets (Portrait, Illustration, Nature, Anime, Product, Wallpaper, Text & Logo); **2× 3× 4× 8× 16×** or
  **Fit a print / wall size** (e.g. 10 ft wide at 100 DPI); Detail / Remove noise / Texture sliders;
  **before/after slider**; *Download Upscaled* (PNG / TIFF / JPG / PDF) or *Use in Editor* (with Undo).
* **Download Preview** dialog: print size in inches with cm and mm, area in sq ft, the design with
  **dimension arrows** ("4 inches (10.16 cm / 102 mm)"), print-quality check and the colour / size warning.
  Buttons: **Download Preview** and **Download Original**.
* **Closeup Print Preview** dialog: click or drag to mark a spot, see it magnified (150–800 %) with the print
  size and area. Buttons: **Download Closeup Preview** and **Download Original**.
* Print size can be typed in **inches, cm, mm or feet**; it is remembered between the two previews.
* Preview panel: **zoom slider, − / +, zoom % box, full screen (F11)**.
* Crop panel always visible, with **Crop Size** boxes and **Reset Crop**.
* **✕ remove image** on the file card; size tiles **Original / Small / Medium / Large / Custom / More sizes**
  (incl. wallpaper walls 8×8 ft … 16×9 ft).
* **TIFF** output (lossless LZW, DPI and colour profile kept).

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
| **AI Upscale studio** | Lupa-style modes and presets, 2×–16× or fit a wall/print size at a DPI, Detail/Noise/Texture, before/after slider, download or continue editing (Ctrl+U) |
| **Upscale 2× / 3× / 4×** | Quick buttons under *More resize options* (AI when available, Enhanced otherwise) |
| **Customer previews** | *Download Preview* (size, sq ft, dimension arrows, warning) and *Closeup Print Preview* (magnified spot), each with Download Original. Options: warning text, watermark, footer, sq ft / sq m, trim or white bars (Ctrl+P, Ctrl+Shift+P) |
| **Classic proof sheet** | "Preview with info" for customers: **size in inches** (or feet+inches / cm), **area in Sq.Ft** (or Sq.M), editable NOTE text, design in its exact print shape, optional **close-up inset**, **watermark** and footer (shop name / phone / order no.). Shows whether the resolution is good enough for that print size. Save as JPG/PNG/PDF, copy, or send on WhatsApp (Ctrl+Alt+P, or Preview → Options) |
| **Save** | JPG (4:4:4 colour, quality slider), PNG (lossless), TIFF (lossless, for print), WEBP (lossy or lossless), PDF (for printing). Optional **max file size** (e.g. ≤ 200 KB for online forms), print DPI embedded, colour profile kept, auto-rotation of phone photos, optional removal of GPS/camera info |
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

**Build without a Windows PC:** push the folder to a GitHub repository. The included workflow (`.github/workflows/build-windows.yml`) builds and tests the app (unit tests, self-test and the click-everything robot), makes the installer, and attaches it under **Actions → Artifacts** (and to a Release for the `main` branch).

**Run from source while developing:** `run.bat` (after `build.bat` has run once), or `python main.py`.

### Signing the installer (removes "Unknown publisher")

Windows SmartScreen warns about unsigned programs. To sign the app, installer and uninstaller you need a
**code-signing certificate** (a yearly purchase from a certificate seller such as Sectigo, DigiCert or
SSL.com; an "OV" certificate as a .pfx file works with the scripts here). Then either:

* **GitHub build:** in the repository go to *Settings → Secrets and variables → Actions* and add
  `WINDOWS_CERT_PFX_BASE64` (the .pfx file as base64: in PowerShell
  `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx")) | Set-Clipboard`) and
  `WINDOWS_CERT_PASSWORD`. Every build is then signed automatically.
* **On your PC:** set `IRS_SIGN_PFX` (path to the .pfx) and `IRS_SIGN_PASSWORD`, then run `build.bat`
  (signs the .exe), and compile the installer with
  `ISCC /DSign "/Ssigntool=powershell -ExecutionPolicy Bypass -File tools\sign.ps1 $f" installer.iss`.

Without a certificate everything builds as before, just unsigned. (New certificates build up
SmartScreen trust over a few weeks of downloads; an "EV" certificate is trusted at once but needs a USB key
or cloud signing service.)

### Updates and error reports

* **Check for updates** reads the GitHub Releases of `UPDATE_REPO` in `app/__init__.py`. That works when
  the repository is public. For a private repository, put the `latest.json` file attached to each
  release on any public web address and set `UPDATE_JSON_URL` to it.
* Releases are tagged `windows-v<version>.<build>` (e.g. `windows-v3.1.1.57`); the build number is shown in
  Help › About.
* To receive error reports directly, set `SUPPORT_EMAIL` and/or `SUPPORT_WHATSAPP` in `app/__init__.py`.
  Without them, users can copy the report file or show it in its folder and send it themselves.

## About quality

* **Shrinking** uses Lanczos with light sharpening, which is as sharp as any professional editor.
* **Enlarging**: a small image has no hidden detail, so ordinary apps just blur it.
  * **Enhanced** enlarges in ≤2× steps and sharpens with *anti-halo clamping*: crisp edges with no white outlines. It works on every PC and is fast.
  * **AI Super-Resolution** uses Real-ESRGAN, a neural network that redraws realistic detail (hair, skin, text edges). Use **Photos** for photos and **Logos/artwork** for graphics, drawings and screenshots. It needs a graphics card with Vulkan support, which covers most PCs from 2016 onwards (Intel, AMD, NVIDIA). If there isn't one, the app automatically uses Enhanced and tells you.
  * The app shows the enlargement factor, and for printing the real pixels-per-inch, so you know when a photo is too small for the print size.
* **Nothing is cut off** unless you choose *Fill* or crop. The default *Fit* mode keeps the whole image.
* **JPG at 90–95%** cannot be told apart from the original. Use **PNG** for logos and screenshots.

## AI Upscale: what it does (and doesn't)

* Runs **offline** on your PC with Real-ESRGAN (any graphics card with Vulkan, most PCs from 2016 on). On a
  normal GPU a 4× upscale of a phone photo takes seconds; without a GPU the app uses *Enhanced* upscaling.
* **High Fidelity** keeps the picture true to the original, **Balanced** adds a little clarity,
  **Creative Detail** adds micro-contrast and fine texture, **Illustration & Anime** keeps lines clean and colours flat.
* 8× and 16× use two AI passes, sized so the second pass lands exactly on the target.
* Cloud services such as Lupa or Magnific also have *generative* modes that invent new detail (faces, foliage).
  Wall Studio → Design → ⋯ → **Online creative upscale** does this through your own Replicate account
  (Real-ESRGAN or Clarity models; you pay Replicate per image, usually a few cents). Add the token in
  **Jobs → Online Upscaling**. Everything else stays offline.
* For wallpaper: **AI Upscale → Fit a print / wall size**, enter the wall width and 100–150 DPI, then
  *Use in Editor* – the previews will then show the wall size in feet and the area in sq ft.

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
app/core/proof.py           classic proof sheet renderer (size, sq ft, note, close-up)
app/core/sheets.py          print-size labels + Download Preview / Closeup Preview images
app/core/upscale.py         AI Upscale studio engine (modes, presets, fit print size)
app/ui/main_window.py       main window
app/ui/views.py             zoomable preview + interactive crop canvas
app/ui/batch.py             batch dialog
app/ui/proof_dialog.py      classic proof sheet dialog
app/ui/preview_dialogs.py   Download Preview, Closeup Print Preview, full-screen viewer
app/ui/upscale_dialog.py    AI Upscale studio with before/after slider
app/ui/share.py             clipboard / folder / WhatsApp helpers
app/ui/style.py             look & feel
app/core/wall.py            walls, items, placement, panels, seams, rolls (Wall Studio model)
app/core/measure.py         measure from photo: perspective, scale, straightening, door/window finding
app/core/detect.py          furniture (YOLOX) and face (YuNet) detection, seam risk
app/core/production.py      panel rendering, print files, output presets, print package
app/core/documents.py       proof, installation, survey, options sheets, test strip
app/core/colour.py          ICC soft proof, gamut, palettes, colour matching, colourways
app/core/mockup.py          room scenes, photo mockups, materials
app/core/pattern.py         repeating patterns
app/core/jobs.py            job folders, numbering, history, design library, business details
app/core/preflight.py       print checks
app/core/cloud.py           optional Replicate online upscaling and AI expand
app/core/expand.py          expand a design to the wall's shape (offline + AI)
app/core/layers.py          text and logo layers drawn on every render
app/core/posts.py           WhatsApp reminders, before/after posts
app/core/backup.py          backup, restore, moving the data folder
app/ui/wall_studio.py       Wall Studio page;  wall_canvas.py  interactive wall plan
app/ui/measure_dialog.py    Measure from Photo
app/ui/room_dialog.py, colour_dialog.py, pattern_dialog.py, job_docs.py (proof), print_dialog.py
app/ui/jobs_page.py         Jobs, Design Library, Showroom;  installs_view.py  fittings, reminders, posts
app/ui/shape_dialog.py, expand_dialog.py, layers_dialog.py
app/ui/settings_dialogs.py  business / presets / online AI / data & backup
assets/icc, assets/models   colour profiles and detection models
tests/                      unit tests (pytest)
build.bat, run.bat, ImageResizeShare.spec, installer.iss, .github/workflows/
```

## Licences

App code is yours. It uses Qt for Python (PySide6, LGPLv3), Pillow (MIT-CMU), pillow-heif (BSD-3), NumPy (BSD-3),
OpenCV (Apache-2.0), qrcode (BSD), Liberation Sans font (SIL OFL 1.1, in `assets/fonts`) and Real-ESRGAN ncnn
(BSD-3, by Xintao Wang et al.).

Bundled data: the YOLOX-S object detection model (Apache-2.0, Megvii, via the OpenCV Model Zoo) and the YuNet
face detection model (MIT, via the OpenCV Model Zoo) in `assets/models`; colour profiles in `assets/icc` from the
colord project (sRGB, Adobe RGB-compatible, FOGRA39L, FOGRA29L – CC0). The GRACoL and SWOP profiles are built from
characterization data published by CGATS (TR006, TR005) – credit "CGATS TR" as the source.
Include these notices if you distribute the app.
