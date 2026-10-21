package uk.ifixdigital.imageresizeshare.core

import android.graphics.Bitmap
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/** An image as unpremultiplied ARGB ints (what Bitmap.getPixels returns). */
class Pix(val w: Int, val h: Int, val px: IntArray) {

    fun hasTransparency(): Boolean {
        for (p in px) if ((p ushr 24) != 255) return true
        return false
    }

    fun toBitmap(): Bitmap {
        val b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        b.setPixels(px, 0, w, 0, 0, w, h)
        b.setHasAlpha(hasTransparency())
        return b
    }

    companion object {
        fun of(bmp: Bitmap): Pix {
            val a = IntArray(bmp.width * bmp.height)
            bmp.getPixels(a, 0, bmp.width, 0, 0, bmp.width, bmp.height)
            return Pix(bmp.width, bmp.height, a)
        }
    }
}

/**
 * Quality core, a port of the desktop engine:
 *  * Lanczos-3 resampling (same filter and support as Pillow's LANCZOS),
 *    done on premultiplied colour so transparent edges get no dark fringes,
 *    with an integer pre-reduction for very large reductions ("reducing gap 3").
 *  * Enlarging in <=2x steps followed by size-aware unsharp masking with
 *    anti-halo clamping ("Enhanced").
 */
object Resampler {
    private const val PREC = 20
    private const val ONE = 1 shl PREC
    private const val HALF = 1 shl (PREC - 1)

    private class Coeffs(val start: IntArray, val count: IntArray, val weights: IntArray, val stride: Int)

    private fun lanczos3(x: Double): Double {
        if (x == 0.0) return 1.0
        if (x <= -3.0 || x >= 3.0) return 0.0
        val px = PI * x
        return 3.0 * sin(px) * sin(px / 3.0) / (px * px)
    }

    private fun coeffs(inSize: Int, outSize: Int): Coeffs {
        val scale = inSize.toDouble() / outSize
        val filterScale = max(1.0, scale)
        val support = 3.0 * filterScale
        val stride = ceil(support).toInt() * 2 + 1
        val start = IntArray(outSize)
        val count = IntArray(outSize)
        val weights = IntArray(outSize * stride)
        val tmp = DoubleArray(stride)
        for (xx in 0 until outSize) {
            val center = (xx + 0.5) * scale
            var xmin = (center - support + 0.5).toInt()
            if (xmin < 0) xmin = 0
            var xmax = (center + support + 0.5).toInt()
            if (xmax > inSize) xmax = inSize
            val n = min(xmax - xmin, stride)
            var total = 0.0
            for (x in 0 until n) {
                val v = lanczos3((x + xmin - center + 0.5) / filterScale)
                tmp[x] = v
                total += v
            }
            if (total == 0.0) total = 1.0
            val base = xx * stride
            for (x in 0 until n) weights[base + x] = (tmp[x] / total * ONE).roundToInt()
            start[xx] = xmin
            count[xx] = n
        }
        return Coeffs(start, count, weights, stride)
    }

    private fun clamp8(v: Int): Int = if (v < 0) 0 else if (v > 255) 255 else v

    private fun horizontal(src: Pix, outW: Int): Pix {
        val c = coeffs(src.w, outW)
        val out = IntArray(outW * src.h)
        val sp = src.px
        val inW = src.w
        for (y in 0 until src.h) {
            val row = y * inW
            val orow = y * outW
            for (x in 0 until outW) {
                var a = HALF
                var r = HALF
                var g = HALF
                var b = HALF
                val s = row + c.start[x]
                val n = c.count[x]
                val wo = x * c.stride
                for (k in 0 until n) {
                    val p = sp[s + k]
                    val wt = c.weights[wo + k]
                    a += (p ushr 24) * wt
                    r += ((p shr 16) and 255) * wt
                    g += ((p shr 8) and 255) * wt
                    b += (p and 255) * wt
                }
                out[orow + x] = (clamp8(a shr PREC) shl 24) or (clamp8(r shr PREC) shl 16) or
                    (clamp8(g shr PREC) shl 8) or clamp8(b shr PREC)
            }
        }
        return Pix(outW, src.h, out)
    }

    private fun vertical(src: Pix, outH: Int): Pix {
        val c = coeffs(src.h, outH)
        val w = src.w
        val sp = src.px
        val out = IntArray(w * outH)
        val accA = IntArray(w)
        val accR = IntArray(w)
        val accG = IntArray(w)
        val accB = IntArray(w)
        for (y in 0 until outH) {
            accA.fill(HALF); accR.fill(HALF); accG.fill(HALF); accB.fill(HALF)
            val s = c.start[y]
            val n = c.count[y]
            val wo = y * c.stride
            for (k in 0 until n) {
                val wt = c.weights[wo + k]
                val row = (s + k) * w
                for (x in 0 until w) {
                    val p = sp[row + x]
                    accA[x] += (p ushr 24) * wt
                    accR[x] += ((p shr 16) and 255) * wt
                    accG[x] += ((p shr 8) and 255) * wt
                    accB[x] += (p and 255) * wt
                }
            }
            val orow = y * w
            for (x in 0 until w) {
                out[orow + x] = (clamp8(accA[x] shr PREC) shl 24) or (clamp8(accR[x] shr PREC) shl 16) or
                    (clamp8(accG[x] shr PREC) shl 8) or clamp8(accB[x] shr PREC)
            }
        }
        return Pix(w, outH, out)
    }

    private fun premultiplied(src: Pix): Pix {
        val o = IntArray(src.px.size)
        val sp = src.px
        for (i in o.indices) {
            val p = sp[i]
            val a = p ushr 24
            o[i] = when (a) {
                255 -> p
                0 -> 0
                else -> {
                    val r = (((p shr 16) and 255) * a + 127) / 255
                    val g = (((p shr 8) and 255) * a + 127) / 255
                    val b = ((p and 255) * a + 127) / 255
                    (a shl 24) or (r shl 16) or (g shl 8) or b
                }
            }
        }
        return Pix(src.w, src.h, o)
    }

    private fun unpremultiplyInPlace(px: IntArray) {
        for (i in px.indices) {
            val p = px[i]
            val a = p ushr 24
            if (a == 255) continue
            if (a == 0) {
                px[i] = 0
                continue
            }
            val r = min(255, (((p shr 16) and 255) * 255 + a / 2) / a)
            val g = min(255, (((p shr 8) and 255) * 255 + a / 2) / a)
            val b = min(255, ((p and 255) * 255 + a / 2) / a)
            px[i] = (a shl 24) or (r shl 16) or (g shl 8) or b
        }
    }

    /** Average fx × fy blocks (like Pillow's Image.reduce). */
    private fun boxReduce(src: Pix, fx: Int, fy: Int): Pix {
        val ow = (src.w + fx - 1) / fx
        val oh = (src.h + fy - 1) / fy
        val out = IntArray(ow * oh)
        val sa = IntArray(ow)
        val sr = IntArray(ow)
        val sg = IntArray(ow)
        val sb = IntArray(ow)
        val cnt = IntArray(ow)
        val sp = src.px
        for (oy in 0 until oh) {
            sa.fill(0); sr.fill(0); sg.fill(0); sb.fill(0); cnt.fill(0)
            val ys = oy * fy
            val ye = min(src.h, ys + fy)
            for (y in ys until ye) {
                val row = y * src.w
                for (x in 0 until src.w) {
                    val ox = x / fx
                    val p = sp[row + x]
                    sa[ox] += p ushr 24
                    sr[ox] += (p shr 16) and 255
                    sg[ox] += (p shr 8) and 255
                    sb[ox] += p and 255
                    cnt[ox]++
                }
            }
            val orow = oy * ow
            for (ox in 0 until ow) {
                val n = cnt[ox]
                val h = n / 2
                out[orow + ox] = (((sa[ox] + h) / n) shl 24) or (((sr[ox] + h) / n) shl 16) or
                    (((sg[ox] + h) / n) shl 8) or ((sb[ox] + h) / n)
            }
        }
        return Pix(ow, oh, out)
    }

    /** Lanczos-3 resize to an exact size. */
    fun resize(src: Pix, tw: Int, th: Int): Pix {
        if (tw == src.w && th == src.h) return Pix(src.w, src.h, src.px.copyOf())
        val alpha = src.hasTransparency()
        var work = if (alpha) premultiplied(src) else src
        val fx = max(1, (work.w / tw.toDouble() / 3.0).toInt())
        val fy = max(1, (work.h / th.toDouble() / 3.0).toInt())
        if (fx > 1 || fy > 1) work = boxReduce(work, fx, fy)
        var out = work
        if (out.w != tw) out = horizontal(out, tw)
        if (out.h != th) out = vertical(out, th)
        if (out === src) out = Pix(src.w, src.h, src.px.copyOf())
        if (alpha) unpremultiplyInPlace(out.px)
        return out
    }

    fun autoSharpenAmount(scale: Double): Int = when {
        scale <= 0.5 -> 25
        scale < 1.0 -> 15
        scale <= 1.05 -> 0
        else -> min(80.0, 25 + (scale - 1.0) * 20).toInt()
    }

    private fun gaussianKernel(sigma: Double, radius: Int): IntArray {
        val d = DoubleArray(2 * radius + 1)
        var total = 0.0
        for (i in d.indices) {
            val x = (i - radius).toDouble()
            d[i] = exp(-(x * x) / (2 * sigma * sigma))
            total += d[i]
        }
        val k = IntArray(d.size)
        var sum = 0
        for (i in d.indices) {
            k[i] = (d[i] / total * 65536).roundToInt()
            sum += k[i]
        }
        k[radius] += 65536 - sum   // exact normalisation
        return k
    }

    /**
     * Unsharp mask (Pillow semantics: radius = sigma, percent, threshold 1)
     * with optional anti-halo clamping to the local 3×3 min/max of the
     * unsharpened image. Works in place, in horizontal bands, so memory use
     * stays small even for large images. Alpha is left untouched.
     */
    fun unsharpInPlace(img: Pix, amount: Int, scale: Double) {
        if (amount <= 0) return
        val sigma = if (scale < 1) 0.8 else min(2.2, 0.6 + 0.3 * scale)
        val percent = 40 + (amount * 1.6).toInt()
        val antihalo = scale > 1
        val kr = max(1, ceil(sigma * 3.0).toInt())
        val kernel = gaussianKernel(sigma, kr)
        val m = kr + 1
        val w = img.w
        val h = img.h
        val px = img.px
        val band = 64
        val maxRows = band + 2 * m
        val buf = IntArray(maxRows * w)     // original rows of the band (+ margins)
        val hb = IntArray(maxRows * w)      // horizontally blurred rows
        val hmin = if (antihalo) IntArray(maxRows * w) else IntArray(0)
        val hmax = if (antihalo) IntArray(maxRows * w) else IntArray(0)
        val prevTail = IntArray(m * w)
        var prevTailStart = 0
        val ksz = kernel.size

        var y0 = 0
        while (y0 < h) {
            val y1 = min(h, y0 + band)
            val b0 = max(0, y0 - m)
            val b1 = min(h, y1 + m)
            val rows = b1 - b0
            for (r in b0 until b1) {
                val dst = (r - b0) * w
                if (r < y0) System.arraycopy(prevTail, (r - prevTailStart) * w, buf, dst, w)
                else System.arraycopy(px, r * w, buf, dst, w)
            }
            // horizontal pass (blur + min/max)
            for (r in 0 until rows) {
                val row = r * w
                for (x in 0 until w) {
                    var sr = 32768
                    var sg = 32768
                    var sb = 32768
                    for (k in 0 until ksz) {
                        var xx = x + k - kr
                        if (xx < 0) xx = 0 else if (xx >= w) xx = w - 1
                        val p = buf[row + xx]
                        val wt = kernel[k]
                        sr += ((p shr 16) and 255) * wt
                        sg += ((p shr 8) and 255) * wt
                        sb += (p and 255) * wt
                    }
                    hb[row + x] = (clamp8(sr shr 16) shl 16) or (clamp8(sg shr 16) shl 8) or clamp8(sb shr 16)
                    if (antihalo) {
                        val pl = buf[row + max(0, x - 1)]
                        val pc = buf[row + x]
                        val pr = buf[row + min(w - 1, x + 1)]
                        hmin[row + x] = minRgb(minRgb(pl, pc), pr)
                        hmax[row + x] = maxRgb(maxRgb(pl, pc), pr)
                    }
                }
            }
            // vertical pass + sharpen, rows y0 until y1
            for (y in y0 until y1) {
                val outRow = y * w
                val bufRow = (y - b0) * w
                val up = (max(0, y - 1) - b0) * w
                val dn = (min(h - 1, y + 1) - b0) * w
                for (x in 0 until w) {
                    var sr = 32768
                    var sg = 32768
                    var sb = 32768
                    for (k in 0 until ksz) {
                        var yy = y + k - kr
                        if (yy < 0) yy = 0 else if (yy >= h) yy = h - 1
                        val p = hb[(yy - b0) * w + x]
                        val wt = kernel[k]
                        sr += ((p shr 16) and 255) * wt
                        sg += ((p shr 8) and 255) * wt
                        sb += (p and 255) * wt
                    }
                    val o = buf[bufRow + x]
                    var r = sharpen((o shr 16) and 255, clamp8(sr shr 16), percent)
                    var g = sharpen((o shr 8) and 255, clamp8(sg shr 16), percent)
                    var b = sharpen(o and 255, clamp8(sb shr 16), percent)
                    if (antihalo) {
                        val lo = minRgb(minRgb(hmin[up + x], hmin[bufRow + x]), hmin[dn + x])
                        val hi = maxRgb(maxRgb(hmax[up + x], hmax[bufRow + x]), hmax[dn + x])
                        r = r.coerceIn((lo shr 16) and 255, (hi shr 16) and 255)
                        g = g.coerceIn((lo shr 8) and 255, (hi shr 8) and 255)
                        b = b.coerceIn(lo and 255, hi and 255)
                    }
                    px[outRow + x] = (o and -0x1000000) or (r shl 16) or (g shl 8) or b
                }
            }
            prevTailStart = max(0, y1 - m)
            for (r in prevTailStart until y1) {
                System.arraycopy(buf, (r - b0) * w, prevTail, (r - prevTailStart) * w, w)
            }
            y0 = y1
        }
    }

    private fun sharpen(o: Int, blurred: Int, percent: Int): Int {
        val diff = o - blurred
        if (diff == 0) return o
        return clamp8(o + diff * percent / 100)
    }

    private fun minRgb(a: Int, b: Int): Int =
        (min((a shr 16) and 255, (b shr 16) and 255) shl 16) or
            (min((a shr 8) and 255, (b shr 8) and 255) shl 8) or min(a and 255, b and 255)

    private fun maxRgb(a: Int, b: Int): Int =
        (max((a shr 16) and 255, (b shr 16) and 255) shl 16) or
            (max((a shr 8) and 255, (b shr 8) and 255) shl 8) or max(a and 255, b and 255)

    /** Simple separable Gaussian blur (used on small images, e.g. the blurred background). */
    fun gaussianBlur(src: Pix, sigma: Double): Pix {
        val kr = max(1, ceil(sigma * 3.0).toInt())
        val kernel = gaussianKernel(sigma, kr)
        val w = src.w
        val h = src.h
        val tmp = IntArray(w * h)
        val out = IntArray(w * h)
        val sp = src.px
        for (y in 0 until h) {
            val row = y * w
            for (x in 0 until w) {
                var sr = 32768
                var sg = 32768
                var sb = 32768
                for (k in kernel.indices) {
                    val xx = (x + k - kr).coerceIn(0, w - 1)
                    val p = sp[row + xx]
                    val wt = kernel[k]
                    sr += ((p shr 16) and 255) * wt
                    sg += ((p shr 8) and 255) * wt
                    sb += (p and 255) * wt
                }
                tmp[row + x] = (sp[row + x] and -0x1000000) or (clamp8(sr shr 16) shl 16) or
                    (clamp8(sg shr 16) shl 8) or clamp8(sb shr 16)
            }
        }
        for (y in 0 until h) {
            for (x in 0 until w) {
                var sr = 32768
                var sg = 32768
                var sb = 32768
                for (k in kernel.indices) {
                    val yy = (y + k - kr).coerceIn(0, h - 1)
                    val p = tmp[yy * w + x]
                    val wt = kernel[k]
                    sr += ((p shr 16) and 255) * wt
                    sg += ((p shr 8) and 255) * wt
                    sb += (p and 255) * wt
                }
                out[y * w + x] = (tmp[y * w + x] and -0x1000000) or (clamp8(sr shr 16) shl 16) or
                    (clamp8(sg shr 16) shl 8) or clamp8(sb shr 16)
            }
        }
        return Pix(w, h, out)
    }

    /** Enlarge in <=2x Lanczos steps (cleaner edges than one big jump). */
    private fun stepwiseUpscale(src: Pix, tw: Int, th: Int): Pix {
        var cur = src
        while (cur.w * 2 < tw && cur.h * 2 < th) cur = resize(cur, cur.w * 2, cur.h * 2)
        return resize(cur, tw, th)
    }

    /** High-quality resize to an exact pixel size (desktop `resample`). Returns a new Pix. */
    fun resample(src: Pix, tw: Int, th: Int, method: Upscale, sharpen: Int): Pix {
        if (tw == src.w && th == src.h) return src
        val scale = sqrt(tw.toDouble() * th / (src.w.toDouble() * src.h))
        val enlarging = tw > src.w || th > src.h
        if (!enlarging) {
            val out = resize(src, tw, th)
            unsharpInPlace(out, if (sharpen < 0) autoSharpenAmount(scale) else sharpen, scale)
            return out
        }
        if (method == Upscale.STANDARD) {
            val out = resize(src, tw, th)
            if (sharpen > 0) unsharpInPlace(out, sharpen, scale)
            return out
        }
        val out = stepwiseUpscale(src, tw, th)
        unsharpInPlace(out, if (sharpen < 0) autoSharpenAmount(scale) else sharpen, scale)
        return out
    }

    /** Lanczos resize of a Bitmap (no sharpening) – used for proofs and close-ups. */
    fun resizeBitmap(bmp: Bitmap, tw: Int, th: Int): Bitmap {
        if (bmp.width == tw && bmp.height == th) return bmp
        return resize(Pix.of(bmp), max(1, tw), max(1, th)).toBitmap()
    }

    @Suppress("unused")
    private fun absDiff(a: Int, b: Int) = abs(a - b)
}
