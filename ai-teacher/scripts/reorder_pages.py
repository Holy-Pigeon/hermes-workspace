#!/usr/bin/env python3
"""Add a numeric 序号 property + normalize Stage, then number all AI Teacher
lessons by dependency order (类目 1->19, prerequisite order within each)."""
import json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_to_notion as S

token = S.load_token()
config = S.load_config()
db_id = config["database_id"]

# within-category prerequisite order: distinctive substrings, in learning order
ORDER = {
 1: ["向量（Vector", "矩阵（Matrix", "矩阵乘法", "矩阵转置", "逆矩阵", "特征值", "奇异值分解"],
 2: ["导数（Derivative", "偏导数", "梯度（Gradient", "链式法则", "泰勒展开"],
 3: ["概率分布", "期望（Expectation", "方差（Variance", "贝叶斯定理", "最大似然估计"],
 4: ["熵（Entropy", "交叉熵", "KL 散度", "信息增益"],
 5: ["张量操作", "自动求导", "神经网络模块"],
 6: ["神经元模型", "激活函数（Activation", "前向传播"],
 7: ["损失函数", "梯度下降", "反向传播推导"],
 8: ["随机梯度下降", "Momentum", "Adam 优化器", "学习率调度"],
 9: ["Dropout", "L1/L2", "Batch Normalization"],
 10: ["RNN（循环", "LSTM", "GRU", "序列到序列"],
 11: ["软注意力与硬注意力", "Bahdanau", "Luong"],
 12: ["Query / Key / Value", "缩放点积注意力", "多头注意力（Multi-Head"],
 13: ["Encoder-Decoder 架构", "残差连接", "Layer Normalization"],
 14: ["正弦位置编码", "学习位置编码", "RoPE", "ALiBi"],
 15: ["多子空间表示", "注意力头数选择", "注意力的计算复杂度"],
 16: ["前馈网络 FFN 结构", "FFN 激活函数选择", "FFN 维度变换"],
 17: ["BERT——让模型", "RoBERTa", "ALBERT", "掩码语言模型", "NSP"],
 18: ["GPT——", "自回归生成", "因果注意力"],
 19: ["Sparse Attention", "Linear Attention", "FlashAttention"],
}
STAGE = {**{i: "阶段一：数学与编程基础" for i in range(1,6)},
         **{i: "阶段二：神经网络基础" for i in range(6,11)},
         **{i: "阶段三：Transformer 核心" for i in range(11,17)},
         **{i: "阶段四：Transformer 变体与优化" for i in range(17,21)}}

# 1) ensure 序号 number property exists
db = S.notion_request("GET", f"databases/{db_id}", token)
if "序号" not in db["properties"]:
    S.notion_request("PATCH", f"databases/{db_id}", token,
                     {"properties": {"序号": {"number": {"format": "number"}}}})
    print("[+] added 序号 property")
else:
    print("[=] 序号 property already exists")

# 2) fetch all pages
pages = []
cursor = None
while True:
    payload = {"page_size": 100}
    if cursor: payload["start_cursor"] = cursor
    res = S.notion_request("POST", f"databases/{db_id}/query", token, payload)
    for p in res["results"]:
        name = "".join(t.get("plain_text","") for t in p["properties"]["Name"]["title"])
        cat = p["properties"].get("Category", {}).get("select")
        cat_name = cat["name"] if cat else ""
        m = re.search(r"类目\s*(\d+)", cat_name)
        pages.append({"id": p["id"], "name": name, "cat": int(m.group(1)) if m else 999})
    if res.get("has_more"): cursor = res["next_cursor"]
    else: break

# 3) compute sequence number
def within_idx(cat, name):
    for i, kw in enumerate(ORDER.get(cat, [])):
        if kw in name:
            return i
    return 99
for p in pages:
    p["wi"] = within_idx(p["cat"], p["name"])
pages.sort(key=lambda x: (x["cat"], x["wi"], x["name"]))

# sanity: flag unmatched
unmatched = [p for p in pages if p["wi"] == 99]
if unmatched:
    print("!! UNMATCHED (within-order):")
    for p in unmatched: print("   ", p["cat"], p["name"])

# 4) write 序号 + normalized Stage
for seq, p in enumerate(pages, 1):
    stage = STAGE.get(p["cat"], "")
    props = {"序号": {"number": seq}}
    if stage:
        props["Stage"] = {"select": {"name": stage}}
    S.notion_request("PATCH", f"pages/{p['id']}", token, {"properties": props})
    print(f"{seq:>2}  [类目{p['cat']:>2}]  {p['name'][:40]}")
    time.sleep(0.12)

print(f"\nDONE: numbered {len(pages)} pages")
