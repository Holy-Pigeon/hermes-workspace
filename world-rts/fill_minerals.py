#!/usr/bin/env python3
"""灌入「关键矿产」维度(d04) × 14阵营 —— 双端(开采+精炼)综合模型。
数据源: USGS MCS 2025 + IEA Critical Minerals Outlook 2024 + WNA(铀), 见 minerals_shares.json。

核心逻辑(区别于前三维的自给率):矿产瓶颈 = 开采端 + 精炼端双闸门的"净依赖地位"。
- 控制方(开采或精炼份额高)→ 该矿产是筹码/武器,低瓶颈
- 依赖方(两端皆缺,靠进口)→ 高瓶颈
- 精炼端权重 > 开采端(精炼才是真卡脖子;矿可多地采,精炼被垄断更致命)

每个(阵营,矿产)算一个依赖分 dep∈[0,1](0=完全自主/控制, 1=完全依赖):
  self_share = 0.4*mining_share_self + 0.6*refining_share_self  (该阵营自身两端份额,精炼权重0.6)
  dep = clip(1 - self_share/阈值, 0, 1)   阈值=该矿产"够用"的自给线(简化取:自身份额≥25%视为基本自主)
阵营矿产维度物理缺口 = Σ(dep_矿 × 矿战略权重) / Σ权重, 再clip(0.2,1.0)

矿产战略权重(科技战相关性): 稀土/镓/锗/锂/钴/石墨=高(电池+半导体+永磁), 镍/铟=中, 铜/铀=中低(大宗/可替代来源多)。
"""
import json, os, math

BASE = os.path.expanduser("~/hermes-workspace/world-rts")
MATRIX = os.path.join(BASE, "data", "matrix.json")
SHARES = os.path.join(BASE, "minerals_shares.json")

# 阵营 → 中文主体国名(用于在份额表里匹配开采/精炼份额)
FAC_COUNTRY = {
    "us":"美国", "cn":"中国", "eu":"欧盟", "ru":"俄罗斯", "in":"印度",
    "jp":"日本", "kr":"韩国", "sa":"沙特", "br":"巴西", "id":"印尼",
    "mx":"墨西哥", "ng":"尼日利亚", "za":"南非", "vn":"越南",
}
# 别名(份额表里可能用DRC/澳大利亚等,阵营主体国需匹配)——14国里能对上的
ALIAS = {"欧盟":["欧盟","德国","法国"]}  # 欧盟暂无单列矿产份额,按依赖处理

# 矿产战略权重(科技战相关性)
MINERAL_WEIGHT = {
    "rare_earths":3.0, "gallium":2.5, "germanium":2.5, "lithium":2.5,
    "cobalt":2.0, "graphite":2.0, "indium":2.0,
    "nickel":1.5, "uranium":1.5, "copper":1.0,
    "niobium":1.5, "pgm":1.5,
}

def share_of(entry, country, side):
    """返回 country 在该矿产 side(mining/refining) 的份额%(找不到=0)"""
    key = "mining_top" if side=="mining" else "refining_top"
    for name,pct in entry.get(key,[]):
        if name==country: return pct
    return 0

def net_score(entry, country):
    """该阵营对该矿产的净地位分 net∈[-1,+1]。
    +1=完全依赖(瓶颈), -1=绝对控制(筹码/武器), 0=中性。
    self_share=0.4*mining+0.6*refining(精炼权重更高,真卡脖子)。
    - 依赖侧: self_share<自主线DEP_LINE(25%)→正分, 0%→+1
    - 控制侧: self_share>控制线CTRL_LINE(40%)→负分, 100%→-1
    - 两线之间: 线性过渡到0(基本自足,不算瓶颈也不算武器)"""
    ms = share_of(entry, country, "mining")
    rs = share_of(entry, country, "refining")
    self_share = 0.4*ms + 0.6*rs
    DEP_LINE, CTRL_LINE = 25.0, 40.0
    if self_share <= DEP_LINE:
        net = (DEP_LINE - self_share)/DEP_LINE          # 0..+1 (依赖)
    elif self_share >= CTRL_LINE:
        net = -min(1.0, (self_share - CTRL_LINE)/(100.0 - CTRL_LINE))  # 0..-1 (控制)
    else:
        net = 0.0                                        # 25-40%区间:基本自足
    return net, ms, rs

# 项2/3/4 赋档(sr,irr,sec, sr_desc,irr_desc,sec_desc, note) —— 每阵营矿产战略地位
JUDGE = {
    "us":(1.0,2.5,3.0,"关键矿产供应链安全=国家安全,IRA/国防生产法专项","精炼环节高度依赖中国,重建产能需5-10年","写入国安战略+IRA补贴+国防储备,生存级","开采部分自主(稀土MP/铜)但精炼几乎全靠中国;镓锗铟石墨NIR=100%"),
    "cn":(1.0,1.0,1.0,"矿产精炼垄断=中国的战略进攻武器而非瓶颈","本土精炼产能全球主导,资源端海外锁矿","矿产是中国反制筹码(2023镓锗/2023石墨/2025出口管制)","★净控制方:稀土精炼90%/镓98%/石墨98%/锂65%/钴68%,矿产维度对中国是筹码非瓶颈"),
    "eu":(1.0,3.0,2.5,"欧盟关键原材料法案CRMA立法应对,极度焦虑","两端几乎全缺,无本土精炼","CRMA设2030自主目标,战略级","开采精炼两端皆薄弱,高度依赖进口,CRMA(2024)立法自救"),
    "ru":(0.8,1.5,2.0,"铀浓缩是俄战略筹码,其他矿产中等","铀浓缩全球44%是王牌,镍钯有资源","铀浓缩=对西方核电的反制杠杆","★铀浓缩全球约44%(核燃料真卡点),镍/钯有资源;部分领域是控制方"),
    "in":(0.9,2.5,2.5,"印度关键矿产使命KABIL海外找矿,起步晚","本土资源有限精炼几乎无,依赖进口","国家关键矿产使命(2025)战略级","开采精炼两端薄弱,重度依赖进口,2023公布30种关键矿产清单"),
    "jp":(1.0,3.0,3.0,"资源小国,矿产安全=生存级国策(JOGMEC举国储备)","国土无矿+精炼有限,唯靠海外权益+储备+回收","JOGMEC国家储备+海外锁矿,生存级安全化","★两端几乎全缺,资源极度贫乏;靠JOGMEC储备/海外权益/城市矿山回收续命,是被卡最狠的阵营之一"),
    "kr":(1.0,3.0,3.0,"资源小国,电池强国却卡在上游矿,生存级焦虑","本土无矿,精炼有限(铟等少数),重度依赖","国家资源安全特别法+海外资源开发,生存级","★电池/半导体强国但上游矿产两端皆缺,极度依赖进口(尤其对中国);仅铟等少数二级精炼"),
    "sa":(0.7,2.0,2.0,"石油美元转矿产,Manara海外投矿+本土磷酸盐","本土磷酸盐/部分金属,精炼起步","Vision2030矿业列第三支柱,战略级","矿产开采精炼基础薄弱(除磷酸盐),靠主权基金Manara海外投矿布局"),
    "br":(0.6,1.5,1.5,"资源大国,铁矿铌资源丰富但精炼弱","铌全球主导+铁矿,但锂钴镍精炼弱","资源是出口筹码,精炼非重点","★铌全球垄断(未列入本清单)+铁矿资源强;但战略金属精炼端弱,资源型定位"),
    "id":(0.7,1.5,1.5,"镍王:开采精炼双强,资源民族主义(禁原矿出口)","镍两端全球主导55%开采,但其他矿依赖","镍下游一体化国策(禁出口逼建厂),战略级","★镍开采55%+精炼45%全球主导(资源武器),但镍以外其他战略矿产依赖进口"),
    "mx":(0.6,1.5,1.5,"银/铜/萤石资源,锂国有化但开采未成规模","铜银有资源,锂新国有化(LitioMx)未产","锂国有化(2023)战略意图但产能未落地","铜银萤石有资源;锂2023国有化设LitioMx但尚未规模开采"),
    "ng":(0.7,2.0,2.0,"锡钽锂等资源但开采无序+精炼几乎无","矿产资源存在但基建/治理制约开发","矿业多元化国策但落地弱","有锂锡钽等资源禀赋但开采无序、精炼几乎空白,实际高度依赖"),
    "za":(0.5,1.5,1.5,"铂族金属PGM全球垄断+锰铬,资源王牌","PGM全球~70%+锰铬,是南非的资源武器","PGM是战略出口筹码非瓶颈","★铂族金属PGM全球约70%(未列入本清单)+锰/铬主导;战略金属资源强国,精炼部分自主"),
    "vn":(0.7,2.0,2.0,"稀土储量全球第二但开采精炼未成规模","稀土/钨/铝土有储量但加工能力弱","稀土开发列规划但技术/资本受限","★稀土储量全球第二(2200万吨)但开采精炼几乎未启动,潜力未兑现,当前仍依赖"),
}

SRC_USGS = {"label":"USGS Mineral Commodity Summaries 2025(美国地质调查局,一手)","url":"https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries"}
SRC_IEA = {"label":"IEA Critical Minerals Outlook 2024(国际能源署,精炼份额权威)","url":"https://www.iea.org/reports/global-critical-minerals-outlook-2024"}
SRC_WNA = {"label":"World Nuclear Association 铀浓缩产能(核燃料)","url":"https://world-nuclear.org/information-library/nuclear-fuel-cycle/conversion-enrichment-and-fabrication/uranium-enrichment"}

POLICY_REFS = {
    "us":[{"label":"美国《通胀削减法案》IRA关键矿产条款(白宫)","url":"https://www.whitehouse.gov/cleanenergy/inflation-reduction-act-guidebook/"},
          {"label":"美国地质调查局关键矿产清单 USGS Critical Minerals List","url":"https://www.usgs.gov/news/national-news-release/us-geological-survey-releases-2022-list-critical-minerals"}],
    "cn":[{"label":"中国稀土/镓锗/石墨出口管制公告(商务部)","url":"http://www.mofcom.gov.cn/"},
          {"label":"《中华人民共和国出口管制法》(gov.cn)","url":"https://www.gov.cn/"}],
    "eu":[{"label":"欧盟《关键原材料法案》CRMA(欧盟委员会)","url":"https://commission.europa.eu/strategy-and-policy/priorities-2019-2024/european-green-deal/critical-raw-materials_en"}],
    "ru":[{"label":"俄罗斯国家原子能公司 Rosatom(铀浓缩)","url":"https://www.rosatom.ru/en/"}],
    "in":[{"label":"印度国家关键矿产使命 National Critical Mineral Mission(矿业部)","url":"https://mines.gov.in/"}],
    "jp":[{"label":"日本金属矿产资源机构 JOGMEC(国家储备/海外权益)","url":"https://www.jogmec.go.jp/english/"}],
    "kr":[{"label":"韩国《国家资源安全特别法》/韩国矿业公社 KOMIR","url":"https://www.komir.or.kr/"}],
    "sa":[{"label":"沙特工业与矿产资源部 MIM / Vision2030矿业","url":"https://www.mim.gov.sa/en"}],
    "br":[{"label":"巴西矿业与能源部 MME","url":"https://www.gov.br/mme/"}],
    "id":[{"label":"印尼能源与矿产资源部 ESDM(镍禁出口政策)","url":"https://www.esdm.go.id/"}],
    "mx":[{"label":"墨西哥经济部/锂国有化 LitioMx","url":"https://www.gob.mx/litiomx"}],
    "ng":[{"label":"尼日利亚矿业与钢铁发展部","url":"https://www.minesandsteel.gov.ng/"}],
    "za":[{"label":"南非矿产资源与能源部 DMRE(PGM主管)","url":"https://www.dmre.gov.za/"}],
    "vn":[{"label":"越南自然资源与环境部(稀土规划)","url":"https://monre.gov.vn/"}],
}

shares = json.load(open(SHARES, encoding="utf-8"))["minerals"]

TAU = 0.15   # softmax温度:小→极值主导,大→趋近线性平均

def softmax_agg(vals, tau):
    """soft-max:加权平均但用exp(v/tau)放大高值。tau→0退化为hard max,tau→∞退化为算术平均。"""
    mx = max(vals)  # 数值稳定:减去最大值防溢出
    ws = [math.exp((v - mx)/tau) for v in vals]
    s = sum(ws)
    return sum(v*w for v,w in zip(vals,ws))/s

def softmin_agg(vals, tau):
    """soft-min:对称地放大最低值(最强控制筹码)。"""
    return -softmax_agg([-v for v in vals], tau)

def build(fid):
    country = FAC_COUNTRY[fid]
    contribs=[]; sevs=[]
    wmax = max(MINERAL_WEIGHT.values())
    for mid, entry in shares.items():
        w = MINERAL_WEIGHT.get(mid, 1.0)
        net, ms, rs = net_score(entry, country)
        # 战略权重调制:高权重矿产的极值更致命/更有价值。sev∈[-1,+1]
        sev = net * (w / wmax)
        sevs.append(sev)
        contribs.append({"mineral":entry["cn_name"],"net":round(net,2),"sev":round(sev,3),
                         "mining_share":ms,"refining_share":rs,"weight":w,
                         "role":("控制方" if net<-0.1 else "依赖方" if net>0.1 else "自足")})
    # τ=0.15 soft极值:软肋端soft-max(放大最痛)+王牌端soft-min(放大最强牌),二者叠加
    worst = softmax_agg(sevs, TAU)   # 最致命依赖(soft) ∈约[0,+1]
    best  = softmin_agg(sevs, TAU)   # 最强控制筹码(soft) ∈约[-1,0]
    # best为负才算真王牌;若无控制项(best≥0)则不抵消
    net_pos = max(-1.0, min(1.0, worst + min(0.0, best)))
    # 映射物理缺口[0.2,1.0]: net_pos=+1(纯软肋无牌)→1.0, -1(绝对控制)→0.2
    pg_raw = 0.2 + (net_pos + 1)/2 * (1.0 - 0.2)
    return round(net_pos,3), round(pg_raw,3), round(worst,3), round(best,3), contribs

m = json.load(open(MATRIX, encoding="utf-8"))
for fid in FAC_COUNTRY:
    country = FAC_COUNTRY[fid]
    net_pos, pg_raw, worst, best, contribs = build(fid)
    pg = round(max(0.2, min(1.0, pg_raw)), 3)
    sr, irr, sec, srd, irrd, secd, note = JUDGE[fid]
    prefs = POLICY_REFS.get(fid, [])
    aces = [c["mineral"] for c in contribs if c["net"]<-0.1]
    # 最痛软肋矿产名(展示用)
    worst_min = max(contribs, key=lambda c:c["sev"])
    pain = worst_min["mineral"] if worst_min["sev"]>0.1 else "无致命依赖"
    cell = {
        "physical_gap":{"value":pg,"self_sufficiency":round((1-net_pos)/2*100,1),
            "desc":f"12战略金属·soft极值(τ={TAU}):最痛软肋({pain},soft{worst:+.2f})+最强王牌(soft{best:+.2f})={net_pos:+.2f}(+1纯依赖/-1绝对控制;开采40%精炼60%,权重调制)。映射物理缺口{pg}(下限0.2)",
            "breakdown":contribs,"aces":aces,"pain":pain,"data_year":2024,"note":note,"sources":[SRC_USGS,SRC_IEA,SRC_WNA]},
        "strategic_relevance":{"value":sr,"desc":srd,"source":"基于官方关键矿产战略文件判断","policy_refs":prefs},
        "irreplaceability":{"value":irr,"desc":irrd,"policy_refs":prefs},
        "security_amp":{"value":sec,"desc":secd,"source":"基于官方战略文件判断","policy_refs":prefs},
    }
    cell["score"] = round(pg*sr*irr*sec, 2)
    m.setdefault("cells", {})[f"{fid}::d04"] = cell
    tag = f"★王牌:{'/'.join(aces)}" if aces else ""
    print(f"✓ {fid}({country}): 软肋{worst:+.3f}+王牌{best:+.3f}=净{net_pos:+.3f} pg={pg} score={cell['score']} {tag}")

json.dump(m, open(MATRIX, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n已写入 matrix.json (d04 关键矿产 14阵营, soft极值 τ={TAU})")
