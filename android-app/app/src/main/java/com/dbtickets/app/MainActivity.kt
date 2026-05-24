package com.dbtickets.app

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView

class MainActivity : AppCompatActivity() {

    private lateinit var rvLayouts: RecyclerView
    private lateinit var etSearch: android.widget.EditText
    private lateinit var tvCount: TextView
    private var allLayouts: List<LayoutEntry> = emptyList()

    data class LayoutEntry(val name: String, val resId: Int, val type: String)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        rvLayouts = findViewById(R.id.rvLayouts)
        etSearch = findViewById(R.id.etSearch)
        tvCount = findViewById(R.id.tvCount)

        allLayouts = collectLayouts()
        rvLayouts.layoutManager = LinearLayoutManager(this)
        rvLayouts.adapter = LayoutAdapter(allLayouts)
        tvCount.text = "${allLayouts.size} Layouts"

        etSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val query = s?.toString()?.lowercase() ?: ""
                val filtered = if (query.isEmpty()) allLayouts
                    else allLayouts.filter { it.name.lowercase().contains(query) }
                rvLayouts.adapter = LayoutAdapter(filtered)
                tvCount.text = "${filtered.size} Layouts"
            }
        })
    }

    private fun collectLayouts(): List<LayoutEntry> {
        val layouts = mutableListOf<LayoutEntry>()
        val fields = R.layout::class.java.fields
        for (field in fields) {
            val name = field.name
            if (name == "activity_main" || name == "item_layout_entry" || name == "activity_layout_viewer") continue
            val resId = field.getInt(null)
            val type = when {
                name.startsWith("activity_") -> "Activity"
                name.startsWith("fragment_") -> "Fragment"
                name.startsWith("item_") || name.endsWith("_item") || name.endsWith("_list_item") -> "List Item"
                name.startsWith("dialog_") -> "Dialog"
                name.startsWith("widget_") -> "Widget"
                name.contains("toolbar") || name.contains("header") -> "Toolbar/Header"
                name.contains("bottom_sheet") -> "Bottom Sheet"
                else -> "Layout"
            }
            layouts.add(LayoutEntry(name, resId, type))
        }
        return layouts.sortedBy { it.name }
    }

    inner class LayoutAdapter(private val items: List<LayoutEntry>) :
        RecyclerView.Adapter<LayoutAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvName: TextView = view.findViewById(R.id.tvLayoutName)
            val tvType: TextView = view.findViewById(R.id.tvLayoutType)
            val colorIndicator: View = view.findViewById(R.id.colorIndicator)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_layout_entry, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val entry = items[position]
            holder.tvName.text = entry.name.replace("_", " ")
            holder.tvType.text = entry.type

            val colorRes = when (entry.type) {
                "Activity" -> android.R.color.holo_red_dark
                "Fragment" -> android.R.color.holo_blue_dark
                "List Item" -> android.R.color.holo_green_dark
                "Dialog" -> android.R.color.holo_orange_dark
                "Bottom Sheet" -> android.R.color.holo_purple
                else -> android.R.color.darker_gray
            }
            holder.colorIndicator.setBackgroundResource(colorRes)

            holder.itemView.setOnClickListener {
                val intent = Intent(this@MainActivity, LayoutViewerActivity::class.java)
                intent.putExtra("layout_name", entry.name)
                intent.putExtra("layout_res_id", entry.resId)
                startActivity(intent)
            }
        }

        override fun getItemCount() = items.size
    }
}
