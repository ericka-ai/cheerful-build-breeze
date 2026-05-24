package com.dbtickets.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import java.text.SimpleDateFormat
import java.util.*

class TicketWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        for (appWidgetId in appWidgetIds) {
            updateWidget(context, appWidgetManager, appWidgetId)
        }
    }

    companion object {
        fun updateWidget(context: Context, appWidgetManager: AppWidgetManager, appWidgetId: Int) {
            val views = RemoteViews(context.packageName, R.layout.widget_ticket)
            val tickets = TicketStore.getTickets(context)

            val openIntent = Intent(context, MainActivity::class.java)
            val pendingIntent = PendingIntent.getActivity(
                context, 0, openIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetRoot, pendingIntent)

            val nextTicket = findNextTicket(tickets)
            if (nextTicket != null) {
                views.setTextViewText(R.id.widgetName, "${nextTicket.vorname} ${nextTicket.nachname}")
                views.setTextViewText(R.id.widgetType, nextTicket.ticketTypeLabel)
                views.setTextViewText(R.id.widgetDate, "${nextTicket.gueltigVon} - ${nextTicket.gueltigBis}")
                views.setTextViewText(R.id.widgetAuftrag, "Nr: ${nextTicket.auftragsnummer}")
            } else {
                views.setTextViewText(R.id.widgetName, context.getString(R.string.noch_keine_tickets))
                views.setTextViewText(R.id.widgetType, "")
                views.setTextViewText(R.id.widgetDate, "")
                views.setTextViewText(R.id.widgetAuftrag, "")
            }

            views.setTextViewText(R.id.widgetCount, "${tickets.size} Tickets")

            appWidgetManager.updateAppWidget(appWidgetId, views)
        }

        private fun findNextTicket(tickets: List<Ticket>): Ticket? {
            if (tickets.isEmpty()) return null
            val sdf = SimpleDateFormat("dd.MM.yyyy", Locale.GERMANY)
            val now = Date()
            val future = tickets.filter {
                try {
                    val end = sdf.parse(it.gueltigBis)
                    end != null && end.after(now)
                } catch (e: Exception) {
                    false
                }
            }.sortedBy {
                try { sdf.parse(it.gueltigVon)?.time ?: Long.MAX_VALUE } catch (e: Exception) { Long.MAX_VALUE }
            }
            return future.firstOrNull() ?: tickets.firstOrNull()
        }
    }
}
