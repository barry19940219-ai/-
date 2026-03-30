"""长期运行的行情抓取 + 微信推送脚本。

改进点：
1. 使用 requests.Session 复用连接，并在每次请求后及时关闭响应，避免套接字堆积。
2. 为网络请求增加超时、重试、退避，防止短时网络抖动导致脚本退出。
3. 对微信发送做失败重连，避免长时间运行后会话失效。
4. 主循环永不抛出到顶层，出现异常自动恢复并继续运行。

依赖：
    pip install requests beautifulsoup4 PyOfficeRobot
"""

from __future__ import annotations

import logging
import random
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from PyOfficeRobot.core.WeChatType import WeChat


ADDRESS = "https://xuangutong.com.cn/live"
GROUP_NAME = "911"  # 这里更改要发送至的群聊名称
POLL_SECONDS = 10
MAX_REQUESTS_BEFORE_REBUILD = 300

HEADERS = {
    "Host": "xuangutong.com.cn",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) "
        "Gecko/20100101 Firefox/97.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
    "Accept-Encoding": "gzip, deflate, br",
    "Cookie": (
        "Hm_lvt_5a36d47aea259294d4ceb6ccbb2fa0d9=1651901559; "
        "Hm_lpvt_5a36d47aea259294d4ceb6ccbb2fa0d9=1651902205; "
        "_ga_297ZV00D16=GS1.1.1651901558.1.1.1651902205.0; "
        "_ga=GA1.1.1645758609.1651901559; "
        "_bl_uid=gplkv2nvv6mf54jF5cqh58CiUazg; "
        "taotieDeviceId=1809d016-cf36-2b73-c46d-fa60814d2da6"
    ),
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "If-None-Match": "44567-1U6JY7ZKiv1miLwk1gp2SoikA94",
}


@dataclass
class RuntimeState:
    last_message: str = ""
    wx_failures: int = 0
    crawl_failures: int = 0
    request_count: int = 0


class LiveCrawler:
    def __init__(self) -> None:
        self.session = self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            status=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=5, pool_maxsize=5)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(HEADERS)
        return session

    def scrape_data(self) -> str:
        # 必须设置 timeout，避免 socket 长时间卡住后资源耗尽
        with self.session.get(ADDRESS, timeout=(5, 12)) as response:
            response.raise_for_status()
            content = response.text

        soup = BeautifulSoup(content, "html.parser")
        target = soup.select_one("div.left_UgaS8")
        if target is None:
            raise ValueError("页面结构变化：未找到 div.left_UgaS8")

        title_node = target.select_one("a")
        detail_node = target.select_one("pre")

        title = (title_node.get_text(strip=True) if title_node else "").strip()
        detail = (detail_node.get_text(strip=True) if detail_node else "").strip()

        parent_classes = ""
        if target.parent and target.parent.parent:
            parent_classes = " ".join(target.parent.parent.get("class", []))

        prefix = " ★★★ " if "bigItem_DlVpd" in parent_classes else " "
        body = f"{title}  {detail}".strip()
        if not body:
            raise ValueError("页面结构变化：抓取到空内容")
        return f"{prefix}{body}"

    def rebuild_session(self) -> None:
        """主动重建 Session，释放连接池中的底层 socket 资源。"""
        try:
            self.session.close()
        finally:
            self.session = self._build_session()


def is_socket_buffer_error(exc: Exception) -> bool:
    """兼容中文/英文错误信息，识别 WinError 10055 及类似 socket 缓冲区耗尽。"""
    text = str(exc)
    return any(
        keyword in text
        for keyword in (
            "WinError 10055",
            "缓冲区空间不足",
            "队列已满",
            "No buffer space available",
            "WSAENOBUFS",
        )
    )


class WeChatSender:
    def __init__(self, group_name: str) -> None:
        self.group_name = group_name
        self.wx: Optional[WeChat] = None
        self.reconnect()

    def reconnect(self) -> None:
        logging.info("初始化/重连微信会话...")
        self.wx = WeChat()
        self.wx.GetSessionList()

    def send(self, message: str) -> None:
        if self.wx is None:
            self.reconnect()
        assert self.wx is not None

        timestamp = datetime.now().strftime("%H:%M:%S")
        final_message = f"{timestamp}{message}"
        self.wx.ChatWith(self.group_name)
        self.wx.SendMsg(final_message)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    state = RuntimeState()
    crawler = LiveCrawler()
    sender = WeChatSender(GROUP_NAME)

    logging.info("脚本已启动，开始监控: %s", ADDRESS)
    while True:
        sleep_seconds = POLL_SECONDS + random.uniform(0, 1.5)
        try:
            message = crawler.scrape_data()
            state.crawl_failures = 0
            state.request_count += 1
        except (requests.RequestException, socket.error, OSError) as exc:
            state.crawl_failures += 1
            wait = min(60, 5 * state.crawl_failures)
            logging.exception("抓取失败（连续 %s 次），%s 秒后重试", state.crawl_failures, wait)

            # 命中“系统缓冲区空间不足/队列已满”后，立刻重建所有连接对象。
            if is_socket_buffer_error(exc):
                logging.warning("检测到 socket 缓冲区异常，开始重建 HTTP/微信会话")
                crawler.rebuild_session()
                try:
                    sender.reconnect()
                except Exception:
                    logging.exception("微信重连失败")

            time.sleep(wait)
            continue
        except Exception:
            state.crawl_failures += 1
            wait = min(60, 5 * state.crawl_failures)
            logging.exception("解析失败（连续 %s 次），%s 秒后重试", state.crawl_failures, wait)
            time.sleep(wait)
            continue

        if message != state.last_message:
            for attempt in range(1, 4):
                try:
                    sender.send(message)
                    state.last_message = message
                    state.wx_failures = 0
                    logging.info("已发送新消息：%s", message)
                    break
                except Exception as exc:
                    state.wx_failures += 1
                    logging.exception("微信发送失败（尝试 %s/3）", attempt)
                    try:
                        sender.reconnect()
                    except Exception:
                        logging.exception("微信重连失败")

                    # 如果也是 socket 缓冲区问题，同时重建 HTTP Session。
                    if is_socket_buffer_error(exc):
                        crawler.rebuild_session()

                    time.sleep(min(30, 2 * attempt))
            else:
                logging.error("本轮消息发送失败，等待下一轮继续")
        else:
            logging.debug("内容无变化")

        # 高频重建连接池：避免累积到一天后才暴露底层 socket 问题。
        if state.request_count >= MAX_REQUESTS_BEFORE_REBUILD:
            crawler.rebuild_session()
            state.request_count = 0
            logging.info("达到请求阈值，已主动重建 HTTP Session")

        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
