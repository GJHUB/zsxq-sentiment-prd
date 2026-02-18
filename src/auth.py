"""认证模块 - Cookie管理与扫码登录"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from playwright.async_api import async_playwright

from .config import get_config

logger = logging.getLogger(__name__)


class AuthManager:
    def __init__(self, cookie_path: str = None, notify_func: Callable = None):
        self.cookie_path = cookie_path or get_config("cookie_path")
        self.notify_func = notify_func
        self._cookie: Optional[dict] = None

    def is_cookie_valid(self) -> bool:
        """检查Cookie是否有效（请求一次API验证）"""
        import requests

        cookie = self.load_cookie()
        if not cookie:
            return False

        try:
            headers = self._build_headers(cookie)
            resp = requests.get(
                "https://api.zsxq.com/v2/users/self",
                headers=headers,
                timeout=10,
            )
            data = resp.json()
            if data.get("succeeded"):
                logger.info("Cookie有效")
                return True
            logger.warning("Cookie已失效: %s", data.get("code"))
            return False
        except Exception as e:
            logger.error("Cookie验证异常: %s", e)
            return False

    def load_cookie(self) -> Optional[dict]:
        """从文件加载Cookie"""
        path = Path(self.cookie_path)
        if not path.exists():
            logger.info("Cookie文件不存在: %s", self.cookie_path)
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                cookie = json.load(f)
            self._cookie = cookie
            return cookie
        except Exception as e:
            logger.error("加载Cookie失败: %s", e)
            return None

    def save_cookie(self, cookie: dict) -> None:
        """保存Cookie到文件"""
        path = Path(self.cookie_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookie, f, ensure_ascii=False, indent=2)
        self._cookie = cookie
        logger.info("Cookie已保存到: %s", self.cookie_path)

    async def login_with_qrcode(self, timeout: int = None) -> bool:
        """
        扫码登录流程：
        1. 启动无头浏览器
        2. 打开知识星球登录页
        3. 截图二维码区域
        4. 调用notify_func发送图片
        5. 轮询检测登录状态
        6. 登录成功后提取并保存Cookie
        """
        timeout = timeout or get_config("qrcode_timeout", 300)
        logger.info("启动扫码登录流程，超时时间: %ds", timeout)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # 1. 打开登录页
                await page.goto("https://wx.zsxq.com", timeout=30000)
                await asyncio.sleep(3)

                # 2. 点击"获取登录二维码"按钮
                get_qr_btn = await page.query_selector("button.get-qr-btn")
                if get_qr_btn:
                    logger.info("点击'获取登录二维码'按钮...")
                    await get_qr_btn.click(force=True)
                    await asyncio.sleep(2)

                # 3. 处理用户协议弹窗 - 点击"同意"
                agree_btn = await page.query_selector(
                    "button:has-text('同意'):not(:has-text('不同意'))"
                )
                if agree_btn:
                    logger.info("点击'同意'用户协议...")
                    await agree_btn.click(force=True)
                    await asyncio.sleep(3)

                # 4. 等待二维码容器出现
                await page.wait_for_selector(
                    ".qrcode-container",
                    timeout=15000,
                )
                await asyncio.sleep(2)

                # 5. 截图二维码区域
                qr_element = await page.query_selector(".qrcode-container")

                if qr_element:
                    qr_image = await qr_element.screenshot()
                else:
                    logger.warning("未找到二维码元素，截取整页")
                    qr_image = await page.screenshot()

                # 3. 发送到企业微信
                if self.notify_func:
                    self.notify_func(qr_image, "请扫码登录知识星球")
                    logger.info("二维码已发送，等待扫码...")
                else:
                    # 保存到本地
                    qr_path = Path(self.cookie_path).parent / "qrcode.png"
                    with open(qr_path, "wb") as f:
                        f.write(qr_image)
                    logger.info("二维码已保存到: %s", qr_path)

                # 4. 等待登录成功
                start_time = time.time()
                while time.time() - start_time < timeout:
                    current_url = page.url
                    if "feed" in current_url or "group" in current_url:
                        # 5. 提取所有zsxq相关Cookie
                        cookies = await page.context.cookies(
                            ["https://wx.zsxq.com", "https://api.zsxq.com"]
                        )
                        cookie_dict = {c["name"]: c["value"] for c in cookies}
                        logger.info("获取到 %d 个Cookie字段: %s",
                                    len(cookie_dict), list(cookie_dict.keys()))
                        self.save_cookie(cookie_dict)
                        logger.info("扫码登录成功")
                        return True
                    await asyncio.sleep(3)

                logger.warning("扫码登录超时")
                return False

            except Exception as e:
                logger.error("扫码登录异常: %s", e)
                return False
            finally:
                await browser.close()

    async def get_cookie(self) -> Optional[dict]:
        """获取有效Cookie，无效则触发扫码流程"""
        if self.is_cookie_valid():
            return self._cookie

        logger.info("Cookie无效，触发扫码登录...")
        success = await self.login_with_qrcode()
        if success:
            return self._cookie

        logger.error("无法获取有效Cookie")
        return None

    @staticmethod
    def _build_headers(cookie: dict) -> dict:
        """构建请求头"""
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie.items())
        return {
            "Cookie": cookie_str,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Origin": "https://wx.zsxq.com",
            "Referer": "https://wx.zsxq.com/",
        }
