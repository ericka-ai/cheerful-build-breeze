package com.dbtickets.app

import android.app.Dialog
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageButton
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.google.android.material.textfield.TextInputEditText

class ProfilFragment : Fragment() {

    private var isLoggedIn = false
    private var loggedInName = ""

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        return inflater.inflate(R.layout.fragment_profil, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val prefs = requireContext().getSharedPreferences("db_tickets", android.content.Context.MODE_PRIVATE)

        // Load login state
        isLoggedIn = prefs.getBoolean("is_logged_in", false)
        loggedInName = prefs.getString("logged_in_name", "") ?: ""

        updateLoginUI(view)

        // Login button
        view.findViewById<Button>(R.id.btnLogin).setOnClickListener {
            showLoginDialog()
        }

        // Logout button
        view.findViewById<Button>(R.id.btnLogout).setOnClickListener {
            prefs.edit()
                .putBoolean("is_logged_in", false)
                .putString("logged_in_name", "")
                .apply()
            isLoggedIn = false
            loggedInName = ""
            updateLoginUI(view)
            Toast.makeText(requireContext(), "Abgemeldet", Toast.LENGTH_SHORT).show()
        }

        // Settings click handlers
        view.findViewById<View>(R.id.btnBahnCard).setOnClickListener {
            Toast.makeText(requireContext(), "BahnCard Verwaltung", Toast.LENGTH_SHORT).show()
        }
        view.findViewById<View>(R.id.btnBahnBonus).setOnClickListener {
            Toast.makeText(requireContext(), "BahnBonus", Toast.LENGTH_SHORT).show()
        }
        view.findViewById<View>(R.id.btnPersoenlicheDaten).setOnClickListener {
            Toast.makeText(requireContext(), "Persönliche Daten", Toast.LENGTH_SHORT).show()
        }
        view.findViewById<View>(R.id.btnZahlungsmittel).setOnClickListener {
            Toast.makeText(requireContext(), "Zahlungsmittel", Toast.LENGTH_SHORT).show()
        }
        view.findViewById<View>(R.id.btnEinstellungen).setOnClickListener {
            Toast.makeText(requireContext(), "Einstellungen", Toast.LENGTH_SHORT).show()
        }

        // Rechtliches
        view.findViewById<View>(R.id.btnDatenschutz).setOnClickListener {
            Toast.makeText(requireContext(), "Datenschutz", Toast.LENGTH_SHORT).show()
        }
        view.findViewById<View>(R.id.btnImpressum).setOnClickListener {
            Toast.makeText(requireContext(), "Impressum", Toast.LENGTH_SHORT).show()
        }
        view.findViewById<View>(R.id.btnNutzungsbedingungen).setOnClickListener {
            Toast.makeText(requireContext(), "Nutzungsbedingungen", Toast.LENGTH_SHORT).show()
        }

        // Server URL settings
        val etServerUrl = view.findViewById<TextInputEditText>(R.id.etServerUrl)
        val btnSave = view.findViewById<Button>(R.id.btnSaveServer)
        val tvStatus = view.findViewById<TextView>(R.id.tvServerStatus)

        val savedUrl = prefs.getString("server_url", ServerConfig.DEFAULT_URL) ?: ServerConfig.DEFAULT_URL
        etServerUrl.setText(savedUrl)

        btnSave.setOnClickListener {
            val url = etServerUrl.text?.toString()?.trim() ?: ""
            if (url.isEmpty()) {
                tvStatus.text = "Bitte Server-URL eingeben"
                tvStatus.setTextColor(resources.getColor(R.color.dbRed, null))
                tvStatus.visibility = View.VISIBLE
                return@setOnClickListener
            }
            prefs.edit().putString("server_url", url).apply()
            tvStatus.text = "Server-URL gespeichert"
            tvStatus.setTextColor(resources.getColor(R.color.dbCoolGray500, null))
            tvStatus.visibility = View.VISIBLE
            Toast.makeText(requireContext(), "Server-URL gespeichert", Toast.LENGTH_SHORT).show()
        }
    }

    private fun updateLoginUI(view: View) {
        val tvTitle = view.findViewById<TextView>(R.id.tvProfileTitle)
        val tvStatus = view.findViewById<TextView>(R.id.tvProfileStatus)
        val btnLogin = view.findViewById<Button>(R.id.btnLogin)
        val btnLogout = view.findViewById<Button>(R.id.btnLogout)

        if (isLoggedIn) {
            tvTitle.text = loggedInName
            tvStatus.text = "Angemeldet"
            tvStatus.setTextColor(resources.getColor(android.R.color.holo_green_dark, null))
            btnLogin.visibility = View.GONE
            btnLogout.visibility = View.VISIBLE
        } else {
            tvTitle.text = "Mein Profil"
            tvStatus.text = "Nicht angemeldet"
            tvStatus.setTextColor(resources.getColor(R.color.dbCoolGray500, null))
            btnLogin.visibility = View.VISIBLE
            btnLogout.visibility = View.GONE
        }
    }

    private fun showLoginDialog() {
        val dialog = Dialog(requireContext())
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
        dialog.setContentView(R.layout.dialog_login)
        dialog.window?.setLayout(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT
        )

        val etEmail = dialog.findViewById<TextInputEditText>(R.id.etLoginEmail)
        val etPassword = dialog.findViewById<TextInputEditText>(R.id.etLoginPassword)
        val tvError = dialog.findViewById<TextView>(R.id.tvLoginError)
        val btnDoLogin = dialog.findViewById<Button>(R.id.btnDoLogin)
        val btnClose = dialog.findViewById<ImageButton>(R.id.btnCloseLogin)
        val progress = dialog.findViewById<ProgressBar>(R.id.loginProgress)
        val btnRegister = dialog.findViewById<Button>(R.id.btnRegister)

        btnClose.setOnClickListener { dialog.dismiss() }

        btnDoLogin.setOnClickListener {
            val email = etEmail.text?.toString()?.trim() ?: ""
            val password = etPassword.text?.toString()?.trim() ?: ""

            if (email.isEmpty()) {
                tvError.text = "Bitte E-Mail oder Benutzername eingeben"
                tvError.visibility = View.VISIBLE
                return@setOnClickListener
            }
            if (password.isEmpty()) {
                tvError.text = "Bitte Passwort eingeben"
                tvError.visibility = View.VISIBLE
                return@setOnClickListener
            }

            tvError.visibility = View.GONE
            progress.visibility = View.VISIBLE
            btnDoLogin.isEnabled = false

            // Simulate login
            view?.postDelayed({
                progress.visibility = View.GONE
                val prefs = requireContext().getSharedPreferences("db_tickets", android.content.Context.MODE_PRIVATE)
                val displayName = email.substringBefore("@").replaceFirstChar { it.uppercase() }
                prefs.edit()
                    .putBoolean("is_logged_in", true)
                    .putString("logged_in_name", displayName)
                    .apply()
                isLoggedIn = true
                loggedInName = displayName
                view?.let { updateLoginUI(it) }
                dialog.dismiss()
                Toast.makeText(requireContext(), "Angemeldet als $displayName", Toast.LENGTH_SHORT).show()
            }, 1500)
        }

        btnRegister.setOnClickListener {
            Toast.makeText(requireContext(), "Registrierung kommt bald", Toast.LENGTH_SHORT).show()
        }

        dialog.show()
    }
}
