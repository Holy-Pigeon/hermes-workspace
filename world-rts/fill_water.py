#!/usr/bin/env python3
"""灌入「水」维度(d03) × 14阵营。
数据源: World Bank(数据溯源 FAO AQUASTAT), 免key稳定。
两个硬指标:
  ① 人均内部可再生水 ER.H2O.INTR.PC (m3/人) —— 存量稀缺度
  ② 淡水取用占内部资源比 ER.H2O.FWTL.ZS (%) —— water stress水压力,越高越逼近枯竭
物理缺口 = 综合两指标(stress 60% + 人均 40%),锚点线性映射后取(100-综合分)/100,clip(0.2,1.0)。
  - stress锚点: <=10%充裕=100分, >=100%枯竭=0分
  - 人均锚点: >=4000 m3/人=100分, <=500=0分(绝对缺水线,国际警戒1700为参考)
跨境依赖度(上游截流风险)AQUASTAT精确值API不可得→定性note标注,不编数字。
项2/3/4 政策判断带真实文件链接。
"""
import json, os

BASE = os.path.expanduser("~/hermes-workspace/world-rts")
MATRIX = os.path.join(BASE, "data", "matrix.json")
WATER_PC = "/tmp/water_intr.json"   # {iso3:[name,val,year]}

# 阵营 → World Bank ISO3(EU用EUU聚合)
FAC_ISO = {
    "us":"USA", "cn":"CHN", "eu":"EUU", "ru":"RUS", "in":"IND",
    "jp":"JPN", "kr":"KOR", "sa":"SAU", "br":"BRA", "id":"IDN",
    "mx":"MEX", "ng":"NGA", "za":"ZAF", "vn":"VNM",
}

# 硬数据: 人均内部可再生水(m3/人,2022) + water stress取用占比(%,2022)
# 均来自 World Bank / FAO AQUASTAT,已在采集脚本核实
WATER = {
    # iso3:(人均可再生水m3, water_stress取用占内部资源%)
    "USA":(8437.2, 15.77),
    "CHN":(1991.9, 20.21),
    "EUU":(3040.5, 13.69),
    "RUS":(29895.3, 1.50),
    "IND":(1014.4, 44.78),
    "JPN":(3436.6, 18.53),
    "KOR":(1255.0, 45.02),
    "SAU":(74.6,  974.17),
    "BRA":(26917.9, 1.20),
    "IDN":(7239.9, 11.03),
    "MEX":(3180.1, 21.96),
    "NGA":(990.4,  5.64),
    "ZAF":(718.2, 47.12),
    "VNM":(3605.7, 22.78),
}

def stress_score(s):
    # <=10充裕=100, >=100枯竭=0
    return max(0.0, min(100.0, (100.0 - s) / (100.0 - 10.0) * 100.0))

def pc_score(pc):
    # >=4000=100, <=500=0
    return max(0.0, min(100.0, (pc - 500.0) / (4000.0 - 500.0) * 100.0))

def water_score(pc, s):
    return round(0.6 * stress_score(s) + 0.4 * pc_score(pc), 1)

# 项2/3/4 赋档(sr,irr,sec, sr_desc,irr_desc,sec_desc, note)
# 跨境依赖度定性标注写入note(AQUASTAT精确dependency ratio API不可得,标待核)
JUDGE = {
    "us":(0.5,1.0,1.0,"水资源整体充裕,区域性缺水(西南)","内部资源丰富多元","水非国家安全瓶颈","人均8437m3充裕;西部科罗拉多河/西南干旱是区域问题,非全国瓶颈"),
    "cn":(0.8,1.5,2.0,"北方缺水+南水北调是长期国策","水资源时空分布极不均,工程调水","水安全写入国策(南水北调/三条红线)","人均1992m3中等偏紧;华北平原严重超采,跨境依赖低(多为上游)"),
    "eu":(0.5,1.0,1.0,"整体水资源平衡,南欧地中海区缺水","内部资源充足","水非欧盟级安全瓶颈","人均3040m3;南欧(西/意/希)季节性干旱是区域问题"),
    "ru":(0.3,1.0,1.0,"水资源极度充裕,全球前列","内部资源海量(贝加尔湖等)","水完全非瓶颈","人均29895m3全球顶级;水是战略盈余资产"),
    "in":(0.9,2.0,2.5,"14亿人口+农业90%耗水,水压力极高","地下水超采+季风依赖,替代难","水安全=生存级(地下水危机/河流分水)","人均1014m3低于缺水线;water stress 45%高压;部分河流上游在中国(布拉马普特拉),跨境依赖待核"),
    "jp":(0.4,1.0,1.0,"降水丰沛水资源充足","内部资源充足","水非安全瓶颈","人均3437m3充裕;岛国降水丰沛,无跨境依赖"),
    "kr":(0.9,2.0,2.0,"人均水资源低+高取用率,压力显著","国土狭小水库调节有限","水安全是长期治理议题","人均1255m3低于缺水线;water stress 45%高压;半岛无重大上游依赖"),
    "sa":(1.0,3.0,3.0,"沙漠国家,几乎无淡水,靠海水淡化续命","无地表径流,化石地下水枯竭在即,唯一替代=淡化(高耗能)","水=生存级绝对安全,国家存续命脉","人均仅75m3全球垫底;water stress 974%严重超采(取用远超再生);60%+饮用水靠海水淡化"),
    "br":(0.3,1.0,1.0,"水资源全球最丰富之一","亚马逊流域海量","水是战略盈余","人均26918m3全球第二;水极度盈余"),
    "id":(0.4,1.0,1.0,"热带岛国降水充沛","内部资源丰富","水非国家瓶颈","人均7240m3充裕;区域(爪哇岛)人口密集有局部压力"),
    "mx":(0.7,1.5,1.5,"北部干旱+城市缺水,区域性紧张","南北分布不均","水安全区域治理议题","人均3180m3中等;北部/墨西哥城缺水,与美国科罗拉多河分水协定"),
    "ng":(0.6,1.5,1.5,"人均水偏低+基建薄弱,取水能力受限","乍得湖萎缩+水基建不足","水安全与发展绑定","人均990m3低;water stress仅5.6%(取水能力不足非水多);乍得湖生态危机"),
    "za":(0.9,2.0,2.0,"半干旱国家,开普敦曾濒临Day Zero","水资源本就稀缺+分布不均","水安全=战略级(缺水危机反复)","人均718m3严重缺水;water stress 47%高压;2018开普敦Day Zero危机"),
    "vn":(0.8,2.5,2.0,"湄公河/红河下游,上游截流风险高","水量充足但命脉在他国上游","水安全=地缘敏感(跨境河流依赖)","人均3606m3看似充足但严重依赖跨境河流:湄公河上游(中国/老挝水坝)+红河上游(中国),外部依赖度高,枯水期受制于人"),
}

SRC_WB = {"label":"World Bank 世界发展指标(数据溯源 FAO AQUASTAT)","url":"https://data.worldbank.org/indicator/ER.H2O.INTR.PC"}
SRC_STRESS = {"label":"World Bank 淡水取用占内部资源比 ER.H2O.FWTL.ZS(FAO AQUASTAT)","url":"https://data.worldbank.org/indicator/ER.H2O.FWTL.ZS"}
SRC_AQUA = {"label":"FAO AQUASTAT 全球水资源数据库(一手源)","url":"https://data.apps.fao.org/aquastat/"}

# 政策文件(真实链接,各国水资源主管/战略)
POLICY_REFS = {
    "us":[{"label":"US Bureau of Reclamation 垦务局(西部水资源主管)","url":"https://www.usbr.gov/"}],
    "cn":[{"label":"《国家水网建设规划纲要》/南水北调(水利部)","url":"http://www.mwr.gov.cn/"},
          {"label":"最严格水资源管理制度『三条红线』(gov.cn)","url":"https://www.gov.cn/"}],
    "eu":[{"label":"EU Water Framework Directive 水框架指令(欧盟环境总司)","url":"https://environment.ec.europa.eu/topics/water/water-framework-directive_en"}],
    "ru":[{"label":"俄罗斯联邦水资源署 Rosvodresursy","url":"https://voda.gov.ru/"}],
    "in":[{"label":"印度 Jal Shakti 水利部(地下水/河流分水主管)","url":"https://jalshakti-dowr.gov.in/"}],
    "jp":[{"label":"日本国土交通省水管理·国土保全局","url":"https://www.mlit.go.jp/mizukokudo/"}],
    "kr":[{"label":"韩国环境部 K-water 水资源公社","url":"https://www.kwater.or.kr/eng/"}],
    "sa":[{"label":"沙特环境水利农业部 MEWA(海水淡化战略)","url":"https://www.mewa.gov.sa/en"},
          {"label":"沙特海水淡化总公司 SWCC/SWPC","url":"https://www.swpc.sa/en"}],
    "br":[{"label":"巴西国家水资源与卫生署 ANA","url":"https://www.gov.br/ana/"}],
    "id":[{"label":"印尼公共工程与住房部(水资源总司)","url":"https://www.pu.go.id/"}],
    "mx":[{"label":"墨西哥国家水资源委员会 CONAGUA","url":"https://www.gob.mx/conagua"}],
    "ng":[{"label":"尼日利亚水资源与卫生部 FMWRS","url":"https://water.gov.ng/"}],
    "za":[{"label":"南非水利与卫生部 DWS","url":"https://www.dws.gov.za/"}],
    "vn":[{"label":"越南农业与环境部(水资源管理)/湄公河委员会 MRC","url":"https://www.mrcmekong.org/"}],
}

m = json.load(open(MATRIX, encoding="utf-8"))
for fid, iso in FAC_ISO.items():
    pc, stress = WATER[iso]
    score = water_score(pc, stress)
    ss_cap = min(score, 100)
    pg = round(max(0.2, min(1.0, (100 - ss_cap) / 100)), 3)
    sr, irr, sec, srd, irrd, secd, note = JUDGE[fid]
    prefs = POLICY_REFS.get(fid, [])
    breakdown = [
        {"item":"人均内部可再生水","value":pc,"unit":"m³/人","score":round(pc_score(pc),1),"anchor":"缺水线1700,绝对缺水500"},
        {"item":"淡水取用/内部资源(water stress)","value":stress,"unit":"%","score":round(stress_score(stress),1),"anchor":"充裕≤10%,枯竭≥100%"},
    ]
    cell = {
        "physical_gap":{"value":pg,"self_sufficiency":score,
            "desc":f"水资源安全综合分{score}(water stress 60%权重+人均可再生水40%;缺口下限0.2)。人均{pc:.0f}m³/人,取用占内部资源{stress:.1f}%",
            "breakdown":breakdown,"data_year":2022,"note":note,"sources":[SRC_WB,SRC_STRESS,SRC_AQUA]},
        "strategic_relevance":{"value":sr,"desc":srd,"source":"基于官方水资源战略文件判断","policy_refs":prefs},
        "irreplaceability":{"value":irr,"desc":irrd,"policy_refs":prefs},
        "security_amp":{"value":sec,"desc":secd,"source":"基于官方战略文件判断","policy_refs":prefs},
    }
    cell["score"] = round(pg * sr * irr * sec, 2)
    m.setdefault("cells", {})[f"{fid}::d03"] = cell
    print(f"✓ {fid}({iso}): 水安全分{score} 人均{pc:.0f}m³ stress{stress:.1f}% pg={pg} score={cell['score']}")

json.dump(m, open(MATRIX, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n已写入 matrix.json (d03 水维 14阵营)")
