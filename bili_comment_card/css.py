"""渲染所用 CSS（{font} 与主题色由 render._CSS.format 注入）。"""

_CSS = """
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{background:transparent}}
body{{width:{bg_w}px;background:transparent;font-family:"{font}","Noto Sans CJK SC",sans-serif;
  padding:36px 40px;-webkit-font-smoothing:antialiased}}
.card{{background:{card};border:1px solid {border};border-radius:16px;
  padding:30px 32px;margin-bottom:24px;box-shadow:0 4px 16px rgba(0,0,0,.05)}}
.ctitle{{font-size:15px;color:{meta};margin-bottom:18px;letter-spacing:.5px}}
.c{{display:flex;gap:16px}}
.c+.c{{margin-top:26px}}
.ava{{width:54px;height:54px;border-radius:50%;flex:none;object-fit:cover;
  background:{border}}}
.body{{flex:1;min-width:0}}
.head{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.name{{font-size:16px;font-weight:600;color:{name}}}
.lv{{height:1em;vertical-align:-0.15em;margin-right:4px}}
.up{{width:24px;height:24px;vertical-align:-7px}}
.tag{{font-size:11px;font-weight:700;padding:1px 7px;border-radius:4px;
  color:{accent};border:1px solid {accent}}}
.text{{font-size:17px;line-height:1.75;color:{text};word-wrap:break-word;
  white-space:pre-wrap}}
.em{{height:24px;vertical-align:-6px;margin:0 2px}}
.mention{{color:{accent}}}
.pics{{margin-top:10px;display:flex;flex-wrap:wrap;gap:8px}}
.pic{{max-width:240px;max-height:240px;border-radius:10px;
  border:1px solid {border};object-fit:cover}}
.meta{{margin-top:8px;display:flex;gap:22px;align-items:center;
  font-size:13px;color:{meta}}}
.act{{display:inline-flex;align-items:center;gap:5px}}
.act i{{font-style:normal}}
.i{{width:17px;height:17px;display:block}}
.nested{{margin-top:14px;background:transparent;border-radius:0;
  padding:0}}
.nested .c{{gap:10px;align-items:flex-start}}
.nested .c+.c{{margin-top:10px;padding-top:0;border-top:none}}
.nested .ava{{width:24px;height:24px}}
.nested .lv{{height:0.85em;vertical-align:-0.1em;margin-right:0}}
.nested .body{{padding-top:1px}}
.rtext{{font-size:15px;line-height:1.7;color:{text};word-wrap:break-word}}
.rtext .name{{font-size:15px;font-weight:400;color:{meta}}}
.nested .meta{{margin-top:2px;font-size:12px;gap:18px}}
.nested .em{{height:18px;vertical-align:-4px}}
"""
