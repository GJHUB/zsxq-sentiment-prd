"""爬虫模块 - 知识星球内容抓取"""

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from urllib3.util.retry import Retry

from .config import get_config

logger = logging.getLogger(__name__)


class RateLimiter:
    """请求限流器"""

    def __init__(self, requests_per_minute: int = 20):
        self.rpm = requests_per_minute
        self.interval = 60.0 / requests_per_minute
        self.last_request = 0.0

    async def wait(self):
        """等待直到可以发送下一个请求"""
        now = time.time()
        wait_time = self.interval - (now - self.last_request)
        if wait_time > 0:
            # 加随机抖动，模拟人工行为
            jitter = random.uniform(0.5, 2.0)
            await asyncio.sleep(wait_time + jitter)
        self.last_request = time.time()


class ZsxqCrawler:
    """知识星球爬虫"""

    BASE_URL = "https://api.zsxq.com/v2"

    def __init__(self, group_id: str = None, cookie: dict = None):
        self.group_id = group_id or get_config("group_id")
        self.cookie = cookie or {}
        self.rate_limiter = RateLimiter(
            requests_per_minute=get_config("requests_per_minute", 20)
        )
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """创建带重试的Session"""
        session = requests.Session()
        retry_strategy = Retry(
            total=get_config("max_retries", 3),
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # 设置默认headers
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookie.items())
        session.headers.update(
            {
                "Cookie": cookie_str,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Origin": "https://wx.zsxq.com",
                "Referer": "https://wx.zsxq.com/",
                "Accept": "application/json, text/plain, */*",
            }
        )
        return session

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=30),
        retry=retry_if_exception_type(
            (requests.exceptions.RequestException, requests.exceptions.Timeout)
        ),
        before_sleep=lambda rs: logger.warning(
            "请求失败，第%d次重试...", rs.attempt_number
        ),
    )
    def _fetch(self, url: str, params: dict = None) -> dict:
        """带重试的请求"""
        resp = self.session.get(
            url,
            params=params,
            timeout=get_config("request_timeout", 10),
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("succeeded"):
            raise requests.exceptions.RequestException(
                f"API返回失败: {data.get('code', 'unknown')}"
            )
        return data

    async def fetch_topics(
        self, date: str = None, end_time: str = None
    ) -> list[dict]:
        """
        获取指定日期的帖子
        - 自动处理分页
        - 遵守请求限流
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        target_date = datetime.strptime(date, "%Y-%m-%d")
        target_start = target_date.replace(hour=0, minute=0, second=0)
        target_end = target_start + timedelta(days=1)

        all_topics = []
        url = f"{self.BASE_URL}/groups/{self.group_id}/topics"
        params = {"scope": "all", "count": 20}

        if end_time:
            params["end_time"] = end_time

        page = 0
        while True:
            page += 1
            await self.rate_limiter.wait()
            logger.info("获取帖子列表第%d页...", page)

            try:
                data = self._fetch(url, params)
            except Exception as e:
                logger.error("获取帖子列表失败: %s", e)
                break

            resp_data = data.get("resp_data", {})
            topics = resp_data.get("topics", [])

            if not topics:
                break

            for topic in topics:
                create_time_str = topic.get("create_time", "")
                try:
                    create_time = datetime.strptime(
                        create_time_str, "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    create_time_naive = create_time.replace(tzinfo=None)
                except (ValueError, TypeError):
                    continue

                if target_start <= create_time_naive < target_end:
                    all_topics.append(self._parse_topic(topic))
                elif create_time_naive < target_start:
                    logger.info("已到达目标日期之前的帖子，停止翻页")
                    return all_topics

            # 下一页
            last_topic = topics[-1]
            params["end_time"] = last_topic.get("create_time", "")

        logger.info("共获取到 %d 条帖子", len(all_topics))
        return all_topics

    async def fetch_topic_detail(self, topic_id: str) -> Optional[dict]:
        """获取帖子详情（含评论）"""
        await self.rate_limiter.wait()

        url = f"{self.BASE_URL}/topics/{topic_id}"
        try:
            data = self._fetch(url)
            topic = data.get("resp_data", {}).get("topic", {})
            return self._parse_topic(topic)
        except Exception as e:
            logger.error("获取帖子详情失败 [%s]: %s", topic_id, e)
            return None

    async def fetch_comments(self, topic_id: str) -> list[dict]:
        """获取帖子评论"""
        await self.rate_limiter.wait()

        url = f"{self.BASE_URL}/topics/{topic_id}/comments"
        params = {"count": 30, "sort": "asc"}

        try:
            data = self._fetch(url, params)
            comments_raw = data.get("resp_data", {}).get("comments", [])
            return [self._parse_comment(c) for c in comments_raw]
        except Exception as e:
            logger.error("获取评论失败 [%s]: %s", topic_id, e)
            return []

    async def fetch_all_today(self) -> list[dict]:
        """获取今日所有内容（帖子+评论）"""
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info("开始获取 %s 的内容...", today)

        topics = await self.fetch_topics(date=today)
        logger.info("获取到 %d 条帖子，开始获取评论...", len(topics))

        for topic in topics:
            topic_id = topic.get("topic_id")
            if topic_id:
                comments = await self.fetch_comments(topic_id)
                topic["comments"] = comments
                # 随机间隔，模拟人工
                await asyncio.sleep(random.uniform(1, 3))

        return topics

    @staticmethod
    def _parse_topic(topic: dict) -> dict:
        """解析帖子数据"""
        talk = topic.get("talk", {}) or {}
        question = topic.get("question", {}) or {}

        # 内容可能在 talk 或 question 中
        text = talk.get("text", "") or question.get("text", "")
        article = talk.get("article", {}) or {}
        if article:
            text += "\n" + article.get("title", "") + "\n" + article.get("text", "")

        owner = topic.get("owner", {}) or {}

        return {
            "topic_id": str(topic.get("topic_id", "")),
            "type": topic.get("type", ""),
            "text": text.strip(),
            "author": owner.get("name", "未知"),
            "author_id": str(owner.get("user_id", "")),
            "create_time": topic.get("create_time", ""),
            "likes_count": topic.get("likes_count", 0),
            "comments_count": topic.get("comments_count", 0),
            "comments": [],
        }

    @staticmethod
    def _parse_comment(comment: dict) -> dict:
        """解析评论数据"""
        owner = comment.get("owner", {}) or {}
        return {
            "comment_id": str(comment.get("comment_id", "")),
            "text": comment.get("text", ""),
            "author": owner.get("name", "未知"),
            "author_id": str(owner.get("user_id", "")),
            "create_time": comment.get("create_time", ""),
            "likes_count": comment.get("likes_count", 0),
        }
