#base.py
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    source_name: str
    rate_limit_seconds: float = 2.0

    @abstractmethod
    def scrape(self) -> list[dict]:
        pass

    def respect_rate_limit(self) -> None:
        time.sleep(self.rate_limit_seconds)

    def fetch_page(self, url: str, params: dict | None = None) -> BeautifulSoup | None:
        ua = UserAgent()
        for attempt in range(3):
            try:
                headers = {"User-Agent": ua.random}
                response = requests.get(url, params=params, headers=headers, timeout=15)
                if response.status_code == 200:
                    return BeautifulSoup(response.text, "lxml")
                logger.error(
                    "scraper_error source=%s url=%s status=%s timestamp=%s",
                    self.source_name,
                    url,
                    response.status_code,
                    datetime.utcnow().isoformat(),
                )
            except Exception as exc:
                logger.error(
                    "scraper_error source=%s url=%s error=%s timestamp=%s",
                    self.source_name,
                    url,
                    type(exc).__name__,
                    datetime.utcnow().isoformat(),
                )
            time.sleep(2 ** attempt)
        return None

