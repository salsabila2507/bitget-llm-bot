import bitget_llm_trader as bot


def test_extract_json_array_with_extra_text():
    text = """
    Here is the result:
    [{"rank": 1, "symbol": "BTCUSDT", "direction": "LONG", "open": true}]
    Extra notes with [not json
    """
    parsed = bot.extract_json_array(text)
    assert parsed[0]["symbol"] == "BTCUSDT"
    assert parsed[0]["open"] is True


def test_extract_json_array_python_literal():
    text = "```json\n[{'rank': 1, 'symbol': 'ETHUSDT', 'direction': 'SHORT', 'open': False,}]\n```"
    parsed = bot.extract_json_array(text)
    assert parsed[0]["symbol"] == "ETHUSDT"
    assert parsed[0]["open"] is False


def test_close_position_failure_list_blocks_db_close():
    res = {
        "code": "00000",
        "data": {
            "failureList": [
                {"symbol": "BTCUSDT", "holdSide": "long", "errorMsg": "position not found"}
            ],
            "successList": [],
        },
    }
    ok, reason = bot.close_position_succeeded(res, "BTCUSDT", "LONG")
    assert ok is False
    assert "position not found" in reason


def test_close_position_success_list_matches_symbol_side():
    res = {
        "code": "00000",
        "data": {
            "failureList": [],
            "successList": [{"symbol": "BTCUSDT", "holdSide": "short"}],
        },
    }
    ok, reason = bot.close_position_succeeded(res, "BTCUSDT", "SHORT")
    assert ok is True
    assert reason == ""


def test_trade_mode_profiles_switch_cleanly():
    assert bot.apply_trade_mode("normal") is True
    assert bot.TRADE_MODE == "normal"
    assert bot.SLEEP_MINUTES == 60
    assert bot.TAKE_PROFIT_ROI_PCT == 70.0
    assert bot.STOP_LOSS_ROI_PCT == 40.0

    assert bot.apply_trade_mode("scalping") is True
    assert bot.TRADE_MODE == "scalping"
    assert bot.SLEEP_MINUTES == 5
    assert bot.TAKE_PROFIT_ROI_PCT == 10.0
    assert bot.STOP_LOSS_ROI_PCT == 6.0
