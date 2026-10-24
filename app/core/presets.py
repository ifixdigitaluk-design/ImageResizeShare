"""Size presets and crop ratio presets."""
from __future__ import annotations

# (label, width, height, unit, dpi)  unit "px" => dpi ignored
SIZE_PRESETS = {
    "Common": [
        ("Original", 0, 0, "px", 0),
        ("800 × 600", 800, 600, "px", 0),
        ("1024 × 768", 1024, 768, "px", 0),
        ("1280 × 1024", 1280, 1024, "px", 0),
        ("HD 1920 × 1080", 1920, 1080, "px", 0),
        ("4K 3840 × 2160", 3840, 2160, "px", 0),
    ],
    "WhatsApp / Social": [
        ("WhatsApp DP 640 × 640", 640, 640, "px", 0),
        ("WhatsApp Status 1080 × 1920", 1080, 1920, "px", 0),
        ("Instagram Post 1080 × 1080", 1080, 1080, "px", 0),
        ("Instagram Portrait 1080 × 1350", 1080, 1350, "px", 0),
        ("Instagram Story 1080 × 1920", 1080, 1920, "px", 0),
        ("Facebook Post 1200 × 630", 1200, 630, "px", 0),
        ("YouTube Thumbnail 1280 × 720", 1280, 720, "px", 0),
    ],
    "Print (300 DPI)": [
        ("Passport UK/EU 35 × 45 mm", 35, 45, "mm", 300),
        ("Passport US/India 2 × 2 in", 2, 2, "in", 300),
        ("Photo 4 × 6 in", 4, 6, "in", 300),
        ("Photo 5 × 7 in", 5, 7, "in", 300),
        ("Photo 8 × 10 in", 8, 10, "in", 300),
        ("A6 105 × 148 mm", 105, 148, "mm", 300),
        ("A5 148 × 210 mm", 148, 210, "mm", 300),
        ("A4 210 × 297 mm", 210, 297, "mm", 300),
        ("A3 297 × 420 mm", 297, 420, "mm", 300),
    ],
    "Wallpaper & murals (100 DPI)": [
        ("Feature wall 8 × 8 ft", 96, 96, "in", 100),
        ("Wall 10 × 8 ft", 120, 96, "in", 100),
        ("Wall 12 × 8 ft", 144, 96, "in", 100),
        ("Wall 12 × 9 ft", 144, 108, "in", 100),
        ("Wall 14 × 9 ft", 168, 108, "in", 100),
        ("Large wall 16 × 9 ft (72 DPI)", 192, 108, "in", 72),
        ("Canvas 24 × 36 in (150 DPI)", 24, 36, "in", 150),
        ("Poster 36 × 48 in (150 DPI)", 36, 48, "in", 150),
    ],
}

# Quick tiles on the Resize panel (as in the design mockup); "Custom" is added by the UI
QUICK_PRESETS = [
    ("Original", 0, 0), ("Small", 800, 600), ("Medium", 1200, 900), ("Large", 1920, 1080),
]

# (label, ratio_w, ratio_h) ; 0,0 = free ; -1,-1 = original image ratio
CROP_RATIOS = [
    ("Free", 0, 0),
    ("Original", -1, -1),
    ("1:1 Square", 1, 1),
    ("4:5 Portrait", 4, 5),
    ("3:4", 3, 4),
    ("2:3", 2, 3),
    ("9:16 Story", 9, 16),
    ("4:3", 4, 3),
    ("3:2", 3, 2),
    ("16:9 Wide", 16, 9),
    ("Passport 35×45 mm", 35, 45),
    ("Passport 2×2 in", 1, 1),
    ("A4 portrait", 210, 297),
]
