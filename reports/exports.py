"""CSV, Excel and PDF export of any report."""
import csv
import io
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

from core.templatetags.ui import format_cell


def _filename(report, extension):
    return f"{report['slug']}-{report['start']}-{report['end']}.{extension}"


def _display_rows(report):
    return [[format_cell(cell) for cell in row] for row in report["rows"]]


def export_csv(report):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{_filename(report, "csv")}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(report["columns"])
    for row in _display_rows(report):
        writer.writerow(row)
    if report["summary"]:
        writer.writerow([])
        for label, value in report["summary"]:
            writer.writerow([label, format_cell(value)])
    return response


def _excel_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return timezone.localtime(value).replace(tzinfo=None) if timezone.is_aware(value) else value
    if isinstance(value, date):
        return value
    return value


def export_xlsx(report):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = report["title"][:31]
    sheet.append(report["columns"])
    header_fill = PatternFill("solid", fgColor="1E293B")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for row in report["rows"]:
        sheet.append([_excel_value(cell) for cell in row])
    if report["summary"]:
        sheet.append([])
        for label, value in report["summary"]:
            sheet.append([label, _excel_value(value)])
            sheet.cell(row=sheet.max_row, column=1).font = Font(bold=True)
    for index, column in enumerate(report["columns"], start=1):
        width = max(12, min(40, len(str(column)) + 6))
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{_filename(report, "xlsx")}"'
    return response


def export_pdf(report, shop):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    page_size = landscape(A4) if len(report["columns"]) > 6 else A4
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=report["title"],
        author=shop.name,
    )
    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "Heading", parent=styles["Heading1"], fontSize=15, spaceAfter=2, textColor=colors.HexColor("#1e293b")
    )
    meta = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#475569"))
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=7.5, leading=9)
    head_style = ParagraphStyle(
        "Head", parent=styles["Normal"], fontSize=7.5, leading=9, textColor=colors.white, fontName="Helvetica-Bold"
    )
    story = [Paragraph(shop.name, heading)]
    address = shop.address.replace("\n", ", ") if shop.address else ""
    if address or shop.phone:
        story.append(Paragraph(" · ".join(part for part in [address, shop.phone] if part), meta))
    story.append(Paragraph(report["title"], heading))
    story.append(
        Paragraph(
            f"{report['start']:%d %b %Y} to {report['end']:%d %b %Y} · generated {timezone.localtime():%Y-%m-%d %H:%M}",
            meta,
        )
    )
    story.append(Spacer(1, 6))

    data = [[Paragraph(str(column), head_style) for column in report["columns"]]]
    for row in report["rows"]:
        data.append([Paragraph(format_cell(cell), cell_style) for cell in row])
    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(table)
    if report["summary"]:
        story.append(Spacer(1, 8))
        summary_data = [
            [Paragraph(f"<b>{label}</b>", cell_style), Paragraph(format_cell(value), cell_style)]
            for label, value in report["summary"]
        ]
        summary = Table(summary_data, hAlign="LEFT")
        summary.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ]
            )
        )
        story.append(summary)
    document.build(story)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_filename(report, "pdf")}"'
    return response


def report_response(report, fmt, shop):
    if fmt == "xlsx":
        return export_xlsx(report)
    if fmt == "pdf":
        return export_pdf(report, shop)
    return export_csv(report)
