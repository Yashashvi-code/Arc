package com.example.arc

import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import com.example.arc.services.ArcForegroundService
import com.example.arc.theme.ArcTheme

class MainActivity : ComponentActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)

    enableEdgeToEdge()
    setContent {
      ArcTheme { Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { MainNavigation() } }
    }
  }

  override fun onResume() {
    super.onResume()
    
    val prefs = getSharedPreferences("arc_prefs", Context.MODE_PRIVATE)
    val autoSync = prefs.getBoolean("auto_clipboard_sync", false)
    if (!autoSync) {
      return
    }

    // Read clipboard when app gets focus (complying with Android 10+ background limits)
    val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    if (clipboard.hasPrimaryClip()) {
      val clipData = clipboard.primaryClip
      if (clipData != null && clipData.itemCount > 0) {
        val item = clipData.getItemAt(0)
        val text = item.text?.toString() ?: ""
        val uri = item.uri
        
        if (text.isNotEmpty()) {
          val intent = Intent(this, ArcForegroundService::class.java).apply {
            action = ArcForegroundService.ACTION_SEND_CLIPBOARD
            putExtra(ArcForegroundService.EXTRA_CLIPBOARD_TEXT, text)
          }
          ContextCompat.startForegroundService(this, intent)
        } else if (uri != null) {
          val mimeType = contentResolver.getType(uri)
          if (mimeType != null && mimeType.startsWith("image/")) {
            val host = prefs.getString("host_ip", null)
            if (host != null) {
              val intent = Intent(this, ArcForegroundService::class.java).apply {
                action = ArcForegroundService.ACTION_START_TRANSFER
                putExtra(ArcForegroundService.EXTRA_FILE_URI, uri.toString())
                putExtra(ArcForegroundService.EXTRA_HOST, host)
                putExtra(ArcForegroundService.EXTRA_PORT, prefs.getString("port", "59152")?.toIntOrNull() ?: 59152)
              }
              ContextCompat.startForegroundService(this, intent)
            }
          }
        }
      }
    }
  }
}
