## 今日知识点：Pre-LN vs Post-LN（归一化放前面还是后面）——决定深层 Transformer 能不能训得动的一个位置选择

### 所属类目
类目 13：Transformer 架构

### 问题入口
你已经知道 Transformer 的每个子层（注意力、FFN）外面都套着两样东西：**残差连接**（把输入直接加到输出上）和 **LayerNorm**（层归一化，把一层的激活值拉回稳定分布）。

但有一个看似鸡毛蒜皮、实则决定生死的问题：**LayerNorm 到底该放在哪里？**

- 是放在子层**之后**、加完残差再归一化？（这叫 Post-LN，原始 Transformer 论文的做法）
- 还是放在子层**之前**、先归一化再进子层？（这叫 Pre-LN，今天几乎所有大模型的做法）

这两种摆法只差一个位置，公式几乎一模一样。可现实是：**原始 Post-LN 的 Transformer 想训练到几十上百层，不加特殊技巧（warmup）根本训不起来，loss 直接飞掉；而换成 Pre-LN，同样的深度稳稳收敛。** 为什么一个归一化的位置会有这么大的差别？这就是今天要讲清楚的事。

### 朴素想法
一个自然的想法是："位置无所谓吧？反正 LayerNorm 就是把数据标准化一下，早归一化、晚归一化，最后都归一化了，结果应该差不多。"

按这个思路，你会觉得 Post-LN（原论文写法）看起来甚至更"正统"：先让子层充分计算，加上残差，最后统一收拾一遍，输出一个干净的归一化结果给下一层。逻辑上很顺。

### 卡住的地方
朴素想法忽略了一件事：**LayerNorm 不只是"收拾输出"，它还会挡在梯度回传的路上。**

回忆残差连接的本质：它给梯度开了一条"高速公路"，让梯度可以**不经过任何变换、原封不动地**从深层流回浅层，从而缓解梯度消失。这条高速公路是残差之所以能训练超深网络的核心。

现在看 Post-LN 干了什么。它的结构是：

$$
\mathbf{x}_{l+1} = \mathrm{LayerNorm}(\mathbf{x}_l + \mathrm{Sublayer}(\mathbf{x}_l))
$$

注意：**LayerNorm 套在了残差加法的外面。** 这意味着梯度想从 $\mathbf{x}_{l+1}$ 回到 $\mathbf{x}_l$，**必须先穿过一层 LayerNorm**。那条本该畅通无阻的残差高速公路，被 LayerNorm 收了过路费——它的雅可比矩阵会缩放梯度。一层还好，可当你堆 24 层、48 层、96 层，每一层都乘一个不是 1 的因子，梯度就会指数级地被放大或缩小。

后果就是：Post-LN 深层网络在训练**初期**梯度极不稳定，尤其靠近输出的层梯度巨大，逼得你必须用 learning rate warmup（一开始用极小的学习率慢慢热身）小心翼翼地伺候，否则一步就崩。

### 1. 概念

**Post-LN（Post Layer Normalization，后归一化）**：LayerNorm 放在残差相加**之后**。这是 2017 年原始 Transformer 论文《Attention Is All You Need》的写法。

$$
\mathbf{x}_{l+1} = \mathrm{LayerNorm}\big(\mathbf{x}_l + \mathrm{Sublayer}(\mathbf{x}_l)\big)
$$

**Pre-LN（Pre Layer Normalization，前归一化）**：LayerNorm 放在子层**之前**，残差直接跨过整个"归一化 + 子层"的组合。

$$
\mathbf{x}_{l+1} = \mathbf{x}_l + \mathrm{Sublayer}\big(\mathrm{LayerNorm}(\mathbf{x}_l)\big)
$$

符号说明：$\mathbf{x}_l$ 是第 $l$ 层的输入向量；$\mathrm{Sublayer}(\cdot)$ 是注意力或 FFN 子层；$\mathrm{LayerNorm}(\cdot)$ 是层归一化。两个式子的唯一区别，就是 LayerNorm 括住了谁。

**关键差异一句话**：在 Pre-LN 里，那个 $\mathbf{x}_l +$ 是**裸露在最外面**的——残差是一条完全没有被任何归一化污染的干净通路，梯度可以原样流回去；而在 Post-LN 里，$\mathbf{x}_l +$ 被 LayerNorm 包在里面，梯度回传必经归一化这道关卡。

通俗理解：想象一栋高楼的电梯（残差高速公路）。Pre-LN 是"电梯井从顶层直通地下室，中间不设关卡，每层的办公室（子层）挂在电梯井旁边"；Post-LN 是"每一层电梯门口都装了一道安检（LayerNorm），你上上下下每层都要过一次安检"。楼层少时安检没啥影响；楼层一多，光排队安检就把人堵死了。但类比到此为止，回到机制：安检=LayerNorm 的雅可比缩放，堵死=梯度的指数级失稳。

### 2. 推导与证明

我们从梯度回传的角度看清两者的差别。核心是**残差路径上梯度的传播因子**。

**关键步骤：**

1. **Pre-LN 的梯度通路。** 对 $\mathbf{x}_{l+1} = \mathbf{x}_l + \mathrm{Sublayer}(\mathrm{LayerNorm}(\mathbf{x}_l))$ 求对 $\mathbf{x}_l$ 的偏导：

$$
\frac{\partial \mathbf{x}_{l+1}}{\partial \mathbf{x}_l} = \mathbf{I} + \frac{\partial\, \mathrm{Sublayer}(\mathrm{LayerNorm}(\mathbf{x}_l))}{\partial \mathbf{x}_l}
$$

这里 $\mathbf{I}$ 是单位矩阵。**为什么重要**：那个 $\mathbf{I}$ 就是残差高速公路——它保证不管子层那一项算出什么，梯度里永远有一个"原样通过"的成分。把 $L$ 层连乘，主干上始终有个 $\mathbf{I}$ 兜底，梯度不会因深度而指数消失。

2. **Post-LN 的梯度通路。** 对 $\mathbf{x}_{l+1} = \mathrm{LayerNorm}(\mathbf{x}_l + \mathrm{Sublayer}(\mathbf{x}_l))$ 求导，多出一个 LayerNorm 的雅可比 $\mathbf{J}_{LN}$ 挡在最外面：

$$
\frac{\partial \mathbf{x}_{l+1}}{\partial \mathbf{x}_l} = \mathbf{J}_{LN}\cdot\Big(\mathbf{I} + \frac{\partial\, \mathrm{Sublayer}(\mathbf{x}_l)}{\partial \mathbf{x}_l}\Big)
$$

**为什么重要**：现在残差的 $\mathbf{I}$ 不再裸露，它被 $\mathbf{J}_{LN}$ 左乘了。$L$ 层连乘就变成 $\prod_{l} \mathbf{J}_{LN}^{(l)}\cdot(\cdots)$，一堆雅可比连乘。$\mathbf{J}_{LN}$ 的范数一般不等于 1，连乘 $L$ 次就是它的 $L$ 次方——这正是指数放大/缩小的来源。

3. **理论结论（Xiong et al. 2020）。** 论文用数学证明：Post-LN 在初始化时，靠近输出层的梯度期望量级正比于 $\sqrt{d\ln d}$ 并随深度累积，导致大梯度；而 **Pre-LN 靠近输出层的梯度量级与深度 $L$ 无关**（大致按 $1/\sqrt{L}$ 均匀分摊到各层）。**为什么要证这个**：它把"经验上 Pre-LN 好训"这件事，落到了"梯度量级不随深度爆炸"这个可计算的判据上——这就是为什么 Pre-LN 可以**去掉 warmup** 也能稳定训练，而 Post-LN 离开 warmup 就崩。

### 3. 来源与历史动机
- 论文：《On Layer Normalization in the Transformer Architecture》
- 作者：Ruibin Xiong, Yunchang Yang, Di He, Kai Zheng, Shuxin Zheng, 等（微软亚洲研究院等）
- 时间：2020 年（ICML 2020）
- 链接：https://arxiv.org/abs/2002.04745

历史背景：2017 年原始 Transformer 用的是 Post-LN，能 work，但训练非常"娇气"——必须配 learning rate warmup，超参数敏感，越深越难训。很长一段时间大家把这归为"炼丹玄学"。2020 年这篇论文第一次从梯度理论上讲清了根因：**问题不在 LayerNorm 本身，而在它相对残差的位置。** 从此 Pre-LN 成为主流，GPT-2/GPT-3、后来的绝大多数大模型都采用 Pre-LN（或其变体），因为要堆到几十上百层，稳定性压倒一切。

### 4. 核心用途

用途一：**训练超深 Transformer。** 现代大模型动辄几十层、上百层。Pre-LN 让梯度量级不随深度爆炸，是"能不能把网络堆深还训得动"的前提。GPT 系列、LLaMA 系列几乎清一色 Pre-LN。

用途二：**省掉或简化 warmup、放宽超参。** Post-LN 严重依赖精心设计的 warmup 计划表；Pre-LN 理论上可去掉 warmup，对学习率也更鲁棒，大幅降低调参成本——在动辄几百万美元一次的大模型训练里，这种稳定性就是真金白银。

用途三：**作为架构改进的基座。** 后续很多稳定性工作（如 DeepNorm 试图让 Post-LN 也能训极深、各种 sub-LN 变体）都以 Pre-LN/Post-LN 之争为出发点。理解这个位置问题，是读懂现代 Transformer 稳定性设计的钥匙。

### 5. 反直觉点与常见误区

反直觉点：**Post-LN 训练更难，但它训好之后的最终效果往往还略微更强。** Pre-LN 的胜利是"稳定性"的胜利，不是"表达能力"的胜利。因为 Pre-LN 里残差通路完全裸露，深层的输出方差会不断累加、越堆越大，等效于"最深的那些层贡献被稀释"，模型有点"变浅"的味道——所以在能训得动的前提下，调好的 Post-LN 有时精度更高。这也是为什么至今仍有人研究怎么把 Post-LN 训稳（如 DeepNorm）。选 Pre-LN，是在"训得动"和"训到极致"之间做的工程权衡。

常见误区：
- 误区一：**"LayerNorm 放哪都一样，反正都归一化了。"** 错。位置决定了它是否挡在残差梯度通路上，这直接改变梯度随深度的传播行为，是稳定性的分水岭。
- 误区二：**"Pre-LN 就是无脑更好，Post-LN 是过时的错误设计。"** 不对。Post-LN 收敛后常有更好的最终性能；两者是稳定性 vs 上限的权衡，不是对错。而且原始 Transformer 用 Post-LN 训翻译任务是完全成功的，只是层数不多。
- 误区三：**"Pre-LN 不需要最后再归一化。"** 恰恰相反，Pre-LN 因为残差不断累加导致最后一层输出方差很大，通常需要在整个堆栈的**最末尾额外加一个 final LayerNorm** 才能得到干净的输出——这是 Pre-LN 的标配收尾。

### 6. 小实验
不用训练，只做一个"心算 + 画图"的思想实验，感受梯度连乘。

假设每层的 LayerNorm 雅可比等效缩放因子约为 $c$（Post-LN 里它挡在残差外面）。梯度从第 $L$ 层回传到第 1 层，Post-LN 主干大致乘了 $c^L$：

- 取 $c = 1.1$，$L = 48$ 层：$1.1^{48} \approx 114$。梯度被放大约一百倍——爆炸。
- 取 $c = 0.9$，$L = 48$ 层：$0.9^{48} \approx 0.0064$。梯度缩到千分之几——消失。
- 而 Pre-LN 主干上永远有裸露的 $\mathbf{I}$（因子为 $1$），$1^{48} = 1$，无论多深都不爆不消。

动手版（可选，极短 Python）：

```python
for c in [0.9, 1.0, 1.1]:
    print(c, "->", round(c**48, 4))
# 0.9 -> 0.0064   (梯度消失)
# 1.0 -> 1.0      (Pre-LN 的理想主干)
# 1.1 -> 114.48   (梯度爆炸)
```

结论一目了然：把缩放因子哪怕偏离 1 一点点，连乘几十层就是天壤之别；而残差裸露带来的因子 1，是唯一能"稳住"的选择。这就是 Pre-LN 把 LayerNorm 挪进残差内部的全部动机。

### 7. 批判性思考

局限性：Pre-LN 的稳定是靠"让残差彻底裸露"换来的，代价是深层输出方差累积、深层有效贡献被稀释，最终性能上限可能不如调好的 Post-LN。而且 Pre-LN 也不是万能——超大规模下仍会遇到 loss spike，工业界又叠加了 QK-Norm、sandwich-LN、logit soft-cap 等一堆补丁。所以"Pre-LN 解决了稳定性"是相对的，不是终局。

深度问题：如果 Pre-LN 的核心优势是"残差裸露、梯度有个不随深度衰减的主干"，那么把归一化换成更省的 **RMSNorm**（前面学过）会不会进一步改善？为什么现代大模型几乎都是 **Pre-RMSNorm** 的组合？再往深一层想：既然位置和归一化种类都能调，能不能设计一种初始化（比如让子层初始输出接近 0）来让 Post-LN 也具备 Pre-LN 的稳定性？（提示：DeepNorm 走的正是"给残差乘一个与深度相关的系数 + 特制初始化"这条路。）

### 8. 和后续知识的连接
- 直接依赖前面学过的**残差连接**（梯度高速公路）和 **LayerNorm / RMSNorm**——本课就是这两者"如何组合"的关键抉择。
- 与**梯度消失与梯度爆炸**一课呼应：Pre-LN 正是从梯度稳定性角度对深层网络的又一处"救命"设计。
- 现代大模型（GPT、LLaMA 系列）的标准配方是 **Pre-LN + RMSNorm + final LayerNorm**，理解本课才能看懂它们 config 里为什么这么摆。
- 往后学 **DeepNorm、模型 scaling、训练稳定性（loss spike）** 时，Pre/Post-LN 之争是绕不开的起点。

---
学习进度：已学习 111 个知识点
上次学习：2026-07-02
当前类目：类目 13：Transformer 架构
下一阶段：类目 14：位置编码（已部分覆盖，继续查漏补缺）
