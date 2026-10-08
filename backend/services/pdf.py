"""Branded PDF output shared by loan schedules, payslips and reports.

Everything (name, colours, logo, footer line, contact details) is static
— backend/branding.py, the one place that changes for a different
client. LIGHT/ZEBRA (row-shading tints) are fixed constants derived from
a neutral blue tint, since there's no "light tint of the brand colour"
setting. All money is comma-formatted (1,000,000.00).
"""
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape as landscape_page
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import branding
from services.loan_calculator import schedule_totals

LIGHT = colors.HexColor("#EAF1F8")
ZEBRA = colors.HexColor("#F4F8FC")


def company_name():
    return branding.COMPANY_NAME


def primary_color():
    return colors.HexColor(branding.PRIMARY_COLOR)


def accent_color():
    return colors.HexColor(branding.ACCENT_COLOR)


def footer_text():
    return branding.FOOTER_TEXT


def company_contacts():
    """address / phone / email, joined for the header's right-hand column —
    only whichever of the three are actually set."""
    parts = [p for p in (branding.COMPANY_ADDRESS, branding.COMPANY_PHONE, branding.COMPANY_EMAIL) if p]
    return "  |  ".join(parts)


def company_logo_path():
    return branding.LOGO_PATH if branding.logo_bytes() else None


def fmt_money(value):
    # Part 1.5: every money value in every PDF is whole shillings, commas, no decimals.
    return f"{Decimal(str(value)):,.0f}"


def _header_footer(subtitle, confidential=True):
    def draw(canvas, doc):
        width, height = doc.pagesize
        canvas.saveState()
        canvas.setFillColor(primary_color())
        canvas.rect(0, height - 26 * mm, width, 26 * mm, fill=1, stroke=0)
        canvas.setFillColor(accent_color())
        canvas.rect(0, height - 28 * mm, width, 2 * mm, fill=1, stroke=0)
        # Logo at left (Phase 4).
        logo = company_logo_path()
        text_x = 15 * mm
        if logo:
            try:
                canvas.drawImage(logo, 15 * mm, height - 24 * mm, width=18 * mm, height=18 * mm, preserveAspectRatio=True, mask="auto")
                text_x = 37 * mm
            except Exception:
                pass
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 10)
        canvas.drawString(text_x, height - 18 * mm, subtitle)
        # Name and contacts at right (Phase 4).
        right_x = width - 15 * mm
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawRightString(right_x, height - 13 * mm, company_name())
        contacts = company_contacts()
        if contacts:
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(right_x, height - 20 * mm, contacts)
        canvas.setFillColor(colors.grey)
        canvas.setFont("Helvetica", 8)
        # "Page X of Y" is drawn once the real page count is known, by
        # NumberedCanvas.save() below — not drawn here to avoid overlapping text.
        footer = (
            f"{company_name()} — {footer_text()} Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}."
            if confidential else company_name()
        )
        canvas.drawString(15 * mm, 8 * mm, footer)
        canvas.restoreState()

    return draw


def _build_with_page_count(story, subtitle, pagesize=A4, confidential=True):
    """'Page X of Y' needs the real page count, which ReportLab only knows
    after the first pass — NumberedCanvas defers drawing it until save()."""
    from reportlab.pdfgen import canvas as canvas_mod

    class NumberedCanvas(canvas_mod.Canvas):
        def __init__(self, *args, **kwargs):
            canvas_mod.Canvas.__init__(self, *args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.drawRightString(pagesize[0] - 15 * mm, 8 * mm, f"Page {self._pageNumber} of {total}")
                canvas_mod.Canvas.showPage(self)
            canvas_mod.Canvas.save(self)

    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream, pagesize=pagesize, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=34 * mm, bottomMargin=16 * mm
    )
    draw = _header_footer(subtitle, confidential)
    doc.build(story, onFirstPage=draw, onLaterPages=draw, canvasmaker=NumberedCanvas)
    stream.seek(0)
    return stream


def _styles():
    base = getSampleStyleSheet()
    primary = primary_color()
    return {
        "title": ParagraphStyle("t", parent=base["Heading2"], textColor=primary, spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontSize=9, leading=12),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontSize=9, leading=12, textColor=primary, fontName="Helvetica-Bold"),
    }


def _kv_table(pairs, col_widths):
    table = Table(pairs, colWidths=col_widths)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), primary_color()),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _build(story, subtitle):
    return _build_with_page_count(story, subtitle)


def schedule_pdf(loan):
    """Full amortization schedule for a loan, in any status (draft onward).

    Reflects the CURRENT reconciled schedule — paid rows as they actually
    settled, remaining rows as last re-amortized — never the original
    at-creation plan, since it is built from loan.schedules as they stand.
    """
    styles = _styles()
    rows = sorted(loan.schedules, key=lambda r: r.due_date)

    # Balance after each row, derived from the schedule itself: what is still to
    # be repaid in principal by the rows that follow it.
    balances, running = [], Decimal("0")
    for row in reversed(rows):
        balances.append(running)
        running += Decimal(str(row.principal_portion))
    balances.reverse()

    # Single shared totals computation — same function the calculator, loan
    # creation preview and loan detail page use, so the numbers can never
    # drift apart from what is shown on screen.
    totals = schedule_totals((r.principal_portion, r.interest_portion, r.expected_amount) for r in rows)
    total_principal, total_interest, total_paid = totals["total_principal"], totals["total_interest"], totals["total_paid"]

    story = [
        Paragraph(f"Repayment Schedule — Loan #{loan.id}", styles["title"]),
        _kv_table(
            [
                ["Borrower", loan.borrower.name if loan.borrower else "-", "Principal", fmt_money(loan.principal_amount)],
                ["Product", loan.loan_product.name if loan.loan_product else "-", "Monthly Interest Rate", f"{loan.interest_rate}% per month (reducing balance)"],
                ["Start date", loan.start_date.isoformat(), "Term", f"{loan.term_months} months"],
                ["Status", str(loan.status).replace("_", " ").title(), "Outstanding balance", fmt_money(loan.outstanding_balance)],
            ],
            [28 * mm, 55 * mm, 38 * mm, 55 * mm],
        ),
        Spacer(1, 6 * mm),
    ]

    data = [["#", "Due date", "Principal", "Interest", "Payment", "Balance after", "Status"]]
    for index, row in enumerate(rows, start=1):
        data.append(
            [
                str(index),
                row.due_date.isoformat(),
                fmt_money(row.principal_portion),
                fmt_money(row.interest_portion),
                fmt_money(row.expected_amount),
                fmt_money(balances[index - 1]),
                # Display-only: "paid" + paid_less_than_scheduled reads as
                # "Partially Paid" — the row's real status column never
                # changes (that's what the allocation math reads).
                ("Partially Paid" if row.status == "paid" and row.paid_less_than_scheduled else str(row.status).replace("_", " ").title()),
            ]
        )
    data.append(["", "Totals", fmt_money(total_principal), fmt_money(total_interest), fmt_money(total_paid), "", ""])

    table = Table(data, repeatRows=1, colWidths=[9 * mm, 24 * mm, 29 * mm, 27 * mm, 29 * mm, 31 * mm, 23 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), primary_color()),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (2, 0), (5, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, LIGHT]),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, accent_color()),
                ("GRID", (0, 0), (-1, -2), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.grey),
            ]
        )
    )
    story.append(table)
    return _build(story, "Loan repayment schedule")


def _payslip_story(line, styles):
    """The flowables for one employee's payslip — shared by payslip_pdf()
    (one employee) and payslips_pdf() (every employee in a batch, one page
    each), so there is exactly one layout, never two to drift apart."""
    employee = line.employee
    story = [
        Paragraph(f"Payslip — {line.month}", styles["title"]),
        _kv_table(
            [
                ["Employee", employee.name if employee else "-"],
                ["Job title", (employee.job_title if employee else None) or "-"],
                ["Pay period", line.month],
            ],
            [35 * mm, 100 * mm],
        ),
        Spacer(1, 6 * mm),
    ]
    employee_lines = [dl for dl in line.deduction_lines if dl.side == "employee"]
    employer_lines = [dl for dl in line.deduction_lines if dl.side == "employer"]
    rows = [["Description", "Amount"], ["Gross salary", fmt_money(line.salary_amount)]]
    for dl in employee_lines:
        rows.append([dl.name_snapshot, f"-{fmt_money(dl.amount)}"])
    rows.append(["Net pay", fmt_money(line.net_pay)])
    net_row_index = len(rows) - 1
    table = Table(rows, colWidths=[95 * mm, 45 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), primary_color()),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, net_row_index), (-1, net_row_index), "Helvetica-Bold"),
                ("LINEABOVE", (0, net_row_index), (-1, net_row_index), 0.8, accent_color()),
                ("BACKGROUND", (0, net_row_index), (-1, net_row_index), LIGHT),
                ("GRID", (0, 0), (-1, net_row_index - 1), 0.25, colors.lightgrey),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.grey),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    if employer_lines:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Employer contributions (cost to the company — not deducted from net pay)", styles["body"]))
        employer_rows = [["Description", "Amount"]] + [[dl.name_snapshot, fmt_money(dl.amount)] for dl in employer_lines]
        employer_table = Table(employer_rows, colWidths=[95 * mm, 45 * mm])
        employer_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.grey),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(employer_table)
    return story


def payslip_pdf(line):
    """Payslip for one employee's payroll line - itemized deductions (Part
    5.2): each deduction/contribution shown on its own row, employee-side
    ones subtracted to reach net pay, employer-side ones shown separately
    as a cost to the company (never subtracted from net pay)."""
    return _build(_payslip_story(line, _styles()), "Employee payslip")


def report_pdf(title, period, generated_by, kpis, columns, rows, totals_row=None, landscape=False, numeric_cols=None):
    """Generic report PDF: header/logo, title + period, KPI cards, a bordered
    zebra-striped table with right-aligned numeric columns and a bold totals
    row, repeated header row, page X of Y, confidentiality footer (Part 6.3).

    columns: list of header labels. rows: list of lists of already-formatted
    cell strings. numeric_cols: 0-based column indexes to right-align.
    """
    styles = _styles()
    pagesize = landscape_page(A4) if landscape else A4
    story = [Paragraph(title, styles["title"])]
    meta = f"Period: {period} &nbsp;&nbsp;|&nbsp;&nbsp; Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} by {generated_by}"
    story.append(Paragraph(meta, styles["body"]))
    story.append(Spacer(1, 4 * mm))

    if kpis:
        kpi_cells = [[Paragraph(f"<b>{label}</b>", styles["body"]), Paragraph(str(value), styles["title"])] for label, value in kpis]
        # Lay KPIs out in a row of small boxes.
        per_row = 4
        for chunk_start in range(0, len(kpi_cells), per_row):
            chunk = kpi_cells[chunk_start:chunk_start + per_row]
            kpi_table = Table([[c[0] for c in chunk], [c[1] for c in chunk]], colWidths=[(pagesize[0] - 30 * mm) / max(len(chunk), 1)] * len(chunk))
            kpi_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.5, accent_color()),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))
            story.append(kpi_table)
            story.append(Spacer(1, 3 * mm))
        story.append(Spacer(1, 3 * mm))

    numeric_cols = set(numeric_cols or [])
    data = [columns] + rows
    if totals_row:
        data.append(totals_row)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), primary_color()),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, (len(data) - 2) if totals_row else -1), [colors.white, ZEBRA]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for col in numeric_cols:
        style_cmds.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    if totals_row:
        style_cmds += [
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, accent_color()),
            ("BACKGROUND", (0, -1), (-1, -1), LIGHT),
        ]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    return _build_with_page_count(story, title, pagesize=pagesize)
