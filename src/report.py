"""报告生成模块 - Excel报告"""

import logging
import os
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.dataframe import dataframe_to_rows

from .config import get_config

logger = logging.getLogger(__name__)

# 情绪颜色映射
SENTIMENT_COLORS = {
    "bullish": "C6EFCE",   # 绿色 - 看多
    "bearish": "FFC7CE",   # 红色 - 看空
    "neutral": "FFEB9C",   # 黄色 - 中性
}

SENTIMENT_LABELS = {
    "bullish": "看多",
    "bearish": "看空",
    "neutral": "中性",
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
        - Sheet1: 股票汇总
        - Sheet2: 评论明细
        返回文件路径
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        filename = f"舆情分析_{date}.xlsx"
        filepath = os.path.join(self.output_dir, filename)

        try:
            wb = Workbook()
            self._create_summary_sheet(wb, analysis, date)
            self._create_detail_sheet(wb, analysis)
            self._apply_styles(wb)
            wb.save(filepath)
            logger.info("报告已生成: %s", filepath)
            return filepath
        except Exception as e:
            logger.error("Excel生成失败，降级到CSV: %s", e)
            return self._fallback_csv(analysis, date)

    def _create_summary_sheet(
        self, wb: Workbook, df: pd.DataFrame, date: str
    ) -> None:
        """创建股票汇总Sheet"""
        ws = wb.active
        ws.title = "股票汇总"

        if df.empty:
            ws.append(["暂无数据"])
            return

        # 按股票分组统计
        summary_data = []
        for stock, group in df.groupby("stock"):
            total = len(group)
            bullish = len(group[group["sentiment"] == "bullish"])
            bearish = len(group[group["sentiment"] == "bearish"])
            neutral = len(group[group["sentiment"] == "neutral"])
            ratio = f"{bullish}:{bearish}" if bearish > 0 else f"{bullish}:0"
            avg_conf = group["confidence"].mean()

            # 生成AI总结
            reasons = group["reason"].dropna().tolist()
            ai_summary = "；".join(r for r in reasons[:3] if r)

            summary_data.append({
                "股票代码": stock,
                "提及次数": total,
                "看多": bullish,
                "看空": bearish,
                "中性": neutral,
                "多空比": ratio,
                "平均置信度": round(avg_conf, 2),
                "AI总结": ai_summary or "无",
            })

        summary_df = pd.DataFrame(summary_data)
        summary_df = summary_df.sort_values("提及次数", ascending=False)

        # 写入标题行
        headers = list(summary_df.columns)
        ws.append(headers)

        # 写入数据
        for _, row in summary_df.iterrows():
            ws.append(list(row))

    def _create_detail_sheet(self, wb: Workbook, df: pd.DataFrame) -> None:
        """创建评论明细Sheet"""
        ws = wb.create_sheet("评论明细")

        if df.empty:
            ws.append(["暂无数据"])
            return

        # 准备明细数据
        detail_df = df.copy()
        detail_df["情绪"] = detail_df["sentiment"].map(
            lambda x: SENTIMENT_LABELS.get(x, x)
        )
        detail_df = detail_df.rename(columns={
            "create_time": "时间",
            "author": "作者",
            "text_excerpt": "内容摘要",
            "stock": "提及股票",
            "confidence": "置信度",
            "reason": "判断依据",
        })

        columns = ["时间", "作者", "内容摘要", "提及股票", "情绪", "置信度", "判断依据"]
        available_cols = [c for c in columns if c in detail_df.columns]

        # 写入标题行
        ws.append(available_cols)

        # 写入数据
        for _, row in detail_df.iterrows():
            ws.append([row.get(c, "") for c in available_cols])

    def _apply_styles(self, wb: Workbook) -> None:
        """应用样式：表头加粗、列宽、条件格式等"""
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
            # 表头样式
            for cell in ws[1]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border

            # 数据行样式
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                for cell in row:
                    cell.border = thin_border
                    cell.alignment = Alignment(
                        vertical="center", wrap_text=True
                    )

            # 自动列宽（近似）
            for col in ws.columns:
                max_length = 0
                col_letter = col[0].column_letter
                for cell in col:
                    try:
                        val = str(cell.value or "")
                        # 中文字符算2个宽度
                        length = sum(2 if ord(c) > 127 else 1 for c in val)
                        max_length = max(max_length, length)
                    except Exception:
                        pass
                adjusted_width = min(max_length + 4, 50)
                ws.column_dimensions[col_letter].width = adjusted_width

            # 情绪列条件着色
            self._apply_sentiment_colors(ws)

    def _apply_sentiment_colors(self, ws) -> None:
        """为情绪列添加颜色"""
        # 找到情绪列
        header_row = [cell.value for cell in ws[1]]
        sentiment_col = None
        for idx, h in enumerate(header_row):
            if h in ("情绪", "sentiment"):
                sentiment_col = idx
                break

        if sentiment_col is None:
            return

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            cell = row[sentiment_col]
            val = str(cell.value or "")

            # 匹配中文或英文
            color = None
            if val in ("看多", "bullish"):
                color = SENTIMENT_COLORS["bullish"]
            elif val in ("看空", "bearish"):
                color = SENTIMENT_COLORS["bearish"]
            elif val in ("中性", "neutral"):
                color = SENTIMENT_COLORS["neutral"]

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
