package com.dbtickets.app

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

object TicketStore {

    private const val PREFS_NAME = "db_tickets"
    private const val KEY_TICKETS = "tickets_json"

    private fun prefs(context: Context): SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun getTickets(context: Context): List<Ticket> {
        val json = prefs(context).getString(KEY_TICKETS, "[]") ?: "[]"
        val arr = JSONArray(json)
        val list = mutableListOf<Ticket>()
        for (i in 0 until arr.length()) {
            val obj = arr.getJSONObject(i)
            list.add(
                Ticket(
                    orderNumber = obj.optString("orderNumber"),
                    lastName = obj.optString("lastName"),
                    ticketType = obj.optString("ticketType", "Flexpreis"),
                    from = obj.optString("from"),
                    to = obj.optString("to"),
                    departureTime = obj.optString("departureTime"),
                    arrivalTime = obj.optString("arrivalTime"),
                    travelClass = obj.optString("travelClass", "2. Klasse"),
                    date = obj.optString("date"),
                    status = obj.optString("status", "Gültig")
                )
            )
        }
        return list
    }

    fun addTicket(context: Context, ticket: Ticket) {
        val tickets = getTickets(context).toMutableList()
        tickets.add(0, ticket)
        saveTickets(context, tickets)
    }

    fun removeTicket(context: Context, orderNumber: String) {
        val tickets = getTickets(context).filter { it.orderNumber != orderNumber }
        saveTickets(context, tickets)
    }

    private fun saveTickets(context: Context, tickets: List<Ticket>) {
        val arr = JSONArray()
        for (t in tickets) {
            val obj = JSONObject()
            obj.put("orderNumber", t.orderNumber)
            obj.put("lastName", t.lastName)
            obj.put("ticketType", t.ticketType)
            obj.put("from", t.from)
            obj.put("to", t.to)
            obj.put("departureTime", t.departureTime)
            obj.put("arrivalTime", t.arrivalTime)
            obj.put("travelClass", t.travelClass)
            obj.put("date", t.date)
            obj.put("status", t.status)
            arr.put(obj)
        }
        prefs(context).edit().putString(KEY_TICKETS, arr.toString()).apply()
    }
}
