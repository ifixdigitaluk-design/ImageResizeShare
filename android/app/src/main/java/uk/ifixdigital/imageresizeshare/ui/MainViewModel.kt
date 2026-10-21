package uk.ifixdigital.imageresizeshare.ui

import android.app.Application
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import uk.ifixdigital.imageresizeshare.core.Background
import uk.ifixdigital.imageresizeshare.core.Crop
import uk.ifixdigital.imageresizeshare.core.CropRatio
import uk.ifixdigital.imageresizeshare.core.DEFAULT_NOTE
import uk.ifixdigital.imageresizeshare.core.EditState
import uk.ifixdigital.imageresizeshare.core.FitMode
import uk.ifixdigital.imageresizeshare.core.ImageEngine
import uk.ifixdigital.imageresizeshare.core.ImageTooLargeException
import uk.ifixdigital.imageresizeshare.core.LoadedImage
import uk.ifixdigital.imageresizeshare.core.MAX_OUTPUT_PIXELS
import uk.ifixdigital.imageresizeshare.core.MAX_OUTPUT_SIDE
import uk.ifixdigital.imageresizeshare.core.OutFormat
import uk.ifixdigital.imageresizeshare.core.OutputSettings
import uk.ifixdigital.imageresizeshare.core.Outputs
import uk.ifixdigital.imageresizeshare.core.Presets
import uk.ifixdigital.imageresizeshare.core.ProcessResult
import uk.ifixdigital.imageresizeshare.core.Proof
import uk.ifixdigital.imageresizeshare.core.ProofRender
import uk.ifixdigital.imageresizeshare.core.ProofSettings
import uk.ifixdigital.imageresizeshare.core.ResizeSettings
import uk.ifixdigital.imageresizeshare.core.SizePreset
import uk.ifixdigital.imageresizeshare.core.SizeUnit
import uk.ifixdigital.imageresizeshare.core.Upscale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

enum class Screen { MAIN, PROOF, BATCH, HELP }
enum class MainTab(val label: String) { RESIZE("Resize"), CROP("Crop"), FORMAT("Format"), SHARE("Share") }
enum class BatchMode(val label: String) {
    KEEP("Keep original size (convert only)"),
    PERCENT("Scale by percentage"),
    FIT("Fit within W × H (keep shape, no borders)"),
    EXACT("Exact W × H (uses the shape option on the Resize tab)"),
}

/** A request for the UI to open the system "Save as" picker. */
data class SaveAsRequest(val name: String, val mime: String, val proof: Boolean)

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val ctx: Context get() = getApplication()
    private val prefs = app.getSharedPreferences("settings", Context.MODE_PRIVATE)

    // ------------------------------------------------------------ navigation
    var screen by mutableStateOf(Screen.MAIN)
    var tab by mutableStateOf(MainTab.RESIZE)
    var showOriginal by mutableStateOf(false)

    // ------------------------------------------------------------ source + edits
    var src by mutableStateOf<LoadedImage?>(null); private set
    var loading by mutableStateOf(false); private set
    var edit by mutableStateOf(EditState()); private set
    var orientedDisplay by mutableStateOf<ImageBitmap?>(null); private set

    // ------------------------------------------------------------ size
    var tw by mutableIntStateOf(0); private set
    var th by mutableIntStateOf(0); private set
    var keepOriginal by mutableStateOf(true); private set
    var link by mutableStateOf(true); private set
    var unit by mutableStateOf(SizeUnit.PX)
    var dpi by mutableIntStateOf(300); private set

    // ------------------------------------------------------------ options (remembered)
    var mode by mutableStateOf(FitMode.FIT_PAD)
    var background by mutableStateOf(Background.WHITE)
    var customColor by mutableIntStateOf(0xFFFFFFFF.toInt())
    var upscale by mutableStateOf(Upscale.ENHANCED)
    var sharpenAuto by mutableStateOf(true)
    var sharpenValue by mutableIntStateOf(30)
    var allowUpscale by mutableStateOf(true)
    var fmt by mutableStateOf(OutFormat.JPG)
    var quality by mutableIntStateOf(92)
    var webpLossless by mutableStateOf(false)
    var targetOn by mutableStateOf(false)
    var targetKb by mutableIntStateOf(200)
    var waPhone by mutableStateOf("")

    // ------------------------------------------------------------ crop UI
    var cropRatio by mutableStateOf(Presets.CROP_RATIOS[0]); private set
    var cropSwap by mutableStateOf(false); private set
    var showGrid by mutableStateOf(true)

    // ------------------------------------------------------------ result
    var result by mutableStateOf<ProcessResult?>(null); private set
    var resultDisplay by mutableStateOf<ImageBitmap?>(null); private set
    var processing by mutableStateOf(false); private set
    var problem by mutableStateOf<String?>(null); private set
    var busyText by mutableStateOf<String?>(null); private set
    private var resultParams: Params? = null
    private var lastNotes: List<String> = emptyList()

    // ------------------------------------------------------------ close-up
    var closeUpOn by mutableStateOf(false)
    var closeUpZoom by mutableIntStateOf(200)
    var closeUpPanelPx by mutableIntStateOf(400)
    var closeUpPoint by mutableStateOf<Offset?>(null); private set
    var closeBefore by mutableStateOf<ImageBitmap?>(null); private set
    var closeAfter by mutableStateOf<ImageBitmap?>(null); private set
    var closeUpRect by mutableStateOf<Rect?>(null); private set
    var closeUpInfo by mutableStateOf(""); private set

    // ------------------------------------------------------------ undo
    private data class Snap(val edit: EditState, val keep: Boolean, val tw: Int, val th: Int)
    private val undoStack = ArrayDeque<Snap>()
    private val redoStack = ArrayDeque<Snap>()
    private var undoKey: String? = null
    var canUndo by mutableStateOf(false); private set
    var canRedo by mutableStateOf(false); private set

    // ------------------------------------------------------------ events for the UI
    private val _events = MutableSharedFlow<String>(extraBufferCapacity = 16)
    val events = _events.asSharedFlow()
    private val _intents = MutableSharedFlow<Intent>(extraBufferCapacity = 4)
    val intents = _intents.asSharedFlow()
    private val _saveAs = MutableSharedFlow<SaveAsRequest>(extraBufferCapacity = 2)
    val saveAs = _saveAs.asSharedFlow()

    fun toast(msg: String) {
        _events.tryEmit(msg)
    }

    // ------------------------------------------------------------ engine state (guarded by engineLock)
    private val engineLock = Mutex()
    private var orientedFull: Bitmap? = null
    private var orientedKey: Triple<LoadedImage, Int, Pair<Boolean, Boolean>>? = null
    private var resizedKey: Triple<LoadedImage, EditState, ResizeSettings>? = null
    private var resized: Bitmap? = null
    private var resizedNotes: List<String> = emptyList()

    private data class Params(
        val src: LoadedImage,
        val edit: EditState,
        val rs: ResizeSettings,
        val os: OutputSettings,
    )

    private class Computed(val params: Params, val result: ProcessResult, val display: Bitmap)

    // ================================================================= settings

    private fun loadSettings() {
        fun <E : Enum<E>> enumPref(key: String, values: Array<E>, def: E): E =
            values.firstOrNull { it.name == prefs.getString(key, null) } ?: def
        unit = enumPref("unit", SizeUnit.entries.toTypedArray(), SizeUnit.PX)
        dpi = prefs.getInt("dpi", 300)
        mode = enumPref("mode", FitMode.entries.toTypedArray(), FitMode.FIT_PAD)
        background = enumPref("bg", Background.entries.toTypedArray(), Background.WHITE)
        customColor = prefs.getInt("custom_color", 0xFFFFFFFF.toInt())
        upscale = enumPref("upscale", Upscale.entries.toTypedArray(), Upscale.ENHANCED)
        sharpenAuto = prefs.getBoolean("sharpen_auto", true)
        sharpenValue = prefs.getInt("sharpen", 30)
        allowUpscale = prefs.getBoolean("allow_upscale", true)
        fmt = enumPref("fmt", OutFormat.entries.toTypedArray(), OutFormat.JPG)
        quality = prefs.getInt("quality", 92)
        webpLossless = prefs.getBoolean("webp_lossless", false)
        targetOn = prefs.getBoolean("target_on", false)
        targetKb = prefs.getInt("target_kb", 200)
        waPhone = prefs.getString("wa_phone", "") ?: ""
        showGrid = prefs.getBoolean("grid", true)
        closeUpZoom = prefs.getInt("cu_zoom", 200)
        batchMode = enumPref("batch_mode", BatchMode.entries.toTypedArray(), BatchMode.FIT)
        batchW = prefs.getInt("batch_w", 1080)
        batchH = prefs.getInt("batch_h", 1080)
        batchPct = prefs.getInt("batch_pct", 50)
        batchPattern = prefs.getString("batch_pattern", "{name}_{w}x{h}") ?: "{name}_{w}x{h}"
        proofUnit = prefs.getString("proof_unit", "in") ?: "in"
        proofAreaUnit = prefs.getString("proof_area", "sqft") ?: "sqft"
        proofWidthPx = prefs.getInt("proof_px", 1800)
        proofTitle = prefs.getString("proof_title", "NOTE:-") ?: "NOTE:-"
        proofNoteText = prefs.getString("proof_note", DEFAULT_NOTE.joinToString("\n")) ?: ""
        proofWatermark = prefs.getString("proof_wm", "") ?: ""
        proofFooter = prefs.getString("proof_footer", "") ?: ""
    }

    private fun settingsKey(): List<Any> = listOf(
        unit, dpi, mode, background, customColor, upscale, sharpenAuto, sharpenValue, allowUpscale,
        fmt, quality, webpLossless, targetOn, targetKb, waPhone, showGrid, closeUpZoom,
        batchMode, batchW, batchH, batchPct, batchPattern,
    )

    private fun saveSettings() {
        prefs.edit()
            .putString("unit", unit.name).putInt("dpi", dpi).putString("mode", mode.name)
            .putString("bg", background.name).putInt("custom_color", customColor)
            .putString("upscale", upscale.name).putBoolean("sharpen_auto", sharpenAuto)
            .putInt("sharpen", sharpenValue).putBoolean("allow_upscale", allowUpscale)
            .putString("fmt", fmt.name).putInt("quality", quality).putBoolean("webp_lossless", webpLossless)
            .putBoolean("target_on", targetOn).putInt("target_kb", targetKb).putString("wa_phone", waPhone)
            .putBoolean("grid", showGrid).putInt("cu_zoom", closeUpZoom)
            .putString("batch_mode", batchMode.name).putInt("batch_w", batchW).putInt("batch_h", batchH)
            .putInt("batch_pct", batchPct).putString("batch_pattern", batchPattern)
            .apply()
    }

    fun currentResize(): ResizeSettings = ResizeSettings(
        enabled = !keepOriginal && tw > 0 && th > 0,
        width = tw, height = th, mode = mode, background = background, customColor = customColor,
        upscale = upscale, sharpen = if (sharpenAuto) -1 else sharpenValue, allowUpscale = allowUpscale,
    )

    fun currentOutput(): OutputSettings = OutputSettings(
        fmt = fmt, quality = quality, webpLossless = webpLossless,
        targetKb = if (targetOn && ImageEngine.isLossy(OutputSettings(fmt, quality, webpLossless))) targetKb else 0,
        dpi = dpi,
    )

    private fun currentParams(): Params? {
        val s = src ?: return null
        return Params(s, edit, currentResize(), currentOutput())
    }

    // ================================================================= opening

    fun open(uri: Uri) {
        viewModelScope.launch {
            loading = true
            try {
                val li = withContext(Dispatchers.IO) { engineLock.withLock { ImageEngine.load(ctx, uri) } }
                setSource(li)
                screen = Screen.MAIN
            } catch (e: CancellationException) {
                throw e
            } catch (e: OutOfMemoryError) {
                toast("This photo is too large to open on this phone.")
            } catch (e: Throwable) {
                toast("Could not open this image: ${e.message ?: e.javaClass.simpleName}")
            } finally {
                loading = false
            }
        }
    }

    private fun setSource(li: LoadedImage) {
        undoStack.clear(); redoStack.clear(); undoKey = null
        updateUndoFlags()
        cropRatio = Presets.CROP_RATIOS[0]
        cropSwap = false
        closeUpPoint = null
        result = null
        resultDisplay = null
        resultParams = null
        problem = null
        showOriginal = false
        edit = EditState()
        keepOriginal = true
        tw = li.width
        th = li.height
        orientedDisplay = displayCopy(li.bitmap).asImageBitmap()
        src = li
        if (li.reduced) {
            toast("Large photo: working at ${li.width} × ${li.height} px (from about ${li.originalWidth} × ${li.originalHeight}).")
        }
    }

    // ================================================================= processing

    private var processJob: Job? = null

    /** Wait after the last change before re-rendering (tests set this to 0). */
    var debounceMs = 220L

    private fun scheduleProcess(p: Params?) {
        processJob?.cancel()
        if (p == null) {
            processing = false
            return
        }
        if (p == resultParams) {
            processing = false
            return
        }
        processing = true
        processJob = viewModelScope.launch {
            if (debounceMs > 0) delay(debounceMs)
            try {
                val c = withContext(Dispatchers.Default) { engineLock.withLock { compute(p) } }
                applyResult(c)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                problem = friendly(e)
                processing = false
            }
        }
    }

    private fun friendly(e: Throwable): String = when (e) {
        is OutOfMemoryError -> "Not enough memory for this size on this phone. Try a smaller size."
        is ImageTooLargeException -> e.message ?: "Too large."
        else -> e.message ?: e.javaClass.simpleName
    }

    private suspend fun oriented(p: Params): Bitmap {
        val key = Triple(p.src, p.edit.rotation, p.edit.flipH to p.edit.flipV)
        val cached = orientedFull
        if (cached != null && orientedKey == key) return cached
        orientedFull = null
        val o = ImageEngine.applyOrientation(p.src.bitmap, p.edit)
        orientedFull = o
        orientedKey = key
        val disp = displayCopy(o).asImageBitmap()
        withContext(Dispatchers.Main) { if (src === p.src) orientedDisplay = disp }
        return o
    }

    private suspend fun compute(p: Params): Computed {
        val o = oriented(p)
        currentCoroutineContext().ensureActive()
        val rKey = Triple(p.src, p.edit, p.rs)
        val r: Bitmap
        val notes: List<String>
        val cachedResized = resized
        if (cachedResized != null && resizedKey == rKey) {
            r = cachedResized
            notes = resizedNotes
        } else {
            resized = null
            resizedKey = null
            val edited = ImageEngine.applyCrop(o, p.edit)
            val n = mutableListOf<String>()
            r = ImageEngine.resizeImage(edited, p.rs, n)
            resized = r
            resizedKey = rKey
            resizedNotes = n
            notes = n
        }
        currentCoroutineContext().ensureActive()
        val res = ImageEngine.finish(r, p.os, notes)
        return Computed(p, res, displayCopy(res.image))
    }

    private fun applyResult(c: Computed) {
        if (src !== c.params.src) return
        val old = result
        result = c.result
        resultDisplay = c.display.asImageBitmap()
        resultParams = c.params
        problem = null
        processing = currentParams() != c.params
        val img = c.result.image
        val pt = closeUpPoint
        if (old != null && pt != null && (old.image.width != img.width || old.image.height != img.height)) {
            closeUpPoint = Offset(pt.x / old.image.width * img.width, pt.y / old.image.height * img.height)
        }
        if (c.result.notes.isNotEmpty() && c.result.notes != lastNotes) toast(c.result.notes.joinToString("  "))
        lastNotes = c.result.notes
    }

    /** Up-to-date result; computes now if the preview is still pending. */
    private suspend fun freshResult(): ProcessResult? {
        val p = currentParams() ?: run {
            toast("Open an image first.")
            return null
        }
        val r = result
        if (r != null && resultParams == p) return r
        busyText = "Preparing image…"
        return try {
            val c = withContext(Dispatchers.Default) { engineLock.withLock { compute(p) } }
            applyResult(c)
            c.result
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            toast("Could not process image: ${friendly(e)}")
            null
        } finally {
            busyText = null
        }
    }

    /** A bitmap small enough to draw on screen (halving keeps it smooth). */
    private fun displayCopy(bmp: Bitmap, maxSide: Int = 2400): Bitmap {
        var cur = bmp
        while (max(cur.width, cur.height) > maxSide * 2) {
            cur = Bitmap.createScaledBitmap(cur, max(1, cur.width / 2), max(1, cur.height / 2), true)
        }
        if (max(cur.width, cur.height) > maxSide) {
            val k = maxSide.toDouble() / max(cur.width, cur.height)
            cur = Bitmap.createScaledBitmap(cur, max(1, (cur.width * k).roundToInt()), max(1, (cur.height * k).roundToInt()), true)
        }
        return cur
    }

    // ================================================================= undo / edit

    private fun snap() = Snap(edit, keepOriginal, tw, th)

    private fun pushUndo(key: String? = null) {
        if (src == null) return
        if (key != null && key == undoKey) return
        undoKey = key
        undoStack.addLast(snap())
        if (undoStack.size > 100) undoStack.removeFirst()
        redoStack.clear()
        updateUndoFlags()
    }

    private fun updateUndoFlags() {
        canUndo = undoStack.isNotEmpty()
        canRedo = redoStack.isNotEmpty()
    }

    private fun restore(s: Snap) {
        edit = s.edit
        keepOriginal = s.keep
        tw = s.tw
        th = s.th
        undoKey = null
        updateUndoFlags()
        refreshSize()
    }

    fun undo() {
        val s = undoStack.removeLastOrNull() ?: return
        redoStack.addLast(snap())
        restore(s)
    }

    fun redo() {
        val s = redoStack.removeLastOrNull() ?: return
        undoStack.addLast(snap())
        restore(s)
    }

    fun rotate(clockwise: Boolean) {
        val s = src ?: return
        pushUndo()
        edit = ImageEngine.rotateState(edit, s.width, s.height, clockwise)
        if (!keepOriginal) {
            val t = tw; tw = th; th = t
        }
        refreshSize()
    }

    fun flip(horizontal: Boolean) {
        val s = src ?: return
        pushUndo()
        edit = ImageEngine.flipState(edit, s.width, s.height, horizontal)
        refreshSize()
    }

    fun resetAll() {
        if (src == null) return
        pushUndo()
        edit = EditState()
        keepOriginal = true
        cropRatio = Presets.CROP_RATIOS[0]
        cropSwap = false
        refreshSize()
        toast("Reset to the original image.")
    }

    private fun refreshSize() {
        val (bw, bh) = baseSize()
        if (keepOriginal) {
            tw = bw; th = bh
        }
    }

    // ================================================================= size

    fun baseSize(): Pair<Int, Int> {
        val s = src ?: return 0 to 0
        return ImageEngine.editedSize(s.width, s.height, edit)
    }

    fun orientedSize(): Pair<Int, Int> {
        val s = src ?: return 0 to 0
        return ImageEngine.orientedSize(s.width, s.height, edit)
    }

    fun widthInUnit(): Double = ImageEngine.fromPixels(tw, unit, dpi, baseSize().first)
    fun heightInUnit(): Double = ImageEngine.fromPixels(th, unit, dpi, baseSize().second)

    fun setWidthValue(v: Double) {
        if (src == null) return
        val (bw, bh) = baseSize()
        pushUndo("size")
        tw = min(MAX_OUTPUT_SIDE, ImageEngine.toPixels(if (v > 0) v else 1.0, unit, dpi, bw))
        if (link) th = max(1, (tw.toDouble() * bh / bw).roundToInt())
        sizeEdited()
    }

    fun setHeightValue(v: Double) {
        if (src == null) return
        val (bw, bh) = baseSize()
        pushUndo("size")
        th = min(MAX_OUTPUT_SIDE, ImageEngine.toPixels(if (v > 0) v else 1.0, unit, dpi, bh))
        if (link) tw = max(1, (th.toDouble() * bw / bh).roundToInt())
        sizeEdited()
    }

    private fun sizeEdited() {
        val (bw, bh) = baseSize()
        keepOriginal = tw == bw && th == bh
    }

    fun toggleLink() {
        link = !link
        if (link && src != null && !keepOriginal) {
            val (bw, bh) = baseSize()
            th = max(1, (tw.toDouble() * bh / bw).roundToInt())
            sizeEdited()
        }
    }

    fun changeDpi(newDpi: Int) {
        val d = newDpi.coerceIn(10, 2400)
        if (d == dpi) return
        if (unit.physical && src != null && !keepOriginal) {
            // keep the physical size: more DPI -> more pixels
            val wv = ImageEngine.fromPixels(tw, unit, dpi, 0)
            val hv = ImageEngine.fromPixels(th, unit, dpi, 0)
            pushUndo("size")
            dpi = d
            tw = min(MAX_OUTPUT_SIDE, ImageEngine.toPixels(wv, unit, d, 0))
            th = min(MAX_OUTPUT_SIDE, ImageEngine.toPixels(hv, unit, d, 0))
            sizeEdited()
        } else dpi = d
    }

    fun applyPreset(p: SizePreset) {
        if (src == null) {
            toast("Open an image first.")
            return
        }
        pushUndo()
        if (p.w == 0.0) {
            keepOriginal = true
            refreshSize()
            return
        }
        if (p.dpi > 0) {
            dpi = p.dpi
            unit = p.unit
        }
        val d = if (p.dpi > 0) p.dpi else dpi
        tw = ImageEngine.toPixels(p.w, p.unit, d, 0)
        th = ImageEngine.toPixels(p.h, p.unit, d, 0)
        val (bw, bh) = baseSize()
        if (abs(tw.toDouble() / th - bw.toDouble() / bh) > 0.01) link = false
        sizeEdited()
    }

    fun isPresetSelected(p: SizePreset): Boolean {
        if (src == null) return false
        if (p.w == 0.0) return keepOriginal
        return p.unit == SizeUnit.PX && tw == p.w.toInt() && th == p.h.toInt()
    }

    fun quickUpscale(k: Int) {
        if (src == null) {
            toast("Open an image first.")
            return
        }
        val (bw, bh) = baseSize()
        if (bw * k > MAX_OUTPUT_SIDE || bh * k > MAX_OUTPUT_SIDE || bw.toLong() * k * bh * k > MAX_OUTPUT_PIXELS) {
            toast("${bw * k} × ${bh * k} px is too large for a phone. Try a smaller factor or crop first.")
            return
        }
        pushUndo()
        keepOriginal = false
        tw = bw * k
        th = bh * k
        link = true
        upscale = Upscale.ENHANCED
        toast("Upscaling $k× to $tw × $th px with Enhanced…")
    }

    /** Lines for the size information card. Each pair is (text, isWarning). */
    fun sizeInfo(): List<Pair<String, Boolean?>> {
        if (src == null) return emptyList()
        val (bw, bh) = baseSize()
        val lines = mutableListOf<Pair<String, Boolean?>>()
        lines += "Output: $tw × $th px" to null
        lines += "Print size: ${ImageEngine.printSizeText(tw, th, dpi)}" to null
        val wi = tw.toDouble() / dpi
        val hi = th.toDouble() / dpi
        lines += "Area: ${Proof.areaLabel(wi, hi)} (${Proof.areaLabel(wi, hi, "sqm")})" to null
        val scale = if (mode == FitMode.FILL || mode == FitMode.STRETCH) max(tw.toDouble() / bw, th.toDouble() / bh)
        else min(tw.toDouble() / bw, th.toDouble() / bh)
        if (!keepOriginal && scale > 1.01 && allowUpscale) {
            if (upscale == Upscale.STANDARD) {
                lines += String.format("Enlarging %.2f× – Standard can look soft. Choose Enhanced.", scale) to true
            } else {
                lines += String.format("Enlarging %.2f× – Enhanced keeps edges sharp.", scale) to false
            }
            val ppi = min(bw / wi, bh / hi)
            if (ppi < 150) lines += String.format("The original has about %.0f real pixels per inch at this print size.", ppi) to true
        } else if (!keepOriginal && scale < 0.99) {
            lines += String.format("Reducing to %.0f%% – sharp downscaling.", scale * 100) to false
        }
        return lines
    }

    fun shapeDiffers(): Boolean {
        if (src == null || keepOriginal) return false
        val (bw, bh) = baseSize()
        return abs(tw.toDouble() / th - bw.toDouble() / bh) > 0.005
    }

    // ================================================================= crop

    fun currentRatio(): Float? {
        val r = cropRatio
        if (r.isFree) return null
        val (a, b) = if (r.isOriginal) orientedSize() else r.a to r.b
        if (a <= 0 || b <= 0) return null
        var ratio = a.toFloat() / b
        if (cropSwap) ratio = 1f / ratio
        return ratio
    }

    fun setCrop(c: Crop?, key: String? = null) {
        if (src == null) return
        val (w, h) = orientedSize()
        pushUndo(key)
        edit = edit.copy(crop = ImageEngine.clampCrop(c, w, h))
        afterCropChange()
    }

    private fun afterCropChange() {
        val (bw, bh) = baseSize()
        if (keepOriginal) {
            tw = bw; th = bh
        } else if (link) {
            th = max(1, (tw.toDouble() * bh / bw).roundToInt())
        }
    }

    fun selectRatio(r: CropRatio) {
        cropRatio = r
        applyRatioToCrop()
    }

    fun swapRatio() {
        cropSwap = !cropSwap
        applyRatioToCrop()
    }

    private fun applyRatioToCrop() {
        val ratio = currentRatio() ?: return
        val (w, h) = orientedSize()
        val cur = ImageEngine.clampCrop(edit.crop, w, h)
        setCrop(fitRatio(cur, ratio, w, h))
    }

    /** A crop with the given ratio: the largest centred one, or one with about the current area. */
    private fun fitRatio(cur: Crop?, ratio: Float, w: Int, h: Int): Crop {
        var cw: Double
        var ch: Double
        if (w.toDouble() / h > ratio) {
            ch = h.toDouble(); cw = ch * ratio
        } else {
            cw = w.toDouble(); ch = cw / ratio
        }
        var cx = w / 2.0
        var cy = h / 2.0
        if (cur != null) {
            val area = cur.w.toDouble() * cur.h
            val k = sqrt(area / (cw * ch))
            if (k < 1) {
                cw *= k; ch *= k
            }
            cx = cur.x + cur.w / 2.0
            cy = cur.y + cur.h / 2.0
        }
        val x = (cx - cw / 2).coerceIn(0.0, w - cw)
        val y = (cy - ch / 2).coerceIn(0.0, h - ch)
        return Crop(x.roundToInt(), y.roundToInt(), max(1, cw.roundToInt()), max(1, ch.roundToInt()))
    }

    fun cropSelectAll() {
        val ratio = currentRatio()
        val (w, h) = orientedSize()
        if (ratio == null) setCrop(null) else setCrop(fitRatio(null, ratio, w, h))
    }

    fun cropClear() {
        setCrop(null)
    }

    fun setCropField(which: Char, value: Int) {
        val (w, h) = orientedSize()
        val c = ImageEngine.clampCrop(edit.crop, w, h) ?: Crop(0, 0, w, h)
        var n = when (which) {
            'x' -> c.copy(x = value)
            'y' -> c.copy(y = value)
            'w' -> c.copy(w = value)
            else -> c.copy(h = value)
        }
        currentRatio()?.let { r ->
            n = if (which == 'h') n.copy(w = (n.h * r).roundToInt()) else n.copy(h = (n.w / r).roundToInt())
        }
        setCrop(n, "crop-field")
    }

    // ================================================================= close-up

    fun tapResult(x: Float, y: Float) {
        val r = result ?: return
        closeUpPoint = Offset(x.coerceIn(0f, r.image.width.toFloat()), y.coerceIn(0f, r.image.height.toFloat()))
        if (!closeUpOn) closeUpOn = true
    }

    private var closeJob: Job? = null

    private fun updateCloseUp() {
        closeJob?.cancel()
        val r = result
        val s = src
        val disp = orientedDisplay
        if (!closeUpOn || r == null || s == null || disp == null) {
            closeUpRect = null
            return
        }
        val img = r.image
        val pt = closeUpPoint ?: Offset(img.width / 2f, img.height / 2f)
        val z = closeUpZoom / 100f
        val panel = max(32, closeUpPanelPx)
        val e = edit
        val rs = resultParams?.rs ?: currentResize()
        closeJob = viewModelScope.launch {
            val out = withContext(Dispatchers.Default) {
                val region = max(2f, panel / z)
                val afterRect = regionRect(img.width, img.height, pt.x, pt.y, region)
                val after = Bitmap.createBitmap(img, afterRect.left.toInt(), afterRect.top.toInt(), afterRect.width.toInt(), afterRect.height.toInt())
                val (sx, sy, k) = ImageEngine.resultToSource(pt.x, pt.y, s.width, s.height, e, rs, img.width)
                val o = engineLock.withLock { orientedFull }
                val before = if (o != null && o.width == ImageEngine.orientedSize(s.width, s.height, e).first) {
                    val br = regionRect(o.width, o.height, sx, sy, max(2f, region / k))
                    Bitmap.createBitmap(o, br.left.toInt(), br.top.toInt(), br.width.toInt(), br.height.toInt())
                } else null
                Triple(after, before, Pair(afterRect, k))
            }
            closeAfter = out.first.asImageBitmap()
            closeBefore = out.second?.asImageBitmap()
            closeUpRect = out.third.first
            closeUpInfo = String.format(
                "Showing %d%% of the result (%.1f× the original pixels).", closeUpZoom, z * out.third.second,
            )
        }
    }

    private fun regionRect(w: Int, h: Int, cx: Float, cy: Float, size: Float): Rect {
        val rw = min(size, w.toFloat()).roundToInt().coerceAtLeast(1)
        val rh = min(size, h.toFloat()).roundToInt().coerceAtLeast(1)
        val x = (cx - rw / 2f).roundToInt().coerceIn(0, w - rw)
        val y = (cy - rh / 2f).roundToInt().coerceIn(0, h - rh)
        return Rect(x.toFloat(), y.toFloat(), (x + rw).toFloat(), (y + rh).toFloat())
    }

    // ================================================================= save / share

    private fun defaultName(r: ProcessResult): String =
        ImageEngine.autoFilename(src?.name ?: "image", r.image.width, r.image.height, r.fmt)

    private suspend fun <T> busy(text: String, block: suspend () -> T): T {
        busyText = text
        try {
            return block()
        } finally {
            busyText = null
        }
    }

    fun saveToGallery() {
        viewModelScope.launch {
            val r = freshResult() ?: return@launch
            val name = defaultName(r)
            try {
                val saved = busy("Saving…") {
                    withContext(Dispatchers.IO) { Outputs.saveToGallery(ctx, r.data, name, r.fmt.mime) }
                }
                toast("Saved $name (${ImageEngine.humanSize(r.sizeBytes.toLong())}) to ${saved.where}")
            } catch (e: Throwable) {
                if (e is CancellationException) throw e
                toast("Could not save: ${e.message}")
            }
        }
    }

    fun requestSaveAs() {
        viewModelScope.launch {
            val r = freshResult() ?: return@launch
            _saveAs.tryEmit(SaveAsRequest(defaultName(r), r.fmt.mime, proof = false))
        }
    }

    fun writeTo(uri: Uri, proofFile: Boolean) {
        viewModelScope.launch {
            val data = if (proofFile) proofBytes(proofFmt) else freshResult()?.data
            if (data == null) return@launch
            try {
                busy("Saving…") {
                    withContext(Dispatchers.IO) {
                        ctx.contentResolver.openOutputStream(uri, "w")?.use { it.write(data) }
                            ?: throw java.io.IOException("Could not open the file.")
                    }
                }
                toast("Saved (${ImageEngine.humanSize(data.size.toLong())}).")
            } catch (e: Throwable) {
                if (e is CancellationException) throw e
                toast("Could not save: ${e.message}")
            }
        }
    }

    fun share() {
        viewModelScope.launch {
            val r = freshResult() ?: return@launch
            val uri = withContext(Dispatchers.IO) { Outputs.cacheForShare(ctx, r.data, defaultName(r)) }
            _intents.tryEmit(Intent.createChooser(Outputs.shareIntent(listOf(uri), r.fmt.mime), "Share image"))
        }
    }

    fun copy() {
        viewModelScope.launch {
            val r = freshResult() ?: return@launch
            val uri = withContext(Dispatchers.IO) { Outputs.cacheForShare(ctx, r.data, defaultName(r)) }
            Outputs.copyToClipboard(ctx, uri)
            toast("Copied! Long-press a message box and choose Paste.")
        }
    }

    /** Save a copy to Pictures/…/WhatsApp (for sending as a Document) and open WhatsApp with the image. */
    fun shareWhatsApp(canWriteStorage: Boolean) {
        viewModelScope.launch {
            val r = freshResult() ?: return@launch
            val name = defaultName(r)
            sendToWhatsApp(r.data, name, r.fmt.mime, canWriteStorage)
        }
    }

    private suspend fun sendToWhatsApp(data: ByteArray, name: String, mime: String, canWriteStorage: Boolean) {
        val uri = withContext(Dispatchers.IO) {
            if (canWriteStorage) {
                try {
                    Outputs.saveToGallery(ctx, data, name, mime, "WhatsApp")
                } catch (_: Exception) {
                }
            }
            Outputs.cacheForShare(ctx, data, name)
        }
        val i = Outputs.whatsAppIntent(ctx, listOf(uri), mime, waPhone)
        if (i == null) {
            toast("WhatsApp is not installed – choose another app.")
            _intents.tryEmit(Intent.createChooser(Outputs.shareIntent(listOf(uri), mime), "Share image"))
        } else {
            _intents.tryEmit(i)
            toast("Tip: for full quality send it as a Document – the file is in Pictures/${Outputs.FOLDER}/WhatsApp.")
        }
    }

    // ================================================================= proof sheet

    var proof by mutableStateOf(ProofSettings()); private set
    var proofLock by mutableStateOf(true)
    var proofRender by mutableStateOf<ProofRender?>(null); private set
    var proofDisplay by mutableStateOf<ImageBitmap?>(null); private set
    var proofBusy by mutableStateOf(false); private set
    var proofFmt by mutableStateOf(OutFormat.JPG)
    private var proofImage: Bitmap? = null
    private var proofName: String? = null
    var proofDesignPx by mutableStateOf(0 to 0); private set

    // remembered proof options
    private var proofUnit = "in"
    private var proofAreaUnit = "sqft"
    private var proofWidthPx = 1800
    private var proofTitle = "NOTE:-"
    var proofNoteText by mutableStateOf(DEFAULT_NOTE.joinToString("\n")); private set
    private var proofWatermark = ""
    private var proofFooter = ""

    fun openProof() {
        viewModelScope.launch {
            val r = freshResult() ?: return@launch
            proofImage = r.image
            proofName = src?.name
            proofDesignPx = r.image.width to r.image.height
            val wIn = (r.image.width.toDouble() / dpi * 100).roundToInt() / 100.0
            val ratio = r.image.height.toDouble() / r.image.width
            proof = ProofSettings(
                widthIn = wIn, heightIn = (wIn * ratio * 100).roundToInt() / 100.0,
                unit = proofUnit, areaUnit = proofAreaUnit, widthPx = proofWidthPx,
                noteTitle = proofTitle, noteLines = noteLines(proofNoteText),
                watermark = proofWatermark, footer = proofFooter,
            )
            proofRender = null
            proofDisplay = null
            screen = Screen.PROOF
        }
    }

    fun updateProof(p: ProofSettings) {
        proof = p
        proofUnit = p.unit; proofAreaUnit = p.areaUnit; proofWidthPx = p.widthPx
        proofTitle = p.noteTitle
        proofWatermark = p.watermark; proofFooter = p.footer
        prefs.edit().putString("proof_unit", p.unit).putString("proof_area", p.areaUnit)
            .putInt("proof_px", p.widthPx).putString("proof_title", p.noteTitle)
            .putString("proof_note", proofNoteText).putString("proof_wm", p.watermark)
            .putString("proof_footer", p.footer).apply()
    }

    private fun noteLines(text: String) = text.lines().map { it.trim() }.filter { it.isNotEmpty() }

    fun setProofNote(text: String) {
        proofNoteText = text
        updateProof(proof.copy(noteLines = noteLines(text)))
    }

    fun setProofWidth(v: Double) {
        val (w, h) = proofDesignPx
        val ratio = if (w > 0) h.toDouble() / w else 1.0
        updateProof(proof.copy(widthIn = v, heightIn = if (proofLock) (v * ratio * 100).roundToInt() / 100.0 else proof.heightIn))
    }

    fun setProofHeight(v: Double) {
        val (w, h) = proofDesignPx
        val ratio = if (w > 0) h.toDouble() / w else 1.0
        updateProof(proof.copy(heightIn = v, widthIn = if (proofLock) (v / ratio * 100).roundToInt() / 100.0 else proof.widthIn))
    }

    fun tapProof(x: Float, y: Float) {
        val box = proofRender?.designBox ?: return
        val u = (x - box.left) / box.width()
        val v = (y - box.top) / box.height()
        if (u in 0f..1f && v in 0f..1f) updateProof(proof.copy(closeupX = u, closeupY = v, closeup = true))
    }

    private var proofJob: Job? = null

    private fun scheduleProof(ps: ProofSettings?) {
        proofJob?.cancel()
        val img = proofImage
        if (ps == null || img == null || ps.widthIn <= 0 || ps.heightIn <= 0) return
        proofBusy = true
        proofJob = viewModelScope.launch {
            if (debounceMs > 0) delay(debounceMs)
            try {
                val r = withContext(Dispatchers.Default) { engineLock.withLock { Proof.render(ctx, img, ps) } }
                proofRender = r
                proofDisplay = displayCopy(r.bitmap).asImageBitmap()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                toast("Could not render the proof: ${friendly(e)}")
            } finally {
                proofBusy = false
            }
        }
    }

    fun proofQuality(): Pair<String, Boolean> {
        val (w, _) = proofDesignPx
        val ppi = w / max(0.01, proof.widthIn)
        return when {
            ppi >= 150 -> String.format("Excellent for print (%.0f pixels per inch).", ppi) to false
            ppi >= 72 -> String.format("Good for wall prints (%.0f pixels per inch).", ppi) to false
            else -> {
                val need = 100 / ppi
                String.format(
                    "Low resolution: %.0f pixels per inch at this size. Use Upscale ×%d on the Resize tab first.",
                    ppi, min(8, max(2, (need + 0.49).roundToInt())),
                ) to true
            }
        }
    }

    private suspend fun proofBytes(f: OutFormat): ByteArray? {
        val r = proofRender ?: run {
            toast("The proof is still being prepared.")
            return null
        }
        return withContext(Dispatchers.Default) {
            ImageEngine.encode(r.bitmap, OutputSettings(fmt = f, quality = 92, dpi = 150))
        }
    }

    private fun proofFileName(f: OutFormat) = Proof.proofFilename(proofName, proof, f.ext)

    fun saveProof() {
        viewModelScope.launch {
            val f = proofFmt
            val data = proofBytes(f) ?: return@launch
            try {
                val saved = withContext(Dispatchers.IO) { Outputs.saveToGallery(ctx, data, proofFileName(f), f.mime) }
                toast("Saved ${proofFileName(f)} to ${saved.where}")
            } catch (e: Throwable) {
                if (e is CancellationException) throw e
                toast("Could not save: ${e.message}")
            }
        }
    }

    fun requestProofSaveAs() {
        if (proofRender == null) return
        _saveAs.tryEmit(SaveAsRequest(proofFileName(proofFmt), proofFmt.mime, proof = true))
    }

    fun shareProof() {
        viewModelScope.launch {
            val data = proofBytes(OutFormat.JPG) ?: return@launch
            val uri = withContext(Dispatchers.IO) { Outputs.cacheForShare(ctx, data, proofFileName(OutFormat.JPG)) }
            _intents.tryEmit(Intent.createChooser(Outputs.shareIntent(listOf(uri), "image/jpeg"), "Share proof"))
        }
    }

    fun whatsAppProof(canWriteStorage: Boolean) {
        viewModelScope.launch {
            val data = proofBytes(OutFormat.JPG) ?: return@launch
            sendToWhatsApp(data, proofFileName(OutFormat.JPG), "image/jpeg", canWriteStorage)
        }
    }

    // ================================================================= batch

    val batchUris = mutableStateListOf<Uri>()
    var batchMode by mutableStateOf(BatchMode.FIT)
    var batchW by mutableIntStateOf(1080)
    var batchH by mutableIntStateOf(1080)
    var batchPct by mutableIntStateOf(50)
    var batchPattern by mutableStateOf("{name}_{w}x{h}")
    var batchRunning by mutableStateOf(false); private set
    var batchProgress by mutableFloatStateOf(0f); private set
    var batchStatus by mutableStateOf(""); private set
    var batchErrors by mutableStateOf<List<String>>(emptyList()); private set
    var batchSaved by mutableStateOf<List<Uri>>(emptyList()); private set
    var batchFinished by mutableStateOf(false); private set
    private var batchJob: Job? = null

    fun openBatch(uris: List<Uri> = emptyList()) {
        if (batchRunning) {
            screen = Screen.BATCH
            return
        }
        if (uris.isNotEmpty()) {
            batchUris.clear()
            batchUris.addAll(uris)
        }
        batchFinished = false
        batchErrors = emptyList()
        batchSaved = emptyList()
        batchStatus = ""
        batchProgress = 0f
        screen = Screen.BATCH
    }

    fun addBatch(uris: List<Uri>) {
        for (u in uris) if (u !in batchUris) batchUris.add(u)
        batchFinished = false
    }

    fun clearBatch() {
        if (!batchRunning) {
            batchUris.clear()
            batchFinished = false
            batchErrors = emptyList()
            batchSaved = emptyList()
        }
    }

    fun startBatch() {
        if (batchRunning || batchUris.isEmpty()) return
        val files = batchUris.toList()
        val rsBase = currentResize().copy(enabled = true)
        val os = currentOutput()
        val bm = batchMode
        val bw = batchW.coerceIn(1, MAX_OUTPUT_SIDE)
        val bh = batchH.coerceIn(1, MAX_OUTPUT_SIDE)
        val pct = batchPct.coerceIn(1, 1600)
        val pattern = batchPattern.ifBlank { "{name}_{w}x{h}" }
        batchJob = viewModelScope.launch {
            batchRunning = true
            batchFinished = false
            val errors = mutableListOf<String>()
            val saved = mutableListOf<Uri>()
            for ((i, uri) in files.withIndex()) {
                batchProgress = i.toFloat() / files.size
                batchStatus = "${i + 1} / ${files.size}"
                try {
                    val u = withContext(Dispatchers.Default) {
                        engineLock.withLock {
                            val li = ImageEngine.load(ctx, uri)
                            val rs = when (bm) {
                                BatchMode.KEEP -> rsBase.copy(enabled = false)
                                BatchMode.PERCENT -> rsBase.copy(
                                    width = max(1, (li.width * pct / 100.0).roundToInt()),
                                    height = max(1, (li.height * pct / 100.0).roundToInt()),
                                    mode = FitMode.STRETCH,
                                )
                                BatchMode.FIT -> rsBase.copy(width = bw, height = bh, mode = FitMode.FIT_INSIDE)
                                BatchMode.EXACT -> rsBase.copy(width = bw, height = bh)
                            }
                            val notes = mutableListOf<String>()
                            val resizedImg = ImageEngine.resizeImage(li.bitmap, rs, notes)
                            val res = ImageEngine.finish(resizedImg, os, notes)
                            val name = pattern.replace("{name}", ImageEngine.stem(li.name))
                                .replace("{w}", res.image.width.toString())
                                .replace("{h}", res.image.height.toString()) + os.fmt.ext
                            Outputs.saveToGallery(ctx, res.data, name, os.fmt.mime, "Batch").uri
                        }
                    }
                    saved += u
                } catch (e: CancellationException) {
                    batchRunning = false
                    batchSaved = saved.toList()
                    batchErrors = errors.toList()
                    throw e
                } catch (e: Throwable) {
                    errors += "Image ${i + 1}: ${friendly(e)}"
                }
            }
            batchProgress = 1f
            batchStatus = "Done"
            batchSaved = saved
            batchErrors = errors
            batchRunning = false
            batchFinished = true
            toast("Saved ${saved.size} of ${files.size} images to Pictures/${Outputs.FOLDER}/Batch")
        }
    }

    fun cancelBatch() {
        batchJob?.cancel()
        batchRunning = false
        batchStatus = "Cancelled"
    }

    fun shareBatch() {
        val list = batchSaved
        if (list.isEmpty()) return
        val mime = if (fmt == OutFormat.PDF) "application/pdf" else "image/*"
        _intents.tryEmit(Intent.createChooser(Outputs.shareIntent(list, mime), "Share images"))
    }

    // Must stay last: runs after every property above has been initialised.
    init {
        loadSettings()
        // Recompute the preview whenever anything that affects it changes.
        viewModelScope.launch {
            snapshotFlow { currentParams() }.collect { p -> scheduleProcess(p) }
        }
        viewModelScope.launch {
            snapshotFlow { settingsKey() }.collect { saveSettings() }
        }
        viewModelScope.launch {
            snapshotFlow { listOf(result, closeUpPoint, closeUpZoom, closeUpOn, closeUpPanelPx, orientedDisplay) }
                .collect { updateCloseUp() }
        }
        viewModelScope.launch {
            snapshotFlow { if (screen == Screen.PROOF) proof else null }.collect { ps -> scheduleProof(ps) }
        }
    }
}
