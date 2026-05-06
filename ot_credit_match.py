import os
import re
import sys
from datetime import datetime
import pandas as pd
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


ALIGN_RTL = (
    Qt.AlignmentFlag.AlignRight
    | Qt.AlignmentFlag.AlignAbsolute
    | Qt.AlignmentFlag.AlignVCenter
)


def make_rtl_label(text, bold=False):
    label = QLabel(text)
    font = QFont("Arial", 11)
    font.setBold(bold)
    label.setFont(font)
    label.setAlignment(ALIGN_RTL)
    label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    return label


def format_currency(value):
    return f"₪{value:,.0f}"


def enforce_rtl_header_alignment(table):
    table.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    header = table.horizontalHeader()
    header.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    header.setDefaultAlignment(ALIGN_RTL)
    for col_idx in range(table.columnCount()):
        item = table.horizontalHeaderItem(col_idx)
        if item is not None:
            item.setTextAlignment(ALIGN_RTL)


def sum_amount(series):
    return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())


def classify_diff_status(diff_value):
    if diff_value == 0:
        return "success", "✅"
    if diff_value < 0:
        return "warning", "⚠️"
    return "error", "❌"


def compute_supplier_dashboard_data(
    df_credit,
    df_all_suppliers,
    matched_all,
    df_only_in_credit,
    df_only_in_suppliers,
    supplier_cols_dict,
):
    supplier_map = {
        "גלבוע": "ספק גבייה - גילבוע",
        "אייגנסי": "ספק גבייה - אייג'נסי",
        "אודיסאה": "ספק גבייה - אודיסאה",
        "בוסטר": "ספק גבייה - בוסטר",
    }

    suppliers = []
    total_processor = 0.0
    total_supplier = 0.0
    total_matched_amount = 0.0

    for supplier_key, supplier_label in supplier_map.items():
        matched_supplier = matched_all[matched_all["ספק_משויך"] == supplier_key]
        credit_only_supplier = df_only_in_credit[df_only_in_credit["ספק_משויך"] == supplier_key]
        supplier_only_rows = df_only_in_suppliers[df_only_in_suppliers["source_supplier"] == supplier_key]

        credit_exception_cols = [
            c for c in ["מסוף", "טוקן", "מספר אישור", "סכום", "מספר הזמנה"]
            if c in credit_only_supplier.columns
        ]
        supplier_exception_cols = [
            c for c in supplier_cols_dict.get(supplier_key, [])
            if c in supplier_only_rows.columns
        ]

        matched_amount = sum_amount(matched_supplier.get("match_amount", pd.Series(dtype=float)))
        credit_only_amount = sum_amount(credit_only_supplier.get("match_amount", pd.Series(dtype=float)))
        supplier_only_amount = sum_amount(supplier_only_rows.get("match_amount", pd.Series(dtype=float)))

        processor_total = matched_amount + credit_only_amount
        supplier_total = matched_amount + supplier_only_amount
        diff_amount = supplier_total - processor_total
        status, status_icon = classify_diff_status(diff_amount)

        matched_count = int(len(matched_supplier))
        credit_only_count = int(len(credit_only_supplier))
        supplier_only_count = int(len(supplier_only_rows))

        denominator = matched_count + credit_only_count
        match_rate = (matched_count / denominator * 100) if denominator else 0.0

        suppliers.append(
            {
                "supplier_key": supplier_key,
                "supplier_name": supplier_label,
                "processor_total": processor_total,
                "supplier_total": supplier_total,
                "diff_amount": diff_amount,
                "status": status,
                "status_icon": status_icon,
                "matched_count": matched_count,
                "credit_only_count": credit_only_count,
                "supplier_only_count": supplier_only_count,
                "match_rate": match_rate,
                "matched_amount": matched_amount,
                "credit_only_amount": credit_only_amount,
                "supplier_only_amount": supplier_only_amount,
                "credit_exception_records": (
                    credit_only_supplier[credit_exception_cols].fillna("").to_dict("records")
                    if credit_exception_cols
                    else []
                ),
                "supplier_exception_records": (
                    supplier_only_rows[supplier_exception_cols].fillna("").to_dict("records")
                    if supplier_exception_cols
                    else []
                ),
            }
        )

        total_processor += processor_total
        total_supplier += supplier_total
        total_matched_amount += matched_amount

    discrepancy = total_supplier - total_processor
    overall_rate = (total_matched_amount / total_processor * 100) if total_processor else 0.0

    return {
        "kpis": {
            "processor_total": total_processor,
            "suppliers_total": total_supplier,
            "match_rate": overall_rate,
            "discrepancy": discrepancy,
        },
        "suppliers": suppliers,
    }


class SupplierBreakdownDialog(QDialog):
    def __init__(self, supplier_stats, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"פירוט תנועות - {supplier_stats['supplier_name']}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(560, 280)

        layout = QVBoxLayout(self)
        title = make_rtl_label(f"פירוט תנועות עבור {supplier_stats['supplier_name']}", bold=True)
        layout.addWidget(title)

        table = QTableWidget(3, 3)
        table.setHorizontalHeaderLabels(["קטגוריה", "כמות", "סכום"]) 
        enforce_rtl_header_alignment(table)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        rows = [
            ("התאמות", supplier_stats["matched_count"], supplier_stats["matched_amount"]),
            ("רק בקרדיט", supplier_stats["credit_only_count"], supplier_stats["credit_only_amount"]),
            ("רק בספק", supplier_stats["supplier_only_count"], supplier_stats["supplier_only_amount"]),
        ]
        for row_idx, (name, count, amount) in enumerate(rows):
            table.setItem(row_idx, 0, QTableWidgetItem(name))
            table.setItem(row_idx, 1, QTableWidgetItem(str(count)))
            table.setItem(row_idx, 2, QTableWidgetItem(format_currency(amount)))

        layout.addWidget(table)


class VennComparisonWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.left_only = 0
        self.overlap = 0
        self.right_only = 0
        self.setMinimumHeight(180)

    def set_values(self, left_only, overlap, right_only):
        self.left_only = int(left_only)
        self.overlap = int(overlap)
        self.right_only = int(right_only)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        diameter = min(140, max(90, int(w * 0.28)))
        radius = diameter // 2
        center_y = max(58, h // 2 - 10)
        left_x = w // 2 - int(radius * 1.15)
        right_x = w // 2 + int(radius * 1.15)

        left_color = QColor("#60a5fa")
        left_color.setAlpha(130)
        right_color = QColor("#34d399")
        right_color.setAlpha(130)

        painter.setPen(QPen(QColor("#2563eb"), 2))
        painter.setBrush(left_color)
        painter.drawEllipse(left_x - radius, center_y - radius, diameter, diameter)

        painter.setPen(QPen(QColor("#059669"), 2))
        painter.setBrush(right_color)
        painter.drawEllipse(right_x - radius, center_y - radius, diameter, diameter)

        painter.setPen(QPen(QColor("#111827")))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        painter.drawText(left_x - radius + 10, center_y, f"{self.left_only}")
        painter.drawText(w // 2 - 12, center_y, f"{self.overlap}")
        painter.drawText(right_x + radius - 28, center_y, f"{self.right_only}")

        painter.setFont(QFont("Arial", 9))
        painter.drawText(left_x - radius, center_y + radius + 22, "סולק בלבד")
        painter.drawText(w // 2 - 26, center_y + radius + 22, "חיתוך")
        painter.drawText(right_x + radius - 66, center_y + radius + 22, "ספק בלבד")

        painter.end()


class SupplierExceptionsDialog(QDialog):
    def __init__(self, supplier_stats, parent=None):
        super().__init__(parent)
        self.supplier_stats = supplier_stats
        self.setWindowTitle(f"חריגים - {supplier_stats['supplier_name']}")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(1200, 760)
        self.credit_records = supplier_stats.get("credit_exception_records", [])
        self.supplier_records = supplier_stats.get("supplier_exception_records", [])
        self.credit_table = None
        self.supplier_table = None

        main_layout = QVBoxLayout(self)
        title = make_rtl_label(f"חריגים מתוך הנתונים האמיתיים - {supplier_stats['supplier_name']}", bold=True)
        title.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        main_layout.addWidget(title)

        summary = make_rtl_label(
            f"רק בקרדיט: {supplier_stats['credit_only_count']} | רק בספק: {supplier_stats['supplier_only_count']}"
        )
        main_layout.addWidget(summary)

        export_button = QPushButton("ייצוא חריגים לאקסל")
        export_button.setMinimumHeight(38)
        export_button.clicked.connect(self._export_exceptions_to_excel)
        main_layout.addWidget(export_button, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)

        tabs = QTabWidget()
        tabs.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        credit_tab = QWidget()
        credit_layout = QVBoxLayout(credit_tab)
        self.credit_table = self._build_records_table(
            self.credit_records,
            empty_message="אין חריגים בצד הקרדיט לספק זה.",
        )
        credit_layout.addWidget(self.credit_table)

        supplier_tab = QWidget()
        supplier_layout = QVBoxLayout(supplier_tab)
        self.supplier_table = self._build_records_table(
            self.supplier_records,
            empty_message="אין חריגים בצד הספק לספק זה.",
        )
        supplier_layout.addWidget(self.supplier_table)

        tabs.addTab(credit_tab, "חריגים - רק בקרדיט")
        tabs.addTab(supplier_tab, "חריגים - רק בספק")
        main_layout.addWidget(tabs)

        drilldown_box = QFrame()
        drilldown_box.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; }"
        )
        drilldown_layout = QVBoxLayout(drilldown_box)

        drilldown_title = make_rtl_label("התאמה כמותית וכספית בלחיצה על רשומה", bold=True)
        drilldown_layout.addWidget(drilldown_title)

        self.selected_record_label = make_rtl_label("בחר רשומה בטבלה כדי לראות התאמה כמותית וכספית")
        drilldown_layout.addWidget(self.selected_record_label)

        quantitative_row = QHBoxLayout()
        self.processor_count_label = make_rtl_label("כמות בצד סולק: 0")
        self.overlap_count_label = make_rtl_label("כמות משותפת: 0")
        self.supplier_count_label = make_rtl_label("כמות בצד ספק: 0")
        quantitative_row.addWidget(self.processor_count_label)
        quantitative_row.addWidget(self.overlap_count_label)
        quantitative_row.addWidget(self.supplier_count_label)
        drilldown_layout.addLayout(quantitative_row)

        monetary_row = QHBoxLayout()
        self.processor_amount_label = make_rtl_label("סכום סולק: ₪0")
        self.overlap_amount_label = make_rtl_label("סכום משותף: ₪0")
        self.supplier_amount_label = make_rtl_label("סכום ספק: ₪0")
        self.diff_amount_label = make_rtl_label("פער: ₪0")
        monetary_row.addWidget(self.processor_amount_label)
        monetary_row.addWidget(self.overlap_amount_label)
        monetary_row.addWidget(self.supplier_amount_label)
        monetary_row.addWidget(self.diff_amount_label)
        drilldown_layout.addLayout(monetary_row)

        self.venn_widget = VennComparisonWidget()
        drilldown_layout.addWidget(self.venn_widget)

        venn_amounts = QHBoxLayout()
        self.left_only_amount_label = make_rtl_label("סולק בלבד: ₪0")
        self.intersection_amount_label = make_rtl_label("חיתוך: ₪0")
        self.right_only_amount_label = make_rtl_label("ספק בלבד: ₪0")
        venn_amounts.addWidget(self.left_only_amount_label)
        venn_amounts.addWidget(self.intersection_amount_label)
        venn_amounts.addWidget(self.right_only_amount_label)
        drilldown_layout.addLayout(venn_amounts)

        main_layout.addWidget(drilldown_box)

        self._wire_selection_handlers()
        self._update_drilldown(None, "")

    def _build_records_table(self, records, empty_message):
        if not records:
            return make_rtl_label(empty_message)

        headers = list(records[0].keys())
        table = QTableWidget(len(records), len(headers))
        table.setHorizontalHeaderLabels(headers)
        enforce_rtl_header_alignment(table)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setFont(QFont("Arial", 10))

        for row_idx, row in enumerate(records):
            for col_idx, header in enumerate(headers):
                table.setItem(row_idx, col_idx, QTableWidgetItem(str(row.get(header, ""))))

        return table

    def _wire_selection_handlers(self):
        if isinstance(self.credit_table, QTableWidget):
            self.credit_table.itemSelectionChanged.connect(
                lambda: self._handle_table_selection(
                    self.credit_table,
                    self.credit_records,
                    "חריג סולק",
                )
            )

        if isinstance(self.supplier_table, QTableWidget):
            self.supplier_table.itemSelectionChanged.connect(
                lambda: self._handle_table_selection(
                    self.supplier_table,
                    self.supplier_records,
                    "חריג ספק",
                )
            )

    def _handle_table_selection(self, table, records, source_label):
        if not isinstance(table, QTableWidget):
            return

        row = table.currentRow()
        if row < 0 or row >= len(records):
            self._update_drilldown(None, "")
            return

        self._update_drilldown(records[row], source_label)

    def _record_display_text(self, record, source_label):
        if not record:
            return "בחר רשומה בטבלה כדי לראות התאמה כמותית וכספית"

        identifier = (
            record.get("מספר הזמנה")
            or record.get("Voucher number")
            or record.get("Doc number")
            or record.get("טוקן")
            or record.get("Pan")
            or "ללא מזהה"
        )
        amount = self._extract_amount(record)
        return f"נבחרה רשומה ({source_label}) | מזהה: {identifier} | סכום רשומה: {format_currency(amount)}"

    def _extract_amount(self, record):
        amount_candidates = [
            "סכום",
            "match_amount",
            "origin amount",
            "charge amount",
            "Amount",
            "Invoice sum",
        ]
        for key in amount_candidates:
            if key in record and str(record.get(key, "")).strip() != "":
                return clean_amount(record.get(key))
        return 0.0

    def _update_drilldown(self, selected_record, source_label):
        matched_count = int(self.supplier_stats.get("matched_count", 0))
        credit_only_count = int(self.supplier_stats.get("credit_only_count", 0))
        supplier_only_count = int(self.supplier_stats.get("supplier_only_count", 0))

        processor_count = matched_count + credit_only_count
        supplier_count = matched_count + supplier_only_count

        matched_amount = float(self.supplier_stats.get("matched_amount", 0.0))
        credit_only_amount = float(self.supplier_stats.get("credit_only_amount", 0.0))
        supplier_only_amount = float(self.supplier_stats.get("supplier_only_amount", 0.0))

        processor_total = float(self.supplier_stats.get("processor_total", matched_amount + credit_only_amount))
        supplier_total = float(self.supplier_stats.get("supplier_total", matched_amount + supplier_only_amount))
        diff_amount = float(self.supplier_stats.get("diff_amount", supplier_total - processor_total))

        self.selected_record_label.setText(self._record_display_text(selected_record, source_label))

        self.processor_count_label.setText(f"כמות בצד סולק: {processor_count}")
        self.overlap_count_label.setText(f"כמות משותפת: {matched_count}")
        self.supplier_count_label.setText(f"כמות בצד ספק: {supplier_count}")

        self.processor_amount_label.setText(f"סכום סולק: {format_currency(processor_total)}")
        self.overlap_amount_label.setText(f"סכום משותף: {format_currency(matched_amount)}")
        self.supplier_amount_label.setText(f"סכום ספק: {format_currency(supplier_total)}")
        self.diff_amount_label.setText(f"פער: {format_currency(diff_amount)}")

        self.left_only_amount_label.setText(f"סולק בלבד: {format_currency(credit_only_amount)}")
        self.intersection_amount_label.setText(f"חיתוך: {format_currency(matched_amount)}")
        self.right_only_amount_label.setText(f"ספק בלבד: {format_currency(supplier_only_amount)}")

        self.venn_widget.set_values(credit_only_count, matched_count, supplier_only_count)

    def _export_exceptions_to_excel(self):
        default_name = f"חריגים_{self.supplier_stats['supplier_key']}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "שמור חריגים לקובץ אקסל",
            default_name,
            "Excel Files (*.xlsx)",
        )
        if not path:
            return

        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            credit_df = pd.DataFrame(self.supplier_stats.get("credit_exception_records", []))
            supplier_df = pd.DataFrame(self.supplier_stats.get("supplier_exception_records", []))

            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                if credit_df.empty:
                    pd.DataFrame({"הודעה": ["אין חריגים בצד הקרדיט"]}).to_excel(
                        writer, sheet_name="חריגים_קרדיט", index=False
                    )
                else:
                    credit_df.to_excel(writer, sheet_name="חריגים_קרדיט", index=False)

                if supplier_df.empty:
                    pd.DataFrame({"הודעה": ["אין חריגים בצד הספק"]}).to_excel(
                        writer, sheet_name="חריגים_ספק", index=False
                    )
                else:
                    supplier_df.to_excel(writer, sheet_name="חריגים_ספק", index=False)

            QMessageBox.information(self, "הצלחה", f"קובץ החריגים נשמר בהצלחה:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "שגיאה", f"ייצוא החריגים נכשל:\n{exc}")


class SupplierReconciliationDashboard(QWidget):
    def __init__(self, dashboard_data, parent=None):
        super().__init__(parent)
        self.dashboard_data = dashboard_data
        self._details_dialogs = []
        self.setWindowTitle("פירוט התאמה לפי ספק")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(1200, 720)
        self.resize(1440, 860)
        self._build_ui()

    def _make_kpi_card(self, title_text, value_text, accent_color):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: #ffffff; border: 1px solid #e5e7eb; border-right: 5px solid {accent_color}; border-radius: 10px; }}"
        )
        card_layout = QVBoxLayout(card)
        card.setMinimumHeight(100)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title = QLabel(title_text)
        title.setStyleSheet("color: #6b7280; font-size: 12px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value = QLabel(value_text)
        value.setStyleSheet("color: #111827; font-size: 22px; font-weight: 700;")
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)
        card_layout.addWidget(value)
        return card

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        header = make_rtl_label("פירוט התאמה לפי ספק", bold=True)
        header.setFont(QFont("Arial", 17, QFont.Weight.Bold))
        layout.addWidget(header, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)

        kpis = self.dashboard_data["kpis"]
        cards_layout = QHBoxLayout()
        cards_layout.addWidget(self._make_kpi_card("סכום סולק", format_currency(kpis["processor_total"]), "#2563eb"))
        cards_layout.addWidget(self._make_kpi_card("סכום ספקים", format_currency(kpis["suppliers_total"]), "#7c3aed"))
        cards_layout.addWidget(self._make_kpi_card("אחוז התאמה", f"{kpis['match_rate']:.1f}%", "#16a34a"))

        discrepancy_color = "#16a34a" if kpis["discrepancy"] == 0 else "#dc2626"
        cards_layout.addWidget(self._make_kpi_card("הפרש לטיפול", format_currency(kpis["discrepancy"]), discrepancy_color))
        layout.addLayout(cards_layout)

        table = QTableWidget(len(self.dashboard_data["suppliers"]), 6)
        table.setHorizontalHeaderLabels(["שם הספק", "דיווח סולק", "דיווח ספק", "הפרש", "סטטוס", "פעולה"])
        enforce_rtl_header_alignment(table)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setFont(QFont("Arial", 11))
        table.setMinimumHeight(460)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumSectionSize(120)

        for row_idx, supplier_stats in enumerate(self.dashboard_data["suppliers"]):
            table.setItem(row_idx, 0, QTableWidgetItem(supplier_stats["supplier_name"]))
            table.setItem(row_idx, 1, QTableWidgetItem(format_currency(supplier_stats["processor_total"])))
            table.setItem(row_idx, 2, QTableWidgetItem(format_currency(supplier_stats["supplier_total"])))

            diff_item = QTableWidgetItem(format_currency(supplier_stats["diff_amount"]))
            if supplier_stats["status"] == "success":
                diff_item.setForeground(Qt.GlobalColor.darkGreen)
            elif supplier_stats["status"] == "warning":
                diff_item.setForeground(Qt.GlobalColor.darkYellow)
            else:
                diff_item.setForeground(Qt.GlobalColor.red)
            table.setItem(row_idx, 3, diff_item)

            status_text = f"{supplier_stats['status_icon']} {supplier_stats['matched_count']} התאמות"
            table.setItem(row_idx, 4, QTableWidgetItem(status_text))

            action_btn = QPushButton("הצג חריגים")
            action_btn.clicked.connect(
                lambda _checked=False, data=supplier_stats: self._show_supplier_details(data)
            )
            table.setCellWidget(row_idx, 5, action_btn)

        layout.addWidget(table)

    def _show_supplier_details(self, supplier_stats):
        dialog = SupplierExceptionsDialog(supplier_stats, self)
        self._details_dialogs.append(dialog)
        dialog.exec()


def clean_card(card_val):
    if pd.isna(card_val):
        return ""
    val_str = str(card_val).strip()
    digits = re.sub(r"\D", "", val_str)
    return digits[-4:] if len(digits) >= 4 else digits


def clean_pnr(pnr_val, length=6):
    if pd.isna(pnr_val):
        return ""
    val_str = str(pnr_val).split(".")[0].strip()
    val_str = re.sub(r"\D", "", val_str).lstrip("0")
    return val_str[-length:] if len(val_str) >= length else val_str


def clean_auth(auth_val):
    if pd.isna(auth_val):
        return ""
    val_str = str(auth_val).split(".")[0].strip()
    return val_str.lstrip("0")


def clean_amount(amount_val):
    if pd.isna(amount_val):
        return 0.0
    val_str = str(amount_val).replace(",", "").strip()
    num = pd.to_numeric(val_str, errors="coerce")
    if pd.isna(num):
        return 0.0
    return round(float(num), 2)


# =====================================================================
# פונקציות קריאה וניקוי עבור כל אחד מהספקים
# =====================================================================

def load_gilboa(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            f.read()
        encoding_used = "utf-8"
    except UnicodeDecodeError:
        encoding_used = "cp1255"

    df = pd.read_csv(file_path, sep="^", dtype=str, encoding=encoding_used)
    df.columns = df.columns.astype(str).str.strip()

    if "Fop" in df.columns:
        df = df[df["Fop"].str.strip().isin(["PDQ", "CRD"])]

    # איחוד שורות לפי Doc number במידה וקיים
    if "Doc number" in df.columns:
        df["origin amount_num"] = df["origin amount"].apply(clean_amount)
        
        agg_dict = {col: "first" for col in df.columns if col != "origin amount_num"}
        agg_dict["origin amount_num"] = "sum"
        
        df = df.groupby("Doc number", as_index=False).agg(agg_dict)
        
        df["origin amount"] = df["origin amount_num"].astype(str)
        df.drop(columns=["origin amount_num"], inplace=True)

    df["match_card"] = df["Details"].apply(clean_card)
    df["match_amount"] = df["origin amount"].apply(clean_amount)
    df["match_auth"] = df["ref"].apply(clean_auth)
    df["source_supplier"] = "גלבוע"
    return df


def load_agency(file_path):
    if file_path.lower().endswith(".csv"):
        try:
            temp_df = pd.read_csv(file_path, header=None, dtype=str, encoding="utf-8")
        except UnicodeDecodeError:
            temp_df = pd.read_csv(file_path, header=None, dtype=str, encoding="cp1255")
    else:
        try:
            temp_df = pd.read_excel(file_path, header=None, dtype=str)
        except Exception:
            temp_df = pd.read_html(file_path)[0].astype(str)

    header_idx = 0
    for i, row in temp_df.iterrows():
        row_str = [str(s) for s in row.fillna("").values]
        if any("4 ספרות" in s or "סכום מטבע ראשי" in s or "מס' תיק" in s for s in row_str):
            header_idx = int(str(i).split(".")[0])
            break

    if file_path.lower().endswith(".csv"):
        try:
            df = pd.read_csv(file_path, skiprows=header_idx, dtype=str, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, skiprows=header_idx, dtype=str, encoding="cp1255")
    else:
        try:
            df = pd.read_excel(file_path, skiprows=header_idx, dtype=str)
        except Exception:
            df = pd.read_html(file_path, skiprows=header_idx)[0].astype(str)

    df.columns = df.columns.astype(str).str.strip()

    column_names = [str(c) for c in list(df.columns)]
    required_cols = ["4 ספרות אחרונות", "סכום מטבע ראשי", "מס' תיק", "מספר אישור"]
    for col in required_cols:
        if col not in column_names:
            matched_col = [
                c for c in column_names
                if col in c or c in col
            ]
            if matched_col:
                df.rename(columns={matched_col[0]: col}, inplace=True)

    if "סוג תשלום" in df.columns:
        df = df[df["סוג תשלום"].astype(str).str.strip() == "כרטיס אשראי"]

    df = df.dropna(how="all")

    df["match_card"] = df["4 ספרות אחרונות"].apply(clean_card)
    df["match_amount"] = df["סכום מטבע ראשי"].apply(clean_amount)
    df["match_pnr"] = df["מס' תיק"].apply(lambda x: clean_pnr(x, 6))
    df["match_auth"] = df["מספר אישור"].apply(clean_auth)
    df["source_supplier"] = "אייגנסי"
    return df


def load_odyssey(file_path):
    if file_path.lower().endswith(".csv"):
        temp_df = pd.read_csv(file_path, header=None, dtype=str)
    else:
        temp_df = pd.read_excel(file_path, header=None, dtype=str)

    header_idx = 0
    for i, row in temp_df.iterrows():
        row_str = [str(s) for s in row.values]
        if any("Amount" in s for s in row_str) and any("Card" in s for s in row_str):
            header_idx = int(str(i).split(".")[0])
            break

    if file_path.lower().endswith(".csv"):
        df = pd.read_csv(file_path, skiprows=header_idx, dtype=str)
    else:
        df = pd.read_excel(file_path, skiprows=header_idx, dtype=str)

    df.columns = df.columns.astype(str).str.strip()

    df = df.dropna(subset=["Amount", "Card"], how="all")
    for col in df.columns:
        df = df[~df[col].astype(str).str.contains("Total|Summary", na=False)]

    df["match_card"] = df["Card"].apply(clean_card)
    df["match_amount"] = df["Amount"].apply(clean_amount)
    df["match_pnr"] = df["Pnr"].apply(lambda x: clean_pnr(x, 6))
    df["match_auth"] = ""
    df["source_supplier"] = "אודיסאה"
    return df


def load_booster(file_path):
    if file_path.lower().endswith(".csv"):
        df = pd.read_csv(file_path, skiprows=6, dtype=str)
    else:
        df = pd.read_excel(file_path, skiprows=6, dtype=str)
        
    df.columns = df.columns.astype(str).str.strip()

    if "Payment Method" in df.columns:
        df = df[df["Payment Method"].astype(str).str.strip().str.lower().str.startswith("credit card", na=False)]

    # איחוד שורות לפי Document No. במידה וקיים
    if "Document No." in df.columns:
        df["Amount_num"] = df["Amount"].apply(clean_amount)
        
        agg_dict = {col: "first" for col in df.columns if col != "Amount_num"}
        agg_dict["Amount_num"] = "sum"
        
        df = df.groupby("Document No.", as_index=False).agg(agg_dict)
        
        df["Amount"] = df["Amount_num"].astype(str)
        df.drop(columns=["Amount_num"], inplace=True)

    df["match_card"] = df["Payment Method"].apply(clean_card)
    df["match_amount"] = df["Amount"].apply(clean_amount)
    df["match_pnr"] = df["Credit Account Name"].apply(lambda x: clean_pnr(x, 6))
    df["match_auth"] = df["Description"].apply(clean_auth)
    df["source_supplier"] = "בוסטר"
    return df


# =====================================================================
# טעינה וסיווג לקובץ "קרדיט 2000"
# =====================================================================

def load_credit_2000(file_path):
    df = pd.read_excel(file_path, dtype=str)
    df.columns = df.columns.astype(str).str.strip()

    df["מסוף_נקי"] = df["מסוף"].astype(str).str.strip().str.lower()
    df["מספר הזמנה_נקי"] = df["מספר הזמנה"].astype(str).str.strip()

    def classify_supplier(row):
        terminal = row["מסוף_נקי"]
        order_no = row["מספר הזמנה_נקי"]

        if terminal in ["cus0896", "cus0899", "cus0002"]:
            return "אייגנסי"
        if terminal in ["cus2343", "cus2798"]:
            return "אודיסאה"
        
        if terminal == "cus0855":
            if order_no.startswith("00"):
                return "בוסטר"
            return "גלבוע"

        gilboa_terminals = [
            "cus0853", "cus0856", "cus0862", "cus0865", "cus0866",
            "cus0870", "cus0871", "cus0874", "cus0879", "cus0881",
            "cus0884", "cus2097", "cus2479", "cus3130", "cus3444"
        ]
        if terminal in gilboa_terminals:
            return "גלבוע"
        return "לא מזוהה"

    df["ספק_משויך"] = df.apply(classify_supplier, axis=1)
    df = df[df["ספק_משויך"] != "לא מזוהה"]

    df["match_card"] = df["טוקן"].apply(clean_card)
    df["match_amount"] = df["סכום"].apply(clean_amount)

    if "מספר אישור" in df.columns:
        df["match_auth"] = df["מספר אישור"].apply(clean_auth)
    else:
        df["match_auth"] = ""

    def extract_credit_pnr(row):
        pnr_raw = str(row["מספר הזמנה_נקי"]).split(".")[0].strip()
        pnr_str = re.sub(r"\D", "", pnr_raw)
        
        if row["ספק_משויך"] == "גלבוע":
            return pnr_str.lstrip("0")[:8]
        
        pnr_clean = pnr_str.lstrip("0")
        return pnr_clean[-6:] if len(pnr_clean) >= 6 else pnr_clean

    df["match_pnr"] = df.apply(extract_credit_pnr, axis=1)
    return df


# =====================================================================
# תהליך ההתאמה הראשי
# =====================================================================

def run_reconciliation(
    credit_file,
    output_folder,
    gilboa_file="",
    agency_file="",
    odyssey_file="",
    booster_file="",
    log_func=None,
):
    def log(message):
        if log_func:
            log_func(message)

    log("התחלת ריצה: טעינת פרמטרים...")

    if not credit_file:
        raise ValueError("יש לבחור קובץ קרדיט 2000.")

    if not output_folder:
        raise ValueError("יש לבחור תיקיית פלט.")

    if not os.path.isfile(credit_file):
        raise FileNotFoundError(f"קובץ קרדיט 2000 לא נמצא: {credit_file}")

    allowed_ext = {".xlsx", ".xls", ".csv", ".txt"}
    credit_ext = os.path.splitext(credit_file)[1].lower()
    if credit_ext not in allowed_ext:
        raise ValueError(f"סוג קובץ לא נתמך לקרדיט 2000: {credit_ext}")

    supplier_files = {
        "גלבוע": gilboa_file,
        "אייגנסי": agency_file,
        "אודיסאה": odyssey_file,
        "בוסטר": booster_file,
    }

    if not any(path for path in supplier_files.values()):
        raise ValueError("יש לבחור לפחות קובץ ספק אחד.")

    for supplier_name, file_path in supplier_files.items():
        if file_path and not os.path.isfile(file_path):
            raise FileNotFoundError(f"קובץ הספק לא נמצא ({supplier_name}): {file_path}")
        if file_path:
            supplier_ext = os.path.splitext(file_path)[1].lower()
            if supplier_ext not in allowed_ext:
                raise ValueError(f"סוג קובץ לא נתמך עבור {supplier_name}: {supplier_ext}")

    os.makedirs(output_folder, exist_ok=True)
    log("תיקיית הפלט מוכנה.")

    log("טוען קובץ קרדיט 2000...")
    df_credit = load_credit_2000(credit_file)
    log(f"נטענו {len(df_credit)} רשומות מקרדיט 2000.")

    suppliers_dfs = []
    if gilboa_file:
        log("טוען קובץ ספק: גלבוע...")
        suppliers_dfs.append(load_gilboa(gilboa_file))
    if agency_file:
        log("טוען קובץ ספק: אייגנסי...")
        suppliers_dfs.append(load_agency(agency_file))
    if odyssey_file:
        log("טוען קובץ ספק: אודיסאה...")
        suppliers_dfs.append(load_odyssey(odyssey_file))
    if booster_file:
        log("טוען קובץ ספק: בוסטר...")
        suppliers_dfs.append(load_booster(booster_file))

    if not suppliers_dfs:
        raise ValueError("לא נבחרו קבצי ספקים תקינים לעיבוד.")

    df_all_suppliers = pd.concat(suppliers_dfs, ignore_index=True)
    log(f"נטענו {len(df_all_suppliers)} רשומות מכלל הספקים.")

    df_credit["credit_uid"] = range(len(df_credit))
    df_all_suppliers["supplier_uid"] = range(len(df_all_suppliers))

    # 1. התאמה עבור גלבוע
    matched_gilboa = pd.merge(
        df_credit[df_credit["ספק_משויך"] == "גלבוע"],
        df_all_suppliers[df_all_suppliers["source_supplier"] == "גלבוע"],
        left_on=["match_card", "match_amount", "match_auth", "ספק_משויך"],
        right_on=["match_card", "match_amount", "match_auth", "source_supplier"],
        how="inner"
    )

    # 2. התאמה עבור אייגנסי ובוסטר
    matched_with_auth = pd.merge(
        df_credit[df_credit["ספק_משויך"].isin(["אייגנסי", "בוסטר"])],
        df_all_suppliers[df_all_suppliers["source_supplier"].isin(["אייגנסי", "בוסטר"])],
        left_on=["match_card", "match_amount", "match_pnr", "match_auth", "ספק_משויך"],
        right_on=["match_card", "match_amount", "match_pnr", "match_auth", "source_supplier"],
        how="inner",
    )

    # 3. התאמה עבור אודיסאה
    matched_odyssey = pd.merge(
        df_credit[df_credit["ספק_משויך"] == "אודיסאה"],
        df_all_suppliers[df_all_suppliers["source_supplier"] == "אודיסאה"],
        left_on=["match_card", "match_amount", "match_pnr", "ספק_משויך"],
        right_on=["match_card", "match_amount", "match_pnr", "source_supplier"],
        how="inner",
    )

    matched_all = pd.concat([matched_gilboa, matched_with_auth, matched_odyssey], ignore_index=True)
    matched_all = matched_all.drop_duplicates(subset=["credit_uid", "supplier_uid"])
    log(f"הושלמו התאמות: {len(matched_all)}.")

    matched_credit_uids = matched_all["credit_uid"].unique()
    df_only_in_credit = df_credit[~df_credit["credit_uid"].isin(matched_credit_uids)]

    matched_supplier_uids = matched_all["supplier_uid"].unique()
    df_only_in_suppliers = df_all_suppliers[~df_all_suppliers["supplier_uid"].isin(matched_supplier_uids)]
    log(f"רק בקרדיט: {len(df_only_in_credit)} | רק בספקים: {len(df_only_in_suppliers)}")

    # =====================================================================
    # יצירת דוחות ספציפיים לפי עמודות מבוקשות
    # =====================================================================
    
    credit_cols = ["מסוף", "טוקן", "מספר אישור", "סכום", "מספר הזמנה", "ספק_משויך"]

    for col in credit_cols:
        if col not in df_credit.columns:
            df_credit[col] = ""

    supplier_cols_dict = {
        "בוסטר": ["Payment Method", "Amount", "Credit Account Name", "Description"],
        "אייגנסי": ["4 ספרות אחרונות", "סכום מטבע ראשי", "מס' תיק", "מספר אישור"],
        "אודיסאה": ["Card", "Amount", "Pnr"],
        "גלבוע": ["Details", "origin amount", "ref"]
    }

    path_matched = os.path.join(output_folder, "1_התאמה_מלאה.xlsx")
    path_credit = os.path.join(output_folder, "2_רק_בקרדיט_2000.xlsx")
    path_suppliers = os.path.join(output_folder, "3_רק_בדוחות_הספקים.xlsx")
    path_log = os.path.join(output_folder, "LOGER.log")

    # --- יצירת קובץ 1: התאמה מלאה ---
    with pd.ExcelWriter(path_matched, engine="openpyxl") as writer:
        has_sheets = False
        for supplier, sup_cols in supplier_cols_dict.items():
            df_sup_matched = matched_all[matched_all["ספק_משויך"] == supplier].copy()
            if not df_sup_matched.empty:
                rename_map = {}
                for c in credit_cols:
                    if c in df_sup_matched.columns:
                        rename_map[c] = f"{c} - קרדיט"
                    elif f"{c}_x" in df_sup_matched.columns:
                        rename_map[f"{c}_x"] = f"{c} - קרדיט"
                    elif f"{c}_y" in df_sup_matched.columns:
                        rename_map[f"{c}_y"] = f"{c} - קרדיט"

                for c in sup_cols:
                    if c in df_sup_matched.columns:
                        rename_map[c] = f"{c} - {supplier}"
                    elif f"{c}_y" in df_sup_matched.columns:
                        rename_map[f"{c}_y"] = f"{c} - {supplier}"
                    elif f"{c}_x" in df_sup_matched.columns:
                        rename_map[f"{c}_x"] = f"{c} - {supplier}"

                df_sup_matched.rename(columns=rename_map, inplace=True)

                current_credit_cols = [f"{c} - קרדיט" for c in credit_cols if f"{c} - קרדיט" in df_sup_matched.columns]
                current_sup_cols = [f"{c} - {supplier}" for c in sup_cols if f"{c} - {supplier}" in df_sup_matched.columns]

                final_cols = current_credit_cols + current_sup_cols
                df_sup_matched[final_cols].to_excel(writer, sheet_name=supplier, index=False)
                has_sheets = True
        
        if not has_sheets:
            pd.DataFrame(columns=[f"{c} - קרדיט" for c in credit_cols]).to_excel(writer, sheet_name="אין נתונים", index=False)

    # --- יצירת קובץ 2: רק בקרדיט 2000 ---
    df_only_in_credit_clean = df_only_in_credit[credit_cols].copy()
    df_only_in_credit_clean.to_excel(path_credit, index=False)

    # --- יצירת קובץ 3: רק בדוחות הספקים ---
    with pd.ExcelWriter(path_suppliers, engine="openpyxl") as writer:
        has_sheets_sup = False
        for supplier, sup_cols in supplier_cols_dict.items():
            df_sup_missing = df_only_in_suppliers[df_only_in_suppliers["source_supplier"] == supplier].copy()
            if not df_sup_missing.empty:
                current_sup_cols = [c for c in sup_cols if c in df_sup_missing.columns]
                if current_sup_cols:
                    df_sup_missing[current_sup_cols].to_excel(writer, sheet_name=supplier, index=False)
                    has_sheets_sup = True
                    
        if not has_sheets_sup:
            pd.DataFrame(columns=["אין נתונים"]).to_excel(writer, sheet_name="אין נתונים", index=False)

    dashboard_data = compute_supplier_dashboard_data(
        df_credit=df_credit,
        df_all_suppliers=df_all_suppliers,
        matched_all=matched_all,
        df_only_in_credit=df_only_in_credit,
        df_only_in_suppliers=df_only_in_suppliers,
        supplier_cols_dict=supplier_cols_dict,
    )

    log("כתיבת קבצי הפלט הושלמה בהצלחה.")

    return {
        "matched": path_matched,
        "credit_only": path_credit,
        "suppliers_only": path_suppliers,
        "output_folder": output_folder,
        "log_file": path_log,
        "dashboard_data": dashboard_data,
    }


class ReconciliationWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("כלי התאמות קרדיט 2000")
        self.setMinimumSize(1200, 760)
        self.resize(1440, 900)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._active_log_path = None
        self._dashboard_window = None
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(14)

        title = make_rtl_label("התאמת קרדיט 2000 מול ספקי גבייה", bold=True)
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        main_layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)

        subtitle = make_rtl_label("בחר תיקיית פלט, קובץ קרדיט 2000, וקבצי ספקים (אופציונלי לבחור חלק מהם).")
        subtitle.setStyleSheet("color: #444;")
        main_layout.addWidget(subtitle, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 6)

        self.output_edit = self._add_row(grid, 0, "תיקיית פלט", self._browse_output_folder, is_folder=True)
        self.credit_edit = self._add_row(grid, 1, "קובץ סולק קרדיט 2000", self._browse_credit_file)
        self.gilboa_edit = self._add_row(grid, 2, "ספק גבייה - גילבוע", self._browse_gilboa_file)
        self.agency_edit = self._add_row(grid, 3, "ספק גבייה - אייג'נסי", self._browse_agency_file)
        self.odyssey_edit = self._add_row(grid, 4, "ספק גבייה - אודיסאה", self._browse_odyssey_file)
        self.booster_edit = self._add_row(grid, 5, "ספק גבייה - בוסטר", self._browse_booster_file)

        main_layout.addLayout(grid)

        self.status_label = make_rtl_label("מצב: מוכן")
        self.status_label.setStyleSheet("color: #666;")
        main_layout.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setMinimumHeight(260)
        self.log_view.setStyleSheet(
            "QTextEdit { background-color: #000000; color: #d8ffd8; border: 1px solid #333; }"
        )
        main_layout.addWidget(make_rtl_label("לוג פעילות:"), alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
        main_layout.addWidget(self.log_view)

        self.run_button = QPushButton("הפעל התאמה")
        self.run_button.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.run_button.clicked.connect(self._on_run_clicked)
        self.run_button.setMinimumHeight(46)
        main_layout.addWidget(self.run_button)

        self.setLayout(main_layout)

    def _add_row(self, grid, row_idx, label_text, browse_handler, is_folder=False):
        label = make_rtl_label(label_text)
        browse_button = QPushButton("בחירה")
        browse_button.setMinimumWidth(130)
        browse_button.setMinimumHeight(34)
        browse_button.clicked.connect(browse_handler)

        line_edit = QLineEdit()
        line_edit.setReadOnly(True)
        line_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        line_edit.setAlignment(ALIGN_RTL)
        line_edit.setFont(QFont("Arial", 10))
        line_edit.setMinimumHeight(34)
        line_edit.setPlaceholderText("לא נבחר" if not is_folder else "לא נבחרה תיקייה")

        # With RTL layout mirroring: logical columns 0,1,2 are shown as right, middle, left.
        # This gives the requested visual order: label -> button -> selected path.
        grid.addWidget(label, row_idx, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
        grid.addWidget(browse_button, row_idx, 1, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
        grid.addWidget(line_edit, row_idx, 2)
        return line_edit

    def _browse_file(self, target_edit, title):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "Excel or Text Files (*.xlsx *.xls *.csv *.txt);;All Files (*)",
        )
        if file_path:
            target_edit.setText(file_path)

    def _browse_folder(self, target_edit, title):
        folder_path = QFileDialog.getExistingDirectory(self, title)
        if folder_path:
            target_edit.setText(folder_path)

    def _browse_output_folder(self):
        self._browse_folder(self.output_edit, "בחר תיקיית פלט")

    def _browse_credit_file(self):
        self._browse_file(self.credit_edit, "בחר את קובץ קרדיט 2000")

    def _browse_gilboa_file(self):
        self._browse_file(self.gilboa_edit, "בחר קובץ ספק - GILBOA")

    def _browse_agency_file(self):
        self._browse_file(self.agency_edit, "בחר קובץ ספק - AGENCY")

    def _browse_odyssey_file(self):
        self._browse_file(self.odyssey_edit, "בחר קובץ ספק - ODYSSEY")

    def _browse_booster_file(self):
        self._browse_file(self.booster_edit, "בחר קובץ ספק - BOOSTER")

    def _show_message(self, title, text, icon):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(icon)
        msg.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        msg.exec()

    def _append_log(self, message):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}"
        self.log_view.append(line)

        if self._active_log_path:
            with open(self._active_log_path, "a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")

        # Force repaint while running on the UI thread so logs are visible progressively.
        QCoreApplication.processEvents()

    def _start_live_log(self, output_folder):
        os.makedirs(output_folder, exist_ok=True)
        self._active_log_path = os.path.join(output_folder, "LOGER.log")
        with open(self._active_log_path, "w", encoding="utf-8") as log_file:
            log_file.write("")
        return self._active_log_path

    def _finish_live_log(self):
        log_path = self._active_log_path
        self._active_log_path = None
        return log_path

    def _on_run_clicked(self):
        credit_file = self.credit_edit.text().strip()
        output_folder = self.output_edit.text().strip()
        gilboa_file = self.gilboa_edit.text().strip()
        agency_file = self.agency_edit.text().strip()
        odyssey_file = self.odyssey_edit.text().strip()
        booster_file = self.booster_edit.text().strip()

        if not credit_file:
            self._show_message("שגיאת קלט", "יש לבחור קובץ קרדיט 2000.", QMessageBox.Icon.Warning)
            return

        if not output_folder:
            self._show_message("שגיאת קלט", "יש לבחור תיקיית פלט.", QMessageBox.Icon.Warning)
            return

        if not any([gilboa_file, agency_file, odyssey_file, booster_file]):
            self._show_message("שגיאת קלט", "יש לבחור לפחות קובץ ספק אחד.", QMessageBox.Icon.Warning)
            return

        self.run_button.setEnabled(False)
        self.status_label.setText("מצב: מעבד נתונים...")
        self.log_view.clear()
        log_path = self._start_live_log(output_folder)
        self._append_log("הריצה התחילה.")

        try:
            result = run_reconciliation(
                credit_file=credit_file,
                output_folder=output_folder,
                gilboa_file=gilboa_file,
                agency_file=agency_file,
                odyssey_file=odyssey_file,
                booster_file=booster_file,
                log_func=self._append_log,
            )
            self.status_label.setText("מצב: הושלם בהצלחה")
            self._append_log("הריצה הסתיימה בהצלחה.")
            if log_path:
                self._append_log(f"לוג נכתב לקובץ: {log_path}")

            dashboard_data = result.get("dashboard_data")
            if dashboard_data:
                self._dashboard_window = SupplierReconciliationDashboard(dashboard_data, self)
                self._dashboard_window.showMaximized()

            self._show_message(
                "הצלחה",
                "הדוחות נוצרו בהצלחה:\n"
                f"{result['matched']}\n"
                f"{result['credit_only']}\n"
                f"{result['suppliers_only']}\n"
                f"LOGER: {log_path}",
                QMessageBox.Icon.Information,
            )
        except Exception as exc:
            self.status_label.setText("מצב: שגיאה")
            self._append_log(f"שגיאה: {exc}")
            if log_path:
                self._append_log(f"לוג שגיאה נשמר: {log_path}")
            self._show_message(
                "שגיאה במהלך העיבוד",
                f"אירעה שגיאה:\n{exc}",
                QMessageBox.Icon.Critical,
            )
        finally:
            self._finish_live_log()
            self.run_button.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setFont(QFont("Arial", 11))

    window = ReconciliationWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())