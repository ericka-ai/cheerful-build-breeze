package com.dbtickets.app

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.dbtickets.app.databinding.ActivityTicketResultBinding
import java.io.File

class TicketResultActivity : AppCompatActivity() {

    private lateinit var binding: ActivityTicketResultBinding
    private var ticket: Ticket? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityTicketResultBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val ticketStoreId = intent.getStringExtra("ticket_store_id") ?: ""
        ticket = TicketStore.getTicketById(this, ticketStoreId)

        if (ticket == null) {
            Toast.makeText(this, "Ticket nicht gefunden", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        val t = ticket!!

        binding.tvAuftragsnummer.text = t.auftragsnummer
        binding.tvTicketId.text = t.ticketId
        binding.tvResultTicketType.text = t.ticketTypeLabel
        binding.tvResultName.text = "${t.vorname} ${t.nachname}"
        binding.tvResultGeburtsdatum.text = t.geburtsdatum
        binding.tvResultGueltigkeit.text = "${t.gueltigVon} - ${t.gueltigBis}"
        binding.tvResultPreis.text = t.preis
        binding.tvResultKlasse.text = "${t.klasse}. Klasse"
        binding.tvResultPassagierTyp.text = if (t.passagierTyp == "ERWACHSENER") "Erwachsener" else "Jugendlicher"
        binding.tvResultCreatedAt.text = t.createdAt

        binding.btnDownloadPdf.setOnClickListener {
            openPdf()
        }

        binding.btnNewTicket.setOnClickListener {
            val intent = Intent(this, MainActivity::class.java)
            intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
            startActivity(intent)
            finish()
        }
    }

    override fun onResume() {
        super.onResume()
        val t = ticket ?: return
        val updatedTicket = TicketStore.getTicketById(this, t.id)
        if (updatedTicket != null && updatedTicket.pdfPath.isNotEmpty()) {
            binding.btnDownloadPdf.visibility = View.VISIBLE
            binding.tvPdfStatus.text = "PDF bereit"
            binding.tvPdfStatus.visibility = View.VISIBLE
        } else {
            binding.tvPdfStatus.text = "PDF wird vom Server geladen..."
            binding.tvPdfStatus.visibility = View.VISIBLE
        }
    }

    private fun openPdf() {
        val t = ticket ?: return
        val updatedTicket = TicketStore.getTicketById(this, t.id)
        val pdfPath = updatedTicket?.pdfPath ?: ""

        if (pdfPath.isEmpty()) {
            Toast.makeText(this, "PDF wird noch vom Server geladen. Bitte warten...", Toast.LENGTH_SHORT).show()
            return
        }

        val pdfFile = File(pdfPath)
        if (!pdfFile.exists()) {
            Toast.makeText(this, "PDF-Datei nicht gefunden", Toast.LENGTH_SHORT).show()
            return
        }

        val uri = FileProvider.getUriForFile(this, "${packageName}.fileprovider", pdfFile)
        val viewIntent = Intent(Intent.ACTION_VIEW)
        viewIntent.setDataAndType(uri, "application/pdf")
        viewIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        try {
            startActivity(viewIntent)
        } catch (e: Exception) {
            Toast.makeText(this, "Kein PDF-Viewer installiert", Toast.LENGTH_SHORT).show()
        }
    }
}
