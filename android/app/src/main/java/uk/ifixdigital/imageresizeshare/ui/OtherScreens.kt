@file:OptIn(ExperimentalMaterial3Api::class)

package uk.ifixdigital.imageresizeshare.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import uk.ifixdigital.imageresizeshare.core.ImageEngine
import uk.ifixdigital.imageresizeshare.core.OutFormat
import uk.ifixdigital.imageresizeshare.core.Outputs
import uk.ifixdigital.imageresizeshare.core.Proof
import kotlin.math.roundToInt

@Composable
private fun BackBar(title: String, onBack: () -> Unit) {
    TopAppBar(
        title = { Text(title, fontWeight = FontWeight.SemiBold) },
        navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.Filled.ArrowBack, "Back") } },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.White),
    )
}

// ============================================================ proof sheet

@Composable
fun ProofScreen(vm: MainViewModel, actions: UiActions, snackbar: SnackbarHostState) {
    val p = vm.proof
    Scaffold(
        topBar = { BackBar("Proof sheet") { vm.screen = Screen.MAIN } },
        snackbarHost = { SnackbarHost(snackbar) },
        containerColor = PageBg,
        bottomBar = {
            Surface(color = Color.White, shadowElevation = 8.dp) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedButton(
                        onClick = { actions.withStorage { ok -> if (ok) vm.saveProof() else vm.requestProofSaveAs() } },
                        modifier = Modifier.weight(1f),
                    ) {
                        Icon(Icons.Filled.Save, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Save")
                    }
                    OutlinedButton(onClick = vm::shareProof, modifier = Modifier.weight(1f)) {
                        Icon(Icons.Filled.Share, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Share")
                    }
                    Button(
                        onClick = { actions.withStorage { ok -> vm.whatsAppProof(ok) } },
                        modifier = Modifier.weight(1.25f),
                        colors = ButtonDefaults.buttonColors(containerColor = Green),
                    ) {
                        Icon(Icons.Filled.Send, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("WhatsApp", maxLines = 1)
                    }
                }
            }
        },
    ) { pad ->
        Column(
            Modifier
                .padding(pad)
                .fillMaxSize(),
        ) {
            Box(Modifier.fillMaxWidth().weight(1f)) {
                val r = vm.proofRender
                ZoomableImage(
                    vm.proofDisplay, r?.bitmap?.width ?: 0, r?.bitmap?.height ?: 0, Modifier.fillMaxSize(),
                    onTap = { x, y -> vm.tapProof(x, y) },
                )
                if (vm.proofBusy) LinearProgressIndicator(Modifier.fillMaxWidth().align(Alignment.TopCenter))
                if (r != null) {
                    Text(
                        "Tap the design to choose the close-up spot · ${r.bitmap.width} × ${r.bitmap.height} px",
                        color = Color.White, fontSize = 12.sp,
                        modifier = Modifier
                            .align(Alignment.BottomStart)
                            .padding(8.dp)
                            .background(Color(0xCC0F172A), RoundedCornerShape(6.dp))
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                    )
                }
            }
            Column(
                Modifier
                    .weight(1.2f)
                    .fillMaxWidth()
                    .imePadding()
                    .verticalScroll(rememberScrollState())
                    .padding(vertical = 6.dp),
            ) {
                Panel("Print size") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        NumberField("Width (inches)", p.widthIn, 2, { vm.setProofWidth(it) }, Modifier.weight(1f))
                        NumberField("Height (inches)", p.heightIn, 2, { vm.setProofHeight(it) }, Modifier.weight(1f))
                    }
                    SwitchRow("Keep the design's shape", vm.proofLock, { vm.proofLock = it })
                    Dropdown(
                        "Show size in", listOf("in", "ft", "cm"), p.unit,
                        {
                            when (it) {
                                "in" -> "Inches  (125”x 104”)"
                                "ft" -> "Feet + inches  (10'5” x 8'8”)"
                                else -> "Centimetres"
                            }
                        },
                        { vm.updateProof(p.copy(unit = it)) },
                    )
                    SwitchRow("Show area", p.showArea, { vm.updateProof(p.copy(showArea = it)) })
                    Dropdown(
                        "Area in", listOf("sqft", "sqm"), p.areaUnit,
                        { if (it == "sqft") "Square feet (Sq.Ft)" else "Square metres (Sq.M)" },
                        { vm.updateProof(p.copy(areaUnit = it)) }, enabled = p.showArea,
                    )
                    Text(
                        "${Proof.sizeLabel(p.widthIn, p.heightIn, p.unit)}  =  ${Proof.areaLabel(p.widthIn, p.heightIn, p.areaUnit)}",
                        fontSize = 19.sp, fontWeight = FontWeight.Bold, color = Color(0xFF0F172A),
                    )
                    val (q, warn) = vm.proofQuality()
                    val (dw, dh) = vm.proofDesignPx
                    InfoLines(listOf("Design: $dw × $dh px" to null, q to warn))
                    Dropdown(
                        "Design", listOf(true, false), p.fill,
                        { if (it) "Trim design to the print shape" else "Show whole design (white bars)" },
                        { vm.updateProof(p.copy(fill = it)) },
                    )
                }
                Panel("Note") {
                    OutlinedTextField(
                        value = p.noteTitle, onValueChange = { vm.updateProof(p.copy(noteTitle = it)) },
                        label = { Text("Title") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = vm.proofNoteText, onValueChange = { vm.setProofNote(it) },
                        label = { Text("Note") }, minLines = 3, maxLines = 5, modifier = Modifier.fillMaxWidth(),
                    )
                    HintText("Up to 3 lines. Text shrinks automatically to fit.")
                }
                Panel("Extras") {
                    SwitchRow("Add close-up detail", p.closeup, { vm.updateProof(p.copy(closeup = it)) }, hint = "Tap the preview to choose the spot.")
                    Dropdown(
                        "Close-up area", listOf(0.10, 0.16, 0.26), p.closeupFraction,
                        {
                            when (it) {
                                0.10 -> "Small (strong zoom)"
                                0.16 -> "Medium"
                                else -> "Large"
                            }
                        },
                        { vm.updateProof(p.copy(closeupFraction = it)) }, enabled = p.closeup,
                    )
                    OutlinedTextField(
                        value = p.watermark, onValueChange = { vm.updateProof(p.copy(watermark = it)) },
                        label = { Text("Watermark (protects your design)") },
                        placeholder = { Text("e.g. your shop name – leave empty for none") },
                        singleLine = true, modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = p.footer, onValueChange = { vm.updateProof(p.copy(footer = it)) },
                        label = { Text("Footer") },
                        placeholder = { Text("e.g. shop name · phone · order number") },
                        singleLine = true, modifier = Modifier.fillMaxWidth(),
                    )
                    Dropdown(
                        "Proof width", listOf(1200, 1800, 2400, 3200), p.widthPx, { "$it px" },
                        { vm.updateProof(p.copy(widthPx = it)) },
                    )
                    Dropdown(
                        "Save as", listOf(OutFormat.JPG, OutFormat.PNG, OutFormat.PDF), vm.proofFmt,
                        { if (it == OutFormat.PDF) "PDF document" else "${it.label} image" },
                        { vm.proofFmt = it },
                    )
                    TextButton(onClick = vm::requestProofSaveAs) { Text("Save as… (choose folder)") }
                }
            }
        }
    }
}

// ============================================================ batch

@Composable
fun BatchScreen(vm: MainViewModel, actions: UiActions, snackbar: SnackbarHostState) {
    Scaffold(
        topBar = { BackBar("Batch resize & convert") { vm.screen = Screen.MAIN } },
        snackbarHost = { SnackbarHost(snackbar) },
        containerColor = PageBg,
    ) { pad ->
        Column(
            Modifier
                .padding(pad)
                .fillMaxSize()
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(vertical = 6.dp),
        ) {
            Panel("Images") {
                Text("${vm.batchUris.size} image${if (vm.batchUris.size == 1) "" else "s"} selected", fontSize = 15.sp)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = actions.pickBatch, enabled = !vm.batchRunning) {
                        Icon(Icons.Filled.AddPhotoAlternate, null, Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Add images…")
                    }
                    TextButton(onClick = vm::clearBatch, enabled = !vm.batchRunning && vm.batchUris.isNotEmpty()) { Text("Clear") }
                }
            }
            Panel("Size") {
                BatchMode.entries.forEach { m ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable { vm.batchMode = m },
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(selected = vm.batchMode == m, onClick = { vm.batchMode = m })
                        Text(m.label, fontSize = 14.sp)
                    }
                }
                if (vm.batchMode == BatchMode.FIT || vm.batchMode == BatchMode.EXACT) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        NumberField("Width (px)", vm.batchW.toDouble(), 0, { vm.batchW = it.roundToInt() }, Modifier.weight(1f))
                        NumberField("Height (px)", vm.batchH.toDouble(), 0, { vm.batchH = it.roundToInt() }, Modifier.weight(1f))
                    }
                }
                if (vm.batchMode == BatchMode.PERCENT) {
                    NumberField("Percentage", vm.batchPct.toDouble(), 0, { vm.batchPct = it.roundToInt() }, Modifier.width(160.dp), suffix = "%")
                }
            }
            Panel("Output") {
                val os = vm.currentOutput()
                val lossy = ImageEngine.isLossy(os)
                var txt = os.fmt.label + if (lossy) ", quality ${os.quality}%" else ""
                if (os.targetKb > 0) txt += ", max ${os.targetKb} KB"
                HintText("Format: $txt. Change these on the Format tab.")
                OutlinedTextField(
                    value = vm.batchPattern, onValueChange = { vm.batchPattern = it },
                    label = { Text("File names") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    supportingText = { Text("{name} = original name, {w} {h} = new size") },
                )
                HintText(
                    if (os.fmt == OutFormat.PDF) "Saved to Download/${Outputs.FOLDER}/Batch"
                    else "Saved to Pictures/${Outputs.FOLDER}/Batch"
                )
            }
            Panel {
                if (vm.batchRunning) {
                    LinearProgressIndicator(progress = { vm.batchProgress }, modifier = Modifier.fillMaxWidth())
                    Text(vm.batchStatus, fontSize = 14.sp)
                    OutlinedButton(onClick = vm::cancelBatch) { Text("Cancel") }
                } else {
                    Button(
                        onClick = {
                            actions.withStorage { ok ->
                                if (ok) vm.startBatch() else vm.toast("Storage permission is needed to save the images.")
                            }
                        },
                        enabled = vm.batchUris.isNotEmpty(),
                        modifier = Modifier.fillMaxWidth().height(50.dp),
                    ) { Text("Start") }
                }
                if (vm.batchFinished || vm.batchSaved.isNotEmpty()) {
                    Text("Saved ${vm.batchSaved.size} image${if (vm.batchSaved.size == 1) "" else "s"}.", fontWeight = FontWeight.SemiBold)
                    vm.batchErrors.forEach { Text(it, color = WarnColor, fontSize = 13.sp) }
                    if (vm.batchSaved.isNotEmpty()) {
                        Button(
                            onClick = vm::shareBatch,
                            colors = ButtonDefaults.buttonColors(containerColor = Green),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Icon(Icons.Filled.Share, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("Share all")
                        }
                    }
                }
            }
        }
    }
}

// ============================================================ help

private val HELP = listOf(
    "Open" to "Tap the photo button, or share a photo to this app from Gallery, WhatsApp or Files " +
        "(“Resize & Share”). JPG, PNG, WEBP, HEIC (iPhone), AVIF, GIF and BMP are supported.",
    "Resize" to "Type a width or height in px, %, cm, mm or inches. The print size and area (Sq.Ft / Sq.M) " +
        "are shown underneath. Quick sizes and the “More” list have WhatsApp, Instagram, YouTube, passport, 4×6 and A4 sizes.",
    "Different shape?" to "Fit keeps the whole photo and adds a background (white, black, blurred, transparent or your colour). " +
        "Fit inside adds no borders. Fill trims the edges. Stretch forces the size.",
    "Enlarge" to "Upscale 2×, 3× or 4× with Enhanced: the photo is enlarged in small steps and sharpened " +
        "without white outlines. Use the Close-up to compare before and after at up to 800%.",
    "Crop" to "On the Crop tab drag the corners or edges. Pick a ratio (1:1, 4:5, 9:16, passport, A4…) " +
        "or type exact X / Y / width / height.",
    "Save" to "JPG (quality slider), PNG (lossless), WEBP or PDF for printing. “Max file size” finds the best " +
        "quality under a limit, e.g. 200 KB for online forms. Files go to Pictures/${Outputs.FOLDER} and are never overwritten.",
    "WhatsApp" to "Send on WhatsApp opens WhatsApp with the image (optionally straight to a phone number). " +
        "WhatsApp compresses photos: for full quality send it as a Document (📎 → Document) – a copy is saved in " +
        "Pictures/${Outputs.FOLDER}/WhatsApp – or turn on HD.",
    "Proof sheet" to "Make a customer preview with the size in inches or feet, the area in Sq.Ft, a note, " +
        "a close-up inset, a watermark and your shop details. Save as JPG, PNG or PDF, or send it on WhatsApp.",
    "Batch" to "Resize or convert many photos in one go with the current format settings.",
    "Quality" to "Shrinking uses Lanczos with light sharpening. JPG at 90–95% can't be told apart from the original. " +
        "Use PNG for logos and screenshots. Very large photos (over 24 megapixels) are reduced to fit in the phone's memory.",
)

@Composable
fun HelpScreen(vm: MainViewModel) {
    Scaffold(
        topBar = { BackBar("Help & tips") { vm.screen = Screen.MAIN } },
        containerColor = PageBg,
    ) { pad ->
        Column(
            Modifier
                .padding(pad)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(vertical = 6.dp),
        ) {
            HELP.forEach { (t, body) ->
                Panel(t) { Text(body, fontSize = 14.sp, lineHeight = 20.sp, color = Color(0xFF334155)) }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}
