package uk.ifixdigital.imageresizeshare.core

/** A size preset. width == 0 means "original size". dpi == 0 keeps the current DPI. */
data class SizePreset(val label: String, val w: Double, val h: Double, val unit: SizeUnit, val dpi: Int)

data class CropRatio(val label: String, val a: Int, val b: Int) {
    val isFree: Boolean get() = a == 0
    val isOriginal: Boolean get() = a == -1
}

object Presets {
    val SIZE_GROUPS: List<Pair<String, List<SizePreset>>> = listOf(
        "Common" to listOf(
            SizePreset("Original", 0.0, 0.0, SizeUnit.PX, 0),
            SizePreset("800 × 600", 800.0, 600.0, SizeUnit.PX, 0),
            SizePreset("1024 × 768", 1024.0, 768.0, SizeUnit.PX, 0),
            SizePreset("1280 × 1024", 1280.0, 1024.0, SizeUnit.PX, 0),
            SizePreset("HD 1920 × 1080", 1920.0, 1080.0, SizeUnit.PX, 0),
            SizePreset("4K 3840 × 2160", 3840.0, 2160.0, SizeUnit.PX, 0),
        ),
        "WhatsApp / Social" to listOf(
            SizePreset("WhatsApp DP 640 × 640", 640.0, 640.0, SizeUnit.PX, 0),
            SizePreset("WhatsApp Status 1080 × 1920", 1080.0, 1920.0, SizeUnit.PX, 0),
            SizePreset("Instagram Post 1080 × 1080", 1080.0, 1080.0, SizeUnit.PX, 0),
            SizePreset("Instagram Portrait 1080 × 1350", 1080.0, 1350.0, SizeUnit.PX, 0),
            SizePreset("Instagram Story 1080 × 1920", 1080.0, 1920.0, SizeUnit.PX, 0),
            SizePreset("Facebook Post 1200 × 630", 1200.0, 630.0, SizeUnit.PX, 0),
            SizePreset("YouTube Thumbnail 1280 × 720", 1280.0, 720.0, SizeUnit.PX, 0),
        ),
        "Print (300 DPI)" to listOf(
            SizePreset("Passport UK/EU 35 × 45 mm", 35.0, 45.0, SizeUnit.MM, 300),
            SizePreset("Passport US/India 2 × 2 in", 2.0, 2.0, SizeUnit.IN, 300),
            SizePreset("Photo 4 × 6 in", 4.0, 6.0, SizeUnit.IN, 300),
            SizePreset("Photo 5 × 7 in", 5.0, 7.0, SizeUnit.IN, 300),
            SizePreset("Photo 8 × 10 in", 8.0, 10.0, SizeUnit.IN, 300),
            SizePreset("A6 105 × 148 mm", 105.0, 148.0, SizeUnit.MM, 300),
            SizePreset("A5 148 × 210 mm", 148.0, 210.0, SizeUnit.MM, 300),
            SizePreset("A4 210 × 297 mm", 210.0, 297.0, SizeUnit.MM, 300),
            SizePreset("A3 297 × 420 mm", 297.0, 420.0, SizeUnit.MM, 300),
        ),
    )

    val QUICK: List<SizePreset> = listOf(
        SizePreset("Original", 0.0, 0.0, SizeUnit.PX, 0),
        SizePreset("800 × 600", 800.0, 600.0, SizeUnit.PX, 0),
        SizePreset("1024 × 768", 1024.0, 768.0, SizeUnit.PX, 0),
        SizePreset("1080 × 1080", 1080.0, 1080.0, SizeUnit.PX, 0),
        SizePreset("1280 × 1024", 1280.0, 1024.0, SizeUnit.PX, 0),
        SizePreset("1920 × 1080", 1920.0, 1080.0, SizeUnit.PX, 0),
    )

    val CROP_RATIOS: List<CropRatio> = listOf(
        CropRatio("Free", 0, 0),
        CropRatio("Original", -1, -1),
        CropRatio("1:1 Square", 1, 1),
        CropRatio("4:5 Portrait", 4, 5),
        CropRatio("3:4", 3, 4),
        CropRatio("2:3", 2, 3),
        CropRatio("9:16 Story", 9, 16),
        CropRatio("4:3", 4, 3),
        CropRatio("3:2", 3, 2),
        CropRatio("16:9 Wide", 16, 9),
        CropRatio("Passport 35×45 mm", 35, 45),
        CropRatio("Passport 2×2 in", 1, 1),
        CropRatio("A4 portrait", 210, 297),
    )
}
