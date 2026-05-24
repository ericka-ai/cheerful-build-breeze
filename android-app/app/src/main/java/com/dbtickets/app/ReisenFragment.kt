package com.dbtickets.app

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView

class ReisenFragment : Fragment() {

    private lateinit var rvTickets: RecyclerView
    private lateinit var emptyState: View

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        return inflater.inflate(R.layout.fragment_reisen, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        rvTickets = view.findViewById(R.id.rvTickets)
        emptyState = view.findViewById(R.id.emptyState)

        rvTickets.layoutManager = LinearLayoutManager(requireContext())

        view.findViewById<View>(R.id.fabAdd).setOnClickListener {
            (activity as? MainActivity)?.showAddTicketDialog()
        }

        view.findViewById<View>(R.id.swipeRefresh)?.let {
            (it as? androidx.swiperefreshlayout.widget.SwipeRefreshLayout)?.apply {
                setColorSchemeResources(android.R.color.holo_red_dark)
                setOnRefreshListener {
                    loadTickets()
                    isRefreshing = false
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        loadTickets()
    }

    fun loadTickets() {
        val tickets = TicketStore.getTickets(requireContext())
        if (tickets.isEmpty()) {
            emptyState.visibility = View.VISIBLE
            rvTickets.visibility = View.GONE
        } else {
            emptyState.visibility = View.GONE
            rvTickets.visibility = View.VISIBLE
            rvTickets.adapter = TicketAdapter(tickets)
        }
    }

    inner class TicketAdapter(private val tickets: List<Ticket>) :
        RecyclerView.Adapter<TicketAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvTicketType: TextView = view.findViewById(R.id.tvTicketType)
            val tvPassenger: TextView = view.findViewById(R.id.tvPassenger)
            val tvRoute: TextView = view.findViewById(R.id.tvRoute)
            val tvOrderNumber: TextView = view.findViewById(R.id.tvOrderNumber)
            val tvDate: TextView = view.findViewById(R.id.tvDate)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_ticket_card, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val ticket = tickets[position]
            holder.tvTicketType.text = ticket.ticketType
            holder.tvPassenger.text = ticket.lastName
            holder.tvRoute.text = when {
                ticket.from.isNotEmpty() && ticket.to.isNotEmpty() ->
                    "${ticket.from} → ${ticket.to}"
                ticket.gueltigVon.isNotEmpty() && ticket.gueltigBis.isNotEmpty() ->
                    "${ticket.gueltigVon} – ${ticket.gueltigBis}"
                ticket.preis.isNotEmpty() -> ticket.preis
                else -> ""
            }
            holder.tvOrderNumber.text = "Nr. ${ticket.orderNumber}"
            holder.tvDate.text = if (ticket.date.isNotEmpty()) ticket.date
                else ticket.gueltigVon

            holder.itemView.setOnClickListener {
                val intent = Intent(requireContext(), TicketDisplayActivity::class.java)
                intent.putExtra("ticket", ticket)
                startActivity(intent)
            }
        }

        override fun getItemCount() = tickets.size
    }
}
