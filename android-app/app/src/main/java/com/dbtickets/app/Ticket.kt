package com.dbtickets.app

import java.io.Serializable

data class Ticket(
    val orderNumber: String,
    val lastName: String,
    val ticketType: String = "Flexpreis",
    val from: String = "",
    val to: String = "",
    val departureTime: String = "",
    val arrivalTime: String = "",
    val travelClass: String = "2. Klasse",
    val date: String = "",
    val status: String = "Gültig"
) : Serializable
