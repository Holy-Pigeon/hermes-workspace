#!/usr/bin/env python3
"""灌入「粮食·农业」维度(d02) × 10阵营 —— 六品类拆解版(对标能源维度)。
数据源: FAOSTAT Food Balance Sheets 2023(一手官方, bulk下载免key)。
自给率 = Production(5511) / Domestic supply quantity(5301)。
六品类: 谷物/大豆油料/肉类/糖/蔬果/奶蛋鱼。权重=各品类国内供应量(1000t)占六类合计比。
物理缺口 = clip((100−加权自给率封顶100)/100, 0.2, 1.0)。
项2/3/4 政策判断带真实文件链接。
"""
import csv, json, os

FAO = "/tmp/fao_fbs/FoodBalanceSheets_E_All_Data_(Normalized).csv"
BASE = os.path.expanduser("~/hermes-workspace/world-rts")
MATRIX = os.path.join(BASE, "data", "matrix.json")

# 阵营 → FAO Area Code (14单一主权棋手)。日本FAO FBS缺数据→jp不在此表(标待核)
FAC_AREA = {
    "us":231, "cn":41, "eu":None, "ru":185, "in":100,
    "kr":117,  # 韩国(日本FAO缺数据,jp单独标待核)
    "sa":194,  # 沙特
    "br":21,   # 巴西
    "id":101,  # 印尼
    "mx":138,  # 墨西哥
    "ng":159,  # 尼日利亚
    "za":202,  # 南非
    "vn":237,  # 越南
    # jp 日本: FAO FBS无数据,不灌(前端保持待采集)
}
# 欧盟用区域聚合 Area Code
FAC_AREA_REGION = {"eu":5707}  # 5707=EU27

# 六品类聚合 item code
CATS = [
    ("谷物", 2905),
    ("大豆油料", 2913),
    ("肉类", 2943),
    ("糖", 2909),
    ("蔬果", None),   # 2918蔬菜+2919水果合并
    ("奶蛋鱼", None), # 2848奶+2949蛋+2960鱼合并
]
CAT_MULTI = {"蔬果":[2918,2919], "奶蛋鱼":[2848,2949,2960]}

# 项2/3/4 赋档(sr,irr,sec, sr_desc,irr_desc,sec_desc, note)
JUDGE = {
    "us":(0.7,1.0,1.0,"农业出口强国,粮食安全非瓶颈","多元高产+出口盈余","粮食完全自主非安全议题","代表体:美国;全球最大农产品出口国之一"),
    "cn":(1.0,2.0,3.0,"口粮绝对安全写入国策,大豆是软肋","谷物基本自给但大豆85%+靠进口,替代难","粮食安全=生存级,18亿亩耕地红线+储备举国","代表体:中国mainland;大豆对外依存度极高"),
    "eu":(0.8,1.5,2.0,"CAP保障粮食自给,整体盈余","部分饲料/油料进口但可替代","粮食安全政策级非生存级","代表体:EU27;共同农业政策CAP高补贴"),
    "ru":(0.8,1.0,1.5,"谷物出口大国,粮食武器化","谷物极度盈余","粮食安全在出口端非供给端","代表体:俄罗斯;全球最大小麦出口国"),
    "in":(1.0,1.5,2.5,"口粮自给是14亿人口生存底线","谷物自给但油料依赖进口","粮食安全=战略级,公共分配系统PDS","代表体:印度;食用油高度依赖进口"),
    "kr":(1.0,2.5,3.0,"卡路里自给率极低,极度依赖进口","耕地稀缺无本土替代空间","粮食安全=生存级国策,长期提自给率","韩国;谷物自给全球最低之一(日本FAO缺数据单列待核)"),
    "sa":(1.0,3.0,3.0,"沙漠国家几乎全靠进口,水粮双缺","无耕地无淡水,本土生产极限低","粮食安全=生存级,海外购地+储备战略","沙特;粮食自给率极低"),
    "id":(0.7,1.5,2.0,"人口大国口粮压力,大米自给波动","热带作物盈余但小麦全进口","粮食安全国策,Bulog储备调控","印尼;2.7亿人口,大米自给+小麦全进口"),
    "br":(0.5,1.0,1.0,"农业出口巨头,粮食极度盈余","本土多元高产替代性极好","粮食安全非议题反而是出口筹码","巴西;全球大豆/肉类出口龙头"),
    "mx":(0.9,1.5,2.0,"玉米原产国却进口玉米,粮食主权敏感","主粮玉米/小麦依赖美国进口","粮食主权是政治议题(对美依赖)","墨西哥;玉米/谷物高度依赖美国进口"),
    "ng":(1.0,2.0,2.5,"人口第一大国,主粮缺口扩大","农业生产率低+安全局势制约","粮食安全=社会稳定核心","尼日利亚;2亿+人口,主粮进口依赖上升"),
    "za":(0.7,1.0,1.5,"非洲粮仓,谷物基本自给","本土农业强,替代性好","粮食安全区域枢纽非瓶颈","南非;撒南非洲少数粮食净出口国"),
    "vn":(0.6,1.0,1.5,"大米出口大国,主粮盈余","水稻高产替代性好","粮食安全是出口筹码非瓶颈","越南;全球前三大米出口国"),
}

# 数据源(可跳转)
SRC_FAO = {"label":"FAOSTAT Food Balance Sheets 2023(联合国粮农组织,官方bulk)",
           "url":"https://www.fao.org/faostat/en/#data/FBS"}
SRC_USDA = {"label":"USDA Foreign Agricultural Service PSD(交叉参考)",
            "url":"https://fas.usda.gov/data/production"}

# 政策文件(真实链接,与粮食安全相关)
POLICY_REFS = {
    "us":[{"label":"USDA 美国农业部(农业出口/粮食政策主管)","url":"https://www.usda.gov/"}],
    "cn":[{"label":"《国家粮食安全中长期规划纲要》/耕地红线(农业农村部)","url":"http://www.moa.gov.cn/"},
          {"label":"《中华人民共和国粮食安全保障法》(2024施行,gov.cn)","url":"https://www.gov.cn/"}],
    "eu":[{"label":"欧盟共同农业政策 CAP(欧盟委员会农业总司)","url":"https://agriculture.ec.europa.eu/common-agricultural-policy_en"}],
    "ru":[{"label":"俄罗斯粮食安全学说 Doctrine of Food Security(俄农业部)","url":"https://mcx.gov.ru/"}],
    "in":[{"label":"印度国家粮食安全法 National Food Security Act(粮食公共分配部)","url":"https://dfpd.gov.in/"}],
    "kr":[{"label":"韩国农林畜产食品部 MAFRA(粮食自给率目标主管)","url":"https://www.mafra.go.kr/"}],
    "sa":[{"label":"沙特环境水利农业部 MEWA(农业与粮食安全战略)","url":"https://www.mewa.gov.sa/en"}],
    "id":[{"label":"印尼国家粮食局 Bapanas(粮食安全主管)","url":"https://badanpangan.go.id/"}],
    "br":[{"label":"巴西农业部 MAPA(农业出口大国)","url":"https://www.gov.br/agricultura/"}],
    "mx":[{"label":"墨西哥农业与农村发展部 SADER","url":"https://www.gob.mx/agricultura"}],
    "ng":[{"label":"尼日利亚农业与粮食安全部 FMAFS","url":"https://fmard.gov.ng/"}],
    "za":[{"label":"南非农业部 DALRRD","url":"https://www.dalrrd.gov.za/"}],
    "vn":[{"label":"越南农业与农村发展部 MARD","url":"https://www.mard.gov.vn/"}],
}

def load_fao():
    """返回 {area_code:{item_code:{elem_code:value}}} for 最新年(2023)。
    5511=生产 5301=国内供应(算自给率) 661=卡路里供应(算权重)"""
    data = {}
    with open(FAO, newline="", encoding="utf-8", errors="replace") as f:
        r = csv.reader(f); h=next(r)
        ci={n:i for i,n in enumerate(h)}
        A,IT,EL,Y,V = ci["Area Code"],ci["Item Code"],ci["Element Code"],ci["Year"],ci["Value"]
        for row in r:
            if len(row)<=V: continue
            try:
                area=int(row[A]); item=int(row[IT]); elem=int(row[EL]); yr=int(row[Y])
                val=float(row[V]) if row[V] else 0
            except: continue
            if yr!=2023: continue
            if elem not in (5511,5301,661): continue
            data.setdefault(area,{}).setdefault(item,{})[elem]=val
    return data

FAO_DATA = load_fao()

def ss_of(area, items):
    """给定 item(s): 自给率=ΣProduction/ΣDomestic supply(吨口径),
    权重量=Σ卡路里供应661(kcal口径,粮食安全语义)。返回(自给率, kcal权重量)"""
    prod=supp=kcal=0
    for it in (items if isinstance(items,list) else [items]):
        d=FAO_DATA.get(area,{}).get(it,{})
        prod+=d.get(5511,0); supp+=d.get(5301,0); kcal+=d.get(661,0)
    if supp<=0: return None,0
    return round(prod/supp*100,1), kcal

def build(area):
    bd=[]; wtot=0; contribs=[]
    for name,code in CATS:
        items = CAT_MULTI.get(name, code)
        ss,supp = ss_of(area, items)
        if ss is None or supp<=0: continue
        bd.append([name,ss,supp])
        wtot+=supp
    if not bd or wtot<=0: return None,None
    out=[]; wss=0
    for name,ss,kc in bd:
        w=kc/wtot
        out.append({"item":name,"self_sufficiency":ss,"weight":round(w,3),"kcal_share_pct":round(w*100,1)})
        wss+=ss*w
    return round(wss,1),out

m=json.load(open(MATRIX,encoding="utf-8"))
for fid in FAC_AREA:
    area = FAC_AREA_REGION.get(fid) or FAC_AREA[fid]
    wss,bd = build(area)
    if wss is None:
        print(f"⚠ {fid}(area={area}) 无数据"); continue
    ss_cap=min(wss,100)
    pg=round(max(0.2,min(1.0,(100-ss_cap)/100)),3)
    sr,irr,sec,srd,irrd,secd,note=JUDGE[fid]
    prefs=POLICY_REFS.get(fid,[])
    cell={
        "physical_gap":{"value":pg,"self_sufficiency":wss,
            "desc":f"六品类卡路里加权粮食自给率{wss}%(权重=各品类卡路里供应占比,贴合粮食安全语义;净出口封顶100,缺口下限0.2)",
            "breakdown":bd,"data_year":2023,"note":note,"sources":[SRC_FAO,SRC_USDA]},
        "strategic_relevance":{"value":sr,"desc":srd,"source":"基于官方粮食安全战略文件判断","policy_refs":prefs},
        "irreplaceability":{"value":irr,"desc":irrd,"policy_refs":prefs},
        "security_amp":{"value":sec,"desc":secd,"source":"基于官方战略文件判断","policy_refs":prefs},
    }
    cell["score"]=round(pg*sr*irr*sec,2)
    m.setdefault("cells",{})[f"{fid}::d02"]=cell
    print(f"✓ {fid}: 加权粮食自给{wss}% pg={pg} score={cell['score']} [{len(bd)}品类]")

json.dump(m,open(MATRIX,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
print("\n已写入 matrix.json")
