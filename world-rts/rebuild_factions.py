#!/usr/bin/env python3
"""重构 World-RTS 阵营结构：10聚合阵营 → 14单一主权棋手(方向A)。
砍掉地理平均(东盟/拉美/非洲),拆成有代表性的单一国家。
保留 matrix.json 其余结构(维度/层/公式),只换 factions + 迁移已有 cells 的 id。
"""
import json, os

BASE = os.path.expanduser("~/hermes-workspace/world-rts")
MATRIX = os.path.join(BASE, "data", "matrix.json")

# 新14阵营 (id, name, flag)。id 尽量沿用旧的以复用数据
NEW_FACTIONS = [
    ("us","美国","🇺🇸"),
    ("cn","中国","🇨🇳"),
    ("eu","欧盟","🇪🇺"),
    ("ru","俄罗斯","🇷🇺"),
    ("in","印度","🇮🇳"),
    ("jp","日本","🇯🇵"),
    ("kr","韩国","🇰🇷"),
    ("sa","沙特","🇸🇦"),
    ("br","巴西","🇧🇷"),
    ("id","印尼","🇮🇩"),
    ("mx","墨西哥","🇲🇽"),
    ("ng","尼日利亚","🇳🇬"),
    ("za","南非","🇿🇦"),
    ("vn","越南","🇻🇳"),
]

# 旧id → 新id 的 cell 迁移映射(仅迁移语义明确对应的)
# jpkr(韩国代表体) → kr; gulf(沙特) → sa; latam(巴西) → br; asean(印尼) → id
# africa 是平均值,不迁移(丢弃,重新按 ng/za 采集); 能源的jpkr是日本→jp
# 注意:能源 jpkr 用的是日本数据,粮食 jpkr 用的是韩国数据,需分别迁移
CELL_MIGRATE = {
    # 能源维度 d01
    "jpkr::d01":"jp::d01",   # 能源jpkr=日本数据 → jp
    "gulf::d01":"sa::d01",
    "latam::d01":"br::d01",
    "asean::d01":"id::d01",
    # 粮食维度 d02
    "jpkr::d02":"kr::d02",   # 粮食jpkr=韩国数据 → kr
    "gulf::d02":"sa::d02",
    "latam::d02":"br::d02",
    "asean::d02":"id::d02",
    # africa 两维都是平均值 → 丢弃(不迁移,待按单一国家重采)
}

# 阵营结构重构：直接换14阵营，清空旧cells，两维按14国全新重灌(比拼接迁移更可靠、口径一致)
m = json.load(open(MATRIX, encoding="utf-8"))
m["factions"] = [{"id":i,"name":n,"flag":f} for i,n,f in NEW_FACTIONS]
m["cells"] = {}   # 清空，由 fill_energy/fill_food 按新14国重灌
m["meta"]["factions_count"] = len(NEW_FACTIONS)

json.dump(m, open(MATRIX,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"阵营重构为 {len(NEW_FACTIONS)} 个单一主权棋手，cells已清空待重灌:")
for i,n,f in NEW_FACTIONS:
    print(f"  {f} {n} ({i})")
