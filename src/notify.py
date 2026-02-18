"""通知模块 - 企业微信通知"""

import base64
import hashlib
import logging
from pathlib import Path
from typing import Optional

import requests

from .config import get_config

logger = logging.getLogger(__name__)


class WeChatNotifier:
    """企业微信通知器"""

    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or get_config("wecom_webhook")

    def send_image(self, image_data: bytes, caption: str = "") -> bool:
        """发送图片（二维码）"""
        if not self.webhook_url:
            logger.warning("未配置企业微信webhook，跳过图片发送")
            return False

        try:
            b64 = base64.b64encode(image_data).decode()
            md5 = hashlib.md5(image_data).hexdigest()

            payload = {
                "msgtype": "image",
                "image": {"base64": b64, "md5": md5},
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()

            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("图片发送成功: %s", caption)
                return True
            logger.error("图片发送失败: %s", result)
            return False
        except Exception as e:
            logger.error("图片发送异常: %s", e)
            return False

    def send_text(self, message: str) -> bool:
        """发送文本消息"""
        if not self.webhook_url:
            logger.warning("未配置企业微信webhook，跳过文本发送")
            return False

        try:
            payload = {
                "msgtype": "text",
                "text": {"content": message},
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()

            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("文本发送成功")
                return True
            logger.error("文本发送失败: %s", result)
            return False
        except Exception as e:
            logger.error("文本发送异常: %s", e)
            return False

    def send_file(self, file_path: str, caption: str = "") -> bool:
        """
        发送文件（Excel报告）
        注意：企业微信机器人webhook不直接支持文件发送，
        这里通过markdown消息发送文件路径提示
        """
        if not self.webhook_url:
            logger.warning("未配置企业微信webhook，跳过文件发送")
            return False

        path = Path(file_path)
        if not path.exists():
            logger.error("文件不存在: %s", file_path)
            return False

        try:
            size_mb = path.stat().st_size / (1024 * 1024)
            content = (
                f"📊 **{caption or '报告已生成'}**\n"
                f"> 文件: {path.name}\n"
                f"> 大小: {size_mb:.2f} MB\n"
                f"> 路径: {file_path}"
            )
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()

            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("文件通知发送成功: %s", path.name)
                return True
            logger.error("文件通知发送失败: %s", result)
            return False
        except Exception as e:
            logger.error("文件通知发送异常: %s", e)
            return False

    def send_alert(self, error: str) -> bool:
        """发送异常告警"""
        message = f"⚠️ 舆情分析异常告警\n\n错误信息: {error}\n\n请及时检查处理。"
        return self.send_text(message)

    def send_markdown(self, content: str) -> bool:
        """发送markdown消息"""
        if not self.webhook_url:
            logger.warning("未配置企业微信webhook，跳过发送")
            return False

        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()

            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("Markdown发送成功")
                return True
            logger.error("Markdown发送失败: %s", result)
            return False
        except Exception as e:
            logger.error("Markdown发送异常: %s", e)
            return False
