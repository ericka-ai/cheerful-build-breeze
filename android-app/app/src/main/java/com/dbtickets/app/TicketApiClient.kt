package com.dbtickets.app

import android.content.Context
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

object TicketApiClient {

    private const val API_KEY = "9f098376d138c85c13cb64fb2d006ebe34a91ca6b868cd38c62d0ab9e4abb28e"

    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    data class TicketResponse(
        val auftragsnummer: String,
        val nachname: String,
        val ticketId: String,
        val klasse: String,
        val preis: String,
        val product: String,
        val gueltigVon: String,
        val gueltigBis: String,
        val status: String
    )

    fun loadTicket(
        context: Context,
        auftragsnummer: String,
        nachname: String
    ): TicketResponse {
        val serverUrl = ServerConfig.getServerUrl(context).trimEnd('/')

        // First try to look up existing ticket by Auftragsnummer
        val lookupUrl = "$serverUrl/api/ticket/$auftragsnummer"
        val lookupRequest = Request.Builder()
            .url(lookupUrl)
            .header("X-API-Key", API_KEY)
            .get()
            .build()

        try {
            val lookupResponse = client.newCall(lookupRequest).execute()
            if (lookupResponse.isSuccessful) {
                val jsonStr = lookupResponse.body?.string() ?: ""
                if (jsonStr.isNotEmpty()) {
                    val json = JSONObject(jsonStr)
                    if (!json.has("error")) {
                        return parseResponse(json, auftragsnummer, nachname)
                    }
                }
            }
        } catch (_: Exception) { }

        // If not found, generate a new ticket
        val generateUrl = "$serverUrl/api/generate"
        val body = FormBody.Builder()
            .add("nachname", nachname)
            .add("vorname", nachname)
            .add("geburtsdatum", "01.01.1990")
            .add("order_number", auftragsnummer)
            .build()

        val request = Request.Builder()
            .url(generateUrl)
            .header("X-API-Key", API_KEY)
            .post(body)
            .build()

        val response = client.newCall(request).execute()
        if (!response.isSuccessful) {
            throw IOException("Server-Fehler: ${response.code}")
        }

        val jsonStr = response.body?.string() ?: throw IOException("Leere Antwort vom Server")
        val json = JSONObject(jsonStr)

        return parseResponse(json, auftragsnummer, nachname)
    }

    private fun parseResponse(json: JSONObject, auftragsnummer: String, nachname: String): TicketResponse {
        val productKey = json.optString("product", "")
        val productLabel = json.optString("ticket_type_label", productKey)

        return TicketResponse(
            auftragsnummer = json.optString("auftragsnummer", auftragsnummer),
            nachname = json.optString("nachname", nachname),
            ticketId = json.optString("ticket_id", ""),
            klasse = json.optString("klasse", "2") + ". Klasse",
            preis = json.optString("preis", ""),
            product = if (productLabel.isNotEmpty()) productLabel else productKey,
            gueltigVon = json.optString("gueltig_von", ""),
            gueltigBis = json.optString("gueltig_bis", ""),
            status = "Gültig"
        )
    }
}
