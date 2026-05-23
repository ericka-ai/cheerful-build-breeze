package com.dbtickets.app

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.dbtickets.app.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.cardGermanRailPass.setOnClickListener {
            openTicketForm("grp_consecutive")
        }

        binding.cardEurailGlobal.setOnClickListener {
            openTicketForm("eurail_global")
        }

        binding.cardDeutschlandticket.setOnClickListener {
            openTicketForm("deutschlandticket")
        }

        binding.cardSparpreis.setOnClickListener {
            openTicketForm("sparpreis")
        }

        binding.btnSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        binding.rvTickets.layoutManager = LinearLayoutManager(this)
    }

    override fun onResume() {
        super.onResume()
        loadTicketHistory()
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

    private fun openTicketForm(ticketType: String) {
        val intent = Intent(this, TicketFormActivity::class.java)
        intent.putExtra("ticket_type", ticketType)
        startActivity(intent)
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
