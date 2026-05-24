package com.dbtickets.app

import android.content.Context
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

object TicketApiClient {

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
        val url = "$serverUrl/api/generate"

        val body = FormBody.Builder()
            .add("auftragsnummer", auftragsnummer)
            .add("nachname", nachname)
            .build()

        val request = Request.Builder()
            .url(url)
            .post(body)
            .build()

        val response = client.newCall(request).execute()
        if (!response.isSuccessful) {
            throw IOException("Server-Fehler: ${response.code}")
        }

        val jsonStr = response.body?.string() ?: throw IOException("Leere Antwort vom Server")
        val json = JSONObject(jsonStr)

        return TicketResponse(
            auftragsnummer = json.optString("auftragsnummer", auftragsnummer),
            nachname = json.optString("nachname", nachname),
            ticketId = json.optString("ticket_id", ""),
            klasse = json.optString("klasse", "2. Klasse"),
            preis = json.optString("preis", ""),
            product = json.optString("product", ""),
            gueltigVon = json.optString("gueltig_von", ""),
            gueltigBis = json.optString("gueltig_bis", ""),
            status = json.optString("status", "Gültig")
        )
    }
}
