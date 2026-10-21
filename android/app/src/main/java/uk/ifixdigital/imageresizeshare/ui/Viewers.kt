package uk.ifixdigital.imageresizeshare.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.gestures.drag
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import uk.ifixdigital.imageresizeshare.core.Crop
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

private fun DrawScope.checker(tl: Offset, w: Float, h: Float, tile: Float) {
    clipRect(tl.x, tl.y, tl.x + w, tl.y + h) {
        drawRect(Color.White, tl, Size(w, h))
        val x0 = max(tl.x, 0f)
        val y0 = max(tl.y, 0f)
        val x1 = min(tl.x + w, size.width)
        val y1 = min(tl.y + h, size.height)
        var y = y0 - ((y0 - tl.y) % tile)
        var row = ((y - tl.y) / tile).roundToInt()
        while (y < y1) {
            var x = x0 - ((x0 - tl.x) % tile)
            var col = ((x - tl.x) / tile).roundToInt()
            while (x < x1) {
                if ((row + col) % 2 == 0) drawRect(Color(0xFFE2E8F0), Offset(x, y), Size(tile, tile))
                x += tile
                col++
            }
            y += tile
            row++
        }
    }
}

/**
 * Pinch-zoom / pan image viewer. [contentW]×[contentH] is the real image size
 * (the bitmap shown may be a smaller display copy). Taps are reported in
 * real image pixels.
 */
@Composable
fun ZoomableImage(
    image: ImageBitmap?,
    contentW: Int,
    contentH: Int,
    modifier: Modifier = Modifier,
    transparentHint: Boolean = false,
    marker: Rect? = null,
    onTap: ((Float, Float) -> Unit)? = null,
) {
    BoxWithConstraints(modifier.clipToBounds().background(Color(0xFFE5E9F0))) {
        val vw = constraints.maxWidth.toFloat()
        val vh = constraints.maxHeight.toFloat()
        if (image == null || contentW <= 0 || contentH <= 0 || vw <= 0f || vh <= 0f) return@BoxWithConstraints
        val fit = min(vw / contentW, vh / contentH)
        val maxScale = max(fit * 1.5f, 8f)
        var scale by remember(contentW, contentH, vw, vh) { mutableFloatStateOf(fit) }
        var tl by remember(contentW, contentH, vw, vh) {
            mutableStateOf(Offset((vw - contentW * fit) / 2f, (vh - contentH * fit) / 2f))
        }
        val tapState = rememberUpdatedState(onTap)
        val tile = with(LocalDensity.current) { 10.dp.toPx() }
        val stroke = with(LocalDensity.current) { 2.dp.toPx() }

        fun clampTl(s: Float, p: Offset): Offset {
            val iw = contentW * s
            val ih = contentH * s
            val x = if (iw <= vw) (vw - iw) / 2f else p.x.coerceIn(vw - iw, 0f)
            val y = if (ih <= vh) (vh - ih) / 2f else p.y.coerceIn(vh - ih, 0f)
            return Offset(x, y)
        }

        Canvas(
            Modifier
                .fillMaxSize()
                .pointerInput(contentW, contentH, vw, vh) {
                    detectTransformGestures { centroid, pan, zoom, _ ->
                        val ns = (scale * zoom).coerceIn(fit, maxScale)
                        val f = ns / scale
                        val ntl = Offset(
                            centroid.x - (centroid.x - tl.x) * f + pan.x,
                            centroid.y - (centroid.y - tl.y) * f + pan.y,
                        )
                        scale = ns
                        tl = clampTl(ns, ntl)
                    }
                }
                .pointerInput(contentW, contentH, vw, vh) {
                    detectTapGestures(
                        onDoubleTap = { pos ->
                            val target = if (scale > fit * 1.05f) fit
                            else min(maxScale, if (1f > fit * 1.2f) 1f else fit * 2.5f)
                            val f = target / scale
                            val ntl = Offset(pos.x - (pos.x - tl.x) * f, pos.y - (pos.y - tl.y) * f)
                            scale = target
                            tl = clampTl(target, ntl)
                        },
                        onTap = { pos ->
                            tapState.value?.invoke((pos.x - tl.x) / scale, (pos.y - tl.y) / scale)
                        },
                    )
                },
        ) {
            val dw = contentW * scale
            val dh = contentH * scale
            if (transparentHint) checker(tl, dw, dh, tile)
            drawImage(
                image,
                srcOffset = IntOffset.Zero,
                srcSize = IntSize(image.width, image.height),
                dstOffset = IntOffset(tl.x.roundToInt(), tl.y.roundToInt()),
                dstSize = IntSize(dw.roundToInt().coerceAtLeast(1), dh.roundToInt().coerceAtLeast(1)),
                filterQuality = if (dw / image.width >= 2f) FilterQuality.None else FilterQuality.Medium,
            )
            marker?.let { r ->
                drawRect(
                    Accent,
                    topLeft = Offset(tl.x + r.left * scale, tl.y + r.top * scale),
                    size = Size(max(2f, r.width * scale), max(2f, r.height * scale)),
                    style = Stroke(width = stroke),
                )
            }
        }
    }
}

private enum class CropDrag { MOVE, NEW, TL, TR, BL, BR, L, R, T, B }

private fun fromAnchor(ax: Float, ay: Float, px: Float, py: Float, ratio: Float?, w: Float, h: Float, minS: Float): Rect {
    val sx = if (px >= ax) 1 else -1
    val sy = if (py >= ay) 1 else -1
    var cw = abs(px - ax)
    var ch = abs(py - ay)
    val maxW = if (sx > 0) w - ax else ax
    val maxH = if (sy > 0) h - ay else ay
    if (ratio != null) {
        if (cw / max(ch, 0.001f) > ratio) ch = cw / ratio else cw = ch * ratio
        if (cw < minS) {
            cw = minS; ch = cw / ratio
        }
        if (cw > maxW) {
            cw = maxW; ch = cw / ratio
        }
        if (ch > maxH) {
            ch = maxH; cw = ch * ratio
        }
    } else {
        cw = cw.coerceIn(min(minS, maxW), maxW)
        ch = ch.coerceIn(min(minS, maxH), maxH)
    }
    val left = if (sx > 0) ax else ax - cw
    val top = if (sy > 0) ay else ay - ch
    return Rect(left, top, left + cw, top + ch)
}

private fun dragEdge(r0: Rect, mode: CropDrag, p: Offset, ratio: Float?, w: Float, h: Float, minS: Float): Rect {
    var l = r0.left
    var t = r0.top
    var r = r0.right
    var b = r0.bottom
    when (mode) {
        CropDrag.L -> l = p.x.coerceIn(0f, max(0f, r - minS))
        CropDrag.R -> r = p.x.coerceIn(min(w, l + minS), w)
        CropDrag.T -> t = p.y.coerceIn(0f, max(0f, b - minS))
        CropDrag.B -> b = p.y.coerceIn(min(h, t + minS), h)
        else -> Unit
    }
    if (ratio != null) {
        if (mode == CropDrag.L || mode == CropDrag.R) {
            var nh = (r - l) / ratio
            if (nh > h) {
                nh = h
                val nw = nh * ratio
                if (mode == CropDrag.L) l = r - nw else r = l + nw
            }
            val cy = (r0.top + r0.bottom) / 2f
            t = (cy - nh / 2f).coerceIn(0f, h - nh)
            b = t + nh
        } else {
            var nw = (b - t) * ratio
            if (nw > w) {
                nw = w
                val nh = nw / ratio
                if (mode == CropDrag.T) t = b - nh else b = t + nh
            }
            val cx = (r0.left + r0.right) / 2f
            l = (cx - nw / 2f).coerceIn(0f, w - nw)
            r = l + nw
        }
    }
    return Rect(l, t, r, b)
}

/** Interactive crop box with corner/edge handles, move, and rule-of-thirds grid. */
@Composable
fun CropEditor(
    image: ImageBitmap?,
    imgW: Int,
    imgH: Int,
    crop: Crop?,
    ratio: Float?,
    grid: Boolean,
    onCrop: (Crop) -> Unit,
    modifier: Modifier = Modifier,
) {
    BoxWithConstraints(modifier.clipToBounds().background(Color(0xFF1F2937))) {
        val vw = constraints.maxWidth.toFloat()
        val vh = constraints.maxHeight.toFloat()
        if (image == null || imgW <= 0 || imgH <= 0 || vw <= 0f || vh <= 0f) return@BoxWithConstraints
        val density = LocalDensity.current
        val pad = with(density) { 20.dp.toPx() }
        val handle = with(density) { 30.dp.toPx() }
        val dot = with(density) { 7.dp.toPx() }
        val line = with(density) { 2.dp.toPx() }
        val s = min((vw - 2 * pad) / imgW, (vh - 2 * pad) / imgH)
        val ox = (vw - imgW * s) / 2f
        val oy = (vh - imgH * s) / 2f
        val w = imgW.toFloat()
        val h = imgH.toFloat()
        var rect by remember(crop, imgW, imgH) {
            mutableStateOf(
                crop?.let { Rect(it.x.toFloat(), it.y.toFloat(), (it.x + it.w).toFloat(), (it.y + it.h).toFloat()) }
                    ?: Rect(0f, 0f, w, h)
            )
        }
        val ratioState = rememberUpdatedState(ratio)
        val onCropState = rememberUpdatedState(onCrop)

        Canvas(
            Modifier
                .fillMaxSize()
                .pointerInput(imgW, imgH, s, ox, oy) {
                    fun toImg(p: Offset) = Offset(((p.x - ox) / s).coerceIn(0f, w), ((p.y - oy) / s).coerceIn(0f, h))
                    awaitEachGesture {
                        val down = awaitFirstDown()
                        val p0 = toImg(down.position)
                        val r0 = rect
                        val tol = handle / s
                        val minS = max(4f, 36f / s)
                        val near = { a: Float, b: Float -> abs(a - b) < tol }
                        val mode = when {
                            near(p0.x, r0.left) && near(p0.y, r0.top) -> CropDrag.TL
                            near(p0.x, r0.right) && near(p0.y, r0.top) -> CropDrag.TR
                            near(p0.x, r0.left) && near(p0.y, r0.bottom) -> CropDrag.BL
                            near(p0.x, r0.right) && near(p0.y, r0.bottom) -> CropDrag.BR
                            near(p0.x, r0.left) && p0.y in r0.top..r0.bottom -> CropDrag.L
                            near(p0.x, r0.right) && p0.y in r0.top..r0.bottom -> CropDrag.R
                            near(p0.y, r0.top) && p0.x in r0.left..r0.right -> CropDrag.T
                            near(p0.y, r0.bottom) && p0.x in r0.left..r0.right -> CropDrag.B
                            r0.contains(p0) -> CropDrag.MOVE
                            else -> CropDrag.NEW
                        }
                        var changed = false
                        drag(down.id) { change ->
                            val p = toImg(change.position)
                            val ratioNow = ratioState.value
                            rect = when (mode) {
                                CropDrag.MOVE -> {
                                    val nl = (r0.left + p.x - p0.x).coerceIn(0f, w - r0.width)
                                    val nt = (r0.top + p.y - p0.y).coerceIn(0f, h - r0.height)
                                    Rect(nl, nt, nl + r0.width, nt + r0.height)
                                }
                                CropDrag.NEW -> fromAnchor(p0.x, p0.y, p.x, p.y, ratioNow, w, h, minS)
                                CropDrag.TL -> fromAnchor(r0.right, r0.bottom, p.x, p.y, ratioNow, w, h, minS)
                                CropDrag.TR -> fromAnchor(r0.left, r0.bottom, p.x, p.y, ratioNow, w, h, minS)
                                CropDrag.BL -> fromAnchor(r0.right, r0.top, p.x, p.y, ratioNow, w, h, minS)
                                CropDrag.BR -> fromAnchor(r0.left, r0.top, p.x, p.y, ratioNow, w, h, minS)
                                else -> dragEdge(r0, mode, p, ratioNow, w, h, minS)
                            }
                            changed = true
                            change.consume()
                        }
                        if (changed) {
                            val r = rect
                            if (r.width >= 2f && r.height >= 2f) {
                                onCropState.value(
                                    Crop(r.left.roundToInt(), r.top.roundToInt(), r.width.roundToInt(), r.height.roundToInt())
                                )
                            }
                        }
                    }
                },
        ) {
            drawImage(
                image,
                srcOffset = IntOffset.Zero,
                srcSize = IntSize(image.width, image.height),
                dstOffset = IntOffset(ox.roundToInt(), oy.roundToInt()),
                dstSize = IntSize((w * s).roundToInt().coerceAtLeast(1), (h * s).roundToInt().coerceAtLeast(1)),
                filterQuality = FilterQuality.Medium,
            )
            val l = ox + rect.left * s
            val t = oy + rect.top * s
            val r = ox + rect.right * s
            val b = oy + rect.bottom * s
            val shade = Color(0x99000000)
            val iw = w * s
            val ih = h * s
            drawRect(shade, Offset(ox, oy), Size(iw, t - oy))
            drawRect(shade, Offset(ox, b), Size(iw, oy + ih - b))
            drawRect(shade, Offset(ox, t), Size(l - ox, b - t))
            drawRect(shade, Offset(r, t), Size(ox + iw - r, b - t))
            if (grid) {
                val g = Color(0x99FFFFFF)
                for (i in 1..2) {
                    val x = l + (r - l) * i / 3f
                    val y = t + (b - t) * i / 3f
                    drawLine(g, Offset(x, t), Offset(x, b), strokeWidth = line / 2)
                    drawLine(g, Offset(l, y), Offset(r, y), strokeWidth = line / 2)
                }
            }
            drawRect(Color.White, Offset(l, t), Size(r - l, b - t), style = Stroke(width = line))
            for ((cx, cy) in listOf(l to t, r to t, l to b, r to b)) {
                drawCircle(Color.White, dot, Offset(cx, cy))
                drawCircle(Accent, dot, Offset(cx, cy), style = Stroke(width = line))
            }
            val bar = dot * 2.4f
            val thick = dot * 0.9f
            val mx = (l + r) / 2f
            val my = (t + b) / 2f
            drawRoundRect(Color.White, Offset(mx - bar / 2, t - thick / 2), Size(bar, thick), CornerRadius(thick / 2))
            drawRoundRect(Color.White, Offset(mx - bar / 2, b - thick / 2), Size(bar, thick), CornerRadius(thick / 2))
            drawRoundRect(Color.White, Offset(l - thick / 2, my - bar / 2), Size(thick, bar), CornerRadius(thick / 2))
            drawRoundRect(Color.White, Offset(r - thick / 2, my - bar / 2), Size(thick, bar), CornerRadius(thick / 2))
        }
    }
}
