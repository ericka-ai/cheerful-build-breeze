package com.dbtickets.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.View
import kotlin.math.sin

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
        drawDate(canvas, h, density)
        drawCrossHatch(canvas, h, density)
        drawMirrorNumber(canvas, w, h, density)
    }

    private fun drawWaveLines(canvas: Canvas, w: Float, h: Float, density: Float) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#DCDCDC")
            strokeWidth = 0.7f * density
            style = Paint.Style.STROKE
        }

        val path = Path()
        val amplitude = 3.5f * density
        val wavelength = 35f * density
        val spacing = 10f * density

        var lineIdx = 0f
        var y = spacing
        while (y < h) {
            path.reset()
            val phaseOffset = lineIdx * 0.3f
            path.moveTo(0f, y)
            var x = 0f
            while (x < w) {
                val step = 4f
                val nextX = x + step
                val nextY = y + amplitude * sin((2.0 * Math.PI * nextX / wavelength + phaseOffset).toFloat())
                path.lineTo(nextX, nextY)
                x = nextX
            }
            canvas.drawPath(path, paint)
            y += spacing
            lineIdx++
        }
    }

    private fun drawBackgroundText(canvas: Canvas, w: Float, h: Float, density: Float) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#D0D0D0")
            textSize = 10f * density
            typeface = Typeface.DEFAULT
        }

        val prefix = if (auftragsnummer.length >= 4) "(${auftragsnummer.substring(0, 4)})" else ""
        val textParts = listOf(
            productLabel, fullName, "Fahrkarte",
            gueltigVon, auftragsnummer, "${klasse}. Kl.",
            prefix, productLabel, fullName, "Fahrkarte",
            "${klasse}. Kl.", gueltigVon
        ).filter { it.isNotEmpty() }
        val fullText = textParts.joinToString(" ")

        val angles = floatArrayOf(-3f, 1.5f, -5f, 2.5f, -4f, 3f)

        var y = 14f * density
        var lineIndex = 0
        while (y < h + 30f * density) {
            canvas.save()
            val angle = angles[lineIndex % angles.size]
            canvas.rotate(angle, w / 2f, y)

            var x = -60f * density
            while (x < w + 120f * density) {
                canvas.drawText(fullText, x, y, paint)
                x += paint.measureText(fullText) + 12f * density
            }
            canvas.restore()
            y += 14f * density
            lineIndex++
        }
    }

    private fun drawBigNumber(canvas: Canvas, w: Float, h: Float, density: Float) {
        if (auftragsnummer.isEmpty()) return

        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#BFBFBF")
            typeface = Typeface.DEFAULT_BOLD
        }

        val numStr = auftragsnummer

        val sizePattern = floatArrayOf(58f, 85f, 48f, 50f, 90f, 42f, 42f, 42f, 52f, 40f, 50f)

        val charWidths = FloatArray(numStr.length)
        val charSizes = FloatArray(numStr.length)

        for (i in numStr.indices) {
            val patternIdx = i % sizePattern.size
            val size = sizePattern[patternIdx] * density
            charSizes[i] = size
            paint.textSize = size
            charWidths[i] = paint.measureText(numStr[i].toString())
        }

        val totalWidth = charWidths.sum()
        val availableWidth = w * 1.0f
        val scale = (availableWidth / totalWidth).coerceAtMost(1.15f)
        var x = w * 0.01f

        for (i in numStr.indices) {
            val scaledSize = charSizes[i] * scale
            paint.textSize = scaledSize
            val baselineY = h * 0.28f
            canvas.drawText(numStr[i].toString(), x, baselineY, paint)
            x += paint.measureText(numStr[i].toString())
        }
    }

    private fun drawName(canvas: Canvas, w: Float, h: Float, density: Float) {
        if (fullName.isEmpty()) return

        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#333333")
            textSize = 22f * density
            typeface = Typeface.DEFAULT_BOLD
        }

        val x = w * 0.22f
        val y = h * 0.42f

        canvas.drawText(fullName, x.coerceAtLeast(16f * density), y, paint)
    }

    private fun drawDate(canvas: Canvas, h: Float, density: Float) {
        if (day.isEmpty()) return

        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#1B1B1B")
            textSize = 38f * density
            typeface = Typeface.DEFAULT_BOLD
        }

        val dateText = "$day  $month"
        val x = 16f * density
        val y = h * 0.72f

        canvas.drawText(dateText, x, y, paint)
    }

    private fun drawCrossHatch(canvas: Canvas, h: Float, density: Float) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#AAAAAA")
            strokeWidth = 1.2f * density
            style = Paint.Style.STROKE
        }

        val centerX = 28f * density
        val centerY = h * 0.65f
        val size = 32f * density

        for (i in 0..7) {
            val offset = i * 6f * density
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
            color = Color.parseColor("#D8D8D8")
            textSize = 30f * density
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
