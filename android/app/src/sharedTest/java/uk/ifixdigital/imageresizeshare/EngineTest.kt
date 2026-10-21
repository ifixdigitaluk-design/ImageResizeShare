package uk.ifixdigital.imageresizeshare

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.pdf.PdfRenderer
import android.os.ParcelFileDescriptor
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import uk.ifixdigital.imageresizeshare.core.Background
import uk.ifixdigital.imageresizeshare.core.Crop
import uk.ifixdigital.imageresizeshare.core.EditState
import uk.ifixdigital.imageresizeshare.core.FitMode
import uk.ifixdigital.imageresizeshare.core.ImageEngine
import uk.ifixdigital.imageresizeshare.core.OutFormat
import uk.ifixdigital.imageresizeshare.core.OutputSettings
import uk.ifixdigital.imageresizeshare.core.Pix
import uk.ifixdigital.imageresizeshare.core.Proof
import uk.ifixdigital.imageresizeshare.core.ProofSettings
import uk.ifixdigital.imageresizeshare.core.ResizeSettings
import uk.ifixdigital.imageresizeshare.core.Resampler
import uk.ifixdigital.imageresizeshare.core.SizeUnit
import uk.ifixdigital.imageresizeshare.core.Upscale
import java.io.File
import kotlin.math.abs
import kotlin.random.Random

/** Ports of the desktop engine tests (tests/test_imaging.py). */
@RunWith(AndroidJUnit4::class)
class EngineTest {
    private val ctx = InstrumentationRegistry.getInstrumentation().targetContext

    private fun photo(w: Int = 400, h: Int = 300, alpha: Boolean = false): Bitmap {
        val px = IntArray(w * h)
        val rnd = Random(1)
        for (y in 0 until h) for (x in 0 until w) {
            val r = (x * 255 / w + rnd.nextInt(-4, 5)).coerceIn(0, 255)
            val g = (y * 255 / h + rnd.nextInt(-4, 5)).coerceIn(0, 255)
            val b = ((r + g) / 2).coerceIn(0, 255)
            px[y * w + x] = Color.rgb(r, g, b)
        }
        val bmp = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        bmp.setPixels(px, 0, w, 0, 0, w, h)
        val c = Canvas(bmp)
        val p = Paint().apply { color = Color.BLACK; strokeWidth = 1f }
        for (x in 0 until w step 20) c.drawLine(x.toFloat(), 0f, x.toFloat(), h.toFloat(), p)
        p.color = Color.WHITE
        p.textSize = 14f
        c.drawText("Sharp text 123", 10f, 24f, p)
        if (alpha) {
            val out = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
            val oc = Canvas(out)
            val paint = Paint(Paint.ANTI_ALIAS_FLAG)
            paint.shader = android.graphics.BitmapShader(bmp, android.graphics.Shader.TileMode.CLAMP, android.graphics.Shader.TileMode.CLAMP)
            oc.drawOval(20f, 20f, w - 20f, h - 20f, paint)
            return out
        }
        bmp.setHasAlpha(false)
        return bmp
    }

    private fun edgeEnergy(b: Bitmap): Double {
        val p = Pix.of(b)
        var s = 0.0
        fun lum(v: Int) = ((v shr 16 and 255) * 299 + (v shr 8 and 255) * 587 + (v and 255) * 114) / 1000.0
        for (y in 0 until p.h - 1) for (x in 0 until p.w - 1) {
            val c = lum(p.px[y * p.w + x])
            s += abs(c - lum(p.px[y * p.w + x + 1])) + abs(c - lum(p.px[(y + 1) * p.w + x]))
        }
        return s / (p.w * p.h)
    }

    @Test
    fun modesSizes() {
        val expected = mapOf(
            FitMode.FIT_PAD to (1080 to 1080), FitMode.FILL to (1080 to 1080),
            FitMode.STRETCH to (1080 to 1080), FitMode.FIT_INSIDE to (1080 to 810),
        )
        for ((mode, exp) in expected) {
            val out = ImageEngine.resizeImage(photo(), ResizeSettings(width = 1080, height = 1080, mode = mode), mutableListOf())
            assertEquals(mode.name, exp, out.width to out.height)
        }
    }

    @Test
    fun fitPadKeepsWholeImage() {
        val src = Bitmap.createBitmap(400, 200, Bitmap.Config.ARGB_8888).apply { eraseColor(Color.RED) }
        val out = ImageEngine.resizeImage(
            src, ResizeSettings(width = 400, height = 400, mode = FitMode.FIT_PAD, background = Background.BLACK), mutableListOf(),
        )
        assertEquals(Color.BLACK, out.getPixel(200, 0))
        assertTrue(Color.red(out.getPixel(200, 200)) > 240)
    }

    @Test
    fun blurredBackground() {
        val out = ImageEngine.resizeImage(
            photo(), ResizeSettings(width = 1080, height = 1920, mode = FitMode.FIT_PAD, background = Background.BLUR), mutableListOf(),
        )
        assertEquals(1080, out.width)
        assertEquals(1920, out.height)
        assertEquals(255, Color.alpha(out.getPixel(5, 5)))
    }

    @Test
    fun enhancedSharperThanStandard() {
        val small = Pix.of(photo(200, 150))
        val std = Resampler.resample(small, 800, 600, Upscale.STANDARD, -1).toBitmap()
        val enh = Resampler.resample(small, 800, 600, Upscale.ENHANCED, -1).toBitmap()
        assertTrue(edgeEnergy(enh) > edgeEnergy(std) * 1.05)
    }

    @Test
    fun enhancedHasNoHalos() {
        val img = Bitmap.createBitmap(60, 60, Bitmap.Config.ARGB_8888).apply { eraseColor(Color.rgb(60, 60, 60)) }
        Canvas(img).drawRect(20f, 20f, 41f, 41f, Paint().apply { color = Color.rgb(200, 200, 200) })
        val out = Resampler.resample(Pix.of(img), 240, 240, Upscale.ENHANCED, -1)
        val lan = Resampler.resize(Pix.of(img), 240, 240)
        val mx = { p: Pix -> p.px.maxOf { it and 255 } }
        val mn = { p: Pix -> p.px.minOf { it and 255 } }
        assertTrue(mx(out) <= mx(lan) && mn(out) >= mn(lan))
    }

    @Test
    fun downscaleKeepsColour() {
        val src = Bitmap.createBitmap(3000, 2000, Bitmap.Config.ARGB_8888).apply { eraseColor(Color.rgb(30, 120, 200)) }
        val out = Resampler.resample(Pix.of(src), 300, 200, Upscale.ENHANCED, -1)
        val p = out.px[100 * 300 + 150]
        assertEquals(30, p shr 16 and 255)
        assertEquals(120, p shr 8 and 255)
        assertEquals(200, p and 255)
    }

    @Test
    fun rotationAndCrop() {
        val st = EditState(rotation = 90, crop = Crop(10, 20, 100, 50))
        assertEquals(300 to 400, ImageEngine.orientedSize(400, 300, st))
        val out = ImageEngine.applyCrop(ImageEngine.applyOrientation(photo(), st), st)
        assertEquals(100 to 50, out.width to out.height)
        assertEquals(100 to 50, ImageEngine.editedSize(400, 300, st))
    }

    @Test
    fun cropClamp() {
        assertNull(ImageEngine.clampCrop(Crop(-5, -5, 1000, 1000), 100, 100))
        assertEquals(Crop(90, 90, 10, 10), ImageEngine.clampCrop(Crop(90, 90, 50, 50), 100, 100))
    }

    @Test
    fun units() {
        assertEquals(413, ImageEngine.toPixels(35.0, SizeUnit.MM, 300, 0))
        assertEquals(531, ImageEngine.toPixels(45.0, SizeUnit.MM, 300, 0))
        assertEquals(600, ImageEngine.toPixels(2.0, SizeUnit.IN, 300, 0))
        assertEquals(500, ImageEngine.toPixels(50.0, SizeUnit.PERCENT, 300, 1000))
        assertEquals(2.0, ImageEngine.fromPixels(600, SizeUnit.IN, 300, 0), 1e-9)
    }

    /** What the user sees after applying [st] to [img]. */
    private fun seen(img: Bitmap, st: EditState): IntArray =
        Pix.of(ImageEngine.applyCrop(ImageEngine.applyOrientation(img, st), st)).px

    private fun transform(b: Bitmap, op: String): Bitmap {
        val m = android.graphics.Matrix()
        when (op) {
            "cw" -> m.postRotate(90f)
            "ccw" -> m.postRotate(270f)
            "fh" -> m.postScale(-1f, 1f)
            else -> m.postScale(1f, -1f)
        }
        return Bitmap.createBitmap(b, 0, 0, b.width, b.height, m, false)
    }

    @Test
    fun rotateFlipComposeLikeUserSees() {
        val img = photo(120, 80)
        var st = EditState()
        var view = img
        for (op in listOf("cw", "fh", "cw", "fv", "ccw", "fh", "cw")) {
            st = when (op) {
                "cw" -> ImageEngine.rotateState(st, 120, 80, true)
                "ccw" -> ImageEngine.rotateState(st, 120, 80, false)
                "fh" -> ImageEngine.flipState(st, 120, 80, true)
                else -> ImageEngine.flipState(st, 120, 80, false)
            }
            view = transform(view, op)
            assertArrayEquals(op, Pix.of(view).px, seen(img, st))
        }
    }

    @Test
    fun cropFollowsRotationAndFlip() {
        val img = photo(120, 80)
        var st = EditState(crop = Crop(10, 5, 40, 30))
        var view = Bitmap.createBitmap(img, 10, 5, 40, 30)
        for (op in listOf("cw", "fh", "ccw", "fv", "cw")) {
            st = when (op) {
                "cw" -> ImageEngine.rotateState(st, 120, 80, true)
                "ccw" -> ImageEngine.rotateState(st, 120, 80, false)
                "fh" -> ImageEngine.flipState(st, 120, 80, true)
                else -> ImageEngine.flipState(st, 120, 80, false)
            }
            view = transform(view, op)
            assertArrayEquals(op, Pix.of(view).px, seen(img, st))
        }
    }

    @Test
    fun encodeFormats() {
        val img = photo()
        for (f in OutFormat.entries) {
            val data = ImageEngine.encode(img, OutputSettings(fmt = f, dpi = 300))
            assertTrue(f.name, data.size > 100)
            when (f) {
                OutFormat.PDF -> {
                    val s = String(data, Charsets.ISO_8859_1)
                    assertTrue(s.startsWith("%PDF-1.4"))
                    assertTrue(s.endsWith("%EOF\n"))
                    assertTrue(s.contains("/DCTDecode") && s.contains("/MediaBox [0 0 96.000 72.000]"))
                    if (android.os.Build.FINGERPRINT == "robolectric") continue
                    val file = File(ctx.cacheDir, "t.pdf").apply { writeBytes(data) }
                    PdfRenderer(ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)).use { r ->
                        assertEquals(1, r.pageCount)
                        r.openPage(0).use { page ->
                            assertEquals(96, page.width)   // 400 px at 300 DPI = 96 pt
                            assertEquals(72, page.height)
                        }
                    }
                }
                else -> {
                    val b = BitmapFactory.decodeByteArray(data, 0, data.size)
                    assertEquals(f.name, 400 to 300, b.width to b.height)
                }
            }
            if (f == OutFormat.JPG) {
                assertEquals(1, data[13].toInt())
                assertEquals(300, ((data[14].toInt() and 255) shl 8) or (data[15].toInt() and 255))
            }
            if (f == OutFormat.PNG) assertTrue(String(data, 0, 80, Charsets.ISO_8859_1).contains("pHYs"))
        }
    }

    @Test
    fun transparencyKeptInPngAndFlattenedInJpg() {
        val img = photo(alpha = true)
        val png = ImageEngine.encode(img, OutputSettings(fmt = OutFormat.PNG))
        val pb = BitmapFactory.decodeByteArray(png, 0, png.size)
        assertEquals(0, Color.alpha(pb.getPixel(0, 0)))
        val jpg = ImageEngine.encode(img, OutputSettings(fmt = OutFormat.JPG))
        val jb = BitmapFactory.decodeByteArray(jpg, 0, jpg.size)
        val c = jb.getPixel(0, 0)
        assertTrue(Color.red(c) + Color.green(c) + Color.blue(c) > 740)
    }

    @Test
    fun targetSize() {
        val notes = mutableListOf<String>()
        val enc = ImageEngine.encodeToTarget(photo(1600, 1200), OutputSettings(fmt = OutFormat.JPG, quality = 95, targetKb = 120), notes)
        assertTrue(enc.data.size <= 120 * 1024)
    }

    @Test
    fun targetSizeShrinksWhenNeeded() {
        val w = 1500
        val rnd = Random(0)
        val px = IntArray(w * w) { Color.rgb(rnd.nextInt(256), rnd.nextInt(256), rnd.nextInt(256)) }
        val img = Bitmap.createBitmap(w, w, Bitmap.Config.ARGB_8888).apply { setPixels(px, 0, w, 0, 0, w, w); setHasAlpha(false) }
        val notes = mutableListOf<String>()
        val enc = ImageEngine.encodeToTarget(img, OutputSettings(fmt = OutFormat.JPG, targetKb = 60), notes)
        assertTrue(enc.data.size <= 60 * 1024)
        assertTrue(enc.image.width < w)
        assertTrue(notes.isNotEmpty())
    }

    @Test
    fun noUpscaleOption() {
        val notes = mutableListOf<String>()
        val out = ImageEngine.resizeImage(photo(), ResizeSettings(width = 800, height = 600, allowUpscale = false, mode = FitMode.FIT_INSIDE), notes)
        assertEquals(400 to 300, out.width to out.height)
        assertTrue(notes.isNotEmpty())
    }

    @Test
    fun pointMapping() {
        // Upscale 2x: the centre maps back to the centre, k = 2
        val (x, y, k) = ImageEngine.resultToSource(
            640f, 480f, 640, 480, EditState(), ResizeSettings(width = 1280, height = 960), 1280,
        )
        assertEquals(320f, x, 0.5f)
        assertEquals(240f, y, 0.5f)
        assertEquals(2f, k, 0.01f)
        // With a crop, the centre of the result is the centre of the crop
        for (mode in FitMode.entries) {
            val st = EditState(crop = Crop(50, 40, 200, 100))
            val rs = ResizeSettings(width = 600, height = 600, mode = mode)
            val out = ImageEngine.resizeImage(ImageEngine.applyCrop(photo(), st), rs, mutableListOf())
            val (cx, cy, kk) = ImageEngine.resultToSource(out.width / 2f, out.height / 2f, 400, 300, st, rs, out.width)
            assertEquals(mode.name, 150f, cx, 1f)
            assertEquals(mode.name, 90f, cy, 1f)
            assertTrue(kk > 1)
        }
    }

    @Test
    fun proofSheet() {
        val r = Proof.render(ctx, photo(895, 740), ProofSettings(widthIn = 125.0, heightIn = 104.0, widthPx = 955))
        assertEquals(955, r.bitmap.width)
        assertTrue(r.bitmap.height > 800)
        assertEquals("90.28 Sq.Ft", Proof.areaLabel(125.0, 104.0))
        assertEquals("125”x 104”", Proof.sizeLabel(125.0, 104.0))
        assertEquals("10'5” x 8'8”", Proof.sizeLabel(125.0, 104.0, "ft"))
        val r2 = Proof.render(
            ctx, photo(400, 300),
            ProofSettings(widthIn = 100.0, heightIn = 50.0, closeup = true, watermark = "SAMPLE", footer = "Shop", fill = false, widthPx = 800),
        )
        val box = r2.designBox
        assertEquals(2.0, box.width().toDouble() / box.height(), 0.02)
    }
}
