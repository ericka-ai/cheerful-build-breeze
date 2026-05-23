package com.dbtickets.app

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
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
    }

    override fun onResume() {
        super.onResume()
        loadTicketHistory()
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

                    val barcodeBase64 = json.optString("barcode_base64", "")
                    if (barcodeBase64.isNotEmpty()) {
                        val barcodeBytes = android.util.Base64.decode(barcodeBase64, android.util.Base64.DEFAULT)
                        val dir = File(filesDir, "barcodes")
                        dir.mkdirs()
                        val imgFile = File(dir, "barcode_${ticket.ticketId}.png")
                        FileOutputStream(imgFile).use { it.write(barcodeBytes) }
                        TicketStore.updateTicketBarcodePath(this@MainActivity, ticket.id, imgFile.absolutePath)
                    }

                    downloadWatermarkSync(ticket)
                    downloadPdfAsync(ticket)

                    runOnUiThread {
                        binding.btnLoadTicket.isEnabled = true
                        binding.btnLoadTicket.text = "Ticket laden"

                        val intent = Intent(this@MainActivity, TicketResultActivity::class.java)
                        intent.putExtra("ticket_store_id", uniqueId)
                        startActivity(intent)
                    }

                } catch (e: Exception) {
                    runOnUiThread {
                        binding.btnLoadTicket.isEnabled = true
                        binding.btnLoadTicket.text = "Ticket laden"
                        binding.tvError.text = "Fehler beim Laden des Tickets"
                        binding.tvError.visibility = View.VISIBLE
                    }
                }
            }
        })
    }

    private fun downloadWatermarkSync(ticket: Ticket) {
        val serverUrl = TicketStore.getServerUrl(this)
        val client = createHttpClient()
        val formBody = buildFormBody(ticket)

        val request = Request.Builder()
            .url("$serverUrl/api/watermark")
            .post(formBody)
            .build()

        try {
            val response = client.newCall(request).execute()
            if (response.isSuccessful) {
                val imgBytes = response.body?.bytes()
                if (imgBytes != null) {
                    val dir = File(filesDir, "watermarks")
                    dir.mkdirs()
                    val imgFile = File(dir, "watermark_${ticket.ticketId}.jpg")
                    FileOutputStream(imgFile).use { it.write(imgBytes) }
                    TicketStore.updateTicketWatermarkPath(this, ticket.id, imgFile.absolutePath)
                }
            }
        } catch (_: Exception) { }
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
        val tickets = TicketStore.getTickets(this)
        if (tickets.isEmpty()) {
            binding.tvNoTickets.visibility = View.VISIBLE
            binding.rvTickets.visibility = View.GONE
            binding.tvRecentTickets.visibility = View.GONE
        } else {
            binding.tvNoTickets.visibility = View.GONE
            binding.rvTickets.visibility = View.VISIBLE
            binding.tvRecentTickets.visibility = View.VISIBLE
            binding.rvTickets.adapter = TicketAdapter(tickets) { ticket ->
                val intent = Intent(this, TicketResultActivity::class.java)
                intent.putExtra("ticket_store_id", ticket.id)
                startActivity(intent)
            }
        }
    }
}

class TicketAdapter(
    private val tickets: List<Ticket>,
    private val onClick: (Ticket) -> Unit
) : RecyclerView.Adapter<TicketAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val tvTicketType: TextView = view.findViewById(R.id.tvItemTicketType)
        val tvName: TextView = view.findViewById(R.id.tvItemName)
        val tvAuftrag: TextView = view.findViewById(R.id.tvItemAuftrag)
        val tvDate: TextView = view.findViewById(R.id.tvItemDate)
        val tvPreis: TextView = view.findViewById(R.id.tvItemPreis)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_ticket, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val ticket = tickets[position]
        holder.tvTicketType.text = ticket.ticketTypeLabel
        holder.tvName.text = "${ticket.vorname} ${ticket.nachname}"
        holder.tvAuftrag.text = "Auftrag: ${ticket.auftragsnummer}"
        holder.tvDate.text = ticket.gueltigVon
        holder.tvPreis.text = ticket.preis
        holder.itemView.setOnClickListener { onClick(ticket) }
    }

    override fun getItemCount() = tickets.size
}
