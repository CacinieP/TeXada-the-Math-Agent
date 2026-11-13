# TeXada v0.4.8

发布日期 / Release date 2026-11-13（Asia/Shanghai）。

v0.4.8 是一个补丁版本：修掉计算范围门禁对"求导法则/公式/表"这类**待排版内容**的
误拒，并把范围拒绝从基线失败里区分出来。

[下载 Release](https://github.com/CacinieP/TeXada-the-Math-Agent/releases/tag/v0.4.8) · [完整 diff](https://github.com/CacinieP/TeXada-the-Math-Agent/compare/v0.4.7...v0.4.8) · [CHANGELOG](../CHANGELOG.md#048---2026-11-13) · [使用指南](../README.md)

## 本版变化

- `u 除以 v 的求导法则`、`泰勒公式的求导法则`、`基本积分公式表` 不再被当成
  "让我求导"而拒绝。实现方式是在动词扫描前剥离名词化搭配
  `求导/积分/极限 +（的）法则|公式|规则|表`，其余动词判定不变——
  `计算这个求导公式`、`推导泰勒公式的求导法则` 仍然被拒绝。
- 基线报告 `eval/run_real_baseline.py` 把 `ComputationOutsideScope` 单列为
  "产品边界拒绝"，既不进 Errors 也不算进分母，避免把"没跑"记成"跑错"。
- 复测 100 条 golden set（MiniCPM-V 4.7 1B）：结构通过 59/95（62.1%）、
  编译 92/100、渲染 98/100、轨迹 98/100、确定性修复 53/53，
  延迟 p50/p95 = 1.5s / 4.2s。分母 94→95 是 `062` 重新进入评测所致。

## 边界

- golden `010`（`把 x 平方减一分解成两个因式`）与 `073`（`微积分基本定理：…积分对
  x 求导`）仍被拒绝，属**有意**的产品边界，见 `eval/known-gaps.md` G-016：
  前者要的是分解结果，后者无法用正则与真实求导请求区分。
- 本版未改模型、提示词、打包、签名与公证流程；安装包验收口径同 v0.4.7。
