package com.dbtickets.app

import android.app.Dialog
import android.os.Bundle
import android.view.View
import android.view.Window
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageButton
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.fragment.app.Fragment
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.android.material.textfield.TextInputEditText

class MainActivity : AppCompatActivity() {

    private lateinit var toolbar: Toolbar
    private lateinit var btnToolbarAction: ImageButton
    private lateinit var bottomNav: BottomNavigationView

    private val reisenFragment = ReisenFragment()
    private val buchenFragment = BuchenFragment()
    private val profilFragment = ProfilFragment()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        toolbar = findViewById(R.id.toolbar)
        btnToolbarAction = findViewById(R.id.btnToolbarAction)
        bottomNav = findViewById(R.id.bottomNav)

        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayShowTitleEnabled(true)

        if (savedInstanceState == null) {
            switchFragment(reisenFragment, "Reisen", showAddButton = true)
        }

        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_reisen -> {
                    switchFragment(reisenFragment, "Reisen", showAddButton = true)
                    true
                }
                R.id.nav_buchen -> {
                    switchFragment(buchenFragment, "Buchen", showAddButton = false)
                    true
                }
                R.id.nav_profil -> {
                    switchFragment(profilFragment, "Profil", showAddButton = false)
                    true
                }
                else -> false
            }
        }

        btnToolbarAction.setOnClickListener {
            showAddTicketDialog()
        }
    }

    private fun switchFragment(fragment: Fragment, title: String, showAddButton: Boolean) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.fragmentContainer, fragment)
            .commit()
        supportActionBar?.title = title
        btnToolbarAction.visibility = if (showAddButton) View.VISIBLE else View.GONE
    }

    fun showAddTicketDialog() {
        val dialog = Dialog(this)
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
        dialog.setContentView(R.layout.dialog_add_ticket)
        dialog.window?.setLayout(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT
        )

        val etAuftragsnummer = dialog.findViewById<TextInputEditText>(R.id.etAuftragsnummer)
        val etNachname = dialog.findViewById<TextInputEditText>(R.id.etNachname)
        val tvError = dialog.findViewById<TextView>(R.id.tvError)
        val btnLoad = dialog.findViewById<Button>(R.id.btnLoadTicket)
        val progressBar = dialog.findViewById<ProgressBar>(R.id.progressBar)
        val btnClose = dialog.findViewById<ImageButton>(R.id.btnClose)

        btnClose.setOnClickListener { dialog.dismiss() }

        btnLoad.setOnClickListener {
            val orderNumber = etAuftragsnummer.text?.toString()?.trim() ?: ""
            val lastName = etNachname.text?.toString()?.trim() ?: ""

            if (orderNumber.isEmpty()) {
                tvError.text = "Bitte Auftragsnummer eingeben"
                tvError.visibility = View.VISIBLE
                return@setOnClickListener
            }
            if (lastName.isEmpty()) {
                tvError.text = "Bitte Nachname eingeben"
                tvError.visibility = View.VISIBLE
                return@setOnClickListener
            }

            tvError.visibility = View.GONE
            progressBar.visibility = View.VISIBLE
            btnLoad.isEnabled = false

            Thread {
                try {
                    val response = TicketApiClient.loadTicket(this, orderNumber, lastName)
                    val ticket = Ticket(
                        orderNumber = response.auftragsnummer,
                        lastName = response.nachname,
                        ticketType = response.product,
                        travelClass = response.klasse,
                        date = response.gueltigVon,
                        status = response.status,
                        ticketId = response.ticketId,
                        preis = response.preis,
                        gueltigVon = response.gueltigVon,
                        gueltigBis = response.gueltigBis
                    )

                    runOnUiThread {
                        TicketStore.addTicket(this, ticket)
                        progressBar.visibility = View.GONE
                        dialog.dismiss()
                        reisenFragment.loadTickets()
                        bottomNav.selectedItemId = R.id.nav_reisen
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        progressBar.visibility = View.GONE
                        btnLoad.isEnabled = true
                        tvError.text = "Fehler: ${e.message ?: "Verbindung fehlgeschlagen"}"
                        tvError.visibility = View.VISIBLE
                    }
                }
            }.start()
        }

        dialog.show()
    }
}
