#!/usr/bin/env python3
"""Download OpenDART corporation codes and save them as a CSV file.

The OpenDART ``corpCode.xml`` endpoint returns a ZIP file containing an XML
file with DART corporation code records. This script downloads the ZIP,
extracts the XML, and writes the commonly needed fields to CSV:
``corp_code``, ``corp_name``, ``stock_code``, and ``modify_date``.
"""

from __future__ import annotations

import argparse
import csv
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree

OPENDART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
CSV_COLUMNS = ("corp_code", "corp_name", "stock_code", "modify_date")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download DART disclosure target company codes from OpenDART "
            "and save corp_code, corp_name, stock_code, and modify_date as CSV."
        )
    )
    parser.add_argument(
        "-k",
        "--api-key",
        default=os.getenv("OPENDART_API_KEY"),
        help="OpenDART API key. If omitted, OPENDART_API_KEY is used.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="dart_corp_codes.csv",
        help="Output CSV file path. Defaults to dart_corp_codes.csv.",
    )
    parser.add_argument(
        "--include-unlisted",
        action="store_true",
        help=(
            "Include rows without a stock_code. By default only listed companies "
            "with stock codes are exported."
        ),
    )
    parser.add_argument(
        "--insecure-skip-tls-verify",
        action="store_true",
        help=(
            "Skip HTTPS certificate verification. Use only as a temporary workaround "
            "when your local Python certificate store is broken."
        ),
    )
    return parser.parse_args()


def download_corp_code_zip(
    api_key: str, insecure_skip_tls_verify: bool = False
) -> bytes:
    query = urllib.parse.urlencode({"crtfc_key": api_key})
    url = f"{OPENDART_CORP_CODE_URL}?{query}"

    request = urllib.request.Request(
        url, headers={"User-Agent": "bizline-opendart-downloader/1.0"}
    )
    context = None
    if insecure_skip_tls_verify:
        context = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(
            request, timeout=60, context=context
        ) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"OpenDART request failed with HTTP {exc.code}: {exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise RuntimeError(
                "OpenDART HTTPS 인증서 검증에 실패했습니다. "
                "Windows/Python 인증서 저장소 문제일 수 있습니다. "
                "먼저 README의 SSL 인증서 오류 해결 방법을 확인하세요. "
                "급하게 테스트만 해야 한다면 --insecure-skip-tls-verify 옵션을 "
                "임시로 사용할 수 있습니다."
            ) from exc
        raise RuntimeError(f"OpenDART request failed: {exc.reason}") from exc


def extract_xml_from_zip(zip_bytes: bytes) -> bytes:
    with tempfile.TemporaryFile() as zip_buffer:
        zip_buffer.write(zip_bytes)
        zip_buffer.seek(0)
        try:
            with zipfile.ZipFile(zip_buffer) as archive:
                xml_names = [
                    name for name in archive.namelist() if name.lower().endswith(".xml")
                ]
                if not xml_names:
                    raise RuntimeError("Downloaded ZIP did not contain an XML file.")
                with archive.open(xml_names[0]) as xml_file:
                    return xml_file.read()
        except zipfile.BadZipFile as exc:
            message = zip_bytes.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                "OpenDART did not return a valid ZIP file. "
                f"Response preview: {message}"
            ) from exc


def iter_corp_rows(xml_bytes: bytes, include_unlisted: bool) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_bytes)
    rows: list[dict[str, str]] = []

    for item in root.findall(".//list"):
        row = {column: (item.findtext(column) or "").strip() for column in CSV_COLUMNS}
        if include_unlisted or row["stock_code"]:
            rows.append(row)

    return rows


def write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print("error: provide --api-key or set OPENDART_API_KEY", file=sys.stderr)
        return 2

    output_path = Path(args.output)

    try:
        print("1/4 OpenDART에서 고유번호 ZIP 파일을 다운로드합니다...", flush=True)
        zip_bytes = download_corp_code_zip(
            args.api_key, insecure_skip_tls_verify=args.insecure_skip_tls_verify
        )

        print("2/4 ZIP 파일에서 XML을 추출합니다...", flush=True)
        xml_bytes = extract_xml_from_zip(zip_bytes)

        print("3/4 XML에서 회사 목록을 읽습니다...", flush=True)
        rows = iter_corp_rows(xml_bytes, include_unlisted=args.include_unlisted)

        print(f"4/4 CSV 파일을 저장합니다: {output_path}", flush=True)
        write_csv(rows, output_path)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"완료: {len(rows):,}개 행을 {output_path} 파일로 저장했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
