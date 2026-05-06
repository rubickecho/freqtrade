# AGENTS.md

## Project Overview

This is a customized [freqtrade](https://github.com/freqtrade/freqtrade) repository, used as a personal trading strategy lab. The primary workflow is: **validate trading ideas by writing strategies, backtesting them, and iterating on results**. Do NOT modify freqtrade's core source code under `freqtrade/` unless explicitly asked.

## Task Scope

Tasks in this project focus on:

- Writing new trading strategies in `user_data/strategies/`
- Modifying or optimizing existing strategies
- Writing backtesting configurations
- Running backtests and analyzing results
- Hyperopt parameter tuning
- Downloading market data for backtesting

## Project Structure

```
freqtrade/                # Framework core - DO NOT MODIFY unless explicitly asked
user_data/
  strategies/             # Custom strategies go here
  data/                   # Downloaded OHLCV market data
  backtest_results/       # Backtest output results
  hyperopts/              # Custom hyperopt loss functions
  notebooks/              # Jupyter notebooks for analysis
config_examples/          # Example configuration files
tests/                    # Framework test suite
docs/                     # Freqtrade documentation
```

## Strategy Development Conventions

### File Location & Naming

- Strategies live in `user_data/strategies/<StrategyClassName>.py`
- File name must match the class name (e.g. `RsiMacdStrategy.py` contains class `RsiMacdStrategy`)
- Strategy class name is used as `--strategy` argument in CLI commands

### Mandatory Structure

Every strategy must inherit from `IStrategy` and implement three methods:

```python
from freqtrade.strategy import IStrategy
from pandas import DataFrame

class MyStrategy(IStrategy):
    INTERFACE_VERSION = 3

    # -- Core config --
    timeframe = "5m"
    minimal_roi = {"0": 0.04}
    stoploss = -0.10
    startup_candle_count: int = 200

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe
```

### Signal Columns (INTERFACE_VERSION = 3)

Use these column names for signals:

- `enter_long` / `exit_long` for long positions
- `enter_short` / `exit_short` for short positions
- `enter_tag` / `exit_tag` for signal tagging (max 64 chars)

Do NOT use deprecated `buy` / `sell` column names.

### Indicator Libraries

Standard imports for technical analysis:

```python
import talib.abstract as ta
from technical import qtpylib
import numpy as np
```

Commonly used indicators via `talib.abstract`:
- `ta.RSI(dataframe, timeperiod=14)`
- `ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)`
- `ta.BBANDS(dataframe, timeperiod=20, nbdevup=2, nbdevdn=2)`
- `ta.EMA(dataframe, timeperiod=21)`, `ta.SMA(dataframe, timeperiod=21)`
- `ta.ATR(dataframe, timeperiod=14)`
- `ta.STOCH(dataframe, ...)`, `ta.ADX(dataframe, timeperiod=14)`

### Coding Patterns

- **Vectorized operations only**: Use pandas vectorized ops, never `for` loops or `iloc[-1]` on dataframe rows.
- **Previous candle reference**: Use `dataframe.shift(1)` or `qtpylib.crossed_above()`.
- **Entry/exit assignment**: Use `dataframe.loc[conditions, "enter_long"] = 1` pattern.
- **Volume guard**: Always include `dataframe["volume"] > 0` as a guard condition.
- **Hyperopt parameters**: Use `IntParameter`, `DecimalParameter`, `RealParameter`, `BooleanParameter` for tunable values. Access via `.value`, e.g. `self.buy_rsi.value`.

### Hyperopt Parameters

```python
from freqtrade.strategy import IntParameter, DecimalParameter, BooleanParameter

class MyStrategy(IStrategy):
    buy_rsi = IntParameter(low=1, high=50, default=30, space="buy", optimize=True)
    sell_rsi = IntParameter(low=50, high=100, default=70, space="sell", optimize=True)
```

### Informative (Higher Timeframe) Data

Use the `@informative` decorator:

```python
from freqtrade.strategy import informative

@informative('1h')
def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
    return dataframe
```

### Custom Stoploss

```python
use_custom_stoploss = True

def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                    current_rate: float, current_profit: float, after_fill: bool,
                    **kwargs) -> float:
    return -0.05  # Return negative ratio
```

## Common CLI Commands

### Create a new strategy from template

```bash
freqtrade new-strategy --strategy <StrategyName>
```

### Download market data

```bash
freqtrade download-data --config config.json --pairs BTC/USDT ETH/USDT --timeframes 5m 1h --timerange 20230101-
```

### Run backtesting

```bash
freqtrade backtesting --config config.json --strategy <StrategyName> --timerange 20230101-20240101
```

### Compare multiple strategies

```bash
freqtrade backtesting --config config.json --strategy-list Strategy1 Strategy2 --timerange 20230101-20240101
```

### Run hyperopt (parameter optimization)

```bash
freqtrade hyperopt --config config.json --strategy <StrategyName> --hyperopt-loss SharpeHyperOptLoss --spaces buy sell --timerange 20230101-20240101
```

### List strategies

```bash
freqtrade list-strategies --strategy-path user_data/strategies/
```

## Quality Checks

Run these commands after modifying strategy code:

```bash
# Lint with ruff
ruff check user_data/strategies/

# Type check (if applicable)
mypy user_data/strategies/
```

## Key Rules

1. **Never modify `freqtrade/` core code** unless explicitly asked.
2. **Always use INTERFACE_VERSION = 3** for new strategies.
3. **Always use vectorized pandas operations** - no loops over dataframe rows.
4. **Always include volume guards** (`dataframe["volume"] > 0`) in signal conditions.
5. **Strategy file name must match class name**.
6. **Use hyperopt parameters** for any tunable values to enable optimization.
7. **Run lint check** after writing or modifying strategy code.
8. **Test strategies with backtesting** before considering them complete.
