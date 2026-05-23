package com.dbtickets.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat

class TicketExpiryReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val ticketId = intent.getStringExtra("ticket_id") ?: return
        val ticketName = intent.getStringExtra("ticket_name") ?: "Ticket"
        val expiryDate = intent.getStringExtra("expiry_date") ?: ""

        val channelId = "ticket_expiry"
        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Ticket-Erinnerungen",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Erinnerungen wenn Tickets bald ablaufen"
            }
            notificationManager.createNotificationChannel(channel)
        }

        val openIntent = Intent(context, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            context, ticketId.hashCode(), openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Ticket l\u00e4uft bald ab")
            .setContentText("$ticketName l\u00e4uft am $expiryDate ab")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()

        notificationManager.notify(ticketId.hashCode(), notification)
    }

    companion object {
        fun scheduleReminder(context: Context, ticket: Ticket) {
            try {
                val sdf = java.text.SimpleDateFormat("dd.MM.yyyy", java.util.Locale.GERMANY)
                val expiryDate = sdf.parse(ticket.gueltigBis) ?: return
                val cal = java.util.Calendar.getInstance()
                cal.time = expiryDate
                cal.add(java.util.Calendar.DAY_OF_MONTH, -1)
                cal.set(java.util.Calendar.HOUR_OF_DAY, 9)
                cal.set(java.util.Calendar.MINUTE, 0)

                if (cal.timeInMillis <= System.currentTimeMillis()) return

                val intent = Intent(context, TicketExpiryReceiver::class.java).apply {
                    putExtra("ticket_id", ticket.ticketId)
                    putExtra("ticket_name", "${ticket.vorname} ${ticket.nachname} - ${ticket.ticketTypeLabel}")
                    putExtra("expiry_date", ticket.gueltigBis)
                }

                val pendingIntent = PendingIntent.getBroadcast(
                    context, ticket.ticketId.hashCode(), intent,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )

                val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as android.app.AlarmManager
                alarmManager.set(android.app.AlarmManager.RTC_WAKEUP, cal.timeInMillis, pendingIntent)
            } catch (_: Exception) { }
        }
    }
}
