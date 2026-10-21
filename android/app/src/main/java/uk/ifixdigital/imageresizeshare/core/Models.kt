package uk.ifixdigital.imageresizeshare.core

import android.graphics.Bitmap

/** Limits that keep phones from running out of memory. */
const val MAX_OUTPUT_SIDE = 16000
const val MAX_OUTPUT_PIXELS = 25_000_000L
const val MAX_SOURCE_PIXELS = 24_000_000L

enum class FitMode(val label: String) {
    FIT_PAD("Fit – keep whole image, add background"),
    FIT_INSIDE("Fit inside – keep whole image, no borders"),
    FILL("Fill – fill the size, trim edges"),
    STRETCH("Stretch – exact size (may distort)"),
}

enum class Background(val label: String) {
    WHITE("White"),
    BLACK("Black"),
    BLUR("Blurred photo"),
    TRANSPARENT("Transparent (PNG/WEBP)"),
    CUSTOM("Custom colour"),
}

enum class Upscale(val label: String) {
    ENHANCED("Enhanced – sharp edges, no halos (recommended)"),
    STANDARD("Standard – plain Lanczos"),
}

enum class OutFormat(val label: String, val ext: String, val mime: String, val lossy: Boolean) {
    JPG("JPG", ".jpg", "image/jpeg", true),
    PNG("PNG", ".png", "image/png", false),
    WEBP("WEBP", ".webp", "image/webp", true),
    PDF("PDF", ".pdf", "application/pdf", true),
}

enum class SizeUnit(val label: String, val decimals: Int) {
    PX("px", 0), PERCENT("%", 1), CM("cm", 2), MM("mm", 1), IN("in", 2);

    val physical: Boolean get() = this == CM || this == MM || this == IN
}

data class Crop(val x: Int, val y: Int, val w: Int, val h: Int)

/** Geometry edits applied to the source before resizing (undoable). */
data class EditState(
    val rotation: Int = 0,          // 0, 90, 180, 270 clockwise
    val flipH: Boolean = false,
    val flipV: Boolean = false,
    val crop: Crop? = null,         // in oriented (rotated/flipped) coordinates
)

data class ResizeSettings(
    val enabled: Boolean = true,
    val width: Int = 0,
    val height: Int = 0,
    val mode: FitMode = FitMode.FIT_PAD,
    val background: Background = Background.WHITE,
    val customColor: Int = 0xFFFFFFFF.toInt(),
    val upscale: Upscale = Upscale.ENHANCED,
    val sharpen: Int = -1,          // -1 = auto, else 0..100
    val allowUpscale: Boolean = true,
)

data class OutputSettings(
    val fmt: OutFormat = OutFormat.JPG,
    val quality: Int = 92,
    val webpLossless: Boolean = false,
    val targetKb: Int = 0,          // 0 = off
    val dpi: Int = 300,
)

class ProcessResult(
    val image: Bitmap,
    val data: ByteArray,
    val fmt: OutFormat,
    val qualityUsed: Int?,
    val notes: List<String>,
) {
    val sizeBytes: Int get() = data.size
}

class LoadedImage(
    val bitmap: Bitmap,             // orientation-corrected, ARGB_8888
    val name: String,
    val fileSize: Long,
    val mime: String?,
    val originalWidth: Int,
    val originalHeight: Int,
) {
    val width: Int get() = bitmap.width
    val height: Int get() = bitmap.height
    val reduced: Boolean get() = originalWidth != bitmap.width || originalHeight != bitmap.height
}

class ImageTooLargeException(msg: String) : Exception(msg)
