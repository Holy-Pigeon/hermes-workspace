#!/usr/bin/env python3
"""World-RTS 能源维度(d01)全量重灌 —— 六项拆解版。
石油/天然气/煤炭 自给率 = OWID production/consumption(有硬数据)
核电/水电/风光 = 本土发电≈100%(核电铀依赖单独在 note 标注)
加权自给率 = Σ(品类自给率 × 品类消费占比)
物理缺口 = clip((100−加权自给率)/100, 0.2, 1.0)  ← 用户要求下限0.2
多源可跳转 URL + 品类明细写入 cell.physical_gap.breakdown。
"""
import csv, json, os

OWID = "/tmp/owid_energy.csv"
BASE = os.path.expanduser("~/hermes-workspace/world-rts")
MATRIX = os.path.join(BASE, "data", "matrix.json")

# 阵营 → OWID country 名(用代表经济体，多国阵营取主导体或加注)
FAC_MAP = {
    "us":"United States", "cn":"China", "eu":"European Union (27)",
    "ru":"Russia", "in":"India", "jpkr":"Japan", "gulf":"Saudi Arabia",
    "asean":"Indonesia", "latam":"Brazil", "africa":"Africa",
}
# 项2/3/4 赋档(政策判断)+ note。(sr, irr, sec, sr_desc, irr_desc, sec_desc, note)
JUDGE = {
    "us":   (0.8,1.0,1.5,"能源独立既定国策且已实现","多元自产+盟友供给易替代","能源已自主非生存级","代表体:美国本土"),
    "cn":   (1.0,2.0,3.0,"能源安全写入十四五,油气进口通道核心关切","石油进口依赖中东+马六甲海运,替代难","能源安全=生存级,战略储备+多元化举国推进","核电燃料铀约60%+依赖进口"),
    "eu":   (1.0,2.5,3.0,"2022俄气断供后能源安全升至最高战略","俄气断供后LNG替代成本高周期长","REPowerEU=生存级去俄化,不计成本","代表体:EU27整体;核电铀依赖俄/哈"),
    "ru":   (0.8,1.0,2.0,"能源是财政命脉与地缘武器","能源极度自给无需替代","安全关切在出口通道非供给端","净出口国,物理缺口触0.2下限"),
    "in":   (1.0,2.0,2.5,"能源安全是印度增长关键约束","油气进口依赖中东,替代有限","能源进口安全战略级但未到举国","代表体:印度本土"),
    "jpkr": (1.0,3.0,3.0,"资源贫国,能源安全=国家生存基础","化石无本土替代,核电是唯一自主选项","能源=生存级,战略储备+核电复兴","代表体:日本;核电铀100%进口"),
    "gulf": (0.9,1.0,1.5,"油气是立国根基但供给端无瓶颈","能源极度盈余","安全关切在后石油转型非供给","代表体:沙特;净出口触0.2下限"),
    "asean":(0.7,1.5,2.0,"区域整体能源盈余但内部分化","区域内可调剂但跨国电网不足","能源安全区域协调中未到举国","代表体:印尼(最大动力煤出口国);新马依赖进口"),
    "latam":(0.6,1.0,1.5,"能源基本自给非核心战略瓶颈","本土多元能源结构替代性好","能源安全非紧迫议题","代表体:巴西(深海油+水电+乙醇);净出口触0.2下限"),
    "africa":(0.7,2.0,2.0,"能源可及性是发展瓶颈(电力普及率低)","基建薄弱制约本土能源转化","能源发展战略优先但资金受限","代表体:非洲整体;产油国盈余but多数电力短缺"),
}

CATS = [("石油","oil_consumption","oil_production"),
        ("天然气","gas_consumption","gas_production"),
        ("煤炭","coal_consumption","coal_production"),
        ("核电","nuclear_consumption",None),
        ("水电","hydro_consumption",None),
        ("风光","solar_consumption",None)]

# 可跳转一手源 URL
SRC_OWID = {"label":"OWID Energy Data (←Energy Institute Statistical Review 2024 + EIA)",
            "url":"https://github.com/owid/energy-data"}
SRC_EI = {"label":"Energy Institute Statistical Review of World Energy 2024",
          "url":"https://www.energyinst.org/statistical-review"}
SRC_EUROSTAT = {"label":"Eurostat 能源进口依赖度 nrg_ind_id (欧盟官方,交叉验证用)",
                "url":"https://ec.europa.eu/eurostat/databrowser/view/nrg_ind_id/default/table"}

def fnum(row,k):
    try: return float(row.get(k,""))
    except: return None

# 读 OWID
rows = {}
with open(OWID, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["country"] in FAC_MAP.values():
            try: yr=int(row["year"])
            except: continue
            rows.setdefault(row["country"],{})[yr]=row

def build_breakdown(country):
    yr=None
    for y in sorted(rows.get(country,{}),reverse=True):
        if fnum(rows[country][y],"primary_energy_consumption"): yr=y;break
    if yr is None: return None,None,None
    row=rows[country][yr]; total=fnum(row,"primary_energy_consumption")
    bd=[]; wsum=0
    for name,cc,pc in CATS:
        cons=fnum(row,cc) or 0
        if name=="风光": cons+=fnum(row,"wind_consumption") or 0
        if cons<=0: continue
        w=cons/total
        if pc:
            prod=fnum(row,pc) or 0
            ss=round(min(prod/cons*100,999),1)
        else:
            ss=100.0
        bd.append({"item":name,"self_sufficiency":ss,"weight":round(w,3),
                   "consumption_twh":round(cons)})
        wsum+=ss*w
    return round(wsum,1),yr,bd

m=json.load(open(MATRIX,encoding="utf-8"))
for fid,country in FAC_MAP.items():
    wss,yr,bd=build_breakdown(country)
    if wss is None:
        print(f"⚠ {fid} 无数据"); continue
    ss_cap=min(wss,100)  # 净出口封顶100
    pg=round(max(0.2,min(1.0,(100-ss_cap)/100)),3)  # 0.2下限
    sr,irr,sec,srd,irrd,secd,note=JUDGE[fid]
    sources=[SRC_OWID,SRC_EI]
    if fid=="eu": sources.append(SRC_EUROSTAT)
    cell={
        "physical_gap":{"value":pg,"self_sufficiency":round(wss,1),
            "desc":f"六项加权自给率{wss}%(净出口封顶100,物理缺口下限0.2)",
            "breakdown":bd,"data_year":yr,"note":note,"sources":sources},
        "strategic_relevance":{"value":sr,"desc":srd,"source":"基于官方能源战略文件判断"},
        "irreplaceability":{"value":irr,"desc":irrd},
        "security_amp":{"value":sec,"desc":secd,"source":"基于官方战略文件判断"},
    }
    cell["score"]=round(pg*sr*irr*sec,2)
    m.setdefault("cells",{})[f"{fid}::d01"]=cell
    print(f"✓ {fid}: 加权自给{wss}%({yr}) pg={pg} score={cell['score']} [{len(bd)}项]")

json.dump(m,open(MATRIX,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
print("\n已写入 matrix.json")
