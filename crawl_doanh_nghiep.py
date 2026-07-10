"""
Đọc danh_muc_nganh_nghe.json, vào từng URL ngành và crawl toàn bộ URL doanh nghiệp.

Đầu ra mặc định:
    doanh_nghiep_urls.json

Mỗi phần tử:
    {"business_url": "https://masothue.com/..."}

Chạy:
    python crawl_doanh_nghiep.py

Crawl lại từ đầu:
    python crawl_doanh_nghiep.py --restart
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from crawl_masothue import (
    CrawlError,
    clean_text,
    create_session,
    fetch_html,
    read_json,
    validate_url,
    write_json,
)


DEFAULT_INPUT = Path("danh_muc_nganh_nghe.json")
DEFAULT_OUTPUT = Path("doanh_nghiep_urls.json")
DEFAULT_STATE_FILE = Path("crawl_doanh_nghiep_state.json")
COMPANY_PATH_PATTERN = re.compile(
    r"^/\d{8,14}(?:-\d{3})?(?:-[^/?#]+)?/?$",
    flags=re.IGNORECASE,
)


def build_page_url(base_url: str, page: int) -> str:
    """Thêm/cập nhật query parameter page cho URL ngành."""
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(query)))


def canonical_company_url(href: str, page_url: str) -> str | None:
    """Chỉ nhận URL trang chi tiết doanh nghiệp có path bắt đầu bằng MST."""
    absolute = urljoin(page_url, href)
    parsed = urlparse(absolute)
    if (parsed.hostname or "").lower() not in {"masothue.com", "www.masothue.com"}:
        return None
    if not COMPANY_PATH_PATTERN.fullmatch(parsed.path):
        return None

    return urlunparse(("https", "masothue.com", parsed.path.rstrip("/"), "", "", ""))


def parse_company_urls(html: str, page_url: str) -> list[str]:
    """Lấy URL doanh nghiệp từ một trang ngành, ưu tiên liên kết trong h3."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[str] = []
    seen: set[str] = set()

    candidates = list(soup.select("h3 a[href]"))
    if not candidates:
        candidates = list(soup.find_all("a", href=True))

    for anchor in candidates:
        url = canonical_company_url(str(anchor.get("href")), page_url)
        if not url or url in seen:
            continue

        text = clean_text(anchor.get_text(" ", strip=True))
        if not text:
            continue

        seen.add(url)
        results.append(url)

    # Fallback: có giao diện đặt MST ở liên kết ngoài h3.
    if not results:
        for anchor in soup.find_all("a", href=True):
            url = canonical_company_url(str(anchor.get("href")), page_url)
            if url and url not in seen:
                seen.add(url)
                results.append(url)

    return results


def load_categories(path: Path) -> list[dict[str, str]]:
    raw = read_json(path)
    if raw is None:
        raise CrawlError(f"Không tìm thấy file danh mục: {path}")
    if not isinstance(raw, list):
        raise CrawlError("File danh mục phải là một mảng JSON.")

    categories: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            print(f"Bỏ qua danh mục index={index}: không phải object.")
            continue
        detail_url = item.get("detail_url")
        if not isinstance(detail_url, str) or not clean_text(detail_url):
            print(f"Bỏ qua danh mục index={index}: thiếu detail_url.")
            continue
        validate_url(detail_url)
        categories.append(item)

    return categories


def load_existing_urls(path: Path) -> list[dict[str, str]]:
    raw = read_json(path, default=[])
    if not isinstance(raw, list):
        raise CrawlError(f"File {path} phải là một mảng JSON.")

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = item.get("business_url")
        if isinstance(url, str) and url not in seen:
            seen.add(url)
            results.append({"business_url": url})
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl URL doanh nghiệp từ tất cả danh mục ngành nghề."
    )
    parser.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help="Checkpoint category_index và page hiện tại.",
    )
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Crawl lại từ danh mục 0, page 1.",
    )
    parser.add_argument(
        "--max-categories",
        type=int,
        help="Giới hạn số danh mục xử lý trong lần chạy.",
    )
    parser.add_argument(
        "--max-pages-per-category",
        type=int,
        help="Giới hạn số trang mỗi ngành để kiểm thử.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.delay < 0:
        print("Lỗi: --delay không được âm.")
        return 2
    if args.max_categories is not None and args.max_categories <= 0:
        print("Lỗi: --max-categories phải lớn hơn 0.")
        return 2
    if args.max_pages_per_category is not None and args.max_pages_per_category <= 0:
        print("Lỗi: --max-pages-per-category phải lớn hơn 0.")
        return 2

    try:
        categories = load_categories(args.input)
        if not categories:
            raise CrawlError("Không có danh mục ngành nghề hợp lệ.")

        if args.restart:
            output_items: list[dict[str, str]] = []
            category_index = 0
            page = 1
        else:
            output_items = load_existing_urls(args.output)
            state = read_json(args.state_file, default={})
            if isinstance(state, dict):
                category_index = int(state.get("category_index", 0))
                page = int(state.get("page", 1))
            else:
                category_index, page = 0, 1
            category_index = max(0, min(category_index, len(categories)))
            page = max(1, page)
    except (ValueError, CrawlError) as exc:
        print(f"Lỗi: {exc}")
        return 1

    seen_urls = {item["business_url"] for item in output_items}
    category_end = len(categories)
    if args.max_categories is not None:
        category_end = min(category_end, category_index + args.max_categories)

    print(
        f"Tổng danh mục: {len(categories)}; bắt đầu category_index="
        f"{category_index}, page={page}; đã có {len(output_items)} URL."
    )

    with create_session() as session:
        while category_index < category_end:
            category = categories[category_index]
            category_url = str(category["detail_url"])
            business_code = category.get("business_code", "")
            business_name = category.get("business_name", "")
            pages_processed = 0
            seen_page_fingerprints: set[tuple[str, ...]] = set()

            print(
                f"\n[{category_index + 1}/{len(categories)}] "
                f"{business_code} - {business_name}"
            )

            while True:
                page_url = build_page_url(category_url, page)
                print(f"  page={page}: {page_url}")

                try:
                    html = fetch_html(page_url, session=session)
                    page_urls = parse_company_urls(html, page_url)
                except (ValueError, CrawlError) as exc:
                    write_json(
                        {
                            "category_index": category_index,
                            "page": page,
                            "completed": False,
                            "error": str(exc),
                        },
                        args.state_file,
                    )
                    print(f"  Crawl thất bại: {exc}")
                    print(
                        "Đã lưu checkpoint; chạy lại cùng lệnh để tiếp tục "
                        "đúng danh mục và trang này."
                    )
                    return 1

                fingerprint = tuple(page_urls)
                if not page_urls:
                    print("  Không còn doanh nghiệp; chuyển sang ngành tiếp theo.")
                    category_index += 1
                    page = 1
                    write_json(
                        {
                            "category_index": category_index,
                            "page": page,
                            "completed": category_index >= len(categories),
                        },
                        args.state_file,
                    )
                    break

                if fingerprint in seen_page_fingerprints:
                    print("  Trang bị lặp; chuyển sang ngành tiếp theo.")
                    category_index += 1
                    page = 1
                    write_json(
                        {
                            "category_index": category_index,
                            "page": page,
                            "completed": category_index >= len(categories),
                        },
                        args.state_file,
                    )
                    break
                seen_page_fingerprints.add(fingerprint)

                new_count = 0
                for url in page_urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        output_items.append({"business_url": url})
                        new_count += 1

                # Nếu cả trang chỉ gồm URL đã có, có thể là trang cuối bị redirect/lặp.
                if new_count == 0:
                    print("  Không có URL mới; chuyển sang ngành tiếp theo.")
                    category_index += 1
                    page = 1
                    write_json(
                        {
                            "category_index": category_index,
                            "page": page,
                            "completed": category_index >= len(categories),
                        },
                        args.state_file,
                    )
                    break

                write_json(output_items, args.output)
                page += 1
                pages_processed += 1
                write_json(
                    {
                        "category_index": category_index,
                        "page": page,
                        "completed": False,
                    },
                    args.state_file,
                )
                print(
                    f"    Lấy {len(page_urls)} URL, mới {new_count}; "
                    f"tổng {len(output_items)}."
                )

                if (
                    args.max_pages_per_category is not None
                    and pages_processed >= args.max_pages_per_category
                ):
                    print("  Đã đạt --max-pages-per-category; lưu checkpoint và dừng.")
                    print(f"Đã lưu: {args.output.resolve()}")
                    return 0

                if args.delay > 0:
                    time.sleep(args.delay)

            if args.delay > 0 and category_index < category_end:
                time.sleep(args.delay)

    completed = category_index >= len(categories)
    write_json(
        {
            "category_index": category_index,
            "page": page,
            "completed": completed,
        },
        args.state_file,
    )
    print(f"\nĐã lưu {len(output_items)} URL vào: {args.output.resolve()}")
    if not completed:
        print("Chưa hết danh mục do giới hạn --max-categories; chạy lại để tiếp tục.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())