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

# 阵营 → OWID country 名 (14单一主权棋手)
FAC_MAP = {
    "us":"United States", "cn":"China", "eu":"European Union (27)",
    "ru":"Russia", "in":"India", "jp":"Japan", "kr":"South Korea",
    "sa":"Saudi Arabia", "br":"Brazil", "id":"Indonesia",
    "mx":"Mexico", "ng":"Nigeria", "za":"South Africa", "vn":"Vietnam",
}
# 项2/3/4 赋档(政策判断)+ note。(sr, irr, sec, sr_desc, irr_desc, sec_desc, note)
JUDGE = {
    "us":(0.8,1.0,1.5,"能源独立既定国策且已实现","多元自产+盟友供给易替代","能源已自主非生存级","页岩革命后能源净出口国"),
    "cn":(1.0,2.0,3.0,"能源安全写入十四五,油气进口通道核心关切","石油进口依赖中东+马六甲海运,替代难","能源安全=生存级,战略储备+多元化举国推进","核电燃料铀约60%+依赖进口"),
    "eu":(1.0,2.5,3.0,"2022俄气断供后能源安全升至最高战略","俄气断供后LNG替代成本高周期长","REPowerEU=生存级去俄化,不计成本","EU27整体;核电铀依赖俄/哈"),
    "ru":(0.8,1.0,2.0,"能源是财政命脉与地缘武器","能源极度自给无需替代","安全关切在出口通道非供给端","净出口国,物理缺口触0.2下限"),
    "in":(1.0,2.0,2.5,"能源安全是印度增长关键约束","油气进口依赖中东,替代有限","能源进口安全战略级但未到举国","石油对外依存度超85%"),
    "jp":(1.0,3.0,3.0,"资源贫国,能源安全=国家生存基础","化石无本土替代,核电是唯一自主选项","能源=生存级,核电复兴+战略储备","化石几乎全进口,自给率全球最低之一;核电铀100%进口"),
    "kr":(1.0,3.0,3.0,"资源贫国,油气煤高度依赖进口","化石无本土替代,核电是主要本土贡献","能源=生存级安全国策","油气煤高度依赖进口,核电本土主力"),
    "sa":(0.9,1.0,1.5,"油气是立国根基但供给端无瓶颈","能源极度盈余","安全关切在后石油转型(Vision2030)非供给","世界级油气出口国;净出口触0.2下限"),
    "br":(0.6,1.0,1.5,"能源基本自给非核心战略瓶颈","深海油+水电+乙醇多元替代性好","能源安全非紧迫议题","深海油+水电+乙醇多元;净出口触0.2下限"),
    "id":(0.8,1.5,2.0,"最大动力煤出口国但油气转进口","煤盈余但石油已净进口,替代中","能源安全上升(油气进口增)","全球最大动力煤出口国之一;石油净进口"),
    "mx":(0.8,1.5,2.0,"曾能源自给,近年油气转net进口","炼油能力不足需进口成品油","能源主权是政治议题(Pemex国有)","原油出口但成品油/天然气依赖美国进口"),
    "ng":(0.7,1.5,2.0,"产油国但炼油瘫痪,成品油全进口","原油出口却进口成品油,替代畸形","能源是财政命脉但下游瘫痪","非洲最大产油国之一;炼油能力瘫痪,成品油依赖进口"),
    "za":(0.9,2.0,2.5,"煤电为主但电力危机严重(限电)","煤自给但电网老化,替代难","能源安全=经济生存(Eskom危机)","煤炭自给但Eskom限电危机,电力严重短缺"),
    "vn":(0.9,1.5,2.0,"曾能源出口国近年转净进口","煤油气均转进口,增长快耗能高","能源安全随工业化上升","制造业崛起耗能激增,煤油气转净进口"),
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

# 项2/3/4 赋档依据的真实政策/战略文件(链接均已实测,403/Cloudflare的为反爬非死链,真浏览器可开)
POLICY_REFS = {
    "us":   [{"label":"美国能源部 DOE(能源独立战略主管机构)","url":"https://www.energy.gov/"},
             {"label":"Inflation Reduction Act 2022 法案文本(congress.gov,H.R.5376;反爬需浏览器)","url":"https://www.congress.gov/bill/117th-congress/house-bill/5376"}],
    "cn":   [{"label":"《十四五现代能源体系规划》原文(国务院gov.cn,2022)","url":"https://www.gov.cn/zhengce/zhengceku/2022-03/23/content_5680759.htm"},
             {"label":"国家能源局(能源安全新战略主管)","url":"https://www.nea.gov.cn/"}],
    "eu":   [{"label":"REPowerEU Plan 官方页(欧盟委员会,2022)","url":"https://commission.europa.eu/strategy-and-policy/priorities-2019-2024/european-green-deal/repowereu-affordable-secure-and-sustainable-energy-europe_en"}],
    "ru":   [{"label":"俄罗斯联邦能源部 Minenergo(《至2035能源战略》主管)","url":"https://minenergo.gov.ru/"}],
    "in":   [{"label":"印度国家绿氢使命 National Green Hydrogen Mission(MNRE,2023)","url":"https://mnre.gov.in/national-green-hydrogen-mission/"},
             {"label":"NITI Aayog(National Energy Policy 主管)","url":"https://www.niti.gov.in/"}],
    "jp": [{"label":"日本能源基本计划 Strategic Energy Plan(经产省METI/资源能源厅)","url":"https://www.enecho.meti.go.jp/en/category/others/basic_plan/"}],
    "kr": [{"label":"韩国产业通商资源部 MOTIE(能源基本计划主管)","url":"https://www.motie.go.kr/"},
           {"label":"韩国能源经济研究院 KEEI","url":"https://www.keei.re.kr/"}],
    "sa": [{"label":"Saudi Vision 2030 官方门户(后石油转型;Cloudflare需浏览器)","url":"https://www.vision2030.gov.sa/en"}],
    "br": [{"label":"巴西能源研究公司 EPE(十年能源扩展计划 PDE 主管)","url":"https://www.epe.gov.br/"}],
    "id": [{"label":"印尼能源与矿产资源部 ESDM(国家能源总规划 RUEN 主管)","url":"https://www.esdm.go.id/"}],
    "mx": [{"label":"墨西哥能源部 SENER","url":"https://www.gob.mx/sener"},
           {"label":"墨西哥国家石油公司 Pemex","url":"https://www.pemex.com/"}],
    "ng": [{"label":"尼日利亚石油资源部 / NNPC(国家石油公司)","url":"https://www.nnpcgroup.com/"}],
    "za": [{"label":"南非矿产资源与能源部 DMRE","url":"https://www.dmr.gov.za/"},
           {"label":"南非电力公司 Eskom(限电危机)","url":"https://www.eskom.co.za/"}],
    "vn": [{"label":"越南工贸部 MOIT(第八次电力规划PDP8主管)","url":"https://moit.gov.vn/en/"}],
}

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
    if wss is None or not bd or len(bd)<3:
        # 拆解品类不足3项=OWID商业能源数据严重不全(如尼日利亚传统生物质为主未计入)
        # 诚实标注待核,不强行填0或假数据
        print(f"⚠ {fid}({country}) 拆解仅{len(bd) if bd else 0}项,数据不全→标注待核,不灌假数据")
        continue
    ss_cap=min(wss,100)  # 净出口封顶100
    pg=round(max(0.2,min(1.0,(100-ss_cap)/100)),3)  # 0.2下限
    sr,irr,sec,srd,irrd,secd,note=JUDGE[fid]
    sources=[SRC_OWID,SRC_EI]
    if fid=="eu": sources.append(SRC_EUROSTAT)
    prefs=POLICY_REFS.get(fid,[])  # 政策判断依据的真实文件链接
    cell={
        "physical_gap":{"value":pg,"self_sufficiency":round(wss,1),
            "desc":f"六项加权自给率{wss}%(净出口封顶100,物理缺口下限0.2)",
            "breakdown":bd,"data_year":yr,"note":note,"sources":sources},
        "strategic_relevance":{"value":sr,"desc":srd,"source":"基于官方能源战略文件判断","policy_refs":prefs},
        "irreplaceability":{"value":irr,"desc":irrd,"policy_refs":prefs},
        "security_amp":{"value":sec,"desc":secd,"source":"基于官方战略文件判断","policy_refs":prefs},
    }
    cell["score"]=round(pg*sr*irr*sec,2)
    m.setdefault("cells",{})[f"{fid}::d01"]=cell
    print(f"✓ {fid}: 加权自给{wss}%({yr}) pg={pg} score={cell['score']} [{len(bd)}项]")

json.dump(m,open(MATRIX,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
print("\n已写入 matrix.json")
