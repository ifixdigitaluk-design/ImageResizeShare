package uk.ifixdigital.imageresizeshare.core

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Typeface
import java.util.Locale
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

val DEFAULT_NOTE = listOf(
    "THERE MIGHT BE SLIGHT VARIATION IN COLORS IN ACTUAL PRINT.",
    "PLEASE CHECK SIZE & DESIGN CAREFULLY BEFORE PLACING THE ORDER.",
)

data class ProofSettings(
    val widthIn: Double = 0.0,
    val heightIn: Double = 0.0,
    val unit: String = "in",            // "in", "ft", "cm" for the size label
    val showArea: Boolean = true,
    val areaUnit: String = "sqft",      // "sqft" or "sqm"
    val noteTitle: String = "NOTE:-",
    val noteLines: List<String> = DEFAULT_NOTE,
    val fill: Boolean = true,           // true: trim to print shape, false: fit with white
    val closeup: Boolean = false,
    val closeupX: Float = 0.5f,         // relative position in the design
    val closeupY: Float = 0.5f,
    val closeupFraction: Double = 0.16,
    val watermark: String = "",
    val footer: String = "",
    val widthPx: Int = 1800,
)

class ProofRender(val bitmap: Bitmap, val designBox: Rect)

/** Customer proof sheet ("preview with info"), a port of the desktop renderer. */
object Proof {
    private const val SQIN_PER_SQFT = 144.0
    private const val SQM_PER_SQIN = 0.00064516

    private val BG = Color.rgb(89, 89, 89)
    private val BOX = Color.rgb(232, 232, 232)
    private val LABEL_GREY = Color.rgb(140, 140, 140)
    private val BLACK = Color.rgb(10, 10, 10)
    private val ACCENT = Color.rgb(26, 115, 232)

    private var bold: Typeface? = null
    private var regular: Typeface? = null

    private fun fonts(context: Context) {
        if (bold == null) {
            bold = try {
                Typeface.createFromAsset(context.assets, "fonts/LiberationSans-Bold.ttf")
            } catch (_: Exception) {
                Typeface.DEFAULT_BOLD
            }
            regular = try {
                Typeface.createFromAsset(context.assets, "fonts/LiberationSans-Regular.ttf")
            } catch (_: Exception) {
                Typeface.DEFAULT
            }
        }
    }

    fun fmtNum(v: Double, decimals: Int = 2): String {
        val s = String.format(Locale.US, "%.${decimals}f", v).trimEnd('0').trimEnd('.')
        return s.ifEmpty { "0" }
    }

    fun sizeLabel(wIn: Double, hIn: Double, unit: String = "in"): String = when (unit) {
        "cm" -> "${fmtNum(wIn * 2.54, 1)} x ${fmtNum(hIn * 2.54, 1)} cm"
        "ft" -> {
            fun ft(v: Double): String {
                var f = (v / 12).toInt()
                var i = v - f * 12
                if ((i * 10).roundToInt() / 10.0 >= 12) {
                    f += 1; i = 0.0
                }
                return if (i >= 0.05) "$f'${fmtNum(i, 1)}”" else "$f'"
            }
            "${ft(wIn)} x ${ft(hIn)}"
        }
        else -> "${fmtNum(wIn)}”x ${fmtNum(hIn)}”"
    }

    fun areaValue(wIn: Double, hIn: Double, unit: String = "sqft"): Double {
        val sqIn = wIn * hIn
        return if (unit == "sqm") sqIn * SQM_PER_SQIN else sqIn / SQIN_PER_SQFT
    }

    fun areaLabel(wIn: Double, hIn: Double, unit: String = "sqft"): String {
        val v = areaValue(wIn, hIn, unit)
        return if (unit == "sqm") String.format(Locale.US, "%.2f Sq.M", v)
        else String.format(Locale.US, "%.2f Sq.Ft", v)
    }

    fun proofFilename(srcName: String?, ps: ProofSettings, ext: String): String =
        "${ImageEngine.stem(srcName ?: "design")}_proof_${fmtNum(ps.widthIn, 1)}x${fmtNum(ps.heightIn, 1)}in$ext"

    // ---------------------------------------------------------------- text helpers

    private fun paint(size: Float, isBold: Boolean = true, color: Int = Color.WHITE) =
        Paint(Paint.ANTI_ALIAS_FLAG).apply {
            typeface = if (isBold) bold else regular
            textSize = max(6f, size)
            this.color = color
        }

    private fun textW(p: Paint, t: String): Float = p.measureText(t)

    private fun textH(p: Paint, t: String): Int {
        val r = Rect()
        val s = t.ifEmpty { "Ag" }
        p.getTextBounds(s, 0, s.length, r)
        return r.height()
    }

    /** Draw text with its ink top at y. */
    private fun drawTop(c: Canvas, t: String, x: Float, y: Float, p: Paint) {
        if (t.isEmpty()) return
        val r = Rect()
        p.getTextBounds(t, 0, t.length, r)
        c.drawText(t, x, y - r.top, p)
    }

    private fun fitPaint(lines: List<String>, maxW: Float, size: Float, color: Int, min: Int = 8): Paint {
        var s = size.toInt()
        while (s > min) {
            val p = paint(s.toFloat(), true, color)
            if (lines.filter { it.isNotEmpty() }.all { textW(p, it) <= maxW }) return p
            s--
        }
        return paint(min.toFloat(), true, color)
    }

    // ---------------------------------------------------------------- geometry

    fun designShape(designW: Int, ps: ProofSettings): Pair<Int, Int> {
        val ratio = if (ps.widthIn > 0 && ps.heightIn > 0) ps.heightIn / ps.widthIn else 1.0
        return designW to max(1, (designW * ratio).roundToInt())
    }

    private fun closeupBox(w: Int, h: Int, ps: ProofSettings): Rect {
        var side = max(16, minOf(w, h, (w * ps.closeupFraction / 0.8).toInt()))
        side = minOf(side, w, h)
        var x = (ps.closeupX * w - side / 2f).roundToInt()
        var y = (ps.closeupY * h - side / 2f).roundToInt()
        x = x.coerceIn(0, w - side)
        y = y.coerceIn(0, h - side)
        return Rect(x, y, x + side, y + side)
    }

    /** Full-resolution design trimmed (or padded) to the print shape. */
    private fun shapeDesign(img: Bitmap, ps: ProofSettings): Bitmap {
        val flat = ImageEngine.flatten(img)
        if (ps.widthIn <= 0 || ps.heightIn <= 0) return flat
        val r = ps.widthIn / ps.heightIn
        val ir = flat.width.toDouble() / flat.height
        if (abs(ir - r) < 0.002) return flat
        if (ps.fill) {
            return if (ir > r) {
                val w = (flat.height * r).roundToInt().coerceIn(1, flat.width)
                Bitmap.createBitmap(flat, (flat.width - w) / 2, 0, w, flat.height)
            } else {
                val h = (flat.width / r).roundToInt().coerceIn(1, flat.height)
                Bitmap.createBitmap(flat, 0, (flat.height - h) / 2, flat.width, h)
            }
        }
        val (w, h) = if (ir > r) flat.width to (flat.width / r).roundToInt() else (flat.height * r).roundToInt() to flat.height
        val out = Bitmap.createBitmap(max(1, w), max(1, h), Bitmap.Config.ARGB_8888)
        val c = Canvas(out)
        c.drawColor(Color.WHITE)
        c.drawBitmap(flat, ((w - flat.width) / 2).toFloat(), ((h - flat.height) / 2).toFloat(), null)
        out.setHasAlpha(false)
        return out
    }

    // ---------------------------------------------------------------- renderer

    fun render(context: Context, img: Bitmap, ps: ProofSettings): ProofRender {
        fonts(context)
        val W = ps.widthPx
        val s = W / 955f
        val full = shapeDesign(img, ps)

        val pad = 10 * s
        val fSmall = paint(15 * s, color = LABEL_GREY)
        val fBig = paint(29 * s, color = BLACK)
        val boxes = mutableListOf("(Width)X(Height)" to sizeLabel(ps.widthIn, ps.heightIn, ps.unit))
        if (ps.showArea) boxes += "(Area)" to areaLabel(ps.widthIn, ps.heightIn, ps.areaUnit)
        val boxW = boxes.map { (a, b) -> max(textW(fSmall, a), textW(fBig, b)) + 2 * pad }
        val headerH = (70 * s).toInt()
        val margin = (10 * s).toInt()
        val frame = (18 * s).toInt()
        val footerH = if (ps.footer.isNotBlank()) (40 * s).toInt() else 0
        val designW = W - 2 * (margin + frame)
        val (dw, dh) = designShape(designW, ps)
        val H = headerH + margin + 2 * frame + dh + margin + footerH

        val canvasBmp = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888)
        val c = Canvas(canvasBmp)
        c.drawColor(BG)
        val fillPaint = Paint().apply { style = Paint.Style.FILL }

        // ---------- header boxes ----------
        var x = 27 * s
        for ((i, box) in boxes.withIndex()) {
            val (lab, value) = box
            val bw = boxW[i]
            fillPaint.color = BOX
            c.drawRect(x, 0f, x + bw, headerH - 2 * s, fillPaint)
            drawTop(c, lab, x + (bw - textW(fSmall, lab)) / 2, 7 * s, fSmall)
            drawTop(c, value, x + (bw - textW(fBig, value)) / 2, 32 * s, fBig)
            x += bw + 6 * s
        }

        // ---------- note ----------
        val nx = x + 4 * s
        val maxW = W - nx - 12 * s
        val lines = ps.noteLines.map { it.trim() }.filter { it.isNotEmpty() }.take(3)
        if (ps.noteTitle.isNotBlank() || lines.isNotEmpty()) {
            val fTitle = fitPaint(listOf(ps.noteTitle), maxW, 22 * s, Color.WHITE)
            val fNote = fitPaint(lines.ifEmpty { listOf("") }, maxW, (if (lines.size <= 2) 15 else 12) * s, Color.WHITE)
            var y = 5 * s
            if (ps.noteTitle.isNotBlank()) {
                drawTop(c, ps.noteTitle, nx, y, fTitle)
                y += textH(fTitle, ps.noteTitle) + 6 * s
            }
            val avail = headerH - y - 4 * s
            val lh = textH(fNote, "AG")
            val n = max(1, lines.size)
            var gap = max(3 * s, (avail - lh * n) / n)
            gap = min(gap, 7 * s)
            for (ln in lines) {
                drawTop(c, ln, nx, y, fNote)
                y += lh + gap
            }
        }

        // ---------- white frame + design ----------
        val fy = headerH + margin
        fillPaint.color = Color.WHITE
        c.drawRect(margin.toFloat(), fy.toFloat(), (W - margin).toFloat(), (fy + 2 * frame + dh).toFloat(), fillPaint)
        var shown = Resampler.resizeBitmap(full, dw, dh)
        if (ps.watermark.isNotBlank()) {
            shown = shown.copy(Bitmap.Config.ARGB_8888, true)
            drawWatermark(shown, ps.watermark.trim(), s)
        }
        val ox = margin + frame
        val oy = fy + frame
        c.drawBitmap(shown, ox.toFloat(), oy.toFloat(), null)

        // ---------- close-up inset ----------
        if (ps.closeup) {
            val b = closeupBox(full.width, full.height, ps)
            val k = dw.toFloat() / full.width
            val rect = RectF(ox + b.left * k, oy + b.top * k, ox + b.right * k, oy + b.bottom * k)
            val lw = max(2f, 2.5f * s)
            val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                style = Paint.Style.STROKE; color = ACCENT; strokeWidth = lw
            }
            val inset = (min(dw, dh) * 0.42).toInt()
            val detail = Resampler.resizeBitmap(Bitmap.createBitmap(full, b.left, b.top, b.width(), b.height()), inset, inset)
            val border = max(3, (4 * s).toInt())
            var ix = ox + dw - inset - (14 * s).toInt()
            val iy = oy + dh - inset - (14 * s).toInt()
            if (rect.right > ix - border && rect.bottom > iy - border) ix = ox + (14 * s).toInt()
            val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = ACCENT; strokeWidth = max(1f, lw / 2) }
            c.drawLine(rect.centerX(), rect.centerY(), ix + inset / 2f, iy + inset / 2f, line)
            c.drawRect(rect, stroke)
            fillPaint.color = Color.WHITE
            c.drawRect(
                (ix - border).toFloat(), (iy - border).toFloat(),
                (ix + inset + border).toFloat(), (iy + inset + border).toFloat(), fillPaint,
            )
            c.drawBitmap(detail, ix.toFloat(), iy.toFloat(), null)
            val zoom = inset / max(1f, b.width() * k)
            val tag = String.format(Locale.US, "CLOSE-UP  %.1fx", zoom)
            val fTag = paint(13 * s)
            val tw = textW(fTag, tag) + 14 * s
            val th = textH(fTag, tag) + 10 * s
            fillPaint.color = ACCENT
            c.drawRect(ix.toFloat(), iy.toFloat(), ix + tw, iy + th, fillPaint)
            drawTop(c, tag, ix + 7 * s, iy + 5 * s, fTag)
        }

        // ---------- footer ----------
        if (footerH > 0) {
            val ft = ps.footer.trim()
            val fFoot = fitPaint(listOf(ft), (W - 4 * margin).toFloat(), 17 * s, Color.WHITE)
            val fy2 = H - footerH + (footerH - textH(fFoot, ft)) / 2f - margin / 2f
            drawTop(c, ft, (W - textW(fFoot, ft)) / 2, fy2, fFoot)
        }
        canvasBmp.setHasAlpha(false)
        return ProofRender(canvasBmp, Rect(ox, oy, ox + dw, oy + dh))
    }

    private fun drawWatermark(img: Bitmap, text: String, s: Float) {
        val c = Canvas(img)
        val p = paint(34 * s, color = Color.argb(95, 255, 255, 255))
        val shadow = paint(34 * s, color = Color.argb(40, 0, 0, 0))
        val tw = textW(p, text) + 120 * s
        val th = textH(p, text) + 110 * s
        val diag = hypot(img.width.toFloat(), img.height.toFloat()) + tw
        val ascent = -p.fontMetrics.ascent
        c.save()
        c.rotate(-30f, img.width / 2f, img.height / 2f)
        val left = img.width / 2f - diag / 2
        val top = img.height / 2f - diag / 2
        var row = 0
        var y = 0f
        while (y < diag) {
            val off = (row % 2) * tw / 2
            var x = -tw
            while (x < diag) {
                c.drawText(text, left + x + off, top + y + ascent, p)
                c.drawText(text, left + x + off + 2, top + y + 2 + ascent, shadow)
                x += tw
            }
            y += th
            row++
        }
        c.restore()
    }
}
