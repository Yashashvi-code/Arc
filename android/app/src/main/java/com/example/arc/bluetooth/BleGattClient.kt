package com.example.arc.bluetooth

import android.annotation.SuppressLint
import android.bluetooth.*
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import android.util.Log
import java.util.*
import kotlin.collections.ArrayDeque

@Suppress("DEPRECATION")
@SuppressLint("MissingPermission")
class BleGattClient(
    private val context: Context,
    private val listener: BleListener
) {
    interface BleListener {
        fun onConnectionStateChange(connected: Boolean)
        fun onClipboardReceived(text: String)
        fun onPcIpReceived(ip: String)
        fun onError(message: String)
    }

    companion object {
        private const val TAG = "ArcBleGattClient"
        
        val SERVICE_UUID: UUID = UUID.fromString("4564ea7d-1c3c-44ef-a28a-7e61405e3201")
        val COORDINATES_CHAR_UUID: UUID = UUID.fromString("4564ea7d-1c3c-44ef-a28a-7e61405e3202")
        val CLIPBOARD_CHAR_UUID: UUID = UUID.fromString("4564ea7d-1c3c-44ef-a28a-7e61405e3203")
        val PC_IP_CHAR_UUID: UUID = UUID.fromString("4564ea7d-1c3c-44ef-a28a-7e61405e3204")
        
        // Client Characteristic Configuration Descriptor (CCCD) UUID
        val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }

    private val bluetoothManager: BluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val bluetoothAdapter: BluetoothAdapter? = bluetoothManager.adapter
    private var bluetoothGatt: BluetoothGatt? = null
    private var isScanning = false
    private var isConnected = false

    private val handler = Handler(Looper.getMainLooper())

    // Serial GATT operation queue to prevent stack deadlocks
    private val operationQueue = ArrayDeque<BleOperation>()
    private var isOperationPending = false

    sealed class BleOperation {
        data class WriteChar(val characteristic: BluetoothGattCharacteristic, val data: ByteArray) : BleOperation()
        data class WriteDesc(val descriptor: BluetoothGattDescriptor, val data: ByteArray) : BleOperation()
    }

    private fun enqueue(op: BleOperation) {
        synchronized(operationQueue) {
            operationQueue.addLast(op)
            runNextOperation()
        }
    }

    private fun completeOperation() {
        synchronized(operationQueue) {
            isOperationPending = false
            runNextOperation()
        }
    }

    private fun runNextOperation() {
        if (isOperationPending || operationQueue.isEmpty() || bluetoothGatt == null) return
        val op = operationQueue.removeFirst()
        isOperationPending = true

        handler.post {
            val gatt = bluetoothGatt ?: return@post
            val success = when (op) {
                is BleOperation.WriteChar -> {
                    op.characteristic.value = op.data
                    gatt.writeCharacteristic(op.characteristic)
                }
                is BleOperation.WriteDesc -> {
                    op.descriptor.value = op.data
                    gatt.writeDescriptor(op.descriptor)
                }
            }
            if (!success) {
                Log.e(TAG, "GATT operation execution failed immediately: $op")
                completeOperation()
            }
        }
    }

    // Scan Callback
    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: android.bluetooth.le.ScanResult?) {
            result?.device?.let { device ->
                Log.i(TAG, "Found device: ${device.name ?: "Unknown"} (${device.address})")
                stopScan()
                connectToDevice(device)
            }
        }

        override fun onScanFailed(errorCode: Int) {
            Log.e(TAG, "Scan failed with error code: $errorCode")
            listener.onError("Scan failed: code $errorCode")
        }
    }

    // GATT Callback
    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt?, status: Int, newState: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                Log.e(TAG, "GATT Error status: $status")
                disconnect()
                return
            }

            if (newState == BluetoothProfile.STATE_CONNECTED) {
                Log.i(TAG, "Connected to GATT Server. Starting service discovery...")
                isConnected = true
                // Add a small delay for stable service discovery on older/Samsung platforms
                handler.postDelayed({
                    bluetoothGatt?.discoverServices()
                }, 600)
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                Log.i(TAG, "Disconnected from GATT Server.")
                disconnect()
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt?, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.i(TAG, "Services discovered. Negotiating MTU...")
                // Request MTU up to 512 bytes for faster clipboard packets
                gatt?.requestMtu(512)
            } else {
                Log.e(TAG, "Service discovery failed: $status")
                listener.onError("Service discovery failed.")
            }
        }

        override fun onMtuChanged(gatt: BluetoothGatt?, mtu: Int, status: Int) {
            Log.i(TAG, "MTU changed to $mtu (status: $status). Configuring notifications...")
            setupClipboardNotifications()
        }

        override fun onCharacteristicWrite(gatt: BluetoothGatt?, characteristic: BluetoothGattCharacteristic?, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.i(TAG, "Characteristic write successful: ${characteristic?.uuid}")
            } else {
                Log.e(TAG, "Characteristic write failed: status $status")
            }
            completeOperation()
        }

        override fun onDescriptorWrite(gatt: BluetoothGatt?, descriptor: BluetoothGattDescriptor?, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.i(TAG, "Descriptor write successful: ${descriptor?.uuid}")
            } else {
                Log.e(TAG, "Descriptor write failed: status $status")
            }
            completeOperation()
        }

        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(gatt: BluetoothGatt?, characteristic: BluetoothGattCharacteristic?) {
            characteristic?.let {
                if (it.uuid == CLIPBOARD_CHAR_UUID) {
                    val text = it.value?.toString(Charsets.UTF_8) ?: ""
                    Log.i(TAG, "Clipboard notification received: ${text.take(30)}...")
                    listener.onClipboardReceived(text)
                } else if (it.uuid == PC_IP_CHAR_UUID) {
                    val ip = it.value?.toString(Charsets.UTF_8) ?: ""
                    Log.i(TAG, "PC IP received via BLE: $ip")
                    listener.onPcIpReceived(ip)
                }
            }
        }
    }

    fun startScan() {
        val adapter = bluetoothAdapter
        if (adapter == null || !adapter.isEnabled) {
            listener.onError("Bluetooth is disabled.")
            return
        }

        if (isScanning) return
        isScanning = true

        val filter = ScanFilter.Builder()
            .setServiceUuid(ParcelUuid(SERVICE_UUID))
            .build()

        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_BALANCED)
            .build()

        Log.i(TAG, "Scanning for GATT Server: $SERVICE_UUID...")
        adapter.bluetoothLeScanner?.startScan(listOf(filter), settings, scanCallback)
        
        // Timeout scan — auto retry instead of giving up
        handler.postDelayed({
            if (isScanning) {
                stopScan()
                Log.i(TAG, "Scan timed out. Auto-retrying in 3s...")
                handler.postDelayed({ startScan() }, 3000)
            }
        }, 60000)
    }

    fun stopScan() {
        if (!isScanning) return
        isScanning = false
        bluetoothAdapter?.bluetoothLeScanner?.stopScan(scanCallback)
        Log.i(TAG, "Scanning stopped.")
    }

    private fun connectToDevice(device: BluetoothDevice) {
        Log.i(TAG, "Connecting to device: ${device.address}")
        bluetoothGatt = device.connectGatt(context, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
    }

    private fun setupClipboardNotifications() {
        val gatt = bluetoothGatt ?: return
        val service = gatt.getService(SERVICE_UUID) ?: return
        val char = service.getCharacteristic(CLIPBOARD_CHAR_UUID) ?: return

        // 1. Enable local notification routing in Android stack
        gatt.setCharacteristicNotification(char, true)

        // 2. Write Notification Descriptor to remote GATT Server (CCCD)
        val desc = char.getDescriptor(CCCD_UUID)
        if (desc != null) {
            enqueue(BleOperation.WriteDesc(desc, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE))
        }

        // 3. Subscribe to PC IP notifications
        setupPcIpNotifications()
        // 4. Services ready — notify listener and auto-write coordinates
        listener.onConnectionStateChange(true)
    }

    private fun setupPcIpNotifications() {
        val gatt = bluetoothGatt ?: return
        val service = gatt.getService(SERVICE_UUID) ?: return
        val char = service.getCharacteristic(PC_IP_CHAR_UUID) ?: return
        gatt.setCharacteristicNotification(char, true)
        val desc = char.getDescriptor(CCCD_UUID)
        if (desc != null) {
            enqueue(BleOperation.WriteDesc(desc, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE))
        }
    }

    fun writeCoordinates(ip: String, port: Int) {
        val gatt = bluetoothGatt ?: return
        val service = gatt.getService(SERVICE_UUID) ?: return
        val char = service.getCharacteristic(COORDINATES_CHAR_UUID) ?: return

        val data = "$ip:$port".toByteArray(Charsets.UTF_8)
        enqueue(BleOperation.WriteChar(char, data))
    }

    fun writeClipboard(text: String) {
        val gatt = bluetoothGatt ?: return
        val service = gatt.getService(SERVICE_UUID) ?: return
        val char = service.getCharacteristic(CLIPBOARD_CHAR_UUID) ?: return

        val data = text.toByteArray(Charsets.UTF_8)
        enqueue(BleOperation.WriteChar(char, data))
    }

    fun disconnect() {
        stopScan()
        isConnected = false
        synchronized(operationQueue) {
            operationQueue.clear()
            isOperationPending = false
        }
        bluetoothGatt?.close()
        bluetoothGatt = null
        listener.onConnectionStateChange(false)
        Log.i(TAG, "Gatt resources cleared.")
    }
}
