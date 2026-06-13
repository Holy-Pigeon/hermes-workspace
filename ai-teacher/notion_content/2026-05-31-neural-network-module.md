## 今日知识点：神经网络模块（torch.nn.Module）——把参数和计算组织成可训练的积木

### 所属类目
类目 5：Python 与 PyTorch

### 问题入口
前面我们已经知道，张量让数据能被批量计算，Autograd 让计算图能自动反向传播梯度。可是真正训练神经网络时，还有一个更工程化但非常关键的问题：

模型里的参数放在哪里？前向计算写在哪里？优化器怎么知道要更新哪些参数？

如果只是写几个张量和函数，小例子还能跑；但 Transformer 有词嵌入层、注意力层、前馈网络、归一化层、残差连接，以及很多重复堆叠的子层。没有一个统一的组织方式，模型很快会变成一堆难以追踪的变量。

`torch.nn.Module` 要解决的困难就是：把“可训练参数”和“前向计算逻辑”打包成一个清晰的对象，让模型可以被组合、训练、保存、加载和迁移到 GPU。

### 朴素想法
如果还不知道 `nn.Module`，我们可能会自然地写一个普通函数：

```python
import torch

W = torch.randn(3, 2, requires_grad=True)
b = torch.zeros(2, requires_grad=True)

def linear(x):
    return x @ W + b
```

这个办法很直观：参数就是 `W` 和 `b`，前向计算就是 `x @ W + b`。

再进一步，我们也许会用一个普通 Python 类：

```python
class MyLinear:
    def __init__(self):
        self.W = torch.randn(3, 2, requires_grad=True)
        self.b = torch.zeros(2, requires_grad=True)

    def forward(self, x):
        return x @ self.W + self.b
```

这看起来已经像模型了：参数和计算被放在同一个地方。

### 卡住的地方
普通函数和普通类的问题，不在于不能计算，而在于“训练系统看不懂它”。

比如优化器通常需要这样拿到参数：

```python
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
```

如果 `model` 只是普通类，PyTorch 不知道哪些属性是参数、哪些只是普通缓存，也不知道子模块在哪里。你就得手动维护参数列表：

```python
params = [model.W, model.b]
```

模型变大后，这会很容易漏掉参数。漏掉的参数不会更新，看起来训练在跑，实际上某些层永远学不到东西。

另一个问题是设备迁移。真实训练常要把模型从 CPU 放到 GPU：

```python
model.to("cuda")
```

普通类不会自动递归移动内部参数。保存、加载、切换训练模式和推理模式也都会变得混乱。

所以我们需要一个模型容器，它不仅能执行计算，还能向 PyTorch 声明：这些是我的参数，这些是我的子模块，这些状态需要被保存。这就是 `nn.Module`。

### 1. 概念
`torch.nn.Module` 是 PyTorch 中所有神经网络层和模型的基类。基类可以理解成“共同父类”：你写自己的模型时继承它，就能获得 PyTorch 约定好的模型能力。

一个 `nn.Module` 通常包含两部分：

- `__init__`：定义子层和可训练参数。
- `forward`：定义输入如何一步步变成输出。

最小例子：

```python
import torch
from torch import nn

class MyLinear(nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = nn.Parameter(torch.randn(3, 2))
        self.bias = nn.Parameter(torch.zeros(2))

    def forward(self, x):
        return x @ self.weight + self.bias
```

通俗理解：`nn.Module` 像一个标准化的工具箱。你把会被训练的零件放进工具箱，把使用这些零件的步骤写在说明书里。之后 PyTorch 不需要理解你脑子里的设计，只要按工具箱规则，就能找到零件、更新零件、搬运工具箱、保存工具箱。

回到机制本身，`nn.Module` 的核心不是“让计算更神奇”，而是“让计算结构可管理”。它把参数注册、子模块递归、状态保存、设备迁移和训练模式切换统一到一套接口里。

### 2. 推导与证明
我们用一个简单线性层看清楚 `nn.Module` 为什么能成为训练系统的接口。

设输入是一个向量：

$$
x = [x_1, x_2, x_3]
$$

线性层参数是：

$$
W \in \mathbb{R}^{3 \times 2}, \quad b \in \mathbb{R}^2
$$

输出为：

$$
y = xW + b
$$

这里：

- $x$ 是输入特征。
- $W$ 是权重矩阵，决定每个输入维度如何影响输出维度。
- $b$ 是偏置向量，允许输出整体平移。
- $y$ 是线性层输出。

关键步骤：

1. 把会学习的量声明成参数

在 PyTorch 中：

```python
self.weight = nn.Parameter(torch.randn(3, 2))
```

`nn.Parameter` 是一种特殊张量。它告诉 `nn.Module`：这个张量不是普通中间变量，而是模型需要学习的参数。

为什么要这么做？因为优化器只会更新被注册为参数的张量。注册参数相当于把它写入模型的“可训练清单”。

2. 把计算路径写进 `forward`

```python
def forward(self, x):
    return x @ self.weight + self.bias
```

`forward` 描述从输入到输出的实际计算。调用模型时：

```python
y = model(x)
```

PyTorch 内部会调用 `model.__call__`，再进入你写的 `forward`。这就是为什么实践中通常写 `model(x)`，而不是直接写 `model.forward(x)`：前者会保留 PyTorch 在调用前后插入钩子和状态管理的机会。

3. 让优化器通过统一接口拿到参数

```python
list(model.parameters())
```

会递归返回模型中所有被注册的参数。如果模型内部还有子模块，比如：

```python
self.layer = nn.Linear(3, 2)
```

那么 `layer` 里的权重和偏置也会自动出现在 `model.parameters()` 里。

为什么这很重要？因为神经网络训练的更新公式通常是：

$$
\theta \leftarrow \theta - \eta \nabla_{\theta} L
$$

这里：

- $\theta$ 表示模型参数。
- $\eta$ 是学习率，控制每次更新步长。
- $L$ 是损失函数。
- $\nabla_{\theta} L$ 是损失对参数的梯度。

优化器必须知道所有 $\theta$ 在哪里，才能执行这一步。`nn.Module` 就是把这些参数集中暴露出来的结构。

4. 用状态字典保存模型

```python
model.state_dict()
```

会返回模型参数和缓冲状态的字典，例如：

```text
weight -> tensor(...)
bias -> tensor(...)
```

这让模型保存不依赖整个 Python 对象，而是保存最核心的可学习状态。以后加载同结构模型时，再把这些状态填回去。

### 3. 来源与历史动机
- 论文：PyTorch: An Imperative Style, High-Performance Deep Learning Library
- 作者：Adam Paszke, Sam Gross, Francisco Massa 等
- 时间：2019
- 链接：https://arxiv.org/abs/1912.01703

历史背景：深度学习模型从早期简单网络逐渐变成复杂系统。研究人员需要一种既像普通 Python 一样灵活，又能让训练框架自动管理参数和状态的模型表示方式。PyTorch 的 `nn.Module` 延续了 Torch 生态中“模块化神经网络层”的思想，并配合动态图 Autograd，让模型定义、调试和训练更贴近普通程序写法。

这个设计的重要性在于：它没有强迫用户先声明一张完整静态图，而是允许用 Python 类自然组织模型，同时仍然保留参数注册、设备管理和序列化能力。

### 4. 核心用途
用途一：搭建可训练模型。

几乎所有 PyTorch 模型都会继承 `nn.Module`。无论是一个线性分类器、CNN、RNN，还是完整 Transformer，本质上都是由许多 `Module` 组合成的树状结构。

用途二：复用和组合网络层。

`nn.Linear`、`nn.Embedding`、`nn.LayerNorm`、`nn.MultiheadAttention` 都是模块。你可以把它们像积木一样放进自己的模型。Transformer 的 Encoder block 也是一个模块，多个 block 还能继续堆成更大的模块。

用途三：统一训练、保存和部署流程。

`model.parameters()` 给优化器用，`model.to(device)` 负责移动设备，`model.train()` 和 `model.eval()` 切换训练与推理行为，`model.state_dict()` 用于保存权重。这些统一接口让模型从实验走向实际使用。

### 5. 反直觉点与常见误区
反直觉点：

`nn.Module` 本身不会自动让模型变聪明。真正的数值计算仍然发生在张量操作里，梯度仍然来自 Autograd。`nn.Module` 的价值主要是组织和注册：它让 PyTorch 知道哪些东西属于模型。

常见误区：
- 误区一：把张量直接赋给 `self.weight` 就一定会被优化器更新。普通张量不会自动成为参数，应该使用 `nn.Parameter`，或者使用已经内置好参数注册的层，比如 `nn.Linear`。
- 误区二：忘记调用 `super().__init__()`。如果父类初始化没有执行，模块内部的参数和子模块注册机制可能无法正常工作。
- 误区三：推理时忘记 `model.eval()`。像 Dropout、BatchNorm 这类模块在训练和推理时行为不同，不切换模式会导致结果不稳定。

### 6. 小实验
你可以用极短代码验证：只有注册进 `nn.Module` 的参数，才会被 `parameters()` 找到。

```python
import torch
from torch import nn

class Demo(nn.Module):
    def __init__(self):
        super().__init__()
        self.a = torch.randn(2, requires_grad=True)
        self.b = nn.Parameter(torch.randn(2))
        self.linear = nn.Linear(2, 1)

    def forward(self, x):
        return self.linear(x + self.a + self.b)

model = Demo()

for name, param in model.named_parameters():
    print(name, param.shape)
```

你会看到类似输出：

```text
b torch.Size([2])
linear.weight torch.Size([1, 2])
linear.bias torch.Size([1])
```

但不会看到 `a`。原因是 `a` 虽然 `requires_grad=True`，却只是普通张量，没有被注册为 `nn.Parameter`。

这说明一个重要区别：Autograd 负责“能不能算梯度”，`nn.Module` 负责“这个量是不是模型参数、会不会被优化器统一管理”。

### 7. 批判性思考
局限性：

`nn.Module` 提供的是组织结构，不保证模型设计合理。你可以写出能运行但学习效果很差的模块，也可以因为参数没有正确注册、设备不一致、模式切换错误而得到隐蔽 bug。

另一个限制是，`forward` 里过度依赖复杂 Python 控制流时，虽然动态图可以运行，但后续导出、编译或部署可能更困难。研究阶段的灵活性和生产阶段的可优化性之间，经常需要取舍。

深度问题：

如果 Transformer 是由许多 `nn.Module` 堆叠而成的，那么“模型结构”和“计算图”是不是同一件事？

答案是否定的。`nn.Module` 是模型的静态组织方式，描述有哪些层和参数；计算图是某一次前向计算时由具体张量操作动态产生的依赖关系。同一个模块在不同输入、不同分支下，可能产生不同计算图。

### 8. 和后续知识的连接
理解 `nn.Module` 后，后面的神经网络课程会自然很多。

学习多层感知机时，我们会把多个 `nn.Linear` 和激活函数组合成一个模块。学习反向传播时，`Module` 提供参数入口，Autograd 提供梯度来源，优化器负责更新。学习 Transformer 时，Embedding、Attention、FFN、LayerNorm、Encoder block、Decoder block 都会以模块形式组织。

也就是说，`nn.Module` 是从“数学公式”走向“可训练工程系统”的桥。没有它，你仍然可以算张量；有了它，模型才变成一个能被训练框架理解和管理的整体。

---
学习进度：已学习 26 个知识点
上次学习：2026-05-31
当前类目：类目 5：Python 与 PyTorch
下一阶段：感知机与多层感知机
