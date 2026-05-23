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
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.*

class TicketFormActivity : AppCompatActivity() {

    private lateinit var binding: ActivityTicketFormBinding
    private var ticketType = ""
    private val dateFormat = SimpleDateFormat("dd.MM.yyyy", Locale.GERMANY)

    private val stations = arrayOf(
        "Berlin Hbf", "Hamburg Hbf", "Muenchen Hbf", "Koeln Hbf",
        "Frankfurt(Main)Hbf", "Stuttgart Hbf", "Duesseldorf Hbf",
        "Hannover Hbf", "Leipzig Hbf", "Dresden Hbf", "Nuernberg Hbf",
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

        // Set default dates
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

            submitTicket(nachname, vorname, geburtsdatum)
        }
    }

    private fun submitTicket(nachname: String, vorname: String, geburtsdatum: String) {
        val prefs = getSharedPreferences("db_tickets", MODE_PRIVATE)
        val serverUrl = prefs.getString("server_url", "") ?: ""

        if (serverUrl.isEmpty()) {
            runOnUiThread {
                Toast.makeText(this, "Bitte zuerst Server-URL in Einstellungen setzen", Toast.LENGTH_LONG).show()
                binding.btnSubmit.isEnabled = true
                binding.btnSubmit.text = getString(R.string.ticket_erstellen)
            }
            return
        }

        val klasse = if (binding.rbKlasse1.isChecked) "1" else "2"
        val passagierTyp = if (binding.rbErwachsener.isChecked) "ERWACHSENER" else "JUGENDLICHER"

        val formBody = FormBody.Builder()
            .add("nachname", nachname)
            .add("vorname", vorname)
            .add("geburtsdatum", geburtsdatum)
            .add("klasse", klasse)
            .add("passagier_typ", passagierTyp)
            .add("gueltig_von", binding.etGueltigVon.text.toString())

        when (ticketType) {
            "grp_consecutive", "grp_flexi" -> {
                val passTyp = if (binding.rbConsecutive.isChecked) "consecutive" else "flexi"
                val selectedDays = binding.spinnerReisetage.selectedItem.toString().split(" ")[0]
                formBody.add("product", "grp_$passTyp")
                formBody.add("tage", selectedDays)
                formBody.add("gueltig_bis", binding.etGueltigBis.text.toString())
            }
            "eurail_global" -> {
                val selectedDays = binding.spinnerReisetage.selectedItem.toString().split(" ")[0]
                formBody.add("product", "eurail_global")
                formBody.add("tage", selectedDays)
                formBody.add("gueltig_bis", binding.etGueltigBis.text.toString())
            }
            "deutschlandticket" -> {
                formBody.add("product", "deutschlandticket")
            }
            "sparpreis" -> {
                formBody.add("product", "sparpreis")
                formBody.add("von", binding.spinnerVon.selectedItem.toString())
                formBody.add("nach", binding.spinnerNach.selectedItem.toString())
                formBody.add("zug_typ", binding.etZugTyp.text.toString())
                formBody.add("zug_nummer", binding.etZugNummer.text.toString())
                formBody.add("gueltig_bis", binding.etGueltigBis.text.toString())
            }
        }

        val client = OkHttpClient()
        val request = Request.Builder()
            .url("$serverUrl/api/generate")
            .post(formBody.build())
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread {
                    Toast.makeText(
                        this@TicketFormActivity,
                        getString(R.string.error_connection) + ": " + e.message,
                        Toast.LENGTH_LONG
                    ).show()
                    binding.btnSubmit.isEnabled = true
                    binding.btnSubmit.text = getString(R.string.ticket_erstellen)
                }
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: "{}"
                runOnUiThread {
                    try {
                        val json = JSONObject(body)
                        val intent = Intent(this@TicketFormActivity, TicketResultActivity::class.java)
                        intent.putExtra("auftragsnummer", json.optString("auftragsnummer", "N/A"))
                        intent.putExtra("ticket_id", json.optString("ticket_id", "N/A"))
                        intent.putExtra("ticket_type", ticketType)
                        intent.putExtra("name", "$vorname $nachname")
                        intent.putExtra("geburtsdatum", geburtsdatum)
                        intent.putExtra("gueltigkeit", "${binding.etGueltigVon.text} - ${binding.etGueltigBis.text}")
                        intent.putExtra("preis", json.optString("preis", ""))
                        intent.putExtra("pdf_url", json.optString("pdf_url", ""))
                        startActivity(intent)
                        finish()
                    } catch (e: Exception) {
                        Toast.makeText(
                            this@TicketFormActivity,
                            "Fehler: ${e.message}",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                    binding.btnSubmit.isEnabled = true
                    binding.btnSubmit.text = getString(R.string.ticket_erstellen)
                }
            }
        })
    }
}
