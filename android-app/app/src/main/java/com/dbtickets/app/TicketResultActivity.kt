package com.dbtickets.app

import android.app.AlertDialog
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
import okhttp3.*
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
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

        val isDarkMode = getSharedPreferences("db_tickets", MODE_PRIVATE)
            .getBoolean("dark_mode", false)
        applyTheme(isDarkMode)

        displayTicket(t)

        binding.btnBackTicket.setOnClickListener { finish() }

        binding.btnWeitereAktionen.setOnClickListener {
            showWeitereAktionen()
        }
    }

    private fun applyTheme(isDark: Boolean) {
        if (isDark) {
            binding.rootLayout.setBackgroundColor(Color.parseColor("#282828"))
            binding.scrollContent.setBackgroundColor(Color.parseColor("#282828"))
            setTextColors(Color.WHITE)
        }
    }

    private fun setTextColors(primary: Int) {
        binding.tvResultName.setTextColor(primary)
        binding.tvCiv.setTextColor(primary)
        binding.tvResultTicketType.setTextColor(primary)
        binding.tvResultKlasse.setTextColor(primary)
        binding.tvResultPassagierTyp.setTextColor(primary)
        binding.tvResultGueltigkeit.setTextColor(primary)
        binding.tvResultCreatedAt.setTextColor(primary)
        binding.tvAuftragsnummer.setTextColor(primary)
        binding.tvResultPreis.setTextColor(primary)
        binding.tvKonditionen.setTextColor(primary)
        binding.tvStornierung.setTextColor(primary)
        binding.tvTicketCode.setTextColor(primary)
    }

    private fun showWeitereAktionen() {
        val t = ticket ?: return
        val items = arrayOf(
            "Entsch\u00e4digung beantragen",
            "Rechnung \u00f6ffnen",
            "Feedback zur Reise",
            "Zur Stornierung",
            "Ticket l\u00f6schen"
        )

        val builder = AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog)
        builder.setItems(items) { dialog, which ->
            when (which) {
                0 -> Toast.makeText(this, "Entsch\u00e4digungsantrag wird vorbereitet...", Toast.LENGTH_SHORT).show()
                1 -> openPdf()
                2 -> Toast.makeText(this, "Vielen Dank f\u00fcr Ihr Feedback!", Toast.LENGTH_SHORT).show()
                3 -> showStornierungDialog(t)
                4 -> showDeleteDialog(t)
            }
            dialog.dismiss()
        }
        builder.setNegativeButton("Abbrechen") { dialog, _ -> dialog.dismiss() }
        builder.show()
    }

    private fun showStornierungDialog(t: Ticket) {
        val von = t.gueltigVon
        var stornoDate = von
        try {
            val sdf = SimpleDateFormat("dd.MM.yyyy", Locale.GERMANY)
            val startDate = sdf.parse(von)
            if (startDate != null) {
                val cal = Calendar.getInstance()
                cal.time = startDate
                cal.add(Calendar.DAY_OF_MONTH, -1)
                stornoDate = sdf.format(cal.time)
            }
        } catch (e: Exception) { }

        AlertDialog.Builder(this)
            .setTitle("Stornierung")
            .setMessage("Auftrags-Nr: ${t.auftragsnummer}\n\nKostenfreie Stornierung bis $stornoDate m\u00f6glich.\n\nM\u00f6chten Sie dieses Ticket stornieren?")
            .setPositiveButton("Stornieren") { dialog, _ ->
                Toast.makeText(this, "Stornierung wurde simuliert. Ticket-Nr: ${t.auftragsnummer}", Toast.LENGTH_LONG).show()
                dialog.dismiss()
            }
            .setNegativeButton("Abbrechen") { dialog, _ -> dialog.dismiss() }
            .show()
    }

    private fun showDeleteDialog(t: Ticket) {
        AlertDialog.Builder(this)
            .setTitle("Ticket l\u00f6schen")
            .setMessage("M\u00f6chtest du das Ticket ${t.auftragsnummer} wirklich l\u00f6schen?")
            .setPositiveButton("L\u00f6schen") { dialog, _ ->
                TicketStore.deleteTicket(this, t.id)
                Toast.makeText(this, "Ticket gel\u00f6scht", Toast.LENGTH_SHORT).show()
                dialog.dismiss()
                finish()
            }
            .setNegativeButton("Abbrechen") { dialog, _ -> dialog.dismiss() }
            .show()
    }

    private fun displayTicket(t: Ticket) {
        loadBarcode(t)

        binding.tvResultName.text = "${t.vorname} ${t.nachname}"
        binding.tvCiv.text = "CIV 1080"

        binding.tvResultTicketType.text = t.ticketTypeLabel
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

        val productName = t.ticketTypeLabel
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
            append("Fahrgastrechte-Verordnung f\u00fcr den Eisenbahnverkehr.\n\n")
            append("Produkt: $productName")
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

        loadWatermark(t)
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
        downloadBarcodeFromServer(t)
    }

    private fun downloadBarcodeFromServer(t: Ticket) {
        val serverUrl = TicketStore.getServerUrl(this)
        val client = ApiClient.client

        val formBody = FormBody.Builder()
            .add("nachname", t.nachname)
            .add("vorname", t.vorname)
            .add("geburtsdatum", t.geburtsdatum)
            .add("klasse", t.klasse)
            .add("passagier_typ", t.passagierTyp)
            .add("gueltig_von", t.gueltigVon)
            .add("gueltig_bis", t.gueltigBis)
            .add("product", t.product)
            .add("tage", "15")
            .add("ticket_id", t.ticketId)
            .add("order_number", t.auftragsnummer)
            .build()

        val request = Request.Builder()
            .url("$serverUrl/api/barcode")
            .post(formBody)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread {
                    binding.tvBarcodeLoading.text = "Barcode konnte nicht geladen werden"
                }
            }

            override fun onResponse(call: Call, response: Response) {
                if (response.isSuccessful) {
                    val imgBytes = response.body?.bytes()
                    if (imgBytes != null && imgBytes.isNotEmpty()) {
                        val dir = File(filesDir, "barcodes")
                        dir.mkdirs()
                        val imgFile = File(dir, "barcode_${t.ticketId}.png")
                        FileOutputStream(imgFile).use { it.write(imgBytes) }
                        TicketStore.updateTicketBarcodePath(this@TicketResultActivity, t.id, imgFile.absolutePath)

                        val bitmap = BitmapFactory.decodeFile(imgFile.absolutePath)
                        runOnUiThread {
                            if (bitmap != null) {
                                binding.ivBarcode.setImageBitmap(bitmap)
                                binding.tvBarcodeLoading.visibility = View.GONE
                            } else {
                                binding.tvBarcodeLoading.text = "Barcode konnte nicht geladen werden"
                            }
                        }
                        return
                    }
                }
                runOnUiThread {
                    binding.tvBarcodeLoading.text = "Barcode konnte nicht geladen werden"
                }
            }
        })
    }

    private fun loadWatermark(t: Ticket) {
        val updatedTicket = TicketStore.getTicketById(this, t.id)
        val wmPath = updatedTicket?.watermarkPath ?: ""

        if (wmPath.isNotEmpty()) {
            val file = File(wmPath)
            if (file.exists()) {
                val bitmap = BitmapFactory.decodeFile(wmPath)
                if (bitmap != null) {
                    binding.ivWatermark.setImageBitmap(bitmap)
                    return
                }
            }
        }

        startWatermarkPolling(t)
    }

    private fun startWatermarkPolling(t: Ticket) {
        val wmRunnable = object : Runnable {
            override fun run() {
                val updated = TicketStore.getTicketById(this@TicketResultActivity, t.id)
                val path = updated?.watermarkPath ?: ""
                if (path.isNotEmpty() && File(path).exists()) {
                    val bitmap = BitmapFactory.decodeFile(path)
                    if (bitmap != null) {
                        binding.ivWatermark.setImageBitmap(bitmap)
                        return
                    }
                }
                handler.postDelayed(this, 2000)
            }
        }
        handler.postDelayed(wmRunnable, 2000)
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
