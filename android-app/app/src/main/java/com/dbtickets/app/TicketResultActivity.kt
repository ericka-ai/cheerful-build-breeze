package com.dbtickets.app

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
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
    private val handler = Handler(Looper.getMainLooper())
    private var barcodeCheckRunnable: Runnable? = null

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
        loadBarcode(t)

        binding.tvResultName.text = "${t.vorname} ${t.nachname}"
        binding.tvCiv.text = "CIV 1080"

        val typeLabel = t.ticketTypeLabel
        binding.tvResultTicketType.text = typeLabel
        binding.tvResultKlasse.text = "${t.klasse}. Klasse"

        val passTypLabel = when (t.passagierTyp) {
            "ERWACHSENER" -> "1 Erwachsener"
            "JUGENDLICHER" -> "1 Jugendlicher (12-27 J.)"
            else -> "1 ${t.passagierTyp}"
        }
        binding.tvResultPassagierTyp.text = passTypLabel

        val von = t.gueltigVon
        val bis = t.gueltigBis
        binding.tvResultGueltigkeit.text = "Von: $von, 00:00 Uhr\nBis: $bis, 03:00 Uhr"

        if (t.product == "db_sparpreis") {
            binding.sectionVerbindung.visibility = View.VISIBLE
            binding.tvVerbindung.text = "Verbindung wird angezeigt"
        }

        binding.tvResultCreatedAt.text = "Gebucht am: ${t.createdAt} Uhr"
        binding.tvAuftragsnummer.text = "Auftrags-Nr: ${t.auftragsnummer}"
        binding.tvResultPreis.text = "Gesamtpreis: ${t.preis}"

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
            append("Bef\u00f6rderungsvertr\u00e4gen. Vertraglicher Bef\u00f6rderer ")
            append("k\u00f6nnen dabei ein oder mehrere Verkehrsunternehmen ")
            append("sein. Es handelt sich bei dieser Fahrkarte um eine ")
            append("Durchgangsfahrkarte gem\u00e4\u00df Europ\u00e4ischer ")
            append("Fahrgastrechte-Verordnung f\u00fcr den Eisenbahnverkehr.")
        }

        try {
            val sdf = SimpleDateFormat("dd.MM.yyyy", Locale.GERMANY)
            val startDate = sdf.parse(von)
            if (startDate != null) {
                val cal = Calendar.getInstance()
                cal.time = startDate
                cal.add(Calendar.DAY_OF_MONTH, -1)
                val stornoDate = sdf.format(cal.time)
                binding.tvStornierung.text = "Stornierung bis $stornoDate kostenfrei"
            }
        } catch (e: Exception) {
            binding.tvStornierung.text = ""
        }

        val ticketCode = generateTicketCode()
        binding.tvTicketCode.text = "Ticketcode: $ticketCode"

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

    private fun loadBarcode(t: Ticket) {
        val updatedTicket = TicketStore.getTicketById(this, t.id)
        val barcodePath = updatedTicket?.barcodePath ?: ""

        if (barcodePath.isNotEmpty()) {
            val file = File(barcodePath)
            if (file.exists()) {
                val bitmap = BitmapFactory.decodeFile(barcodePath)
                if (bitmap != null) {
                    binding.ivBarcode.setImageBitmap(bitmap)
                    binding.tvBarcodeLoading.visibility = View.GONE
                    return
                }
            }
        }

        binding.tvBarcodeLoading.visibility = View.VISIBLE
        binding.tvBarcodeLoading.text = "Barcode wird geladen..."
        generateFallbackBarcode(t)
        startBarcodePolling(t)
    }

    private fun startBarcodePolling(t: Ticket) {
        barcodeCheckRunnable = object : Runnable {
            override fun run() {
                val updated = TicketStore.getTicketById(this@TicketResultActivity, t.id)
                val path = updated?.barcodePath ?: ""
                if (path.isNotEmpty() && File(path).exists()) {
                    val bitmap = BitmapFactory.decodeFile(path)
                    if (bitmap != null) {
                        binding.ivBarcode.setImageBitmap(bitmap)
                        binding.tvBarcodeLoading.visibility = View.GONE
                        return
                    }
                }
                handler.postDelayed(this, 2000)
            }
        }
        handler.postDelayed(barcodeCheckRunnable!!, 2000)
    }

    private fun generateFallbackBarcode(t: Ticket) {
        try {
            val barcodeData = buildString {
                append("#UT01;OTI:")
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
            val bitMatrix: BitMatrix = writer.encode(barcodeData, BarcodeFormat.AZTEC, 800, 800)
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
        loadBarcode(t)
    }

    override fun onPause() {
        super.onPause()
        barcodeCheckRunnable?.let { handler.removeCallbacks(it) }
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
