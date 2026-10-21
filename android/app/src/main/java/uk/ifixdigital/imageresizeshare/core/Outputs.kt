package uk.ifixdigital.imageresizeshare.core

import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import java.io.File
import java.io.IOException

/** Saving to the gallery, sharing, WhatsApp and clipboard helpers. */
object Outputs {
    const val FOLDER = "Image Resize & Share"

    class Saved(val uri: Uri, val where: String)

    fun needsStoragePermission(): Boolean = Build.VERSION.SDK_INT < 29

    /** Save into Pictures/Image Resize & Share[/sub] (PDFs go to Download/…). Never overwrites. */
    fun saveToGallery(context: Context, data: ByteArray, name: String, mime: String, sub: String? = null): Saved {
        val isImage = mime.startsWith("image/")
        val topDir = if (isImage) Environment.DIRECTORY_PICTURES else Environment.DIRECTORY_DOWNLOADS
        val rel = "$topDir/$FOLDER" + (sub?.let { "/$it" } ?: "")
        val cr = context.contentResolver
        if (Build.VERSION.SDK_INT >= 29) {
            val collection = if (isImage) MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            else MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, name)
                put(MediaStore.MediaColumns.MIME_TYPE, mime)
                put(MediaStore.MediaColumns.RELATIVE_PATH, rel)
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = cr.insert(collection, values) ?: throw IOException("Could not create the file.")
            try {
                cr.openOutputStream(uri)?.use { it.write(data) } ?: throw IOException("Could not write the file.")
                values.clear()
                values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                cr.update(uri, values, null, null)
            } catch (e: Exception) {
                cr.delete(uri, null, null)
                throw e
            }
            return Saved(uri, rel)
        }
        @Suppress("DEPRECATION")
        val base = Environment.getExternalStoragePublicDirectory(topDir)
        val dir = File(base, FOLDER + (sub?.let { "/$it" } ?: ""))
        if (!dir.exists() && !dir.mkdirs()) throw IOException("Could not create folder $rel")
        val file = uniqueFile(dir, name)
        file.writeBytes(data)
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, file.name)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            @Suppress("DEPRECATION")
            put(MediaStore.MediaColumns.DATA, file.absolutePath)
        }
        val collection = if (isImage) MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        else MediaStore.Files.getContentUri("external")
        val uri = try {
            cr.insert(collection, values)
        } catch (_: Exception) {
            null
        } ?: Uri.fromFile(file)
        return Saved(uri, rel)
    }

    private fun uniqueFile(dir: File, name: String): File {
        var f = File(dir, name)
        if (!f.exists()) return f
        val dot = name.lastIndexOf('.')
        val stem = if (dot > 0) name.substring(0, dot) else name
        val ext = if (dot > 0) name.substring(dot) else ""
        var i = 1
        while (f.exists()) {
            f = File(dir, "${stem}_$i$ext")
            i++
        }
        return f
    }

    /** Write to the app cache and return a shareable content:// Uri. */
    fun cacheForShare(context: Context, data: ByteArray, name: String): Uri {
        val dir = File(context.cacheDir, "share")
        dir.mkdirs()
        val cutoff = System.currentTimeMillis() - 24L * 3600 * 1000
        dir.listFiles()?.forEach { if (it.lastModified() < cutoff) it.delete() }
        val safe = name.replace(Regex("[\\\\/:*?\"<>|]"), "_")
        val f = File(dir, safe)
        f.writeBytes(data)
        return FileProvider.getUriForFile(context, context.packageName + ".fileprovider", f)
    }

    fun shareIntent(uris: List<Uri>, mime: String): Intent {
        val i = if (uris.size == 1) {
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris[0])
        } else {
            Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
        }
        i.type = mime
        val clip = ClipData.newRawUri("", uris[0])
        for (u in uris.drop(1)) clip.addItem(ClipData.Item(u))
        i.clipData = clip
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return i
    }

    private fun installed(pm: PackageManager, pkg: String): Boolean = try {
        @Suppress("DEPRECATION")
        pm.getPackageInfo(pkg, 0)
        true
    } catch (_: Exception) {
        false
    }

    /** WhatsApp, or WhatsApp Business, whichever is installed. */
    fun whatsAppPackage(context: Context): String? =
        listOf("com.whatsapp", "com.whatsapp.w4b").firstOrNull { installed(context.packageManager, it) }

    fun cleanPhone(phone: String): String = phone.filter { it.isDigit() }

    /** Share straight into WhatsApp, optionally to one phone number (with country code). */
    fun whatsAppIntent(context: Context, uris: List<Uri>, mime: String, phone: String): Intent? {
        val pkg = whatsAppPackage(context) ?: return null
        val i = shareIntent(uris, mime)
        i.setPackage(pkg)
        val digits = cleanPhone(phone)
        if (digits.length >= 7) i.putExtra("jid", "$digits@s.whatsapp.net")
        return i
    }

    fun copyToClipboard(context: Context, uri: Uri, label: String = "Image") {
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newUri(context.contentResolver, label, uri))
    }
}
