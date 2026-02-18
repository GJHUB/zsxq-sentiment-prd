"""AI情绪分析模块 - 深度财经分析"""

import json
import logging
import re

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import get_config

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """你是一个专业的财经分析师。请分析以下知识星球帖子及其评论内容。

帖子内容：
{post_text}

评论内容：
{comments_text}

请分析以下要点：
1. 该内容是否涉及股票、期货、区块链等财经相关话题？（是/否）
2. 如果是财经相关：
   - 涉及的金融产品类型（股票/期货/区块链/基金/债券/其他）
   - 具体标的（如果是股票，具体哪只股票及代码；如果是期货，具体哪个品种；如果是区块链，具体哪个币种）
   - 作者及评论者的整体看法（看多/看空/中性/分歧）
   - 具体原因和逻辑分析

请以JSON格式返回：
{{
    "is_financial": true/false,
    "product_type": "股票/期货/区块链/基金/其他/无",
    "targets": ["具体标的1", "具体标的2"],
    "outlook": "看多/看空/中性/分歧/无",
    "reason": "具体原因和逻辑（简要概括）",
    "summary": "一句话总结该帖子的核心观点"
}}

只返回JSON，不要其他内容。如果不涉及财经话题，is_financial设为false，其他字段填"无"。"""


class SentimentAnalyzer:
    """AI深度财经分析器"""

    def __init__(
        self,
        openai_api_key: str = None,
        anthropic_api_key: str = None,
    ):
        self.openai_api_key = openai_api_key or get_config("openai_api_key")
        self.anthropic_api_key = anthropic_api_key or get_config("anthropic_api_key")

    async def analyze_topics(self, topics: list[dict]) -> pd.DataFrame:
        """分析所有帖子，返回DataFrame"""
        results = []

        # 财经关键词预过滤
        finance_keywords = [
            "股", "基金", "期货", "债券", "涨", "跌", "买入", "卖出",
            "仓", "多", "空", "牛", "熊", "板块", "行情", "大盘",
            "指数", "K线", "均线", "macd", "ETF", "A股", "港股", "美股",
            "比特币", "BTC", "ETH", "币", "区块链", "加密", "合约",
            "原油", "黄金", "白银", "铜", "螺纹", "豆粕",
            "利率", "降息", "加息", "通胀", "GDP", "CPI",
        ]

        for i, topic in enumerate(topics):
            post_text = topic.get("text", "").strip()
            if not post_text:
                continue

            comments = topic.get("comments", [])
            all_text = post_text + " ".join(c.get("text", "") for c in comments)

            # 预过滤：不含财经关键词的直接跳过
            has_keyword = any(kw in all_text for kw in finance_keywords)
            if not has_keyword:
                results.append({
                    "is_financial": False,
                    "product_type": "无",
                    "targets": [],
                    "outlook": "无",
                    "reason": "",
                    "summary": "非财经内容",
                    "author": topic.get("author", "未知"),
                    "create_time": topic.get("create_time", ""),
                    "post_excerpt": post_text[:300],
                    "comments_count": len(comments),
                })
                continue

            logger.info("分析第 %d/%d 条帖子（含财经关键词）...", i + 1, len(topics))

            comments_text = "\n".join(
                f"- {c.get('author', '匿名')}: {c.get('text', '')}"
                for c in comments
                if c.get("text")
            ) or "（无评论）"

            # 调用AI分析，加间隔避免打挂API
            import asyncio
            await asyncio.sleep(5)

            try:
                analysis = await self._analyze_single(post_text, comments_text)
            except Exception as e:
                logger.error("分析帖子失败: %s", e)
                analysis = {
                    "is_financial": False,
                    "product_type": "无",
                    "targets": [],
                    "outlook": "无",
                    "reason": f"分析失败: {e}",
                    "summary": "分析失败",
                }

            analysis.update({
                "author": topic.get("author", "未知"),
                "create_time": topic.get("create_time", ""),
                "post_excerpt": post_text[:300],
                "comments_count": len(comments),
            })
            results.append(analysis)

        df = pd.DataFrame(results)
        financial_count = len(df[df["is_financial"] == True]) if not df.empty else 0
        logger.info("分析完成，共 %d 条帖子，其中 %d 条涉及财经", len(df), financial_count)
        return df

    async def _analyze_single(self, post_text: str, comments_text: str) -> dict:
        """分析单个帖子"""
        prompt = ANALYSIS_PROMPT.format(
            post_text=post_text[:2000],
            comments_text=comments_text[:2000],
        )
        result = await self._call_ai_api(prompt)
        return self._parse_result(result)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=10, max=120),
    )
    async def _call_ai_api(self, prompt: str) -> str:
        """调用AI API，带重试和降级"""
        if self.anthropic_api_key:
            try:
                return await self._call_claude(prompt)
            except Exception as e:
                logger.warning("Claude API失败: %s", e)
                if self.openai_api_key:
                    logger.info("降级到OpenAI...")
                    return await self._call_openai(prompt)
                raise

        if self.openai_api_key:
            return await self._call_openai(prompt)

        raise ValueError("未配置任何AI API密钥")

    async def _call_claude(self, prompt: str) -> str:
        """调用Claude API"""
        import anthropic
        client = anthropic.Anthropic(api_key=self.anthropic_api_key)
        message = client.messages.create(
            model=get_config("ai_model", "claude-3-sonnet-20240229"),
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    async def _call_openai(self, prompt: str) -> str:
        """调用OpenAI API"""
        from openai import OpenAI
        client = OpenAI(
            api_key=self.openai_api_key,
            base_url=get_config("openai_api_base", "https://api.openai.com/v1"),
        )
        response = client.chat.completions.create(
            model="moonshot-v1-32k",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )
        return response.choices[0].message.content

    @staticmethod
    def _parse_result(result: str) -> dict:
        """解析AI返回的JSON"""
        try:
            json_match = re.search(r"\{[\s\S]*\}", result)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "is_financial": bool(data.get("is_financial", False)),
                    "product_type": data.get("product_type", "无"),
                    "targets": data.get("targets", []),
                    "outlook": data.get("outlook", "无"),
                    "reason": data.get("reason", ""),
                    "summary": data.get("summary", ""),
                }
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("解析AI结果失败: %s", e)

        return {
            "is_financial": False,
            "product_type": "无",
            "targets": [],
            "outlook": "无",
            "reason": "解析失败",
            "summary": "解析失败",
        }
