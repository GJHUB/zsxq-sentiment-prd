"""AI情绪分析模块"""

import logging
import re
from typing import Optional

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import get_config

logger = logging.getLogger(__name__)

# 常见A股关键词映射（部分示例）
STOCK_KEYWORDS = {
    "茅台": "600519", "贵州茅台": "600519",
    "宁德时代": "300750", "比亚迪": "002594",
    "中芯国际": "688981", "腾讯": "00700",
    "阿里": "09988", "阿里巴巴": "09988",
    "招商银行": "600036", "招行": "600036",
    "平安": "601318", "中国平安": "601318",
    "万科": "000002", "美的": "000333",
    "格力": "000651", "格力电器": "000651",
    "隆基": "601012", "隆基绿能": "601012",
    "药明康德": "603259", "迈瑞医疗": "300760",
}

# 股票代码正则
STOCK_CODE_PATTERN = re.compile(r"(?<!\d)([036]\d{5})(?!\d)")


class SentimentAnalyzer:
    """AI情绪分析器"""

    def __init__(
        self,
        anthropic_api_key: str = None,
        openai_api_key: str = None,
        model: str = None,
    ):
        self.anthropic_api_key = anthropic_api_key or get_config("anthropic_api_key")
        self.openai_api_key = openai_api_key or get_config("openai_api_key")
        self.model = model or get_config("ai_model")
        self.batch_size = get_config("batch_size", 5)

    def extract_stocks(self, text: str) -> list[str]:
        """
        从文本提取股票
        - 正则匹配股票代码（6位数字）
        - 关键词匹配股票名称
        - 去重
        """
        stocks = set()

        # 正则匹配代码
        codes = STOCK_CODE_PATTERN.findall(text)
        stocks.update(codes)

        # 关键词匹配
        for name, code in STOCK_KEYWORDS.items():
            if name in text:
                stocks.add(code)

        return list(stocks)

    async def analyze_sentiment(self, text: str, stock: str) -> dict:
        """
        分析单条评论对某只股票的情绪
        返回: {"sentiment": "bullish/bearish/neutral", "confidence": 0.0-1.0, "reason": "..."}
        """
        prompt = self._build_single_prompt(text, stock)
        try:
            result = await self._call_ai_api(prompt)
            return self._parse_sentiment_result(result, stock)
        except Exception as e:
            logger.error("情绪分析失败 [%s]: %s", stock, e)
            return {
                "stock": stock,
                "sentiment": "neutral",
                "confidence": 0.0,
                "reason": f"分析失败: {e}",
            }

    async def analyze_batch(self, texts: list[str]) -> list[dict]:
        """
        批量分析，减少API调用次数
        - 每批最多batch_size条，合并为一次API请求
        - 失败时降级为单条处理
        """
        results = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            try:
                batch_result = await self._analyze_batch_request(batch)
                results.extend(batch_result)
            except Exception as e:
                logger.warning("批量分析失败，降级为单条处理: %s", e)
                for text in batch:
                    stocks = self.extract_stocks(text)
                    for stock in stocks:
                        result = await self.analyze_sentiment(text, stock)
                        result["text"] = text[:200]
                        results.append(result)
        return results

    async def analyze_topics(self, topics: list[dict]) -> pd.DataFrame:
        """分析所有帖子，返回汇总DataFrame"""
        all_results = []

        # 收集所有文本（帖子+评论）
        text_items = []
        for topic in topics:
            text_items.append({
                "text": topic.get("text", ""),
                "author": topic.get("author", "未知"),
                "create_time": topic.get("create_time", ""),
                "type": "topic",
            })
            for comment in topic.get("comments", []):
                text_items.append({
                    "text": comment.get("text", ""),
                    "author": comment.get("author", "未知"),
                    "create_time": comment.get("create_time", ""),
                    "type": "comment",
                })

        # 过滤有股票提及的文本
        relevant_items = []
        for item in text_items:
            stocks = self.extract_stocks(item["text"])
            if stocks:
                item["stocks"] = stocks
                relevant_items.append(item)

        logger.info("共 %d 条文本，其中 %d 条提及股票", len(text_items), len(relevant_items))

        if not relevant_items:
            return pd.DataFrame()

        # 批量分析
        texts_for_batch = [item["text"] for item in relevant_items]
        batch_results = await self.analyze_batch(texts_for_batch)

        # 合并元数据
        result_idx = 0
        for item in relevant_items:
            for stock in item.get("stocks", []):
                if result_idx < len(batch_results):
                    result = batch_results[result_idx]
                else:
                    result = {"sentiment": "neutral", "confidence": 0.0, "reason": ""}
                result.update({
                    "stock": stock,
                    "author": item["author"],
                    "create_time": item["create_time"],
                    "text_excerpt": item["text"][:200],
                    "content_type": item["type"],
                })
                all_results.append(result)
                result_idx += 1

        df = pd.DataFrame(all_results)
        logger.info("分析完成，共 %d 条结果", len(df))
        return df

    def generate_summary(self, stock: str, sentiments: list[dict]) -> str:
        """生成某只股票的综合总结"""
        if not sentiments:
            return "无数据"

        bullish = sum(1 for s in sentiments if s.get("sentiment") == "bullish")
        bearish = sum(1 for s in sentiments if s.get("sentiment") == "bearish")
        neutral = sum(1 for s in sentiments if s.get("sentiment") == "neutral")
        total = len(sentiments)

        reasons = [s.get("reason", "") for s in sentiments if s.get("reason")]
        top_reasons = reasons[:3]

        summary = f"共{total}条提及，看多{bullish}，看空{bearish}，中性{neutral}。"
        if top_reasons:
            summary += " 主要观点：" + "；".join(top_reasons)
        return summary

    async def _analyze_batch_request(self, texts: list[str]) -> list[dict]:
        """批量分析请求"""
        prompt = self._build_batch_prompt(texts)
        result = await self._call_ai_api(prompt)
        return self._parse_batch_result(result, texts)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, max=60),
    )
    async def _call_ai_api(self, prompt: str) -> str:
        """调用AI API，带重试和降级"""
        # 优先使用 Claude
        if self.anthropic_api_key:
            try:
                return await self._call_claude(prompt)
            except Exception as e:
                logger.warning("Claude API失败: %s", e)
                if self.openai_api_key:
                    logger.info("降级到OpenAI...")
                    return await self._call_openai(prompt)
                raise

        # 仅有 OpenAI
        if self.openai_api_key:
            return await self._call_openai(prompt)

        raise ValueError("未配置任何AI API密钥")

    async def _call_claude(self, prompt: str) -> str:
        """调用Claude API"""
        import anthropic

        client = anthropic.Anthropic(api_key=self.anthropic_api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    async def _call_openai(self, prompt: str) -> str:
        """调用OpenAI API"""
        from openai import OpenAI

        client = OpenAI(api_key=self.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )
        return response.choices[0].message.content

    @staticmethod
    def _build_single_prompt(text: str, stock: str) -> str:
        return f"""分析以下投资评论对股票 {stock} 的情绪倾向。

评论内容：
{text}

请以JSON格式返回：
{{"sentiment": "bullish/bearish/neutral", "confidence": 0.0-1.0, "reason": "简要判断依据"}}

只返回JSON，不要其他内容。"""

    @staticmethod
    def _build_batch_prompt(texts: list[str]) -> str:
        numbered = "\n".join(f"[{i+1}] {t[:300]}" for i, t in enumerate(texts))
        return f"""分析以下投资评论中提及的股票及情绪倾向。

评论列表：
{numbered}

对每条评论，识别提及的股票并分析情绪。以JSON数组格式返回：
[{{"index": 1, "stock": "股票代码或名称", "sentiment": "bullish/bearish/neutral", "confidence": 0.0-1.0, "reason": "简要依据"}}]

如果一条评论提及多只股票，为每只股票生成一条记录。只返回JSON数组。"""

    @staticmethod
    def _parse_sentiment_result(result: str, stock: str) -> dict:
        """解析单条分析结果"""
        import json

        try:
            # 尝试提取JSON
            json_match = re.search(r"\{[^}]+\}", result)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    "stock": stock,
                    "sentiment": data.get("sentiment", "neutral"),
                    "confidence": float(data.get("confidence", 0.5)),
                    "reason": data.get("reason", ""),
                }
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("解析结果失败: %s", e)

        return {
            "stock": stock,
            "sentiment": "neutral",
            "confidence": 0.0,
            "reason": "解析失败",
        }

    @staticmethod
    def _parse_batch_result(result: str, texts: list[str]) -> list[dict]:
        """解析批量分析结果"""
        import json

        try:
            json_match = re.search(r"\[[\s\S]*\]", result)
            if json_match:
                data = json.loads(json_match.group())
                return [
                    {
                        "stock": item.get("stock", ""),
                        "sentiment": item.get("sentiment", "neutral"),
                        "confidence": float(item.get("confidence", 0.5)),
                        "reason": item.get("reason", ""),
                        "text_excerpt": (
                            texts[item.get("index", 1) - 1][:200]
                            if item.get("index", 0) <= len(texts)
                            else ""
                        ),
                    }
                    for item in data
                ]
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("批量解析失败: %s", e)

        return [
            {"stock": "", "sentiment": "neutral", "confidence": 0.0, "reason": "批量解析失败"}
            for _ in texts
        ]
