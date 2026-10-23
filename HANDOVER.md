# Handover: Image Resize & Share (v3.1, QA pass in progress)

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
python3 -m pytest -q                 # 112 tests, all pass
python3 main.py --selftest           # full app self-test, must end with OK
python3 -m pyflakes app main.py      # must be clean
```
For screenshots and robot runs, use `QT_QPA_PLATFORM=offscreen` with a 1920×1080 virtual screen
(a configfile `screen.json`). Set `IRS_HOME=<temp folder>` so tests don't touch real data.

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

## Still to do (next steps)
1. Last robot run: editor/files scenarios clean; studio/dialogs/extreme/jobs had no real errors
   (one cancelled print package was logged as an error; now fixed). Re-run once more if wanted.

## Things that can only be tested on the real Windows PC
- Building the .exe/installer (PyInstaller + Inno Setup `installer.iss`)
- Real phone photos for Measure, real WhatsApp Desktop paste, real printers
- Online AI (needs a Replicate token in Jobs › Online AI)

## Not built on purpose
- Price builder (excluded by the owner)
- Online customer approval link and installer phone app (these need a web server)
