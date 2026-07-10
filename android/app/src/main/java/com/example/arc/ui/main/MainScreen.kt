package com.example.arc.ui.main

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation3.runtime.NavKey
import com.example.arc.services.ArcForegroundService
import com.example.arc.services.TransferState
import java.util.regex.Pattern

// Theme Colors matching Nothing OS design language
private val COLOR_DARK_BG = Color(0xFF0D0D0D)
private val COLOR_DARK_CARD = Color(0xFF161616)
private val COLOR_DARK_BORDER = Color(0xFF2A2A2A)
private val COLOR_DARK_DOT = Color(0x0DFFFFFF) // 5% White dots

private val COLOR_LIGHT_BG = Color(0xFFF2F2EE) // Warm off-white
private val COLOR_LIGHT_CARD = Color(0xFFE8E8E4) // Warm grey cards
private val COLOR_LIGHT_BORDER = Color(0xFF1A1A1A)
private val COLOR_LIGHT_DOT = Color(0x0A000000) // 3% Black dots

private val ACCENT_GREEN = Color(0xFF00E676) // Muted vibrant green replacing harsh red
private val ACCENT_LIME = Color(0xFFC5F500) // Diagnostic pairing Lime

private val IP_PATTERN = Pattern.compile(
    "^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)

data class RecentDrop(val fileName: String, val timestamp: String, val size: String, val success: Boolean)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    onItemClick: (NavKey) -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val progressState by ArcForegroundService.transferState.collectAsStateWithLifecycle()

    var hostIp by remember { mutableStateOf("192.168.1.1") }
    var port by remember { mutableStateOf("59152") }
    var customTextToSend by remember { mutableStateOf("") }

    // Mock history of recent drops to make app look alive & functional
    val recentDrops = remember {
        mutableStateListOf(
            RecentDrop("MATHS PBL.PDF", "18:02", "2.4 MB", true),
            RecentDrop("IMG_8530.PNG", "17:45", "840 KB", true),
            RecentDrop("DOC_SPECS.TXT", "17:21", "12 KB", false)
        )
    }

    // Capture completion of transfers in current session and append them to history
    LaunchedEffect(progressState.state) {
        if (progressState.state == TransferState.COMPLETED && progressState.fileName.isNotEmpty()) {
            recentDrops.add(0, RecentDrop(progressState.fileName.uppercase(), "NOW", "DROP", true))
        } else if (progressState.state == TransferState.ERROR && progressState.fileName.isNotEmpty()) {
            recentDrops.add(0, RecentDrop(progressState.fileName.uppercase(), "NOW", "FAIL", false))
        }
    }

    // Resolve theme colors dynamically
    val sysDark = isSystemInDarkTheme()
    
    val bgColor = if (sysDark) COLOR_DARK_BG else COLOR_LIGHT_BG
    val cardColor = if (sysDark) COLOR_DARK_CARD else COLOR_LIGHT_CARD
    val borderColor = if (sysDark) COLOR_DARK_BORDER else COLOR_LIGHT_BORDER
    val dotColor = if (sysDark) COLOR_DARK_DOT else COLOR_LIGHT_DOT
    val textPrimary = if (sysDark) Color.White else Color(0xFF1A1A1A)
    val textSecondary = if (sysDark) Color(0xFF888888) else Color(0xFF777777)

    // Load saved settings
    val prefs = remember { context.getSharedPreferences("arc_prefs", Context.MODE_PRIVATE) }
    LaunchedEffect(Unit) {
        hostIp = prefs.getString("host_ip", "10.0.2.2") ?: "10.0.2.2"
        port = prefs.getString("port", "59152") ?: "59152"
    }

    // Permission checks
    var hasNotificationPermission by remember {
        mutableStateOf(
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                androidx.core.content.ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.POST_NOTIFICATIONS
                ) == android.content.pm.PackageManager.PERMISSION_GRANTED
            } else {
                true
            }
        )
    }

    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        hasNotificationPermission = isGranted
    }

    val bluetoothPermissions = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        arrayOf(
            Manifest.permission.BLUETOOTH_SCAN,
            Manifest.permission.BLUETOOTH_CONNECT
        )
    } else {
        arrayOf(
            Manifest.permission.BLUETOOTH,
            Manifest.permission.BLUETOOTH_ADMIN,
            Manifest.permission.ACCESS_FINE_LOCATION
        )
    }

    val bluetoothPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { permissionsMap ->
        val allGranted = permissionsMap.values.all { it }
        if (allGranted) {
            val intent = Intent(context, ArcForegroundService::class.java).apply {
                action = ArcForegroundService.ACTION_START_BLE
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        } else {
            Toast.makeText(context, "Bluetooth permissions required for pairing.", Toast.LENGTH_SHORT).show()
        }
    }

    // File picker launcher
    val filePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        if (uri != null) {
            prefs.edit().apply {
                putString("host_ip", hostIp)
                putString("port", port)
                apply()
            }

            val intent = Intent(context, ArcForegroundService::class.java).apply {
                action = ArcForegroundService.ACTION_START_TRANSFER
                putExtra(ArcForegroundService.EXTRA_FILE_URI, uri.toString())
                putExtra(ArcForegroundService.EXTRA_HOST, hostIp)
                putExtra(ArcForegroundService.EXTRA_PORT, port.toIntOrNull() ?: 59152)
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }

    val scrollState = rememberScrollState()

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(bgColor)
            // GPU-Accelerated Substrate Grid Background drawing (locked 120fps)
            .drawBehind {
                val spacing = 8.dp.toPx()
                val radius = 1.dp.toPx()
                
                var x = 0f
                while (x < size.width) {
                    var y = 0f
                    while (y < size.height) {
                        drawCircle(
                            color = dotColor,
                            radius = radius,
                            center = Offset(x, y)
                        )
                        y += spacing
                    }
                    x += spacing
                }
            }
            .padding(24.dp)
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(scrollState),
            verticalArrangement = Arrangement.SpaceBetween
        ) {
            // Header
            Column(modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = "ARC",
                    color = textPrimary,
                    fontSize = 32.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 4.sp,
                    modifier = Modifier.padding(top = 16.dp)
                )
                Text(
                    text = "LOCAL ECOSYSTEM LINK",
                    color = textSecondary,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.SemiBold,
                    letterSpacing = 2.sp,
                    modifier = Modifier.padding(bottom = 24.dp)
                )

                // 1. Ecosystem Link Card
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .border(1.dp, borderColor, RoundedCornerShape(20.dp))
                        .background(cardColor, RoundedCornerShape(20.dp))
                        .padding(20.dp)
                ) {
                    Text(
                        text = "ECOSYSTEM PAIRING",
                        color = textSecondary,
                        fontSize = 9.sp,
                        fontFamily = FontFamily.SansSerif,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 1.5.sp,
                        modifier = Modifier.padding(bottom = 14.dp)
                    )

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Column {
                            Text(
                                text = "LINK STATUS",
                                color = textSecondary,
                                fontSize = 11.sp,
                                fontFamily = FontFamily.SansSerif
                            )
                            Spacer(modifier = Modifier.height(2.dp))
                            val isConnected = progressState.isBleConnected || progressState.isWifiConnected
                            Text(
                                text = if (isConnected) "CONNECTED" else "DISCONNECTED",
                                color = textPrimary,
                                fontSize = 14.sp,
                                fontWeight = FontWeight.Bold,
                                fontFamily = FontFamily.Monospace
                            )
                        }

                        // Custom signal gauge (Concentric green/lime arcs)
                        Canvas(modifier = Modifier.size(36.dp)) {
                            drawArc(
                                color = borderColor,
                                startAngle = 0f,
                                sweepAngle = 360f,
                                useCenter = false,
                                style = Stroke(width = 2.dp.toPx())
                            )
                            if (progressState.isBleConnected || progressState.isWifiConnected) {
                                drawArc(
                                    color = ACCENT_GREEN,
                                    startAngle = -90f,
                                    sweepAngle = 270f,
                                    useCenter = false,
                                    style = Stroke(width = 4.dp.toPx(), cap = StrokeCap.Round)
                                )
                                drawCircle(
                                    color = ACCENT_GREEN,
                                    radius = 3.dp.toPx(),
                                    center = Offset(size.width / 2, size.height / 2)
                                )
                            }
                        }
                    }

                    if (progressState.bleLog.isNotEmpty()) {
                        Spacer(modifier = Modifier.height(10.dp))
                        Text(
                            text = progressState.bleLog.uppercase(),
                            color = textSecondary,
                            fontSize = 10.sp,
                            fontFamily = FontFamily.Monospace
                        )
                    }

                    Spacer(modifier = Modifier.height(18.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        OutlinedButton(
                            onClick = { bluetoothPermissionLauncher.launch(bluetoothPermissions) },
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = textPrimary),
                            modifier = Modifier
                                .weight(1f)
                                .height(44.dp)
                                .border(1.dp, borderColor, RoundedCornerShape(12.dp))
                        ) {
                            Text(
                                text = "PAIR",
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold
                            )
                        }

                        OutlinedButton(
                            onClick = {
                                val intent = Intent(context, ArcForegroundService::class.java).apply {
                                    action = ArcForegroundService.ACTION_STOP_BLE
                                }
                                context.startService(intent)
                            },
                            enabled = progressState.isBleConnected || progressState.isWifiConnected || progressState.bleLog.contains("Scanning"),
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = textSecondary,
                                disabledContentColor = borderColor
                            ),
                            modifier = Modifier
                                .weight(1f)
                                .height(44.dp)
                                .border(1.dp, borderColor, RoundedCornerShape(12.dp))
                        ) {
                            Text(
                                text = "RESET",
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // 2. Manual Clipboard Utilities Card (NEW Utility Functionality)
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .border(1.dp, borderColor, RoundedCornerShape(20.dp))
                        .background(cardColor, RoundedCornerShape(20.dp))
                        .padding(20.dp)
                ) {
                    Text(
                        text = "CLIPBOARD SYNC UTILITY",
                        color = textSecondary,
                        fontSize = 9.sp,
                        fontFamily = FontFamily.SansSerif,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 1.5.sp,
                        modifier = Modifier.padding(bottom = 14.dp)
                    )

                    // Utility Button: Sync current local system clipboard to laptop over BLE
                    Button(
                        onClick = {
                            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                            if (clipboard.hasPrimaryClip()) {
                                val item = clipboard.primaryClip?.getItemAt(0)
                                val text = item?.text?.toString() ?: ""
                                if (text.isNotEmpty()) {
                                    val intent = Intent(context, ArcForegroundService::class.java).apply {
                                        action = ArcForegroundService.ACTION_SEND_CLIPBOARD
                                        putExtra(ArcForegroundService.EXTRA_CLIPBOARD_TEXT, text)
                                    }
                                    context.startService(intent)
                                    Toast.makeText(context, "System Clipboard pushed.", Toast.LENGTH_SHORT).show()
                                } else {
                                    Toast.makeText(context, "Clipboard is empty.", Toast.LENGTH_SHORT).show()
                                }
                            }
                        },
                        enabled = progressState.isBleConnected || progressState.isWifiConnected,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = cardColor,
                            contentColor = textPrimary,
                            disabledContainerColor = cardColor,
                            disabledContentColor = textSecondary
                        ),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(44.dp)
                            .border(1.dp, borderColor, RoundedCornerShape(12.dp))
                    ) {
                        Text(
                            text = "PUSH SYSTEM CLIPBOARD",
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold
                        )
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    // Text Field and Button: Custom Quick Text Send
                    OutlinedTextField(
                        value = customTextToSend,
                        onValueChange = { customTextToSend = it },
                        label = { Text("TYPE TEXT TO PUSH TO PC", fontFamily = FontFamily.Monospace, fontSize = 11.sp) },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = textPrimary,
                            unfocusedBorderColor = borderColor,
                            focusedTextColor = textPrimary,
                            unfocusedTextColor = textPrimary,
                            focusedLabelColor = textSecondary,
                            unfocusedLabelColor = textSecondary,
                            focusedContainerColor = Color.Transparent,
                            unfocusedContainerColor = Color.Transparent
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(bottom = 8.dp)
                    )

                    Button(
                        onClick = {
                            if (customTextToSend.isNotEmpty()) {
                                val intent = Intent(context, ArcForegroundService::class.java).apply {
                                    action = ArcForegroundService.ACTION_SEND_CLIPBOARD
                                    putExtra(ArcForegroundService.EXTRA_CLIPBOARD_TEXT, customTextToSend)
                                }
                                context.startService(intent)
                                customTextToSend = ""
                                Toast.makeText(context, "Custom Text pushed.", Toast.LENGTH_SHORT).show()
                            }
                        },
                        enabled = (progressState.isBleConnected || progressState.isWifiConnected) && customTextToSend.isNotEmpty(),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = ACCENT_GREEN,
                            contentColor = Color.Black
                        ),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(44.dp)
                    ) {
                        Text(
                            text = "SEND CUSTOM TEXT",
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // 3. Manual Coordinates Card
                var isCoordinatesExpanded by remember { mutableStateOf(false) }

                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .border(1.dp, borderColor, RoundedCornerShape(20.dp))
                        .background(cardColor, RoundedCornerShape(20.dp))
                        .padding(20.dp)
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { isCoordinatesExpanded = !isCoordinatesExpanded },
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "MANUAL COORDINATES",
                            color = textSecondary,
                            fontSize = 9.sp,
                            fontFamily = FontFamily.SansSerif,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 1.5.sp
                        )
                        Text(
                            text = if (isCoordinatesExpanded) "[ SHRINK ]" else "[ EXPAND ]",
                            color = ACCENT_GREEN,
                            fontSize = 9.sp,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold
                        )
                    }

                    if (isCoordinatesExpanded) {
                        Spacer(modifier = Modifier.height(14.dp))

                        OutlinedTextField(
                            value = hostIp,
                            onValueChange = { hostIp = it },
                            label = { Text("LAPTOP IP ADDRESS", fontFamily = FontFamily.Monospace, fontSize = 11.sp) },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = textPrimary,
                                unfocusedBorderColor = borderColor,
                                focusedTextColor = textPrimary,
                                unfocusedTextColor = textPrimary,
                                focusedLabelColor = textSecondary,
                                unfocusedLabelColor = textSecondary,
                                focusedContainerColor = Color.Transparent,
                                unfocusedContainerColor = Color.Transparent
                            ),
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(bottom = 8.dp)
                        )

                        OutlinedTextField(
                            value = port,
                            onValueChange = { port = it },
                            label = { Text("PORT", fontFamily = FontFamily.Monospace, fontSize = 11.sp) },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = textPrimary,
                                unfocusedBorderColor = borderColor,
                                focusedTextColor = textPrimary,
                                unfocusedTextColor = textPrimary,
                                focusedLabelColor = textSecondary,
                                unfocusedLabelColor = textSecondary,
                                focusedContainerColor = Color.Transparent,
                                unfocusedContainerColor = Color.Transparent
                            ),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(12.dp))

                        val isIpValid = IP_PATTERN.matcher(hostIp).matches()
                        Button(
                            onClick = {
                                prefs.edit().apply {
                                    putString("host_ip", hostIp)
                                    putString("port", port)
                                    apply()
                                }
                                val intent = Intent(context, ArcForegroundService::class.java).apply {
                                    action = "com.example.arc.action.PING_LAPTOP"
                                    putExtra(ArcForegroundService.EXTRA_HOST, hostIp)
                                    putExtra(ArcForegroundService.EXTRA_PORT, port.toIntOrNull() ?: 59152)
                                }
                                context.startService(intent)
                            },
                            enabled = isIpValid,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = ACCENT_GREEN,
                                contentColor = Color.Black,
                                disabledContainerColor = cardColor,
                                disabledContentColor = textSecondary
                            ),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(44.dp)
                                .border(1.dp, if (isIpValid) ACCENT_GREEN else borderColor, RoundedCornerShape(12.dp))
                        ) {
                            Text(
                                text = "SYNC ECOSYSTEM COORDINATES",
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // 4. System Diagnostic Metrics
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .border(1.dp, borderColor, RoundedCornerShape(20.dp))
                        .background(cardColor, RoundedCornerShape(20.dp))
                        .padding(20.dp)
                ) {
                    Text(
                        text = "TRANSFER DIAGNOSTIC",
                        color = textSecondary,
                        fontSize = 9.sp,
                        fontFamily = FontFamily.SansSerif,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 1.5.sp,
                        modifier = Modifier.padding(bottom = 14.dp)
                    )

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "ENGINE STATE",
                            color = textSecondary,
                            fontSize = 11.sp,
                            fontFamily = FontFamily.SansSerif
                        )
                        Text(
                            text = progressState.state.name,
                            color = when (progressState.state) {
                                TransferState.IDLE -> textSecondary
                                TransferState.CONNECTING -> Color(0xFFFFB300)
                                TransferState.TRANSFERRING -> ACCENT_GREEN
                                TransferState.COMPLETED -> textPrimary
                                TransferState.ERROR -> Color.Red
                            },
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold,
                            fontFamily = FontFamily.Monospace
                        )
                    }

                    if (progressState.state != TransferState.IDLE) {
                        Spacer(modifier = Modifier.height(10.dp))
                        HorizontalDivider(color = borderColor, thickness = 1.dp)
                        Spacer(modifier = Modifier.height(10.dp))

                        Text(
                            text = "FILE: ${progressState.fileName.uppercase()}",
                            color = textPrimary,
                            fontSize = 11.sp,
                            fontFamily = FontFamily.Monospace,
                            modifier = Modifier.padding(bottom = 6.dp)
                        )

                        if (progressState.state == TransferState.TRANSFERRING) {
                            val percent = if (progressState.totalBytes > 0) {
                                (progressState.bytesSent.toFloat() / progressState.totalBytes.toFloat())
                            } else 0f

                            val speedMb = progressState.speedBps / (1024.0 * 1024.0)

                            Spacer(modifier = Modifier.height(6.dp))

                            // Segmented LED Progress Bar
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(6.dp),
                                horizontalArrangement = Arrangement.spacedBy(3.dp)
                            ) {
                                val numSegments = 24
                                val activeCount = (percent * numSegments).toInt()
                                for (i in 0 until numSegments) {
                                    Box(
                                        modifier = Modifier
                                            .weight(1f)
                                            .fillMaxHeight()
                                            .background(
                                                color = if (i < activeCount) ACCENT_GREEN else borderColor,
                                                shape = RoundedCornerShape(1.dp)
                                            )
                                    )
                                }
                            }

                            Spacer(modifier = Modifier.height(10.dp))

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text(
                                    text = "${(percent * 100).toInt()}%",
                                    color = textPrimary,
                                    fontSize = 11.sp,
                                    fontFamily = FontFamily.Monospace
                                )
                                Text(
                                    text = String.format("%.2f MB/S", speedMb),
                                    color = textPrimary,
                                    fontSize = 11.sp,
                                    fontFamily = FontFamily.Monospace
                                )
                            }
                        }

                        if (progressState.state == TransferState.ERROR) {
                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                text = progressState.error.uppercase(),
                                color = Color.Red,
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(16.dp))

                // 5. Recent Drops History Card (NEW Live Drop History Log)
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .border(1.dp, borderColor, RoundedCornerShape(20.dp))
                        .background(cardColor, RoundedCornerShape(20.dp))
                        .padding(20.dp)
                ) {
                    Text(
                        text = "RECENT DIAGNOSTIC LOGS",
                        color = textSecondary,
                        fontSize = 9.sp,
                        fontFamily = FontFamily.SansSerif,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 1.5.sp,
                        modifier = Modifier.padding(bottom = 12.dp)
                    )

                    recentDrops.take(3).forEach { drop ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                modifier = Modifier.weight(1f)
                            ) {
                                Text(
                                    text = if (drop.success) "•" else "×",
                                    color = if (drop.success) ACCENT_GREEN else Color.Red,
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.padding(end = 8.dp)
                                )
                                Text(
                                    text = drop.fileName,
                                    color = textPrimary,
                                    fontSize = 11.sp,
                                    fontFamily = FontFamily.Monospace,
                                    maxLines = 1
                                )
                            }
                            Text(
                                text = "${drop.size} | ${drop.timestamp}",
                                color = textSecondary,
                                fontSize = 10.sp,
                                fontFamily = FontFamily.Monospace
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

            // Bottom Actions Panel
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 16.dp)
            ) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !hasNotificationPermission) {
                    Button(
                        onClick = { notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS) },
                        colors = ButtonDefaults.buttonColors(containerColor = cardColor),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .border(1.dp, borderColor, RoundedCornerShape(12.dp))
                            .padding(bottom = 12.dp)
                    ) {
                        Text(
                            text = "ENABLE DIAGNOSTIC ALERTS",
                            color = textPrimary,
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp
                        )
                    }
                }

                val canSend = progressState.state == TransferState.IDLE ||
                        progressState.state == TransferState.COMPLETED ||
                        progressState.state == TransferState.ERROR

                val isIpValid = IP_PATTERN.matcher(hostIp).matches()

                // Hero Accent Trigger: Green primary action button
                Button(
                    onClick = { filePickerLauncher.launch("*/*") },
                    enabled = canSend && isIpValid,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = ACCENT_GREEN,
                        disabledContainerColor = cardColor
                    ),
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(56.dp)
                        .border(
                            1.dp,
                            if (canSend && isIpValid) ACCENT_GREEN else borderColor,
                            RoundedCornerShape(14.dp)
                        )
                ) {
                    Text(
                        text = "QUICK DROP",
                        color = if (canSend && isIpValid) Color.Black else textSecondary,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.Bold,
                        fontSize = 15.sp,
                        letterSpacing = 2.sp
                    )
                }
            }
        }
    }
}
