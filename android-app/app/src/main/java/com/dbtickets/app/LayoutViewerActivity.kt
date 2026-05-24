package com.dbtickets.app

import android.os.Bundle
import android.view.LayoutInflater
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class LayoutViewerActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_layout_viewer)

        val layoutName = intent.getStringExtra("layout_name") ?: "unknown"
        val layoutResId = intent.getIntExtra("layout_res_id", 0)

        findViewById<TextView>(R.id.tvTitle).text = layoutName.replace("_", " ")
        findViewById<ImageButton>(R.id.btnBack).setOnClickListener { finish() }

        val container = findViewById<FrameLayout>(R.id.layoutContainer)

        if (layoutResId != 0) {
            try {
                val inflated = LayoutInflater.from(this).inflate(layoutResId, container, false)
                container.addView(inflated)
            } catch (e: Exception) {
                Toast.makeText(this, "Fehler beim Laden: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }
}
