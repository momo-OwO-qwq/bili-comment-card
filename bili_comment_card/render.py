"""HTML 模板 + chromium 截图：把评论渲染成图片。

主题（dark/light）、字体、时间戳与图标开关都在这里生效。
"""
import html as html_mod
import json
import os
import re
import subprocess
import tempfile
import time

from PIL import Image

from . import api
from .css import _CSS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

# ---------------------------------------------------------------------------
# 主题：对齐 B 站网页明/暗两种配色
# ---------------------------------------------------------------------------
THEMES = {
    "dark": {
        "bg": "#18191c", "card": "#1f2023", "border": "#2f3033",
        "text": "#e3e5e7", "name": "#e3e5e7", "meta": "#99a2aa",
        "dim": "#61666d", "nested": "#232427", "dash": "#34363b",
        "accent": "#00a1d6", "vip": "#fb7299", "pad": (24, 25, 28),
    },
    "light": {
        "bg": "#f1f2f3", "card": "#ffffff", "border": "#e3e5e7",
        "text": "#18191c", "name": "#61666d", "meta": "#99a2aa",
        "dim": "#c9cdd4", "nested": "#f6f7f8", "dash": "#e3e5e7",
        "accent": "#00a1d6", "vip": "#fb7299", "pad": (241, 242, 243),
    },
}

# ---------------------------------------------------------------------------
# 原版图标（B 站 svg-next 矢量数据）
# ---------------------------------------------------------------------------
_ICON_CACHE = {}


def _icon_paths(name):
    if name not in _ICON_CACHE:
        p = os.path.join(ASSETS, "icons", f"{name}.json")
        with open(p, encoding="utf-8") as f:
            _ICON_CACHE[name] = json.load(f)["default"]
    return _ICON_CACHE[name]


def icon_svg(name, color, cls="i"):
    """生成内联 SVG（viewBox 0 0 24 24，stroke 风格原版矢量）。"""
    paths = "".join(
        f'<path d="{d}"/>' for d in (_icon_paths(name)
                                     if isinstance(_icon_paths(name), list)
                                     else [_icon_paths(name)])
    )
    return (f'<svg class="{cls}" viewBox="0 0 24 24" fill="{color}" '
            f'xmlns="http://www.w3.org/2000/svg">{paths}</svg>')


def level_svg(lv):
    return os.path.join(ASSETS, "level", "fit", f"level_{lv}.svg")


# ---------------------------------------------------------------------------
# 文本渲染
# ---------------------------------------------------------------------------

def _esc(s):
    return html_mod.escape(s, quote=False)


def _render_text(comment):
    """把 [doge] 这类表情 token 替换为缓存后的表情图片。

    经验：表情下载失败时退回显示原始 [token] 文本，绝不产出裂图。
    """
    msg = comment.get("text", "")
    em = comment.get("emote") or {}
    out, i = [], 0
    pat = re.compile(r"\[[^\[\]\s]{1,12}\]")
    mpat = re.compile(r"@[^\s@:：]+")          # @昵称 → B站蓝
    while i < len(msg):
        if msg[i] == "@":
            m = mpat.match(msg, i)
            if m:
                out.append(f'<span class="mention">{_esc(m.group())}</span>')
                i = m.end()
                continue
        m = pat.match(msg, i)
        if m and m.group() in em:
            path = api.cache_emote(em[m.group()].get("url", ""))
            if path:
                out.append(f'<img class="em" src="file://{path}">')
                i = m.end()
                continue
        out.append(_esc(msg[i]))
        i += 1
    return "".join(out)


def _pics_html(comment):
    """评论配图（content.pictures[].img_src）：下载缓存后以缩略图网格展示。"""
    urls = comment.get("pics") or []
    if not urls:
        return ""
    imgs = []
    for u in urls:
        p = api.cache_pic(u)
        if p:
            imgs.append(f'<img class="pic" src="file://{p}">')
    if not imgs:
        return ""
    return '<div class="pics">' + "".join(imgs) + "</div>"


def _fmt_time(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


# ---------------------------------------------------------------------------
# 卡片
# ---------------------------------------------------------------------------

class Options:
    """渲染选项（由 CLI 填充）。"""

    def __init__(self, theme="dark", font="Noto Sans CJK SC",
                 show_time=True, show_like=True, show_reply=True,
                 show_share=False, width=760, scale=3):
        # 经验：3 倍分辨率（2x 进视频仍显糊），pad 换算见 _crop_alpha
        self.theme = theme
        self.font = font
        self.show_time = show_time
        self.show_like = show_like
        self.show_reply = show_reply
        self.show_share = show_share
        self.width = width
        self.scale = scale


def _meta_row(c, opt, t):
    items = []
    if opt.show_time:
        items.append(f"<span>{_fmt_time(c['ctime'])}</span>")
    if opt.show_like:
        color = t["meta"]
        items.append(
            f'<span class="act">{icon_svg("hand_thumbsup_line", color)}'
            f'<i>{c["like"] or ""}</i></span>')
    if opt.show_reply and c.get("reply"):
        items.append(
            f'<span class="act">{icon_svg("bubble_comment_line", color)}'
            f'<i>{c["reply"]}</i></span>')
    if opt.show_share and c.get("share"):
        items.append(
            f'<span class="act">{icon_svg("arrow_share_line", color)}'
            f'<i>{c["share"]}</i></span>')
    if not items:
        return ""
    return '<div class="meta">' + "".join(items) + "</div>"


def _badges(c, t):
    out = []
    if c.get("level"):
        out.append(f'<img class="lv" src="file://{level_svg(c["level"])}">')
    # 经验：不显示大会员标（主人要求）
    if c.get("is_up"):
        out.append(f'<img class="up" src="file://{ASSETS}/up_pb.svg">')
    return "".join(out)


def _comment_html(c, opt, t, nested=False):
    avatar = api.cache_avatar(c["avatar"]) or ""
    src = f' src="file://{avatar}"' if avatar else ""
    inner = (f'<div class="head"><span class="name">{_esc(c["name"])}</span>'
             f'{_badges(c, t)}</div>'
             f'<div class="text">{_render_text(c)}</div>'
             f'{_pics_html(c)}'
             f'{_meta_row(c, opt, t)}')
    kids = ""
    if c.get("children") and not nested:
        kids = ('<div class="nested">' +
                "".join(_comment_html(k, opt, t, nested=True)
                        for k in c["children"]) + "</div>")
    return (f'<div class="c"><img class="ava"{src}>'
            f'<div class="body">{inner}{kids}</div></div>')


def _header_html(src, opt, t):
    avatar = api.cache_avatar(src["avatar"]) or ""
    badge = f'<img class="up" src="file://{ASSETS}/up_pb.svg">' if src.get("is_up") else ""
    meta = []
    if opt.show_time and src.get("ctime"):
        meta.append(f"<span>{_fmt_time(src['ctime'])}</span>")
    if opt.show_like and src.get("like") is not None:
        meta.append(f'<span class="act">{icon_svg("hand_thumbsup_line", t["meta"])}'
                    f'<i>{src.get("like") or ""}</i></span>')
    if opt.show_share and src.get("share"):
        meta.append(f'<span class="act">{icon_svg("arrow_share_line", t["meta"])}'
                    f'<i>{src["share"]}</i></span>')
    if opt.show_reply and src.get("reply"):
        meta.append(f'<span class="act">{icon_svg("bubble_comment_line", t["meta"])}'
                    f'<i>{src["reply"]}</i></span>')
    label = "动态" if src["kind"] == "dynamic" else "视频"
    return (f'<div class="c"><img class="ava" src="file://{avatar}">'
            f'<div class="body"><div class="head"><span class="name">'
            f'{_esc(src["author"])}</span>{badge}'
            f'<span class="tag">{label}</span></div>'
            f'<div class="text">{_esc(src["text"])}</div>'
            + (f'<div class="meta">{"".join(meta)}</div>' if meta else "")
            + "</div></div>")


def build_html(source, comments, opt, numbered=False, with_header=True):
    """with_header=False：单条卡片不带主动态头（长图概览才显示）。"""
    t = THEMES[opt.theme]
    cards = []
    if with_header:
        cards.append(f'<div class="card">{_header_html(source, opt, t)}</div>')
    total = len(comments)
    for i, c in enumerate(comments, 1):
        title = f'<div class="ctitle">评论 {i} / {total}</div>' if numbered else ""
        cards.append(f'<div class="card">{title}{_comment_html(c, opt, t)}</div>')
    css = _CSS.format(font=opt.font, bg_w=opt.width + 80, **t)
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<style>{css}</style></head><body>{"".join(cards)}</body></html>')


# ---------------------------------------------------------------------------
# 截图与裁剪
# ---------------------------------------------------------------------------

def screenshot(html_text, out_png, opt):
    """chromium 渲染整页并裁剪，返回输出路径。

    经验：
    - 透明框外底色（--default-background-color=00000000）+ alpha 裁边
    - 固定窗口高度会截断长卡（楼中楼多的评论），内容触底时自动加倍
      窗口高度重渲，直到不截断（或达到上限）
    """
    t = THEMES[opt.theme]
    with tempfile.TemporaryDirectory() as td:
        page = os.path.join(td, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(html_text)
        w = opt.width + 80
        win_h = 1200
        for attempt in range(4):
            raw = os.path.join(td, "raw.png")
            subprocess.run(
                ["chromium", "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--hide-scrollbars", f"--force-device-scale-factor={opt.scale}",
                 "--default-background-color=00000000",
                 f"--window-size={w},{win_h}", f"--screenshot={raw}", page],
                capture_output=True, timeout=180, check=True)
            im = Image.open(raw).convert("RGBA")
            bbox = _alpha_bbox(im)
            if not bbox:
                break
            truncated = bbox[3] >= im.height - 4
            if truncated and attempt < 3:
                win_h = min(win_h * 2, 16000)   # 触底 → 加倍窗口高度重渲
                continue
            _crop_alpha(im, out_png, bbox, scale=opt.scale)
            break
    return out_png


def _alpha_bbox(im):
    """按 alpha>8 计算非透明内容边界。"""
    return im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()


def _crop_alpha(im, dst, bbox, pad=None, scale=3):
    """透明底裁边：裁到内容边界外加 padding（按倍率换算，保持 CSS 观感一致）。"""
    if pad is None:
        pad = int(28 * scale)        # 28 CSS px × 倍率（3x=84, 2x=56）
    l, top, r, b = bbox
    w, h = im.size
    im.crop((max(0, l - pad), max(0, top - pad),
             min(w, r + pad), min(h, b + pad))).save(dst)
