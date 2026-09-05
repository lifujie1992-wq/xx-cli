import pytest

from tmall_sku_cli.feishu_url import parse_feishu_url
from tmall_sku_cli.output import CliError


@pytest.mark.unit
def test_parse_wiki_url() -> None:
    kind, token = parse_feishu_url("https://example.feishu.cn/wiki/REPLACE_WITH_WIKI_TOKEN")
    assert kind == "wiki"
    assert token == "REPLACE_WITH_WIKI_TOKEN"


@pytest.mark.unit
def test_parse_sheet_url() -> None:
    kind, token = parse_feishu_url(
        "https://example.feishu.cn/sheets/REPLACE_WITH_SHEET_TOKEN?sheet=example"
    )
    assert kind == "sheet"
    assert token == "REPLACE_WITH_SHEET_TOKEN"


@pytest.mark.unit
def test_reject_non_feishu_url() -> None:
    with pytest.raises(CliError) as exc:
        parse_feishu_url("https://example.com/wiki/abc")
    assert exc.value.code == "invalid_feishu_url"
