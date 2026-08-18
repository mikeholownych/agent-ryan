from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class WordPressDraft:
    post_id: int
    status: str
    link: str | None
    edit_url: str | None


class WordPressHttpClient(Protocol):
    def post(self, url: str, *, json: dict, auth: tuple[str, str], timeout: int):
        ...


class WordPressDraftPublisher:
    def __init__(
        self,
        *,
        site_url: str,
        username: str,
        password: str,
        http_client: WordPressHttpClient | None = None,
    ) -> None:
        self.site_url = site_url.rstrip("/")
        self.username = username
        self.password = password
        self.http_client = http_client or httpx.Client()

    def create_draft(self, *, title: str, body: str) -> WordPressDraft:
        response = self.http_client.post(
            f"{self.site_url}/index.php?rest_route=/wp/v2/posts",
            json={
                "title": title,
                "content": body,
                "status": "draft",
            },
            auth=(self.username, self.password),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return WordPressDraft(
            post_id=int(payload["id"]),
            status=str(payload["status"]),
            link=payload.get("link"),
            edit_url=_edit_url(self.site_url, int(payload["id"])),
        )


def _edit_url(site_url: str, post_id: int) -> str:
    return f"{site_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"


__all__ = ["WordPressDraft", "WordPressDraftPublisher"]
