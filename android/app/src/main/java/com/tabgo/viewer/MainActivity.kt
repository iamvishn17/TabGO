package com.tabgo.viewer

import android.app.Activity
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.cos
import kotlin.math.roundToInt

class MainActivity : Activity() {
    companion object { private const val PORT = 38177 }
    private val running = AtomicBoolean(true)
    private val connected = AtomicBoolean(false)
    @Volatile private var output: OutputStream? = null
    @Volatile private var serverSocket: ServerSocket? = null
    @Volatile private var activeClient: Socket? = null
    private lateinit var status: TextView
    private lateinit var surface: TabletSurface
    private var lastSentAt = 0L
    private var eventCount = 0
    private var rateWindowStart = System.currentTimeMillis()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = (View.SYSTEM_UI_FLAG_FULLSCREEN
            or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
            or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(31, 33, 36))
        }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(22), dp(12), dp(22), dp(12))
            setBackgroundColor(Color.rgb(37, 40, 44))
        }
        val brand = TextView(this).apply {
            text = "TABGO"
            textSize = 15f
            letterSpacing = 0.18f
            setTextColor(Color.rgb(236, 239, 243))
            typeface = android.graphics.Typeface.create("sans-serif", android.graphics.Typeface.BOLD)
        }
        status = TextView(this).apply {
            text = "●  NOT CONNECTED"
            textSize = 11f
            letterSpacing = 0.06f
            setTextColor(Color.rgb(150, 156, 165))
            gravity = Gravity.END or Gravity.CENTER_VERTICAL
        }
        header.addView(brand, LinearLayout.LayoutParams(0, dp(30), 1f))
        header.addView(status)
        root.addView(header, LinearLayout.LayoutParams(-1, dp(54)))
        surface = TabletSurface()
        root.addView(surface, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(root)
        surface.setOnTouchListener { _, event ->
            val tool = if (event.pointerCount > 0) event.getToolType(0) else MotionEvent.TOOL_TYPE_UNKNOWN
            if (tool == MotionEvent.TOOL_TYPE_STYLUS || tool == MotionEvent.TOOL_TYPE_ERASER) {
                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN -> sendPen(event, "down")
                    MotionEvent.ACTION_MOVE -> sendPen(event, "move")
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> sendPen(event, "up")
                }
                true
            } else false
        }
        surface.setOnGenericMotionListener { _, event ->
            val tool = if (event.pointerCount > 0) event.getToolType(0) else MotionEvent.TOOL_TYPE_UNKNOWN
            if (tool == MotionEvent.TOOL_TYPE_STYLUS || tool == MotionEvent.TOOL_TYPE_ERASER) {
                when (event.actionMasked) {
                    MotionEvent.ACTION_HOVER_ENTER, MotionEvent.ACTION_HOVER_MOVE -> sendPen(event, "hover")
                    MotionEvent.ACTION_HOVER_EXIT -> sendPen(event, "hover_exit")
                    MotionEvent.ACTION_MOVE -> sendPen(event, "move")
                }
                true
            } else false
        }
        startUsbServer()
    }

    private fun startUsbServer() {
        thread(name = "TabGO-USB-server", isDaemon = true) {
            try {
                ServerSocket(PORT).use { server ->
                    serverSocket = server
                    while (running.get()) {
                        val client = try { server.accept() } catch (_: Exception) { break }
                        try {
                            activeClient = client
                            output = BufferedOutputStream(client.getOutputStream())
                            client.soTimeout = 1500
                            val input = client.getInputStream()
                            connected.set(true)
                            runOnUiThread { updateConnection(true) }
                            while (running.get() && !client.isClosed) {
                                try {
                                    if (input.read() < 0) break
                                } catch (_: java.net.SocketTimeoutException) {
                                    // ADB keepalive is expected; timeout lets the activity stop cleanly.
                                }
                            }
                        } catch (e: Exception) {
                            Log.e("TabGO", "USB client session failed", e)
                        } finally {
                            connected.set(false)
                            output = null
                            activeClient = null
                            try { client.close() } catch (_: Exception) {}
                            runOnUiThread { updateConnection(false) }
                        }
                    }
                    serverSocket = null
                }
            } catch (_: Exception) {
                runOnUiThread { status.text = "●  USB SERVICE ERROR" }
            }
        }
    }

    private fun updateConnection(value: Boolean) {
        status.text = if (value) "●  CONNECTED" else "●  NOT CONNECTED"
        status.setTextColor(if (value) Color.rgb(87, 214, 154) else Color.rgb(150, 156, 165))
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun sendPen(event: MotionEvent, action: String) {
        if (event.pointerCount == 0) return
        val index = 0
        val tool = event.getToolType(index)
        if (tool != MotionEvent.TOOL_TYPE_STYLUS && tool != MotionEvent.TOOL_TYPE_ERASER) return
        val width = max(1, surface.width)
        val height = max(1, surface.height)
        val nx = (event.getX(index) / width).coerceIn(0f, 1f)
        val ny = (event.getY(index) / height).coerceIn(0f, 1f)
        val pressure = event.getPressure(index).coerceIn(0f, 1f)
        val tilt = event.getAxisValue(MotionEvent.AXIS_TILT, index)
        val orientation = event.getAxisValue(MotionEvent.AXIS_ORIENTATION, index)
        val tiltX = (sin(orientation) * tilt * 90f).roundToInt().coerceIn(-90, 90)
        val tiltY = (cos(orientation) * tilt * 90f).roundToInt().coerceIn(-90, 90)
        eventCount++
        val now = System.currentTimeMillis()
        if (now - rateWindowStart >= 1000) { eventCount = 0; rateWindowStart = now }
        val packet = JSONObject().apply {
            put("type", "pen")
            put("action", action)
            put("x", nx.toDouble())
            put("y", ny.toDouble())
            put("pressure", pressure.toDouble())
            put("contact", action == "down" || (action == "move" && pressure > 0f))
            put("tiltX", tiltX)
            put("tiltY", tiltY)
            put("buttons", event.buttonState)
            put("tool", if (tool == MotionEvent.TOOL_TYPE_ERASER) "eraser" else "stylus")
            put("eventTime", event.eventTime)
            put("rate", eventCount)
        }.toString() + "\n"
        try {
            synchronized(this) {
                output?.write(packet.toByteArray(Charsets.UTF_8))
                output?.flush()
            }
        } catch (e: Exception) {
            Log.e("TabGO", "Failed to send pen event; closing stale USB session", e)
            connected.set(false)
            output = null
            try { activeClient?.close() } catch (_: Exception) {}
            runOnUiThread { updateConnection(false) }
        }
        surface.updatePen(nx, ny, action != "up" && action != "hover_exit", action == "down" || (action == "move" && pressure > 0f))
    }

    override fun onDestroy() {
        running.set(false)
        try { output?.close() } catch (_: Exception) {}
        try { activeClient?.close() } catch (_: Exception) {}
        try { serverSocket?.close() } catch (_: Exception) {}
        super.onDestroy()
    }

    private inner class TabletSurface : View(this@MainActivity) {
        private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(61, 65, 71); strokeWidth = dp(1).toFloat() }
        private val penPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(139, 156, 255); style = Paint.Style.STROKE; strokeWidth = dp(2).toFloat() }
        private val touchPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(87, 214, 154); style = Paint.Style.STROKE; strokeWidth = dp(2).toFloat() }
        private var px = -1f
        private var py = -1f
        private var visible = false
        private var touching = false

        fun updatePen(x: Float, y: Float, show: Boolean, contact: Boolean) {
            px = x; py = y; visible = show; touching = contact; postInvalidateOnAnimation()
        }
        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            canvas.drawColor(Color.rgb(31, 33, 36))
            val spacing = dp(22).toFloat()
            var x = dp(12).toFloat()
            while (x < width) {
                var y = dp(12).toFloat()
                while (y < height) {
                    canvas.drawCircle(x, y, dp(1).toFloat(), dotPaint)
                    y += spacing
                }
                x += spacing
            }
            if (visible) {
                val cx = px * width
                val cy = py * height
                canvas.drawCircle(cx, cy, dp(8).toFloat(), if (touching) touchPaint else penPaint)
                canvas.drawLine(cx - dp(15), cy, cx + dp(15), cy, if (touching) touchPaint else penPaint)
                canvas.drawLine(cx, cy - dp(15), cx, cy + dp(15), if (touching) touchPaint else penPaint)
            }
        }
    }
}
