"""
后台定时任务：天气预报推送 + 日程提醒
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

# 北京时间 (UTC+8)
_CST = timezone(timedelta(hours=8))

def _now_cst() -> datetime:
    """返回当前北京时间"""
    return datetime.now(_CST)
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)


class Scheduler:
    """
    定时任务管理器

    用法：
        scheduler = Scheduler(profile_mgr, send_fn)
        asyncio.ensure_future(scheduler.start())
    """

    def __init__(
        self,
        profile_mgr: Any,  # ProfileManager
        send_fn: Callable,  # 发送消息的回调，参数 (user_id, text)
    ):
        self.pm = profile_mgr
        self.send = send_fn  # async def(user_id, text)
        self._running = True

    async def start(self):
        """启动所有定时任务"""
        logger.info("启动定时任务：天气预报 + 日程提醒")
        asyncio.ensure_future(self._reminder_loop())
        asyncio.ensure_future(self._weather_loop())
        # 等待，不阻塞
        while self._running:
            await asyncio.sleep(60)

    async def stop(self):
        self._running = False

    # ---- 天气预报 ----

    async def _weather_loop(self):
        """按用户设定的时间推送天气预报（每 30 分钟检查一次）"""
        sent_today: set[str] = set()
        last_check_day = _now_cst().day

        await asyncio.sleep(60)

        while self._running:
            now = _now_cst()

            # 新的一天，重置记录
            if now.day != last_check_day:
                sent_today.clear()
                last_check_day = now.day

            users = self.pm.get_all_cities()
            async with httpx.AsyncClient(timeout=15) as client:
                for user_id, city in users:
                    if user_id in sent_today:
                        continue
                    if not self.pm.get_weather_on(user_id):
                        continue

                    pref_hour = self.pm.get_weather_time(user_id)
                    # 在用户设定的时间点（±5分钟窗口）发送
                    if now.hour == pref_hour and now.minute < 10:
                        try:
                            weather = await self._fetch_weather(client, city)
                            msg = f"☀️ 早安～\n{city}今日天气：{weather}"
                            await self.send(user_id, msg)
                            sent_today.add(user_id)
                            logger.info("天气已推送 user=%s city=%s", user_id, city)
                        except Exception as e:
                            logger.error("发送天气失败 user=%s: %s", user_id, e)

            await asyncio.sleep(1800)  # 每 30 分钟检查一次

    async def _send_weather_to_all(self):
        """给所有设置了城市的用户发天气"""
        users = self.pm.get_all_cities()
        if not users:
            return

        async with httpx.AsyncClient(timeout=15) as client:
            for user_id, city in users:
                if not self.pm.get_weather_on(user_id):
                    continue
                try:
                    weather = await self._fetch_weather(client, city)
                    msg = f"☀️ 早安～\n{city}今日天气：{weather}"
                    await self.send(user_id, msg)
                except Exception as e:
                    logger.error("发送天气失败 user=%s: %s", user_id, e)

    @staticmethod
    async def _fetch_weather(client: httpx.AsyncClient, city: str) -> str:
        """从 wttr.in 获取天气"""
        url = f"https://wttr.in/{city}?format=%C+%t+%w+%h&lang=zh"
        resp = await client.get(url)
        if resp.status_code == 200:
            text = resp.text.strip()
            return text if text else "暂无数据"
        return "获取失败"

    # ---- 日程提醒 ----

    async def _reminder_loop(self):
        """每 30 秒检查一次到期提醒"""
        from bot.server_bot import QQBotServer

        await asyncio.sleep(10)  # 先等一轮

        while self._running:
            try:
                reminders = self.pm.get_due_reminders()
                for r in reminders:
                    if not self.pm.get_remind_on(r["user_id"]):
                        continue
                    msg = f"⏰ 提醒：{r['message']}"
                    await self.send(r["user_id"], msg)
                    self.pm.mark_reminder_done(r["id"])
                    logger.info("发送提醒 user=%s: %s", r["user_id"], r["message"])
            except Exception as e:
                logger.error("检查提醒异常: %s", e)

            await asyncio.sleep(30)


def parse_reminder_time(text: str) -> Optional[str]:
    """
    解析中文时间表达式，返回 ISO 格式时间字符串

    支持：
      "明天早上8点"  "今天下午3点"  "后天"  "5分钟后"
      "2026-05-05 08:00"  "8点"  "明天"
    """
    now = _now_cst()
    text = text.strip()

    # ISO 格式直接解析
    try:
        dt = datetime.fromisoformat(text)
        return dt.isoformat()
    except ValueError:
        pass

    # 匹配 "N分钟后"
    m = re.match(r'^(\d+)分钟后$', text)
    if m:
        return (_now_cst() + timedelta(minutes=int(m.group(1)))).isoformat()

    # 匹配 "明天" / "后天"
    days = 0
    if "后天" in text:
        days = 2
    elif "明天" in text or "明早" in text:
        days = 1
    elif "今天" in text or "今早" in text:
        days = 0

    base = now + timedelta(days=days)

    # 提取时间
    hour = None
    minute = 0

    # "早上X点" / "上午X点" / "下午X点" / "晚上X点"
    m = re.search(r'(早上|上午|中午|下午|晚上|凌晨)?(\d+)点(\d+)?分?', text)
    if m:
        period = m.group(1) or ""
        hour = int(m.group(2))
        if m.group(3):
            minute = int(m.group(3))

        if period in ("下午", "晚上") and hour < 12:
            hour += 12
        elif period == "凌晨" and hour == 12:
            hour = 0
        elif period == "中午" and hour < 12:
            pass  # 中午12点保持

    if hour is not None:
        base = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return base.isoformat()

    # 只有"明天"/"后天"没具体时间，默认早上9点
    if "明天" in text or "后天" in text:
        base = base.replace(hour=9, minute=0, second=0, microsecond=0)
        return base.isoformat()

    return None
