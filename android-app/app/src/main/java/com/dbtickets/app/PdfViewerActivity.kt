package com.dbtickets.app

import android.graphics.Bitmap
import android.graphics.pdf.PdfRenderer
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import java.io.File

class PdfViewerActivity : AppCompatActivity() {

    private var renderer: PdfRenderer? = null
    private var fileDescriptor: ParcelFileDescriptor? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val pdfPath = intent.getStringExtra("pdf_path") ?: run {
            Toast.makeText(this, "PDF-Pfad nicht gefunden", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        val file = File(pdfPath)
        if (!file.exists()) {
            Toast.makeText(this, "PDF-Datei nicht gefunden", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        val topBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setBackgroundColor(0xFF141414.toInt())
            setPadding(16, 12, 16, 12)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        val backBtn = android.widget.TextView(this).apply {
            text = "\u276E ${getString(R.string.zurueck)}"
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 16f
            setOnClickListener { finish() }
            setPadding(8, 8, 16, 8)
        }
        topBar.addView(backBtn)

        val title = android.widget.TextView(this).apply {
            text = "PDF"
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 17f
            gravity = android.view.Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        topBar.addView(title)

        val scrollView = ScrollView(this)
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, 0, 0)
        }
        scrollView.addView(container)

        val rootLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xFF0D0D0D.toInt())
        }
        rootLayout.addView(topBar)
        rootLayout.addView(scrollView, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.MATCH_PARENT
        ))
        setContentView(rootLayout)

        try {
            fileDescriptor = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
            renderer = PdfRenderer(fileDescriptor!!)

            for (i in 0 until renderer!!.pageCount) {
                val page = renderer!!.openPage(i)
                val scale = 2
                val bitmap = Bitmap.createBitmap(
                    page.width * scale,
                    page.height * scale,
                    Bitmap.Config.ARGB_8888
                )
                bitmap.eraseColor(0xFFFFFFFF.toInt())
                page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                page.close()

                val imageView = ImageView(this).apply {
                    setImageBitmap(bitmap)
                    adjustViewBounds = true
                    scaleType = ImageView.ScaleType.FIT_CENTER
                    layoutParams = LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT
                    ).apply {
                        setMargins(8, 8, 8, 8)
                    }
                }
                container.addView(imageView)
            }
        } catch (e: Exception) {
            Toast.makeText(this, "PDF konnte nicht geladen werden", Toast.LENGTH_SHORT).show()
            finish()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        renderer?.close()
        fileDescriptor?.close()
    }
}
