package com.example.arc.networking

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Log
import org.json.JSONObject
import java.io.InputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.UUID

object TcpClient {
    private const val TAG = "ArcTcpClient"
    private val MAGIC_BYTES = "ARC\u0001".toByteArray(Charsets.US_ASCII)
    private const val HEADER_SIZE = 81

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

    private const val TYPE_METADATA: Byte = 0x01
    private const val TYPE_DATA: Byte = 0x02

    interface ProgressListener {
        fun onProgress(bytesSent: Long, totalBytes: Long, speedBps: Double)
        fun onError(message: String)
        fun onComplete()
    }

    private fun UUID.toBytes(): ByteArray {
        val bb = ByteBuffer.wrap(ByteArray(16))
        bb.putLong(mostSignificantBits)
        bb.putLong(leastSignificantBits)
        return bb.array()
    }

    private fun sha256(data: ByteArray): ByteArray {
        val digest = MessageDigest.getInstance("SHA-256")
        return digest.digest(data)
    }

    private fun getFileMetadata(contentResolver: ContentResolver, fileUri: Uri): Pair<String, Long> {
        var name = "unknown"
        var size = 0L
        contentResolver.query(fileUri, null, null, null, null)?.use { cursor ->
            val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
            if (cursor.moveToFirst()) {
                if (nameIndex != -1) name = cursor.getString(nameIndex)
                if (sizeIndex != -1) size = cursor.getLong(sizeIndex)
            }
        }
        return Pair(name, size)
    }

    fun calculateFileSha256(contentResolver: ContentResolver, fileUri: Uri): String {
        val digest = MessageDigest.getInstance("SHA-256")
        contentResolver.openInputStream(fileUri)?.use { input ->
            val buffer = ByteArray(8192)
            var bytesRead = input.read(buffer)
            while (bytesRead != -1) {
                digest.update(buffer, 0, bytesRead)
                bytesRead = input.read(buffer)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun makeHeader(type: Byte, sessionId: String, chunkIdx: Long, payload: ByteArray, authToken: String): ByteArray {
        val sessionBytes = UUID.fromString(sessionId).toBytes()
        val payloadLen = payload.size
        val checksum = sha256(payload)
        val tokenBytes = hexStringToByteArray(authToken)

        val header = ByteBuffer.allocate(HEADER_SIZE)
        header.put(MAGIC_BYTES)
        header.put(type)
        header.put(tokenBytes)
        header.put(sessionBytes)
        header.putLong(chunkIdx)
        header.putInt(payloadLen)
        header.put(checksum)
        return header.array()
    }

    private fun InputStream.skipFully(n: Long) {
        var remaining = n
        while (remaining > 0) {
            val skipped = skip(remaining)
            if (skipped <= 0) {
                break
            }
            remaining -= skipped
        }
    }

    fun sendFile(
        contentResolver: ContentResolver,
        fileUri: Uri,
        host: String,
        port: Int,
        authToken: String = "",
        sessionId: String = UUID.randomUUID().toString(),
        chunkSize: Int = 1024 * 1024,
        listener: ProgressListener
    ) {
        val socket = Socket()
        var input: InputStream? = null
        try {
            val (fileName, fileSize) = getFileMetadata(contentResolver, fileUri)
            Log.i(TAG, "Starting transfer for $fileName ($fileSize bytes) to $host:$port")

            // Connect
            socket.connect(InetSocketAddress(host, port), 5000)
            val outputStream = socket.getOutputStream()
            val inputStream = socket.getInputStream()

            // 1. Send Metadata (empty file_hash signals incremental hashing mode)
            val metadataJson = JSONObject().apply {
                put("file_name", fileName)
                put("total_size", fileSize)
                put("file_hash", "")
            }
            val metadataBytes = metadataJson.toString().toByteArray(Charsets.UTF_8)
            val metadataHeader = makeHeader(TYPE_METADATA, sessionId, 0L, metadataBytes, authToken)

            outputStream.write(metadataHeader)
            outputStream.write(metadataBytes)
            outputStream.flush()

            // Read resume offset (8 bytes, Big-Endian long)
            val offsetBytes = ByteArray(8)
            var bytesReadOffset = 0
            while (bytesReadOffset < 8) {
                val read = inputStream.read(offsetBytes, bytesReadOffset, 8 - bytesReadOffset)
                if (read == -1) {
                    throw Exception("Connection closed while reading handshake offset.")
                }
                bytesReadOffset += read
            }
            val offset = ByteBuffer.wrap(offsetBytes).long
            Log.i(TAG, "Server requested resume offset: $offset bytes")

            // Initialize message digest for incremental hashing
            val digest = MessageDigest.getInstance("SHA-256")
            if (offset > 0) {
                Log.i(TAG, "Resuming session: Seeding hash generator with first $offset bytes...")
                contentResolver.openInputStream(fileUri)?.use { seedInput ->
                    val seedBuffer = ByteArray(65536)
                    var seeded = 0L
                    while (seeded < offset) {
                        val toRead = minOf(65536L, offset - seeded).toInt()
                        val bytesRead = seedInput.read(seedBuffer, 0, toRead)
                        if (bytesRead == -1) break
                        digest.update(seedBuffer, 0, bytesRead)
                        seeded += bytesRead
                    }
                }
            }

            // 2. Stream chunks
            input = contentResolver.openInputStream(fileUri) ?: throw Exception("Failed to open file input stream.")
            if (offset > 0) {
                input.skipFully(offset)
            }

            var bytesSent = offset
            var chunkIdx = offset / chunkSize
            val buffer = ByteArray(chunkSize)

            var lastReportTime = System.currentTimeMillis()
            var lastReportBytes = bytesSent
            var speedBps = 0.0

            while (bytesSent < fileSize) {
                val bytesRead = input.read(buffer)
                if (bytesRead == -1) break

                val payload = if (bytesRead == chunkSize) buffer else buffer.copyOf(bytesRead)
                
                // Update hash digest
                digest.update(payload)
                
                val chunkHeader = makeHeader(TYPE_DATA, sessionId, chunkIdx, payload, authToken)

                outputStream.write(chunkHeader)
                outputStream.write(payload)
                outputStream.flush()

                bytesSent += bytesRead
                chunkIdx++

                // Calculate Speed
                val now = System.currentTimeMillis()
                val elapsed = now - lastReportTime
                if (elapsed >= 1000 || bytesSent == fileSize) {
                    val bytesDiff = bytesSent - lastReportBytes
                    val rawSpeedBps = (bytesDiff.toDouble() / (elapsed.toDouble() / 1000.0))
                    speedBps = if (lastReportBytes == offset) rawSpeedBps else (0.3 * rawSpeedBps + 0.7 * speedBps)
                    listener.onProgress(bytesSent, fileSize, speedBps)
                    lastReportTime = now
                    lastReportBytes = bytesSent
                }
            }

            // 3. Send final verification hash packet (0x06)
            val finalHash = digest.digest().joinToString("") { "%02x".format(it) }
            Log.i(TAG, "Sending final verification hash: $finalHash")
            val hashPayload = finalHash.toByteArray(Charsets.UTF_8)
            val hashHeader = makeHeader(0x06.toByte(), sessionId, 0L, hashPayload, authToken)
            
            outputStream.write(hashHeader)
            outputStream.write(hashPayload)
            outputStream.flush()

            Log.i(TAG, "Finished streaming data. Closing connection.")
            listener.onComplete()

        } catch (e: Exception) {
            Log.e(TAG, "Socket error: ${e.message}", e)
            listener.onError(e.message ?: "Unknown socket error")
        } finally {
            try {
                input?.close()
            } catch (e: Exception) { /* ignore */ }
            try {
                socket.close()
            } catch (e: Exception) { /* ignore */ }
        }
    }
}
