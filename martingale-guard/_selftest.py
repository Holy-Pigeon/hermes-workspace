"""自测:临时DB注入三种加仓轨迹,验证判级正确(不触碰真实盘DB)。
运行: /opt/homebrew/bin/python3 _selftest.py  → 期望 "自测 PASS"。
"""
import sqlite3, tempfile, os, importlib.util
spec = importlib.util.spec_from_file_location("mg", "martingale_guard.py")
mg = importlib.util.module_from_spec(spec); spec.loader.exec_module(mg)

tmp = tempfile.mktemp(suffix=".db")
c = sqlite3.connect(tmp)
c.execute("CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT)")
c.execute("CREATE TABLE trades(id INTEGER PRIMARY KEY, account_id INT, symbol TEXT, name TEXT, market TEXT, currency TEXT, side TEXT, quantity REAL, price REAL, fx_rate REAL, traded_at TEXT)")
c.execute("INSERT INTO accounts VALUES(1,'test')")
# 场景A: 教科书马丁——越跌买越多 (应 R3 红)
for i,(px,q) in enumerate([(100,10000),(90,12000),(80,15000),(70,20000)]):
    c.execute("INSERT INTO trades(account_id,symbol,name,market,currency,side,quantity,price,fx_rate,traded_at) VALUES(1,'AAA','马丁股','A股','CNY','buy',?,?,1.0,?)",(q,px,f"2026-06-1{i} 10:00"))
# 场景B: 向下加仓但缩量 (应 R1 橙)
for i,(px,q) in enumerate([(50,20000),(45,5000),(40,3000)]):
    c.execute("INSERT INTO trades(account_id,symbol,name,market,currency,side,quantity,price,fx_rate,traded_at) VALUES(1,'BBB','摊低股','A股','CNY','buy',?,?,1.0,?)",(q,px,f"2026-06-1{i} 11:00"))
# 场景C: 顺势加仓 (应 绿,不误伤向赢家加仓)
for i,(px,q) in enumerate([(20,10000),(25,10000),(30,10000)]):
    c.execute("INSERT INTO trades(account_id,symbol,name,market,currency,side,quantity,price,fx_rate,traded_at) VALUES(1,'CCC','顺势股','A股','CNY','buy',?,?,1.0,?)",(q,px,f"2026-06-1{i} 12:00"))
c.commit(); c.close()

mg.DB = tmp
res = mg.analyze(account='test', use_price=False)
for f in res:
    print(f["level"], f["symbol"], "买入", f["n_buys"], "次 ->", f["detail"])
os.unlink(tmp)

exp = {"AAA":"\U0001F534","BBB":"\U0001F7E0","CCC":"\U0001F7E2"}  # 马丁红/摊低橙/顺势绿
ok = all(next(f["level"] for f in res if f["symbol"]==k)==v for k,v in exp.items())
print("\n自测", "PASS 全部符合预期" if ok else "FAIL 有偏差")
