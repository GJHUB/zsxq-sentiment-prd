"""配置管理模块"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG = {
    # 知识星球
    "group_id": os.getenv("ZSXQ_GROUP_ID", ""),

    # AI API
    "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
    "ai_model": "claude-3-sonnet-20240229",
    "batch_size": 5,

    # 爬虫
    "requests_per_minute": 20,
    "request_timeout": 10,
    "max_retries": 3,

    # 扫码
    "qrcode_timeout": 300,  # 5分钟

    # 路径
    "cookie_path": str(BASE_DIR / "data" / "cookie.json"),
    "output_dir": str(BASE_DIR / "output"),
    "log_dir": str(BASE_DIR / "logs"),
    "log_level": "INFO",

    # 企业微信
    "wecom_webhook": os.getenv("WECOM_WEBHOOK", ""),
}


def get_config(key: str, default=None):
    """获取配置项"""
    return CONFIG.get(key, default)
