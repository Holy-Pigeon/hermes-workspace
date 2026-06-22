#!/usr/bin/env python3
"""价值雷达 API Token 管理 CLI。

与 app.py 的 token 体系共用同一份文件 ~/.hermes/dashboard_tokens.json。
文件只存 sha256(token),明文仅在 issue 时打印一次,丢失只能重发。

用法:
  # 签发:30 天有效、最多 20 个不同 IP
  python3 token_admin.py issue --label "手机+脚本" --days 30 --max-ips 20

  # 永久 / 不限 IP(省略对应参数)
  python3 token_admin.py issue --label "内部"

  python3 token_admin.py list            # 列出所有(只显示 hash 前缀,不显示明文)
  python3 token_admin.py revoke <hash前缀>   # 吊销(按 token_hash 前缀匹配)
  python3 token_admin.py reset-ips <hash前缀> # 清空已记录 IP(重新计数)
"""
import os, sys, json, time, hashlib, secrets, argparse, datetime
from pathlib import Path

TOKENS_FILE = Path.home() / ".hermes" / "dashboard_tokens.json"


def _load() -> dict:
    try:
        return json.loads(TOKENS_FILE.read_text())
    except Exception:
        return {"tokens": []}


def _save(data: dict):
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(TOKENS_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def _fmt_ts(ts):
    if ts is None:
        return "永久"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def cmd_issue(args):
    tok = "vr_" + secrets.token_urlsafe(24)  # 明文 token,vr_ 前缀便于辨识
    now = time.time()
    expires = None if args.days is None else now + args.days * 86400
    rec = {
        "label": args.label,
        "token_hash": _hash(tok),
        "created": now,
        "expires": expires,
        "max_ips": args.max_ips,   # None = 不限
        "seen_ips": [],
        "revoked": False,
    }
    data = _load()
    data.setdefault("tokens", []).append(rec)
    _save(data)
    print("✅ Token 已签发(明文只显示这一次,请立即保存):\n")
    print(f"  TOKEN     : {tok}")
    print(f"  标签      : {args.label}")
    print(f"  有效期    : {'永久' if expires is None else f'{args.days} 天(至 {_fmt_ts(expires)})'}")
    print(f"  IP 上限   : {'不限' if args.max_ips is None else args.max_ips} 个不同 IP")
    print(f"  hash 前缀 : {rec['token_hash'][:12]}")
    print("\n用法示例:")
    print(f"  浏览器: https://<面板地址>/?token={tok}")
    print(f"  脚本  : curl -H 'X-Auth-Token: {tok}' https://<面板地址>/api/system")


def cmd_list(args):
    data = _load()
    toks = data.get("tokens", [])
    if not toks:
        print("(无 token)")
        return
    now = time.time()
    print(f"{'hash前缀':<14}{'标签':<18}{'状态':<8}{'有效期至':<18}{'IP用量':<10}{'最后IP'}")
    print("-" * 86)
    for r in toks:
        exp = r.get("expires")
        if r.get("revoked"):
            status = "已吊销"
        elif exp is not None and now > exp:
            status = "已过期"
        else:
            status = "有效"
        max_ips = r.get("max_ips")
        ipu = f"{len(r.get('seen_ips', []))}/{'∞' if max_ips is None else max_ips}"
        print(f"{r['token_hash'][:12]:<14}{(r.get('label') or '')[:16]:<18}{status:<8}"
              f"{_fmt_ts(exp):<18}{ipu:<10}{r.get('last_ip', '-')}")


def _match(data, prefix):
    hits = [r for r in data.get("tokens", []) if r.get("token_hash", "").startswith(prefix)]
    if len(hits) == 0:
        print(f"✗ 没有匹配 '{prefix}' 的 token")
        return None
    if len(hits) > 1:
        print(f"✗ 前缀 '{prefix}' 匹配到 {len(hits)} 条,请用更长前缀")
        return None
    return hits[0]


def cmd_revoke(args):
    data = _load()
    r = _match(data, args.prefix)
    if not r:
        sys.exit(1)
    r["revoked"] = True
    _save(data)
    print(f"✅ 已吊销:{r['token_hash'][:12]} ({r.get('label')})")


def cmd_reset_ips(args):
    data = _load()
    r = _match(data, args.prefix)
    if not r:
        sys.exit(1)
    n = len(r.get("seen_ips", []))
    r["seen_ips"] = []
    _save(data)
    print(f"✅ 已清空 {r['token_hash'][:12]} 的 {n} 个已记录 IP,重新计数")


def main():
    ap = argparse.ArgumentParser(description="价值雷达 API Token 管理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("issue", help="签发新 token")
    pi.add_argument("--label", required=True, help="用途标签")
    pi.add_argument("--days", type=int, default=None, help="有效天数(省略=永久)")
    pi.add_argument("--max-ips", type=int, default=None, dest="max_ips", help="最多不同 IP 数(省略=不限)")
    pi.set_defaults(func=cmd_issue)

    pl = sub.add_parser("list", help="列出所有 token")
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("revoke", help="吊销 token")
    pr.add_argument("prefix", help="token_hash 前缀")
    pr.set_defaults(func=cmd_revoke)

    prs = sub.add_parser("reset-ips", help="清空某 token 已记录的 IP")
    prs.add_argument("prefix", help="token_hash 前缀")
    prs.set_defaults(func=cmd_reset_ips)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
