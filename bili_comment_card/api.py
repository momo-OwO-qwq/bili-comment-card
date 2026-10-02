"""B 站评论数据抓取：动态与视频两种来源。

只使用公开接口，不需要 Cookie；头像与表情会缓存到项目 cache/ 目录。
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")


_RETRY_CODES = {-352, -412, -504, 412}


_BUVID_COOKIE = None          # spi 官方匿名 Cookie，懒加载


def _buvid_cookie():
    """取 B 站官方匿名 buvid Cookie（finger/spi），失败返回 ''。

    经验：seek_rpid 带官方匿名 Cookie 才能在风控期命中（实测 11:06 成功
    路径即如此）；但全量分页接口带 Cookie 反而降级只回 3 条，所以 Cookie
    仅用于锚点直达，不进全量抓取。自造 Cookie 一律不用。
    """
    global _BUVID_COOKIE
    if _BUVID_COOKIE:
        return _BUVID_COOKIE
    try:
        req = urllib.request.Request(
            "https://api.bilibili.com/x/frontend/finger/spi",
            headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        _BUVID_COOKIE = (f"buvid3={d['data']['b_3']}; "
                         f"buvid4={d['data']['b_4']}")
    except Exception:
        _BUVID_COOKIE = ""
    return _BUVID_COOKIE


def _get(url, referer="https://www.bilibili.com/", retries=3, with_cookie=False):
    """带风控重试的 GET。

    经验：
    - -352 是 IP 级临时风控，重试太长只会让用户以为「卡死」，
      默认 3 次、退避封顶 8s，快速给出明确报错；
    - with_cookie=True 仅锚点直达使用（spi 官方匿名 buvid）；
      全量分页带 Cookie 会降级只回 3 条，故不带。
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
            **({"Cookie": _buvid_cookie()} if with_cookie else {}),
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

def parse_anchor(s):
    """提取链接锚点里的目标评论 rpid（如 ...#reply315705541057）。

    没有锚点返回 None；存在锚点返回 int rpid。
    """
    m = re.search(r"#reply(\d+)", s or "")
    return int(m.group(1)) if m else None


def find_comment(comments, rpid):
    """按 rpid 定位评论，支持楼中楼子评论。

    返回 (comment, is_child)；未找到返回 (None, False)。
    """
    for c in comments:
        if c["rpid"] == rpid:
            return c, False
        for ch in c.get("children") or []:
            if ch["rpid"] == rpid:
                return ch, True
    return None, False


def _source_cache_path(kind, ident):
    return os.path.join(CACHE, "source", f"{kind}_{ident}.json")


def fetch_source(kind, ident):
    """来源信息，带本地缓存回落。

    经验：-352 风控会封动态详情接口；成功抓过一次就落盘，之后接口
    不可用时用缓存兜底（正文/作者/oid 不常变），配合锚点直达可在
    风控期继续出图。
    """
    path = _source_cache_path(kind, ident)
    try:
        src = _fetch_source_live(kind, ident)
    except Exception as e:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                src = json.load(f)
            print(f"  ⓘ 来源接口不可用（{e}），使用本地缓存",
                  file=sys.stderr, flush=True)
            return src
        raise
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(src, f, ensure_ascii=False, indent=1)
    except Exception:
        pass                        # 缓存写失败不影响主流程
    return src


def _fetch_source_live(kind, ident):
    """实时抓取来源信息（无缓存）。"""
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


def fetch_comment_by_anchor(source, rpid, with_replies=True):
    """锚点直达：用 seek_rpid 单点拉取目标评论。

    经验（-352 风控期实战）：全量分页接口被封时，seek_rpid 往往仍可用
    ——它是网页点 #reply 锚点跳转的底层机制，一次请求直接返回目标评论
    所在位置，不依赖全量列表。返回归一化后的单条评论 dict。

    失败时抛 RuntimeError，调用方可回退到全量抓取 + find_comment。
    """
    referer = (f"https://t.bilibili.com/{source['id']}"
               if source["kind"] == "dynamic" else
               f"https://www.bilibili.com/video/{source['id']}")
    q = urllib.parse.quote(json.dumps({"offset": ""}))
    d = _get("https://api.bilibili.com/x/v2/reply/main"
             f"?oid={source['oid']}&type={source['ctype']}&mode=3"
             f"&pagination_str={q}&seek_rpid={rpid}"
             "&web_location=333.1387", referer=referer, retries=2,
             with_cookie=True)
    if d.get("code") != 0:
        raise RuntimeError(f"seek_rpid 失败：{d.get('code')} {d.get('message')}")
    data = d.get("data") or {}
    pool = (data.get("top_replies") or []) + (data.get("replies") or [])
    # 目标是根评论
    for r in pool:
        if r["rpid"] == rpid:
            subs = (_fetch_sub_replies(source, r, r.get("replies"))
                    if with_replies else [])
            return _norm(r, source, subs)
    # 目标是楼中楼子评论（挂在某根评论的 replies 里）
    for r in pool:
        for ch in (r.get("replies") or []):
            if ch["rpid"] == rpid:
                return _norm(ch, source)
    raise RuntimeError(f"seek_rpid 未找到目标评论 {rpid}")


def fetch_comments(source, with_replies=True, limit=None):
    """产出评论结构列表（已归一化，方便渲染层直接使用）。"""
    roots = _walk_roots(source, limit=limit)
    out = []
    for r in roots:
        subs = _fetch_sub_replies(source, r, r.get("replies")) if with_replies else []
        out.append(_norm(r, source, subs))
    return out


def _norm(c, source, subs=None):
    """归一化评论（根评论与楼中楼子评论通用）。

    subs：根评论补全后的楼中楼列表（子评论传 None/[]）。
    """
    is_root = subs is not None
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
        "reply": c.get("rcount", 0) if is_root else 0,
        "share": c.get("count", 0) if is_root else 0,
        # 经验：配图字段是 pictures[].img_src（不是 pics[].url，错用会漏图）
        "pics": [p.get("img_src") for p in
                 (c["content"].get("pictures") or []) if p.get("img_src")],
        "children": [_norm(x, source) for x in (subs or [])],
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
