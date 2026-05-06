# AGENTS.md

## P0 规则（最高优先级）

1. **使用中文** — 所有回复、注释说明、commit message 描述均使用中文（代码本身保持英文）。
2. **使用东八区时区** — 所有涉及时间的操作（回测时间范围、数据分析、日志解读等）默认使用 UTC+8（Asia/Shanghai）时区。
3. **绝对禁止修改 `freqtrade/` 源码** — 本仓库 fork 自上游 freqtrade，为保持与上游同步（sync）的能力，`freqtrade/` 目录下的所有文件仅作为参考阅读，**任何情况下都不允许修改**。
4. **每个策略独立文件夹** — 每个策略在 `user_data/strategies/` 下创建独立子目录，策略脚本与设计文档内聚管理。
5. **使用 `uv` 运行所有命令** — 所有 freqtrade CLI 命令统一通过 `uv run` 执行（如 `uv run freqtrade backtesting ...`），不使用裸 `freqtrade` 命令。

## 项目概述

这是一个基于 [freqtrade](https://github.com/freqtrade/freqtrade) 的个人定制仓库，用作**交易策略实验场**。核心工作流：**编写策略 → 回测验证 → 迭代优化**，用于验证交易想法。`freqtrade/` 仅作为参考阅读，**禁止修改**。

## 任务范围

- 在 `user_data/strategies/` 中编写新策略
- 修改或优化已有策略
- 编写回测配置文件
- 运行回测并分析结果
- Hyperopt 参数调优
- 下载市场数据用于回测

## 项目结构

```
freqtrade/                # 框架核心 — 仅参考阅读，绝对禁止修改
user_data/
  strategies/             # 自定义策略存放目录（每个策略一个子文件夹）
    MyStrategy/           # 示例：策略独立目录
      CHANGELOG.md        # 迭代日志（必需）
      v1/                 # 版本子目录
        MyStrategyV1.py   # 策略脚本（类名含版本号）
        config.json       # 回测配置
        design.md         # 策略设计文档
      v2/                 # 后续迭代版本
        MyStrategyV2.py
        config.json
  data/                   # 已下载的 OHLCV 市场数据
  backtest_results/       # 回测输出结果
  hyperopts/              # 自定义 hyperopt 损失函数
  notebooks/              # Jupyter 分析笔记本
config_examples/          # 示例配置文件
tests/                    # 框架测试套件
docs/                     # Freqtrade 文档
```

## 策略版本迭代规范

### 目录结构

每个策略目录采用 `v1/` `v2/` ... 子目录管理版本，根目录维护 `CHANGELOG.md`。

### 命名规则

| 项目 | 规则 | 示例 |
|------|------|------|
| 版本目录名 | `v` + 数字，从 1 开始 | `v1/`, `v2/` |
| 策略类名 | 策略名 + `V` + 数字 | `TrendFlowV1`, `TrendFlowV2` |
| 策略文件名 | 与类名一致 | `TrendFlowV1.py` |
| 配置文件 | 统一命名为 `config.json`（在版本目录内） | `v1/config.json` |

### CHANGELOG.md 格式

每个策略目录的 `CHANGELOG.md` 按版本倒序记录：

```markdown
# 策略名 迭代日志

## vN — 标题（状态）
- **日期：** YYYY-MM-DD
- **类型：** 初始版本 / 优化 / 重构 / 修复
- **变更：** 简要说明
- **回测结果：** 关键指标（收益 / CAGR / 回撤 / Profit Factor / Sharpe）
- **已知问题：** 如有
- **文件：** vN/StrategyFile.py + vN/config.json
```

### 迭代规则

1. **每次优化前创建新版本目录**，禁止原地修改已有版本
2. **先写 CHANGELOG 记录变更意图**，再实现代码
3. **回测完成后更新 CHANGELOG 中的回测结果**
4. **删除旧版本根目录下的遗留文件**（迁移完成后）
5. **每个版本自包含**：策略文件 + 配置文件均在版本目录内

## 策略开发规范

### 文件位置与命名

- 每个策略在 `user_data/strategies/` 下创建**独立子目录**，策略脚本与设计文档内聚管理
- 目录结构示例：`user_data/strategies/RsiMacdStrategy/RsiMacdStrategy.py` + `design.md`
- 文件名必须与类名一致（例如 `RsiMacdStrategy.py` 包含类 `RsiMacdStrategy`）
- 策略类名即 CLI `--strategy` 参数的值，运行时通过 `--strategy-path` 指定策略目录

### 必须实现的结构

每个策略必须继承 `IStrategy` 并实现以下三个方法：

```python
from freqtrade.strategy import IStrategy
from pandas import DataFrame

class MyStrategy(IStrategy):
    INTERFACE_VERSION = 3

    # -- 核心配置 --
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

### 信号列名（INTERFACE_VERSION = 3）

使用以下列名生成信号：

- `enter_long` / `exit_long` — 做多入场 / 退出
- `enter_short` / `exit_short` — 做空入场 / 退出
- `enter_tag` / `exit_tag` — 信号标签（最长 64 字符）

**禁止**使用已废弃的 `buy` / `sell` 列名。

### 技术指标库

标准导入：

```python
import talib.abstract as ta
from technical import qtpylib
import numpy as np
```

常用指标（通过 `talib.abstract`）：
- `ta.RSI(dataframe, timeperiod=14)`
- `ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)`
- `ta.BBANDS(dataframe, timeperiod=20, nbdevup=2, nbdevdn=2)`
- `ta.EMA(dataframe, timeperiod=21)` / `ta.SMA(dataframe, timeperiod=21)`
- `ta.ATR(dataframe, timeperiod=14)`
- `ta.STOCH(dataframe, ...)` / `ta.ADX(dataframe, timeperiod=14)`

### 编码模式

- **仅使用向量化操作**：使用 pandas 向量化运算，禁止 `for` 循环或 `iloc[-1]` 遍历行。
- **引用前一根 K 线**：使用 `dataframe.shift(1)` 或 `qtpylib.crossed_above()`。
- **入场/出场赋值**：使用 `dataframe.loc[conditions, "enter_long"] = 1` 模式。
- **成交量守卫**：信号条件中必须包含 `dataframe["volume"] > 0`。
- **Hyperopt 参数**：使用 `IntParameter`、`DecimalParameter`、`RealParameter`、`BooleanParameter` 定义可调参数，通过 `.value` 访问，如 `self.buy_rsi.value`。

### Hyperopt 参数定义

```python
from freqtrade.strategy import IntParameter, DecimalParameter, BooleanParameter

class MyStrategy(IStrategy):
    buy_rsi = IntParameter(low=1, high=50, default=30, space="buy", optimize=True)
    sell_rsi = IntParameter(low=50, high=100, default=70, space="sell", optimize=True)
```

### 高级别时间框架数据（Informative）

使用 `@informative` 装饰器：

```python
from freqtrade.strategy import informative

@informative('1h')
def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
    return dataframe
```

### 自定义止损

```python
use_custom_stoploss = True

def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                    current_rate: float, current_profit: float, after_fill: bool,
                    **kwargs) -> float:
    return -0.05
```

## 常用 CLI 命令

### 从模板创建新策略

```bash
uv run freqtrade new-strategy --strategy <策略名>
```

### 下载市场数据

```bash
uv run freqtrade download-data --config config.json --pairs BTC/USDT ETH/USDT --timeframes 5m 1h --timerange 20230101-
```

### 运行回测

```bash
uv run freqtrade backtesting --config config.json --strategy <策略名> --timerange 20230101-20240101
```

### 对比多个策略

```bash
uv run freqtrade backtesting --config config.json --strategy-list Strategy1 Strategy2 --timerange 20230101-20240101
```

### 运行 Hyperopt（参数优化）

```bash
uv run freqtrade hyperopt --config config.json --strategy <策略名> --hyperopt-loss SharpeHyperOptLoss --spaces buy sell --timerange 20230101-20240101
```

### 列出所有策略

```bash
uv run freqtrade list-strategies --strategy-path user_data/strategies/
```

## 质量检查

修改策略代码后运行以下命令：

```bash
# Ruff 代码检查
ruff check user_data/strategies/

# 类型检查（如适用）
mypy user_data/strategies/
```

## 回测规范

**每次回测必须附带策略参数说明**，包含以下信息（从回测日志和配置中提取）：

| 类别 | 必需参数 |
|------|----------|
| 基础 | 交易所, Trading Mode, Timeframe（含辅助框架） |
| 资金 | 初始本金, stake_amount, max_open_trades, 杠杆 |
| 风控 | stoploss (硬止损), minimal_roi (止盈) |
| 策略（如适用） | 自定义止损/止盈参数, 入场门槛参数 |
| 数据 | 回测时间范围, 品种 |

## 关键规则

1. **禁止修改 `freqtrade/` 核心代码**，除非明确要求。
2. **新策略一律使用 INTERFACE_VERSION = 3**。
3. **仅使用 pandas 向量化操作** — 禁止遍历 dataframe 行。
4. **信号条件必须包含成交量守卫**（`dataframe["volume"] > 0`）。
5. **策略文件名必须与类名一致**。
6. **可调参数使用 Hyperopt 参数类型**，以便后续优化。
7. **编写或修改策略后必须运行 lint 检查**。
8. **策略完成后必须通过回测验证**。
9. **回测结果必须附带策略参数说明**（见上方「回测规范」章节）。
