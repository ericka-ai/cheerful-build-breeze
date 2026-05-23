package com.dbtickets.app

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.dbtickets.app.databinding.ActivitySettingsBinding

class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val prefs = getSharedPreferences("db_tickets", MODE_PRIVATE)
        val savedUrl = prefs.getString("server_url", "") ?: ""
        binding.etServerUrl.setText(savedUrl.ifEmpty { TicketStore.getDefaultServerUrl() })

        val isDarkMode = prefs.getBoolean("dark_mode", false)
        binding.switchDarkMode.isChecked = isDarkMode

        binding.btnBack.setOnClickListener { finish() }

        binding.btnSave.setOnClickListener {
            val serverUrl = binding.etServerUrl.text.toString().trim().trimEnd('/')
            val darkMode = binding.switchDarkMode.isChecked
            prefs.edit()
                .putString("server_url", serverUrl)
                .putBoolean("dark_mode", darkMode)
                .apply()
            Toast.makeText(this, getString(R.string.success_settings), Toast.LENGTH_SHORT).show()
            finish()
        }
    }
}
