package com.dbtickets.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.*

data class Ticket(
    val id: String,
    val auftragsnummer: String,
    val ticketId: String,
    val ticketType: String,
    val ticketTypeLabel: String,
    val nachname: String,
    val vorname: String,
    val geburtsdatum: String,
    val klasse: String,
    val passagierTyp: String,
    val gueltigVon: String,
    val gueltigBis: String,
    val preis: String,
    val createdAt: String,
    val product: String,
    val pdfPath: String = "",
    val barcodePath: String = "",
    val watermarkPath: String = "",
) {
    fun toJson(): JSONObject {
        val json = JSONObject()
        json.put("id", id)
        json.put("auftragsnummer", auftragsnummer)
        json.put("ticket_id", ticketId)
        json.put("ticket_type", ticketType)
        json.put("ticket_type_label", ticketTypeLabel)
        json.put("nachname", nachname)
        json.put("vorname", vorname)
        json.put("geburtsdatum", geburtsdatum)
        json.put("klasse", klasse)
        json.put("passagier_typ", passagierTyp)
        json.put("gueltig_von", gueltigVon)
        json.put("gueltig_bis", gueltigBis)
        json.put("preis", preis)
        json.put("created_at", createdAt)
        json.put("product", product)
        json.put("pdf_path", pdfPath)
        json.put("barcode_path", barcodePath)
        json.put("watermark_path", watermarkPath)
        return json
    }

    companion object {
        fun fromJson(json: JSONObject): Ticket {
            return Ticket(
                id = json.optString("id"),
                auftragsnummer = json.optString("auftragsnummer"),
                ticketId = json.optString("ticket_id"),
                ticketType = json.optString("ticket_type"),
                ticketTypeLabel = json.optString("ticket_type_label"),
                nachname = json.optString("nachname"),
                vorname = json.optString("vorname"),
                geburtsdatum = json.optString("geburtsdatum"),
                klasse = json.optString("klasse"),
                passagierTyp = json.optString("passagier_typ"),
                gueltigVon = json.optString("gueltig_von"),
                gueltigBis = json.optString("gueltig_bis"),
                preis = json.optString("preis"),
                createdAt = json.optString("created_at"),
                product = json.optString("product"),
                pdfPath = json.optString("pdf_path"),
                barcodePath = json.optString("barcode_path"),
                watermarkPath = json.optString("watermark_path"),
            )
        }
    }
}

object TicketStore {
    private const val PREFS_NAME = "db_tickets_store"
    private const val KEY_TICKETS = "tickets"

    fun generateAuftragsnummer(): String {
        val random = Random()
        return (1_000_000_000_000L + (random.nextDouble() * 8_999_999_999_999L).toLong()).toString()
    }

    fun generateTicketId(): String {
        val random = Random()
        return (1_000_000 + random.nextInt(8_999_999)).toString()
    }

    fun saveTicket(context: Context, ticket: Ticket) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val ticketsJson = prefs.getString(KEY_TICKETS, "[]") ?: "[]"
        val array = JSONArray(ticketsJson)
        array.put(ticket.toJson())
        prefs.edit().putString(KEY_TICKETS, array.toString()).apply()
    }

    fun getTickets(context: Context): List<Ticket> {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val ticketsJson = prefs.getString(KEY_TICKETS, "[]") ?: "[]"
        val array = JSONArray(ticketsJson)
        val tickets = mutableListOf<Ticket>()
        for (i in 0 until array.length()) {
            tickets.add(Ticket.fromJson(array.getJSONObject(i)))
        }
        return tickets.reversed()
    }

    fun getTicketById(context: Context, id: String): Ticket? {
        return getTickets(context).find { it.id == id }
    }

    fun getTicketByAuftragsnummer(context: Context, auftragsnummer: String): Ticket? {
        return getTickets(context).find { it.auftragsnummer == auftragsnummer }
    }

    fun updateTicketPdfPath(context: Context, ticketId: String, pdfPath: String) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val ticketsJson = prefs.getString(KEY_TICKETS, "[]") ?: "[]"
        val array = JSONArray(ticketsJson)
        val newArray = JSONArray()
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            if (obj.optString("id") == ticketId) {
                obj.put("pdf_path", pdfPath)
            }
            newArray.put(obj)
        }
        prefs.edit().putString(KEY_TICKETS, newArray.toString()).apply()
    }

    fun updateTicketBarcodePath(context: Context, ticketId: String, barcodePath: String) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val ticketsJson = prefs.getString(KEY_TICKETS, "[]") ?: "[]"
        val array = JSONArray(ticketsJson)
        val newArray = JSONArray()
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            if (obj.optString("id") == ticketId) {
                obj.put("barcode_path", barcodePath)
            }
            newArray.put(obj)
        }
        prefs.edit().putString(KEY_TICKETS, newArray.toString()).apply()
    }

    fun updateTicketWatermarkPath(context: Context, ticketId: String, watermarkPath: String) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val ticketsJson = prefs.getString(KEY_TICKETS, "[]") ?: "[]"
        val array = JSONArray(ticketsJson)
        val newArray = JSONArray()
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            if (obj.optString("id") == ticketId) {
                obj.put("watermark_path", watermarkPath)
            }
            newArray.put(obj)
        }
        prefs.edit().putString(KEY_TICKETS, newArray.toString()).apply()
    }

    fun getDefaultServerUrl(): String {
        return "https://cheerful-build-breeze-8.onrender.com"
    }

    fun getServerUrl(context: Context): String {
        val prefs = context.getSharedPreferences("db_tickets", Context.MODE_PRIVATE)
        val url = prefs.getString("server_url", "") ?: ""
        return url.ifEmpty { getDefaultServerUrl() }
    }

    fun getPriceForProduct(product: String, days: Int, klasse: String, passagierTyp: String): String {
        val pricesGrpConsecutive = mapOf(
            3 to mapOf(("2" to "ERWACHSENER") to "191,00\u20ac", ("2" to "JUGENDLICHER") to "153,00\u20ac",
                ("1" to "ERWACHSENER") to "255,00\u20ac", ("1" to "JUGENDLICHER") to "204,00\u20ac"),
            4 to mapOf(("2" to "ERWACHSENER") to "218,00\u20ac", ("2" to "JUGENDLICHER") to "174,00\u20ac",
                ("1" to "ERWACHSENER") to "290,00\u20ac", ("1" to "JUGENDLICHER") to "232,00\u20ac"),
            5 to mapOf(("2" to "ERWACHSENER") to "240,00\u20ac", ("2" to "JUGENDLICHER") to "192,00\u20ac",
                ("1" to "ERWACHSENER") to "320,00\u20ac", ("1" to "JUGENDLICHER") to "256,00\u20ac"),
            7 to mapOf(("2" to "ERWACHSENER") to "279,00\u20ac", ("2" to "JUGENDLICHER") to "223,00\u20ac",
                ("1" to "ERWACHSENER") to "372,00\u20ac", ("1" to "JUGENDLICHER") to "298,00\u20ac"),
            10 to mapOf(("2" to "ERWACHSENER") to "367,00\u20ac", ("2" to "JUGENDLICHER") to "294,00\u20ac",
                ("1" to "ERWACHSENER") to "490,00\u20ac", ("1" to "JUGENDLICHER") to "392,00\u20ac"),
            15 to mapOf(("2" to "ERWACHSENER") to "452,00\u20ac", ("2" to "JUGENDLICHER") to "362,00\u20ac",
                ("1" to "ERWACHSENER") to "603,00\u20ac", ("1" to "JUGENDLICHER") to "482,00\u20ac"),
        )

        val pricesGrpFlexi = mapOf(
            3 to mapOf(("2" to "ERWACHSENER") to "192,00\u20ac", ("2" to "JUGENDLICHER") to "154,00\u20ac",
                ("1" to "ERWACHSENER") to "256,00\u20ac", ("1" to "JUGENDLICHER") to "205,00\u20ac"),
            4 to mapOf(("2" to "ERWACHSENER") to "222,00\u20ac", ("2" to "JUGENDLICHER") to "178,00\u20ac",
                ("1" to "ERWACHSENER") to "296,00\u20ac", ("1" to "JUGENDLICHER") to "237,00\u20ac"),
            5 to mapOf(("2" to "ERWACHSENER") to "246,00\u20ac", ("2" to "JUGENDLICHER") to "197,00\u20ac",
                ("1" to "ERWACHSENER") to "328,00\u20ac", ("1" to "JUGENDLICHER") to "262,00\u20ac"),
            7 to mapOf(("2" to "ERWACHSENER") to "292,00\u20ac", ("2" to "JUGENDLICHER") to "234,00\u20ac",
                ("1" to "ERWACHSENER") to "389,00\u20ac", ("1" to "JUGENDLICHER") to "311,00\u20ac"),
            10 to mapOf(("2" to "ERWACHSENER") to "392,00\u20ac", ("2" to "JUGENDLICHER") to "314,00\u20ac",
                ("1" to "ERWACHSENER") to "523,00\u20ac", ("1" to "JUGENDLICHER") to "418,00\u20ac"),
            15 to mapOf(("2" to "ERWACHSENER") to "486,00\u20ac", ("2" to "JUGENDLICHER") to "389,00\u20ac",
                ("1" to "ERWACHSENER") to "648,00\u20ac", ("1" to "JUGENDLICHER") to "518,00\u20ac"),
        )

        val pricesEurail = mapOf(
            4 to mapOf(("2" to "ERWACHSENER") to "261,00\u20ac", ("2" to "JUGENDLICHER") to "209,00\u20ac",
                ("1" to "ERWACHSENER") to "348,00\u20ac", ("1" to "JUGENDLICHER") to "278,00\u20ac"),
            5 to mapOf(("2" to "ERWACHSENER") to "296,00\u20ac", ("2" to "JUGENDLICHER") to "237,00\u20ac",
                ("1" to "ERWACHSENER") to "395,00\u20ac", ("1" to "JUGENDLICHER") to "316,00\u20ac"),
            7 to mapOf(("2" to "ERWACHSENER") to "349,00\u20ac", ("2" to "JUGENDLICHER") to "279,00\u20ac",
                ("1" to "ERWACHSENER") to "465,00\u20ac", ("1" to "JUGENDLICHER") to "372,00\u20ac"),
            10 to mapOf(("2" to "ERWACHSENER") to "415,00\u20ac", ("2" to "JUGENDLICHER") to "332,00\u20ac",
                ("1" to "ERWACHSENER") to "553,00\u20ac", ("1" to "JUGENDLICHER") to "442,00\u20ac"),
            15 to mapOf(("2" to "ERWACHSENER") to "489,00\u20ac", ("2" to "JUGENDLICHER") to "391,00\u20ac",
                ("1" to "ERWACHSENER") to "652,00\u20ac", ("1" to "JUGENDLICHER") to "522,00\u20ac"),
            22 to mapOf(("2" to "ERWACHSENER") to "448,00\u20ac", ("2" to "JUGENDLICHER") to "358,00\u20ac",
                ("1" to "ERWACHSENER") to "597,00\u20ac", ("1" to "JUGENDLICHER") to "478,00\u20ac"),
            31 to mapOf(("2" to "ERWACHSENER") to "560,00\u20ac", ("2" to "JUGENDLICHER") to "448,00\u20ac",
                ("1" to "ERWACHSENER") to "747,00\u20ac", ("1" to "JUGENDLICHER") to "597,00\u20ac"),
        )

        val table = when (product) {
            "grp_consecutive" -> pricesGrpConsecutive
            "grp_flexi" -> pricesGrpFlexi
            "eurail_global" -> pricesEurail
            "deutschlandticket" -> return "63,00\u20ac"
            else -> return ""
        }

        val dayPrices = table[days] ?: table.values.firstOrNull() ?: return ""
        return dayPrices[klasse to passagierTyp] ?: ""
    }

    fun getProductLabel(product: String): String {
        return when (product) {
            "grp_consecutive" -> "German Rail Pass (Konsekutiv)"
            "grp_flexi" -> "German Rail Pass (Flexi)"
            "eurail_global" -> "Eurail Global Pass"
            "deutschlandticket" -> "Deutschlandticket"
            "sparpreis", "db_sparpreis" -> "DB Sparpreis"
            else -> product
        }
    }

    fun nowFormatted(): String {
        return SimpleDateFormat("dd.MM.yyyy HH:mm", Locale.GERMANY).format(Date())
    }
}
