# signal-orthogonality · 信号正交性审计器（元层工具）

## 它补的系统级 gap（不是缺某只票，是缺一类视角）
整个组合有 8+ 个信号工具，研究 note 反复把『N 重独立印证』当作真 alpha 的特征——
越多条不重叠证据合流 = 信号越强，这是 note 里 `holder_concentration`「四重独立印证工业富联派发」、
`southbound_flow`「四重印证康方被错杀」等判断的核心修辞。

**但这套逻辑只有在这些信号【输入正交】时才成立。** 若多条『独立印证』其实共享同一根
原始数据（如都从 price 序列派生），它们就是共线的，合流不增加信息量，只制造虚假信心——
**这是确认偏误在系统层的工程化复发**：换七个名字喊同一句话，不等于七个人独立同意。

我们有信号生成器（8+）、有 allocate 配置层、有 prediction-ledger 校准器，
却从无工具审计『我们引用的多重印证到底独立不独立』。本项目补这个洞。

## 首跑硬发现（2026-06-15）
- 全登记表 9 条信号里 **7 条是 price 派生**（tech_screener / reverse_dcf /
  valuation_percentile / alpha_check / correlation_check / holder_concentration / southbound_flow）。
- `alpha_check × correlation_check` Jaccard=1.00（纯 price，完全共线）；
  `valuation_percentile × tech_screener` Jaccard=1.00。全表 15 对高度共线。
- **工业富联「四重印证」实测**：其中可登记的 3 条（估值分位/已实现α/筹码派发）
  全共享 price → 名义 3 重，真正独立根输入贡献远少于 3。其中真正补充独立信息的是
  筹码的 `shares_holders` 维度 + 关税 beta（Polymarket）+ 薄利代工的 income_statement，
  而非『估值贵 + α负 + 价跌派发』这组高度 price-相关的表述。

## 用法
```
# 写 note 主张『N重独立印证』前,先核实这 N 条信号没落在 🔴 共线对里
python3 signal_orthogonality.py --signals valuation_percentile,alpha_check,holder_concentration
python3 signal_orthogonality.py --audit-all          # 全表两两重叠矩阵
python3 signal_orthogonality.py --quiet --signals ... # cron 友好:仅🔴 surface, exit 1
```
退出码：发现 🔴 共线 → 1；正交 → 0。

## 维护纪律
新增任何信号工具 → 在 `signal_registry.json` 登记其 `root_inputs`（消费的原始数据）。
root_inputs 是**人工声明**，非自动推断——这是工具的唯一假设，登记错则裁定错。

## 数据诚实
- Jaccard / 共线裁定是输入集合的确定性算术，非预测、非买卖指令。
- 本工具不判信号对不对、不取数、不下单，只判『这几条证据独不独立』。
- price 被特别标记：它是最易被重复计数的根输入，多条 price 派生信号互引 = 伪独立红旗。

## 边界 / 待扩展
- 当前是**静态输入依赖**审计（声明式）。更强版本可在持仓上实测各信号输出序列的
  两两相关系数（经验正交性），与声明式正交性交叉验证。本版先用低成本声明式堵住
  最大漏洞（把 price 派生信号当多重印证），实测版按需再建。
