package uk.ifixdigital.imageresizeshare

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.net.Uri
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.ViewModelProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import uk.ifixdigital.imageresizeshare.core.Background
import uk.ifixdigital.imageresizeshare.core.FitMode
import uk.ifixdigital.imageresizeshare.core.OutFormat
import uk.ifixdigital.imageresizeshare.core.Presets
import uk.ifixdigital.imageresizeshare.ui.MainTab
import uk.ifixdigital.imageresizeshare.ui.MainViewModel
import uk.ifixdigital.imageresizeshare.ui.Screen
import java.io.File

/**
 * Walks through the app like a user and saves a screenshot of each screen
 * (pulled by the CI workflow so the UI can be reviewed).
 */
@RunWith(AndroidJUnit4::class)
class UiFlowTest {
    @get:Rule
    val rule = createAndroidComposeRule<MainActivity>()

    private val ctx = InstrumentationRegistry.getInstrumentation().targetContext
    private val vm: MainViewModel by lazy { ViewModelProvider(rule.activity)[MainViewModel::class.java] }

    private val robolectric = android.os.Build.FINGERPRINT == "robolectric"

    private fun shot(name: String) {
        rule.waitForIdle()
        if (!robolectric) Thread.sleep(400)
        val bmp: Bitmap? = if (robolectric) {
            try {
                rule.onRoot().captureToImage().asAndroidBitmap()
            } catch (e: Throwable) {
                rule.runOnUiThread {
                    val v = rule.activity.window.decorView
                    Bitmap.createBitmap(v.width, v.height, Bitmap.Config.ARGB_8888).also { v.draw(Canvas(it)) }
                }
            }
        } else {
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
        }
        if (bmp == null) return
        // Robolectric: android/app/build/screens ; device: app files/screens
        val dir = (if (robolectric) File("build/screens") else File(ctx.filesDir, "screens")).apply { mkdirs() }
        File(dir, "$name.png").outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    private fun testPhoto(): Uri {
        val w = 1600
        val h = 1200
        val b = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val c = Canvas(b)
        c.drawColor(Color.rgb(30, 120, 200))
        val p = Paint(Paint.ANTI_ALIAS_FLAG)
        p.color = Color.rgb(250, 200, 60)
        c.drawCircle(1150f, 330f, 170f, p)
        p.color = Color.rgb(40, 140, 70)
        val path = android.graphics.Path().apply {
            moveTo(0f, 1200f); lineTo(500f, 520f); lineTo(900f, 1000f); lineTo(1200f, 700f); lineTo(1600f, 1200f); close()
        }
        c.drawPath(path, p)
        p.color = Color.WHITE
        p.textSize = 90f
        c.drawText("Sample photo", 80f, 160f, p)
        val f = File(ctx.cacheDir, "sample_photo.jpg")
        f.outputStream().use { b.compress(Bitmap.CompressFormat.JPEG, 95, it) }
        return Uri.fromFile(f)
    }

    /** Idle the UI and poll (works on devices and under Robolectric's paused clock). */
    private fun waitFor(what: String, cond: () -> Boolean) {
        repeat(1200) {
            rule.waitForIdle()
            if (cond()) return
            Thread.sleep(50)
        }
        throw AssertionError("Timed out waiting for: $what")
    }

    private fun waitIdle(cond: () -> Boolean) =
        waitFor("result") { !vm.processing && vm.busyText == null && cond() }

    @Test
    fun walkThrough() {
        rule.runOnUiThread { vm.debounceMs = 0 }
        shot("01_start")
        val uri = testPhoto()
        rule.runOnUiThread { vm.open(uri) }
        waitIdle { vm.result != null }
        assertEquals(1600, vm.result!!.image.width)
        shot("02_opened")

        rule.onNodeWithText("1080 × 1080").performScrollTo().performClick()
        waitIdle { vm.result?.image?.width == 1080 && vm.result?.image?.height == 1080 }
        shot("03_preset_1080_fit")

        rule.runOnUiThread { vm.background = Background.BLUR }
        waitIdle { vm.result?.image?.getPixel(540, 4) != Color.WHITE }
        shot("04_blur_background")

        rule.runOnUiThread {
            vm.background = Background.WHITE
            vm.applyPreset(Presets.SIZE_GROUPS[2].second[0])   // passport 35 × 45 mm
        }
        waitIdle { vm.result?.image?.width == 413 && vm.result?.image?.height == 531 }
        shot("05_passport")

        rule.runOnUiThread { vm.tab = MainTab.CROP }
        shot("06_crop_tab")
        rule.runOnUiThread { vm.selectRatio(Presets.CROP_RATIOS[2]) }   // 1:1
        waitIdle { vm.edit.crop != null }
        shot("07_crop_square")

        rule.runOnUiThread {
            vm.cropClear()
            vm.tab = MainTab.RESIZE
            vm.applyPreset(Presets.QUICK[0])          // original
        }
        waitIdle { vm.result?.image?.width == 1600 }
        rule.runOnUiThread { vm.quickUpscale(2) }
        waitIdle { vm.result?.image?.width == 3200 }
        rule.runOnUiThread {
            vm.closeUpOn = true
            vm.tapResult(1700f, 700f)
        }
        waitFor("close-up") { vm.closeAfter != null }
        shot("08_upscale_closeup")

        rule.runOnUiThread {
            vm.closeUpOn = false
            vm.rotate(true)
            vm.tab = MainTab.FORMAT
            vm.fmt = OutFormat.WEBP
        }
        waitIdle { vm.result?.fmt == OutFormat.WEBP && vm.result?.image?.width == 2400 }
        shot("09_format_tab")

        rule.runOnUiThread {
            vm.fmt = OutFormat.JPG
            vm.targetOn = true
            vm.targetKb = 150
        }
        waitIdle { vm.result?.fmt == OutFormat.JPG && (vm.result?.sizeBytes ?: Int.MAX_VALUE) <= 150 * 1024 }
        rule.runOnUiThread {
            vm.targetOn = false
            vm.tab = MainTab.SHARE
        }
        shot("10_share_tab")

        rule.runOnUiThread { vm.saveToGallery() }
        waitFor("save") { vm.busyText == null }
        shot("11_saved")

        rule.runOnUiThread { vm.openProof() }
        waitFor("proof") { vm.screen == Screen.PROOF && vm.proofRender != null && !vm.proofBusy }
        val firstProof = vm.proofRender
        rule.runOnUiThread {
            vm.updateProof(vm.proof.copy(closeup = true, watermark = "iFix Digital", footer = "Shop · 01234 567890 · Order 42"))
        }
        waitFor("proof update") { vm.proofRender !== firstProof && !vm.proofBusy }
        shot("12_proof")

        rule.runOnUiThread { vm.openBatch(listOf(uri, uri)) }
        shot("13_batch")
        rule.runOnUiThread { vm.startBatch() }
        waitFor("batch") { vm.batchFinished }
        val batchSaved = vm.batchSaved.size
        shot("14_batch_done")

        rule.runOnUiThread { vm.screen = Screen.HELP }
        shot("15_help")
        rule.runOnUiThread {
            vm.screen = Screen.MAIN
            vm.tab = MainTab.RESIZE
            vm.mode = FitMode.FIT_PAD
        }
        shot("16_resize_tab")
        assertTrue(vm.problem == null)
        // Robolectric's MediaStore is a stub, so only check saving on a real device
        if (!robolectric) assertEquals(2, batchSaved)
    }
}
