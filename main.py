"""知识星球股票舆情分析器 - 主入口

用法：
  python main.py fetch --start-date 2026-02-14          # 爬取数据（所有星球）
  python main.py fetch                                   # 增量爬取（从上次位置继续）
  python main.py analyze --data data/topics_xxx.json     # 分析数据
  python main.py run --start-date 2026-02-14             # 爬取+分析一条龙
  python main.py run                                     # 增量爬取+分析
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.auth import AuthManager
from src.config import get_config
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


async def do_fetch(args) -> str:
    """爬取所有星球的帖子和评论，保存到JSON"""
    logger = logging.getLogger(__name__)
    notifier = WeChatNotifier()
    auth = AuthManager(
        cookie_path=get_config("cookie_path"),
        notify_func=notifier.send_image,
    )

    # 获取Cookie
    cookie = await auth.get_cookie()
    if not cookie:
        notifier.send_alert("Cookie获取失败，请检查")
        logger.error("Cookie获取失败，退出")
        return ""

    group_ids = get_config("group_ids", [])
    if not group_ids:
        logger.error("未配置 ZSXQ_GROUP_ID")
        return ""

    all_topics = []
    group_names = {}  # {group_id: group_name}
    end_date = getattr(args, "end_date", None) or datetime.now().strftime("%Y-%m-%d")

    for gid in group_ids:
        logger.info("=== 爬取星球: %s ===", gid)
        crawler = ZsxqCrawler(group_id=gid, cookie=cookie)

        # 获取星球名称
        try:
            import requests as req
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookie.items())
            resp = req.get(
                f"https://api.zsxq.com/v2/groups/{gid}",
                headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0",
                         "Origin": "https://wx.zsxq.com", "Referer": "https://wx.zsxq.com/"},
                timeout=10,
            )
            gdata = resp.json()
            if gdata.get("succeeded"):
                gname = gdata["resp_data"]["group"].get("name", gid)
                group_names[gid] = gname
                logger.info("星球名称: %s", gname)
        except Exception:
            group_names[gid] = gid

        # 确定起始时间：优先命令行参数，其次上次爬取位置
        start_date = getattr(args, "start_date", None)
        if not start_date:
            last_time = crawler.get_last_fetch_time()
            if last_time:
                # 从上次最新时间继续
                try:
                    dt = datetime.strptime(last_time, "%Y-%m-%dT%H:%M:%S.%f%z")
                    start_date = dt.strftime("%Y-%m-%d")
                    logger.info("星球 %s 增量爬取，从 %s 开始", gid, last_time)
                except ValueError:
                    start_date = datetime.now().strftime("%Y-%m-%d")
            else:
                start_date = datetime.now().strftime("%Y-%m-%d")

        topics = await crawler.fetch_date_range(start_date, end_date)

        if topics:
            # 标记来源星球
            for t in topics:
                t["group_id"] = gid
            crawler.update_last_fetch(topics)
            all_topics.extend(topics)
            logger.info("星球 %s: 获取 %d 条帖子", gid, len(topics))
        else:
            logger.info("星球 %s: 暂无新内容", gid)

    if not all_topics:
        notifier.send_text("📭 所有星球暂无新内容")
        return ""

    # 保存到JSON
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    date_label = f"{start_date}_to_{end_date}" if len(group_ids) == 1 else end_date
    output_path = str(data_dir / f"topics_{date_label}.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"group_names": group_names, "topics": all_topics}, f, ensure_ascii=False, indent=2)

    logger.info("数据已保存: %s（%d 条帖子）", output_path, len(all_topics))
    notifier.send_text(
        f"📥 数据爬取完成\n"
        f"📊 星球数: {len(group_ids)}\n"
        f"📝 帖子数: {len(all_topics)}\n"
        f"📄 文件: {output_path}"
    )
    return output_path


async def do_analyze(args) -> str:
    """读取JSON数据，调用大模型分析，生成报告"""
    logger = logging.getLogger(__name__)
    notifier = WeChatNotifier()

    data_path = args.data
    if not Path(data_path).exists():
        logger.error("数据文件不存在: %s", data_path)
        return ""

    with open(data_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 兼容新旧格式
    if isinstance(raw, dict) and "topics" in raw:
        topics = raw["topics"]
        group_names = raw.get("group_names", {})
    else:
        topics = raw
        group_names = {}

    logger.info("加载了 %d 条帖子", len(topics))

    # AI分析
    analyzer = SentimentAnalyzer(
        openai_api_key=get_config("openai_api_key"),
        anthropic_api_key=get_config("anthropic_api_key"),
    )
    analysis = await analyzer.analyze_topics(topics)

    if analysis.empty:
        notifier.send_text("📭 内容中未发现可分析的财经信息")
        return ""

    # 从文件名提取日期标签
    stem = Path(data_path).stem
    date_label = stem.replace("topics_", "") or datetime.now().strftime("%Y-%m-%d")

    # 生成报告
    reporter = ReportGenerator()
    report_path = reporter.generate(analysis, topics, date=date_label, group_names=group_names)

    financial_count = len(analysis[analysis["is_financial"] == True]) if not analysis.empty else 0

    summary = (
        f"📊 舆情分析完成\n\n"
        f"📝 帖子数: {len(topics)}\n"
        f"💰 财经相关: {financial_count} 条\n"
        f"📄 报告: {report_path}"
    )
    notifier.send_text(summary)
    notifier.send_file(report_path, "舆情分析报告")

    logger.info("=== 分析完成 ===")
    return report_path


async def do_run(args):
    """爬取+分析一条龙"""
    logger = logging.getLogger(__name__)
    logger.info("=== 知识星球舆情分析开始 ===")

    try:
        data_path = await do_fetch(args)
        if not data_path:
            return

        args.data = data_path
        await do_analyze(args)

        logger.info("=== 全部完成 ===")
    except Exception as e:
        logger.exception("运行异常")
        WeChatNotifier().send_alert(f"运行异常: {str(e)}")
        raise


def main():
    parser = argparse.ArgumentParser(description="知识星球股票舆情分析器")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # fetch
    fetch_p = subparsers.add_parser("fetch", help="爬取帖子和评论")
    fetch_p.add_argument("--start-date", type=str, help="起始日期 YYYY-MM-DD（不传则增量）")
    fetch_p.add_argument("--end-date", type=str, help="结束日期 YYYY-MM-DD")

    # analyze
    analyze_p = subparsers.add_parser("analyze", help="分析已爬取的数据")
    analyze_p.add_argument("--data", type=str, required=True, help="数据JSON文件路径")

    # run
    run_p = subparsers.add_parser("run", help="爬取+分析一条龙")
    run_p.add_argument("--start-date", type=str, help="起始日期 YYYY-MM-DD（不传则增量）")
    run_p.add_argument("--end-date", type=str, help="结束日期 YYYY-MM-DD")

    args = parser.parse_args()
    setup_logging()

    if args.command == "fetch":
        asyncio.run(do_fetch(args))
    elif args.command == "analyze":
        asyncio.run(do_analyze(args))
    elif args.command == "run":
        asyncio.run(do_run(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
