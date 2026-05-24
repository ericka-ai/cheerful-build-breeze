package com.dbtickets.app

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.textfield.TextInputEditText
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

class BuchenFragment : Fragment() {

    private val calendar = Calendar.getInstance()
    private val dateFormat = SimpleDateFormat("dd.MM.yyyy", Locale.GERMANY)
    private val timeFormat = SimpleDateFormat("HH:mm", Locale.GERMANY)

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        return inflater.inflate(R.layout.fragment_buchen, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val etVon = view.findViewById<TextInputEditText>(R.id.etVon)
        val etNach = view.findViewById<TextInputEditText>(R.id.etNach)
        val etDatum = view.findViewById<TextInputEditText>(R.id.etDatum)
        val etUhrzeit = view.findViewById<TextInputEditText>(R.id.etUhrzeit)
        val btnSwap = view.findViewById<ImageButton>(R.id.btnSwap)
        val btnSuchen = view.findViewById<View>(R.id.btnSuchen)
        val searchProgress = view.findViewById<ProgressBar>(R.id.searchProgress)
        val resultsSection = view.findViewById<View>(R.id.searchResultsSection)
        val rvResults = view.findViewById<RecyclerView>(R.id.rvSearchResults)
        val tvResultsHeader = view.findViewById<TextView>(R.id.tvResultsHeader)

        // Set default date/time
        etDatum.setText(dateFormat.format(calendar.time))
        etUhrzeit.setText(timeFormat.format(calendar.time))

        // Date picker
        etDatum.setOnClickListener {
            DatePickerDialog(
                requireContext(),
                { _, year, month, day ->
                    calendar.set(year, month, day)
                    etDatum.setText(dateFormat.format(calendar.time))
                },
                calendar.get(Calendar.YEAR),
                calendar.get(Calendar.MONTH),
                calendar.get(Calendar.DAY_OF_MONTH)
            ).show()
        }

        // Time picker
        etUhrzeit.setOnClickListener {
            TimePickerDialog(
                requireContext(),
                { _, hour, minute ->
                    calendar.set(Calendar.HOUR_OF_DAY, hour)
                    calendar.set(Calendar.MINUTE, minute)
                    etUhrzeit.setText(timeFormat.format(calendar.time))
                },
                calendar.get(Calendar.HOUR_OF_DAY),
                calendar.get(Calendar.MINUTE),
                true
            ).show()
        }

        // Swap button
        btnSwap.setOnClickListener {
            val von = etVon.text?.toString() ?: ""
            val nach = etNach.text?.toString() ?: ""
            etVon.setText(nach)
            etNach.setText(von)
        }

        // Reisende
        view.findViewById<View>(R.id.btnReisende).setOnClickListener {
            Toast.makeText(requireContext(), "Reisende Optionen", Toast.LENGTH_SHORT).show()
        }

        // Search
        rvResults.layoutManager = LinearLayoutManager(requireContext())

        btnSuchen.setOnClickListener {
            val von = etVon.text?.toString()?.trim() ?: ""
            val nach = etNach.text?.toString()?.trim() ?: ""

            if (von.isEmpty()) {
                Toast.makeText(requireContext(), "Bitte Startbahnhof eingeben", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            if (nach.isEmpty()) {
                Toast.makeText(requireContext(), "Bitte Zielbahnhof eingeben", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            searchProgress.visibility = View.VISIBLE
            resultsSection.visibility = View.GONE

            // Simulate search results
            view.postDelayed({
                searchProgress.visibility = View.GONE
                resultsSection.visibility = View.VISIBLE
                tvResultsHeader.text = "$von → $nach"

                val results = generateMockResults(von, nach)
                rvResults.adapter = SearchResultAdapter(results)
            }, 1200)
        }
    }

    private fun generateMockResults(von: String, nach: String): List<SearchResult> {
        val results = mutableListOf<SearchResult>()
        val trains = listOf("ICE", "IC", "RE", "RB", "EC")
        val baseHour = calendar.get(Calendar.HOUR_OF_DAY)
        val baseMinute = calendar.get(Calendar.MINUTE)

        for (i in 0 until 5) {
            val depH = (baseHour + i) % 24
            val depM = (baseMinute + i * 13) % 60
            val durH = 1 + (i % 3)
            val durM = 15 + (i * 17) % 45
            val arrH = (depH + durH + (depM + durM) / 60) % 24
            val arrM = (depM + durM) % 60
            val train = trains[i % trains.size]
            val trainNum = 100 + i * 37
            val changes = i % 3
            val price = String.format("%.2f€", 19.90 + i * 12.50)

            results.add(
                SearchResult(
                    depTime = String.format("%02d:%02d", depH, depM),
                    depStation = von,
                    arrTime = String.format("%02d:%02d", arrH, arrM),
                    arrStation = nach,
                    duration = "${durH}h ${durM}min",
                    train = "$train $trainNum",
                    changes = if (changes == 0) "Direkt" else "$changes Umstiege",
                    price = "ab $price"
                )
            )
        }
        return results
    }

    data class SearchResult(
        val depTime: String,
        val depStation: String,
        val arrTime: String,
        val arrStation: String,
        val duration: String,
        val train: String,
        val changes: String,
        val price: String
    )

    inner class SearchResultAdapter(private val results: List<SearchResult>) :
        RecyclerView.Adapter<SearchResultAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvDepTime: TextView = view.findViewById(R.id.tvDepTime)
            val tvDepStation: TextView = view.findViewById(R.id.tvDepStation)
            val tvArrTime: TextView = view.findViewById(R.id.tvArrTime)
            val tvArrStation: TextView = view.findViewById(R.id.tvArrStation)
            val tvDuration: TextView = view.findViewById(R.id.tvDuration)
            val tvTrain: TextView = view.findViewById(R.id.tvTrain)
            val tvChanges: TextView = view.findViewById(R.id.tvChanges)
            val tvPrice: TextView = view.findViewById(R.id.tvPrice)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_search_result, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val r = results[position]
            holder.tvDepTime.text = r.depTime
            holder.tvDepStation.text = r.depStation
            holder.tvArrTime.text = r.arrTime
            holder.tvArrStation.text = r.arrStation
            holder.tvDuration.text = r.duration
            holder.tvTrain.text = r.train
            holder.tvChanges.text = r.changes
            holder.tvPrice.text = r.price

            holder.itemView.setOnClickListener {
                Toast.makeText(requireContext(), "${r.train}: ${r.depStation} → ${r.arrStation}", Toast.LENGTH_SHORT).show()
            }
        }

        override fun getItemCount() = results.size
    }
}
