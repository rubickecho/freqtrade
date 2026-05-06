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


class MomentumBreakout(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count: int = 100

    minimal_roi = {"0": 0.20}
    stoploss = -0.30
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
    momentum_lookback = IntParameter(10, 30, default=20, space="buy", optimize=True)
    volume_mult = DecimalParameter(1.2, 2.5, default=1.5, decimals=1, space="buy", optimize=True)
    body_ratio = DecimalParameter(0.4, 0.8, default=0.6, decimals=2, space="buy", optimize=True)
    atr_mult_entry = DecimalParameter(0.5, 1.5, default=1.0, decimals=1, space="buy", optimize=True)
    rsi_max_entry = IntParameter(65, 85, default=75, space="buy", optimize=True)

    # ── sell space ─────────────────────────────────────────────
    atr_stop_mult = DecimalParameter(1.5, 3.0, default=2.0, decimals=1, space="sell", optimize=True)
    trail_at_r = DecimalParameter(2.0, 4.0, default=3.0, decimals=1, space="sell", optimize=True)
    trail_atr_mult = DecimalParameter(
        0.8, 2.0, default=1.5, decimals=1, space="sell", optimize=True
    )
    macd_decline_bars = IntParameter(2, 5, default=3, space="sell", optimize=True)
    rsi_exit_peak = IntParameter(65, 85, default=75, space="sell", optimize=True)

    def informative_pairs(self):
        return []

    # ── 15m indicators ─────────────────────────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_ma"] = dataframe["volume"].rolling(window=20).mean()

        macd = ta.MACD(dataframe)
        dataframe["macdhist"] = macd["macdhist"]

        candle_range = (dataframe["high"] - dataframe["low"]).replace(0, np.nan)
        dataframe["body_ratio"] = (dataframe["close"] - dataframe["open"]).abs() / candle_range

        lb = int(self.momentum_lookback.value)
        dataframe["recent_high"] = dataframe["high"].shift(1).rolling(window=lb).max()
        dataframe["recent_low"] = dataframe["low"].shift(1).rolling(window=lb).min()

        dataframe["price_move"] = (dataframe["close"] - dataframe["close"].shift(1)).abs()
        dataframe["move_vs_atr"] = dataframe["price_move"] / dataframe["atr"]

        return dataframe

    # ── entry signals ─────────────────────────────────────────

    def _build_entry_signals(self, df: DataFrame) -> DataFrame:
        df["enter_long"] = 0
        df["enter_short"] = 0
        df["enter_tag"] = ""

        vol_guard = df["volume"] > 0

        breakout_long = (
            vol_guard
            & df["close"].notna()
            & df["recent_high"].notna()
            & (df["close"] > df["recent_high"])
            & (df["move_vs_atr"] > self.atr_mult_entry.value)
            & (df["volume"] > df["volume_ma"] * self.volume_mult.value)
            & (df["body_ratio"] > self.body_ratio.value)
            & (df["rsi"] < self.rsi_max_entry.value)
            & (df["rsi"] > 40)
        )

        breakout_short = (
            vol_guard
            & df["close"].notna()
            & df["recent_low"].notna()
            & (df["close"] < df["recent_low"])
            & (df["move_vs_atr"] > self.atr_mult_entry.value)
            & (df["volume"] > df["volume_ma"] * self.volume_mult.value)
            & (df["body_ratio"] > self.body_ratio.value)
            & (df["rsi"] > (100 - self.rsi_max_entry.value))
            & (df["rsi"] < 60)
        )

        mask = breakout_long & (df["enter_long"] == 0)
        df.loc[mask, ["enter_long", "enter_tag"]] = (1, "momentum_breakout_long")

        mask = breakout_short & (df["enter_short"] == 0)
        df.loc[mask, ["enter_short", "enter_tag"]] = (1, "momentum_breakout_short")

        return df

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
        atr = candle.get("atr", 0)
        if atr <= 0 or pd.isna(atr):
            return None

        stop_distance = self.atr_stop_mult.value * atr
        initial_stop_pct = stop_distance / trade.open_rate

        # trailing after 3R — use tighter stop
        if current_profit >= self.trail_at_r.value * initial_stop_pct:
            trail_price = (
                current_rate + self.trail_atr_mult.value * atr
                if trade.is_short
                else current_rate - self.trail_atr_mult.value * atr
            )
            sl = stoploss_from_absolute(trail_price, current_rate, trade.is_short, trade.leverage)
            if sl is not None and not np.isnan(sl):
                return sl

        # always return ATR-based initial stop — never fall through to hard stoploss
        if trade.is_short:
            return stoploss_from_absolute(
                trade.open_rate * (1 + initial_stop_pct),
                current_rate,
                trade.is_short,
                trade.leverage,
            )
        return stoploss_from_absolute(
            trade.open_rate * (1 - initial_stop_pct),
            current_rate,
            trade.is_short,
            trade.leverage,
        )

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
        if len(dataframe) < 10:
            return None

        candle = dataframe.iloc[-1]

        # ── momentum exhaustion (MACD) ─────────────────────────
        recent = dataframe.tail(10)
        macd_hist = recent["macdhist"]
        if len(macd_hist) >= self.macd_decline_bars.value:
            if trade.is_short:
                hist_rising = (macd_hist.diff() > 0).rolling(self.macd_decline_bars.value).sum()
                if hist_rising.iloc[-1] >= self.macd_decline_bars.value and current_profit > 0:
                    return "momentum_exhaustion"
            else:
                hist_declining = (macd_hist.diff() < 0).rolling(self.macd_decline_bars.value).sum()
                if hist_declining.iloc[-1] >= self.macd_decline_bars.value and current_profit > 0:
                    return "momentum_exhaustion"

        # ── RSI divergence ─────────────────────────────────────
        if current_profit > 0.02:
            prev_rsi = dataframe.iloc[-5:]["rsi"]
            if trade.is_short:
                if candle["rsi"] < (100 - self.rsi_exit_peak.value):
                    if prev_rsi.max() < (100 - self.rsi_exit_peak.value):
                        return "rsi_divergence"
            else:
                if candle["rsi"] > self.rsi_exit_peak.value:
                    if prev_rsi.min() > self.rsi_exit_peak.value:
                        return "rsi_divergence"

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
        atr = candle.get("atr", 0)
        if atr <= 0 or pd.isna(atr):
            return proposed_stake

        stop_distance = self.atr_stop_mult.value * atr
        if stop_distance <= 0:
            return proposed_stake

        risk_pct = 0.005
        wallet = self.wallets.get_total_stake_amount() if self.wallets else 1000
        risk_amount = wallet * risk_pct
        position_by_risk = (risk_amount / stop_distance) * current_rate

        stake = min(position_by_risk, proposed_stake)
        if min_stake is not None:
            stake = max(stake, min_stake)
        return min(stake, max_stake)
