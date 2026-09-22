# -*- coding: utf-8 -*-
"""作者国籍判定。

设计取向：**不依赖任何在线数据源**，直接按文件名中的
国家标记（如 `[英]阿加莎·克里斯蒂.pdf`）本地解析，秒级完成、无风控风险。
无标记或标记无法识别时判定为中国。"""

import os
import re


_NATIONALITY_MAP = {
    # 双字及以上（精确）
    "印度尼西亚": "印度尼西亚", "沙特阿拉伯": "沙特阿拉伯", "白俄罗斯": "白俄罗斯",
    "哈萨克斯坦": "哈萨克斯坦", "孟加拉国": "孟加拉国", "斯里兰卡": "斯里兰卡",
    "新加坡": "新加坡", "马来西亚": "马来西亚", "菲律宾": "菲律宾",
    "巴基斯坦": "巴基斯坦", "阿富汗": "阿富汗", "委内瑞拉": "委内瑞拉",
    "哥伦比亚": "哥伦比亚", "阿根廷": "阿根廷", "澳大利亚": "澳大利亚",
    "新西兰": "新西兰", "加拿大": "加拿大", "爱尔兰": "爱尔兰",
    "冰岛": "冰岛", "瑞典": "瑞典", "挪威": "挪威", "丹麦": "丹麦",
    "芬兰": "芬兰", "瑞士": "瑞士", "奥地利": "奥地利", "波兰": "波兰",
    "捷克": "捷克", "匈牙利": "匈牙利", "罗马尼亚": "罗马尼亚",
    "保加利亚": "保加利亚", "乌克兰": "乌克兰", "希腊": "希腊",
    "土耳其": "土耳其", "以色列": "以色列", "印度": "印度",
    "伊朗": "伊朗", "伊拉克": "伊拉克", "叙利亚": "叙利亚",
    "越南": "越南", "泰国": "泰国", "缅甸": "缅甸",
    "巴西": "巴西", "智利": "智利", "秘鲁": "秘鲁",
    "墨西哥": "墨西哥", "古巴": "古巴", "南非": "南非", "埃及": "埃及",
    "肯尼亚": "肯尼亚", "尼日利亚": "尼日利亚",
    "葡萄牙": "葡萄牙", "比利时": "比利时", "塞尔维亚": "塞尔维亚",
    "克罗地亚": "克罗地亚", "斯洛文尼亚": "斯洛文尼亚",
    "爱沙尼亚": "爱沙尼亚", "拉脱维亚": "拉脱维亚", "立陶宛": "立陶宛",
    "埃塞俄比亚": "埃塞俄比亚", "摩洛哥": "摩洛哥", "尼泊尔": "尼泊尔",
    "蒙古": "蒙古", "乌拉圭": "乌拉圭", "厄瓜多尔": "厄瓜多尔",
    "玻利维亚": "玻利维亚", "牙买加": "牙买加", "加纳": "加纳",
    "塞内加尔": "塞内加尔", "突尼斯": "突尼斯", "阿尔及利亚": "阿尔及利亚",
    "苏丹": "苏丹", "乌干达": "乌干达", "坦桑尼亚": "坦桑尼亚",
    "津巴布韦": "津巴布韦", "赞比亚": "赞比亚", "安哥拉": "安哥拉",
    "莫桑比克": "莫桑比克", "喀麦隆": "喀麦隆", "刚果": "刚果",
    "哥伦比亚": "哥伦比亚", "爱沙尼亚": "爱沙尼亚",
    # 单字（常用）
    "中": "中国", "美": "美国", "英": "英国", "法": "法国", "德": "德国",
    "日": "日本", "韩": "韩国", "俄": "俄罗斯", "意": "意大利", "西": "西班牙",
    "荷": "荷兰", "挪": "挪威", "丹": "丹麦", "芬": "芬兰", "瑞": "瑞典",
    "波": "波兰", "捷": "捷克", "匈": "匈牙利", "奥": "奥地利", "比": "比利时",
    "葡": "葡萄牙", "希": "希腊", "墨": "墨西哥", "古": "古巴", "加": "加拿大",
    "澳": "澳大利亚", "新": "新西兰", "以": "以色列", "印": "印度", "巴": "巴西",
    "泰": "泰国", "越": "越南", "缅": "缅甸", "菲": "菲律宾", "马": "马来西亚",
}


def _parse_nationality(author_line):
    """从豆瓣作者行提取国籍，如「[挪] 格德·布兰腾伯格」→ 挪威；无标记返回 ''。"""
    try:
        m = re.search(r"\[([^\]]+)\]", author_line or "")
        if not m:
            return ""
        tag = m.group(1).strip()
        for k in sorted(_NATIONALITY_MAP, key=len, reverse=True):
            if tag == k or tag.startswith(k):
                return _NATIONALITY_MAP[k]
    except Exception:
        pass
    return ""


def nationality_from_filename(file_path):
    """
    从书籍文件名解析作者国籍（本地规则，不联网）：
    - 文件名含 [xx] 且 xx 能匹配国籍缩写 → 对应国籍
      （如「[英]阿加莎·克里斯蒂 - 东方快车谋杀案.pdf」→ 英国）
    - 无 [xx] 或标记无法识别 → 中国
    """
    try:
        fname = os.path.basename((file_path or "").replace("\\", "/"))
        m = re.search(r"\[([^\]]+)\]", fname)
        if not m:
            return "中国"
        tag = m.group(1).strip()
        for k in sorted(_NATIONALITY_MAP, key=len, reverse=True):
            if tag == k or tag.startswith(k):
                return _NATIONALITY_MAP[k]
    except Exception:
        pass
    return "中国"


def _count_nationalities(data):
    """统计各国籍书籍数量（有国籍的书），按数量降序。"""
    counts = {}
    for b in data["books"]:
        n = (b.get("author_nationality") or "").strip()
        if n:
            counts[n] = counts.get(n, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


def _nat_stats(data):
    """作者国籍汇总数据（供「工具合集」页展示）。"""
    books = data["books"]
    with_author = [b for b in books if b.get("author")]
    filled = [b for b in with_author
              if (b.get("author_nationality") or "").strip()]
    return {"total": len(books), "with_author": len(with_author),
            "filled": len(filled),
            "pending": len(with_author) - len(filled),
            "counts": _count_nationalities(data)}
