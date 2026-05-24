package com.dbtickets.app

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.google.android.material.textfield.TextInputEditText

class ProfilFragment : Fragment() {

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        return inflater.inflate(R.layout.fragment_profil, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val etServerUrl = view.findViewById<TextInputEditText>(R.id.etServerUrl)
        val btnSave = view.findViewById<Button>(R.id.btnSaveServer)
        val tvStatus = view.findViewById<TextView>(R.id.tvServerStatus)

        val prefs = requireContext().getSharedPreferences("db_tickets", android.content.Context.MODE_PRIVATE)
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
}
