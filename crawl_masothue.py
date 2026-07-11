#!/usr/bin/env python3
"""
Crawl trang chi tiết doanh nghiệp trên masothue.com.

Chế độ một URL:
    python crawl_masothue.py \
      "https://masothue.com/1102175850-cong-ty-tnhh-tmdv-ha-phi-nom-group" \
      -o company.json

Chế độ hàng loạt, đọc file do crawl_doanh_nghiep.py tạo:
    python crawl_masothue.py \
      --input doanh_nghiep_urls.json \
      --output doanh_nghiep_chi_tiet.json

Cài thư viện:
    python -m pip install requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_URL = (
    "https://masothue.com/"
    "1102175850-cong-ty-tnhh-tmdv-ha-phi-nom-group"
)
DEFAULT_INPUT = Path("doanh_nghiep_urls.json")
DEFAULT_BATCH_OUTPUT = Path("doanh_nghiep_chi_tiet.json")
DEFAULT_STATE_FILE = Path("crawl_masothue_state.json")
DEFAULT_FAILED_FILE = Path("failed_business_urls.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
}


class CrawlError(RuntimeError):
    """Lỗi tải hoặc phân tích trang."""


def clean_text(value: str | None) -> str | None:
    """Chuẩn hóa khoảng trắng và ký tự vô hình."""
    if value is None:
        return None

    value = value.replace("\u200b", "").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\(\s+", "(", value)
    value = re.sub(r"\s+\)", ")", value)
    return value or None


def normalized(value: str | None) -> str:
    """Chuẩn hóa văn bản để so sánh không dấu, không phân biệt hoa thường."""
    value = clean_text(value) or ""
    value = value.replace("đ", "d").replace("Đ", "D")
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", value).strip().lower()


def validate_url(url: str) -> None:
    """Chỉ cho phép URL HTTP(S) thuộc masothue.com."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL phải dùng http hoặc https.")

    if host not in {"masothue.com", "www.masothue.com"}:
        raise ValueError("Script này chỉ nhận URL thuộc masothue.com.")


def create_session() -> requests.Session:
    """Tạo HTTP session có retry và backoff."""
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )

    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def fetch_html(
    url: str,
    session: requests.Session | None = None,
    timeout: tuple[int, int] = (10, 30),
) -> str:
    """Tải HTML, có thể tái sử dụng session giữa nhiều request."""
    validate_url(url)
    owns_session = session is None
    active_session = session or create_session()

    try:
        try:
            response = active_session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise CrawlError(f"Không thể kết nối tới trang: {exc}") from exc

        if response.status_code in {403, 429}:
            raise CrawlError(
                f"Trang từ chối hoặc giới hạn yêu cầu HTTP "
                f"(status {response.status_code}). Hãy tăng --delay "
                "và chạy tiếp từ checkpoint."
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise CrawlError(
                f"Trang trả về HTTP {response.status_code}: {response.url}"
            ) from exc

        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"

        return response.text
    finally:
        if owns_session:
            active_session.close()


def atomic_write_text(path: Path, content: str) -> None:
    """Ghi file nguyên tử để hạn chế hỏng dữ liệu khi chương trình bị dừng."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def write_json(data: Any, output_path: Path) -> None:
    """Ghi JSON UTF-8, giữ nguyên tiếng Việt."""
    atomic_write_text(
        output_path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    )


def read_json(path: Path, default: Any = None) -> Any:
    """Đọc JSON với thông báo lỗi rõ ràng."""
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CrawlError(f"File JSON không hợp lệ: {path}: {exc}") from exc


def find_tax_info_table(soup: BeautifulSoup) -> Tag | None:
    """Tìm bảng thông tin chính của doanh nghiệp."""
    table = soup.select_one("table.table-taxinfo")
    if isinstance(table, Tag):
        return table

    for candidate in soup.find_all("table"):
        text = normalized(candidate.get_text(" ", strip=True))
        if "ma so thue" in text and "dia chi" in text:
            return candidate

    return None


def select_text(root: Tag, selectors: tuple[str, ...]) -> str | None:
    """Lấy text từ selector đầu tiên tìm thấy."""
    for selector in selectors:
        node = root.select_one(selector)
        if node:
            value = clean_text(node.get_text(" ", strip=True))
            if value:
                return value
    return None


def value_by_label(table: Tag, labels: tuple[str, ...]) -> str | None:
    """Lấy giá trị của hàng dựa trên nhãn, không phụ thuộc vị trí cột."""
    normalized_labels = tuple(normalized(label) for label in labels)

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue

        cell_values = [
            clean_text(cell.get_text(" ", strip=True)) or "" for cell in cells
        ]
        normalized_cells = [normalized(value) for value in cell_values]

        label_indexes: set[int] = set()
        for index, cell_value in enumerate(normalized_cells):
            if any(label in cell_value for label in normalized_labels):
                label_indexes.add(index)

        if not label_indexes:
            continue

        candidates = [
            value
            for index, value in enumerate(cell_values)
            if index not in label_indexes and value
        ]
        if candidates:
            return max(candidates, key=len)

        row_text = clean_text(row.get_text(" ", strip=True)) or ""
        for label in labels:
            row_text = re.sub(
                re.escape(label),
                "",
                row_text,
                count=1,
                flags=re.IGNORECASE,
            )
        row_text = clean_text(row_text)
        if row_text:
            return row_text

    return None


def extract_updated_at(page_text: str) -> str | None:
    """Trích thời điểm cập nhật và chuẩn hóa về YYYY-MM-DD HH:MM:SS."""
    page_text = clean_text(page_text) or ""

    iso_match = re.search(
        r"(?:cập\s+nhật\s+)?lần\s+cuối\s+vào\s+"
        r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?)",
        page_text,
        flags=re.IGNORECASE,
    )
    if iso_match:
        return iso_match.group(1)

    vi_match = re.search(
        r"(?:cập\s+nhật\s+)?lần\s+cuối\s+vào\s+"
        r"(\d{2}:\d{2}:\d{2})\s+(?:ngày\s+)?(\d{2}/\d{2}/\d{4})",
        page_text,
        flags=re.IGNORECASE,
    )
    if vi_match:
        parsed = datetime.strptime(
            f"{vi_match.group(2)} {vi_match.group(1)}",
            "%d/%m/%Y %H:%M:%S",
        )
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    date_only_match = re.search(
        r"(?:cập\s+nhật\s+)?lần\s+cuối\s+vào\s+"
        r"(?:ngày\s+)?(\d{2}/\d{2}/\d{4})",
        page_text,
        flags=re.IGNORECASE,
    )
    if date_only_match:
        parsed = datetime.strptime(date_only_match.group(1), "%d/%m/%Y")
        return parsed.strftime("%Y-%m-%d")

    return None


def looks_like_business_table(table: Tag) -> bool:
    """Kiểm tra sơ bộ một bảng có phải bảng ngành nghề hay không."""
    text = normalized(table.get_text(" ", strip=True))
    if "ma nganh" in text or ("ma" in text[:100] and "nganh" in text[:100]):
        return True

    for row in table.find_all("tr")[:5]:
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) >= 2:
            first = clean_text(cells[0].get_text(" ", strip=True)) or ""
            if re.fullmatch(r"[A-Za-z]|\d{1,6}", first):
                return True

    return False


def find_business_table(soup: BeautifulSoup) -> Tag | None:
    """Tìm bảng nằm dưới tiêu đề 'Ngành nghề kinh doanh'."""
    for heading in soup.find_all(["h2", "h3", "h4", "h5"]):
        if "nganh nghe kinh doanh" not in normalized(
            heading.get_text(" ", strip=True)
        ):
            continue

        candidate = heading.find_next("table")
        if isinstance(candidate, Tag) and looks_like_business_table(candidate):
            return candidate

    for candidate in soup.find_all("table"):
        if looks_like_business_table(candidate):
            return candidate

    return None


def extract_businesses(
    soup: BeautifulSoup,
    main_business: str | None,
) -> list[str]:
    """Lấy các ngành nghề khác thành mảng chuỗi, loại ngành chính."""
    table = find_business_table(soup)
    if table is None:
        return []

    main_key = normalized(main_business)
    results: list[str] = []
    seen: set[str] = set()

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 2:
            continue

        code = clean_text(cells[0].get_text(" ", strip=True)) or ""
        business = clean_text(cells[1].get_text(" ", strip=True))

        if not business or not re.fullmatch(r"[A-Za-z]|\d{1,6}", code):
            continue

        business_key = normalized(business)
        if not business_key:
            continue

        if main_key and (
            business_key == main_key
            or business_key.startswith(main_key + " ")
        ):
            continue

        if business_key not in seen:
            seen.add(business_key)
            results.append(business)

    return results


def parse_company_page(html: str, source_url: str) -> dict[str, Any]:
    """Phân tích HTML trang chi tiết và trả về schema doanh nghiệp."""
    soup = BeautifulSoup(html, "html.parser")
    tax_table = find_tax_info_table(soup)

    if tax_table is None:
        raise CrawlError(
            "Không tìm thấy bảng thông tin doanh nghiệp. "
            "Trang có thể đã đổi cấu trúc hoặc trả về trang chống bot."
        )

    company_name = select_text(
        tax_table,
        (
            'thead th[itemprop="name"]',
            'th[itemprop="name"]',
            "thead th span.copy",
            "thead th",
        ),
    )

    if not company_name:
        h1 = soup.find("h1")
        if h1:
            company_name = clean_text(h1.get_text(" ", strip=True))
            company_name = re.sub(
                r"^\s*\d{8,14}(?:-\d{3})?\s*-\s*",
                "",
                company_name or "",
            )
            company_name = clean_text(company_name)

    tax_code = select_text(
        tax_table,
        (
            '[itemprop="taxID"] .copy',
            '[itemprop="taxID"]',
        ),
    ) or value_by_label(tax_table, ("Mã số thuế",))

    if not tax_code:
        path_match = re.search(
            r"/(\d{8,14}(?:-\d{3})?)(?:-|/|$)",
            urlparse(source_url).path + "/",
        )
        tax_code = path_match.group(1) if path_match else None

    address = select_text(
        tax_table,
        (
            '[itemprop="address"] .copy',
            '[itemprop="address"]',
        ),
    ) or value_by_label(tax_table, ("Địa chỉ",))

    legal_representative = value_by_label(
        tax_table,
        ("Người đại diện pháp luật", "Người đại diện"),
    )

    phone = select_text(
        tax_table,
        (
            '[itemprop="telephone"] .copy',
            '[itemprop="telephone"]',
        ),
    )

    main_business = value_by_label(
        tax_table,
        ("Ngành nghề chính", "Ngành chính"),
    )

    status = value_by_label(
        tax_table,
        ("Tình trạng hoạt động", "Tình trạng"),
    )

    managed_by = value_by_label(
        tax_table,
        ("Quản lý bởi", "Quản lý"),
    )

    business_type = value_by_label(
        tax_table,
        ("Loại hình doanh nghiệp", "Loại hình"),
    )

    active_date = value_by_label(
        tax_table,
        ("Ngày hoạt động", "Ngày thành lập"),
    )

    updated_at = extract_updated_at(soup.get_text(" ", strip=True))
    other_businesses = extract_businesses(soup, main_business)

    data: dict[str, Any] = {
        "company_name": company_name,
        "tax_code": tax_code,
        "address": address,
        "legal_representative": legal_representative,
        "status": status,
        "main_business": main_business,
        "updated_at": updated_at,
        "other_businesses": other_businesses,
        "managed_by": managed_by,
        "business_type": business_type,
        "phone": phone,
        "active_date": active_date,
    }

    # Một số hồ sơ cũ có thể thiếu người đại diện hoặc ngành nghề chính.
    # Chỉ coi trang thất bại khi không xác định được tên hoặc mã số thuế;
    # các trường còn lại vẫn được lưu với giá trị null/[] nếu website không có.
    required_fields = ("company_name", "tax_code")
    missing = [field for field in required_fields if not data[field]]
    if missing:
        raise CrawlError(
            "Không trích xuất được các trường bắt buộc: "
            + ", ".join(missing)
            + ". Trang có thể đã thay đổi HTML."
        )

    return data


def crawl_company(
    url: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Tải và phân tích một trang doanh nghiệp."""
    html = fetch_html(url, session=session)
    return parse_company_page(html, url)


def extract_url_from_item(item: Any) -> str | None:
    """Đọc URL từ chuỗi hoặc object có trường business_url/detail_url/url."""
    if isinstance(item, str):
        return clean_text(item)

    if isinstance(item, dict):
        for key in ("business_url", "detail_url", "url"):
            value = item.get(key)
            if isinstance(value, str) and clean_text(value):
                return clean_text(value)

    return None


def load_business_urls(path: Path) -> list[str]:
    """Đọc danh sách URL doanh nghiệp và loại trùng nhưng giữ thứ tự."""
    raw = read_json(path)
    if raw is None:
        raise CrawlError(f"Không tìm thấy file đầu vào: {path}")

    if isinstance(raw, dict):
        for key in ("businesses", "items", "data", "urls"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break

    if not isinstance(raw, list):
        raise CrawlError("File đầu vào phải là một mảng JSON.")

    urls: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        url = extract_url_from_item(item)
        if not url:
            print(f"Bỏ qua phần tử {index}: không có business_url hợp lệ.")
            continue
        validate_url(url)
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


def load_existing_companies(path: Path) -> list[dict[str, Any]]:
    """Đọc kết quả hiện có để tiếp tục crawl."""
    raw = read_json(path, default=[])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CrawlError(f"File kết quả phải là mảng JSON: {path}")
    return [item for item in raw if isinstance(item, dict)]


def upsert_failed(
    failures: list[dict[str, Any]],
    failure: dict[str, Any],
) -> None:
    """Thêm hoặc cập nhật lỗi theo URL để không tạo bản ghi trùng."""
    url = failure.get("business_url")
    for index, item in enumerate(failures):
        if item.get("business_url") == url:
            failures[index] = failure
            return
    failures.append(failure)


def crawl_batch(
    input_path: Path,
    output_path: Path,
    state_path: Path,
    failed_path: Path,
    delay: float,
    restart: bool,
    stop_on_error: bool,
    max_items: int | None,
) -> int:
    """Crawl hàng loạt URL doanh nghiệp, có checkpoint và file lỗi."""
    urls = load_business_urls(input_path)
    if not urls:
        raise CrawlError("File đầu vào không có URL doanh nghiệp nào.")

    if restart:
        companies: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        start_index = 0
        write_json(companies, output_path)
        write_json(failures, failed_path)
        write_json(
            {"next_index": 0, "total_urls": len(urls), "completed": False},
            state_path,
        )
    else:
        companies = load_existing_companies(output_path)
        raw_failures = read_json(failed_path, default=[])
        failures = raw_failures if isinstance(raw_failures, list) else []
        state = read_json(state_path, default={})
        start_index = int(state.get("next_index", 0)) if isinstance(state, dict) else 0
        start_index = max(0, min(start_index, len(urls)))

    seen_tax_codes = {
        str(item.get("tax_code"))
        for item in companies
        if item.get("tax_code")
    }

    end_index = len(urls)
    if max_items is not None:
        end_index = min(end_index, start_index + max_items)

    print(f"Tổng URL: {len(urls)}; bắt đầu tại index: {start_index}")

    with create_session() as session:
        for index in range(start_index, end_index):
            url = urls[index]
            print(f"[{index + 1}/{len(urls)}] {url}")

            try:
                company = crawl_company(url, session=session)
                tax_code = str(company.get("tax_code") or "")
                if tax_code and tax_code not in seen_tax_codes:
                    seen_tax_codes.add(tax_code)
                    companies.append(company)
                    write_json(companies, output_path)
                elif tax_code:
                    print(f"  Đã có mã số thuế {tax_code}, bỏ qua bản ghi trùng.")

                old_failure_count = len(failures)
                failures = [
                    item for item in failures
                    if item.get("business_url") != url
                ]
                if len(failures) != old_failure_count:
                    write_json(failures, failed_path)
            except (ValueError, CrawlError) as exc:
                print(f"  Lỗi: {exc}")
                upsert_failed(
                    failures,
                    {
                        "index": index,
                        "business_url": url,
                        "error": str(exc),
                    },
                )
                write_json(failures, failed_path)
                write_json(
                    {
                        "next_index": index + (0 if stop_on_error else 1),
                        "total_urls": len(urls),
                        "completed": False,
                    },
                    state_path,
                )
                if stop_on_error:
                    return 1
            else:
                write_json(
                    {
                        "next_index": index + 1,
                        "total_urls": len(urls),
                        "completed": index + 1 >= len(urls),
                    },
                    state_path,
                )

            if delay > 0 and index + 1 < end_index:
                time.sleep(delay)

    completed = end_index >= len(urls)
    write_json(
        {
            "next_index": end_index,
            "total_urls": len(urls),
            "completed": completed,
        },
        state_path,
    )

    print(f"Đã lưu {len(companies)} doanh nghiệp vào: {output_path.resolve()}")
    if failures:
        print(f"Có {len(failures)} URL lỗi trong: {failed_path.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Crawl một trang hoặc hàng loạt trang chi tiết doanh nghiệp "
            "trên masothue.com."
        )
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="URL trang chi tiết cho chế độ crawl một doanh nghiệp.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        help=(
            "File JSON chứa mảng {'business_url': '...'}. "
            f"Mặc định batch: {DEFAULT_INPUT}."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="File JSON đầu ra.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"File checkpoint, mặc định: {DEFAULT_STATE_FILE}.",
    )
    parser.add_argument(
        "--failed-file",
        type=Path,
        default=DEFAULT_FAILED_FILE,
        help=f"File URL crawl lỗi, mặc định: {DEFAULT_FAILED_FILE}.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Số giây nghỉ giữa các request, mặc định 1.5.",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Xóa logic resume và crawl lại từ index 0.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Dừng ngay khi một URL lỗi; mặc định ghi lỗi rồi tiếp tục.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        help="Giới hạn số URL xử lý trong lần chạy, hữu ích khi kiểm thử.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.delay < 0:
        print("Lỗi: --delay không được âm.")
        return 2
    if args.max_items is not None and args.max_items <= 0:
        print("Lỗi: --max-items phải lớn hơn 0.")
        return 2
    if args.url and args.input:
        print("Lỗi: chỉ dùng URL hoặc --input, không dùng đồng thời.")
        return 2

    try:
        if args.input or not args.url:
            input_path = args.input or DEFAULT_INPUT
            output_path = args.output or DEFAULT_BATCH_OUTPUT
            return crawl_batch(
                input_path=input_path,
                output_path=output_path,
                state_path=args.state_file,
                failed_path=args.failed_file,
                delay=args.delay,
                restart=args.restart,
                stop_on_error=args.stop_on_error,
                max_items=args.max_items,
            )

        data = crawl_company(args.url)
        output_path = args.output or Path(
            f"company_{data.get('tax_code') or 'unknown'}.json"
        )
        write_json(data, output_path)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"\nĐã lưu: {output_path.resolve()}")
        return 0
    except (ValueError, CrawlError) as exc:
        print(f"Lỗi: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
