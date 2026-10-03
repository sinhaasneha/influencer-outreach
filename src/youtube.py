"""Thin, retry-aware wrapper around the YouTube Data API v3 (REST)."""
import logging
import time
from typing import Iterator

import requests

log = logging.getLogger(__name__)
BASE_URL = "https://www.googleapis.com/youtube/v3"


class QuotaExceeded(Exception):
    """Raised when the daily API quota is exhausted - callers should save progress and stop."""


class YouTubeClient:
    def __init__(self, api_key: str, timeout: int = 15, max_retries: int = 3):
        if not api_key:
            raise ValueError("YOUTUBE_API_KEY is missing. Copy .env.example to .env and set it.")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def _get(self, endpoint: str, **params) -> dict:
        params["key"] = self.api_key
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=self.timeout)
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 403 and "quotaExceeded" in resp.text:
                raise QuotaExceeded("YouTube API daily quota exceeded")
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"YouTube API error {resp.status_code}: {resp.text[:300]}")
        raise RuntimeError(f"YouTube API failed after {self.max_retries} attempts: {last_err}")

    # ---- discovery -------------------------------------------------------
    def search_channels(self, query: str, pages: int = 1, region_code=None, language=None) -> Iterator[str]:
        """Yield channel IDs matching a query (100 quota units per page)."""
        token = None
        for _ in range(pages):
            params = dict(part="snippet", q=query, type="channel", maxResults=50)
            if region_code:
                params["regionCode"] = region_code
            if language:
                params["relevanceLanguage"] = language
            if token:
                params["pageToken"] = token
            data = self._get("search", **params)
            for item in data.get("items", []):
                cid = item.get("id", {}).get("channelId")
                if cid:
                    yield cid
            token = data.get("nextPageToken")
            if not token:
                break

    def get_channels(self, channel_ids: list[str]) -> list[dict]:
        """Channel details in batches of 50 (1 quota unit per batch)."""
        out = []
        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i:i + 50]
            data = self._get("channels", part="snippet,statistics,contentDetails",
                             id=",".join(batch), maxResults=50)
            out.extend(data.get("items", []))
        return out

    # ---- enrichment ------------------------------------------------------
    def get_recent_videos(self, uploads_playlist_id: str, n: int = 10) -> list[dict]:
        """Recent uploads with stats. 2 quota units total."""
        data = self._get("playlistItems", part="snippet,contentDetails",
                         playlistId=uploads_playlist_id, maxResults=min(n, 50))
        ids = [it["contentDetails"]["videoId"] for it in data.get("items", [])]
        if not ids:
            return []
        vids = self._get("videos", part="snippet,statistics", id=",".join(ids))
        return vids.get("items", [])
