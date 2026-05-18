from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import io
import json
import os
import re
import sys
import time
import zipfile
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib import error as urlerror
from urllib import parse, request
from xml.etree import ElementTree

DART_BASE_URL = "https://opendart.fss.or.kr/api"
KIND_BASE_URL = "https://kind.krx.co.kr"
DEFAULT_LOOKBACK_DAYS = 365

BIZ_NO_COLUMNS = ("biz_no", "business_registration_number", "사업자등록번호", "사업자 번호", "사업자번호")
NAME_COLUMNS = ("customer_name", "company_name", "corp_name", "업체명", "회사명", "거래처명", "상호")

CORP_CLASS_TO_MARKET = {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "기타법인"}
RISK_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    ("상장폐지", "상장폐지", "위험"),
    ("매매거래정지", "거래정지", "위험"),
    ("거래정지", "거래정지", "위험"),
    ("실질심사", "실질심사", "위험"),
    ("관리종목", "관리종목", "주의"),
)


@dataclass(frozen=True)
class CustomerInput:
    biz_no: str
    customer_name: str
    row_number: int


@dataclass
class DartCompanyResult:
    customer: CustomerInput
    corp_code: str | None = None
    corp_name: str | None = None
    bizr_no: str | None = None
    stock_code: str | None = None
    corp_cls: str | None = None
    market_type: str | None = None
    matched_by: str = "no_match"
    candidates: list[dict[str, Any]] = field(default_factory=list)
    raw_data: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class DartDisclosureResult:
    biz_no: str
    customer_name: str
    corp_code: str
    receipt_no: str
    report_name: str | None
    flr_nm: str | None
    pblntf_ty: str | None
    disclosure_date: str | None
    dart_url: str | None
    risk_level: str
    risk_reason: str | None
    raw_data: dict[str, Any]


@dataclass
class KindMarketEventResult:
    biz_no: str
    customer_name: str
    stock_code: str
    event_type: str
    event_title: str | None
    event_date: str | None
    source_url: str | None
    risk_level: str
    risk_reason: str | None
    raw_data: dict[str, Any]


def normalize_biz_no(value: Any) -> str:
    """Return a hyphen-free 10 digit Korean business registration number."""
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 9 and str(value).endswith(".0"):
        digits = digits.zfill(10)
    return digits.zfill(10) if 0 < len(digits) < 10 else digits


def normalize_company_name(value: Any) -> str:
    if value is None:
        return ""
    name = re.sub(r"\s+", "", str(value).strip())
    name = re.sub(r"^(주식회사|\(주\)|㈜|주\))", "", name)
    name = re.sub(r"(주식회사|\(주\)|㈜)$", "", name)
    return name.lower()


def pick_column(columns: Iterable[Any], candidates: tuple[str, ...]) -> str | None:
    normalized = {str(col).strip().lower(): str(col) for col in columns}
    for candidate in candidates:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]
    for col in columns:
        compact = re.sub(r"\s+", "", str(col)).lower()
        if any(re.sub(r"\s+", "", candidate).lower() == compact for candidate in candidates):
            return str(col)
    return None


def read_customers_from_excel(path: Path, sheet_name: str | int | None = None) -> list[CustomerInput]:
    rows = read_tabular_file(path, sheet_name)
    if not rows:
        return []
    biz_col = pick_column(rows[0].keys(), BIZ_NO_COLUMNS)
    name_col = pick_column(rows[0].keys(), NAME_COLUMNS)
    if not biz_col or not name_col:
        raise ValueError(
            "Excel must contain business number and company name columns. "
            f"Business candidates={BIZ_NO_COLUMNS}, name candidates={NAME_COLUMNS}"
        )

    customers: list[CustomerInput] = []
    for index, row in enumerate(rows, start=2):
        biz_no = normalize_biz_no(row.get(biz_col))
        customer_name = str(row.get(name_col) or "").strip()
        if not biz_no and not customer_name:
            continue
        if not re.fullmatch(r"\d{10}", biz_no):
            raise ValueError(f"Invalid business number at Excel row {index}: {row.get(biz_col)!r}")
        if not customer_name:
            raise ValueError(f"Missing company name at Excel row {index}")
        customers.append(CustomerInput(biz_no=biz_no, customer_name=customer_name, row_number=index))
    return customers


def read_tabular_file(path: Path, sheet_name: str | int | None = None) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    if suffix in {".xlsx", ".xlsm"}:
        return read_xlsx(path, sheet_name)
    raise ValueError(f"Unsupported input file type: {path.suffix}. Use .xlsx, .xlsm, or .csv.")


def read_xlsx(path: Path, sheet_name: str | int | None = None) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as workbook:
        shared_strings = load_shared_strings(workbook)
        sheet_path = resolve_sheet_path(workbook, sheet_name)
        root = ElementTree.fromstring(workbook.read(sheet_path))
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    matrix: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values: list[str] = []
        for cell in row.findall("x:c", namespace):
            cell_ref = cell.attrib.get("r", "")
            column_index = column_ref_to_index(cell_ref)
            while len(values) < column_index:
                values.append("")
            values.append(read_xlsx_cell(cell, shared_strings, namespace))
        matrix.append(values)
    if not matrix:
        return []
    headers = [header.strip() for header in matrix[0]]
    return [{headers[index]: row[index] if index < len(row) else "" for index in range(len(headers))} for row in matrix[1:]]


def load_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings: list[str] = []
    for item in root.findall("x:si", namespace):
        strings.append("".join(text.text or "" for text in item.findall(".//x:t", namespace)))
    return strings


def resolve_sheet_path(workbook: zipfile.ZipFile, sheet_name: str | int | None) -> str:
    workbook_xml = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
    rels_xml = ElementTree.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    main_ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    relationships = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_xml.findall("r:Relationship", rel_ns)}
    sheets = workbook_xml.findall(".//x:sheet", main_ns)
    selected = sheets[0] if sheet_name is None else sheets[int(sheet_name) if isinstance(sheet_name, int) else 0]
    if isinstance(sheet_name, str):
        selected = next((sheet for sheet in sheets if sheet.attrib.get("name") == sheet_name), selected)
    rel_id = selected.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    target = relationships[rel_id]
    return f"xl/{target}" if not target.startswith("/") and not target.startswith("xl/") else target.lstrip("/")


def column_ref_to_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - ord("A") + 1
    return max(index - 1, 0)


def read_xlsx_cell(cell: ElementTree.Element, shared_strings: list[str], namespace: dict[str, str]) -> str:
    value = cell.findtext("x:v", default="", namespaces=namespace)
    if cell.attrib.get("t") == "s" and value:
        return shared_strings[int(value)]
    if cell.attrib.get("t") == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//x:t", namespace))
    return value


def http_get(url: str, params: dict[str, Any] | None = None, timeout: int = 30, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    query = parse.urlencode(params or {})
    full_url = f"{url}?{query}" if query else url
    req = request.Request(full_url, headers=headers or {"User-Agent": "bizline-risk-sources/0.1"})
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - fixed public API URLs.
            return response.read(), response.geturl()
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code} for {full_url}: {detail}") from exc


class OpenDartClient:
    def __init__(self, api_key: str, cache_dir: Path, timeout: int = 30, sleep_seconds: float = 0.15) -> None:
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds

    def load_corp_codes(self, refresh: bool = False) -> list[dict[str, str]]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / "dart_corp_codes.json"
        if cache_path.exists() and not refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        content, _ = http_get(f"{DART_BASE_URL}/corpCode.xml", {"crtfc_key": self.api_key}, self.timeout)
        if content[:2] != b"PK":
            raise RuntimeError(f"OpenDART corpCode.xml did not return a ZIP file: {content[:200]!r}")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = ElementTree.fromstring(archive.read("CORPCODE.xml"))
        companies = [
            {
                "corp_code": item.findtext("corp_code", "").strip(),
                "corp_name": item.findtext("corp_name", "").strip(),
                "stock_code": item.findtext("stock_code", "").strip(),
                "modify_date": item.findtext("modify_date", "").strip(),
            }
            for item in root.findall("list")
        ]
        cache_path.write_text(json.dumps(companies, ensure_ascii=False, indent=2), encoding="utf-8")
        return companies

    def company_overview(self, corp_code: str) -> dict[str, Any]:
        content, _ = http_get(f"{DART_BASE_URL}/company.json", {"crtfc_key": self.api_key, "corp_code": corp_code}, self.timeout)
        time.sleep(self.sleep_seconds)
        return json.loads(content.decode("utf-8"))

    def disclosures(self, corp_code: str, begin_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_no = 1
        while True:
            content, _ = http_get(
                f"{DART_BASE_URL}/list.json",
                {
                    "crtfc_key": self.api_key,
                    "corp_code": corp_code,
                    "bgn_de": begin_date.strftime("%Y%m%d"),
                    "end_de": end_date.strftime("%Y%m%d"),
                    "page_no": page_no,
                    "page_count": 100,
                },
                self.timeout,
            )
            data = json.loads(content.decode("utf-8"))
            if data.get("status") not in {"000", "013"}:
                raise RuntimeError(f"OpenDART disclosure search failed for {corp_code}: {data}")
            rows.extend(data.get("list") or [])
            if page_no >= int(data.get("total_page") or 1):
                break
            page_no += 1
            time.sleep(self.sleep_seconds)
        return rows


def match_dart_company(customer: CustomerInput, corp_codes: list[dict[str, str]], client: OpenDartClient) -> DartCompanyResult:
    target_name = normalize_company_name(customer.customer_name)
    candidates = [corp for corp in corp_codes if normalize_company_name(corp.get("corp_name")) == target_name]
    if not candidates:
        partial = [corp for corp in corp_codes if target_name and target_name in normalize_company_name(corp.get("corp_name"))]
        return DartCompanyResult(customer=customer, matched_by="review_required" if partial else "no_match", candidates=partial[:10])
    overview_errors: list[str] = []
    for candidate in candidates:
        try:
            overview = client.company_overview(candidate["corp_code"])
        except Exception as exc:  # noqa: BLE001 - keep collecting other candidates during batch tests.
            overview_errors.append(f"{candidate.get('corp_code')}: {exc}")
            continue
        if overview.get("status") != "000":
            overview_errors.append(f"{candidate.get('corp_code')}: {overview.get('message')}")
            continue
        if normalize_biz_no(overview.get("bizr_no")) == customer.biz_no:
            corp_cls = overview.get("corp_cls") or candidate.get("corp_cls")
            return DartCompanyResult(
                customer=customer,
                corp_code=overview.get("corp_code") or candidate.get("corp_code"),
                corp_name=overview.get("corp_name") or candidate.get("corp_name"),
                bizr_no=normalize_biz_no(overview.get("bizr_no")),
                stock_code=overview.get("stock_code") or candidate.get("stock_code") or None,
                corp_cls=corp_cls,
                market_type=CORP_CLASS_TO_MARKET.get(corp_cls, "비상장" if not overview.get("stock_code") else None),
                matched_by="name_exact_biz_verified",
                candidates=candidates,
                raw_data=overview,
            )
    return DartCompanyResult(
        customer=customer,
        matched_by="review_required",
        candidates=candidates,
        error="; ".join(overview_errors) or "Company name matched but business number was not verified.",
    )


def classify_risk(title: str | None) -> tuple[str, str | None, str | None]:
    text = title or ""
    for keyword, event_type, risk_level in RISK_KEYWORDS:
        if keyword in text:
            return event_type, risk_level, keyword
    return "기타", "정상", None


def map_dart_disclosure(company: DartCompanyResult, row: dict[str, Any]) -> DartDisclosureResult:
    title = row.get("report_nm")
    _, risk_level, reason = classify_risk(title)
    receipt_no = row.get("rcept_no") or ""
    return DartDisclosureResult(
        biz_no=company.customer.biz_no,
        customer_name=company.customer.customer_name,
        corp_code=company.corp_code or row.get("corp_code") or "",
        receipt_no=receipt_no,
        report_name=title,
        flr_nm=row.get("flr_nm"),
        pblntf_ty=row.get("pblntf_ty"),
        disclosure_date=format_yyyymmdd(row.get("rcept_dt")),
        dart_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}" if receipt_no else None,
        risk_level=risk_level,
        risk_reason=reason,
        raw_data=row,
    )


def format_yyyymmdd(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return None


class KindClient:
    """Best-effort KIND scraper for market event testing."""

    EVENT_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
        ("관리종목", "/investwarn/adminissue.do", "searchAdminIssueSub"),
        ("거래정지", "/investwarn/tradinghaltissue.do", "searchTradingHaltIssueSub"),
        ("상장폐지", "/investwarn/delcompany.do", "searchDelCompanySub"),
    )

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def market_events(self, stock_code: str, company_name: str) -> list[dict[str, Any]]:
        if not stock_code:
            return []
        events: list[dict[str, Any]] = []
        headers = {"User-Agent": "Mozilla/5.0 (compatible; bizline-risk-sources/0.1)", "Referer": f"{KIND_BASE_URL}/"}
        for fallback_type, path, method in self.EVENT_ENDPOINTS:
            url = f"{KIND_BASE_URL}{path}"
            params = {
                "method": method,
                "currentPageSize": 100,
                "pageIndex": 1,
                "orderMode": 1,
                "orderStat": "D",
                "searchCodeType": "",
                "searchCorpName": company_name,
                "forward": "sub",
                "chose": "all",
            }
            try:
                content, final_url = http_get(url, params=params, timeout=self.timeout, headers=headers)
            except RuntimeError as exc:
                events.append({"event_type": fallback_type, "error": str(exc), "stock_code": stock_code})
                continue
            events.extend(parse_kind_html(content.decode("utf-8", errors="replace"), stock_code, fallback_type, final_url))
        return events


class KindTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_row = False
        self.in_cell = False
        self.current_cells: list[str] = []
        self.current_text: list[str] = []
        self.current_href: str | None = None
        self.current_link_text: list[str] = []
        self.rows: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.current_cells = []
            self.current_href = None
            self.current_link_text = []
        elif self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.current_text = []
        elif self.in_row and tag == "a" and attrs_dict.get("href"):
            self.current_href = attrs_dict["href"]
            self.current_link_text = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_text.append(data)
        if self.in_row and self.current_href is not None:
            self.current_link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.in_row and tag in {"td", "th"}:
            self.current_cells.append(" ".join("".join(self.current_text).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self.rows.append({"cells": self.current_cells, "href": self.current_href, "link_text": " ".join("".join(self.current_link_text).split())})
            self.in_row = False


def parse_kind_html(html_text: str, stock_code: str, fallback_event_type: str, source_url: str | None = None) -> list[dict[str, Any]]:
    parser = KindTableParser()
    parser.feed(html_text)
    rows: list[dict[str, Any]] = []
    for parsed_row in parser.rows:
        cells = [html.unescape(cell) for cell in parsed_row["cells"]]
        text = " ".join(cells)
        if stock_code not in text:
            continue
        title = parsed_row["link_text"] or (cells[-1] if cells else text)
        event_type, risk_level, reason = classify_risk(title or text)
        rows.append(
            {
                "stock_code": stock_code,
                "event_type": event_type if event_type != "기타" else fallback_event_type,
                "event_title": title or text,
                "event_date": extract_date(text),
                "source_url": absolute_kind_url(parsed_row["href"]) or source_url,
                "risk_level": risk_level if reason else ("주의" if fallback_event_type == "관리종목" else "위험"),
                "risk_reason": reason or fallback_event_type,
                "cells": cells,
            }
        )
    return rows


def extract_date(text: str) -> str | None:
    match = re.search(r"(20\d{2})[./-]?(\d{2})[./-]?(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def absolute_kind_url(href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"{KIND_BASE_URL}{href}"
    return f"{KIND_BASE_URL}/{href}"


def map_kind_event(company: DartCompanyResult, row: dict[str, Any]) -> KindMarketEventResult:
    return KindMarketEventResult(
        biz_no=company.customer.biz_no,
        customer_name=company.customer.customer_name,
        stock_code=company.stock_code or row.get("stock_code") or "",
        event_type=row.get("event_type") or "기타",
        event_title=row.get("event_title") or row.get("error"),
        event_date=row.get("event_date"),
        source_url=row.get("source_url"),
        risk_level=row.get("risk_level") or "주의",
        risk_reason=row.get("risk_reason") or row.get("error"),
        raw_data=row,
    )


def collect(
    excel_path: Path,
    output_dir: Path,
    dart_api_key: str,
    sheet_name: str | int | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    refresh_corp_codes: bool = False,
) -> dict[str, list[Any]]:
    customers = read_customers_from_excel(excel_path, sheet_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    dart = OpenDartClient(dart_api_key, output_dir / ".cache")
    kind = KindClient()
    corp_codes = dart.load_corp_codes(refresh=refresh_corp_codes)
    end_date = dt.date.today()
    begin_date = end_date - dt.timedelta(days=lookback_days)
    companies: list[DartCompanyResult] = []
    disclosures: list[DartDisclosureResult] = []
    kind_events: list[KindMarketEventResult] = []
    for customer in customers:
        company = match_dart_company(customer, corp_codes, dart)
        companies.append(company)
        if company.corp_code:
            disclosures.extend(map_dart_disclosure(company, row) for row in dart.disclosures(company.corp_code, begin_date, end_date))
        if company.stock_code:
            kind_events.extend(map_kind_event(company, row) for row in kind.market_events(company.stock_code, company.customer.customer_name))
    write_outputs(output_dir, companies, disclosures, kind_events)
    return {"dart_companies": companies, "dart_disclosures": disclosures, "kind_market_events": kind_events}


def write_outputs(output_dir: Path, companies: list[DartCompanyResult], disclosures: list[DartDisclosureResult], kind_events: list[KindMarketEventResult]) -> None:
    payloads = {
        "dart_companies": [flatten_dataclass(item) for item in companies],
        "dart_disclosures": [flatten_dataclass(item) for item in disclosures],
        "kind_market_events": [flatten_dataclass(item) for item in kind_events],
    }
    (output_dir / "result.json").write_text(json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, rows in payloads.items():
        write_csv(output_dir / f"{name}.csv", rows)


def flatten_dataclass(item: Any) -> dict[str, Any]:
    row = asdict(item)
    if "customer" in row:
        customer = row.pop("customer")
        row = {**customer, **row}
    return row


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["empty"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect only OpenDART and KIND data from an Excel customer list.")
    parser.add_argument("--excel", required=True, type=Path, help="Input Excel file containing 사업자등록번호 and 업체명 columns.")
    parser.add_argument("--output-dir", default=Path("out/risk_sources"), type=Path, help="Directory for JSON/CSV outputs.")
    parser.add_argument("--dart-api-key", default=os.getenv("OPENDART_API_KEY"), help="OpenDART API key. Defaults to OPENDART_API_KEY.")
    parser.add_argument("--sheet-name", help="Excel sheet name. Defaults to the first sheet.")
    parser.add_argument("--lookback-days", default=DEFAULT_LOOKBACK_DAYS, type=int, help="DART disclosure lookback window.")
    parser.add_argument("--refresh-corp-codes", action="store_true", help="Download corpCode.xml even when a cache exists.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.dart_api_key:
        parser.error("--dart-api-key or OPENDART_API_KEY is required for OpenDART collection.")
    collect(args.excel, args.output_dir, args.dart_api_key, args.sheet_name, args.lookback_days, args.refresh_corp_codes)
    print(f"OpenDART/KIND collection finished. Outputs: {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
