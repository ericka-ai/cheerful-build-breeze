package com.dbtickets.app

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.widget.PopupMenu
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.ItemTouchHelper
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.dbtickets.app.databinding.ActivityMainBinding
import okhttp3.*
import org.json.JSONArray
import org.json.JSONObject
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.*

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var allTickets: List<Ticket> = emptyList()
    private var isAuthenticated = false

    private val importLauncher = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri?.let { importBackup(it) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnLoadTicket.setOnClickListener {
            val auftragsnummer = binding.etAuftragsnummer.text.toString().trim()
            if (auftragsnummer.isEmpty()) {
                binding.tvError.text = getString(R.string.bitte_auftragsnummer_eingeben)
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
                Toast.makeText(this@MainActivity, getString(R.string.authentifizierung_fehlgeschlagen), Toast.LENGTH_SHORT).show()
            }
        })

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle(getString(R.string.app_name))
            .setSubtitle(getString(R.string.identifiziere_dich))
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL)
            .build()

        biometricPrompt.authenticate(promptInfo)
    }

    private fun setupSwipeToDelete() {
        val swipeHandler = object : ItemTouchHelper.SimpleCallback(0, ItemTouchHelper.LEFT) {
            override fun onMove(rv: RecyclerView, vh: RecyclerView.ViewHolder, target: RecyclerView.ViewHolder) = false

            override fun getSwipeDirs(recyclerView: RecyclerView, viewHolder: RecyclerView.ViewHolder): Int {
                if (viewHolder is TicketAdapter.HeaderViewHolder) return 0
                return super.getSwipeDirs(recyclerView, viewHolder)
            }

            override fun onSwiped(viewHolder: RecyclerView.ViewHolder, direction: Int) {
                val position = viewHolder.bindingAdapterPosition
                val adapter = binding.rvTickets.adapter as? TicketAdapter ?: return
                val ticket = try { adapter.getTicketAt(position) } catch (e: Exception) { loadTicketHistory(); return }

                AlertDialog.Builder(this@MainActivity)
                    .setTitle(getString(R.string.ticket_loeschen))
                    .setMessage(getString(R.string.ticket_loeschen_frage, ticket.auftragsnummer))
                    .setPositiveButton(getString(R.string.loeschen)) { _, _ ->
                        TicketStore.deleteTicket(this@MainActivity, ticket.id)
                        loadTicketHistory()
                        Toast.makeText(this@MainActivity, getString(R.string.ticket_geloescht), Toast.LENGTH_SHORT).show()
                    }
                    .setNegativeButton(getString(R.string.abbrechen)) { _, _ ->
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
        binding.btnLoadTicket.text = getString(R.string.wird_geladen)
        binding.progressBar.visibility = View.VISIBLE

        val serverUrl = TicketStore.getServerUrl(this)
        val client = ApiClient.lookupClient

        val request = Request.Builder()
            .url("$serverUrl/api/ticket/$auftragsnummer")
            .get()
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread {
                    binding.btnLoadTicket.isEnabled = true
                    binding.btnLoadTicket.text = getString(R.string.ticket_laden)
                    binding.progressBar.visibility = View.GONE
                    binding.tvError.text = getString(R.string.error_connection)
                    binding.tvError.visibility = View.VISIBLE
                }
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""

                if (!response.isSuccessful) {
                    runOnUiThread {
                        binding.btnLoadTicket.isEnabled = true
                        binding.btnLoadTicket.text = getString(R.string.ticket_laden)
                        binding.progressBar.visibility = View.GONE
                        binding.tvError.text = getString(R.string.ticket_nicht_gefunden)
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
                    val watermarkBase64 = json.optString("watermark_base64", "")

                    // Show ticket immediately, process images in background
                    runOnUiThread {
                        binding.btnLoadTicket.isEnabled = true
                        binding.btnLoadTicket.text = getString(R.string.ticket_laden)
                        binding.progressBar.visibility = View.GONE

                        val intent = Intent(this@MainActivity, TicketResultActivity::class.java)
                        intent.putExtra("ticket_store_id", uniqueId)
                        startActivity(intent)
                    }

                    // Save barcode/watermark in background
                    Thread {
                        try {
                            if (barcodeBase64.isNotEmpty()) {
                                val barcodeBytes = android.util.Base64.decode(barcodeBase64, android.util.Base64.DEFAULT)
                                val dir = File(filesDir, "barcodes")
                                dir.mkdirs()
                                val imgFile = File(dir, "barcode_${ticket.ticketId}.png")
                                FileOutputStream(imgFile).use { it.write(barcodeBytes) }
                                TicketStore.updateTicketBarcodePath(this@MainActivity, ticket.id, imgFile.absolutePath)
                            }
                            if (watermarkBase64.isNotEmpty()) {
                                val wmBytes = android.util.Base64.decode(watermarkBase64, android.util.Base64.DEFAULT)
                                val dir = File(filesDir, "watermarks")
                                dir.mkdirs()
                                val imgFile = File(dir, "watermark_${ticket.ticketId}.jpg")
                                FileOutputStream(imgFile).use { it.write(wmBytes) }
                                TicketStore.updateTicketWatermarkPath(this@MainActivity, ticket.id, imgFile.absolutePath)
                            }
                        } catch (t: Throwable) {
                            // Ignore image save errors
                        }
                    }.start()

                    downloadPdfAsync(ticket)

                } catch (t: Throwable) {
                    runOnUiThread {
                        binding.btnLoadTicket.isEnabled = true
                        binding.btnLoadTicket.text = getString(R.string.ticket_laden)
                        binding.progressBar.visibility = View.GONE
                        binding.tvError.text = getString(R.string.fehler_beim_laden)
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
        updateWidget()
    }

    private fun updateWidget() {
        val manager = AppWidgetManager.getInstance(this)
        val ids = manager.getAppWidgetIds(ComponentName(this, TicketWidgetProvider::class.java))
        for (id in ids) {
            TicketWidgetProvider.updateWidget(this, manager, id)
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

    fun onMenuClick(view: View) {
        val popup = PopupMenu(this, view)
        popup.menu.add(0, 1, 0, getString(R.string.backup_exportieren))
        popup.menu.add(0, 2, 1, getString(R.string.backup_importieren))
        popup.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                1 -> exportBackup()
                2 -> importLauncher.launch("application/json")
            }
            true
        }
        popup.show()
    }

    private fun exportBackup() {
        val tickets = TicketStore.getTickets(this)
        if (tickets.isEmpty()) {
            Toast.makeText(this, getString(R.string.keine_tickets_zum_exportieren), Toast.LENGTH_SHORT).show()
            return
        }
        val array = JSONArray()
        tickets.forEach { array.put(it.toJson()) }
        val backup = JSONObject()
        backup.put("exported_at", TicketStore.nowFormatted())
        backup.put("total_tickets", tickets.size)
        backup.put("tickets", array)

        val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        val file = File(downloadsDir, "db_tickets_backup_${System.currentTimeMillis()}.json")
        file.writeText(backup.toString(2))
        Toast.makeText(this, getString(R.string.backup_erfolgreich), Toast.LENGTH_SHORT).show()
    }

    private fun importBackup(uri: Uri) {
        try {
            val inputStream = contentResolver.openInputStream(uri) ?: return
            val jsonStr = inputStream.bufferedReader().readText()
            inputStream.close()
            val backup = JSONObject(jsonStr)
            val ticketsArray = backup.optJSONArray("tickets") ?: return
            var count = 0
            for (i in 0 until ticketsArray.length()) {
                val obj = ticketsArray.getJSONObject(i)
                val ticket = Ticket.fromJson(obj)
                if (TicketStore.getTicketByAuftragsnummer(this, ticket.auftragsnummer) == null) {
                    TicketStore.saveTicket(this, ticket)
                    count++
                }
            }
            Toast.makeText(this, getString(R.string.restore_erfolgreich, count), Toast.LENGTH_SHORT).show()
            loadTicketHistory()
        } catch (e: Exception) {
            Toast.makeText(this, "Import fehlgeschlagen: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }
}

sealed class TicketListItem {
    data class Header(val title: String) : TicketListItem()
    data class TicketItem(val ticket: Ticket) : TicketListItem()
}

class TicketAdapter(
    tickets: List<Ticket>,
    private val onClick: (Ticket) -> Unit
) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

    private val items: List<TicketListItem>

    init {
        items = buildGroupedList(tickets)
    }

    private fun buildGroupedList(tickets: List<Ticket>): List<TicketListItem> {
        if (tickets.size < 3) {
            return tickets.map { TicketListItem.TicketItem(it) }
        }
        val sdf = SimpleDateFormat("dd.MM.yyyy", Locale.GERMANY)
        val now = Date()
        val active = mutableListOf<Ticket>()
        val upcoming = mutableListOf<Ticket>()
        val expired = mutableListOf<Ticket>()

        for (t in tickets) {
            try {
                val start = sdf.parse(t.gueltigVon)
                val end = sdf.parse(t.gueltigBis)
                when {
                    end != null && end.before(now) -> expired.add(t)
                    start != null && start.after(now) -> upcoming.add(t)
                    else -> active.add(t)
                }
            } catch (e: Exception) {
                active.add(t)
            }
        }

        val result = mutableListOf<TicketListItem>()
        if (active.isNotEmpty()) {
            result.add(TicketListItem.Header("Aktive Tickets"))
            active.forEach { result.add(TicketListItem.TicketItem(it)) }
        }
        if (upcoming.isNotEmpty()) {
            result.add(TicketListItem.Header("Kommende Tickets"))
            upcoming.forEach { result.add(TicketListItem.TicketItem(it)) }
        }
        if (expired.isNotEmpty()) {
            result.add(TicketListItem.Header("Abgelaufene Tickets"))
            expired.forEach { result.add(TicketListItem.TicketItem(it)) }
        }
        return result
    }

    companion object {
        private const val TYPE_HEADER = 0
        private const val TYPE_TICKET = 1
    }

    override fun getItemViewType(position: Int): Int {
        return when (items[position]) {
            is TicketListItem.Header -> TYPE_HEADER
            is TicketListItem.TicketItem -> TYPE_TICKET
        }
    }

    class HeaderViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvHeader: TextView = view as TextView
    }

    class TicketViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvName: TextView = view.findViewById(R.id.tvItemName)
        val tvType: TextView = view.findViewById(R.id.tvItemTicketType)
        val tvDate: TextView = view.findViewById(R.id.tvItemDate)
        val tvAuftrag: TextView = view.findViewById(R.id.tvItemAuftrag)
        val tvPreis: TextView = view.findViewById(R.id.tvItemPreis)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        return if (viewType == TYPE_HEADER) {
            val tv = TextView(parent.context).apply {
                textSize = 16f
                setTextColor(parent.context.getColor(R.color.text_primary))
                setPadding(0, 32, 0, 12)
                setTypeface(typeface, android.graphics.Typeface.BOLD)
            }
            HeaderViewHolder(tv)
        } else {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_ticket, parent, false)
            TicketViewHolder(view)
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        when (val item = items[position]) {
            is TicketListItem.Header -> {
                (holder as HeaderViewHolder).tvHeader.text = item.title
            }
            is TicketListItem.TicketItem -> {
                val ticket = item.ticket
                val h = holder as TicketViewHolder
                h.tvType.text = ticket.ticketTypeLabel
                h.tvName.text = "${ticket.vorname} ${ticket.nachname}"
                h.tvDate.text = "${ticket.gueltigVon} – ${ticket.gueltigBis}"
                h.tvAuftrag.text = "Nr. ${ticket.auftragsnummer}"
                if (ticket.preis.isNotEmpty()) {
                    h.tvPreis.text = "${ticket.preis} €"
                    h.tvPreis.visibility = View.VISIBLE
                } else {
                    h.tvPreis.visibility = View.GONE
                }
                h.itemView.setOnClickListener { onClick(ticket) }
            }
        }
    }

    override fun getItemCount() = items.size

    fun getTicketAt(position: Int): Ticket {
        val item = items[position]
        return if (item is TicketListItem.TicketItem) item.ticket
        else throw IllegalStateException("Not a ticket position")
    }
}
