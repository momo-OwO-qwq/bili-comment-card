"""B 站评论数据抓取：动态与视频两种来源。

只使用公开接口，不需要 Cookie；头像与表情会缓存到项目 cache/ 目录。
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")


_RETRY_CODES = {-352, -412, -504, 412}


def _get(url, referer="https://www.bilibili.com/", retries=3):
    """带风控重试的 GET。

    经验：
    - -352 是 IP 级临时风控，重试太长只会让用户以为「卡死」，
      默认 3 次、退避封顶 8s，快速给出明确报错；
    - 自造 Cookie 会触发降级（详情仍 -352、评论只回 3 条），不用。
    进度输出到 stderr 并 flush，保证用户能看到卡在哪。
    """
    import sys
    import time as _time
    last = None
    for attempt in range(retries):
        if attempt:
            wait = min(2 ** attempt, 8)
            print(f"  ⚠ 接口风控重试 {attempt + 1}/{retries}（{wait}s 后重试）…",
                  file=sys.stderr, flush=True)
            _time.sleep(wait)
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:          # 网络层错误也重试
            last = e
            continue
        if data.get("code") in _RETRY_CODES:
            last = RuntimeError(f"{data.get('code')} {data.get('message')}")
            continue
        if data.get("code") != 0:
            raise RuntimeError(f"接口返回 {data.get('code')}：{data.get('message')}")
        return data
    if last is None:
        last = RuntimeError("接口无响应")
    raise RuntimeError(
        f"请求失败（{last}）：B 站可能对该 IP 触发了临时风控（-352/-412）。"
        "这不是卡死——风控通常几分钟到几小时恢复，稍后重试即可；"
        "或换网络/热点再试。") from last


# --------------------------------------------------------------------------
# 目标解析
# --------------------------------------------------------------------------

def parse_target(s):
    """把 URL / 纯 ID 解析为 ('dynamic', id) 或 ('video', bvid)。"""
    s = s.strip()
    m = re.search(r"bilibili\.com/opus/(\d+)", s)
    if m:
        return "dynamic", m.group(1)
    m = re.search(r"t\.bilibili\.com/(\d+)", s)
    if m:
        return "dynamic", m.group(1)
    m = re.search(r"/video/(av(\d+)|(BV[0-9A-Za-z]+))", s, re.I)
    if m:
        # BV 号大小写敏感，保持原样
        return "video", (f"av{m.group(2)}" if m.group(2) else m.group(3))
    if re.fullmatch(r"\d{15,}", s):          # 长数字当作动态 ID
        return "dynamic", s
    if re.fullmatch(r"BV[0-9A-Za-z]+", s):   # BV 号大小写敏感
        return "video", s
    if re.fullmatch(r"av\d+", s, re.I):
        return "video", "av" + s[2:]
    raise ValueError(f"无法识别的地址：{s}（支持 t.bilibili.com 动态、视频 BV/av 链接）")


# --------------------------------------------------------------------------
# 来源信息
# --------------------------------------------------------------------------

def fetch_source(kind, ident):
    """返回 source 描述 dict：动态拿正文，视频拿标题。"""
    if kind == "dynamic":
        d = _get("https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
                 f"?id={ident}")
        if d.get("code") != 0:
            raise RuntimeError(f"动态获取失败：{d.get('code')} {d.get('message')}")
        item = d["data"]["item"]
        author = item["modules"]["module_author"]
        stat = item["modules"].get("module_stat") or {}
        desc = (item["modules"]["module_dynamic"].get("desc") or {}).get("text", "")
        return {
            "kind": "dynamic",
            "id": ident,
            "author": author.get("name") or author.get("uname") or "",
            "avatar": author.get("face") or author.get("avatar") or "",
            "is_up": True,
            "text": desc,
            "ctime": author.get("pub_ts") or author.get("publish_time"),
            "like": (stat.get("like") or {}).get("count", 0),
            "reply": (stat.get("comment") or {}).get("count", 0),
            "share": (stat.get("forward") or {}).get("count", 0),
            "oid": item["basic"]["comment_id_str"],      # 评论区 oid
            "ctype": item["basic"]["comment_type"],      # 评论区 type
            "title": None,
        }
    # 视频
    if ident.startswith("av"):
        url = f"https://api.bilibili.com/x/web-interface/view?aid={ident[2:]}"
    else:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={ident}"
    d = _get(url)
    if d.get("code") != 0:
        raise RuntimeError(f"视频获取失败：{d.get('code')} {d.get('message')}")
    data = d["data"]
    stat = data["stat"]
    return {
        "kind": "video",
        "id": ident,
        "author": data["owner"]["name"],
        "avatar": data["owner"]["face"],
        "is_up": True,
        "text": data["title"],
        "ctime": data["ctime"],
        "like": stat.get("like", 0),
        "reply": stat.get("reply", 0),
        "share": stat.get("share", 0),
        "oid": str(data["aid"]),
        "ctype": 1,
        "title": data["title"],
    }


# --------------------------------------------------------------------------
# 评论分页
# --------------------------------------------------------------------------

def _walk_roots(source, limit=None):
    """动态/视频统一走 reply/main 游标分页，产出根评论列表。"""
    ctype, oid = source["ctype"], source["oid"]
    referer = (f"https://t.bilibili.com/{source['id']}"
               if source["kind"] == "dynamic" else
               f"https://www.bilibili.com/video/{source['id']}")
    roots, pages, offset = [], 0, ""
    while True:
        q = urllib.parse.quote(json.dumps({"offset": offset}))
        d = _get("https://api.bilibili.com/x/v2/reply/main"
                 f"?oid={oid}&type={ctype}&mode=3&pagination_str={q}"
                 "&web_location=333.1387", referer=referer)
        if d.get("code") != 0:
            raise RuntimeError(f"评论获取失败：{d.get('code')} {d.get('message')}")
        data = d["data"]
        for r in data.get("replies") or []:
            roots.append(r)
        for r in data.get("top_replies") or []:
            if all(x["rpid"] != r["rpid"] for x in roots):
                roots.insert(0, r)
        pages += 1
        cur = data.get("cursor") or {}
        if cur.get("is_end") or not data.get("replies") or pages > 100:
            break
        offset = cur.get("pagination_reply", {}).get("next_offset", "")
        if not offset:
            break
        if limit and len(roots) >= limit:
            break
        time.sleep(0.25)
    if limit:
        roots = roots[:limit]
    return roots


def _fetch_sub_replies(source, root, shown):
    """补全楼中楼（经验：根评论 replies 只带前几条，必须按 rcount 分页拉满）。

    - 分页循环直到拿满 rcount 或无更多数据（单页 ps=20）
    - 与根评论自带的前几条去重、按 ctime 排序（与 B 站展示一致）
    """
    rcount = root.get("rcount", 0)
    subs = list(shown or [])
    if rcount <= len(subs):
        return subs
    have = {x["rpid"] for x in subs}
    pn = 1
    while len(subs) < rcount and pn <= 20:
        url = ("https://api.bilibili.com/x/v2/reply/reply"
               f"?type={source['ctype']}&oid={source['oid']}"
               f"&root={root['rpid']}&ps=20&pn={pn}")
        try:
            d = _get(url)
        except Exception:
            break
        if d.get("code") != 0:
            break
        batch = d["data"].get("replies") or []
        for b in batch:
            if b["rpid"] not in have:
                have.add(b["rpid"])
                subs.append(b)
        if len(batch) < 20:
            break
        pn += 1
        time.sleep(0.3)
    subs.sort(key=lambda x: x["ctime"])
    return subs


def fetch_comments(source, with_replies=True, limit=None):
    """产出评论结构列表（已归一化，方便渲染层直接使用）。"""
    roots = _walk_roots(source, limit=limit)
    out = []
    for r in roots:
        subs = _fetch_sub_replies(source, r, r.get("replies")) if with_replies else []
        out.append({
            "rpid": r["rpid"],
            "mid": r["member"]["mid"],
            "name": r["member"]["uname"],
            "avatar": r["member"]["avatar"],
            "level": (r["member"].get("level_info") or {}).get("current_level", 0),
            "vip": (r["member"].get("vip") or {}).get("vipStatus", 0) == 1,
            "is_up": r["member"]["mid"] == 0,      # 占位，渲染层用 source 判断
            "text": r["content"]["message"],
            "emote": r["content"].get("emote") or {},
            "ctime": r["ctime"],
            "like": r.get("like", 0),
            "reply": r.get("rcount", 0),
            "share": r.get("count", 0),            # 动态评论无转发数时为 0
            # 经验：配图字段是 pictures[].img_src（不是 pics[].url，错用会漏图）
            "pics": [p.get("img_src") for p in
                     (r["content"].get("pictures") or []) if p.get("img_src")],
            "children": [_norm(c, source) for c in (subs or [])],
        })
    return out


def _norm(c, source):
    return {
        "rpid": c["rpid"],
        "mid": c["member"]["mid"],
        "name": c["member"]["uname"],
        "avatar": c["member"]["avatar"],
        "level": (c["member"].get("level_info") or {}).get("current_level", 0),
        "vip": (c["member"].get("vip") or {}).get("vipStatus", 0) == 1,
        "is_up": c["member"]["mid"] == 0,
        "text": c["content"]["message"],
        "emote": c["content"].get("emote") or {},
        "ctime": c["ctime"],
        "like": c.get("like", 0),
        "reply": 0,
        "share": 0,
        # 经验：配图字段是 pictures[].img_src（不是 pics[].url，错用会漏图）
        "pics": [p.get("img_src") for p in
                 (c["content"].get("pictures") or []) if p.get("img_src")],
        "children": [],
    }


# --------------------------------------------------------------------------
# 资源缓存（头像 / 表情）
# --------------------------------------------------------------------------

def _download(url, subdir, retries=3):
    """下载并缓存图片资源。

    经验：hdslb CDN 偶发超时/412 会导致表情或配图缺失，加退避重试；
    下载失败不写空文件，避免坏缓存永久污染。
    """
    if url.startswith("//"):
        url = "https:" + url
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    key = re.sub(r"[^0-9A-Za-z._-]", "_", url[-90:])
    path = os.path.join(CACHE, subdir, key + ext)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": "https://www.bilibili.com/"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            if not data:
                raise IOError("empty body")
            with open(path, "wb") as f:
                f.write(data)
            return path
        except Exception:
            time.sleep(1 + attempt)
    return None


def cache_avatar(url):
    return _download(url, "faces")


def cache_emote(url):
    return _download(url, "emotes")


def cache_pic(url):
    return _download(url, "pics")
