package uk.ifixdigital.imageresizeshare.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Accent = Color(0xFF1A73E8)
val AccentDark = Color(0xFF155FC0)
val Green = Color(0xFF1F9D55)
val WarnColor = Color(0xFFB45309)
val GoodColor = Color(0xFF15803D)
val Hint = Color(0xFF64748B)
val CardBorder = Color(0xFFE3E8EF)
val PageBg = Color(0xFFF1F4F9)

private val Colors = lightColorScheme(
    primary = Accent,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFE8F0FE),
    onPrimaryContainer = AccentDark,
    secondary = Green,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFDCF3E6),
    onSecondaryContainer = Color(0xFF14532D),
    background = PageBg,
    onBackground = Color(0xFF1E293B),
    surface = Color.White,
    onSurface = Color(0xFF1E293B),
    surfaceVariant = Color(0xFFEEF2F7),
    onSurfaceVariant = Color(0xFF475569),
    outline = Color(0xFFCBD5E1),
    outlineVariant = CardBorder,
)

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Colors, content = content)
}
