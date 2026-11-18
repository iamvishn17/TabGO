package com.tabgo.viewer

import android.app.Activity
import android.os.Bundle
import android.view.View
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var message: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.decorView.systemUiVisibility =
            (View.SYSTEM_UI_FLAG_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION)

        val root = FrameLayout(this)
        root.setBackgroundColor(0xFF080B12.toInt())
        message = TextView(this).apply {
            text = "TabGO\n\nWaiting for your PC…\nStart USB Mirror in TabGO Desktop."
            setTextColor(0xFFEAF0FA.toInt())
            textSize = 18f
            gravity = android.view.Gravity.CENTER
        }
        web = WebView(this).apply {
            setBackgroundColor(0xFF080B12.toInt())
            settings.javaScriptEnabled = false
            settings.domStorageEnabled = false
            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun onReceivedError(view: WebView?, errorCode: Int, description: String?, failingUrl: String?) {
                    message.visibility = View.VISIBLE
                    message.text = "TabGO\n\nPC stream not available.\nStart the Windows app, then reopen TabGO."
                }
                override fun onPageFinished(view: WebView?, url: String?) {
                    message.visibility = View.GONE
                }
            }
        }
        root.addView(web, FrameLayout.LayoutParams(-1, -1))
        root.addView(message, FrameLayout.LayoutParams(-1, -1))
        setContentView(root)
        web.loadUrl("http://127.0.0.1:8765/")
    }

    override fun onResume() {
        super.onResume()
        if (::web.isInitialized) web.reload()
    }

    override fun onDestroy() {
        if (::web.isInitialized) web.destroy()
        super.onDestroy()
    }
}
