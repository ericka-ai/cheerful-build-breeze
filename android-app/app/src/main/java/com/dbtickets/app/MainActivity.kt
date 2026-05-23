package com.dbtickets.app

import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.dbtickets.app.databinding.ActivityMainBinding
import okhttp3.*
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.util.*

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var allTickets: List<Ticket> = emptyList()
    private var isAuthenticated = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnLoadTicket.setOnClickListener {
            val auftragsnummer = binding.etAuftragsnummer.text.toString().trim()
            if (auftragsnummer.isEmpty()) {
                binding.tvError.text = "Bitte Auftragsnummer eingeben"
                binding.tvError.visibility = View.VISIBLE
                return@setOnClickListener
            }
            binding.tvError.visibility = View.GONE
            loadTicketByAuftragsnummer(auftragsnummer)
        }

        binding.rvTickets.layoutManager = LinearLayoutManager(this)

        binding.swipeRefresh.setColorSchemeResources(android.R.color.holo_red_dark)
        binding.swipeRefresh.setOnRefreshListener {
            loadTicketHistory()
            binding.swipeRefresh.isRefreshing = false
        }

        binding.etSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                filterTickets(s?.toString() ?: "")
            }
        })

        setupSwipeToDelete()
        checkBiometricAuth()
    }

    override fun onResume() {
        super.onResume()
        loadTicketHistory()
    }

    private fun checkBiometricAuth() {
        val biometricManager = BiometricManager.from(this)
        if (biometricManager.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL) == BiometricManager.BIOMETRIC_SUCCESS) {
            val prefs = getSharedPreferences("db_tickets", MODE_PRIVATE)
            val biometricEnabled = prefs.getBoolean("biometric_enabled", false)
            if (biometricEnabled && !isAuthenticated) {
                showBiometricPrompt()
            }
        }
    }

    private fun showBiometricPrompt() {
        val executor = ContextCompat.getMainExecutor(this)
        val biometricPrompt = BiometricPrompt(this, executor, object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                isAuthenticated = true
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                if (errorCode == BiometricPrompt.ERROR_USER_CANCELED || errorCode == BiometricPrompt.ERROR_NEGATIVE_BUTTON) {
                    finish()
                }
            }

            override fun onAuthenticationFailed() {
                Toast.makeText(this@MainActivity, "Authentifizierung fehlgeschlagen", Toast.LENGTH_SHORT).show()
            }
        })

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("DB Tickets")
            .setSubtitle("Identifiziere dich um fortzufahren")
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL)
            .build()

        biometricPrompt.authenticate(promptInfo)
    }

    private fun setupSwipeToDelete() {
        val swipeHandler = object : ItemTouchHelper.SimpleCallback(0, ItemTouchHelper.LEFT) {
            override fun onMove(rv: RecyclerView, vh: RecyclerView.ViewHolder, target: RecyclerView.ViewHolder) = false

            override fun onSwiped(viewHolder: RecyclerView.ViewHolder, direction: Int) {
                val position = viewHolder.bindingAdapterPosition
                val adapter = binding.rvTickets.adapter as? TicketAdapter ?: return
                val ticket = adapter.getTicketAt(position)

                AlertDialog.Builder(this@MainActivity)
                    .setTitle("Ticket l\u00f6schen")
                    .setMessage("M\u00f6chtest du das Ticket ${ticket.auftragsnummer} wirklich l\u00f6schen?")
                    .setPositiveButton("L\u00f6schen") { _, _ ->
                        TicketStore.deleteTicket(this@MainActivity, ticket.id)
                        loadTicketHistory()
                        Toast.makeText(this@MainActivity, "Ticket gel\u00f6scht", Toast.LENGTH_SHORT).show()
                    }
                    .setNegativeButton("Abbrechen") { _, _ ->
                        loadTicketHistory()
                    }
                    .setOnCancelListener {
                        loadTicketHistory()
                    }
                    .show()
            }
        }
        ItemTouchHelper(swipeHandler).attachToRecyclerView(binding.rvTickets)
    }

    private fun createHttpClient(): OkHttpClient {
        return ApiClient.client
    }

    private fun buildFormBody(ticket: Ticket): FormBody {
        return FormBody.Builder()
            .add("nachname", ticket.nachname)
            .add("vorname", ticket.vorname)
            .add("geburtsdatum", ticket.geburtsdatum)
            .add("klasse", ticket.klasse)
            .add("passagier_typ", ticket.passagierTyp)
            .add("gueltig_von", ticket.gueltigVon)
            .add("gueltig_bis", ticket.gueltigBis)
            .add("product", ticket.product)
            .add("tage", "15")
            .add("ticket_id", ticket.ticketId)
            .add("order_number", ticket.auftragsnummer)
            .build()
    }

    private fun loadTicketByAuftragsnummer(auftragsnummer: String) {
        val existing = TicketStore.getTicketByAuftragsnummer(this, auftragsnummer)
        if (existing != null) {
            val intent = Intent(this, TicketResultActivity::class.java)
            intent.putExtra("ticket_store_id", existing.id)
            startActivity(intent)
            return
        }

        binding.btnLoadTicket.isEnabled = false
        binding.btnLoadTicket.text = "Wird geladen..."
        binding.progressBar.visibility = View.VISIBLE

        val serverUrl = TicketStore.getServerUrl(this)
        val client = createHttpClient()

        val request = Request.Builder()
            .url("$serverUrl/api/ticket/$auftragsnummer")
            .get()
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread {
                    binding.btnLoadTicket.isEnabled = true
                    binding.btnLoadTicket.text = "Ticket laden"
                    binding.progressBar.visibility = View.GONE
                    binding.tvError.text = "Verbindung zum Server fehlgeschlagen"
                    binding.tvError.visibility = View.VISIBLE
                }
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""

                if (!response.isSuccessful) {
                    runOnUiThread {
                        binding.btnLoadTicket.isEnabled = true
                        binding.btnLoadTicket.text = "Ticket laden"
                        binding.progressBar.visibility = View.GONE
                        binding.tvError.text = "Ticket nicht gefunden"
                        binding.tvError.visibility = View.VISIBLE
                    }
                    return
                }

                try {
                    val json = JSONObject(body)
                    val uniqueId = UUID.randomUUID().toString()
                    val product = json.optString("product", "grp_consecutive")

                    val ticket = Ticket(
                        id = uniqueId,
                        auftragsnummer = json.optString("auftragsnummer"),
                        ticketId = json.optString("ticket_id"),
                        ticketType = product,
                        ticketTypeLabel = json.optString("ticket_type_label", TicketStore.getProductLabel(product)),
                        nachname = json.optString("nachname"),
                        vorname = json.optString("vorname"),
                        geburtsdatum = json.optString("geburtsdatum"),
                        klasse = json.optString("klasse", "2"),
                        passagierTyp = json.optString("passagier_typ", "ERWACHSENER"),
                        gueltigVon = json.optString("gueltig_von"),
                        gueltigBis = json.optString("gueltig_bis"),
                        preis = json.optString("preis"),
                        createdAt = json.optString("created_at", TicketStore.nowFormatted()),
                        product = product,
                    )

                    TicketStore.saveTicket(this@MainActivity, ticket)
                    TicketExpiryReceiver.scheduleReminder(this@MainActivity, ticket)

                    val barcodeBase64 = json.optString("barcode_base64", "")
                    if (barcodeBase64.isNotEmpty()) {
                        val barcodeBytes = android.util.Base64.decode(barcodeBase64, android.util.Base64.DEFAULT)
                        val dir = File(filesDir, "barcodes")
                        dir.mkdirs()
                        val imgFile = File(dir, "barcode_${ticket.ticketId}.png")
                        FileOutputStream(imgFile).use { it.write(barcodeBytes) }
                        TicketStore.updateTicketBarcodePath(this@MainActivity, ticket.id, imgFile.absolutePath)
                    }

                    val watermarkBase64 = json.optString("watermark_base64", "")
                    if (watermarkBase64.isNotEmpty()) {
                        val wmBytes = android.util.Base64.decode(watermarkBase64, android.util.Base64.DEFAULT)
                        val dir = File(filesDir, "watermarks")
                        dir.mkdirs()
                        val imgFile = File(dir, "watermark_${ticket.ticketId}.jpg")
                        FileOutputStream(imgFile).use { it.write(wmBytes) }
                        TicketStore.updateTicketWatermarkPath(this@MainActivity, ticket.id, imgFile.absolutePath)
                    }

                    downloadPdfAsync(ticket)

                    runOnUiThread {
                        binding.btnLoadTicket.isEnabled = true
                        binding.btnLoadTicket.text = "Ticket laden"
                        binding.progressBar.visibility = View.GONE

                        val intent = Intent(this@MainActivity, TicketResultActivity::class.java)
                        intent.putExtra("ticket_store_id", uniqueId)
                        startActivity(intent)
                    }

                } catch (e: Exception) {
                    runOnUiThread {
                        binding.btnLoadTicket.isEnabled = true
                        binding.btnLoadTicket.text = "Ticket laden"
                        binding.progressBar.visibility = View.GONE
                        binding.tvError.text = "Fehler beim Laden des Tickets"
                        binding.tvError.visibility = View.VISIBLE
                    }
                }
            }
        })
    }

    private fun downloadPdfAsync(ticket: Ticket) {
        val serverUrl = TicketStore.getServerUrl(this)
        val client = createHttpClient()

        val formBody = FormBody.Builder()
            .add("name", "${ticket.nachname}/${ticket.vorname}")
            .add("birth_date", ticket.geburtsdatum)
            .add("validity_start", ticket.gueltigVon)
            .add("validity_end", ticket.gueltigBis)
            .add("ticket_id", ticket.ticketId)
            .add("order_number", ticket.auftragsnummer)
            .add("klasse", ticket.klasse)
            .add("price", ticket.preis)
            .add("product", ticket.product)
            .build()

        val request = Request.Builder()
            .url("$serverUrl/generate")
            .post(formBody)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {}
            override fun onResponse(call: Call, response: Response) {
                if (response.isSuccessful) {
                    val pdfBytes = response.body?.bytes() ?: return
                    val pdfDir = File(filesDir, "tickets")
                    pdfDir.mkdirs()
                    val pdfFile = File(pdfDir, "ticket_${ticket.ticketId}.pdf")
                    FileOutputStream(pdfFile).use { it.write(pdfBytes) }
                    TicketStore.updateTicketPdfPath(this@MainActivity, ticket.id, pdfFile.absolutePath)
                }
            }
        })
    }

    private fun loadTicketHistory() {
        allTickets = TicketStore.getTickets(this)
        if (allTickets.isEmpty()) {
            binding.tvNoTickets.visibility = View.VISIBLE
            binding.rvTickets.visibility = View.GONE
            binding.tvRecentTickets.visibility = View.GONE
            binding.etSearch.visibility = View.GONE
        } else {
            binding.tvNoTickets.visibility = View.GONE
            binding.rvTickets.visibility = View.VISIBLE
            binding.tvRecentTickets.visibility = View.VISIBLE
            binding.etSearch.visibility = if (allTickets.size > 3) View.VISIBLE else View.GONE
            displayTickets(allTickets)
        }
    }

    private fun filterTickets(query: String) {
        if (query.isEmpty()) {
            displayTickets(allTickets)
            return
        }
        val q = query.lowercase()
        val filtered = allTickets.filter {
            it.nachname.lowercase().contains(q) ||
            it.vorname.lowercase().contains(q) ||
            it.auftragsnummer.contains(q) ||
            it.ticketTypeLabel.lowercase().contains(q) ||
            it.gueltigVon.contains(q) ||
            it.gueltigBis.contains(q)
        }
        displayTickets(filtered)
    }

    private fun displayTickets(tickets: List<Ticket>) {
        binding.rvTickets.adapter = TicketAdapter(tickets) { ticket ->
            val intent = Intent(this, TicketResultActivity::class.java)
            intent.putExtra("ticket_store_id", ticket.id)
            startActivity(intent)
        }
    }
}

class TicketAdapter(
    private val tickets: List<Ticket>,
    private val onClick: (Ticket) -> Unit
) : RecyclerView.Adapter<TicketAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvName: TextView = view.findViewById(R.id.tvItemName)
        val tvType: TextView = view.findViewById(R.id.tvItemTicketType)
        val tvDate: TextView = view.findViewById(R.id.tvItemDate)
        val tvAuftrag: TextView = view.findViewById(R.id.tvItemAuftrag)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_ticket, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val ticket = tickets[position]
        holder.tvName.text = "${ticket.vorname} ${ticket.nachname}"
        holder.tvType.text = ticket.ticketTypeLabel
        holder.tvDate.text = "${ticket.gueltigVon} - ${ticket.gueltigBis}"
        holder.tvAuftrag.text = "Nr: ${ticket.auftragsnummer}"
        holder.itemView.setOnClickListener { onClick(ticket) }
    }

    override fun getItemCount() = tickets.size

    fun getTicketAt(position: Int): Ticket = tickets[position]
}
