@file:OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)

package uk.ifixdigital.imageresizeshare.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.AspectRatio
import androidx.compose.material.icons.filled.Collections
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Flip
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Help
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Redo
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material.icons.filled.RotateLeft
import androidx.compose.material.icons.filled.RotateRight
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material.icons.filled.Undo
import androidx.compose.material.icons.filled.ZoomIn
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import uk.ifixdigital.imageresizeshare.core.Background
import uk.ifixdigital.imageresizeshare.core.Crop
import uk.ifixdigital.imageresizeshare.core.FitMode
import uk.ifixdigital.imageresizeshare.core.ImageEngine
import uk.ifixdigital.imageresizeshare.core.OutFormat
import uk.ifixdigital.imageresizeshare.core.Outputs
import uk.ifixdigital.imageresizeshare.core.Presets
import uk.ifixdigital.imageresizeshare.core.SizeUnit
import uk.ifixdigital.imageresizeshare.core.Upscale
import kotlin.math.roundToInt

/** Things only the Activity can do (pickers, permissions). */
class UiActions(
    val pickImage: () -> Unit,
    val browseFiles: () -> Unit,
    val pickBatch: () -> Unit,
    /** Runs the action with true when saving to Pictures is allowed (asks on Android 9 and older). */
    val withStorage: (action: (Boolean) -> Unit) -> Unit,
)

@Composable
fun MainScreen(vm: MainViewModel, actions: UiActions, snackbar: SnackbarHostState) {
    var menu by remember { mutableStateOf(false) }
    var presetsDialog by remember { mutableStateOf(false) }
    var colorDialog by remember { mutableStateOf(false) }
    val s = vm.src
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            s?.name ?: "Image Resize & Share", maxLines = 1, overflow = TextOverflow.Ellipsis,
                            fontSize = 18.sp, fontWeight = FontWeight.SemiBold,
                        )
                        if (s != null) {
                            val size = if (s.fileSize > 0) " · ${ImageEngine.humanSize(s.fileSize)}" else ""
                            Text("${s.width} × ${s.height} px$size", fontSize = 12.sp, color = Hint)
                        }
                    }
                },
                actions = {
                    IconButton(onClick = actions.pickImage) { Icon(Icons.Filled.AddPhotoAlternate, "Open image") }
                    IconButton(onClick = vm::undo, enabled = vm.canUndo) { Icon(Icons.Filled.Undo, "Undo") }
                    IconButton(onClick = vm::redo, enabled = vm.canRedo) { Icon(Icons.Filled.Redo, "Redo") }
                    Box {
                        IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, "More") }
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            DropdownMenuItem(
                                text = { Text("Browse files…") },
                                leadingIcon = { Icon(Icons.Filled.Folder, null) },
                                onClick = { menu = false; actions.browseFiles() },
                            )
                            DropdownMenuItem(
                                text = { Text("Proof sheet…") },
                                leadingIcon = { Icon(Icons.Filled.Description, null) },
                                enabled = s != null,
                                onClick = { menu = false; vm.openProof() },
                            )
                            DropdownMenuItem(
                                text = { Text("Batch resize…") },
                                leadingIcon = { Icon(Icons.Filled.Collections, null) },
                                onClick = { menu = false; vm.openBatch() },
                            )
                            DropdownMenuItem(
                                text = { Text("Reset all edits") },
                                leadingIcon = { Icon(Icons.Filled.RestartAlt, null) },
                                enabled = s != null,
                                onClick = { menu = false; vm.resetAll() },
                            )
                            DropdownMenuItem(
                                text = { Text("Help & tips") },
                                leadingIcon = { Icon(Icons.Filled.Help, null) },
                                onClick = { menu = false; vm.screen = Screen.HELP },
                            )
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.White),
            )
        },
        bottomBar = { if (s != null) BottomActions(vm, actions) },
        snackbarHost = { SnackbarHost(snackbar) },
        containerColor = PageBg,
    ) { pad ->
        if (s == null) {
            EmptyState(vm, actions, Modifier.padding(pad))
        } else {
            Column(
                Modifier
                    .padding(pad)
                    .fillMaxSize(),
            ) {
                PreviewPane(vm, Modifier.fillMaxWidth().weight(1f))
                ToolsRow(vm)
                if (vm.closeUpOn && vm.tab != MainTab.CROP) CloseUpPanel(vm)
                TabRow(selectedTabIndex = vm.tab.ordinal, containerColor = Color.White) {
                    MainTab.entries.forEach { t ->
                        Tab(selected = vm.tab == t, onClick = { vm.tab = t }, text = { Text(t.label) })
                    }
                }
                Column(
                    Modifier
                        .weight(1.15f)
                        .fillMaxWidth()
                        .imePadding()
                        .verticalScroll(rememberScrollState())
                        .padding(vertical = 6.dp),
                ) {
                    when (vm.tab) {
                        MainTab.RESIZE -> ResizeTab(vm, { presetsDialog = true }, { colorDialog = true })
                        MainTab.CROP -> CropTab(vm)
                        MainTab.FORMAT -> FormatTab(vm)
                        MainTab.SHARE -> ShareTab(vm, actions)
                    }
                    Spacer(Modifier.height(12.dp))
                }
            }
        }
    }
    if (presetsDialog) PresetsDialog(vm) { presetsDialog = false }
    if (colorDialog) ColorDialog(vm.customColor, { vm.customColor = it }) { colorDialog = false }
}

@Composable
private fun EmptyState(vm: MainViewModel, actions: UiActions, modifier: Modifier) {
    Column(
        modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Spacer(Modifier.height(24.dp))
        Box(
            Modifier
                .size(104.dp)
                .background(Color(0xFFE8F0FE), RoundedCornerShape(26.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Filled.Image, null, tint = Accent, modifier = Modifier.size(60.dp))
        }
        Spacer(Modifier.height(18.dp))
        Text("Resize, crop & share photos", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
        Text("without losing quality", color = Hint, fontSize = 15.sp)
        Spacer(Modifier.height(28.dp))
        Button(onClick = actions.pickImage, modifier = Modifier.fillMaxWidth().height(54.dp)) {
            Icon(Icons.Filled.AddPhotoAlternate, null)
            Spacer(Modifier.width(8.dp))
            Text("Open a photo", fontSize = 16.sp)
        }
        Spacer(Modifier.height(10.dp))
        OutlinedButton(onClick = actions.browseFiles, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Filled.Folder, null)
            Spacer(Modifier.width(8.dp))
            Text("Browse files")
        }
        Spacer(Modifier.height(6.dp))
        OutlinedButton(onClick = { vm.openBatch() }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Filled.Collections, null)
            Spacer(Modifier.width(8.dp))
            Text("Batch resize many photos")
        }
        Spacer(Modifier.height(20.dp))
        HintText("Tip: in Gallery or WhatsApp, tap Share on a photo and choose “Resize & Share”.")
        if (vm.loading) {
            Spacer(Modifier.height(16.dp))
            CircularProgressIndicator()
        }
    }
}

@Composable
private fun PreviewPane(vm: MainViewModel, modifier: Modifier) {
    Box(modifier.background(Color(0xFFE5E9F0))) {
        if (vm.tab == MainTab.CROP) {
            val (ow, oh) = vm.orientedSize()
            CropEditor(
                vm.orientedDisplay, ow, oh, vm.edit.crop, vm.currentRatio(), vm.showGrid,
                onCrop = { vm.setCrop(it) }, modifier = Modifier.fillMaxSize(),
            )
            val c = ImageEngine.clampCrop(vm.edit.crop, ow, oh)
            Badge(
                if (c == null) "Whole image $ow × $oh px" else "Crop ${c.w} × ${c.h} px",
                Modifier.align(Alignment.BottomStart),
            )
        } else {
            val r = vm.result
            if (vm.showOriginal) {
                val (ow, oh) = vm.orientedSize()
                ZoomableImage(vm.orientedDisplay, ow, oh, Modifier.fillMaxSize())
                Badge("Original $ow × $oh px", Modifier.align(Alignment.BottomStart))
            } else if (r != null) {
                ZoomableImage(
                    vm.resultDisplay, r.image.width, r.image.height, Modifier.fillMaxSize(),
                    transparentHint = r.image.hasAlpha(),
                    marker = if (vm.closeUpOn) vm.closeUpRect else null,
                    onTap = { x, y -> if (vm.closeUpOn) vm.tapResult(x, y) },
                )
                val q = if (r.qualityUsed != null && r.fmt != OutFormat.PNG) ", quality ${r.qualityUsed}%" else ""
                Badge(
                    "${r.image.width} × ${r.image.height} px · ${ImageEngine.humanSize(r.sizeBytes.toLong())} (${r.fmt.label}$q)",
                    Modifier.align(Alignment.BottomStart),
                )
            }
            Row(
                Modifier
                    .align(Alignment.TopStart)
                    .padding(8.dp),
            ) {
                SegButton("Result", !vm.showOriginal, first = true) { vm.showOriginal = false }
                SegButton("Original", vm.showOriginal, first = false) { vm.showOriginal = true }
            }
        }
        if (vm.processing) {
            LinearProgressIndicator(Modifier.fillMaxWidth().align(Alignment.TopCenter))
        }
        vm.problem?.let {
            Text(
                it,
                color = Color(0xFFB91C1C),
                fontSize = 13.sp,
                modifier = Modifier
                    .align(Alignment.Center)
                    .padding(16.dp)
                    .background(Color.White, RoundedCornerShape(8.dp))
                    .padding(12.dp),
            )
        }
    }
}

@Composable
private fun Badge(text: String, modifier: Modifier) {
    Text(
        text,
        color = Color.White,
        fontSize = 12.sp,
        modifier = modifier
            .padding(8.dp)
            .background(Color(0xCC0F172A), RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

@Composable
private fun SegButton(text: String, selected: Boolean, first: Boolean, onClick: () -> Unit) {
    val shape = if (first) RoundedCornerShape(topStart = 8.dp, bottomStart = 8.dp)
    else RoundedCornerShape(topEnd = 8.dp, bottomEnd = 8.dp)
    Text(
        text,
        color = if (selected) Color.White else Color(0xFF1E293B),
        fontSize = 13.sp,
        fontWeight = FontWeight.Medium,
        modifier = Modifier
            .background(if (selected) Accent else Color(0xEEFFFFFF), shape)
            .border(1.dp, if (selected) Accent else Color(0xFFCBD5E1), shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

@Composable
private fun ToolButton(icon: ImageVector, label: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    IconButton(onClick = onClick) { Icon(icon, label, modifier, tint = Color(0xFF334155)) }
}

@Composable
private fun ToolsRow(vm: MainViewModel) {
    Row(
        Modifier
            .fillMaxWidth()
            .background(Color.White)
            .padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ToolButton(Icons.Filled.RotateLeft, "Rotate left") { vm.rotate(false) }
        ToolButton(Icons.Filled.RotateRight, "Rotate right") { vm.rotate(true) }
        ToolButton(Icons.Filled.Flip, "Flip horizontally") { vm.flip(true) }
        ToolButton(Icons.Filled.Flip, "Flip vertically", Modifier.rotate(90f)) { vm.flip(false) }
        Spacer(Modifier.weight(1f))
        FilterChip(
            selected = vm.closeUpOn,
            onClick = { vm.closeUpOn = !vm.closeUpOn },
            label = { Text("Close-up") },
            leadingIcon = { Icon(Icons.Filled.ZoomIn, null, Modifier.size(18.dp)) },
        )
        Spacer(Modifier.width(8.dp))
    }
    HorizontalDivider(color = CardBorder)
}

@Composable
private fun CloseImg(img: ImageBitmap?, modifier: Modifier) {
    Box(modifier.background(Color(0xFFE2E8F0), RoundedCornerShape(6.dp)), contentAlignment = Alignment.Center) {
        if (img != null) {
            Image(
                img, null, Modifier.fillMaxSize(),
                contentScale = ContentScale.Fit, filterQuality = FilterQuality.None,
            )
        }
    }
}

@Composable
private fun CloseUpPanel(vm: MainViewModel) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(Color.White)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Row {
            Text("Before (original pixels)", Modifier.weight(1f), fontSize = 12.sp, color = Hint)
            Spacer(Modifier.width(8.dp))
            Text("After (your result)", Modifier.weight(1f), fontSize = 12.sp, color = Hint)
        }
        Row(
            Modifier
                .fillMaxWidth()
                .height(112.dp)
                .onSizeChanged { vm.closeUpPanelPx = it.height },
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            CloseImg(vm.closeBefore, Modifier.weight(1f).fillMaxSize())
            CloseImg(vm.closeAfter, Modifier.weight(1f).fillMaxSize())
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            listOf(100, 200, 400, 800).forEach { z ->
                Text(
                    "$z%",
                    fontSize = 12.sp,
                    color = if (vm.closeUpZoom == z) Color.White else Color(0xFF334155),
                    modifier = Modifier
                        .padding(end = 4.dp, top = 4.dp)
                        .background(if (vm.closeUpZoom == z) Accent else Color(0xFFEEF2F7), RoundedCornerShape(6.dp))
                        .clickable { vm.closeUpZoom = z }
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
            Spacer(Modifier.width(6.dp))
            Text("Tap the result to choose the spot.", fontSize = 11.sp, color = Hint, maxLines = 2)
        }
    }
    HorizontalDivider(color = CardBorder)
}

@Composable
private fun BottomActions(vm: MainViewModel, actions: UiActions) {
    Surface(color = Color.White, shadowElevation = 8.dp) {
        Row(
            Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedButton(
                onClick = { actions.withStorage { ok -> if (ok) vm.saveToGallery() else vm.requestSaveAs() } },
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Filled.Save, null, Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("Save")
            }
            OutlinedButton(onClick = vm::share, modifier = Modifier.weight(1f)) {
                Icon(Icons.Filled.Share, null, Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("Share")
            }
            Button(
                onClick = { actions.withStorage { ok -> vm.shareWhatsApp(ok) } },
                modifier = Modifier.weight(1.25f),
                colors = ButtonDefaults.buttonColors(containerColor = Green),
            ) {
                Icon(Icons.Filled.Send, null, Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("WhatsApp", maxLines = 1)
            }
        }
    }
}

// ============================================================ tabs

@Composable
private fun ResizeTab(vm: MainViewModel, onMorePresets: () -> Unit, onPickColor: () -> Unit) {
    Panel("Size") {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Presets.QUICK.forEach { p ->
                FilterChip(selected = vm.isPresetSelected(p), onClick = { vm.applyPreset(p) }, label = { Text(p.label) })
            }
            AssistChip(
                onClick = onMorePresets,
                label = { Text("More: WhatsApp, Instagram, Passport, A4…") },
                leadingIcon = { Icon(Icons.Filled.AspectRatio, null, Modifier.size(18.dp)) },
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            NumberField("Width", vm.widthInUnit(), vm.unit.decimals, { vm.setWidthValue(it) }, Modifier.weight(1f))
            Text("×", color = Hint)
            NumberField("Height", vm.heightInUnit(), vm.unit.decimals, { vm.setHeightValue(it) }, Modifier.weight(1f))
            Dropdown("Unit", SizeUnit.entries, vm.unit, { it.label }, { vm.unit = it }, Modifier.width(82.dp))
        }
        SwitchRow("Maintain aspect ratio", vm.link, { vm.toggleLink() })
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumberField("Print DPI", vm.dpi.toDouble(), 0, { vm.changeDpi(it.roundToInt()) }, Modifier.width(120.dp))
            HintText("Used for cm, mm and inches, and saved in the file for printing.")
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SectionLabel("Upscale")
            for (k in 2..4) {
                OutlinedButton(onClick = { vm.quickUpscale(k) }) { Text("$k×") }
            }
        }
        InfoLines(vm.sizeInfo())
    }
    Panel("If the new shape is different") {
        Dropdown("Shape", FitMode.entries, vm.mode, { it.label }, { vm.mode = it })
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Dropdown(
                "Background", Background.entries, vm.background, { it.label },
                {
                    vm.background = it
                    if (it == Background.CUSTOM) onPickColor()
                },
                Modifier.weight(1f), enabled = vm.mode == FitMode.FIT_PAD,
            )
            if (vm.background == Background.CUSTOM && vm.mode == FitMode.FIT_PAD) {
                ColorSwatch(vm.customColor, false, onPickColor)
            }
        }
        if (vm.shapeDiffers()) {
            HintText("The new size has a different shape from your image. Fit keeps the whole picture (nothing is cut off).")
        }
    }
    Panel("Enlarging quality") {
        Dropdown("Method", Upscale.entries, vm.upscale, { it.label }, { vm.upscale = it })
        SwitchRow("Auto sharpen", vm.sharpenAuto, { vm.sharpenAuto = it })
        if (!vm.sharpenAuto) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Slider(
                    value = vm.sharpenValue.toFloat(), onValueChange = { vm.sharpenValue = it.roundToInt() },
                    valueRange = 0f..100f, modifier = Modifier.weight(1f),
                )
                Text("${vm.sharpenValue}", Modifier.width(36.dp), textAlign = TextAlign.End)
            }
        }
        SwitchRow("Allow enlarging beyond the original size", vm.allowUpscale, { vm.allowUpscale = it })
        HintText("Small images have no hidden detail. Enhanced enlarges in steps and sharpens without white outlines.")
    }
}

@Composable
private fun CropTab(vm: MainViewModel) {
    val (w, h) = vm.orientedSize()
    val c = ImageEngine.clampCrop(vm.edit.crop, w, h) ?: Crop(0, 0, w, h)
    Panel("Crop") {
        HintText("Drag the corners or edges on the picture. Drag inside the box to move it, or outside to draw a new one.")
        SectionLabel("Aspect ratio")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Presets.CROP_RATIOS.forEach { r ->
                FilterChip(selected = vm.cropRatio == r, onClick = { vm.selectRatio(r) }, label = { Text(r.label) })
            }
            AssistChip(
                onClick = vm::swapRatio,
                label = { Text(if (vm.cropSwap) "Swapped" else "Swap") },
                leadingIcon = { Icon(Icons.Filled.SwapHoriz, null, Modifier.size(18.dp)) },
            )
        }
        SwitchRow("Rule-of-thirds grid", vm.showGrid, { vm.showGrid = it })
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("X", c.x.toDouble(), 0, { vm.setCropField('x', it.roundToInt()) }, Modifier.weight(1f), allowZero = true)
            NumberField("Y", c.y.toDouble(), 0, { vm.setCropField('y', it.roundToInt()) }, Modifier.weight(1f), allowZero = true)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            NumberField("Width", c.w.toDouble(), 0, { vm.setCropField('w', it.roundToInt()) }, Modifier.weight(1f))
            NumberField("Height", c.h.toDouble(), 0, { vm.setCropField('h', it.roundToInt()) }, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = vm::cropSelectAll, modifier = Modifier.weight(1f)) { Text("Select all") }
            OutlinedButton(onClick = vm::cropClear, modifier = Modifier.weight(1f)) { Text("Clear crop") }
        }
        InfoLines(listOf("Crop: ${c.w} × ${c.h} px  →  Output: ${vm.tw} × ${vm.th} px" to null))
        HintText("To print or share at a set size, pick it on the Resize tab after cropping.")
    }
}

@Composable
private fun FormatTab(vm: MainViewModel) {
    val lossy = vm.fmt.lossy && !(vm.fmt == OutFormat.WEBP && vm.webpLossless)
    Panel("Output format") {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutFormat.entries.forEach { f ->
                FilterChip(selected = vm.fmt == f, onClick = { vm.fmt = f }, label = { Text(f.label) })
            }
        }
        HintText(
            when (vm.fmt) {
                OutFormat.JPG -> "Best for photos. 90–95% quality can't be told apart from the original."
                OutFormat.PNG -> "Lossless. Best for logos, text and screenshots; keeps transparency."
                OutFormat.WEBP -> "Smaller than JPG at the same quality; keeps transparency."
                OutFormat.PDF -> "For printing: the page is the exact print size at the DPI below."
            }
        )
        if (vm.fmt == OutFormat.WEBP) SwitchRow("WEBP lossless", vm.webpLossless, { vm.webpLossless = it })
        if (lossy) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Quality", Modifier.width(64.dp), fontSize = 14.sp)
                Slider(
                    value = vm.quality.toFloat(), onValueChange = { vm.quality = it.roundToInt() },
                    valueRange = 10f..100f, modifier = Modifier.weight(1f),
                )
                Text("${vm.quality}%", Modifier.width(48.dp), textAlign = TextAlign.End)
            }
        }
        SwitchRow(
            "Max file size", vm.targetOn && lossy, { vm.targetOn = it }, enabled = lossy,
            hint = if (lossy) "e.g. 200 KB for online forms" else "Works with JPG, PDF and lossy WEBP",
        )
        if (vm.targetOn && lossy) {
            NumberField(
                "Max size", vm.targetKb.toDouble(), 0, { vm.targetKb = it.roundToInt().coerceIn(5, 50000) },
                Modifier.width(160.dp), suffix = "KB",
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            NumberField("Print DPI", vm.dpi.toDouble(), 0, { vm.changeDpi(it.roundToInt()) }, Modifier.width(120.dp))
            HintText("Saved in the file so it prints at the right size.")
        }
        vm.result?.let { r ->
            val q = if (r.qualityUsed != null && r.fmt != OutFormat.PNG) ", quality ${r.qualityUsed}%" else ""
            InfoLines(
                listOf(
                    "Result: ${r.image.width} × ${r.image.height} px" to null,
                    "File size: ${ImageEngine.humanSize(r.sizeBytes.toLong())} (${r.fmt.label}$q)" to null,
                )
            )
        }
        HintText("Location and camera details are not copied into saved files.")
    }
}

@Composable
private fun BigButton(icon: ImageVector, title: String, sub: String, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .background(Color(0xFFF8FAFC), RoundedCornerShape(10.dp))
            .border(1.dp, CardBorder, RoundedCornerShape(10.dp))
            .clickable(onClick = onClick)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = Accent)
        Spacer(Modifier.width(12.dp))
        Column {
            Text(title, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
            Text(sub, fontSize = 12.sp, color = Hint)
        }
    }
}

@Composable
private fun ShareTab(vm: MainViewModel, actions: UiActions) {
    Panel("Save & share") {
        BigButton(Icons.Filled.Save, "Save to Gallery", "Pictures/${Outputs.FOLDER} – never overwrites") {
            actions.withStorage { ok -> if (ok) vm.saveToGallery() else vm.requestSaveAs() }
        }
        BigButton(Icons.Filled.Folder, "Save as…", "Choose the folder and file name") { vm.requestSaveAs() }
        BigButton(Icons.Filled.Share, "Share…", "Email, Drive, Messages or any app") { vm.share() }
        BigButton(Icons.Filled.ContentCopy, "Copy", "Then paste into another app") { vm.copy() }
    }
    Panel("WhatsApp") {
        Button(
            onClick = { actions.withStorage { ok -> vm.shareWhatsApp(ok) } },
            colors = ButtonDefaults.buttonColors(containerColor = Green),
            modifier = Modifier.fillMaxWidth().height(48.dp),
        ) {
            Icon(Icons.Filled.Send, null)
            Spacer(Modifier.width(8.dp))
            Text("Send on WhatsApp")
        }
        OutlinedTextField(
            value = vm.waPhone,
            onValueChange = { t -> vm.waPhone = t.filter { it.isDigit() || it == '+' || it == ' ' } },
            label = { Text("Phone number (optional)") },
            placeholder = { Text("e.g. +44 7700 900123") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
            modifier = Modifier.fillMaxWidth(),
        )
        val waNumber = vm.whatsAppNumber()
        if (waNumber.isNotEmpty()) {
            Text("Opens the chat with +$waNumber", fontSize = 13.sp, color = GoodColor)
        }
        HintText("With a number WhatsApp opens that chat straight away. Local numbers like 07700 900123 get your country code added.")
        HintText(
            "WhatsApp compresses photos. For full quality, in WhatsApp tap 📎 → Document and pick the file from " +
                "Pictures/${Outputs.FOLDER}/WhatsApp (saved automatically), or turn on HD before sending."
        )
    }
    Panel("More") {
        BigButton(Icons.Filled.Description, "Proof sheet for customers", "Size in inches, area in Sq.Ft, note, close-up, watermark") {
            vm.openProof()
        }
        BigButton(Icons.Filled.Collections, "Batch resize", "Resize or convert many photos at once") { vm.openBatch() }
    }
}

// ============================================================ dialogs

@Composable
private fun PresetsDialog(vm: MainViewModel, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Close") } },
        title = { Text("Choose a size") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Presets.SIZE_GROUPS.forEach { (group, list) ->
                    Text(group, fontWeight = FontWeight.SemiBold, color = Accent, modifier = Modifier.padding(top = 10.dp, bottom = 2.dp))
                    list.forEach { p ->
                        Text(
                            p.label,
                            fontSize = 15.sp,
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    vm.applyPreset(p)
                                    onDismiss()
                                }
                                .padding(vertical = 10.dp),
                        )
                    }
                }
            }
        },
    )
}

@Composable
private fun ColorDialog(initial: Int, onPick: (Int) -> Unit, onDismiss: () -> Unit) {
    val palette = listOf(
        0xFFFFFFFF, 0xFF000000, 0xFFF1F5F9, 0xFF94A3B8, 0xFF1A73E8, 0xFF0EA5E9, 0xFF22C55E, 0xFF15803D,
        0xFFEAB308, 0xFFF97316, 0xFFEF4444, 0xFFEC4899, 0xFF8B5CF6, 0xFF7C2D12, 0xFFFDE68A, 0xFFBFDBFE,
    ).map { it.toInt() }
    var hex by remember { mutableStateOf(String.format("%06X", initial and 0xFFFFFF)) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Background colour") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    palette.forEach { c ->
                        ColorSwatch(c, (c and 0xFFFFFF) == (initial and 0xFFFFFF)) {
                            onPick(c)
                            onDismiss()
                        }
                    }
                }
                OutlinedTextField(
                    value = hex,
                    onValueChange = { t -> hex = t.uppercase().filter { it in "0123456789ABCDEF#" }.take(7) },
                    label = { Text("Hex colour, e.g. FF8800") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = {
                hex.trimStart('#').toLongOrNull(16)?.let { onPick((0xFF000000 or (it and 0xFFFFFF)).toInt()) }
                onDismiss()
            }) { Text("Use") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
