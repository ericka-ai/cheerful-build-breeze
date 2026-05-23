package com.dbtickets.app

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import com.dbtickets.app.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.cardGermanRailPass.setOnClickListener {
            openTicketForm("grp_consecutive")
        }

        binding.cardEurailGlobal.setOnClickListener {
            openTicketForm("eurail_global")
        }

        binding.cardDeutschlandticket.setOnClickListener {
            openTicketForm("deutschlandticket")
        }

        binding.cardSparpreis.setOnClickListener {
            openTicketForm("sparpreis")
        }

        binding.btnSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
    }

    private fun openTicketForm(ticketType: String) {
        val intent = Intent(this, TicketFormActivity::class.java)
        intent.putExtra("ticket_type", ticketType)
        startActivity(intent)
    }
}
