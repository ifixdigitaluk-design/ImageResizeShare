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
import android.telephony.TelephonyManager
import androidx.core.content.FileProvider
import java.io.File
import java.io.IOException
import java.util.Locale

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

    /** Country calling codes, used when a number is typed the local way ("07700 …"). */
    private val COUNTRY_CODES = mapOf(
        "GB" to "44", "PK" to "92", "IN" to "91", "AE" to "971", "SA" to "966", "QA" to "974",
        "KW" to "965", "OM" to "968", "BH" to "973", "BD" to "880", "IE" to "353", "US" to "1",
        "CA" to "1", "AU" to "61", "NZ" to "64", "ZA" to "27", "NG" to "234", "KE" to "254",
        "DE" to "49", "FR" to "33", "ES" to "34", "IT" to "39", "NL" to "31", "TR" to "90",
        "MY" to "60", "SG" to "65", "EG" to "20", "LK" to "94", "NP" to "977",
    )

    /** The phone's country code: from the SIM, else the mobile network, else the language region. */
    fun countryCode(context: Context): String {
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
        val candidates = listOf(
            try { tm?.simCountryIso } catch (_: Exception) { null },
            try { tm?.networkCountryIso } catch (_: Exception) { null },
            Locale.getDefault().country,
        )
        return candidates.filterNotNull().map { it.uppercase(Locale.ROOT) }
            .firstNotNullOfOrNull { COUNTRY_CODES[it] } ?: ""
    }

    /**
     * Digits WhatsApp understands: international format without + or 00.
     * "07700 900123" typed the local way becomes "447700900123" in the UK;
     * "+92 300 1234567" and "0092 300 …" become "923001234567". (Same rules as the Windows app.)
     */
    fun cleanPhone(phone: String, countryCode: String): String {
        val raw = phone.trim().replace("(0)", "")      // "+44 (0)7700 …" is written but not dialled
        val digits = raw.filter { it.isDigit() }
        if (digits.isEmpty()) return ""
        if (raw.startsWith("+")) return digits
        if (digits.startsWith("00")) return digits.substring(2)
        if (digits.startsWith("0")) {
            val cc = countryCode.filter { it.isDigit() }
            if (cc.isNotEmpty()) return cc + digits.substring(1)
        }
        return digits
    }

    /** Share straight into WhatsApp, optionally to one phone number. */
    fun whatsAppIntent(context: Context, uris: List<Uri>, mime: String, phone: String): Intent? {
        val pkg = whatsAppPackage(context) ?: return null
        val i = shareIntent(uris, mime)
        i.setPackage(pkg)
        val digits = cleanPhone(phone, countryCode(context))
        if (digits.length >= 7) i.putExtra("jid", "$digits@s.whatsapp.net")
        return i
    }

    fun copyToClipboard(context: Context, uri: Uri, label: String = "Image") {
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        cm.setPrimaryClip(ClipData.newUri(context.contentResolver, label, uri))
    }
}
