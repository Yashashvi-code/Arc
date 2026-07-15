package com.example.arc.services

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.example.arc.MainActivity
import com.example.arc.bluetooth.BleGattClient
import com.example.arc.networking.TcpClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.EOFException
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.UUID

enum class TransferState {
    IDLE, CONNECTING, TRANSFERRING, COMPLETED, ERROR
}

data class TransferProgressState(
    val state: TransferState = TransferState.IDLE,
    val fileName: String = "",
    val bytesSent: Long = 0L,
    val totalBytes: Long = 0L,
    val speedBps: Double = 0.0,
    val error: String = "",
    val sessionId: String = "",
    val isBleConnected: Boolean = false,
    val isWifiConnected: Boolean = false,
    val bleLog: String = ""
)

class ArcForegroundService : Service() {

    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var notificationManager: NotificationManager? = null
    private var clipboardManager: ClipboardManager? = null
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())
    
    private var bleClient: BleGattClient? = null
    private var lastReceivedClipboardText = ""

    // Android TCP Server (Receiver) State
    private var serverSocket: ServerSocket? = null
    private var serverThread: Thread? = null
    private var isServerRunning = false

    companion object {
        private const val TAG = "ArcForegroundService"
        private const val CHANNEL_ID = "arc_transfer_channel"
        private const val NOTIFICATION_ID = 1001
        private const val COMPLETED_NOTIFICATION_ID = 1002

        const val ACTION_START_TRANSFER = "com.example.arc.action.START_TRANSFER"
        const val ACTION_START_BLE = "com.example.arc.action.START_BLE"
        const val ACTION_STOP_BLE = "com.example.arc.action.STOP_BLE"
        const val ACTION_SEND_CLIPBOARD = "com.example.arc.action.SEND_CLIPBOARD"
        const val ACTION_PING_LAPTOP = "com.example.arc.action.PING_LAPTOP"
        const val ACTION_CLEAR_LOGS = "com.example.arc.action.CLEAR_LOGS"
        
        const val EXTRA_FILE_URI = "com.example.arc.extra.FILE_URI"
        const val EXTRA_HOST = "com.example.arc.extra.HOST"
        const val EXTRA_PORT = "com.example.arc.extra.PORT"
        const val EXTRA_CLIPBOARD_TEXT = "com.example.arc.extra.CLIPBOARD_TEXT"

        val transferState = MutableStateFlow(TransferProgressState())
    }

    override fun onCreate() {
        super.onCreate()
        notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        clipboardManager = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        createNotificationChannel()
        
        // Initialize BLE GATT client
        bleClient = BleGattClient(this, object : BleGattClient.BleListener {
            override fun onConnectionStateChange(connected: Boolean) {
                Log.i(TAG, "BLE Connection State: $connected")
                val logText = if (connected) "Connected to laptop" else "Disconnected from laptop"
                transferState.value = transferState.value.copy(
                    isBleConnected = connected,
                    bleLog = logText
                )
                
                if (connected) {
                    val ip = getLocalIpAddress()
                    if (ip != null) {
                        Log.i(TAG, "Auto-writing phone IP coordinates: $ip:59152")
                        bleClient?.writeCoordinates(ip, 59152)
                        transferState.value = transferState.value.copy(
                            bleLog = "Pairing successful. Local IP synced."
                        )
                    } else {
                        Log.w(TAG, "Could not determine local IP address.")
                        transferState.value = transferState.value.copy(
                            bleLog = "Warning: Wi-Fi offline. Pairing limited."
                        )
                    }
                } else {
                    Log.i(TAG, "BLE Disconnected. Re-starting scan...")
                    bleClient?.startScan()
                }
            }

            override fun onClipboardReceived(text: String) {
                if (text.isEmpty() || text == lastReceivedClipboardText) return
                
                lastReceivedClipboardText = text
                clipboardManager?.let { cm ->
                    val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
                    mainHandler.post {
                        try {
                            val clip = ClipData.newPlainText("arc_sync", text)
                            cm.setPrimaryClip(clip)
                            Log.i(TAG, "System clipboard updated from BLE notification.")
                        } catch (e: Exception) {
                            Log.e(TAG, "Failed to write received text to system clipboard: ${e.message}")
                        }
                    }
                }
            }

            override fun onPcIpReceived(ipAndToken: String) {
                Log.i(TAG, "Laptop IP and token received via BLE: $ipAndToken — saving to prefs")
                val parts = ipAndToken.split("|")
                val ip = parts[0]
                val token = if (parts.size > 1) parts[1] else ""
                
                val prefs = getSharedPreferences("arc_prefs", MODE_PRIVATE)
                prefs.edit().apply {
                    putString("host_ip", ip)
                    putString("port", "59152")
                    putString("auth_token", token)
                    apply()
                }
                
                transferState.value = transferState.value.copy(
                    bleLog = "Ecosystem paired. Laptop IP: $ip"
                )
            }
            override fun onError(message: String) {
                Log.e(TAG, "BLE Client Error: $message")
                transferState.value = transferState.value.copy(bleLog = "BLE Error: $message")
            }
        })

        // Start local TCP receiver server
        startReceiverServer()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START_TRANSFER -> {
                val fileUriString = intent.getStringExtra(EXTRA_FILE_URI)
                val host = intent.getStringExtra(EXTRA_HOST) ?: "127.0.0.1"
                val port = intent.getIntExtra(EXTRA_PORT, 59152)

                if (fileUriString != null) {
                    val fileUri = Uri.parse(fileUriString)
                    startTransferTask(fileUri, host, port)
                }
            }
            ACTION_START_BLE -> {
                Log.i(TAG, "Starting BLE scans...")
                val notification = buildNotification("Monitoring ecosystem connection...", 0, 0L)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
                } else {
                    startForeground(NOTIFICATION_ID, notification)
                }
                
                transferState.value = transferState.value.copy(bleLog = "Scanning for bridge...")
                bleClient?.startScan()
            }
            ACTION_STOP_BLE -> {
                Log.i(TAG, "Stopping BLE GATT connections & servers...")
                bleClient?.disconnect()
                stopReceiverServer()
                stopForeground(STOP_FOREGROUND_DETACH)
                stopSelf()
            }
            ACTION_SEND_CLIPBOARD -> {
                val text = intent.getStringExtra(EXTRA_CLIPBOARD_TEXT)
                if (text != null && text != lastReceivedClipboardText) {
                    Log.i(TAG, "Pushed clipboard sync: ${text.take(30)}...")
                    // 1. Send via BLE (if connected)
                    bleClient?.writeClipboard(text)
                    
                    // 2. Send via Wi-Fi TCP to laptop
                    val prefs = getSharedPreferences("arc_prefs", Context.MODE_PRIVATE)
                    val host = prefs.getString("host_ip", null)
                    val port = prefs.getString("port", "59152")?.toIntOrNull() ?: 59152
                    val authToken = prefs.getString("auth_token", "") ?: ""
                    if (host != null) {
                        Thread {
                            try {
                                Log.i(TAG, "Syncing clipboard over Wi-Fi to $host:$port")
                                val socket = Socket(host, port)
                                
                                // Create 81-byte header
                                val magic = byteArrayOf('A'.code.toByte(), 'R'.code.toByte(), 'C'.code.toByte(), 1)
                                val type = 0x04.toByte()
                                val sessionUuid = UUID.randomUUID()
                                val sessionUuidBytes = ByteBuffer.allocate(16).apply {
                                    putLong(sessionUuid.mostSignificantBits)
                                    putLong(sessionUuid.leastSignificantBits)
                                }.array()
                                
                                val payload = text.toByteArray(Charsets.UTF_8)
                                val payloadLen = payload.size
                                val checksum = MessageDigest.getInstance("SHA-256").digest(payload)
                                val tokenBytes = hexStringToByteArray(authToken)
                                
                                val header = ByteBuffer.allocate(81).apply {
                                    put(magic)
                                    put(type)
                                    put(tokenBytes)
                                    put(sessionUuidBytes)
                                    putLong(0L) // chunk_idx
                                    putInt(payloadLen)
                                    put(checksum)
                                }.array()
                                
                                socket.getOutputStream().write(header)
                                socket.getOutputStream().write(payload)
                                socket.getOutputStream().flush()
                                socket.close()
                                Log.i(TAG, "Successfully synced clipboard to PC over Wi-Fi.")
                            } catch (e: Exception) {
                                Log.e(TAG, "Failed to sync clipboard to PC over Wi-Fi: ${e.message}")
                            }
                        }.start()
                    }
                }
            }
            ACTION_PING_LAPTOP -> {
                val host = intent.getStringExtra(EXTRA_HOST) ?: "127.0.0.1"
                val port = intent.getIntExtra(EXTRA_PORT, 59152)
                pingLaptop(host, port)
            }
            ACTION_CLEAR_LOGS -> {
                Log.i(TAG, "Clearing diagnostic logs...")
                transferState.value = transferState.value.copy(bleLog = "")
            }
        }
        return START_NOT_STICKY
    }

    // Android Wi-Fi TCP Receiver Server Implementation
    private fun startReceiverServer() {
        if (isServerRunning) return
        isServerRunning = true
        serverThread = Thread {
            try {
                serverSocket = ServerSocket(59152)
                Log.i(TAG, "Local TCP receiver server running on port 59152")
                while (isServerRunning) {
                    val socket = serverSocket?.accept() ?: break
                    Thread { handleIncomingConnection(socket) }.start()
                }
            } catch (e: Exception) {
                Log.e(TAG, "TCP Receiver Server error: ${e.message}")
            }
        }.apply { start() }
    }

    private fun stopReceiverServer() {
        isServerRunning = false
        try {
            serverSocket?.close()
        } catch (e: Exception) {
            // ignore
        }
        serverSocket = null
        serverThread = null
    }

    private fun handleIncomingConnection(socket: Socket) {
        Log.i(TAG, "Accepted inbound data connection from ${socket.remoteSocketAddress}")
        try {
            socket.soTimeout = 30000
        } catch (e: Exception) {
            // ignore
        }
        val inputStream = socket.getInputStream()
        var outputStream: FileOutputStream? = null
        var destFile: File? = null
        
        try {
            var totalSize = 0L
            var bytesReceived = 0L
            var fileName = ""
            var sessionId = ""
            var isClipboard = false
            var lastTime = System.currentTimeMillis()
            var lastBytes = 0L
            var startTime = System.currentTimeMillis()
            var speedBps = 0.0
            
            var expectedFileHash = ""
            
            while (isServerRunning) {
                // Read 81-byte header
                val header = ByteArray(81)
                try {
                    readFully(inputStream, header)
                } catch (e: EOFException) {
                    // Client disconnected cleanly
                    break
                }
                
                // Parse header values
                val expectedMagic = byteArrayOf('A'.code.toByte(), 'R'.code.toByte(), 'C'.code.toByte(), 1)
                if (!header.copyOfRange(0, 4).contentEquals(expectedMagic)) {
                    Log.w(TAG, "Received malformed header magic. Aborting.")
                    break
                }
                
                val type = header[4].toInt()
                val tokenBytes = header.copyOfRange(5, 21)
                
                // Verify auth token
                val prefs = getSharedPreferences("arc_prefs", Context.MODE_PRIVATE)
                val savedToken = prefs.getString("auth_token", "") ?: ""
                val expectedTokenBytes = hexStringToByteArray(savedToken)
                if (!tokenBytes.contentEquals(expectedTokenBytes)) {
                    Log.w(TAG, "Unauthorized TCP connection: token mismatch. Aborting.")
                    break
                }

                val sessionUuid = UUID(
                    ByteBuffer.wrap(header.copyOfRange(21, 29)).long,
                    ByteBuffer.wrap(header.copyOfRange(29, 37)).long
                )
                sessionId = sessionUuid.toString()
                
                val payloadLen = ByteBuffer.wrap(header.copyOfRange(45, 49)).int
                
                // Read payload bytes
                val payload = ByteArray(payloadLen)
                readFully(inputStream, payload)
                
                if (type == 0x01) { // METADATA
                    val json = JSONObject(String(payload, Charsets.UTF_8))
                    val rawFileName = json.getString("file_name")
                    // Sanitize filename to prevent path traversal
                    fileName = File(rawFileName).name
                    if (fileName.isEmpty() || fileName == "." || fileName == ".." || "/" in rawFileName || "\\" in rawFileName) {
                        fileName = "safe_transfer"
                    }
                    totalSize = json.getLong("total_size")
                    isClipboard = json.optBoolean("is_clipboard", false)
                    expectedFileHash = json.optString("file_hash", "")
                    
                    Log.i(TAG, "Inbound file drop metadata: $fileName ($totalSize bytes, expected_hash='$expectedFileHash', is_clip=$isClipboard)")
                    
                    val destDir = if (isClipboard) cacheDir else {
                        val publicDownloadDir = android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_DOWNLOADS)
                        val arcStayDir = File(publicDownloadDir, "Arc-Stay")
                        if (!arcStayDir.exists()) {
                            arcStayDir.mkdirs()
                        }
                        arcStayDir
                    }
                    destFile = File(destDir, fileName)
                    outputStream = FileOutputStream(destFile)
                    
                    // Update state to CONNECTING
                    transferState.value = transferState.value.copy(
                        state = TransferState.CONNECTING,
                        fileName = fileName,
                        bytesSent = 0,
                        totalBytes = totalSize,
                        sessionId = sessionId
                    )
                    updateNotification("Receiving $fileName...", 0, totalSize)
                    
                    // Reply offset (8 bytes of 0 for clean start)
                    socket.getOutputStream().write(ByteArray(8))
                    socket.getOutputStream().flush()
                }
                else if (type == 0x04) { // CLIPBOARD
                    val clipboardText = String(payload, Charsets.UTF_8)
                    Log.i(TAG, "Received clipboard content over Wi-Fi: $clipboardText")
                    
                    // Update system clipboard on main thread
                    val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
                    mainHandler.post {
                        try {
                            val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            val clip = ClipData.newPlainText("arc_sync", clipboardText)
                            cm.setPrimaryClip(clip)
                            Log.i(TAG, "System clipboard updated from Wi-Fi.")
                            android.widget.Toast.makeText(applicationContext, "Clipboard synced over Wi-Fi!", android.widget.Toast.LENGTH_SHORT).show()
                        } catch (e: Exception) {
                            Log.e(TAG, "Failed to write received text to system clipboard: ${e.message}")
                        }
                    }
                    
                    // Update logs
                    transferState.value = transferState.value.copy(
                        bleLog = "Clipboard synced: ${if (clipboardText.length > 15) clipboardText.take(15) + "..." else clipboardText}"
                    )
                    break
                }
                else if (type == 0x06) { // HASH_VERIFY
                    val receivedHash = String(payload, Charsets.UTF_8).trim()
                    Log.i(TAG, "Received final SHA-256 hash for verification: $receivedHash")
                    expectedFileHash = receivedHash
                    break
                }
                else if (type == 0x02) { // DATA
                    outputStream?.write(payload)
                    bytesReceived += payloadLen
                    
                    val now = System.currentTimeMillis()
                    val dt = (now - lastTime) / 1000.0
                    if (dt >= 1.0) {
                        val db = bytesReceived - lastBytes
                        val rawSpeedBps = db / dt
                        speedBps = 0.3 * rawSpeedBps + 0.7 * speedBps
                        lastTime = now
                        lastBytes = bytesReceived
                    } else if (speedBps == 0.0) {
                        val elapsed = (now - startTime) / 1000.0
                        speedBps = if (elapsed > 0) bytesReceived.toDouble() / elapsed else 0.0
                    }
                    
                    val percent = if (totalSize > 0) ((bytesReceived * 100) / totalSize).toInt() else 0
                    transferState.value = transferState.value.copy(
                        state = TransferState.TRANSFERRING,
                        fileName = fileName,
                        bytesSent = bytesReceived,
                        totalBytes = totalSize,
                        speedBps = speedBps
                    )
                    updateNotification("Downloading... $percent% (${fileName})", percent, totalSize)
                    
                    if (bytesReceived >= totalSize && expectedFileHash.isNotEmpty()) {
                        Log.i(TAG, "File drop complete: $fileName (metadata hash mode)")
                        break
                    }
                }
            }
            
            // Finalize transfer
            outputStream?.flush()
            outputStream?.close()
            outputStream = null
            
            if (isClipboard) {
                val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
                mainHandler.post {
                    try {
                        val contentUri = androidx.core.content.FileProvider.getUriForFile(
                            applicationContext,
                            "com.example.arc.fileprovider",
                            destFile!!
                        )
                        val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        val clip = ClipData.newUri(contentResolver, "Clipboard Image", contentUri)
                        cm.setPrimaryClip(clip)
                        android.widget.Toast.makeText(applicationContext, "Image synced to clipboard!", android.widget.Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        Log.e(TAG, "Failed to copy image to clipboard: ${e.message}")
                    }
                }
                
                transferState.value = transferState.value.copy(
                    state = TransferState.IDLE,
                    bleLog = "Image synced to clipboard."
                )
                updateNotification("Ecosystem bridge connected.", 0, 0L)
            } else {
                transferState.value = transferState.value.copy(
                    state = TransferState.COMPLETED,
                    fileName = fileName,
                    bytesSent = totalSize,
                    totalBytes = totalSize
                )
                updateNotification("Ecosystem bridge connected.", 0, 0L)
                val compNotification = buildNotification("Download completed: $fileName", 100, totalSize, isOngoing = false)
                notificationManager?.notify(COMPLETED_NOTIFICATION_ID, compNotification)
            }
            
            resetSyncState()
            
        } catch (e: Exception) {
            Log.e(TAG, "Error handling inbound transfer: ${e.message}")
            outputStream?.close()
            destFile?.delete()
            
            transferState.value = transferState.value.copy(
                state = TransferState.ERROR,
                error = e.message ?: "Connection dropped"
            )
            updateNotification("Ecosystem bridge connected.", 0, 0L)
            val errNotification = buildNotification("Download failed: ${e.message}", 0, 0L, isError = true, isOngoing = false)
            notificationManager?.notify(COMPLETED_NOTIFICATION_ID, errNotification)
            resetSyncState()
        } finally {
            socket.close()
        }
    }

    private fun readFully(inputStream: InputStream, buffer: ByteArray) {
        var offset = 0
        while (offset < buffer.size) {
            val read = inputStream.read(buffer, offset, buffer.size - offset)
            if (read == -1) throw EOFException("End of stream reached")
            offset += read
        }
    }

    private fun startTransferTask(fileUri: Uri, host: String, port: Int) {
        val sessionId = UUID.randomUUID().toString()
        transferState.value = transferState.value.copy(
            state = TransferState.CONNECTING,
            fileName = getFileName(fileUri),
            sessionId = sessionId
        )

        val notification = buildNotification("Connecting Quick Drop...", 0, 0L)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }

        val prefs = getSharedPreferences("arc_prefs", Context.MODE_PRIVATE)
        val authToken = prefs.getString("auth_token", "") ?: ""
        serviceScope.launch {
            TcpClient.sendFile(
                contentResolver = contentResolver,
                fileUri = fileUri,
                host = host,
                port = port,
                authToken = authToken,
                sessionId = sessionId,
                listener = object : TcpClient.ProgressListener {
                    override fun onProgress(bytesSent: Long, totalBytes: Long, speedBps: Double) {
                        val progressPercent = if (totalBytes > 0) ((bytesSent * 100) / totalBytes).toInt() else 0
                        val speedMb = speedBps / (1024.0 * 1024.0)
                        val text = "Sending... $progressPercent% (${String.format("%.2f", speedMb)} MB/s)"

                        transferState.value = transferState.value.copy(
                            state = TransferState.TRANSFERRING,
                            fileName = getFileName(fileUri),
                            bytesSent = bytesSent,
                            totalBytes = totalBytes,
                            speedBps = speedBps,
                            sessionId = sessionId
                        )

                        updateNotification(text, progressPercent, totalBytes)
                    }

                    override fun onError(message: String) {
                        Log.e(TAG, "Transfer error: $message")
                        transferState.value = transferState.value.copy(
                            state = TransferState.ERROR,
                            fileName = getFileName(fileUri),
                            error = message,
                            sessionId = sessionId
                        )
                        updateNotification("Ecosystem bridge connected.", 0, 0L)
                        val errNotification = buildNotification("Transfer failed: $message", 0, 0L, isError = true, isOngoing = false)
                        notificationManager?.notify(COMPLETED_NOTIFICATION_ID, errNotification)
                        resetSyncState()
                    }

                    override fun onComplete() {
                        Log.i(TAG, "Transfer completed successfully.")
                        transferState.value = transferState.value.copy(
                            state = TransferState.COMPLETED,
                            fileName = getFileName(fileUri),
                            sessionId = sessionId
                        )
                        updateNotification("Ecosystem bridge connected.", 0, 0L)
                        val compNotification = buildNotification("Received: ${getFileName(fileUri)}", 100, 100L, isOngoing = false)
                        notificationManager?.notify(COMPLETED_NOTIFICATION_ID, compNotification)
                        resetSyncState()
                    }
                }
            )
        }
    }

    private fun resetSyncState() {
        if (!transferState.value.isBleConnected) {
            stopForeground(STOP_FOREGROUND_DETACH)
            stopSelf()
        } else {
            updateNotification("Ecosystem bridge connected.", 0, 0L)
            handler.postDelayed({
                transferState.value = transferState.value.copy(
                    state = TransferState.IDLE,
                    fileName = "",
                    bytesSent = 0L,
                    totalBytes = 0L,
                    speedBps = 0.0,
                    sessionId = ""
                )
            }, 3000)
        }
    }

    private fun getLocalIpAddress(): String? {
        try {
            val interfaces = NetworkInterface.getNetworkInterfaces()
            while (interfaces.hasMoreElements()) {
                val networkInterface = interfaces.nextElement()
                val addresses = networkInterface.inetAddresses
                while (addresses.hasMoreElements()) {
                    val address = addresses.nextElement()
                    if (!address.isLoopbackAddress && address is Inet4Address) {
                        val ip = address.hostAddress
                        if (ip != null) return ip
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error getting IP", e)
        }
        return null
    }

    private fun getFileName(fileUri: Uri): String {
        var name = "file"
        contentResolver.query(fileUri, null, null, null, null)?.use { cursor ->
            val nameIdx = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (cursor.moveToFirst() && nameIdx != -1) {
                name = cursor.getString(nameIdx)
            }
        }
        return name
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Arc Sync Services",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Shows progress and state of the Arc local link."
            }
            notificationManager?.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String, progress: Int, totalBytes: Long, isError: Boolean = false, isOngoing: Boolean = true): Notification {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Arc Local Bridge")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(pendingIntent)
            .setOnlyAlertOnce(true)
            .setOngoing(isOngoing)

        if (!isOngoing) {
            builder.setAutoCancel(true)
        }

        if (totalBytes > 0 && !isError) {
            builder.setProgress(100, progress, false)
        } else {
            builder.setProgress(0, 0, false)
        }

        return builder.build()
    }

    private fun updateNotification(text: String, progress: Int, totalBytes: Long, isError: Boolean = false, isOngoing: Boolean = true) {
        val notification = buildNotification(text, progress, totalBytes, isError, isOngoing)
        notificationManager?.notify(NOTIFICATION_ID, notification)
    }

    private fun pingLaptop(host: String, port: Int) {
        Thread {
            var socket: java.net.Socket? = null
            try {
                Log.i(TAG, "Initiating secure Wi-Fi pairing request to $host:$port...")
                socket = java.net.Socket()
                // Wait up to 30s to allow the user to click Approve on the PC dialog
                socket.connect(java.net.InetSocketAddress(host, port), 30000)
                
                // Create 81-byte pairing request header
                val magic = byteArrayOf('A'.code.toByte(), 'R'.code.toByte(), 'C'.code.toByte(), 1)
                val type = 0x05.toByte() // PAIR_REQUEST
                val tokenBytes = ByteArray(16) // Empty for pairing request
                val sessionUuidBytes = ByteArray(16) // Empty for pairing request
                val checksum = ByteArray(32) // Empty for pairing request
                
                val header = ByteBuffer.allocate(81).apply {
                    put(magic)
                    put(type)
                    put(tokenBytes)
                    put(sessionUuidBytes)
                    putLong(0L) // chunk_idx
                    putInt(0) // payload_len = 0
                    put(checksum)
                }.array()
                
                // Write pairing request header
                socket.getOutputStream().write(header)
                socket.getOutputStream().flush()
                
                // Read response (expected 32-byte hex token or "REJECTED")
                val responseBuffer = ByteArray(32)
                val readBytes = socket.getInputStream().read(responseBuffer)
                if (readBytes > 0) {
                    val responseStr = String(responseBuffer, 0, readBytes, Charsets.UTF_8).trim()
                    if (responseStr == "REJECTED") {
                        handler.post {
                            android.widget.Toast.makeText(applicationContext, "Ecosystem Sync Rejected by Laptop.", android.widget.Toast.LENGTH_LONG).show()
                        }
                        transferState.value = transferState.value.copy(
                            isWifiConnected = false,
                            bleLog = "Pairing rejected by laptop."
                        )
                    } else if (responseStr.length == 32) {
                        // Success! Save received auth token in shared preferences
                        val prefs = getSharedPreferences("arc_prefs", MODE_PRIVATE)
                        prefs.edit().apply {
                            putString("host_ip", host)
                            putString("port", "59152")
                            putString("auth_token", responseStr)
                            apply()
                        }
                        
                        handler.post {
                            android.widget.Toast.makeText(applicationContext, "Ecosystem Sync Success! Coordinates paired.", android.widget.Toast.LENGTH_SHORT).show()
                        }
                        transferState.value = transferState.value.copy(
                            isWifiConnected = true,
                            bleLog = "Ecosystem paired via Wi-Fi link."
                        )
                    } else {
                        handler.post {
                            android.widget.Toast.makeText(applicationContext, "Ecosystem Sync Failed: Invalid handshake response.", android.widget.Toast.LENGTH_SHORT).show()
                        }
                    }
                } else {
                    handler.post {
                        android.widget.Toast.makeText(applicationContext, "Ecosystem Sync Failed: No response from laptop.", android.widget.Toast.LENGTH_SHORT).show()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Ecosystem sync pairing failed: ${e.message}")
                handler.post {
                    android.widget.Toast.makeText(applicationContext, "Sync Failed: ${e.message}", android.widget.Toast.LENGTH_SHORT).show()
                }
            } finally {
                try { socket?.close() } catch (ex: Exception) {}
            }
        }.start()
    }

    override fun onDestroy() {
        super.onDestroy()
        bleClient?.disconnect()
        bleClient = null
        stopReceiverServer()
    }

    private fun hexStringToByteArray(s: String): ByteArray {
        val len = s.length
        if (len != 32) return ByteArray(16)
        val data = ByteArray(16)
        try {
            for (i in 0 until 16) {
                data[i] = ((Character.digit(s[i * 2], 16) shl 4) + Character.digit(s[i * 2 + 1], 16)).toByte()
            }
        } catch (e: Exception) {
            return ByteArray(16)
        }
        return data
    }
}
