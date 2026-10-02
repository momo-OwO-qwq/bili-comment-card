"""命令行入口。

示例：
  python3 -m bili_comment_card "https://t.bilibili.com/1119499641096765447"
  python3 -m bili_comment_card "https://www.bilibili.com/video/BV1xx411c7mD" --theme light
  python3 -m bili_comment_card <url> --single 3 --font "Noto Serif CJK SC"
"""
import argparse
import os
import re
import sys

from . import api, render
from .render import THEMES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def list_fonts():
    import subprocess
    out = subprocess.run(["fc-list", ":lang=zh", "family"],
                         capture_output=True, text=True).stdout
    fams = sorted({x.strip() for line in out.splitlines()
                   for x in line.split(",") if x.strip()})
    for f in fams:
        print(" ", f)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="bili_comment_card",
        description="把 B 站动态/视频的评论渲染成图片（明暗主题、字体、"
                    "时间戳与图标均可配置）。")
    p.add_argument("url", nargs="?", help="动态链接 t.bilibili.com/… 或视频 BV/av 链接")
    p.add_argument("--theme", choices=sorted(THEMES), default="dark",
                   help="主题风格（默认 dark）")
    p.add_argument("--font", default="Noto Sans CJK SC",
                   help="字体族名（默认 Noto Sans CJK SC）")
    p.add_argument("--list-fonts", action="store_true", help="列出可用中文字体")
    p.add_argument("--no-time", action="store_true", help="不显示时间戳")
    p.add_argument("--no-like", action="store_true", help="不显示点赞图标")
    p.add_argument("--no-reply", action="store_true", help="不显示回复数图标")
    p.add_argument("--share", action="store_true", help="显示转发图标（默认隐藏）")
    p.add_argument("--single", type=int, metavar="N",
                   help="只渲染第 N 条评论（1 起）；不加则整页全部评论")
    p.add_argument("--no-replies", action="store_true", help="忽略楼中楼")
    p.add_argument("--numbered", action="store_true", help="卡片上显示第几条评论")
    p.add_argument("--limit", type=int, help="最多抓取的根评论数（调试用）")
    p.add_argument("--width", type=int, default=760, help="卡片宽度像素（默认 760）")
    p.add_argument("--scale", type=int, default=3, choices=(2, 3, 4),
                   help="分辨率倍率（默认 3，进视频更清晰）")
    p.add_argument("--out", default=os.path.join(ROOT, "output"),
                   help="输出目录")
    a = p.parse_args(argv)

    if a.list_fonts:
        list_fonts()
        return 0
    if not a.url:
        p.error("缺少 URL（或使用 --list-fonts 查看字体）")

    kind, ident = api.parse_target(a.url)
    print(f"[1/3] 目标：{kind} {ident} …")
    source = api.fetch_source(kind, ident)
    print(f"[2/3] 已获取（{source['author']} · {source['reply']} 条评论），拉取评论 …")
    comments = api.fetch_comments(source,
                                  with_replies=not a.no_replies, limit=a.limit)
    if a.single:
        if not 1 <= a.single <= len(comments):
            print(f"序号超出范围（共 {len(comments)} 条）", file=sys.stderr)
            return 2
        comments = [comments[a.single - 1]]
    print(f"[3/3] 渲染 {len(comments)} 张卡片（{a.theme} 主题）…")

    opt = render.Options(
        theme=a.theme, font=a.font,
        show_time=not a.no_time, show_like=not a.no_like,
        show_reply=not a.no_reply, show_share=a.share,
        width=a.width, scale=a.scale)
    os.makedirs(a.out, exist_ok=True)
    label = "动态" if kind == "dynamic" else "视频"

    if a.single:
        # 单条卡片：不重复带主动态头
        page = render.build_html(source, comments, opt,
                                 numbered=a.numbered, with_header=False)
        out = os.path.join(a.out, f"{label}{ident}-评论{a.single:02d}.png")
        render.screenshot(page, out, opt)
        print(f"完成：{out}")
        return 0

    # 全量：长图（含主动态头概览）+ 逐条单卡（不带主动态头）
    page = render.build_html(source, comments, opt, numbered=a.numbered)
    whole = os.path.join(a.out, f"{label}{ident}-全部评论.png")
    render.screenshot(page, whole, opt)
    print(f"完成（长图）：{whole}")
    for i, c in enumerate(comments, 1):
        sub = render.build_html(source, [c], opt, numbered=a.numbered,
                                with_header=False)
        out = os.path.join(a.out, f"{label}{ident}-评论{i:02d}.png")
        render.screenshot(sub, out, opt)
        print(f"完成：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
