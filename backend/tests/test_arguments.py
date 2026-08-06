from __future__ import annotations

import pytest

from app.schemas import AppSettings, CatalogArgumentInput
from app.services.arguments import build_profile_argv, parse_help_output, split_custom_args


def test_split_custom_args_preserves_quotes_and_lines():
    assert split_custom_args('-np 1\n--chat-template-file "/srv/templates/my template.jinja"') == [
        "-np", "1", "--chat-template-file", "/srv/templates/my template.jinja"
    ]


def test_split_custom_args_rejects_unclosed_quote():
    with pytest.raises(ValueError, match="第 1 行无法解析"):
        split_custom_args('--chat-template-file "broken')


def test_build_argv_keeps_order_and_detects_alias_duplicate():
    settings = AppSettings(llama_server_bin="/opt/llama-server", llama_host="127.0.0.1", llama_port=8080)
    result = build_profile_argv(
        settings,
        "/models/model.gguf",
        [CatalogArgumentInput(flag="--parallel", value="2")],
        "-np 1\n--seed -1",
        {"--parallel", "-np", "--seed"},
        {"--parallel": "--parallel", "-np": "--parallel", "--seed": "--seed"},
    )
    assert result.argv[-6:] == ["--parallel", "2", "-np", "1", "--seed", "-1"]
    assert any("--parallel" in warning and "重复" in warning for warning in result.warnings)
    assert not any("-1" in warning for warning in result.warnings)


def test_parse_realistic_llama_help_output():
    parsed = parse_help_output(
        "  -c, --ctx-size N                 context size (default: 4096)\n"
        "                                      0 = from model\n"
        "  -fa, --flash-attn [on|off|auto]  set Flash Attention mode\n"
        "  --metrics                        enable prometheus endpoint\n"
    )
    by_flag = {entry["aliases"][-1]: entry for entry in parsed}
    assert by_flag["--ctx-size"]["value_hint"] == "N"
    assert "from model" in by_flag["--ctx-size"]["description"]
    assert by_flag["--flash-attn"]["value_hint"] == "[on|off|auto]"
    assert by_flag["--metrics"]["description"] == "enable prometheus endpoint"
