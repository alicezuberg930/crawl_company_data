#!/usr/bin/env python3
"""
Crawl toàn bộ danh mục ngành nghề từ masothue.com.

Đầu ra mặc định:
    crawl_data/danh_muc_nganh_nghe.json

Chạy:
    python crawl_danh_muc.py

Chạy lại từ trang đầu:
    python crawl_danh_muc.py --restart
"""

from __future__ import annotations

import argparse
import re
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from crawl_paths import crawl_data_path, resolve_json_path
from crawl_masothue import (
    CrawlError,
    clean_text,
    create_session,
    fetch_html,
    read_json,
    write_json,
)


BASE_URL = "https://masothue.com/tra-cuu-ma-so-thue-theo-nganh-nghe/"
DEFAULT_OUTPUT = crawl_data_path("danh_muc_nganh_nghe.json")
CATEGORY_PATH = "/tra-cuu-ma-so-thue-theo-nganh-nghe/"
CODE_PATTERN = re.compile(r"^(?:[A-Za-z]|\d{1,6})$")
NUMERIC_COMBINED_PATTERN = re.compile(r"^(\d{1,6})\s+(.+)$")


def build_page_url(base_url: str, page: int) -> str:
    """Thêm hoặc cập nhật query parameter page."""
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(query)))


def canonical_category_url(href: str, page_url: str) -> str | None:
    """Chuẩn hóa URL ngành và loại URL danh mục/phân trang."""
    absolute = urljoin(page_url, href)
    parsed = urlparse(absolute)
    if (parsed.hostname or "").lower() not in {"masothue.com", "www.masothue.com"}:
        return None

    path = parsed.path
    if not path.startswith(CATEGORY_PATH):
        return None
    if path.rstrip("/") == CATEGORY_PATH.rstrip("/"):
        return None

    return urlunparse(("https", "masothue.com", path.rstrip("/"), "", "", ""))


def infer_code_from_url(url: str) -> str | None:
    """Lấy mã ngành ở phần cuối slug khi không đọc được từ text."""
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    match = re.search(r"-([A-Za-z]|\d{1,6})$", slug)
    return match.group(1).upper() if match else None


def parse_categories(html: str, page_url: str) -> list[dict[str, str]]:
    """Trích business_code, business_name, detail_url từ một trang danh mục."""
    soup = BeautifulSoup(html, "html.parser")
    grouped: OrderedDict[str, list[str]] = OrderedDict()

    for anchor in soup.find_all("a", href=True):
        detail_url = canonical_category_url(str(anchor.get("href")), page_url)
        if not detail_url:
            continue

        text = clean_text(anchor.get_text(" ", strip=True))
        if not text:
            continue
        grouped.setdefault(detail_url, []).append(text)

    results: list[dict[str, str]] = []
    for detail_url, texts in grouped.items():
        inferred_code = infer_code_from_url(detail_url)
        code: str | None = inferred_code
        names: list[str] = []

        for text in texts:
            if CODE_PATTERN.fullmatch(text) and (
                inferred_code is None or text.upper() == inferred_code.upper()
            ):
                code = text.upper()
                continue

            # Một số giao diện có thể gộp "4659 Tên ngành" trong cùng anchor.
            # Chỉ tự tách mã số; không tách chữ đầu như Y/Q vì dễ nhầm tên ngành.
            combined = NUMERIC_COMBINED_PATTERN.fullmatch(text)
            if combined:
                code = code or combined.group(1)
                names.append(clean_text(combined.group(2)) or "")
            elif inferred_code and text.upper().startswith(inferred_code.upper() + " "):
                names.append(clean_text(text[len(inferred_code):]) or "")
            else:
                names.append(text)

        code = code or inferred_code
        names = [name for name in names if name and name.upper() != (code or "")]
        business_name = max(names, key=len) if names else None

        if code and business_name:
            results.append(
                {
                    "business_code": code,
                    "business_name": business_name,
                    "detail_url": detail_url,
                }
            )

    return results


def load_existing(path: Path) -> list[dict[str, str]]:
    raw = read_json(path, default=[])
    if not isinstance(raw, list):
        raise CrawlError(f"File {path} phải chứa một mảng JSON.")
    return [item for item in raw if isinstance(item, dict)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl toàn bộ danh mục ngành nghề trên masothue.com."
    )
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--start-page", type=int, help="Ép trang bắt đầu.")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Crawl lại từ trang 1 và ghi đè dữ liệu cũ.",
    )
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Giới hạn số trang trong một lần chạy để kiểm thử.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.output = resolve_json_path(args.output)

    if args.delay < 0:
        print("Lỗi: --delay không được âm.")
        return 2
    if args.max_pages is not None and args.max_pages <= 0:
        print("Lỗi: --max-pages phải lớn hơn 0.")
        return 2

    if args.restart:
        categories: list[dict[str, str]] = []
    else:
        try:
            categories = load_existing(args.output)
        except CrawlError as exc:
            print(f"Lỗi: {exc}")
            return 1

    if args.start_page is not None:
        page = max(1, args.start_page)
    else:
        page = 1

    seen_urls = {
        str(item.get("detail_url"))
        for item in categories
        if item.get("detail_url")
    }
    seen_fingerprints: set[tuple[str, ...]] = set()
    crawled_pages = 0

    print(f"Bắt đầu từ page={page}; đã có {len(categories)} ngành nghề.")

    with create_session() as session:
        while True:
            page_url = build_page_url(args.base_url, page)
            print(f"Đang crawl page={page}: {page_url}")

            try:
                html = fetch_html(page_url, session=session)
                page_items = parse_categories(html, page_url)
            except (ValueError, CrawlError) as exc:
                print(f"Crawl thất bại tại page={page}: {exc}")
                return 1

            fingerprint = tuple(item["detail_url"] for item in page_items)
            if not page_items:
                print(f"Page={page} không còn dữ liệu.")
                break

            if fingerprint in seen_fingerprints:
                print(
                    f"Page={page} lặp lại dữ liệu cũ; dừng để tránh vòng lặp."
                )
                break
            seen_fingerprints.add(fingerprint)

            new_count = 0
            for item in page_items:
                if item["detail_url"] not in seen_urls:
                    seen_urls.add(item["detail_url"])
                    categories.append(item)
                    new_count += 1

            if new_count > 0:
                write_json(categories, args.output)
            print(
                f"  Lấy được {len(page_items)} mục, mới {new_count}; "
                f"tổng {len(categories)}."
            )

            page += 1
            crawled_pages += 1
            if args.max_pages is not None and crawled_pages >= args.max_pages:
                print("Đã đạt giới hạn --max-pages.")
                break
            if args.delay > 0:
                time.sleep(args.delay)

    print(f"Đã lưu danh mục: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
