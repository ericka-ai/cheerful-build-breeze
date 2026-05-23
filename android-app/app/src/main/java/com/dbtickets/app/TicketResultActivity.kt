package com.dbtickets.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import com.dbtickets.app.databinding.ActivityTicketResultBinding

class TicketResultActivity : AppCompatActivity() {

    private lateinit var binding: ActivityTicketResultBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityTicketResultBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val ticketTypeMap = mapOf(
            "grp_consecutive" to "German Rail Pass (Konsekutiv)",
            "grp_flexi" to "German Rail Pass (Flexi)",
            "eurail_global" to "Eurail Global Pass",
            "deutschlandticket" to "Deutschlandticket",
            "sparpreis" to "DB Sparpreis"
        )

        binding.tvAuftragsnummer.text = intent.getStringExtra("auftragsnummer") ?: "N/A"
        binding.tvTicketId.text = intent.getStringExtra("ticket_id") ?: "N/A"
        binding.tvResultTicketType.text = ticketTypeMap[intent.getStringExtra("ticket_type")] ?: ""
        binding.tvResultName.text = intent.getStringExtra("name") ?: ""
        binding.tvResultGeburtsdatum.text = intent.getStringExtra("geburtsdatum") ?: ""
        binding.tvResultGueltigkeit.text = intent.getStringExtra("gueltigkeit") ?: ""
        binding.tvResultPreis.text = intent.getStringExtra("preis") ?: ""

        val pdfUrl = intent.getStringExtra("pdf_url") ?: ""

        binding.btnDownloadPdf.setOnClickListener {
            if (pdfUrl.isNotEmpty()) {
                val browserIntent = Intent(Intent.ACTION_VIEW, Uri.parse(pdfUrl))
                startActivity(browserIntent)
            }
        }

        if (pdfUrl.isEmpty()) {
            binding.btnDownloadPdf.visibility = View.GONE
        }

        binding.btnNewTicket.setOnClickListener {
            val intent = Intent(this, MainActivity::class.java)
            intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
            startActivity(intent)
            finish()
        }
    }
}
