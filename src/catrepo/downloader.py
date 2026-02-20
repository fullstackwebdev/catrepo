"""Download and extract remote repositories."""

from __future__ import annotations

import io
import time
import urllib.parse
import requests
import zipfile
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator


@contextmanager
def download_repo(url: str, token: str | None = None) -> Iterator[Path]:
    """Yield a temporary directory with the extracted repo from ``url``."""
    archive_url = _archive_url(url)
    headers = {}
    if token:
        if "github.com" in archive_url:
            headers["Authorization"] = f"token {token}"
        else:
            headers["Authorization"] = f"Bearer {token}"

    response = None
    backoff = 1.0
    for attempt in range(3):
        response = requests.get(archive_url, headers=headers, timeout=30)
        if response.status_code < 500:
            break
        if attempt < 2:
            time.sleep(backoff)
            backoff *= 2
    assert response is not None
    if response.status_code >= 400:
        raise RuntimeError(
            f"Failed to download {archive_url} (HTTP {response.status_code})"
        )
    data = response.content

    tmp = TemporaryDirectory()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp.name)
        root_entries = list(Path(tmp.name).iterdir())
        single = len(root_entries) == 1 and root_entries[0].is_dir()
        root = root_entries[0] if single else Path(tmp.name)
        yield root
    finally:
        tmp.cleanup()


def _archive_url(url: str) -> str:
    if url.endswith(".zip"):
        return url

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    path = parsed.path

    if host is None and "@" in url and ":" in url:
        user_host, path = url.split(":", 1)
        host = user_host.split("@")[-1]

    if not host:
        host = "github.com"
        if not path:
            path = url

    if path.endswith(".git"):
        path = path[:-4]
    slug = path.strip("/")

    if host.endswith("github.com"):
        return f"https://api.github.com/repos/{slug}/zipball"
    if host.endswith("gitlab.com"):
        repo = slug.split("/")[-1]
        return f"https://gitlab.com/{slug}/-/archive/master/{repo}-master.zip"
    if host.endswith("bitbucket.org"):
        return f"https://bitbucket.org/{slug}/get/master.zip"
    raise ValueError("Unsupported host")
