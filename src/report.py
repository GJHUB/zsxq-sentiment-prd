"""报告生成模块 - Excel报告"""

import logging
import os
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from .config import get_config

logger = logging.getLogger(__name__)

OUTLOOK_COLORS = {
    "看多": "C6EFCE",
    "看空": "FFC7CE",
    "中性": "FFEB9C",
    "分歧": "B4C6E7",
}


class ReportGenerator:
    """Excel报告生成器"""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or get_config("output_dir", "output")
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(
        self,
        analysis: pd.DataFrame,
        topics: list[dict],
        date: str = None,
    ) -> str:
        """
        生成Excel报告
        - Sheet1: 财经相关帖子分析
        - Sheet2: 全部帖子概览
        返回文件路径
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        filename = f"舆情分析_{date}.xlsx"
        filepath = os.path.join(self.output_dir, filename)

        try:
            wb = Workbook()
            self._create_financial_sheet(wb, analysis)
            self._create_overview_sheet(wb, analysis)
            self._apply_styles(wb)
            wb.save(filepath)
            logger.info("报告已生成: %s", filepath)
            return filepath
        except Exception as e:
            logger.error("Excel生成失败，降级到CSV: %s", e)
            return self._fallback_csv(analysis, date)

    def _create_financial_sheet(self, wb: Workbook, df: pd.DataFrame) -> None:
        """创建财经分析Sheet（仅财经相关帖子）"""
        ws = wb.active
        ws.title = "财经分析"

        headers = ["时间", "作者", "群主帖子", "金融产品", "具体标的", "看法", "群主看法", "群主理由", "原因分析", "核心观点", "帖子摘要"]
        ws.append(headers)

        if df.empty:
            ws.append(["暂无数据"])
            return

        financial_df = df[df["is_financial"] == True].copy()
        if financial_df.empty:
            ws.append(["无财经相关内容"])
            return

        for _, row in financial_df.iterrows():
            targets = row.get("targets", [])
            if isinstance(targets, list):
                targets_str = "、".join(str(t) for t in targets)
            else:
                targets_str = str(targets)

            ws.append([
                str(row.get("create_time", ""))[:19],
                row.get("author", ""),
                "是" if row.get("is_owner_post") else "否",
                row.get("product_type", ""),
                targets_str,
                row.get("outlook", ""),
                row.get("owner_outlook", "无"),
                row.get("owner_reason", "无"),
                row.get("reason", ""),
                row.get("summary", ""),
                row.get("post_excerpt", "")[:200],
            ])

    def _create_overview_sheet(self, wb: Workbook, df: pd.DataFrame) -> None:
        """创建全部帖子概览Sheet"""
        ws = wb.create_sheet("全部帖子")

        headers = ["时间", "作者", "群主帖子", "是否财经", "金融产品", "具体标的", "看法", "群主看法", "核心观点", "评论数"]
        ws.append(headers)

        if df.empty:
            ws.append(["暂无数据"])
            return

        for _, row in df.iterrows():
            targets = row.get("targets", [])
            if isinstance(targets, list):
                targets_str = "、".join(str(t) for t in targets)
            else:
                targets_str = str(targets)

            ws.append([
                str(row.get("create_time", ""))[:19],
                row.get("author", ""),
                "是" if row.get("is_owner_post") else "否",
                "是" if row.get("is_financial") else "否",
                row.get("product_type", ""),
                targets_str,
                row.get("outlook", ""),
                row.get("owner_outlook", "无"),
                row.get("summary", ""),
                row.get("comments_count", 0),
            ])

    def _apply_styles(self, wb: Workbook) -> None:
        """应用样式"""
        header_font = Font(bold=True, size=11, color="FFFFFF")
        header_fill = PatternFill(
            start_color="4472C4", end_color="4472C4", fill_type="solid"
        )
        header_alignment = Alignment(horizontal="center", vertical="center")
        thin_border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )

        for ws in wb.worksheets:
            for cell in ws[1]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border

            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                for cell in row:
                    cell.border = thin_border
                    cell.alignment = Alignment(vertical="center", wrap_text=True)

            # 自动列宽
            for col in ws.columns:
                max_length = 0
                col_letter = col[0].column_letter
                for cell in col:
                    try:
                        val = str(cell.value or "")
                        length = sum(2 if ord(c) > 127 else 1 for c in val)
                        max_length = max(max_length, length)
                    except Exception:
                        pass
                ws.column_dimensions[col_letter].width = min(max_length + 4, 60)

            # 看法列着色
            self._apply_outlook_colors(ws)

    def _apply_outlook_colors(self, ws) -> None:
        """为看法列添加颜色"""
        header_row = [cell.value for cell in ws[1]]
        outlook_col = None
        for idx, h in enumerate(header_row):
            if h == "看法":
                outlook_col = idx
                break

        if outlook_col is None:
            return

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            cell = row[outlook_col]
            val = str(cell.value or "")
            color = OUTLOOK_COLORS.get(val)
            if color:
                cell.fill = PatternFill(
                    start_color=color, end_color=color, fill_type="solid"
                )

    def _fallback_csv(self, df: pd.DataFrame, date: str) -> str:
        """降级到CSV"""
        filename = f"舆情分析_{date}.csv"
        filepath = os.path.join(self.output_dir, filename)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info("CSV报告已生成（降级）: %s", filepath)
        return filepath
