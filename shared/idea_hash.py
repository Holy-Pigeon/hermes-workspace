"""创新引擎 idea 唯一键的【单一权威实现】(single source of truth)。

dashboard/app.py(前端展示+审批写reviews.json) 和
innovation-engine/engine/ie.py(创新引擎处理review时匹配) 都必须 import 这里的
compute_idea_id，绝不各自再写一份。

历史教训(2026-06-15):这个函数曾散落在 app.py 和 ie.py 两处,改 app.py 的哈希
算法时漏改了 ie.py,导致面板审批写入的新哈希id 与创新引擎匹配用的旧明文id 对不上,
5条已审批approve全部 NOT_FOUND 不推进、状态卡死。收口到本模块根除此类分裂。

约束:纯 stdlib(hashlib),不依赖任何第三方包——因为两个调用方用不同 python 解释器
(homebrew python3 / 系统 python3),共享模块必须在两个解释器下都能直接跑。

口径:日期::sha1(日期::标题全文)[:12]。纯十六进制字符,对标题里的逗号/空格/引号/
斜杠/emoji 等特殊字符完全透明(这些字符在 onclick内联、URL编码、JSON传输中会被改写)。
若未来要改 id 算法,只改本函数一处即可,两个调用方自动同步。
"""
import hashlib


def compute_idea_id(ts: str, title: str) -> str:
    """计算 idea 唯一键。

    Args:
        ts:    日期/时间戳列(ideas_log.md 行的 parts[0])
        title: 标题列原文(ideas_log.md 行的 parts[2],未截断)
    Returns:
        形如 "2026-06-15 16:28::1f637361902a" 的稳定 id。
    """
    key = f"{ts}::{title}"
    return f"{ts}::{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"
