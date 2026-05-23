package com.dbtickets.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Rect
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.View

class WatermarkView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null, defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private var auftragsnummer: String = ""
    private var fullName: String = ""
    private var day: String = ""
    private var month: String = ""
    private var klasse: String = "2"
    private var productLabel: String = ""
    private var gueltigVon: String = ""
    private var stations: String = ""

    private val bgPaint = Paint().apply {
        color = Color.parseColor("#F0F0F0")
        style = Paint.Style.FILL
    }

    fun setTicketData(
        auftragsnummer: String,
        name: String,
        klasse: String,
        productLabel: String,
        gueltigVon: String,
    ) {
        this.auftragsnummer = auftragsnummer
        this.fullName = name
        this.klasse = klasse
        this.productLabel = productLabel
        this.gueltigVon = gueltigVon

        try {
            val parts = gueltigVon.split(".")
            if (parts.size >= 2) {
                day = parts[0]
                month = parts[1]
            }
        } catch (_: Exception) { }

        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        val density = resources.displayMetrics.density

        canvas.drawRect(0f, 0f, w, h, bgPaint)

        drawWaveLines(canvas, w, h, density)
        drawBackgroundText(canvas, w, h, density)
        drawBigNumber(canvas, w, h, density)
        drawName(canvas, w, h, density)
        drawDate(canvas, w, h, density)
        drawCrossHatch(canvas, w, h, density)
        drawMirrorNumber(canvas, w, h, density)
    }

    private fun drawWaveLines(canvas: Canvas, w: Float, h: Float, density: Float) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#DCDCDC")
            strokeWidth = 0.8f * density
            style = Paint.Style.STROKE
        }

        val path = Path()
        val amplitude = 4f * density
        val wavelength = 40f * density
        val spacing = 12f * density

        var y = spacing
        while (y < h) {
            path.reset()
            path.moveTo(0f, y)
            var x = 0f
            while (x < w) {
                path.quadTo(x + wavelength / 4f, y - amplitude, x + wavelength / 2f, y)
                path.quadTo(x + wavelength * 3f / 4f, y + amplitude, x + wavelength, y)
                x += wavelength
            }
            canvas.drawPath(path, paint)
            y += spacing
        }
    }

    private fun drawBackgroundText(canvas: Canvas, w: Float, h: Float, density: Float) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#D5D5D5")
            textSize = 11f * density
            typeface = Typeface.DEFAULT
        }

        val textParts = mutableListOf<String>()
        if (auftragsnummer.isNotEmpty()) textParts.add(auftragsnummer)
        textParts.add("${klasse}. Kl.")
        if (productLabel.isNotEmpty()) textParts.add(productLabel)
        if (fullName.isNotEmpty()) textParts.add(fullName)
        textParts.add("Fahrkarte")
        if (gueltigVon.isNotEmpty()) textParts.add(gueltigVon)
        if (auftragsnummer.isNotEmpty()) textParts.add(auftragsnummer)
        textParts.add("${klasse}. Kl.")
        if (productLabel.isNotEmpty()) textParts.add(productLabel)

        val fullText = textParts.joinToString(" ")

        var y = 18f * density
        var lineIndex = 0
        while (y < h + 30f * density) {
            canvas.save()
            val angle = when {
                lineIndex % 3 == 0 -> -4f
                lineIndex % 3 == 1 -> 2f
                else -> -6f
            }
            canvas.rotate(angle, w / 2f, y)

            var x = -50f * density
            while (x < w + 100f * density) {
                canvas.drawText(fullText, x, y, paint)
                x += paint.measureText(fullText) + 15f * density
            }
            canvas.restore()
            y += 16f * density
            lineIndex++
        }
    }

    private fun drawBigNumber(canvas: Canvas, w: Float, h: Float, density: Float) {
        if (auftragsnummer.isEmpty()) return

        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#C0C0C0")
            typeface = Typeface.DEFAULT_BOLD
        }

        val numStr = auftragsnummer
        val charCount = numStr.length

        val baseSizeLarge = 75f * density
        val baseSizeMedium = 55f * density
        val baseSizeSmall = 45f * density

        val charWidths = FloatArray(charCount)
        val charSizes = FloatArray(charCount)

        for (i in numStr.indices) {
            val size = when {
                i == 0 -> baseSizeMedium
                i == 1 -> baseSizeLarge
                i == 2 || i == 3 -> baseSizeMedium
                i == 4 -> baseSizeLarge
                i == 5 || i == 6 || i == 7 -> baseSizeSmall
                i == 8 -> baseSizeMedium
                i == 9 -> baseSizeSmall
                i == 10 -> baseSizeMedium
                else -> baseSizeSmall
            }
            charSizes[i] = size
            paint.textSize = size
            charWidths[i] = paint.measureText(numStr[i].toString())
        }

        val totalWidth = charWidths.sum()
        val availableWidth = w - 8f * density
        val scale = availableWidth / totalWidth
        var x = 4f * density

        for (i in numStr.indices) {
            val scaledSize = charSizes[i] * scale.coerceAtMost(1.2f)
            paint.textSize = scaledSize
            val actualWidth = paint.measureText(numStr[i].toString())

            val bounds = Rect()
            paint.getTextBounds(numStr[i].toString(), 0, 1, bounds)
            val baselineY = h * 0.30f

            canvas.drawText(numStr[i].toString(), x, baselineY, paint)
            x += actualWidth
        }
    }

    private fun drawName(canvas: Canvas, w: Float, h: Float, density: Float) {
        if (fullName.isEmpty()) return

        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#333333")
            textSize = 20f * density
            typeface = Typeface.DEFAULT_BOLD
        }

        val textWidth = paint.measureText(fullName)
        val x = (w - textWidth) / 2f
        val y = h * 0.45f

        canvas.drawText(fullName, x.coerceAtLeast(16f * density), y, paint)
    }

    private fun drawDate(canvas: Canvas, w: Float, h: Float, density: Float) {
        if (day.isEmpty()) return

        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#1B1B1B")
            textSize = 36f * density
            typeface = Typeface.DEFAULT_BOLD
        }

        val dateText = "$day  $month"
        val x = 16f * density
        val y = h * 0.72f

        canvas.drawText(dateText, x, y, paint)
    }

    private fun drawCrossHatch(canvas: Canvas, w: Float, h: Float, density: Float) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#AAAAAA")
            strokeWidth = 1.5f * density
            style = Paint.Style.STROKE
        }

        val centerX = 35f * density
        val centerY = h * 0.68f
        val size = 35f * density

        for (i in 0..6) {
            val offset = i * 7f * density
            canvas.drawLine(
                centerX - size + offset, centerY - size,
                centerX + offset, centerY + size,
                paint
            )
            canvas.drawLine(
                centerX - size + offset, centerY + size,
                centerX + offset, centerY - size,
                paint
            )
        }
    }

    private fun drawMirrorNumber(canvas: Canvas, w: Float, h: Float, density: Float) {
        if (auftragsnummer.isEmpty()) return

        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#DDDDDD")
            textSize = 32f * density
            typeface = Typeface.DEFAULT_BOLD
        }

        canvas.save()
        val textWidth = paint.measureText(auftragsnummer)
        val x = (w - textWidth) / 2f
        val y = h - 6f * density

        canvas.scale(1f, -1f, w / 2f, y - 16f * density)
        canvas.drawText(auftragsnummer, x, y, paint)
        canvas.restore()
    }
}
