# AdaptiveConfluenceV3 — 策略设计文档

## 1. 策略定位

**一句话：** 在正确方向上（趋势过滤）、用正确方式（突破或回调）、在正确位置（动态 S/R）入场的多因子共振策略。

| 属性 | 值 |
|------|---|
| 策略类型 | 趋势跟随 + 回调入场，自适应双模式 |
| 主时间框架 | 5m |
| 辅助时间框架 | 1h（波动性/趋势）、4h（方向过滤） |
| 交易模式 | 期货双向（做多 + 做空） |
| 持仓周期 | 1-4 小时（中短期日内） |
| 适用品种 | 高流动性加密货币期货（BTC/USDT、ETH/USDT、HYPE/USDT 等） |

## 2. 设计哲学

v2 的核心问题不是理念，而是 **缺趋势过滤 + 出入场不匹配 + 静态参数不适配动态市场**。v3 的改进围绕三个原则：

1. **方向比信号重要** — 永远不在逆势方向开仓
2. **让出场服务于入场逻辑** — 突破单和回调单的退出策略完全不同
3. **用波动性校准一切** — 止损、止盈、仓位、时间窗口全部 ATR 化

## 3. 市场状态分类（三层）

### 3.1 Layer 1：趋势方向（4h）

使用 4h EMA 判断中期趋势方向。

```
uptrend:   EMA(21)_4h > EMA(55)_4h AND ADX(14)_4h > 20
downtrend: EMA(21)_4h < EMA(55)_4h AND ADX(14)_4h > 20
neutral:   ADX(14)_4h <= 20
```

**交易方向规则：**
- uptrend → 仅做多（模式A做多 + 模式B做多回调）
- downtrend → 仅做空（模式A做空 + 模式B做空回调）
- neutral → 双向均可，但仓位缩小 50%

### 3.2 Layer 2：波动性状态（1h ATR 百分位）

用 1h ATR(14) 在过去 100 根 K 线中的百分位排名，替代 v2 的固定倍率。

```
high_vol:    ATR_percentile > 80
normal_vol:  20 <= ATR_percentile <= 80
low_vol:     ATR_percentile < 20
expanding:   ATR > ATR_MA(20) AND ATR_MA 在上升（slope > 0）
```

**作用：** 不同波动性状态下，止损距离、仓位大小、时间窗口不同（详见第 7 节）。

### 3.3 Layer 3：动量状态（5m）

```
momentum_up:   RSI(14) > 50 AND RSI_slope(5) > 0
momentum_down: RSI(14) < 50 AND RSI_slope(5) < 0
neutral:       其他
```

RSI_slope = `(RSI - RSI.shift(5)) / 5`，衡量 RSI 变化速率。

**不作为独立过滤器使用**，仅在模式A中作为辅助确认。

## 4. 动态 S/R 检测（替代经典枢轴点）

经典枢轴点是为有固定交易时段设计的，不适用于 24/7 加密市场。v3 改用 **1h 摆动高/低点** 作为动态 S/R。

### 4.1 摆动点识别（1h 时间框架）

```
swing_high:  high[i] > high[i-1] AND high[i] > high[i-2]
              AND high[i] > high[i+1] AND high[i] > high[i+2]
              (即：左右各 2 根 K 线的局部最高点)

swing_low:   low[i] < low[i-1] AND low[i] < low[i-2]
              AND low[i] < low[i+1] AND low[i] < low[i+2]
```

### 4.2 S/R 有效性

只保留尚未被突破的摆动点：
- 阻力位 = 最近一个 swing_high，且其后的价格未收盘突破该高点
- 支撑位 = 最近一个 swing_low，且其后的价格未收盘跌破该低点

### 4.3 接近度阈值

不用固定百分比，改用 ATR 的比例：
```
proximity = 0.5 * ATR_1h
```
即：价格在 S/R 位 ±0.5×ATR 范围内，视为「在 S/R 附近」。

## 5. 入场逻辑（双模式）

### 5.1 模式A：动量突破（Momentum Breakout）

**核心逻辑：** 在趋势方向上，价格突破近期 S/R 位，伴随成交量确认。

**做多条件（做空镜像反转）：**

| # | 条件 | 说明 |
|---|------|------|
| 1 | 趋势 = uptrend 或 neutral | 方向过滤 |
| 2 | 收盘价 > 最近有效阻力位 | 突破确认 |
| 3 | 前一根收盘价 <= 该阻力位 | 同一根 K 线发生突破（非跳空） |
| 4 | K 线实体比 > 0.5 | `abs(close-open) / (high-low) > 0.5`，排除十字星假突破 |
| 5 | 成交量 > 1.2 × volume_ma(20) | 有量配合 |
| 6 | RSI(14) > 45 AND RSI(14) < 85 | 不是超卖（弱势）也不是极度超买（追高） |
| 7 | volume > 0 | 成交量守卫（freqtrade 强制要求） |

**去掉 v2 的成交量上限（4x）** — 大成交量 + 大实体 = 有效突破，不应被过滤。

**enter_tag:** `momentum_breakout_long` / `momentum_breakout_short`

### 5.2 模式B：趋势回调（Trend Pullback）

**核心逻辑：** 在趋势方向上，价格回调至动态支撑/阻力位，出现拒绝信号。

> v2 叫「衰竭反转」，但逻辑上是「趋势回调」— 反转指的是方向反转，而真正有效的信号是在大趋势方向上的回调入场。

**做多条件（做空镜像反转）：**

| # | 条件 | 说明 |
|---|------|------|
| 1 | 趋势 = uptrend | **必须明确趋势方向**（neutral 不做回调） |
| 2 | 价格在动态支撑位附近 | `close - swing_low <= 0.5 * ATR_1h` |
| 3 | 拒绝 K 线形态（满足任一） | a) 下影线 > 1.5×实体（锤子线）<br>b) 看涨吞没（当前阳线实体包住前一根阴线实体）<br>c) 当前为阳线且收在 K 线上半部分 |
| 4 | RSI 底背离（5m 级别） | 价格创新低（`low < low.shift(1)` 且 `low.shift(1) < low.shift(2)`），但 RSI 未创新低（`RSI > RSI.shift(1)`）<br>或者 RSI(14) < 40（宽松替代，无背离时） |
| 5 | volume > 0 | 成交量守卫 |

**为什么 RSI 底背离 + RSI < 40 是 OR 关系？** 因为在 5m 级别上，完美的背离并不总是出现。当价格回到支撑位 + 有拒绝 K 线时，RSI 只需要不在极端区域就足够了。回测时可以通过 Hyperopt 验证是否需要严格要求背离。

**enter_tag:** `pullback_long` / `pullback_short`

## 6. 出场逻辑（入场模式感知）

v2 的核心问题：出场逻辑不区分入场模式。v3 为两种模式设计独立的出场策略。

### 6.1 模式A 出场（动量突破）

突破交易的特点是「趋势可能延续很远」，需要给足空间。

| 退出方式 | 条件 | 说明 |
|----------|------|------|
| **初始止损** | 入场价 - 1.5 × ATR(14)_5m | ATR 自适应，非固定百分比 |
| **移动止损** | 浮盈超过 1R 后，止损移至成本价（breakeven） | 锁定无风险 |
| **趋势止损** | 浮盈超过 2R 后，追踪止损 = 最高价 - 1.0 × ATR | 让利润奔跑 |
| **动量衰竭** | MACD histogram 连续 3 根递减 + RSI 从 >70 回落至 <65 | 动能衰退但趋势未死 |
| **时间止损** | 持仓超过 30 根 K 线（150 分钟），若浮盈 > 0 则平仓获利；若浮亏则平仓止损 | 突破应在合理时间内产生利润 |

> R = 初始止损距离 = 1.5 × ATR

### 6.2 模式B 出场（趋势回调）

回调交易的特点是「反弹幅度可预期」，止盈目标明确。

| 退出方式 | 条件 | 说明 |
|----------|------|------|
| **初始止损** | 入场 K 线最低价 - 0.3 × ATR(14)_5m | 紧止损，回调失败应快速退出 |
| **目标止盈** | 下一个阻力位（最近有效 swing_high） | 反弹到下一个 S/R 即获利了结 |
| **移动止损** | 浮盈超过 1R 后，止损移至成本价 | |
| **时间止损** | 持仓超过 20 根 K 线（100 分钟），同上逻辑 | 回调反弹应比突破更快产生利润 |

### 6.3 通用退出

以下退出条件两种模式共享：

| 退出方式 | 条件 | 说明 |
|----------|------|------|
| **趋势反转** | 4h 趋势方向翻转（EMA 交叉） | 趋势不在了，任何持仓都应退出 |
| **ROI 上限** | 10%（`minimal_roi`） | 防止极端情况 |

### 6.4 实现方式

- **初始止损 / 移动止损 / 追踪止损** → `custom_stoploss()` + `stoploss_from_open()` / `stoploss_from_absolute()`
- **目标止盈（模式B）** → `custom_exit()` 中读取入场时的阻力位目标价
- **动量衰竭 / 时间止损 / 趋势反转** → `custom_exit()`
- **入场模式标记** → 使用 `trade.enter_tag` 区分 `momentum_breakout_*` 和 `pullback_*`

## 7. 风险管理

### 7.1 仓位大小（基于波动性）

```
base_risk_per_trade = 1.0%  # 每笔交易风险占总资金比例
stop_distance = entry_stop_multiplier * ATR_5m
position_size = (account_balance * base_risk_per_trade) / stop_distance
```

通过 `custom_stake_amount()` 实现。波动性越大，止损越宽，仓位自动缩小。

### 7.2 波动性状态对参数的调节

| 参数 | low_vol | normal_vol | high_vol |
|------|---------|------------|----------|
| 入场信号 | 仅模式A（波动率扩张时） | 模式A + B | 仅模式A（收严实体比 > 0.7） |
| 仓位系数 | 0.7 | 1.0 | 0.7 |
| 时间止损（模式A） | 40 根 | 30 根 | 25 根 |
| 时间止损（模式B） | 25 根 | 20 根 | 15 根 |

低波动下仍然交易，但只做模式A（突破），且要求波动率正在扩张（`expanding=True`），这是波动率压缩后的爆发，往往是最佳入场时机。

### 7.3 杠杆

```
leverage = min(3.0, max_leverage)
```

在 `leverage()` 方法中设置。低波动和 neutral 趋势时降至 2x。

## 8. OI（持仓量）集成

OI 数据仅用于实盘/模拟盘，回测时完全跳过。

| 场景 | OI 信号 | 作用 |
|------|---------|------|
| 模式A突破 | OI 增长 > MA + 1σ | 确认新资金入场（可选加分） |
| 模式B回调 | OI 大幅下降 + 价格在支撑位 | 确认投降/清算完毕（可选加分） |

**关键原则：** OI 是加分项，不是必要条件。回测不依赖 OI。

## 9. Hyperopt 参数空间

所有关键数值均可优化，按 `space` 分组：

### buy space（入场参数）
| 参数 | 类型 | 范围 | 默认值 |
|------|------|------|--------|
| `ema_fast` | IntParameter | 15-30 | 21 |
| `ema_slow` | IntParameter | 40-70 | 55 |
| `trend_adx_threshold` | IntParameter | 15-30 | 20 |
| `rsi_min_breakout` | IntParameter | 35-55 | 45 |
| `rsi_max_breakout` | IntParameter | 75-90 | 85 |
| `volume_min_mult` | DecimalParameter | 0.8-2.0 | 1.2 |
| `body_ratio_min` | DecimalParameter | 0.3-0.7 | 0.5 |
| `pullback_rsi_max` | IntParameter | 30-50 | 40 |
| `atr_stop_mult_breakout` | DecimalParameter | 1.0-2.5 | 1.5 |
| `atr_stop_mult_pullback` | DecimalParameter | 0.3-1.0 | 0.5 |

### sell space（出场参数）
| 参数 | 类型 | 范围 | 默认值 |
|------|------|------|--------|
| `momentum_exit_rsi` | IntParameter | 55-75 | 65 |
| `momentum_exit_rsi_peak` | IntParameter | 65-85 | 70 |
| `macd_decline_bars` | IntParameter | 2-5 | 3 |
| `time_stop_breakout` | IntParameter | 20-45 | 30 |
| `time_stop_pullback` | IntParameter | 12-30 | 20 |
| `breakeven_at_r` | DecimalParameter | 0.8-1.5 | 1.0 |
| `trail_at_r` | DecimalParameter | 1.5-3.0 | 2.0 |
| `trail_atr_mult` | DecimalParameter | 0.5-1.5 | 1.0 |

## 10. 实现架构

```
AdaptiveConfluenceV3/
├── design.md                          # 本文档
├── AdaptiveConfluenceV3.py            # 策略主文件
└── config_adaptive_confluence_v3.json # 回测配置
```

### 10.1 策略文件结构

```python
class AdaptiveConfluenceV3(IStrategy):
    # --- 配置 ---
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "5m"
    startup_candle_count = 500  # 需要足够数据生成 1h/4h 指标

    # --- Hyperopt 参数 ---
    # (见第 9 节)

    # --- informative 数据 ---
    informative_pairs() → [(pair, "1h"), (pair, "4h")]

    # --- 指标计算 ---
    populate_indicators_1h()  # @informative("1h"): ATR, EMA, swing points
    populate_indicators_4h()  # @informative("4h"): EMA, ADX, 趋势方向

    populate_indicators()     # 5m 指标: RSI, MACD, volume_ma, ATR, body_ratio

    # --- 入场 ---
    populate_entry_trend()    # 向量化，无 for 循环
    populate_exit_trend()     # 空壳（退出走 custom_exit + custom_stoploss）

    # --- 出场 ---
    custom_stoploss()         # ATR 自适应止损 + breakeven + trailing
    custom_exit()             # 动量衰竭 + 时间止损 + 趋势反转

    # --- 风险管理 ---
    leverage()
    custom_stake_amount()
```

### 10.2 关键实现要点

1. **使用 `@informative` 装饰器** 获取 1h 和 4h 数据，框架自动处理合并和前向填充
2. **摆动点识别在 `@informative("1h")` 中完成**，结果列如 `swing_high_1h`、`swing_low_1h` 自动映射到 5m
3. **`populate_entry_trend` 纯向量化**：所有条件表达为布尔 Series，最终 `dataframe.loc[conditions, "enter_long"] = 1`
4. **`custom_stoploss` 根据 `trade.enter_tag` 区分模式**，使用不同的止损策略
5. **`custom_exit` 读取 5m 最新 K 线的指标值**，检查动量衰竭、时间止损等条件

## 11. 实施路线

### Phase 1：最小可回测版本
- 三层市场状态分类
- 模式A（动量突破）完整实现
- 模式B（趋势回调）完整实现
- ATR 自适应止损 + breakeven + trailing
- 时间止损
- 回测验证基本信号质量

### Phase 2：精细化
- 动量衰竭退出（MACD histogram 递减 + RSI 回落）
- 趋势反转退出（4h EMA 交叉）
- Hyperopt 参数优化（至少 500 epochs）

### Phase 3：实盘增强
- OI 集成（可选加分项）
- 品种参数化（不同币种不同参数集）
- Telegram 告警集成

## 12. 回测验证清单

- [ ] 至少 3 个月数据，覆盖趋势市和震荡市
- [ ] 总交易笔数 > 100（信号不过于稀疏）
- [ ] 胜率 > 40%（趋势策略正常范围）
- [ ] 盈亏比 > 1.5（趋势策略的核心）
- [ ] 最大回撤 < 15%
- [ ] Sharpe Ratio > 1.0
- [ ] 多头和空头分别验证（不对称表现需要调查原因）
- [ ] 不同币种分别回测
