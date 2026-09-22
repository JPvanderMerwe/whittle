package expo.modules.whittleshare

import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.File

/**
 * The file somebody shared into whittle, as a path the app can open.
 *
 * WHY A NATIVE MODULE AT ALL. Android delivers a shared file as an
 * ACTION_SEND intent carrying a `content://` Uri in EXTRA_STREAM. React
 * Native's `Linking` exposes ACTION_VIEW urls and nothing else, and no Expo
 * package installed here reads intent extras - so the manifest filter alone
 * would put whittle in the share sheet as an app that accepts your STL and
 * silently loses it. That is a worse promise than not being there, which is
 * why the filter was not shipped until this existed.
 *
 * WHY IT COPIES RATHER THAN HANDING BACK THE Uri. A `content://` Uri is a
 * handle into somebody else's ContentProvider: it is not a path, the JS side
 * cannot read it, and the permission to read it is scoped to this intent and
 * gone once the activity is recreated. The bytes are copied into the app's own
 * cache directory while the grant is live, and what comes back is a plain
 * file:// path that expo-file-system and fetch can both open.
 *
 * WHAT IT DOES NOT DO: decide whether the file is a model. The server checks
 * magic bytes rather than trusting a name, so a wrong file is a clear refusal
 * from the engine rather than a guess made here.
 */
class WhittleShareModule : Module() {

  override fun definition() = ModuleDefinition {
    Name("WhittleShare")

    /**
     * The file this app was opened with, or null.
     *
     * CONSUMED ON READ. The launch intent lives for as long as the activity
     * does, so an app that was share-opened once and then backgrounded would
     * hand back the same file every time the JS asked - importing it again on
     * every resume. Clearing the action marks it taken.
     */
    AsyncFunction("takeSharedFile") {
      val activity = appContext.currentActivity ?: return@AsyncFunction null
      val intent = activity.intent ?: return@AsyncFunction null

      val uri = uriFrom(intent) ?: return@AsyncFunction null

      // TAKEN, whatever happens next. A copy that throws must not leave the
      // intent armed to be retried on the next resume - the failure is
      // reported once and the app goes back to its normal state.
      intent.action = null
      intent.removeExtra(Intent.EXTRA_STREAM)

      // THE ACTIVITY'S CONTEXT, NOT appContext.reactContext.
      //
      // `reactContext` is nullable and was null here - the copy returned null
      // with nothing said, so the intent was consumed and the file vanished
      // while `hasSharedFile()` had just reported true. The activity is the
      // context that is definitely alive: this code only runs because it
      // handed us its intent.
      copyIntoCache(activity, uri)
    }

    /** True when this launch carried a file, without consuming it. */
    Function("hasSharedFile") {
      val activity = appContext.currentActivity ?: return@Function false
      uriFrom(activity.intent ?: return@Function false) != null
    }
  }

  /**
   * The Uri an intent is carrying, whichever way it arrived.
   *
   * SEND puts one in EXTRA_STREAM, SEND_MULTIPLE puts a list there, and VIEW
   * puts it in the data slot - a file manager's "open with" uses the last of
   * those. Only the first of a multiple selection is taken: whittle opens one
   * model at a time, and quietly importing four would be four things the
   * person did not ask for.
   */
  private fun uriFrom(intent: Intent): Uri? = when (intent.action) {
    Intent.ACTION_SEND ->
      intent.getParcelableExtra(Intent.EXTRA_STREAM) as? Uri
    Intent.ACTION_SEND_MULTIPLE ->
      intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.firstOrNull()
    Intent.ACTION_VIEW -> intent.data
    else -> null
  }

  /**
   * Copy the shared bytes somewhere the app can read them.
   *
   * Into the CACHE directory rather than documents: this is a working copy of
   * somebody else's file, the engine keeps the real one once it is imported,
   * and the system is free to reclaim it afterwards.
   */
  private fun copyIntoCache(context: android.content.Context, uri: Uri): Map<String, Any?>? {
    val name = displayName(context, uri) ?: "shared.stl"

    val target = File(context.cacheDir, "shared").apply { mkdirs() }
      .let { File(it, "${System.currentTimeMillis()}-$name") }

    context.contentResolver.openInputStream(uri).use { input ->
      if (input == null) return null
      target.outputStream().use { output -> input.copyTo(output) }
    }

    return mapOf(
      "uri" to Uri.fromFile(target).toString(),
      "name" to name,
      "bytes" to target.length(),
    )
  }

  /**
   * What the file is called, asked of the provider that owns it.
   *
   * A content Uri's last path segment is an opaque id on most providers, so
   * using it as a filename produces "1000000042" where the person expects
   * "LCD-knob.stl". The display name is the thing they recognise and it is
   * what the library ends up storing.
   */
  private fun displayName(context: android.content.Context, uri: Uri): String? {
    if (uri.scheme == "file") return uri.lastPathSegment

    context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
      val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
      if (column >= 0 && cursor.moveToFirst()) {
        return cursor.getString(column)
      }
    }
    return uri.lastPathSegment
  }
}
