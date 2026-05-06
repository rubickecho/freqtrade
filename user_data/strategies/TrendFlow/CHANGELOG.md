# TrendFlow 迭代日志

## v3 — 仅动态 ADX 止损（Hyperopt 优化版）
- **日期：** 2026-05-06
- **类型：** Hyperopt 参数优化（SharpeHyperOptLoss, 500 epochs）
- **最优参数：** ema_period=39, adx_threshold=17, atr_stop_mult=1.5
- **回测结果：** +48.76%, CAGR 52.23%, 最大回撤 38.79%, Profit Factor 1.14, Sharpe 0.91, Sortino 3.41
- **变更：** 降低 adx_threshold 增加交易频率，收窄止损至 1.5×ATR 减少亏损幅度
- **文件：** v3/TrendFlowV3.py + v3/config.json

## v3 — 仅动态 ADX 止损（默认参数）
- **日期：** 2026-05-06
- **类型：** 修复（回退 v2 错误的移动止损）
- **回测结果：** +41.54%, CAGR 44.42%, 最大回撤 35.09%, Profit Factor 1.12, Sharpe 0.73, Sortino 2.28
- **v2 教训：** trailing 在 2R 将 8 个 ROI 100% 大赢截断到只剩 1 个，肥尾是趋势策略唯一利润来源
- **文件：** v3/TrendFlowV3.py + v3/config.json

## v2 — 动态止损 + 移动止损（失败）
- **日期：** 2026-05-06
- **类型：** 优化
- **变更：** 新增 ADX 动态止损倍数 + 真正移动止损（浮盈 2R 后追踪 1×ATR）
- **回测结果：** -79.94%, CAGR -81.72%, Profit Factor 0.63
- **失败原因：** 移动止损截断了肥尾大赢家（ROI 100% 从 8 笔 → 1 笔），趋势策略无法幸存
- **文件：** v2/TrendFlowV2.py + v2/config.json

## v1 — 初版（基线）
- **日期：** 2026-05-06
- **类型：** 初始版本
- **策略：** 4h EMA(40) 趋势跟随 + 5 品种分散 + ADX>20+ATR>MA 震荡过滤
- **参数：** ema_period=40, adx_threshold=20, atr_stop_mult=2.0, leverage=3x
- **回测结果：** +28.38%, CAGR 30.26%, 最大回撤 41.23%, Profit Factor 1.08, Sharpe 0.49
- **已知问题：**
  - stop_loss 21 笔均亏 -12.19%，trailing_stop_loss 25 笔均亏 -15.63%
  - 多空不对称（long -31.13% vs short +59.51%）
- **文件：** v1/TrendFlowV1.py + v1/config.json
