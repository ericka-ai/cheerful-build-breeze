package com.dbtickets.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.View

class WatermarkView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null, defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private var auftragsnummer: String = ""
    private var name: String = ""
    private var day: String = ""
    private var month: String = ""
    private var klasse: String = "2"
    private var productLabel: String = ""
    private var gueltigVon: String = ""

    private val bgPaint = Paint().apply {
        color = Color.parseColor("#F0F0F0")
        style = Paint.Style.FILL
    }

    private val bigNumPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#C8C8C8")
        textSize = 52f
        typeface = Typeface.DEFAULT_BOLD
    }

    private val namePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#333333")
        textSize = 38f
        typeface = Typeface.DEFAULT_BOLD
    }

    private val datePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#BBBBBB")
        textSize = 56f
        typeface = Typeface.DEFAULT_BOLD
    }

    private val watermarkTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#E0E0E0")
        textSize = 16f
        typeface = Typeface.DEFAULT
    }

    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#D8D8D8")
        strokeWidth = 1.5f
        style = Paint.Style.STROKE
    }

    private val mirrorNumPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#E8E8E8")
        textSize = 36f
        typeface = Typeface.DEFAULT_BOLD
    }

    fun setTicketData(
        auftragsnummer: String,
        name: String,
        klasse: String,
        productLabel: String,
        gueltigVon: String,
    ) {
        this.auftragsnummer = auftragsnummer
        this.name = name
        this.klasse = klasse
        this.productLabel = productLabel
        this.gueltigVon = gueltigVon

        try {
            val parts = gueltigVon.split(".")
            if (parts.size >= 2) {
                day = parts[0]
                month = parts[1]
            }
        } catch (e: Exception) { }

        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()

        canvas.drawRect(0f, 0f, w, h, bgPaint)

        drawWaveLines(canvas, w, h)
        drawBackgroundText(canvas, w, h)
        drawBigNumber(canvas, w)
        drawName(canvas, w, h)
        drawDate(canvas, h)
        drawCrossHatch(canvas, h)
        drawMirrorNumber(canvas, w, h)
    }

    private fun drawWaveLines(canvas: Canvas, w: Float, h: Float) {
        val path = Path()
        var y = 30f
        while (y < h) {
            path.reset()
            path.moveTo(0f, y)
            var x = 0f
            while (x < w) {
                path.quadTo(x + 20f, y - 8f, x + 40f, y)
                path.quadTo(x + 60f, y + 8f, x + 80f, y)
                x += 80f
            }
            canvas.drawPath(path, linePaint)
            y += 25f
        }
    }

    private fun drawBackgroundText(canvas: Canvas, w: Float, h: Float) {
        val items = listOf(
            auftragsnummer, "${klasse}. Kl.", productLabel,
            name, "Fahrkarte", gueltigVon
        )
        val text = items.joinToString(" ")

        canvas.save()
        var y = 40f
        var angle = -5f
        while (y < h - 20f) {
            canvas.save()
            canvas.rotate(angle, w / 2f, y)
            var x = -20f
            while (x < w + 50f) {
                canvas.drawText(text, x, y, watermarkTextPaint)
                x += watermarkTextPaint.measureText(text) + 20f
            }
            canvas.restore()
            y += 30f
            angle = if (angle < 0) 3f else -5f
        }
        canvas.restore()
    }

    private fun drawBigNumber(canvas: Canvas, w: Float) {
        if (auftragsnummer.isEmpty()) return

        val density = resources.displayMetrics.density
        bigNumPaint.textSize = 42f * density

        val totalWidth = bigNumPaint.measureText(auftragsnummer)
        val startX = (w - totalWidth) / 2f
        val y = 55f * density

        for (i in auftragsnummer.indices) {
            val ch = auftragsnummer[i].toString()
            val size = when {
                i % 4 == 0 -> 48f * density
                i % 4 == 2 -> 38f * density
                else -> 42f * density
            }
            bigNumPaint.textSize = size
            val xOffset = bigNumPaint.measureText(auftragsnummer.substring(0, i))
            canvas.drawText(ch, startX + xOffset, y, bigNumPaint)
        }
    }

    private fun drawName(canvas: Canvas, w: Float, h: Float) {
        if (name.isEmpty()) return

        val density = resources.displayMetrics.density
        namePaint.textSize = 22f * density

        val textWidth = namePaint.measureText(name)
        val x = (w - textWidth) / 2f
        val y = h * 0.48f

        canvas.drawText(name, x, y, namePaint)
    }

    private fun drawDate(canvas: Canvas, h: Float) {
        if (day.isEmpty()) return

        val density = resources.displayMetrics.density
        datePaint.textSize = 40f * density

        val x = 20f * density
        val y = h * 0.78f

        canvas.drawText("$day  $month", x, y, datePaint)
    }

    private fun drawCrossHatch(canvas: Canvas, h: Float) {
        val density = resources.displayMetrics.density
        val hatchPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.parseColor("#CCCCCC")
            strokeWidth = 1.5f * density
            style = Paint.Style.STROKE
        }

        val size = 60f * density
        val startX = 10f * density
        val startY = h * 0.55f

        for (i in 0..5) {
            val offset = i * 8f * density
            canvas.drawLine(startX + offset, startY, startX + size + offset, startY + size, hatchPaint)
            canvas.drawLine(startX + offset, startY + size, startX + size + offset, startY, hatchPaint)
        }
    }

    private fun drawMirrorNumber(canvas: Canvas, w: Float, h: Float) {
        if (auftragsnummer.isEmpty()) return

        val density = resources.displayMetrics.density
        mirrorNumPaint.textSize = 28f * density

        canvas.save()
        val textWidth = mirrorNumPaint.measureText(auftragsnummer)
        val x = (w - textWidth) / 2f
        val y = h - 8f * density

        canvas.scale(1f, -1f, w / 2f, y - 14f * density)
        canvas.drawText(auftragsnummer, x, y, mirrorNumPaint)
        canvas.restore()
    }
}
