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
    stoploss_from_open,
)


class AdaptiveConfluenceV3(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count: int = 500

    minimal_roi = {"0": 0.10}
    stoploss = -0.08
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

    # ── buy space ──────────────────────────────────────────────
    ema_fast = IntParameter(15, 30, default=21, space="buy", optimize=True)
    ema_slow = IntParameter(40, 70, default=55, space="buy", optimize=True)
    trend_adx_threshold = IntParameter(15, 30, default=20, space="buy", optimize=True)
    rsi_min_breakout = IntParameter(35, 55, default=45, space="buy", optimize=True)
    rsi_max_breakout = IntParameter(75, 90, default=85, space="buy", optimize=True)
    volume_min_mult = DecimalParameter(
        0.8, 2.5, default=1.5, decimals=1, space="buy", optimize=True
    )
    body_ratio_min = DecimalParameter(0.3, 0.8, default=0.6, decimals=2, space="buy", optimize=True)
    pullback_rsi_max = IntParameter(25, 45, default=35, space="buy", optimize=True)
    atr_stop_mult_breakout = DecimalParameter(
        1.0, 2.5, default=1.5, decimals=1, space="buy", optimize=True
    )
    atr_stop_mult_pullback = DecimalParameter(
        0.3, 1.0, default=0.5, decimals=1, space="buy", optimize=True
    )

    # ── sell space ─────────────────────────────────────────────
    momentum_exit_rsi_peak = IntParameter(65, 85, default=70, space="sell", optimize=True)
    momentum_exit_rsi = IntParameter(55, 75, default=65, space="sell", optimize=True)
    macd_decline_bars = IntParameter(2, 5, default=3, space="sell", optimize=True)
    time_stop_breakout = IntParameter(15, 40, default=25, space="sell", optimize=True)
    time_stop_pullback = IntParameter(10, 25, default=15, space="sell", optimize=True)
    breakeven_at_r = DecimalParameter(
        0.8, 1.5, default=1.0, decimals=1, space="sell", optimize=True
    )
    trail_at_r = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space="sell", optimize=True)
    trail_atr_mult = DecimalParameter(
        0.5, 1.5, default=1.0, decimals=1, space="sell", optimize=True
    )

    # ── informaitve pairs ──────────────────────────────────────

    def informative_pairs(self):
        if not getattr(self, "dp", None):
            return []
        pairs = []
        for pair in self.dp.current_whitelist():
            pairs.append((pair, "1h"))
            pairs.append((pair, "4h"))
        return pairs

    # ── 4h indicators: trend direction ─────────────────────────

    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_fast = int(self.ema_fast.value)
        ema_slow = int(self.ema_slow.value)

        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=ema_fast)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=ema_slow)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        dataframe["trend_up"] = (
            (dataframe["ema_fast"] > dataframe["ema_slow"])
            & (dataframe["adx"] > self.trend_adx_threshold.value)
        ).astype(int)
        dataframe["trend_down"] = (
            (dataframe["ema_fast"] < dataframe["ema_slow"])
            & (dataframe["adx"] > self.trend_adx_threshold.value)
        ).astype(int)

        return dataframe

    # ── 1h indicators: swing points + volatility regime ────────

    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        atr_ma_period = 100
        dataframe["atr_ma"] = (
            dataframe["atr"].rolling(window=atr_ma_period, min_periods=atr_ma_period).mean()
        )
        dataframe["atr_pct_rank"] = (
            dataframe["atr"].rolling(window=atr_ma_period, min_periods=atr_ma_period).rank(pct=True)
        )

        dataframe["atr_slope"] = dataframe["atr"].diff(5) / 5.0
        dataframe["vol_expanding"] = (
            (dataframe["atr"] > dataframe["atr_ma"]) & (dataframe["atr_slope"] > 0)
        ).astype(int)

        high = dataframe["high"]
        low = dataframe["low"]

        is_swing_high = (
            (high > high.shift(1))
            & (high > high.shift(2))
            & (high > high.shift(-1).fillna(high))
            & (high > high.shift(-2).fillna(high))
        )
        dataframe["swing_high"] = np.where(is_swing_high, high, np.nan)
        dataframe["swing_high"] = dataframe["swing_high"].ffill()

        is_swing_low = (
            (low < low.shift(1))
            & (low < low.shift(2))
            & (low < low.shift(-1).fillna(low))
            & (low < low.shift(-2).fillna(low))
        )
        dataframe["swing_low"] = np.where(is_swing_low, low, np.nan)
        dataframe["swing_low"] = dataframe["swing_low"].ffill()

        dataframe["swing_high_broken"] = (
            dataframe["close"] > dataframe["swing_high"].shift(1)
        ).astype(int)
        dataframe["swing_low_broken"] = (
            dataframe["close"] < dataframe["swing_low"].shift(1)
        ).astype(int)

        dataframe["resistance"] = dataframe["swing_high"].where(
            ~dataframe["swing_high_broken"].astype(bool)
        )
        dataframe["resistance"] = dataframe["resistance"].ffill()
        dataframe["support"] = dataframe["swing_low"].where(
            ~dataframe["swing_low_broken"].astype(bool)
        )
        dataframe["support"] = dataframe["support"].ffill()

        dataframe["proximity"] = 0.5 * dataframe["atr"]

        return dataframe

    # ── 5m indicators ──────────────────────────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_slope"] = (dataframe["rsi"] - dataframe["rsi"].shift(5)) / 5.0

        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_ma"] = dataframe["volume"].rolling(window=20).mean()

        candle_range = (dataframe["high"] - dataframe["low"]).replace(0, np.nan)
        dataframe["body_ratio"] = (dataframe["close"] - dataframe["open"]).abs() / candle_range
        dataframe["lower_wick"] = (
            dataframe[["close", "open"]].min(axis=1) - dataframe["low"]
        ) / candle_range
        dataframe["upper_wick"] = (
            dataframe["high"] - dataframe[["close", "open"]].max(axis=1)
        ) / candle_range

        dataframe["candle_top_half"] = (
            dataframe["close"] > (dataframe["high"] + dataframe["low"]) / 2
        ).astype(int)
        dataframe["candle_bottom_half"] = (
            dataframe["close"] < (dataframe["high"] + dataframe["low"]) / 2
        ).astype(int)

        dataframe["bullish_engulf"] = (
            (dataframe["close"].shift(1) < dataframe["open"].shift(1))
            & (dataframe["close"] > dataframe["open"])
            & (dataframe["open"] <= dataframe["close"].shift(1))
            & (dataframe["close"] >= dataframe["open"].shift(1))
        ).astype(int)
        dataframe["bearish_engulf"] = (
            (dataframe["close"].shift(1) > dataframe["open"].shift(1))
            & (dataframe["close"] < dataframe["open"])
            & (dataframe["open"] >= dataframe["close"].shift(1))
            & (dataframe["close"] <= dataframe["open"].shift(1))
        ).astype(int)

        dataframe["rsi_div_bull"] = (
            (dataframe["low"] < dataframe["low"].shift(1))
            & (dataframe["low"].shift(1) < dataframe["low"].shift(2))
            & (dataframe["rsi"] > dataframe["rsi"].shift(1))
        ).astype(int)
        dataframe["rsi_div_bear"] = (
            (dataframe["high"] > dataframe["high"].shift(1))
            & (dataframe["high"].shift(1) > dataframe["high"].shift(2))
            & (dataframe["rsi"] < dataframe["rsi"].shift(1))
        ).astype(int)

        pair = metadata["pair"]

        # ── merge 4h ──────────────────────────────────────────
        inf_4h = None
        if getattr(self, "dp", None):
            try:
                inf_4h = self.dp.get_pair_dataframe(pair=pair, timeframe="4h")
            except Exception:
                inf_4h = None
        if inf_4h is not None and not inf_4h.empty:
            inf_4h = self.populate_indicators_4h(inf_4h.copy(), metadata)
            inf_4h["_merge_key"] = inf_4h["date"] + pd.Timedelta(hours=4) - pd.Timedelta(minutes=5)
            dataframe = dataframe.merge(
                inf_4h[["_merge_key", "trend_up", "trend_down", "adx"]].rename(
                    columns={
                        "trend_up": "trend_up_4h",
                        "trend_down": "trend_down_4h",
                        "adx": "adx_4h",
                    }
                ),
                left_on="date",
                right_on="_merge_key",
                how="left",
                suffixes=("", ""),
            )
            dataframe.drop(columns=["_merge_key"], inplace=True, errors="ignore")
            dataframe["trend_up_4h"] = dataframe["trend_up_4h"].ffill().fillna(0)
            dataframe["trend_down_4h"] = dataframe["trend_down_4h"].ffill().fillna(0)
            dataframe["adx_4h"] = dataframe["adx_4h"].ffill()
        else:
            dataframe["trend_up_4h"] = 0
            dataframe["trend_down_4h"] = 0
            dataframe["adx_4h"] = np.nan

        # ── merge 1h ──────────────────────────────────────────
        inf_1h = None
        if getattr(self, "dp", None):
            try:
                inf_1h = self.dp.get_pair_dataframe(pair=pair, timeframe="1h")
            except Exception:
                inf_1h = None
        if inf_1h is not None and not inf_1h.empty:
            inf_1h = self.populate_indicators_1h(inf_1h.copy(), metadata)
            inf_1h["_merge_key"] = inf_1h["date"] + pd.Timedelta(hours=1) - pd.Timedelta(minutes=5)
            merge_cols = [
                "_merge_key",
                "atr_pct_rank",
                "vol_expanding",
                "resistance",
                "support",
                "proximity",
                "swing_high",
                "swing_low",
            ]
            dataframe = dataframe.merge(
                inf_1h[merge_cols].rename(
                    columns={
                        "atr_pct_rank": "atr_pct_rank_1h",
                        "vol_expanding": "vol_expanding_1h",
                        "resistance": "resistance_1h",
                        "support": "support_1h",
                        "proximity": "proximity_1h",
                        "swing_high": "swing_high_1h",
                        "swing_low": "swing_low_1h",
                    }
                ),
                left_on="date",
                right_on="_merge_key",
                how="left",
                suffixes=("", ""),
            )
            dataframe.drop(columns=["_merge_key"], inplace=True, errors="ignore")
            for col in [
                "atr_pct_rank_1h",
                "vol_expanding_1h",
                "resistance_1h",
                "support_1h",
                "proximity_1h",
                "swing_high_1h",
                "swing_low_1h",
            ]:
                dataframe[col] = dataframe[col].ffill()
        else:
            dataframe["atr_pct_rank_1h"] = np.nan
            dataframe["vol_expanding_1h"] = 0
            dataframe["resistance_1h"] = np.nan
            dataframe["support_1h"] = np.nan
            dataframe["proximity_1h"] = np.nan
            dataframe["swing_high_1h"] = np.nan
            dataframe["swing_low_1h"] = np.nan

        # ── volatility regime on 5m (fallback) ────────────────
        dataframe["vol_regime"] = "normal"
        pct = dataframe["atr_pct_rank_1h"]
        dataframe.loc[pct > 0.80, "vol_regime"] = "high"
        dataframe.loc[pct < 0.20, "vol_regime"] = "low"
        dataframe.loc[pct.isna(), "vol_regime"] = "normal"

        return dataframe

    # ── entry signals (fully vectorized) ───────────────────────

    def _build_entry_signals(self, df: DataFrame) -> DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0
        df["enter_tag"] = ""

        vol_guard = df["volume"] > 0

        trend_up = df["trend_up_4h"] == 1
        trend_down = df["trend_down_4h"] == 1
        trend_neutral = (df["trend_up_4h"] == 0) & (df["trend_down_4h"] == 0)

        vol_low = df["vol_regime"] == "low"
        vol_expanding = df["vol_expanding_1h"] == 1
        vol_not_low = ~vol_low
        vol_low_expanding = vol_low & vol_expanding

        allowed_long = trend_up | trend_neutral
        allowed_short = trend_down | trend_neutral

        # ── Mode A: Momentum Breakout ──────────────────────────
        resistance = df["resistance_1h"]
        support = df["support_1h"]
        prev_close = df["close"].shift(1)

        breakout_above = (
            vol_guard
            & allowed_long
            & vol_not_low
            & df["close"].notna()
            & resistance.notna()
            & (prev_close <= resistance)
            & (df["close"] > resistance)
            & (df["body_ratio"] > self.body_ratio_min.value)
            & (df["volume"] > df["volume_ma"] * self.volume_min_mult.value)
            & (df["rsi"] > self.rsi_min_breakout.value)
            & (df["rsi"] < self.rsi_max_breakout.value)
        )

        breakdown_below = (
            vol_guard
            & allowed_short
            & vol_not_low
            & df["close"].notna()
            & support.notna()
            & (prev_close >= support)
            & (df["close"] < support)
            & (df["body_ratio"] > self.body_ratio_min.value)
            & (df["volume"] > df["volume_ma"] * self.volume_min_mult.value)
            & (df["rsi"] < (100 - self.rsi_min_breakout.value))
            & (df["rsi"] > (100 - self.rsi_max_breakout.value))
        )

        # ── Mode B: Trend Pullback ─────────────────────────────
        near_support = (
            support.notna() & df["close"].notna() & (df["close"] - support).abs()
            <= df["proximity_1h"]
        )
        near_resistance = (
            resistance.notna() & df["close"].notna() & (df["close"] - resistance).abs()
            <= df["proximity_1h"]
        )

        rejection_bullish = (
            (df["lower_wick"] > 1.5)
            | (df["bullish_engulf"] == 1)
            | ((df["close"] > df["open"]) & (df["candle_top_half"] == 1))
        )

        rejection_bearish = (
            (df["upper_wick"] > 1.5)
            | (df["bearish_engulf"] == 1)
            | ((df["close"] < df["open"]) & (df["candle_bottom_half"] == 1))
        )

        rsi_ok_long = (df["rsi_div_bull"] == 1) | (df["rsi"] < self.pullback_rsi_max.value)
        rsi_ok_short = (df["rsi_div_bear"] == 1) | (df["rsi"] > (100 - self.pullback_rsi_max.value))

        pullback_long = (
            vol_guard & trend_up & vol_not_low & near_support & rejection_bullish & rsi_ok_long
        )

        pullback_short = (
            vol_guard
            & trend_down
            & vol_not_low
            & near_resistance
            & rejection_bearish
            & rsi_ok_short
        )

        # ── Low-vol breakout (vol expanding only) ──────────────
        breakout_above_lowvol = (
            vol_guard
            & allowed_long
            & vol_low_expanding
            & df["close"].notna()
            & resistance.notna()
            & (prev_close <= resistance)
            & (df["close"] > resistance)
            & (df["body_ratio"] > 0.7)
            & (df["volume"] > df["volume_ma"] * 1.5)
            & (df["rsi"] > self.rsi_min_breakout.value)
            & (df["rsi"] < self.rsi_max_breakout.value)
        )

        breakdown_below_lowvol = (
            vol_guard
            & allowed_short
            & vol_low_expanding
            & df["close"].notna()
            & support.notna()
            & (prev_close >= support)
            & (df["close"] < support)
            & (df["body_ratio"] > 0.7)
            & (df["volume"] > df["volume_ma"] * 1.5)
            & (df["rsi"] < (100 - self.rsi_min_breakout.value))
            & (df["rsi"] > (100 - self.rsi_max_breakout.value))
        )

        # ── Final assignment: standard pattern df.loc[mask, ["col", "tag"]] = (val, tag) ──
        mask = breakout_above & (df["enter_long"] == 0)
        df.loc[mask, ["enter_long", "enter_tag"]] = (1, "momentum_breakout_long")

        mask = breakout_above_lowvol & (df["enter_long"] == 0)
        df.loc[mask, ["enter_long", "enter_tag"]] = (1, "momentum_breakout_long_lowvol")

        mask = pullback_long & (df["enter_long"] == 0)
        df.loc[mask, ["enter_long", "enter_tag"]] = (1, "pullback_long")

        mask = breakdown_below & (df["enter_short"] == 0)
        df.loc[mask, ["enter_short", "enter_tag"]] = (1, "momentum_breakdown_short")

        mask = breakdown_below_lowvol & (df["enter_short"] == 0)
        df.loc[mask, ["enter_short", "enter_tag"]] = (1, "momentum_breakdown_short_lowvol")

        mask = pullback_short & (df["enter_short"] == 0)
        df.loc[mask, ["enter_short", "enter_tag"]] = (1, "pullback_short")

        return df

    # ── populate_entry_trend / populate_exit_trend ─────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""
        return self._build_entry_signals(dataframe)

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    # ── leverage ───────────────────────────────────────────────

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
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return min(5.0, max_leverage)

        trend_neutral = (dataframe.iloc[-1].get("trend_up_4h", 0) == 0) & (
            dataframe.iloc[-1].get("trend_down_4h", 0) == 0
        )
        if trend_neutral:
            return min(3.0, max_leverage)
        return min(5.0, max_leverage)

    # ── custom_stoploss ────────────────────────────────────────

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
        atr_5m = candle.get("atr", 0)
        if atr_5m <= 0 or pd.isna(atr_5m):
            return None

        is_breakout = "breakout" in (trade.enter_tag or "")
        is_pullback = "pullback" in (trade.enter_tag or "")

        if is_breakout:
            stop_distance = self.atr_stop_mult_breakout.value * atr_5m
        elif is_pullback:
            stop_distance = self.atr_stop_mult_pullback.value * atr_5m
        else:
            stop_distance = self.atr_stop_mult_breakout.value * atr_5m

        initial_stop_pct = stop_distance / trade.open_rate

        # breakeven
        if current_profit >= self.breakeven_at_r.value * initial_stop_pct:
            sl = stoploss_from_open(0.001, current_profit, trade.is_short, trade.leverage)
            if sl is not None and not np.isnan(sl):
                return sl

        # trailing after 2R
        if current_profit >= self.trail_at_r.value * initial_stop_pct:
            if trade.is_short:
                trail_price = current_rate + self.trail_atr_mult.value * atr_5m
                sl = stoploss_from_absolute(
                    trail_price, current_rate, trade.is_short, trade.leverage
                )
            else:
                trail_price = current_rate - self.trail_atr_mult.value * atr_5m
                sl = stoploss_from_absolute(
                    trail_price, current_rate, trade.is_short, trade.leverage
                )
            if sl is not None and not np.isnan(sl):
                return sl

        return None

    # ── custom_exit ────────────────────────────────────────────

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> str | None:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) < 5:
            return None

        candle = dataframe.iloc[-1]
        hold_candles = (current_time - trade.open_date_utc).total_seconds() / 300.0
        is_breakout = "breakout" in (trade.enter_tag or "")
        is_pullback = "pullback" in (trade.enter_tag or "")

        result = self._check_time_stop(hold_candles, is_breakout)
        if result:
            return result

        result = self._check_trend_reversal(candle, trade.is_short)
        if result:
            return result

        if is_breakout and current_profit > 0:
            result = self._check_momentum_exhaustion(dataframe, candle, trade.is_short)
            if result:
                return result

            result = self._check_rsi_momentum(dataframe, candle, trade.is_short, current_profit)
            if result:
                return result

        if is_pullback and current_profit > 0:
            result = self._check_sr_target(candle, trade.is_short, current_rate)
            if result:
                return result

        return None

    def _check_time_stop(self, hold_candles: float, is_breakout: bool) -> str | None:
        max_candles = (
            self.time_stop_breakout.value if is_breakout else self.time_stop_pullback.value
        )
        if hold_candles >= max_candles:
            return "time_stop"
        return None

    def _check_trend_reversal(self, candle: pd.Series, is_short: bool) -> str | None:
        trend_up = candle.get("trend_up_4h", 0) == 1
        trend_down = candle.get("trend_down_4h", 0) == 1
        if is_short and trend_up:
            return "trend_reversal"
        if not is_short and trend_down:
            return "trend_reversal"
        return None

    def _check_momentum_exhaustion(
        self, dataframe: DataFrame, candle: pd.Series, is_short: bool
    ) -> str | None:
        recent = dataframe.tail(10)
        macd_hist = recent["macdhist"]
        if len(macd_hist) < self.macd_decline_bars.value:
            return None
        if is_short:
            hist_rising = (macd_hist.diff() > 0).rolling(self.macd_decline_bars.value).sum()
            if hist_rising.iloc[-1] >= self.macd_decline_bars.value:
                return "momentum_exhaustion"
        else:
            hist_declining = (macd_hist.diff() < 0).rolling(self.macd_decline_bars.value).sum()
            if hist_declining.iloc[-1] >= self.macd_decline_bars.value:
                return "momentum_exhaustion"
        return None

    def _check_rsi_momentum(
        self, dataframe: DataFrame, candle: pd.Series, is_short: bool, current_profit: float
    ) -> str | None:
        if current_profit <= 0.02:
            return None
        prev_rsi = dataframe.iloc[-5:]["rsi"]
        if is_short:
            if candle["rsi"] < (100 - self.momentum_exit_rsi_peak.value):
                if prev_rsi.min() < (100 - self.momentum_exit_rsi.value):
                    return "rsi_momentum_exit"
        else:
            if candle["rsi"] < self.momentum_exit_rsi.value:
                if prev_rsi.max() > self.momentum_exit_rsi_peak.value:
                    return "rsi_momentum_exit"
        return None

    def _check_sr_target(
        self, candle: pd.Series, is_short: bool, current_rate: float
    ) -> str | None:
        if is_short:
            target = candle.get("support_1h", np.nan)
            if not pd.isna(target) and current_rate <= target:
                return "sr_target"
        else:
            target = candle.get("resistance_1h", np.nan)
            if not pd.isna(target) and current_rate >= target:
                return "sr_target"
        return None

    # ── position sizing ────────────────────────────────────────

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return proposed_stake

        candle = dataframe.iloc[-1]
        atr_5m = candle.get("atr", 0)
        if atr_5m <= 0 or pd.isna(atr_5m):
            return proposed_stake

        is_breakout = entry_tag and "breakout" in entry_tag
        mult = (
            self.atr_stop_mult_breakout.value if is_breakout else self.atr_stop_mult_pullback.value
        )
        stop_distance = mult * atr_5m

        if stop_distance <= 0:
            return proposed_stake

        risk_pct = 0.01
        wallet = self.wallets.get_total_stake_amount() if self.wallets else proposed_stake * 100
        risk_amount = wallet * risk_pct
        position_by_risk = (risk_amount / stop_distance) * current_rate

        stake = min(position_by_risk, max_stake)
        if min_stake is not None:
            stake = max(stake, min_stake)

        vol_regime = candle.get("vol_regime", "normal")
        if vol_regime == "high":
            stake *= 0.7
        elif vol_regime == "low":
            stake *= 0.7

        trend_neutral = (candle.get("trend_up_4h", 0) == 0) & (candle.get("trend_down_4h", 0) == 0)
        if trend_neutral:
            stake *= 0.5

        return stake
