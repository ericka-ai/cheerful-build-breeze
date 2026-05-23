package com.dbtickets.app

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.dbtickets.app.databinding.ActivityTicketResultBinding
import com.google.zxing.BarcodeFormat
import com.google.zxing.aztec.AztecWriter
import com.google.zxing.common.BitMatrix
import java.io.File
import java.text.SimpleDateFormat
import java.util.*

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
        displayTicket(t)

        binding.btnBackTicket.setOnClickListener { finish() }

        binding.btnNewTicket.setOnClickListener {
            val intent = Intent(this, MainActivity::class.java)
            intent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
            startActivity(intent)
            finish()
        }

        binding.btnDownloadPdf.setOnClickListener {
            openPdf()
        }
    }

    private fun displayTicket(t: Ticket) {
        generateBarcode(t)

        binding.tvResultName.text = "${t.vorname} ${t.nachname}"
        binding.tvCiv.text = "CIV ${t.ticketId}"
        binding.tvResultTicketType.text = t.ticketTypeLabel
        binding.tvResultKlasse.text = "${t.klasse}. Klasse"

        val passTypLabel = if (t.passagierTyp == "ERWACHSENER") {
            "1 Erwachsener"
        } else {
            "1 Jugendlicher (12-27 J.)"
        }
        binding.tvResultPassagierTyp.text = passTypLabel

        binding.tvResultGeburtsdatum.text = "Geb. ${t.geburtsdatum}"

        val von = t.gueltigVon
        val bis = t.gueltigBis
        binding.tvResultGueltigkeit.text = "Von: $von, 00:00 Uhr\nBis: $bis, 03:00 Uhr"

        binding.tvResultCreatedAt.text = "Gebucht am: ${t.createdAt} Uhr"
        binding.tvAuftragsnummer.text = "Auftrags-Nr: ${t.auftragsnummer}"
        binding.tvResultPreis.text = "Gesamtpreis: ${t.preis}"

        val ticketCode = generateTicketCode()
        binding.tvTicketCode.text = "Ticketcode: $ticketCode"

        binding.tvKonditionen.text = buildString {
            append("Freie Zugwahl\n\n")
            append("Nur g\u00fcltig mit amtlichen Lichtbildausweis. ")
            append("Dieser ist bei der Kontrolle vorzuzeigen.\n")
            append("Bei Fahrkarten mit BahnCard-Rabatt zeigen Sie bitte ")
            append("zus\u00e4tzlich Ihre g\u00fcltige BahnCard vor.\n")
            append("Es gelten die nationalen und internationalen ")
            append("Bef\u00f6rderungsbedingungen der DB AG. Innerhalb von ")
            append("Verkehrsverb\u00fcnden und Tarifgemeinschaften gelten ")
            append("deren Bestimmungen. Alle Bedingungen finden Sie ")
            append("unter www.bahn.de/agb und www.diebefoerderer.de.\n")
            append("Eine Fahrkarte entspricht grunds\u00e4tzlich einem ")
            append("Bef\u00f6rderungsvertrag, mehrere Fahrkarten mehreren ")
            append("Bef\u00f6rderungsvertr\u00e4gen.")
        }

        binding.tvAuftragBig.text = t.auftragsnummer
        binding.tvNameFooter.text = "${t.vorname} ${t.nachname}"

        try {
            val parts = von.split(".")
            if (parts.size >= 2) {
                binding.tvDateFooter.text = "${parts[0]}  ${parts[1]}"
            }
        } catch (e: Exception) {
            binding.tvDateFooter.text = von
        }
    }

    private fun generateBarcode(t: Ticket) {
        try {
            val barcodeData = buildString {
                append("OTI:")
                append(t.auftragsnummer)
                append(";TI:")
                append(t.ticketId)
                append(";NA:")
                append(t.nachname)
                append("/")
                append(t.vorname)
                append(";GD:")
                append(t.geburtsdatum)
                append(";KL:")
                append(t.klasse)
                append(";PR:")
                append(t.product)
                append(";VN:")
                append(t.gueltigVon)
                append(";BS:")
                append(t.gueltigBis)
                append(";PT:")
                append(t.preis)
            }

            val writer = AztecWriter()
            val bitMatrix: BitMatrix = writer.encode(barcodeData, BarcodeFormat.AZTEC, 600, 600)
            val width = bitMatrix.width
            val height = bitMatrix.height
            val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.RGB_565)

            for (x in 0 until width) {
                for (y in 0 until height) {
                    bitmap.setPixel(x, y, if (bitMatrix.get(x, y)) Color.BLACK else Color.WHITE)
                }
            }

            binding.ivBarcode.setImageBitmap(bitmap)
        } catch (e: Exception) {
            binding.ivBarcode.visibility = View.GONE
        }
    }

    private fun generateTicketCode(): String {
        val chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        val random = Random()
        return (1..8).map { chars[random.nextInt(chars.length)] }.joinToString("")
    }

    override fun onResume() {
        super.onResume()
        val t = ticket ?: return
        val updatedTicket = TicketStore.getTicketById(this, t.id)
        if (updatedTicket != null && updatedTicket.pdfPath.isNotEmpty()) {
            binding.tvPdfStatus.visibility = View.GONE
        }
    }

    private fun openPdf() {
        val t = ticket ?: return
        val updatedTicket = TicketStore.getTicketById(this, t.id)
        val pdfPath = updatedTicket?.pdfPath ?: ""

        if (pdfPath.isEmpty()) {
            Toast.makeText(this, "PDF wird noch vom Server geladen...", Toast.LENGTH_SHORT).show()
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
