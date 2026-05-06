from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IntParameter,
    IStrategy,
    stoploss_from_absolute,
)


class TrendFlowV2(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "4h"
    process_only_new_candles = True
    startup_candle_count: int = 300

    minimal_roi = {"0": 1.0}
    stoploss = -0.50
    use_custom_stoploss = True
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    ema_period = IntParameter(20, 60, default=40, space="buy", optimize=True)
    adx_threshold = IntParameter(15, 30, default=20, space="buy", optimize=True)
    atr_stop_mult = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space="sell", optimize=True)
    trail_at_r = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space="sell", optimize=True)
    trail_atr_mult = DecimalParameter(
        0.8, 1.5, default=1.0, decimals=1, space="sell", optimize=True
    )

    def informative_pairs(self):
        return []

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_ma"] = dataframe["atr"].rolling(window=50, min_periods=50).mean()
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        ema = int(self.ema_period.value)
        dataframe["ema"] = ta.EMA(dataframe, timeperiod=ema)

        dataframe["trending"] = (dataframe["adx"] > self.adx_threshold.value) & (
            dataframe["atr"] > dataframe["atr_ma"]
        )

        dataframe["trend"] = 0
        dataframe.loc[(dataframe["close"] > dataframe["ema"]) & dataframe["trending"], "trend"] = 1
        dataframe.loc[(dataframe["close"] < dataframe["ema"]) & dataframe["trending"], "trend"] = -1

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        vol_guard = dataframe["volume"] > 0

        trend_up_now = dataframe["trend"] == 1
        trend_down_now = dataframe["trend"] == -1
        trend_up_prev = dataframe["trend"].shift(1) == 1
        trend_down_prev = dataframe["trend"].shift(1) == -1

        enter_long = vol_guard & trend_up_now & ~trend_up_prev
        enter_short = vol_guard & trend_down_now & ~trend_down_prev

        df = dataframe
        df.loc[enter_long, ["enter_long", "enter_tag"]] = (1, "trend_up")
        df.loc[enter_short, ["enter_short", "enter_tag"]] = (1, "trend_down")

        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0

        dataframe.loc[dataframe["trend"] != 1, "exit_long"] = 1
        dataframe.loc[dataframe["trend"] != -1, "exit_short"] = 1

        return dataframe

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        return min(3.0, max_leverage)

    def _get_stop_mult(self, adx: float) -> float:
        base = self.atr_stop_mult.value
        if pd.isna(adx):
            return base
        if adx > 30:
            return base * 0.75
        if adx > 20:
            return base
        return base * 1.25

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs: Any,
    ) -> float | None:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None

        candle = dataframe.iloc[-1]
        atr = candle.get("atr", 0)
        if atr <= 0 or pd.isna(atr):
            return None

        stop_mult = self._get_stop_mult(candle.get("adx", np.nan))
        stop_distance = stop_mult * atr
        initial_stop_pct = stop_distance / trade.open_rate

        if current_profit >= self.trail_at_r.value * initial_stop_pct:
            trail_price = (
                current_rate + self.trail_atr_mult.value * atr
                if trade.is_short
                else current_rate - self.trail_atr_mult.value * atr
            )
            sl = stoploss_from_absolute(trail_price, current_rate, trade.is_short, trade.leverage)
            if sl is not None and not np.isnan(sl):
                return sl

        stop_price = trade.open_rate * (
            (1 + initial_stop_pct) if trade.is_short else (1 - initial_stop_pct)
        )
        sl = stoploss_from_absolute(stop_price, current_rate, trade.is_short, trade.leverage)
        if sl is not None and not np.isnan(sl):
            return sl
        return None
