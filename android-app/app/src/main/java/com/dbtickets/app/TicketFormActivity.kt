package com.dbtickets.app

import android.app.DatePickerDialog
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.dbtickets.app.databinding.ActivityTicketFormBinding
import okhttp3.*
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.*

class TicketFormActivity : AppCompatActivity() {

    private lateinit var binding: ActivityTicketFormBinding
    private var ticketType = ""
    private val dateFormat = SimpleDateFormat("dd.MM.yyyy", Locale.GERMANY)

    private val stations = arrayOf(
        "Berlin Hbf", "Hamburg Hbf", "M\u00fcnchen Hbf", "K\u00f6ln Hbf",
        "Frankfurt(Main)Hbf", "Stuttgart Hbf", "D\u00fcsseldorf Hbf",
        "Hannover Hbf", "Leipzig Hbf", "Dresden Hbf", "N\u00fcrnberg Hbf",
        "Bremen Hbf", "Dortmund Hbf", "Essen Hbf", "Mannheim Hbf",
        "Karlsruhe Hbf", "Augsburg Hbf", "Freiburg(Brsg)Hbf",
        "Erfurt Hbf", "Rostock Hbf"
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityTicketFormBinding.inflate(layoutInflater)
        setContentView(binding.root)

        ticketType = intent.getStringExtra("ticket_type") ?: "grp_consecutive"
        setupUI()
        setupDatePickers()
        setupSubmitButton()

        binding.btnBack.setOnClickListener { finish() }
    }

    private fun setupUI() {
        val titleMap = mapOf(
            "grp_consecutive" to "German Rail Pass",
            "grp_flexi" to "German Rail Pass (Flexi)",
            "eurail_global" to "Eurail Global Pass",
            "deutschlandticket" to "Deutschlandticket",
            "sparpreis" to "DB Sparpreis"
        )
        binding.tvTicketType.text = titleMap[ticketType] ?: ticketType
        binding.tvTitle.text = titleMap[ticketType] ?: "Ticket erstellen"

        when (ticketType) {
            "grp_consecutive", "grp_flexi" -> {
                binding.layoutPassTyp.visibility = View.VISIBLE
                binding.layoutReisetage.visibility = View.VISIBLE
                val days = arrayOf("3 Tage", "4 Tage", "5 Tage", "7 Tage", "10 Tage", "15 Tage")
                binding.spinnerReisetage.adapter = ArrayAdapter(
                    this, android.R.layout.simple_spinner_dropdown_item, days
                )
                if (ticketType == "grp_flexi") {
                    binding.rbFlexi.isChecked = true
                }
            }
            "eurail_global" -> {
                binding.layoutReisetage.visibility = View.VISIBLE
                val days = arrayOf("4 Tage", "5 Tage", "7 Tage", "10 Tage", "15 Tage", "22 Tage", "31 Tage")
                binding.spinnerReisetage.adapter = ArrayAdapter(
                    this, android.R.layout.simple_spinner_dropdown_item, days
                )
            }
            "deutschlandticket" -> {
                binding.layoutGueltigBis.visibility = View.GONE
            }
            "sparpreis" -> {
                binding.layoutSparpreis.visibility = View.VISIBLE
                val stationAdapter = ArrayAdapter(
                    this, android.R.layout.simple_spinner_dropdown_item, stations
                )
                binding.spinnerVon.adapter = stationAdapter
                binding.spinnerNach.adapter = stationAdapter
                binding.spinnerNach.setSelection(1)
            }
        }

        val cal = Calendar.getInstance()
        binding.etGueltigVon.setText(dateFormat.format(cal.time))
        cal.add(Calendar.DAY_OF_MONTH, 7)
        binding.etGueltigBis.setText(dateFormat.format(cal.time))
    }

    private fun setupDatePickers() {
        val cal = Calendar.getInstance()

        binding.etGeburtsdatum.setOnClickListener {
            DatePickerDialog(this, { _, year, month, day ->
                cal.set(year, month, day)
                binding.etGeburtsdatum.setText(dateFormat.format(cal.time))
            }, 1990, 0, 1).show()
        }

        binding.etGueltigVon.setOnClickListener {
            val now = Calendar.getInstance()
            DatePickerDialog(this, { _, year, month, day ->
                now.set(year, month, day)
                binding.etGueltigVon.setText(dateFormat.format(now.time))
            }, now.get(Calendar.YEAR), now.get(Calendar.MONTH), now.get(Calendar.DAY_OF_MONTH)).show()
        }

        binding.etGueltigBis.setOnClickListener {
            val now = Calendar.getInstance()
            DatePickerDialog(this, { _, year, month, day ->
                now.set(year, month, day)
                binding.etGueltigBis.setText(dateFormat.format(now.time))
            }, now.get(Calendar.YEAR), now.get(Calendar.MONTH), now.get(Calendar.DAY_OF_MONTH)).show()
        }
    }

    private fun setupSubmitButton() {
        binding.btnSubmit.setOnClickListener {
            val nachname = binding.etNachname.text.toString().trim()
            val vorname = binding.etVorname.text.toString().trim()
            val geburtsdatum = binding.etGeburtsdatum.text.toString().trim()

            if (nachname.isEmpty() || vorname.isEmpty() || geburtsdatum.isEmpty()) {
                Toast.makeText(this, getString(R.string.error_fields), Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            binding.btnSubmit.isEnabled = false
            binding.btnSubmit.text = getString(R.string.bitte_warten)

            createTicket(nachname, vorname, geburtsdatum)
        }
    }

    private fun createTicket(nachname: String, vorname: String, geburtsdatum: String) {
        val klasse = if (binding.rbKlasse1.isChecked) "1" else "2"
        val passagierTyp = if (binding.rbErwachsener.isChecked) "ERWACHSENER" else "JUGENDLICHER"
        val gueltigVon = binding.etGueltigVon.text.toString()
        val gueltigBis = binding.etGueltigBis.text.toString()

        val product = when (ticketType) {
            "grp_consecutive", "grp_flexi" -> {
                if (binding.rbConsecutive.isChecked) "grp_consecutive" else "grp_flexi"
            }
            else -> ticketType
        }

        val days = when (ticketType) {
            "grp_consecutive", "grp_flexi", "eurail_global" -> {
                binding.spinnerReisetage.selectedItem.toString().split(" ")[0].toIntOrNull() ?: 15
            }
            else -> 1
        }

        val auftragsnummer = TicketStore.generateAuftragsnummer()
        val ticketId = TicketStore.generateTicketId()
        val preis = TicketStore.getPriceForProduct(product, days, klasse, passagierTyp)
        val uniqueId = UUID.randomUUID().toString()

        val ticket = Ticket(
            id = uniqueId,
            auftragsnummer = auftragsnummer,
            ticketId = ticketId,
            ticketType = ticketType,
            ticketTypeLabel = TicketStore.getProductLabel(product),
            nachname = nachname,
            vorname = vorname,
            geburtsdatum = geburtsdatum,
            klasse = klasse,
            passagierTyp = passagierTyp,
            gueltigVon = gueltigVon,
            gueltigBis = gueltigBis,
            preis = preis,
            createdAt = TicketStore.nowFormatted(),
            product = product,
        )

        TicketStore.saveTicket(this, ticket)

        binding.btnSubmit.text = "Barcode wird geladen..."

        downloadBarcodeSync(ticket, nachname, vorname, geburtsdatum, klasse, passagierTyp, gueltigVon, gueltigBis, product, days.toString()) {
            downloadWatermark(ticket, nachname, vorname, geburtsdatum, klasse, passagierTyp, gueltigVon, gueltigBis, product, days.toString())
            downloadPdf(ticket, nachname, vorname, geburtsdatum, klasse, passagierTyp, gueltigVon, gueltigBis, product, days.toString())

            runOnUiThread {
                val intent = Intent(this, TicketResultActivity::class.java)
                intent.putExtra("ticket_store_id", uniqueId)
                startActivity(intent)
                finish()
            }
        }
    }

    private fun buildFormBody(
        nachname: String, vorname: String, geburtsdatum: String,
        klasse: String, passagierTyp: String,
        gueltigVon: String, gueltigBis: String,
        product: String, days: String, ticket: Ticket,
    ): FormBody.Builder {
        val formBody = FormBody.Builder()
            .add("nachname", nachname)
            .add("vorname", vorname)
            .add("geburtsdatum", geburtsdatum)
            .add("klasse", klasse)
            .add("passagier_typ", passagierTyp)
            .add("gueltig_von", gueltigVon)
            .add("gueltig_bis", gueltigBis)
            .add("product", product)
            .add("tage", days)
            .add("ticket_id", ticket.ticketId)
            .add("order_number", ticket.auftragsnummer)

        if (product == "sparpreis" || product == "db_sparpreis") {
            formBody.add("von", binding.spinnerVon.selectedItem?.toString() ?: "Berlin Hbf")
            formBody.add("nach", binding.spinnerNach.selectedItem?.toString() ?: "Hamburg Hbf")
            formBody.add("zug_typ", binding.etZugTyp.text?.toString() ?: "ICE")
            formBody.add("zug_nummer", binding.etZugNummer.text?.toString() ?: "919")
        }

        return formBody
    }

    private fun createHttpClient(): OkHttpClient {
        return OkHttpClient.Builder()
            .connectTimeout(30, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(60, java.util.concurrent.TimeUnit.SECONDS)
            .build()
    }

    private fun downloadBarcodeSync(
        ticket: Ticket,
        nachname: String, vorname: String, geburtsdatum: String,
        klasse: String, passagierTyp: String,
        gueltigVon: String, gueltigBis: String,
        product: String, days: String,
        onComplete: () -> Unit,
    ) {
        val serverUrl = TicketStore.getServerUrl(this)
        val formBody = buildFormBody(nachname, vorname, geburtsdatum, klasse, passagierTyp, gueltigVon, gueltigBis, product, days, ticket)

        val request = Request.Builder()
            .url("$serverUrl/api/barcode")
            .post(formBody.build())
            .build()

        createHttpClient().newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                onComplete()
            }

            override fun onResponse(call: Call, response: Response) {
                if (response.isSuccessful) {
                    val imgBytes = response.body?.bytes() ?: run { onComplete(); return }
                    val dir = File(filesDir, "barcodes")
                    dir.mkdirs()
                    val imgFile = File(dir, "barcode_${ticket.ticketId}.png")
                    FileOutputStream(imgFile).use { it.write(imgBytes) }
                    TicketStore.updateTicketBarcodePath(this@TicketFormActivity, ticket.id, imgFile.absolutePath)
                }
                onComplete()
            }
        })
    }

    private fun downloadWatermark(
        ticket: Ticket,
        nachname: String, vorname: String, geburtsdatum: String,
        klasse: String, passagierTyp: String,
        gueltigVon: String, gueltigBis: String,
        product: String, days: String,
    ) {
        val serverUrl = TicketStore.getServerUrl(this)
        val formBody = buildFormBody(nachname, vorname, geburtsdatum, klasse, passagierTyp, gueltigVon, gueltigBis, product, days, ticket)

        val request = Request.Builder()
            .url("$serverUrl/api/watermark")
            .post(formBody.build())
            .build()

        try {
            val response = createHttpClient().newCall(request).execute()
            if (response.isSuccessful) {
                val imgBytes = response.body?.bytes() ?: return
                val dir = File(filesDir, "watermarks")
                dir.mkdirs()
                val imgFile = File(dir, "watermark_${ticket.ticketId}.jpg")
                FileOutputStream(imgFile).use { it.write(imgBytes) }
                TicketStore.updateTicketWatermarkPath(this, ticket.id, imgFile.absolutePath)
            }
        } catch (_: Exception) { }
    }

    private fun downloadPdf(
        ticket: Ticket,
        nachname: String, vorname: String, geburtsdatum: String,
        klasse: String, passagierTyp: String,
        gueltigVon: String, gueltigBis: String,
        product: String, days: String,
    ) {
        val serverUrl = TicketStore.getServerUrl(this)

        val formBody = FormBody.Builder()
            .add("name", "$nachname/$vorname")
            .add("birth_date", geburtsdatum)
            .add("validity_start", gueltigVon)
            .add("validity_end", gueltigBis)
            .add("ticket_id", ticket.ticketId)
            .add("order_number", ticket.auftragsnummer)
            .add("klasse", klasse)
            .add("days", days)
            .add("passenger_type", passagierTyp)
            .add("price", ticket.preis)
            .add("product", product)

        if (product == "sparpreis" || product == "db_sparpreis") {
            formBody.add("station_from", binding.spinnerVon.selectedItem?.toString() ?: "Berlin Hbf")
            formBody.add("station_to", binding.spinnerNach.selectedItem?.toString() ?: "Hamburg Hbf")
            formBody.add("zugtyp", binding.etZugTyp.text?.toString() ?: "ICE")
            formBody.add("train_number", binding.etZugNummer.text?.toString() ?: "919")
        }

        val request = Request.Builder()
            .url("$serverUrl/generate")
            .post(formBody.build())
            .build()

        createHttpClient().newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { }

            override fun onResponse(call: Call, response: Response) {
                if (response.isSuccessful) {
                    val pdfBytes = response.body?.bytes() ?: return
                    val pdfDir = File(filesDir, "tickets")
                    pdfDir.mkdirs()
                    val pdfFile = File(pdfDir, "ticket_${ticket.ticketId}.pdf")
                    FileOutputStream(pdfFile).use { it.write(pdfBytes) }
                    TicketStore.updateTicketPdfPath(this@TicketFormActivity, ticket.id, pdfFile.absolutePath)
                }
            }
        })
    }
}
