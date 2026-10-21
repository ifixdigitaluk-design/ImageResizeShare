package uk.ifixdigital.imageresizeshare.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.util.Locale

@Composable
fun Panel(title: String? = null, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
        shape = RoundedCornerShape(12.dp),
        color = Color.White,
        border = androidx.compose.foundation.BorderStroke(1.dp, CardBorder),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (title != null) {
                Text(title, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = Color(0xFF0F172A))
            }
            content()
        }
    }
}

@Composable
fun SectionLabel(text: String) {
    Text(text, fontWeight = FontWeight.SemiBold, color = Color(0xFF334155), fontSize = 14.sp)
}

@Composable
fun HintText(text: String, color: Color = Hint) {
    Text(text, color = color, fontSize = 12.5.sp, lineHeight = 17.sp)
}

/** Format a number with up to [decimals] decimals and no trailing zeros. */
fun fmt(v: Double, decimals: Int): String {
    if (decimals <= 0) return Math.round(v).toString()
    val s = String.format(Locale.US, "%.${decimals}f", v).trimEnd('0').trimEnd('.')
    return s.ifEmpty { "0" }
}

/**
 * Numeric text field that only commits on Done / focus loss, so typing
 * "1080" doesn't trigger four re-renders.
 */
@Composable
fun NumberField(
    label: String,
    value: Double,
    decimals: Int,
    onCommit: (Double) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    suffix: String? = null,
    allowZero: Boolean = false,
) {
    val shown = fmt(value, decimals)
    var text by remember(shown) { mutableStateOf(shown) }
    var focused by remember { mutableStateOf(false) }
    val focus = LocalFocusManager.current
    fun commit() {
        val v = text.replace(',', '.').toDoubleOrNull()
        if (v != null && (v > 0 || (allowZero && v == 0.0)) && fmt(v, decimals) != shown) onCommit(v) else text = shown
    }
    OutlinedTextField(
        value = text,
        onValueChange = { t -> text = t.filter { it.isDigit() || it == '.' || it == ',' } },
        label = { Text(label, maxLines = 1) },
        singleLine = true,
        enabled = enabled,
        suffix = suffix?.let { { Text(it) } },
        keyboardOptions = KeyboardOptions(
            keyboardType = if (decimals > 0) KeyboardType.Decimal else KeyboardType.Number,
            imeAction = ImeAction.Done,
        ),
        keyboardActions = KeyboardActions(onDone = { commit(); focus.clearFocus() }),
        modifier = modifier.onFocusChanged {
            if (focused && !it.isFocused) commit()
            focused = it.isFocused
        },
    )
}

@Composable
fun <T> Dropdown(
    label: String,
    options: List<T>,
    selected: T,
    text: (T) -> String,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        Surface(
            shape = RoundedCornerShape(8.dp),
            color = if (enabled) Color(0xFFF8FAFC) else Color(0xFFF3F5F8),
            border = androidx.compose.foundation.BorderStroke(1.dp, Color(0xFFD9E0EA)),
            modifier = Modifier
                .fillMaxWidth()
                .clickable(enabled = enabled) { open = true },
        ) {
            Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(label, fontSize = 11.sp, color = Hint)
                    Text(
                        text(selected), fontSize = 14.sp, maxLines = 2,
                        color = if (enabled) Color(0xFF1E293B) else Color(0xFF94A3B8),
                    )
                }
                Icon(Icons.Filled.ArrowDropDown, contentDescription = null, tint = Hint)
            }
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            options.forEach { o ->
                DropdownMenuItem(
                    text = { Text(text(o), fontWeight = if (o == selected) FontWeight.SemiBold else FontWeight.Normal) },
                    onClick = {
                        open = false
                        onSelect(o)
                    },
                )
            }
        }
    }
}

@Composable
fun SwitchRow(text: String, checked: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean = true, hint: String? = null) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(enabled = enabled) { onChange(!checked) }
            .padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(text, fontSize = 14.sp, color = if (enabled) Color(0xFF1E293B) else Color(0xFF94A3B8))
            if (hint != null) HintText(hint)
        }
        Spacer(Modifier.width(8.dp))
        Switch(checked = checked, onCheckedChange = onChange, enabled = enabled)
    }
}

@Composable
fun ColorSwatch(color: Int, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .size(36.dp)
            .background(Color(color), CircleShape)
            .border(if (selected) 3.dp else 1.dp, if (selected) Accent else Color(0xFF94A3B8), CircleShape)
            .clickable(onClick = onClick),
    )
}

@Composable
fun InfoLines(lines: List<Pair<String, Boolean?>>) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(8.dp))
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        for ((t, warn) in lines) {
            Text(
                t, fontSize = 13.sp,
                color = when (warn) {
                    true -> WarnColor
                    false -> GoodColor
                    null -> Color(0xFF334155)
                },
            )
        }
    }
}
