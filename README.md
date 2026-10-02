# bili-comment-card

把 B 站**动态 / 视频**的评论渲染成图片。适配 UP 主读评论、评论区精选等场景。

- 样式对齐 B 站网页原生：官方头像、LV 等级徽章、大会员/UP 主标识、`[doge]` 等官方表情、点赞/回复/转发原版矢量图标
- 支持暗色 / 亮色两套 B 站主题、自定义字体、时间戳与各类图标开关
- 支持**整条动态/视频全部评论**（长图 + 逐条单卡）或**只出单条**

## 依赖

- Python 3.10+（仅标准库 + Pillow）
- Chromium（`chromium`，用于无头渲染截图）
- 系统中文字体（`fc-list :lang=zh` 可查）

```bash
sudo apt install chromium python3-pil   # 按需
```

## 用法

```bash
cd ~/Documents/bili-comment-card

# 动态：全部评论（长图 + 每条评论各一张单卡）
python3 -m bili_comment_card "<动态链接>"

# 视频：全部评论
python3 -m bili_comment_card "<视频链接>"

# 只出第 N 条评论（1 起）
python3 -m bili_comment_card <链接> --single 11

# 只出链接锚点指向的那条评论（支持 #reply<id> 楼中楼定位）
python3 -m bili_comment_card "<链接>#reply<评论id>"
```

### 常用选项

| 选项 | 说明 |
|---|---|
| `--theme dark\|light` | 主题风格（默认 dark） |
| `--font "字体族名"` | 正文与昵称字体，默认 `Noto Sans CJK SC` |
| `--list-fonts` | 列出系统可用中文字体 |
| `--no-time` | 不显示时间戳 |
| `--no-like` | 不显示点赞图标 |
| `--no-reply` | 不显示回复数图标 |
| `--share` | 显示转发图标（默认隐藏） |
| `--no-replies` | 忽略楼中楼 |
| `--numbered` | 卡片上显示「评论 N / 总数」 |
| `--limit N` | 最多抓取 N 条根评论（调试提速） |
| `--width 760` | 卡片宽度（像素） |
| `--scale 3` | 分辨率倍率（2/3/4，默认 3——进视频更清晰） |
| `--out 目录` | 输出目录，默认 `./output` |

示例组合：

```bash
# 亮色主题 + 宋体 + 隐藏时间戳
python3 -m bili_comment_card <链接> --theme light --font "Noto Serif CJK SC" --no-time

# 显示转发图标，并给卡片编号
python3 -m bili_comment_card <链接> --share --numbered
```

## 输出

输出到 `output/`（可用 `--out` 改）：

- `<来源><ID>-全部评论.png` — 所有评论合成的长图
- `<来源><ID>-评论01.png …` — 每条评论一张单卡
- `--single N` 时只生成 `<来源><ID>-评论NN.png`
- 带 `#reply<id>` 锚点时只生成该条评论的单卡，文件名为 `<来源><ID>-评论r<id>.png`

默认 3 倍分辨率（`--scale 2/3/4` 可调），自动裁剪留白、框外透明，可直接进视频。

## 项目结构

```
bili_comment_card/
  __main__.py   # CLI：参数解析与流程编排
  api.py        # 数据层：目标解析、来源信息、评论分页、头像/表情缓存
  render.py     # 渲染层：主题、卡片 HTML、chromium 截图与裁剪
  css.py        # CSS 模板（字体与主题色注入）
assets/
  icons/        # B 站 svg-next 原版图标矢量数据（点赞/回复/转发）
  level/fit/    # B 站官方 LV 徽章（已裁剪 viewBox）
  up_pb.svg     # 官方 UP 主标识
cache/          # 头像与表情图缓存（自动生成）
output/         # 产物（自动生成）
```

## 实现说明与已知限制

- 评论走公开接口 `x/v2/reply/main`（游标分页），动态用 `comment_id/comment_type`，视频用 `aid`；遇到瞬时风控（-352/-412）会自动退避重试
- BV 号大小写敏感，解析时保持原样
- 未登录状态下仅能获取公开可见的评论；UP 主/楼主标识按动态作者与 `is_upper` 判断
- 头像与表情首次抓取后存入 `cache/`，离线也能重复渲染
- **配图字段是 `content.pictures[].img_src`**（不是 `pics[].url`——错用会静默漏掉全部配图）
- 截图触底会自动加倍窗口高度重渲（最多 4 次），长楼中楼卡不会截断
