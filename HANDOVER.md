# Handover: Image Resize & Share (v3.1.1, QA round 2 + upgrades done)

**Which file to upload to the new session**
- Easiest: `ImageResizeShare-v3.1.1-code.zip` (about 1.5 MB). It's all the code, without the
  furniture-detection model. The app works without it; Measure just doesn't suggest furniture.
- To add the model, also upload `model_part1.bin`, `model_part2.bin` and `model_part3.bin` (6 MB each),
  put them in the project folder and run `python tools/get_detection_model.py --join`.
  On a PC with internet you can instead run `pip install onnx` and then
  `python tools/get_detection_model.py`, which downloads it from OpenCV Zoo.
- Or upload the full `ImageResizeShare-v3.1.1.zip` (18 MB, model included) if the upload allows it.

Then paste the prompt below.

---

## Prompt to paste in the new session

> I'm attaching my project ImageResizeShare (PySide6 + Pillow + OpenCV Windows desktop app, v3.1).
> Unzip it and read HANDOVER.md first. It lists what's done and what's left.
> Please carry on with the "real user" QA pass: find and fix every bug so the software is
> professional with no errors. Then run the tests, the self-test and the click-everything robot
> until everything is clean, and send me the new zip with a short list of bugs fixed.

---

## What the app is
- **Image Editor**: resize, crop, AI upscale (Lupa-style), download, print preview, WhatsApp share.
- **Wall Studio**: wallpaper and mural jobs. Measure from photo (auto corners, lens fix), shaped walls,
  room view, colour, pattern, expand to fit (offline + AI), text and logo layers, proof,
  print package, installer sheet.
- **Jobs**: jobs list, installs (dates, reminders, posts), design library, showroom, backup and restore.
- Previews and dialogs open as a rounded sheet inside the dimmed main window (to match the mockups).

## How to test (Linux, offscreen)
```
pip install -r requirements.txt --break-system-packages
pip install -r requirements-dev.txt pyflakes --break-system-packages
python3 -m pytest -q                 # 154 tests, all pass
python3 main.py --selftest           # full app self-test, must end with OK
python3 -m pyflakes app main.py tests tools   # must be clean
MALLOC_MMAP_THRESHOLD_=1048576 python3 tools/robot.py --seed 1 --mem   # click-everything robot, must end ROBOT OK
```
For screenshots and robot runs, use `QT_QPA_PLATFORM=offscreen:configfile=screen.json` for a 1920×1080
virtual screen. The file must look like this (a wrong format gives no screen and the app crashes at start):
`{"screens":[{"name":"s1","x":0,"y":0,"width":1920,"height":1080,"logicalDpi":96,"logicalBaseDpi":96,"dpr":1}]}`
Set `IRS_HOME=<temp folder>` so tests don't touch real data (the robot does this itself).

**The robot** (`tools/robot.py`, new in this round) opens the real window, loads good and broken
pictures (empty, damaged, truncated, CMYK, 16-bit, 1×1, 4000×8, Urdu file name …), then clicks every
button, types odd values in every box (0, -1, 999999, nan, "12,5", very long text …), opens every dialog
and the dialogs inside them, and answers file pickers / questions at random. Scenarios: nav (top bar), editor, files,
studio, dialogs, extreme, jobs. Use different `--seed` values for different click orders, and run one
robot at a time on a PC with 8 GB (each can use 2–3 GB when it makes 250 MP prints).
`MALLOC_MMAP_THRESHOLD_` makes Linux give freed memory back like Windows does; without it memory
looks much higher than on a real PC.

## QA pass: done so far (this zip includes these)
1. **Crash safety net** (`app/ui/errors.py`). Every unexpected error is written to
   `Logs/errors.log` and shown as a short, friendly message instead of the app closing.
   Installed in `main.py`. The self-test fails if any error happened.
2. **Start-up guard**: if the main window can't be built, a clear message points to the log.
3. **Missing data folder** (e.g. a USB drive that isn't plugged in): the app now warns and says which
   folder it is using, instead of quietly showing an empty job list.
4. **Windows blocks Documents** (Controlled Folder Access or a broken OneDrive link): data falls back
   to `%LOCALAPPDATA%\Image Resize & Share` (`app/core/paths.py: default_dir`).
5. **Damaged job file protection**: every save keeps `job.json.bak`, and loading falls back to it.
   Saving retries when antivirus or OneDrive holds the file. Opening a damaged or missing job now shows
   a clear message (`app/core/jobs.py`, `wall_studio.load_job_folder`).
6. **Unicode/long paths**: AI models load from memory (works in folders with Urdu or other non-English
   names). Shorter panel file names (customer ≤16 chars) and job folders (≤28 chars) avoid the
   Windows 260-character path limit.
7. **Font list cache** (`fonts_cache.json`): the Text & Logo dialog opens fast even on PCs with
   hundreds of fonts.
8. **Wall Studio WhatsApp Share with no design** used to send an empty-wall picture. It now says
   "Choose a design first". If the proof is a PDF only, it's copied as a file with the right message.
9. **Image Editor size limit**: typing a huge width (e.g. 999999) is now held to 250 MP with a
   clear status-bar message (`main_window._size_edited`). Tested.
10. **Big prints use far less memory**: sharpening runs in strips (identical result).
    100 MP went from 2.3 GB to 0.75 GB, and 250 MP from more than 6 GB (the test machine ran out of
    memory) to 2.1 GB. Very large JPGs skip progressive/optimize, preview images use 3 bytes a
    pixel, and the clipboard copy is limited to 36 MP (the saved file keeps full size).
    (`imaging._in_strips`, `qtutil.pil_to_qimage`, `share.copy_to_clipboard`)
11. **Memory leak fixed**: one-use dialogs (previews, room view, colour, proof, upscale, full screen …)
    stayed in memory with their pictures until the app closed. They're now freed when closed
    (`qtutil.FreeAfterExec`). Late background results for a closed window are ignored safely.
12. **Damaged or unreadable pictures**: plain-words reasons (empty file, damaged, HEIC not
    supported, too big, open elsewhere) in the editor, Wall Studio, pattern, logo, measure photo
    and library. A bad file no longer replaces the job's design, and choosing a bad measure
    photo no longer deletes the wall's doors/windows (`imaging.load_error_text`).
13. **Saving when a file is open in another program** (PDF viewer, Photoshop) or the disk is full:
    a clear message on every save (test strip, survey, repeat tile, room mockup, options sheet,
    installer sheet), plus friendly text for background jobs like the print package
    (`errors.save_or_warn`, `worker.friendly_error`).
14. **Room View with no design** now says "Choose a design first", like Colour and Proof.

15. **Small laptop screens** (1366×768, or 1920×1080 at 150 % scaling = 1280×680): nothing
    overlaps any more. Each page scrolls instead of squeezing, the top bar shows icons only when
    names don't fit (names are in the tooltips), Wall Plan chips get short names, the tip line hides,
    the right column scrolls, and the room picture fits its box. Full HD looks the same as before.
    (`main_window._scrollable/_fit_nav`, `wall_studio._fit_plan_header/_fit_room_icon`)
16. **Only one copy of the app runs.** Opening a picture while the app is open hands it to the open
    window instead of starting a second copy (two copies could overwrite each other's job saves).
    Uses QLocalServer (`main._single_instance`).
17. **No crash on exit**: the app used to crash in Qt's clean-up at the end of the self-test (an
    older problem too). It now leaves cleanly after saving settings (`main._shutdown`).

18. **Dialogs on small screens**: every sheet (previews, measure, room, proof, print, colour …)
    now scrolls inside itself when the screen is too small, so nothing is cut off. The Measure
    dialog's tool buttons go icon-only on narrow screens (`SheetDialog._scroll`,
    `MeasureDialog.resizeEvent`).
19. **"Use this image in Wall Studio" crash** (found by the robot): if the new design couldn't be
    opened, the studio crashed. It now keeps the previous design and explains why.
20. **No "Not responding"**: Download/Share of a big print used to freeze the window while the
    full-size image was made. That now runs in the background with a progress box, and a second
    click is ignored while it works.
21. **Deleting the job that's open** no longer leaves the studio pointing at a moved folder.
    Deleting is all-or-nothing (a rename), so a locked file can't leave half a job in each place.

22. **Room view, proof and installer sheet with odd item sizes** (found by the robot): a very small
    door/sofa/bed made the room picture fail (blank room thumbnail). All drawing now copes with any size
    (`mockup._SafeDraw`), with tests in `tests/test_odd_sizes.py`.
23. **Friendly, safe saving everywhere**: Download, preview, proof and upscale saves now use the clear
    "open in another program / disk full" message and write via a temporary file, so a failed save never
    leaves a broken file or wipes the old one (`errors.write_bytes_safely`).
24. **Job could not be saved** (read-only/offline folder, full disk): the user is told once, the app keeps
    retrying, and closing asks before losing changes (`wall_studio.save_now`).
25. **Closing while busy**: closing the app during a print package, backup or restore asks first
    (`worker.run_bg(task=…)`, `main_window.closeEvent`).
26. **Backups never include backups** or temp files, and stale `.part` files are cleaned up.
27. **WhatsApp numbers**: numbers typed the local way (07700 900123, 0300 1234567, +44 (0)7700…) are
    turned into WhatsApp's international format. Country code is in Business details (guessed from the
    PC's region when empty).
28. Business logo: a damaged picture is refused with a clear message. AI engine output is read safely on
    any Windows language. A corrupt auto-backup setting can't break start-up.
29. **Frozen build check**: a PyInstaller build (on Linux) passed the full self-test, so the spec
    collects all models, fonts, colour profiles and HEIC/QR modules.

## QA pass round 2 (v3.1.1): bugs found and fixed
30. **Measure: impossible sizes.** Typing 4200 m instead of 420 cm was accepted, the studio showed 100 m
    (its limit) but the job kept 4200 m, so the print package tried to make a kilometre-wide wall. Measure
    now refuses walls over 100 × 30 m or under 10 cm with a clear message (`measure.MAX_WALL_W/H`).
31. **Measure: changing the unit with a half-typed size** ("abc", "4,") raised an error. Fixed.
    Sizes with a decimal comma ("4,2 m") are now understood; "1,200" is still refused (not guessed).
32. **Unsaved job thrown away.** When a job could not be saved (read-only/offline folder, full disk),
    New job, opening another job, or Showroom › Use replaced it and lost the changes, right after the
    warning said "Your changes are still here". Now it asks first (`wall_studio.can_leave_job`).
33. **Jobs/Installs could save over newer studio changes**: the studio is now saved when you leave its page.
34. **Seven more saves had no friendly message** (fitting dates, reminders, posts, business details, proof,
    approval, print package): they now say "open in another program / read-only / disk full" instead of
    the generic error box (`errors.save_or_warn`).
35. **Test strip could use 6 GB and freeze the PC** ("Full media width" with a wide custom roll at 600 dpi
    = 1 gigapixel). Held to 120 MP by making the sample narrower, still 100 % scale; the user is told.
36. **Room Mockup of a tall, narrow wall** made a picture of up to 290 MP. Held to 36 MP (`mockup.MAX_ROOM_PX`),
    and its light effects (vignette, sheen) now work in strips: 3.3 GB → 1.3 GB peak, same pixels.
37. **Image Editor memory at big sizes**: the preview and close-up each kept their own full-size screen copy,
    and changing settings while a big preview was being made started another one alongside it. Now one
    shared copy, one preview job at a time, and the screen copy is made in strips. A 250 MP print went
    from being killed for running out of memory (over 7 GB) to 3.9 GB peak, 2.3 GB of real use.
38. **Thumbnails of big designs** (studio side panel, colour, pattern, expand, proof, previews) made two
    full-size copies first, on every panel refresh: 1.5 GB each time for a 250 MP mural, and slow.
    Now made straight at thumbnail size, and the studio thumbnail only when the design changes (`qtutil.small_rgb`).
39. **Very long, thin pictures** could get a size past 30,000 px a side in the editor (refused later by the
    processing). The size boxes now hold both limits (250 MP and 30,000 px a side).
40. **Undo of a design change** restored the job's settings but not the picture: the studio showed and
    printed the new design while the job said the old one (or none). Undo/redo now reload it
    (`wall_studio._restore`).
41. **Tiny design on a big wall** (e.g. a 2 × 2 px logo filling a 20 m wall): the print renderer enlarged
    the whole padded crop by the full magnification, a picture hundreds of thousands of px wide, so the
    Room View swatch or print package ran out of memory. It now makes only the output pixels
    (`production.ImageSource.render`).
42. **Expand to fit for a long, low wall** (e.g. 30 m × 3 m) could make a picture of several gigapixels,
    and even the live preview a gigapixel one. The result is held to 250 MP (asks first, says the size)
    and the preview to 4 MP; the edge-blend mask no longer uses 2 GB of float arrays (same pixels).
43. **Setting a big design** (from Expand, Upscale or the editor) kept three copies while loading:
    4 GB peak for a 250 MP mural, now 1.3 GB. Loading design files makes one copy instead of three (same
    pixels; checked on GIF, multi-page TIFF, EXIF-rotated JPEG, CMYK, 16-bit, ICC, HEIC).
44. **Upscale dialog** kept the original at full size twice for its before/after slider (2 GB for a big
    design). Now a screen-sized copy.

## Upgrades (v3.1.1)
45. **Fast editor preview** (`imaging.process_preview`, `render_region`, `estimated_bytes`): outputs over
    8 MP are previewed at screen size while editing; views work in real output pixels (`ZoomView`
    `logical_size`); the close-up asks for the real pixels of the spot it shows (`main_window._request_tile`);
    `_fresh_result` makes the full size for Download/Share/Print and keeps it until a setting changes.
    250 MP: about 2 s per change (was minutes), 0.4 GB while editing (was 4 GB). A target file size
    (KB) is always made for real. Close-up regions match the real output (tests in test_imaging.py).
46. **Background jobs** (`worker.run_with_progress`): opening pictures, test strip (also inside the print
    package), Expand to fit and the room options sheet no longer freeze the window.
47. **Code signing** (optional): `tools/sign.ps1`, `installer.iss` (`/DSign`), `build.bat` and the GitHub
    build sign when a certificate is provided (README › Signing the installer). Needs a purchased
    certificate; without it everything builds unsigned as before.
48. **Robot in the GitHub build**: seed 1 must pass; a new seed each build warns only; logs are uploaded
    as the `robot-logs` artifact. The build number is stamped into `app/_build.py` and releases are tagged
    `windows-v<version>.<build>` (was `windows-v1.0.<build>`), plus a `latest.json` file.
49. **Help button** (Jobs page; `app/ui/support.py`): Send an error report (zip: errors.log + PC facts,
    email/WhatsApp when `SUPPORT_EMAIL` / `SUPPORT_WHATSAPP` are set in `app/__init__.py`, else copy/show
    the file), Check for updates (manual, and quietly once a day with a status-bar button; GitHub Releases
    of `UPDATE_REPO` – needs a public repo – or `UPDATE_JSON_URL`), About. The crash message box has a
    "Send error report…" button.
50. **AI-enhance the print files** (Send to Print; `production.with_ai`): each panel is AI-enlarged from the
    design while the package is made (whole panel in one go up to 80 MP, 16 px context), so walls too
    big for a 250 MP upscaled design still get AI detail. The preflight "AI Upscale" button ticks it when
    the wall is too big. Tested with a stand-in engine (real Real-ESRGAN only on Windows).
51. Bug found by the new top-bar robot scenario: typing "inf"/"nan" as the Print Preview width crashed it.
52. Robot: menus and plain message boxes are now answered (PySide ignores replacing QMenu.exec on the
    class, so menus were never opened by the robot before), and it clicks the top bar of every page.
    It also no longer changes your real app settings (it keeps a copy and puts it back at the end).
53. More bugs found by the improved robot, all fixed:
    - Expand to fit crashed for extreme wall shapes (rounding in the padding), and its "blur" fill made a
      picture millions of pixels wide for a very thin design (fuzz-tested on 2,400 extreme cases).
    - Batch resize crashed when the output folder couldn't be made (e.g. name too long); now a message.
    - Error report: platform details are read without starting other programs (failed / flashed a window).
    - Text & Logo: a huge size (e.g. 9999 cm) drew the whole layer at full size (gigapixels). Layers are
      now drawn only where they are visible (same sharpness; also lighter for print panels crossing a
      logo), and the size boxes are limited to 1 cm – 30 m and ±100 m.
    - Opening a picture made up to four full copies (EXIF rotate, colour mode, extra copy): now one,
      identical pixels and EXIF (checked on 14 kinds of file). Matters for pasting a 250 MP result.
    - Print package: a panel is made in memory, so a very tall wall at a high DPI (e.g. 30 m at 150 dpi =
      1.4 gigapixels a panel) ran the PC out of memory. Preflight now warns above 200 MP and stops with a
      clear suggestion (lower DPI or a 50 % scale preset) when a panel can't be made on this PC
      (`production.max_panel_px`: about 1/16 of the PC's memory in pixels, at least 300 MP; no built-in
      preset is affected for walls up to 5 m). CMYK conversion now works in strips without extra copies
      (identical output), so a panel peaks at about 7 bytes a pixel (limit: about 1/20 of the memory).
    - Proofs and print sheets: an extreme print shape (e.g. 1 : 500) no longer makes a gigantic picture,
      and the watermark is made from one rotated stamp (a tall 3200 px proof: 22 s → under 1 s,
      1.6 GB → 0.4 GB; same look, and the dash in "PROOF – NOT FOR PRINT" no longer shows as a box).
    - Colour (colourways, adjust, replace colour) on a big design used whole-picture Lab arrays (about
      6 GB for 250 MP): now in strips, identical result.

## AI upscale fixes (after the owner reported "AI upscale keeps loading")
54. The AI program (Real-ESRGAN) ran silently with a 15-minute timeout per pass (two passes for 16×), so
    a graphics-driver stall looked like endless loading. Now (`app/core/ai_upscale.py`):
    - live progress ("AI upscaling… 40%") read from the program's output;
    - no output for 90 s = stalled: it is stopped and tried once more with small tiles (`-t 128`,
      gentler on laptop graphics); out-of-graphics-memory errors retry the same way; if it still fails,
      the upscale finishes with Enhanced and says why ("try updating the graphics driver");
    - a Cancel button in the AI Upscale window (closing the window also stops the AI program);
    - a small enlargement of a big picture no longer makes a full 4× picture first (the AI pass makes
      about 2× the target, never less than the target);
    - "Waiting for the AI engine…" when another job is using it (one job at a time);
    - the editor's close-up no longer queues AI runs for every spot you hover (it held up the AI window);
    - the editor's Download/Share box shows the AI progress, also for small sizes.
    Tested with a stand-in AI program that can succeed, run slowly, freeze, fail on the GPU or run out of
    graphics memory (`tests/test_ai_engine.py`, Linux/macOS), and in the app's windows.

## Still to do (next steps)
The robot runs clean on seeds 1–8 at 1920×1080, 1366×768 and 1280×680 (all scenarios); 146 tests pass;
the self-test passes at all three screen sizes. What's left needs you or the real Windows PC:

1. Fill in `SUPPORT_EMAIL` / `SUPPORT_WHATSAPP` in `app/__init__.py` so error reports reach you directly.
2. Updates: make the GitHub repository public, or host `latest.json` and set `UPDATE_JSON_URL`.
3. Signing: buy a code-signing certificate and add the two GitHub secrets.
4. On the real PC: try AI Upscale (watch the % and the Cancel button), AI-enhance on a big wall with the
   real AI engine, and a 250 MP print in the editor
   (Task Manager should show well under 1 GB while editing).

## Things that can only be tested on the real Windows PC
- Building the .exe/installer (PyInstaller + Inno Setup `installer.iss`)
- Real phone photos for Measure, real WhatsApp Desktop paste, real printers
- Online AI (needs a Replicate token in Jobs › Online AI)

## Not built on purpose
- Price builder (excluded by the owner)
- Online customer approval link and installer phone app (these need a web server)
