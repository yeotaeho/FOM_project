"""영상 입력: multipart 업로드 또는 HTTP(S) URL 다운로드 → 임시 로컬 파일."""

import ipaddress
import os
import socket
import tempfile
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from fastapi import UploadFile

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
MAX_FILE_SIZE_MB = 500
MAX_FILE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
DOWNLOAD_TIMEOUT_SEC = 120.0
MAX_REDIRECTS = 5

_CONTENT_TYPE_EXT = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
}


def validate_video_extension(filename: str | None) -> str:
    ext = os.path.splitext(filename or "")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"지원하지 않는 형식입니다. 허용: {sorted(ALLOWED_EXTENSIONS)}")
    return ext


def _extension_from_url(url: str) -> str:
    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in ALLOWED_EXTENSIONS:
        return ext
    return ".mp4"


def _extension_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    base = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(base)


def _validate_public_http_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("video_url이 비어 있습니다.")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("video_url은 http 또는 https만 허용됩니다.")
    if not parsed.netloc:
        raise ValueError("video_url 호스트가 없습니다.")
    host = parsed.hostname
    if not host:
        raise ValueError("video_url 호스트가 없습니다.")
    _assert_host_allowed(host)
    return raw


def _assert_host_allowed(host: str) -> None:
    lowered = host.lower().strip()
    if lowered in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise ValueError("내부/로컬 호스트 URL은 허용되지 않습니다.")
    if lowered.endswith(".local") or lowered.endswith(".internal"):
        raise ValueError("내부 호스트 URL은 허용되지 않습니다.")

    try:
        addr_infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"video_url 호스트를 확인할 수 없습니다: {host}") from e

    for info in addr_infos:
        ip_str = info[4][0]
        ip = ipaddress.ip_address(ip_str)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError(
                f"내부·사설 IP로 연결되는 URL은 허용되지 않습니다: {host}"
            )


async def save_upload_to_temp(file: UploadFile) -> Tuple[str, str]:
    """업로드 파일을 임시 경로에 저장. (tmp_path, ext) 반환."""
    if not file.filename:
        raise ValueError("업로드 파일명이 없습니다.")
    ext = validate_video_extension(file.filename)
    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"파일 크기가 {MAX_FILE_SIZE_MB}MB를 초과합니다.")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name
        tmp.write(content)
    return tmp_path, ext


async def download_url_to_temp(video_url: str) -> Tuple[str, str]:
    """HTTP(S) URL에서 영상을 스트리밍 다운로드 후 (tmp_path, ext) 반환."""
    url = _validate_public_http_url(video_url)
    ext_hint = _extension_from_url(url)

    headers = {"User-Agent": "FOM-ROM-Extractor/1.0"}
    timeout = httpx.Timeout(DOWNLOAD_TIMEOUT_SEC, connect=30.0)

    async def _guard_request(request: httpx.Request) -> None:
        host = urlparse(str(request.url)).hostname
        if host:
            _assert_host_allowed(host)

    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
        timeout=timeout,
        event_hooks={"request": [_guard_request]},
    ) as client:
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code >= 400:
                raise ValueError(
                    f"영상 URL 다운로드 실패 (HTTP {response.status_code})"
                )

            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_FILE_BYTES:
                        raise ValueError(
                            f"영상 크기가 {MAX_FILE_SIZE_MB}MB를 초과합니다."
                        )
                except ValueError as e:
                    if "초과" in str(e):
                        raise
                    pass

            ext = _extension_from_content_type(
                response.headers.get("content-type")
            ) or ext_hint
            validate_video_extension(f"video{ext}")

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = tmp.name
                total = 0
                async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_FILE_BYTES:
                        raise ValueError(
                            f"영상 크기가 {MAX_FILE_SIZE_MB}MB를 초과합니다."
                        )
                    tmp.write(chunk)

    if os.path.getsize(tmp_path) == 0:
        os.remove(tmp_path)
        raise ValueError("다운로드한 영상이 비어 있습니다.")

    return tmp_path, ext


async def acquire_video_to_temp(
    *,
    upload: Optional[UploadFile] = None,
    video_url: Optional[str] = None,
) -> Tuple[str, str]:
    """file 또는 video_url 중 정확히 하나 → 임시 로컬 경로."""
    has_file = upload is not None and upload.filename
    has_url = bool((video_url or "").strip())

    if has_file and has_url:
        raise ValueError("file과 video_url 중 하나만 지정하세요.")
    if not has_file and not has_url:
        raise ValueError("file 또는 video_url 중 하나가 필요합니다.")

    if has_file:
        return await save_upload_to_temp(upload)
    return await download_url_to_temp(video_url.strip())  # type: ignore[union-attr]
