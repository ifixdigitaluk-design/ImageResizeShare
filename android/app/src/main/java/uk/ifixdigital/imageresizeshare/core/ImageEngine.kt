package uk.ifixdigital.imageresizeshare.core

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorSpace
import android.graphics.ImageDecoder
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Rect
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import androidx.exifinterface.media.ExifInterface
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.Locale
import java.util.zip.CRC32
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Port of the desktop `imaging.py`: load, geometry, units, resize with box modes, encode. */
object ImageEngine {

    // ------------------------------------------------------------------ loading

    fun load(context: Context, uri: Uri): LoadedImage {
        val cr = context.contentResolver
        var name = "image"
        var size = 0L
        try {
            cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val si = c.getColumnIndex(OpenableColumns.SIZE)
                    if (ni >= 0 && !c.isNull(ni)) name = c.getString(ni)
                    if (si >= 0 && !c.isNull(si)) size = c.getLong(si)
                }
            }
        } catch (_: Exception) {
            uri.lastPathSegment?.let { name = it.substringAfterLast('/') }
        }
        val mime = try { cr.getType(uri) } catch (_: Exception) { null }

        var sample = 1
        fun legacy(): Bitmap {
            sample = 1
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
            if (bounds.outWidth <= 0) throw IOException("This file is not a supported image.")
            val px = bounds.outWidth.toLong() * bounds.outHeight
            while (px / (sample.toLong() * sample) > MAX_SOURCE_PIXELS) sample *= 2
            val opts = BitmapFactory.Options().apply {
                inSampleSize = sample
                inPreferredConfig = Bitmap.Config.ARGB_8888
            }
            val raw = cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
                ?: throw IOException("This file is not a supported image.")
            val exif = try {
                cr.openInputStream(uri)?.use { ExifInterface(it) }
            } catch (_: Exception) {
                null
            }
            val deg = exif?.rotationDegrees ?: 0
            val flipped = exif?.isFlipped ?: false
            if (deg == 0 && !flipped) return raw
            val m = Matrix()
            m.postRotate(deg.toFloat())
            if (flipped) m.postScale(-1f, 1f)
            return Bitmap.createBitmap(raw, 0, 0, raw.width, raw.height, m, true)
        }

        val decoded: Bitmap = if (Build.VERSION.SDK_INT >= 28) {
            try {
                val source = ImageDecoder.createSource(cr, uri)
                ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
                    decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                    val px = info.size.width.toLong() * info.size.height
                    while (px / (sample.toLong() * sample) > MAX_SOURCE_PIXELS) sample++
                    if (sample > 1) decoder.setTargetSampleSize(sample)
                    try {
                        decoder.setTargetColorSpace(ColorSpace.get(ColorSpace.Named.SRGB))
                    } catch (_: Exception) {
                    }
                }
            } catch (e: OutOfMemoryError) {
                throw e
            } catch (e: Exception) {
                legacy()   // e.g. a format ImageDecoder rejects but BitmapFactory reads
            }
        } else {
            legacy()
        }
        val bmp = if (decoded.config == Bitmap.Config.ARGB_8888) decoded
        else decoded.copy(Bitmap.Config.ARGB_8888, false)
        if (bmp.hasAlpha() && !hasTransparency(bmp)) bmp.setHasAlpha(false)
        return LoadedImage(bmp, name, size, mime, bmp.width * sample, bmp.height * sample)
    }

    fun hasTransparency(bmp: Bitmap): Boolean {
        if (!bmp.hasAlpha()) return false
        val row = IntArray(bmp.width)
        for (y in 0 until bmp.height) {
            bmp.getPixels(row, 0, bmp.width, 0, y, bmp.width, 1)
            for (p in row) if ((p ushr 24) != 255) return true
        }
        return false
    }

    // ------------------------------------------------------------------ geometry

    fun orientedSize(w: Int, h: Int, st: EditState): Pair<Int, Int> =
        if (st.rotation % 180 == 90) h to w else w to h

    fun clampCrop(c: Crop?, w: Int, h: Int): Crop? {
        if (c == null) return null
        val x = c.x.coerceIn(0, w - 1)
        val y = c.y.coerceIn(0, h - 1)
        val cw = c.w.coerceIn(1, w - x)
        val ch = c.h.coerceIn(1, h - y)
        if (x == 0 && y == 0 && cw == w && ch == h) return null
        return Crop(x, y, cw, ch)
    }

    fun editedSize(w: Int, h: Int, st: EditState): Pair<Int, Int> {
        val (ow, oh) = orientedSize(w, h, st)
        val c = clampCrop(st.crop, ow, oh)
        return if (c != null) c.w to c.h else ow to oh
    }

    /** Rotate what the user currently sees by 90° (crop box follows). */
    fun rotateState(st: EditState, srcW: Int, srcH: Int, clockwise: Boolean): EditState {
        val (w, h) = orientedSize(srcW, srcH, st)
        var delta = if (clockwise) 90 else 270
        if (st.flipH != st.flipV) delta = 360 - delta
        val c = clampCrop(st.crop, w, h)
        val crop = c?.let {
            if (clockwise) Crop(h - it.y - it.h, it.x, it.h, it.w) else Crop(it.y, w - it.x - it.w, it.h, it.w)
        }
        return st.copy(rotation = (st.rotation + delta) % 360, crop = crop)
    }

    /** Mirror what the user currently sees (crop box follows). */
    fun flipState(st: EditState, srcW: Int, srcH: Int, horizontal: Boolean): EditState {
        val (w, h) = orientedSize(srcW, srcH, st)
        val c = clampCrop(st.crop, w, h)
        val crop = c?.let {
            if (horizontal) Crop(w - it.x - it.w, it.y, it.w, it.h) else Crop(it.x, h - it.y - it.h, it.w, it.h)
        }
        return if (horizontal) st.copy(flipH = !st.flipH, crop = crop) else st.copy(flipV = !st.flipV, crop = crop)
    }

    fun applyOrientation(bmp: Bitmap, st: EditState): Bitmap {
        if (st.rotation % 360 == 0 && !st.flipH && !st.flipV) return bmp
        val m = Matrix()
        if (st.rotation % 360 != 0) m.postRotate(st.rotation.toFloat())
        if (st.flipH) m.postScale(-1f, 1f)
        if (st.flipV) m.postScale(1f, -1f)
        val out = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, m, false)
        out.setHasAlpha(bmp.hasAlpha())
        return out
    }

    fun applyCrop(oriented: Bitmap, st: EditState): Bitmap {
        val c = clampCrop(st.crop, oriented.width, oriented.height) ?: return oriented
        return Bitmap.createBitmap(oriented, c.x, c.y, c.w, c.h)
    }

    // ------------------------------------------------------------------ units

    fun toPixels(value: Double, unit: SizeUnit, dpi: Int, basePx: Int): Int {
        val px = when (unit) {
            SizeUnit.PX -> value
            SizeUnit.PERCENT -> basePx * value / 100.0
            SizeUnit.IN -> value * dpi
            SizeUnit.CM -> value / 2.54 * dpi
            SizeUnit.MM -> value / 25.4 * dpi
        }
        return max(1, px.roundToInt())
    }

    fun fromPixels(px: Int, unit: SizeUnit, dpi: Int, basePx: Int): Double = when (unit) {
        SizeUnit.PX -> px.toDouble()
        SizeUnit.PERCENT -> px * 100.0 / max(1, basePx)
        SizeUnit.IN -> px.toDouble() / dpi
        SizeUnit.CM -> px.toDouble() / dpi * 2.54
        SizeUnit.MM -> px.toDouble() / dpi * 25.4
    }

    fun printSizeText(w: Int, h: Int, dpi: Int): String = String.format(
        Locale.US, "%.1f × %.1f cm (%.2f × %.2f in) at %d DPI",
        w.toDouble() / dpi * 2.54, h.toDouble() / dpi * 2.54, w.toDouble() / dpi, h.toDouble() / dpi, dpi,
    )

    // ------------------------------------------------------------------ resize with box modes

    class Layout(
        val scaledW: Int, val scaledH: Int,
        val canvasW: Int, val canvasH: Int,
        val offX: Int, val offY: Int,
        val cropLeft: Int, val cropTop: Int, val hasCrop: Boolean,
    )

    fun computeLayout(sw: Int, sh: Int, bw: Int, bh: Int, mode: FitMode): Layout {
        if (mode == FitMode.STRETCH) return Layout(bw, bh, bw, bh, 0, 0, 0, 0, false)
        val rw = bw.toDouble() / sw
        val rh = bh.toDouble() / sh
        if (mode == FitMode.FILL) {
            val r = max(rw, rh)
            val nw = max(bw, (sw * r).roundToInt())
            val nh = max(bh, (sh * r).roundToInt())
            return Layout(nw, nh, bw, bh, 0, 0, (nw - bw) / 2, (nh - bh) / 2, true)
        }
        val r = min(rw, rh)
        val nw = max(1, (sw * r).roundToInt())
        val nh = max(1, (sh * r).roundToInt())
        if (mode == FitMode.FIT_INSIDE) return Layout(nw, nh, nw, nh, 0, 0, 0, 0, false)
        return Layout(nw, nh, bw, bh, (bw - nw) / 2, (bh - nh) / 2, 0, 0, false)
    }

    fun checkOutputSize(w: Int, h: Int) {
        if (w > MAX_OUTPUT_SIDE || h > MAX_OUTPUT_SIDE || w.toLong() * h > MAX_OUTPUT_PIXELS) {
            throw ImageTooLargeException(
                "$w × $h px is too large for a phone (max $MAX_OUTPUT_SIDE px per side, " +
                    "${MAX_OUTPUT_PIXELS / 1_000_000} megapixels)."
            )
        }
    }

    fun resizeImage(img: Bitmap, rs: ResizeSettings, notes: MutableList<String>): Bitmap {
        if (!rs.enabled || rs.width <= 0 || rs.height <= 0) return img
        checkOutputSize(rs.width, rs.height)
        var l = computeLayout(img.width, img.height, rs.width, rs.height, rs.mode)
        if (!rs.allowUpscale && (l.scaledW > img.width || l.scaledH > img.height)) {
            val r = min(img.width.toDouble() / l.scaledW, img.height.toDouble() / l.scaledH)
            val sw = max(1, (l.scaledW * r).roundToInt())
            val sh = max(1, (l.scaledH * r).roundToInt())
            notes += "Enlarging is off, so the image was kept at its original size."
            val keepCanvas = !(rs.mode == FitMode.FIT_INSIDE || rs.mode == FitMode.STRETCH)
            val cw = if (keepCanvas) l.canvasW else sw
            val ch = if (keepCanvas) l.canvasH else sh
            l = Layout(sw, sh, cw, ch, (cw - sw) / 2, (ch - sh) / 2, 0, 0, false)
        }
        val src = Pix.of(img)
        val outPix = Resampler.resample(src, l.scaledW, l.scaledH, rs.upscale, rs.sharpen)
        var out = if (outPix === src) img else outPix.toBitmap()
        if (l.hasCrop) {
            out = Bitmap.createBitmap(out, l.cropLeft, l.cropTop, l.canvasW, l.canvasH)
        }
        if (out.width != l.canvasW || out.height != l.canvasH) {
            val bg = background(img, l.canvasW, l.canvasH, rs)
            val c = Canvas(bg)
            c.drawBitmap(out, l.offX.toFloat(), l.offY.toFloat(), null)
            bg.setHasAlpha(rs.background == Background.TRANSPARENT || out.hasAlpha())
            out = bg
        }
        return out
    }

    private fun background(src: Bitmap, cw: Int, ch: Int, rs: ResizeSettings): Bitmap {
        val out = Bitmap.createBitmap(cw, ch, Bitmap.Config.ARGB_8888)
        val c = Canvas(out)
        when (rs.background) {
            Background.TRANSPARENT -> Unit
            Background.WHITE -> c.drawColor(Color.WHITE)
            Background.BLACK -> c.drawColor(Color.BLACK)
            Background.CUSTOM -> c.drawColor(rs.customColor or -0x1000000)
            Background.BLUR -> drawBlurredBackground(c, src, cw, ch)
        }
        return out
    }

    private fun drawBlurredBackground(c: Canvas, src: Bitmap, cw: Int, ch: Int) {
        val k = min(1.0, 256.0 / max(cw, ch))
        val sw = max(1, (cw * k).roundToInt())
        val sh = max(1, (ch * k).roundToInt())
        // cover-fit the photo into the small canvas
        val srcRatio = src.width.toDouble() / src.height
        val dstRatio = cw.toDouble() / ch
        val srcRect = if (srcRatio > dstRatio) {
            val w = (src.height * dstRatio).roundToInt().coerceIn(1, src.width)
            val x = (src.width - w) / 2
            Rect(x, 0, x + w, src.height)
        } else {
            val h = (src.width / dstRatio).roundToInt().coerceIn(1, src.height)
            val y = (src.height - h) / 2
            Rect(0, y, src.width, y + h)
        }
        val small = Bitmap.createBitmap(sw, sh, Bitmap.Config.ARGB_8888)
        val sc = Canvas(small)
        sc.drawColor(Color.WHITE)
        sc.drawBitmap(src, srcRect, Rect(0, 0, sw, sh), Paint(Paint.FILTER_BITMAP_FLAG))
        val sigma = max(1.0, max(8.0, max(cw, ch) / 40.0) * k)
        val blurred = Resampler.gaussianBlur(Pix.of(small), sigma)
        // darken slightly so the photo stands out
        val p = blurred.px
        for (i in p.indices) {
            val v = p[i]
            val r = ((v shr 16) and 255) * 85 / 100
            val g = ((v shr 8) and 255) * 85 / 100
            val b = (v and 255) * 85 / 100
            p[i] = -0x1000000 or (r shl 16) or (g shl 8) or b
        }
        val bmp = blurred.toBitmap()
        c.drawBitmap(bmp, null, Rect(0, 0, cw, ch), Paint(Paint.FILTER_BITMAP_FLAG))
    }

    // ------------------------------------------------------------------ encoding

    fun flatten(img: Bitmap, color: Int = Color.WHITE): Bitmap {
        if (!hasTransparency(img)) {
            if (img.hasAlpha()) img.setHasAlpha(false)
            return img
        }
        val out = Bitmap.createBitmap(img.width, img.height, Bitmap.Config.ARGB_8888)
        val c = Canvas(out)
        c.drawColor(color)
        c.drawBitmap(img, 0f, 0f, null)
        out.setHasAlpha(false)
        return out
    }

    fun encode(img: Bitmap, os: OutputSettings, quality: Int? = null): ByteArray {
        val q = (quality ?: os.quality).coerceIn(1, 100)
        val bos = ByteArrayOutputStream()
        return when (os.fmt) {
            OutFormat.JPG -> {
                flatten(img).compress(Bitmap.CompressFormat.JPEG, q, bos)
                setJpegDpi(bos.toByteArray(), os.dpi)
            }
            OutFormat.PNG -> {
                val im = if (hasTransparency(img)) img else flatten(img)
                im.compress(Bitmap.CompressFormat.PNG, 100, bos)
                setPngDpi(bos.toByteArray(), os.dpi)
            }
            OutFormat.WEBP -> {
                val im = if (hasTransparency(img)) img else flatten(img)
                if (Build.VERSION.SDK_INT >= 30) {
                    if (os.webpLossless) im.compress(Bitmap.CompressFormat.WEBP_LOSSLESS, 75, bos)
                    else im.compress(Bitmap.CompressFormat.WEBP_LOSSY, q, bos)
                } else {
                    // Android 10 makes quality 100 lossless; older versions are always lossy.
                    @Suppress("DEPRECATION")
                    val f = Bitmap.CompressFormat.WEBP
                    im.compress(f, if (os.webpLossless) 100 else min(q, 99), bos)
                }
                bos.toByteArray()
            }
            OutFormat.PDF -> {
                val im = flatten(img)
                im.compress(Bitmap.CompressFormat.JPEG, q, bos)
                PdfWriter.singleImagePdf(bos.toByteArray(), im.width, im.height, os.dpi)
            }
        }
    }

    fun isLossy(os: OutputSettings): Boolean =
        os.fmt.lossy && !(os.fmt == OutFormat.WEBP && os.webpLossless)

    class Encoded(val data: ByteArray, val quality: Int?, val image: Bitmap)

    /** Encode; if a target size is set, find the highest quality that fits (shrinking if needed). */
    fun encodeToTarget(img: Bitmap, os: OutputSettings, notes: MutableList<String>): Encoded {
        val lossy = isLossy(os)
        if (os.targetKb <= 0 || !lossy) {
            if (os.targetKb > 0) notes += "Max file size works with JPG, PDF or lossy WEBP, not ${os.fmt.label}."
            return Encoded(encode(img, os), if (lossy) os.quality else null, img)
        }
        val limit = os.targetKb * 1024
        var work = img
        repeat(12) {
            var lo = 35
            var hi = min(98, max(os.quality, 35))
            val dataHi = encode(work, os, hi)
            if (dataHi.size <= limit) return Encoded(dataHi, hi, work)
            var best: Pair<ByteArray, Int>? = null
            while (lo <= hi) {
                val mid = (lo + hi) / 2
                val data = encode(work, os, mid)
                if (data.size <= limit) {
                    best = data to mid
                    lo = mid + 1
                } else hi = mid - 1
            }
            best?.let {
                if (work !== img) notes += "Reduced to ${work.width} × ${work.height} px to reach ${os.targetKb} KB."
                return Encoded(it.first, it.second, work)
            }
            val nw = max(1, (work.width * 0.9).toInt())
            val nh = max(1, (work.height * 0.9).toInt())
            work = Resampler.resizeBitmap(img, nw, nh)
        }
        notes += "Could not reach the target file size."
        return Encoded(encode(work, os, 35), 35, work)
    }

    /** Resize + encode an already edited (rotated/cropped) image. */
    fun finish(resized: Bitmap, os: OutputSettings, resizeNotes: List<String>): ProcessResult {
        val notes = resizeNotes.toMutableList()
        if (os.fmt == OutFormat.JPG && hasTransparency(resized)) {
            notes += "JPG has no transparency; background filled with white."
        }
        val enc = encodeToTarget(resized, os, notes)
        return ProcessResult(enc.image, enc.data, os.fmt, enc.quality, notes)
    }

    // ------------------------------------------------------------------ DPI metadata

    /** Write the print DPI into the JFIF header (inserting one if missing). */
    fun setJpegDpi(b: ByteArray, dpi: Int): ByteArray {
        val d = dpi.coerceIn(1, 65535)
        if (b.size < 4 || b[0] != 0xFF.toByte() || b[1] != 0xD8.toByte()) return b
        val hasJfif = b.size > 18 && b[2] == 0xFF.toByte() && b[3] == 0xE0.toByte() &&
            b[6] == 'J'.code.toByte() && b[7] == 'F'.code.toByte() && b[8] == 'I'.code.toByte() &&
            b[9] == 'F'.code.toByte() && b[10] == 0.toByte()
        if (hasJfif) {
            b[13] = 1
            b[14] = (d shr 8).toByte(); b[15] = d.toByte()
            b[16] = (d shr 8).toByte(); b[17] = d.toByte()
            return b
        }
        val app0 = byteArrayOf(
            0xFF.toByte(), 0xE0.toByte(), 0, 16, 'J'.code.toByte(), 'F'.code.toByte(), 'I'.code.toByte(),
            'F'.code.toByte(), 0, 1, 1, 1, (d shr 8).toByte(), d.toByte(), (d shr 8).toByte(), d.toByte(), 0, 0,
        )
        val out = ByteArray(b.size + app0.size)
        System.arraycopy(b, 0, out, 0, 2)
        System.arraycopy(app0, 0, out, 2, app0.size)
        System.arraycopy(b, 2, out, 2 + app0.size, b.size - 2)
        return out
    }

    /** Insert a pHYs chunk (pixels per metre) after IHDR. */
    fun setPngDpi(b: ByteArray, dpi: Int): ByteArray {
        if (b.size < 33 || b[1] != 'P'.code.toByte() || b[2] != 'N'.code.toByte()) return b
        var pos = 8
        while (pos + 8 <= b.size) {
            val len = ((b[pos].toInt() and 255) shl 24) or ((b[pos + 1].toInt() and 255) shl 16) or
                ((b[pos + 2].toInt() and 255) shl 8) or (b[pos + 3].toInt() and 255)
            val type = String(b, pos + 4, 4, Charsets.US_ASCII)
            if (type == "pHYs") return b
            if (type == "IDAT") break
            pos += 12 + len
        }
        val ppm = (dpi / 0.0254).roundToInt()
        val body = ByteArray(13)
        "pHYs".toByteArray(Charsets.US_ASCII).copyInto(body, 0)
        for (i in 0..1) {
            body[4 + i * 4] = (ppm shr 24).toByte()
            body[5 + i * 4] = (ppm shr 16).toByte()
            body[6 + i * 4] = (ppm shr 8).toByte()
            body[7 + i * 4] = ppm.toByte()
        }
        body[12] = 1
        val crc = CRC32().apply { update(body) }.value
        val chunk = ByteArray(21)
        chunk[3] = 9
        body.copyInto(chunk, 4)
        chunk[17] = (crc shr 24).toByte(); chunk[18] = (crc shr 16).toByte()
        chunk[19] = (crc shr 8).toByte(); chunk[20] = crc.toByte()
        val at = 33 // signature (8) + IHDR chunk (25)
        val out = ByteArray(b.size + chunk.size)
        System.arraycopy(b, 0, out, 0, at)
        System.arraycopy(chunk, 0, out, at, chunk.size)
        System.arraycopy(b, at, out, at + chunk.size, b.size - at)
        return out
    }

    // ------------------------------------------------------------------ names & sizes

    fun stem(name: String): String {
        val n = name.substringAfterLast('/')
        val i = n.lastIndexOf('.')
        val s = if (i > 0) n.substring(0, i) else n
        return s.ifBlank { "image" }.replace(Regex("[\\\\/:*?\"<>|]"), "_")
    }

    fun autoFilename(srcName: String, w: Int, h: Int, fmt: OutFormat): String =
        "${stem(srcName)}_${w}x${h}${fmt.ext}"

    fun humanSize(n: Long): String = when {
        n < 1024 -> "$n B"
        n < 1024 * 1024 -> String.format(Locale.US, "%.0f KB", n / 1024.0)
        else -> String.format(Locale.US, "%.2f MB", n / 1024.0 / 1024.0)
    }

    // ------------------------------------------------------------------ close-up mapping

    /**
     * Map a point in the result to the oriented (uncropped) source.
     * Returns (x, y, k) where k = result pixels per source pixel.
     */
    fun resultToSource(
        rx: Float, ry: Float, srcW: Int, srcH: Int, st: EditState, rs: ResizeSettings, resultW: Int,
    ): Triple<Float, Float, Float> {
        val (ow, oh) = orientedSize(srcW, srcH, st)
        val c = clampCrop(st.crop, ow, oh)
        val cx = c?.x ?: 0
        val cy = c?.y ?: 0
        val bw = c?.w ?: ow
        val bh = c?.h ?: oh
        val l = if (rs.enabled && rs.width > 0 && rs.height > 0) computeLayout(bw, bh, rs.width, rs.height, rs.mode)
        else Layout(bw, bh, bw, bh, 0, 0, 0, 0, false)
        val f = resultW.toFloat() / max(1, l.canvasW)
        var x = rx / f
        var y = ry / f
        if (l.hasCrop) {
            x += l.cropLeft; y += l.cropTop
        } else {
            x -= l.offX; y -= l.offY
        }
        val sx = l.scaledW.toFloat() / bw
        val sy = l.scaledH.toFloat() / bh
        return Triple(cx + x / sx, cy + y / sy, f * sx)
    }
}

/** Minimal one-page PDF holding a JPEG (like Pillow's PDF output). */
object PdfWriter {
    fun singleImagePdf(jpeg: ByteArray, w: Int, h: Int, dpi: Int): ByteArray {
        val pw = w * 72.0 / dpi
        val ph = h * 72.0 / dpi
        val out = ByteArrayOutputStream()
        val offsets = IntArray(6)
        fun ascii(s: String) = out.write(s.toByteArray(Charsets.ISO_8859_1))
        fun num(v: Double) = String.format(Locale.US, "%.3f", v)
        ascii("%PDF-1.4\n%âãÏÓ\n")
        offsets[1] = out.size()
        ascii("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
        offsets[2] = out.size()
        ascii("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
        offsets[3] = out.size()
        ascii(
            "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(pw)} ${num(ph)}] " +
                "/Resources << /XObject << /Im0 4 0 R >> /ProcSet [/PDF /ImageC] >> /Contents 5 0 R >>\nendobj\n"
        )
        offsets[4] = out.size()
        ascii(
            "4 0 obj\n<< /Type /XObject /Subtype /Image /Width $w /Height $h /ColorSpace /DeviceRGB " +
                "/BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.size} >>\nstream\n"
        )
        out.write(jpeg)
        ascii("\nendstream\nendobj\n")
        val content = "q ${num(pw)} 0 0 ${num(ph)} 0 0 cm /Im0 Do Q"
        offsets[5] = out.size()
        ascii("5 0 obj\n<< /Length ${content.length} >>\nstream\n$content\nendstream\nendobj\n")
        val xref = out.size()
        ascii("xref\n0 6\n0000000000 65535 f \n")
        for (i in 1..5) ascii(String.format(Locale.US, "%010d 00000 n \n", offsets[i]))
        ascii("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n$xref\n%EOF\n")
        return out.toByteArray()
    }
}
