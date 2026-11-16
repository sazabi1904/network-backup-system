
"""TV4: Tong hop va xuat bao cao sao luu CSV/XLSX."""

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


class BackupReport:
    CSV_HEADERS = (
        "Thiet bi", "So ban backup", "Ngay backup", "Gio backup",
        "Trang thai", "Ma phien ban", "Ma loi",
    )
    XLSX_HEADERS = (
        "Thiết bị", "Số bản backup", "Ngày backup", "Giờ backup",
        "Trạng thái", "Mã phiên bản", "Mã lỗi",
    )
    STATUS_CSV = {
        "HAS_BACKUP": "Da sao luu", "NO_BACKUP": "Chua sao luu", "ERROR": "Loi du lieu",
    }
    STATUS_XLSX = {
        "HAS_BACKUP": "Đã sao lưu", "NO_BACKUP": "Chưa sao lưu", "ERROR": "Lỗi dữ liệu",
    }
    COLORS = {
        "navy": "17365D", "blue": "245A81", "white": "FFFFFF",
        "stripe": "EDF4FA", "grid": "CAD2DD", "border": "65758B",
        "HAS_BACKUP": "DCFCE7", "NO_BACKUP": "FFF2CC", "ERROR": "FCE8E6",
    }
    WIDTHS = {"A": 16, "B": 19, "C": 19, "D": 17, "E": 21, "F": 43, "G": 20}
    VN_TZ = timezone(timedelta(hours=7))

    def __init__(self, manager):
        self.manager = manager

    @staticmethod
    def _parse_time(value):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    @classmethod
    def format_time(cls, captured_at):
        dt = cls._parse_time(captured_at).astimezone(cls.VN_TZ)
        return dt.strftime("%d/%m/%Y"), dt.strftime("%H:%M:%S")

    @staticmethod
    def _safe_text(value):
        text = str(value or "")
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    def summarize(self, device_names):
        result = []
        for name in dict.fromkeys(device_names):
            row = dict(device=name, backup_count=0, backup_date="", backup_time="",
                       status="NO_BACKUP", latest_snapshot_id="", error_code="")
            try:
                versions = self.manager.list_snapshots(name)
                row["backup_count"] = len(versions)
                if versions:
                    latest = max(versions, key=lambda x: self._parse_time(x.captured_at))
                    row["backup_date"], row["backup_time"] = self.format_time(latest.captured_at)
                    row["latest_snapshot_id"] = latest.snapshot_id
                    row["status"] = "HAS_BACKUP"
            except Exception as exc:
                row.update(backup_count=None, status="ERROR", error_code=type(exc).__name__)
            result.append(row)
        return result

    def _values(self, row, is_xlsx=False):
        labels = self.STATUS_XLSX if is_xlsx else self.STATUS_CSV
        return [
            self._safe_text(row["device"]), row["backup_count"],
            row["backup_date"], row["backup_time"],
            labels[row["status"]], self._safe_text(row["latest_snapshot_id"]),
            row["error_code"],
        ]

    def export_csv(self, device_names, path="reports/backup_report.csv"):
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open("w", newline="", encoding="utf-8-sig") as file:
                file.write("sep=;\n")  # CSV kieu cu: phan cach ;, nhan khong dau
                writer = csv.writer(file, delimiter=";")
                writer.writerow(self.CSV_HEADERS)
                writer.writerows(self._values(row) for row in self.summarize(device_names))
        except PermissionError as exc:
            raise PermissionError("Hay dong file CSV dang mo trong Excel.") from exc
        return output

    @staticmethod
    def _border(color):
        side = Side(style="thin", color=color)
        return Border(left=side, right=side, top=side, bottom=side)

    def _style_cell(self, cell, *, fill=None, color="243447", bold=False,
                    size=11, align="center", border=None):
        cell.font = Font(name="Calibri", size=size, bold=bold, color=color)
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        if border:
            cell.border = border

    def export_xlsx(self, device_names, path="reports/backup_report.xlsx"):
        rows = self.summarize(device_names)
        wb = Workbook()
        ws = wb.active
        ws.title = "Báo cáo Backup"
        ws.sheet_view.showGridLines = True
        c = self.COLORS
        grid = self._border(c["grid"])
        strong = self._border(c["border"])

        # Ke luoi ca vung trong (A:M, toi thieu 60 hang).
        for line in ws.iter_rows(min_row=1, max_row=max(60, len(rows) + 20),
                                 min_col=1, max_col=13):
            for cell in line:
                cell.border = grid

        # Tieu de + phu de.
        for line in ws.iter_rows(min_row=1, max_row=2, min_col=1, max_col=7):
            for cell in line:
                cell.fill = PatternFill("solid", fgColor=c["navy"])
        ws.merge_cells("A1:G2")
        ws["A1"] = "BÁO CÁO TỔNG HỢP SAO LƯU CẤU HÌNH THIẾT BỊ MẠNG"
        self._style_cell(ws["A1"], fill=c["navy"], color=c["white"], bold=True, size=15)
        ws.merge_cells("A3:G3")
        ws["A3"] = "NETWORK CONFIGURATION BACKUP REPORT"
        self._style_cell(ws["A3"], color="66788A", size=10)
        ws.row_dimensions[1].height = ws.row_dimensions[2].height = 24
        ws.row_dimensions[3].height = 23

        # Thong ke, co vien cho moi o A5:G6 (ke ca o trong).
        for line in ws.iter_rows(min_row=5, max_row=6, min_col=1, max_col=7):
            for cell in line:
                self._style_cell(cell, fill="E8F0F8", border=strong)
        stats = [
            ("A", "Tổng thiết bị", len(rows)),
            ("C", "Đã sao lưu", sum(r["status"] == "HAS_BACKUP" for r in rows)),
            ("E", "Chưa sao lưu", sum(r["status"] == "NO_BACKUP" for r in rows)),
            ("G", "Lỗi dữ liệu", sum(r["status"] == "ERROR" for r in rows)),
        ]
        for col, label, count in stats:
            ws[f"{col}5"] = label
            ws[f"{col}6"] = count
            self._style_cell(ws[f"{col}5"], fill="E8F0F8", color=c["blue"], bold=True, size=10, border=strong)
            self._style_cell(ws[f"{col}6"], fill="E8F0F8", color=c["navy"], bold=True, size=19, border=strong)
        ws.row_dimensions[5].height = 25
        ws.row_dimensions[6].height = 33

        # Bang du lieu.
        for col, header in enumerate(self.XLSX_HEADERS, 1):
            cell = ws.cell(9, col, header)
            self._style_cell(cell, fill=c["blue"], color=c["white"], bold=True, border=strong)
        ws.row_dimensions[9].height = 30

        for i, row in enumerate(rows, 10):
            for j, value in enumerate(self._values(row, is_xlsx=True), 1):
                cell = ws.cell(i, j, value if j not in (3, 4) else None)
                self._style_cell(cell, fill=c["stripe"] if i % 2 == 0 else c["white"],
                                 align="left" if j in (1, 5, 6, 7) else "center", border=strong)
            if row["backup_date"]:
                ws.cell(i, 3, datetime.strptime(row["backup_date"], "%d/%m/%Y").date())
                ws.cell(i, 3).number_format = "dd/mm/yyyy"
            if row["backup_time"]:
                ws.cell(i, 4, datetime.strptime(row["backup_time"], "%H:%M:%S").time())
                ws.cell(i, 4).number_format = "hh:mm:ss"
            self._style_cell(ws.cell(i, 5), fill=c[row["status"]], bold=True,
                             align="left", border=strong)
            ws.row_dimensions[i].height = 26

        for col, width in self.WIDTHS.items():
            ws.column_dimensions[col].width = width
        for col in "HIJKLM":
            ws.column_dimensions[col].width = 12
        ws.freeze_panes = "A10"
        if rows:
            ws.auto_filter.ref = f"A9:G{9 + len(rows)}"
        ws.print_area = f"A1:G{max(13, 9 + len(rows))}"
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.print_title_rows = "1:9"

        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            wb.save(output)
        except PermissionError as exc:
            raise PermissionError("Hay dong file XLSX dang mo trong Excel.") from exc
        return output
