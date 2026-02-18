"""知识星球股票舆情分析器 - 主入口"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.auth import AuthManager
from src.config import CONFIG, get_config
from src.crawler import ZsxqCrawler
from src.analyzer import SentimentAnalyzer
from src.report import ReportGenerator
from src.notify import WeChatNotifier


def setup_logging():
    """配置日志"""
    log_dir = get_config("log_dir", "logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = Path(log_dir) / f"{today}.log"

    logging.basicConfig(
        level=getattr(logging, get_config("log_level", "INFO")),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


async def main():
    """主运行流程"""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("=== 知识星球舆情分析开始 ===")

    # 1. 初始化
    notifier = WeChatNotifier()
    auth = AuthManager(
        cookie_path=get_config("cookie_path"),
        notify_func=notifier.send_image,
    )

    try:
        # 2. 获取有效Cookie
        cookie = await auth.get_cookie()
        if not cookie:
            notifier.send_alert("Cookie获取失败，请检查")
            logger.error("Cookie获取失败，退出")
            return

        # 3. 爬取数据
        crawler = ZsxqCrawler(
            group_id=get_config("group_id"),
            cookie=cookie,
        )
        topics = await crawler.fetch_all_today()

        if not topics:
            notifier.send_text("📭 今日暂无新内容")
            logger.info("今日暂无新内容")
            return

        logger.info("获取到 %d 条帖子", len(topics))

        # 4. AI分析
        analyzer = SentimentAnalyzer(
            anthropic_api_key=get_config("anthropic_api_key"),
            openai_api_key=get_config("openai_api_key"),
        )
        analysis = await analyzer.analyze_topics(topics)

        if analysis.empty:
            notifier.send_text("📭 今日内容未提及具体股票")
            logger.info("今日内容未提及具体股票")
            return

        # 5. 生成报告
        reporter = ReportGenerator()
        today = datetime.now().strftime("%Y-%m-%d")
        report_path = reporter.generate(analysis, topics, date=today)

        # 6. 统计信息
        stock_count = analysis["stock"].nunique()
        bullish_count = len(analysis[analysis["sentiment"] == "bullish"])
        bearish_count = len(analysis[analysis["sentiment"] == "bearish"])

        # 7. 发送结果
        summary = (
            f"📊 舆情分析完成\n\n"
            f"📅 日期: {today}\n"
            f"📝 帖子数: {len(topics)}\n"
            f"📈 涉及股票: {stock_count} 只\n"
            f"🟢 看多: {bullish_count} 条\n"
            f"🔴 看空: {bearish_count} 条\n"
            f"📄 报告: {report_path}"
        )
        notifier.send_text(summary)
        notifier.send_file(report_path, "舆情分析报告")

        logger.info("=== 分析完成 ===")

    except Exception as e:
        logger.exception("运行异常")
        notifier.send_alert(f"运行异常: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
