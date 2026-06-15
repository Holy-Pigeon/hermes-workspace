#!/usr/bin/env python3
# 回填被 research_db_sync latest-only 丢弃的 note 论据
# 宁德 catl_moat_understated（护城河工具冲突）+ 茅台 moutai_diversification（压舱分散化实测）
# 冲突/命门未决的论点标 needs_review，让 DB 确定性如实匹配 note
import psycopg2

conn = psycopg2.connect(dbname='stockchoose', user='postgres', host='localhost')
cur = conn.cursor()

# 取 pick_id
cur.execute("SELECT id, stock_name FROM stock_picks WHERE stock_name IN ('宁德时代','贵州茅台') AND pick_type='research_only';")
ids = {n: i for i, n in cur.fetchall()}
catl_id, moutai_id = ids['宁德时代'], ids['贵州茅台']

rows = [
    # 宁德 moat 冲突篇
    dict(
        pick_id=catl_id,
        title='护城河强于moat工具🧱窄标签（工具对穿越结构性低谷型公司有系统盲区）',
        detail=('moat_scorecard首跑判🧱窄护城河(净利率CV0.241/趋势-0.4pp/ROE≥15%持久性仅67%)，'
                '与reverse_dcf"真便宜成长"+现金含量162%干净 直接冲突。停下查根因，三处工具盲区：'
                '①趋势-0.4pp是基期污染——远半含2016-17上市前小规模虚高margin(19.6/21.0%)，'
                '只看2018规模化后margin 10.2%→18.1%(+7.9pp)是加宽不是侵蚀；'
                '②ROE持久性67%把2018-20补贴退坡行业低谷(全行业一起趴)算成宁德单独缺陷，'
                '实则2021-25连续5年ROE18-22%/加权21-25%；'
                '③CV0.241惩罚的是"穿越一次结构性低谷"而非日常不稳。'
                '【最大待证命门(标needs_review主因)】2025净利率18.1%中有多少是碳酸锂跌价的一次性成本红利、'
                '而非真定价权？2022锂价暴涨时margin被压到10.2%，2024-25锂价回落才弹回——成本端顺风。'
                'reverse_dcf篇已用"毛利率纹丝不动24.4→24.8%"间接论证量增驱动，但net margin扩张仍含锂价因素，待中报拆归因。'),
        data=('一手akshare年报口径2016-2026Q1净利率/ROE序列；2018规模化后margin单调修复10.2%→18.1%；'
              '2021-25连续5年ROE18-22%；对照迈瑞净利率CV0.111(宁德0.241确实更波动)。'),
        inval=('①若2026中报净利率跌破16%(即2025的18%是锂价回落一次性红利而非结构定价权)→margin扩张证伪，'
               'moat工具🧱窄反而对；②若26Q1 ROE年化跌出20%→"现行制度高ROE"动摇。'),
        status='needs_review',
        still_valid=True,
    ),
    # 茅台 分散化压舱篇
    dict(
        pick_id=moutai_id,
        title='组合分散化压舱价值（与现持仓平均相关0.07，负相关对冲富联）',
        detail=('近119交易日(2025-12-12~2026-06-12)一手新浪qfq日线皮尔逊相关实测：'
                '茅台vs现A股3持仓(富联/小商品城/紫金)平均成对相关=0.07，仅为现持仓内部相关(0.27)的1/4，'
                '是真低相关补充而非伪分散加A股beta。茅台↔工业富联=-0.14负相关——富联是组合里估值最贵'
                '(史92/96/93%分位)、唯一负α主拖累、顶部筹码派发、最高关税beta的四重红旗持仓，'
                '茅台对它天然下行对冲(AI/出口杀跌时必需消费常逆势)，是结构性对冲非单纯低相关。'
                '机制：茅台内需/高端消费/品牌定价权驱动，现持仓AI算力(富联)/出口贸易(小商品城)/大宗(紫金)驱动，'
                '宏观因子几乎不重叠=0.07低相关根因，非统计巧合。'
                '【最大局限(标needs_review主因)】仅测近半年常态，危机相关性未测——相关性在危机中趋同是经典风险。'),
        data=('相关矩阵：茅台↔富联-0.14/↔小商品城0.19/↔紫金0.17；茅台vs现3持仓平均0.07 vs 现持仓内部0.27；'
              '样本119交易日单一市场状态。康方港股交易日历不同未纳入。'),
        inval=('若拉长到2-3年窗口、或A股系统性回撤期(如2024Q1式踩踏)茅台与组合相关性跳升到>0.5，'
               '则"压舱"在最需要它的尾部时刻失效，低相关仅是平时现象。'),
        status='needs_review',
        still_valid=True,
    ),
]

inserted = []
for r in rows:
    # 幂等：同 pick + 同 title 已存在则跳过
    cur.execute("SELECT id FROM stock_theses WHERE stock_pick_id=%s AND thesis_title=%s;",
                (r['pick_id'], r['title']))
    ex = cur.fetchone()
    if ex:
        print(f"SKIP existing thesis id={ex[0]}: {r['title'][:30]}")
        continue
    cur.execute("""
        INSERT INTO stock_theses
          (stock_pick_id, thesis_title, thesis_detail, still_valid, status,
           key_supporting_data, invalidation_condition, last_checked_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s, CURRENT_DATE)
        RETURNING id;
    """, (r['pick_id'], r['title'], r['detail'], r['still_valid'], r['status'],
          r['data'], r['inval']))
    nid = cur.fetchone()[0]
    inserted.append((nid, r['status'], r['title']))
    print(f"INSERT id={nid} status={r['status']}: {r['title'][:40]}")

conn.commit()
print(f"\n共新增 {len(inserted)} 条论点")
cur.close()
conn.close()
