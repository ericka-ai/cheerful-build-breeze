package com.dbtickets.app

import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar

class TicketDisplayActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_ticket_display)

        val ticket = intent.getSerializableExtra("ticket") as? Ticket ?: run {
            finish()
            return
        }

        val toolbar = findViewById<Toolbar>(R.id.toolbar)
        toolbar.title = ticket.ticketType
        toolbar.setNavigationOnClickListener { finish() }

        findViewById<TextView>(R.id.tvOrderNumber).text = ticket.orderNumber
        findViewById<TextView>(R.id.tvTicketName).text = ticket.ticketType
        findViewById<TextView>(R.id.tvValidity).text = "Gültig am ${ticket.date}"
        findViewById<TextView>(R.id.tvPassengerName).text = ticket.lastName
        findViewById<TextView>(R.id.tvClass).text = ticket.travelClass

        if (ticket.from.isNotEmpty() && ticket.to.isNotEmpty()) {
            findViewById<android.view.View>(R.id.routeSection).visibility = android.view.View.VISIBLE
            findViewById<TextView>(R.id.tvFrom).text = ticket.from
            findViewById<TextView>(R.id.tvTo).text = ticket.to
            findViewById<TextView>(R.id.tvDepartureTime).text = ticket.departureTime
            findViewById<TextView>(R.id.tvArrivalTime).text = ticket.arrivalTime
        }

        val ivBarcode = findViewById<ImageView>(R.id.ivBarcode)
        ivBarcode.setImageBitmap(generateBarcode(ticket.orderNumber))

        findViewById<android.widget.Button>(R.id.btnDelete).setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Auftrag löschen")
                .setMessage("Möchten Sie den Auftrag ${ticket.orderNumber} wirklich löschen?")
                .setPositiveButton("Löschen") { _, _ ->
                    TicketStore.removeTicket(this, ticket.orderNumber)
                    Toast.makeText(this, "Auftrag gelöscht", Toast.LENGTH_SHORT).show()
                    finish()
                }
                .setNegativeButton("Abbrechen", null)
                .show()
        }
    }

    private fun generateBarcode(data: String): Bitmap {
        val size = 200
        val bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val hash = data.hashCode()
        val rng = java.util.Random(hash.toLong())
        for (x in 0 until size) {
            for (y in 0 until size) {
                val blockX = x / 4
                val blockY = y / 4
                val seed = blockX * 51 + blockY * 37 + hash
                bitmap.setPixel(x, y, if (java.util.Random(seed.toLong()).nextBoolean()) Color.BLACK else Color.WHITE)
            }
        }
        // Add finder patterns (like QR code corners)
        for (i in 0 until 28) {
            for (j in 0 until 28) {
                val isEdge = i < 4 || j < 4 || i >= 24 || j >= 24
                val color = if (isEdge) Color.BLACK else if (i < 8 || j < 8 || i >= 20 || j >= 20) Color.WHITE else Color.BLACK
                bitmap.setPixel(i, j, color)
                bitmap.setPixel(size - 1 - i, j, color)
                bitmap.setPixel(i, size - 1 - j, color)
            }
        }
        return bitmap
    }
}
