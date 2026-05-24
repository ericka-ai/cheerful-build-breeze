package com.dbtickets.app

import android.content.Context

object ServerConfig {

    const val DEFAULT_URL = "https://cheerful-build-breeze-8.onrender.com"

    fun getServerUrl(context: Context): String {
        val prefs = context.getSharedPreferences("db_tickets", Context.MODE_PRIVATE)
        return prefs.getString("server_url", DEFAULT_URL) ?: DEFAULT_URL
    }
}
