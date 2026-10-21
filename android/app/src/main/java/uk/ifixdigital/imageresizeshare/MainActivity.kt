package uk.ifixdigital.imageresizeshare

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat
import kotlinx.coroutines.launch
import uk.ifixdigital.imageresizeshare.core.Outputs
import uk.ifixdigital.imageresizeshare.ui.AppTheme
import uk.ifixdigital.imageresizeshare.ui.BatchScreen
import uk.ifixdigital.imageresizeshare.ui.HelpScreen
import uk.ifixdigital.imageresizeshare.ui.MainScreen
import uk.ifixdigital.imageresizeshare.ui.MainViewModel
import uk.ifixdigital.imageresizeshare.ui.ProofScreen
import uk.ifixdigital.imageresizeshare.ui.SaveAsRequest
import uk.ifixdigital.imageresizeshare.ui.Screen
import uk.ifixdigital.imageresizeshare.ui.UiActions

/** System "Save as" picker with a suggested file name and type. */
class CreateDocumentContract : ActivityResultContract<SaveAsRequest, Uri?>() {
    override fun createIntent(context: Context, input: SaveAsRequest): Intent =
        Intent(Intent.ACTION_CREATE_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType(input.mime)
            .putExtra(Intent.EXTRA_TITLE, input.name)

    override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
        if (resultCode == Activity.RESULT_OK) intent?.data else null
}

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AppTheme {
                val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
                    if (uri != null) vm.open(uri)
                }
                val browse = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
                    if (uri != null) vm.open(uri)
                }
                val pickMany = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) { uris ->
                    if (uris.isNotEmpty()) vm.addBatch(uris)
                }
                var pendingStorage by remember { mutableStateOf<((Boolean) -> Unit)?>(null) }
                val perm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
                    pendingStorage?.invoke(granted)
                    pendingStorage = null
                }
                val actions = remember {
                    UiActions(
                        pickImage = {
                            pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                        },
                        browseFiles = { browse.launch(arrayOf("image/*")) },
                        pickBatch = {
                            pickMany.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                        },
                        withStorage = { action ->
                            val granted = !Outputs.needsStoragePermission() || ContextCompat.checkSelfPermission(
                                this@MainActivity, Manifest.permission.WRITE_EXTERNAL_STORAGE,
                            ) == PackageManager.PERMISSION_GRANTED
                            if (granted) {
                                action(true)
                            } else {
                                pendingStorage = action
                                perm.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                            }
                        },
                    )
                }
                AppRoot(vm, actions)
            }
        }
        if (savedInstanceState == null) handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        when (intent?.action) {
            Intent.ACTION_SEND -> {
                IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)?.let { vm.open(it) }
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                val list = IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
                if (!list.isNullOrEmpty()) {
                    if (list.size == 1) vm.open(list[0]) else vm.openBatch(list)
                }
            }
            Intent.ACTION_VIEW, Intent.ACTION_EDIT -> intent.data?.let { vm.open(it) }
        }
    }
}

@Composable
fun AppRoot(vm: MainViewModel, actions: UiActions) {
    val snackbar = remember { SnackbarHostState() }
    val context = LocalContext.current
    var pendingProofSave by remember { mutableStateOf(false) }
    val saveAsLauncher = rememberLauncherForActivityResult(CreateDocumentContract()) { uri ->
        if (uri != null) vm.writeTo(uri, pendingProofSave)
    }
    LaunchedEffect(Unit) {
        vm.events.collect { msg ->
            snackbar.currentSnackbarData?.dismiss()
            launch { snackbar.showSnackbar(msg, duration = SnackbarDuration.Long) }
        }
    }
    LaunchedEffect(Unit) {
        vm.intents.collect { i ->
            try {
                context.startActivity(i)
            } catch (_: ActivityNotFoundException) {
                vm.toast("No app found to do this.")
            }
        }
    }
    LaunchedEffect(Unit) {
        vm.saveAs.collect { req ->
            pendingProofSave = req.proof
            try {
                saveAsLauncher.launch(req)
            } catch (_: ActivityNotFoundException) {
                vm.toast("No file picker found on this phone.")
            }
        }
    }
    BackHandler(enabled = vm.screen != Screen.MAIN) { vm.screen = Screen.MAIN }

    Box(Modifier.fillMaxSize()) {
        when (vm.screen) {
            Screen.MAIN -> MainScreen(vm, actions, snackbar)
            Screen.PROOF -> ProofScreen(vm, actions, snackbar)
            Screen.BATCH -> BatchScreen(vm, actions, snackbar)
            Screen.HELP -> HelpScreen(vm)
        }
        val busy = vm.busyText ?: if (vm.loading) "Opening…" else null
        if (busy != null) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color(0x66000000))
                    .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) {},
                contentAlignment = Alignment.Center,
            ) {
                Column(
                    Modifier
                        .background(Color.White, RoundedCornerShape(14.dp))
                        .padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    CircularProgressIndicator()
                    Spacer(Modifier.height(12.dp))
                    Text(busy)
                }
            }
        }
    }
}
