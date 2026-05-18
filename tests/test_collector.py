from __future__ import annotations

from pathlib import Path


from risk_sources.collector import (
    classify_risk,
    normalize_biz_no,
    normalize_company_name,
    parse_kind_html,
    read_customers_from_excel,
)


def test_normalize_biz_no_removes_non_digits_and_pads() -> None:
    assert normalize_biz_no("123-45-67890") == "1234567890"
    assert normalize_biz_no("123456789") == "0123456789"


def test_normalize_company_name_ignores_common_corporation_markers() -> None:
    assert normalize_company_name("(주) 테스트 회사") == "테스트회사"
    assert normalize_company_name("테스트회사 주식회사") == "테스트회사"


def test_read_customers_from_excel_with_korean_headers(tmp_path: Path) -> None:
    excel_path = tmp_path / "customers.csv"
    excel_path.write_text(
        "사업자등록번호,업체명\n123-45-67890,테스트\n0123456789,샘플\n",
        encoding="utf-8-sig",
    )

    customers = read_customers_from_excel(excel_path)

    assert [customer.biz_no for customer in customers] == ["1234567890", "0123456789"]
    assert [customer.customer_name for customer in customers] == ["테스트", "샘플"]


def test_classify_risk_detects_market_event_keywords() -> None:
    assert classify_risk("관리종목지정사유추가") == ("관리종목", "주의", "관리종목")
    assert classify_risk("주권매매거래정지") == ("거래정지", "위험", "매매거래정지")
    assert classify_risk("분기보고서") == ("기타", "정상", None)


def test_parse_kind_html_extracts_matching_stock_code_row() -> None:
    html = """
    <table>
      <tr>
        <td>2026.05.15</td><td>123456</td><td>테스트</td>
        <td><a href="/common/disclsviewer.do?method=search&acptno=1">관리종목지정</a></td>
      </tr>
      <tr><td>654321</td><td>다른회사</td><td>거래정지</td></tr>
    </table>
    """

    events = parse_kind_html(html, "123456", "관리종목")

    assert len(events) == 1
    assert events[0]["event_type"] == "관리종목"
    assert events[0]["risk_level"] == "주의"
    assert events[0]["event_date"] == "2026-05-15"
    assert events[0]["source_url"].startswith("https://kind.krx.co.kr/")
