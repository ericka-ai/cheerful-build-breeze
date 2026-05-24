package com.dbtickets.app

import okhttp3.Interceptor
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

object ApiClient {

    private const val API_KEY = "9f098376d138c85c13cb64fb2d006ebe34a91ca6b868cd38c62d0ab9e4abb28e"

    private val apiKeyInterceptor = Interceptor { chain ->
        val request = chain.request().newBuilder()
            .addHeader("X-API-Key", API_KEY)
            .build()
        chain.proceed(request)
    }

    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(60, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .addInterceptor(apiKeyInterceptor)
        .build()

    val lookupClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .addInterceptor(apiKeyInterceptor)
        .build()
}
