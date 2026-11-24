# -*- coding: utf-8 -*-
"""把《高性价比投资指南》指定的节，渲染成一个自包含的单文件 HTML 阅读页。

源文件在同仓库的 book/ 目录下，每章一个 Markdown 文件，格式与原项目 cdyforever/how-to-live-better 的 build.py 相同。

用法：
    python build.py                      # 默认第 1、2、16 节
    python build.py 1 2 16 3             # 指定任意节号（按给定顺序渲染）
    python build.py all                  # 全部节（用于线上站点）
    python build.py all -o index.html    # 指定输出文件名
    python build.py all -o index.html

源目录默认就是本仓库（book/），也可用 --repo 或环境变量 HTIB_REPO 覆盖。
产物默认与脚本同目录，单个 .html，无任何外部依赖，双击即可打开、可离线读。

成本权重与档位规则沿用原项目 build.py 的 COST_W / ratio_of 口径。
"""

import argparse
import html
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def parse_args():
    ap = argparse.ArgumentParser(description="生成《高性价比投资指南》单文件阅读页")
    ap.add_argument("sections", nargs="*", help="节号；或 all 表示全部节")
    ap.add_argument("-o", "--out", default=None, help="输出文件名（默认按节号自动命名）")
    ap.add_argument("--repo", default=None, help="本书仓库目录（默认 build.py 所在目录）")
    return ap.parse_args()


ARGS = parse_args()
REPO = Path(ARGS.repo or os.environ.get("HTIB_REPO") or HERE)

REPO_URL = "https://github.com/xledoo/how-to-invest-better"


def avail_sections():
    """扫描 book/ 目录，得到实际存在的节号。"""
    return sorted(int(p.name[:2]) for p in REPO.glob("book/[0-9][0-9]-*.md"))


ALL = avail_sections()
if not ALL:
    raise SystemExit("在 %s 下找不到 book/NN-*.md，请用 --repo 指定正确的仓库目录" % REPO)

if ARGS.sections:
    if any(a.lower() == "all" for a in ARGS.sections):
        SECTIONS = ALL
    else:
        SECTIONS = [int(a) for a in ARGS.sections]
else:
    SECTIONS = list(ALL)

SCOPE = ("全书 %d 节" % len(ALL)) if SECTIONS == ALL else ("第 %s 节" % "、".join(str(n) for n in SECTIONS))

# 成本权重与档位规则，抄自 index.html 的 COST_W 与 e.ratio 两行
COST_W = {
    "钱": {"0": 0, "少": 1, "多": 2},
    "时间": {"少": 0, "中": 1, "多": 2},
    "毅力": {"否": 0, "些": 1, "是": 2},
}
RATIO_ORDER = {"极高": 0, "高": 1, "一般": 2}


def find_file(n):
    hits = sorted(REPO.glob("book/%02d-*.md" % n))
    if not hits:
        raise SystemExit("找不到第 %d 节" % n)
    return hits[0]


def parse(path):
    lines = path.read_text(encoding="utf-8").split("\n")
    title, intro, entries, cur = "", [], [], None
    for ln in lines:
        m = re.match(r"^#\s+(.*)$", ln)
        if m and not title:
            title = m.group(1).strip()
            continue
        m = re.match(r"^###\s+(\d+)\.\s*(.*)$", ln)
        if m:
            cur = {"no": int(m.group(1)), "title": m.group(2).strip(),
                   "tags_raw": None, "fields": {}, "last": None}
            entries.append(cur)
            continue
        if cur is None:
            if ln.strip() and not ln.startswith("["):
                intro.append(ln.strip())
            continue
        mt = re.match(r"^<!--\s*成本标签:\s*(.*?)\s*-->", ln)
        if mt:
            cur["tags_raw"] = mt.group(1)
            continue
        mf = re.match(r"^-\s*(成本|说人话|收益|证据等级|来源|备注)：(.*)$", ln)
        if mf:
            cur["last"] = mf.group(1)
            cur["fields"][mf.group(1)] = mf.group(2).strip()
            continue
        if not ln.strip():
            cur["last"] = None
            continue
        if cur["last"]:
            cur["fields"][cur["last"]] += ln.strip()
    return title, intro, entries


def parse_tags(raw):
    if not raw:
        return {}
    return dict(re.findall(r"(钱|时间|毅力|收益|口径)=(\S+)", raw))


def ratio_of(t):
    try:
        cs = sum(COST_W[k][t[k]] for k in ("钱", "时间", "毅力"))
    except KeyError:
        return None
    lv = t.get("收益")
    if lv == "大":
        return "极高" if cs == 0 else ("高" if cs <= 2 else "一般")
    if lv == "中" and cs == 0:
        return "高"
    return "一般"


def inline(s):
    """把一小段 markdown 行内语法转成 HTML。先整体转义，再用占位符放链接。"""
    stash = []

    def mk(url, text=None):
        shown = text or url
        if len(shown) > 62:
            shown = shown[:59] + "…"
        stash.append('<a href="%s" target="_blank" rel="noopener">%s</a>' % (url, shown))
        return "\u0001%d\u0001" % (len(stash) - 1)

    s = html.escape(s, quote=False)
    s = re.sub(r"&lt;(https?://[^\s]+?)&gt;", lambda m: mk(m.group(1)), s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", lambda m: mk(m.group(2), m.group(1)), s)
    s = re.sub(r"(?<![\w\"=])(https?://[^\s，。；）)]+)", lambda m: mk(m.group(1)), s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = s.replace("\\*", "*").replace("\\_", "_")
    s = re.sub("\u0001(\\d+)\u0001", lambda m: stash[int(m.group(1))], s)
    return s


def link_count(s):
    return len(re.findall(r"https?://", s or ""))


def source_rev():
    """取本仓库当前提交的短 hash 与日期。

    故意用 git 状态而不是构建时间：同样的源状态下重跑结果完全一致，
    产物可做字节级比对，方便确认「没改坏东西」。
    """
    try:
        p = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--date=short",
                            "--format=%h|%cd"],
                           capture_output=True, text=True, encoding="utf-8", timeout=15)
        if p.returncode == 0 and "|" in (p.stdout or ""):
            h, d = p.stdout.strip().split("|", 1)
            return h.strip(), d.strip()
    except Exception:
        pass
    return "", ""


CSS = r"""
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#f7f3ec;--bg-alt:#f1eadf;--bg-elv:#fffdf8;--bg-mute:#efe7d8;
  --divider:#e2d7c3;--divider-soft:#ece3d2;
  --t1:#2b2620;--t2:#57503f;--t3:#8a7f6c;
  --brand-1:#9a3b26;--brand-2:#7c2e1d;--brand-soft:#f6e6de;
  --green-1:#2e6b4f;--green-soft:#e2efe6;
  --yellow-1:#8a5a1d;--yellow-soft:#f5e9cf;
  --red-1:#b8272c;--red-soft:#fbe4e4;
  --gray-1:#6b6257;--gray-soft:#ece7db;
  --mark:rgba(214,164,92,.38);
  --serif:"Songti SC","STSong","Noto Serif CJK SC","Noto Serif SC",serif;
  --font:"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --bar:56px;--side:300px;
  --shadow:0 1px 2px rgba(60,45,20,.05),0 8px 24px rgba(60,45,20,.06);
}
[data-theme=dark]{
  --bg:#1e1a16;--bg-alt:#241f19;--bg-elv:#292219;--bg-mute:#332b20;
  --divider:#3d3326;--divider-soft:#332b20;
  --t1:#ece3d1;--t2:#c9bda6;--t3:#96897a;
  --brand-1:#e09a7a;--brand-2:#f0b394;--brand-soft:#3a2a20;
  --green-1:#7cc79c;--green-soft:#24382e;
  --yellow-1:#e8bd7a;--yellow-soft:#3a2f1e;
  --red-1:#f08a8e;--red-soft:#3d2323;
  --gray-1:#a89d8c;--gray-soft:#332b20;
  --mark:rgba(214,164,92,.35);
  --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 28px rgba(0,0,0,.35);
}
html{scroll-behavior:smooth;scroll-padding-top:calc(var(--bar) + 16px)}
body{margin:0;background:var(--bg);color:var(--t1);font:16px/1.85 var(--font);
  -webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%}
a{color:var(--brand-1);text-decoration:none}
a:hover{color:var(--brand-2);text-decoration:underline;text-underline-offset:3px}
mark{background:var(--mark);color:inherit;border-radius:2px;padding:0 1px}
strong{font-weight:600;color:var(--t1)}
::selection{background:var(--brand-soft);color:var(--brand-2)}

/* ---- top bar: slim, translucent paper ---- */
.bar{position:sticky;top:0;z-index:30;display:flex;flex-wrap:wrap;align-items:center;gap:10px;
  padding:0 22px;min-height:56px;background:var(--bg);
  backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--divider)}
.bar h1{font-family:var(--serif);font-size:16px;font-weight:700;margin:0;white-space:nowrap;min-width:0;letter-spacing:.02em}
.bar h1 small{font-family:var(--font);font-weight:400;font-size:12px;color:var(--t3);margin-left:8px}
.spacer{flex:1}
.search{position:relative;width:300px;max-width:42vw}
.search input{width:100%;height:34px;padding:0 30px 0 32px;border-radius:999px;border:1px solid var(--divider);
  background:var(--bg-elv);color:var(--t1);font:inherit;font-size:13px}
.search input:focus{outline:0;border-color:var(--brand-1);background:var(--bg-elv);box-shadow:0 0 0 3px var(--brand-soft)}
.search svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);width:15px;height:15px;
  fill:none;stroke:var(--t3);stroke-width:2;pointer-events:none}
.search kbd{position:absolute;right:9px;top:50%;transform:translateY(-50%);font:500 10px/1 var(--font);
  color:var(--t3);border:1px solid var(--divider);border-radius:4px;padding:2px 4px;background:var(--bg-elv)}
.btn{height:30px;padding:0 12px;border-radius:999px;border:1px solid var(--divider);background:var(--bg-elv);
  color:var(--t2);font:500 12px/1 var(--font);cursor:pointer;transition:all .18s;white-space:nowrap}
.btn:hover{border-color:var(--brand-1);color:var(--brand-1)}
.btn[aria-pressed=true]{background:var(--brand-soft);border-color:var(--brand-1);color:var(--brand-1)}
.count{font-size:12px;color:var(--t3);white-space:nowrap;font-variant-numeric:tabular-nums}
.jump{display:none;height:30px;max-width:38vw;padding:0 6px;border-radius:8px;border:1px solid var(--divider);
  background:var(--bg-elv);color:var(--t2);font:500 12px/1 var(--font)}

/* ---- hero ---- */
.hero{max-width:940px;margin:0 auto;padding:64px 40px 44px;text-align:left}
.hero .eyebrow{margin:0 0 18px;font-size:12px;font-weight:600;letter-spacing:.28em;color:var(--brand-1);text-transform:uppercase}
.hero .eyebrow::after{content:"";display:block;width:44px;height:2px;background:var(--brand-1);margin-top:14px}
.hero h1{font-family:var(--serif);font-size:clamp(32px,5vw,46px);font-weight:700;line-height:1.25;letter-spacing:.01em;margin:0 0 18px}
.hero .lede{margin:0;max-width:640px;font-size:17px;line-height:1.9;color:var(--t2)}
.hero .stats{display:flex;flex-wrap:wrap;gap:0;margin-top:34px;border-top:1px solid var(--divider);border-bottom:1px solid var(--divider)}
.hero .stat{padding:16px 28px 16px 0;margin-right:28px}
.hero .stat+.stat{padding-left:28px;border-left:1px solid var(--divider-soft)}
.hero .stat b{display:block;font-family:var(--serif);font-size:26px;font-weight:700;line-height:1.2;color:var(--t1)}
.hero .stat span{font-size:12px;color:var(--t3);letter-spacing:.08em}
.hero .note{margin:20px 0 0;font-size:12.5px;color:var(--t3)}

.shell{display:flex;align-items:flex-start}
.toc{position:sticky;top:var(--bar);flex:none;width:var(--side);height:calc(100vh - var(--bar));
  overflow-y:auto;padding:22px 14px 80px 22px;background:var(--bg-alt);border-right:1px solid var(--divider)}
.toc .gt{font-family:var(--serif);font-size:14px;font-weight:700;margin:0 0 8px;color:var(--t1);display:flex;justify-content:space-between;align-items:baseline}
.toc .gt small{font-family:var(--font);font-weight:400;font-size:11px;color:var(--t3)}
.toc .grp{padding-bottom:16px;margin-bottom:16px;border-bottom:1px solid var(--divider)}
.toc .grp:last-child{border-bottom:0;margin-bottom:0}
.toc a{display:flex;gap:6px;align-items:baseline;padding:4px 6px;border-radius:6px;font-size:12.5px;
  line-height:1.6;color:var(--t2)}
.toc a:hover{background:var(--bg-elv);color:var(--t1);text-decoration:none}
.toc a.active{background:var(--brand-soft);color:var(--brand-1)}
.toc a i{font-style:normal;color:var(--t3);font-variant-numeric:tabular-nums;flex:none;min-width:16px;text-align:right}
.dot{width:6px;height:6px;border-radius:50%;flex:none;margin-top:7px}
.d0{background:var(--brand-1)}.d1{background:var(--green-1)}.d2{background:var(--t3)}

main{flex:1;min-width:0;padding:8px 40px 140px;max-width:940px}
section{margin-bottom:52px}
.sec-h{display:flex;align-items:baseline;gap:12px;padding-bottom:12px;border-bottom:1px solid var(--t1);margin-bottom:6px}
.sec-h h2{font-family:var(--serif);font-size:26px;font-weight:700;margin:0;letter-spacing:.01em}
.sec-h .meta{font-size:12px;color:var(--t3);font-variant-numeric:tabular-nums;letter-spacing:.05em}
.intro{color:var(--t2);font-size:15px;line-height:1.9;margin:16px 0 26px;padding-left:16px;border-left:2px solid var(--divider)}

.card{background:var(--bg-elv);border:1px solid var(--divider);border-radius:14px;padding:22px 24px 18px;margin-bottom:16px;box-shadow:var(--shadow);transition:border-color .18s,transform .18s}
.card:hover{border-color:var(--brand-1)}
.chead{display:flex;gap:12px;align-items:flex-start}
.num{flex:none;min-width:26px;height:26px;padding:0 6px;border-radius:8px;background:var(--bg-mute);color:var(--t3);
  font:600 12px/26px var(--font);text-align:center;font-variant-numeric:tabular-nums}
.chead h3{margin:0;font-family:var(--serif);font-size:18px;font-weight:700;line-height:1.55;letter-spacing:.01em}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 14px 38px}
.badge{font:500 11px/1 var(--font);padding:5px 10px;border-radius:999px;border:1px solid transparent;letter-spacing:.03em}
.gA{background:var(--green-soft);color:var(--green-1);border-color:var(--green-soft)}
.gB{background:var(--yellow-soft);color:var(--yellow-1);border-color:var(--yellow-soft)}
.gC{background:var(--gray-soft);color:var(--gray-1);border-color:var(--gray-soft)}
.r0{background:var(--brand-soft);color:var(--brand-1);border-color:var(--brand-soft)}
.r1{background:var(--green-soft);color:var(--green-1);border-color:var(--green-soft)}
.r2{background:var(--gray-soft);color:var(--gray-1);border-color:var(--gray-soft)}
.tag{font:400 11px/1 var(--font);padding:5px 10px;border-radius:999px;background:var(--bg-mute);color:var(--t3)}

.plain{margin:0 0 14px 38px;padding:14px 18px;background:var(--brand-soft);
  border-left:3px solid var(--brand-1);border-radius:0 10px 10px 0;font-family:var(--serif);font-size:16.5px;line-height:1.85;color:var(--t1)}
.fields{margin-left:38px}
.f{display:grid;grid-template-columns:52px 1fr;gap:12px;padding:9px 0;border-top:1px solid var(--divider-soft);
  font-size:14px;line-height:1.85;color:var(--t2)}
.f b{font-weight:500;color:var(--t3);font-size:12.5px;padding-top:3px}
.f.note b{color:var(--yellow-1)}
.f>div{min-width:0;overflow-wrap:anywhere}
.src{margin:12px 0 0 38px;border-top:1px solid var(--divider-soft);padding-top:10px}
.src summary{cursor:pointer;font-size:12.5px;color:var(--t3);list-style:none;user-select:none}
.src summary::-webkit-details-marker{display:none}
.src summary::before{content:"▸ ";color:var(--t3)}
.src[open] summary::before{content:"▾ "}
.src summary:hover{color:var(--brand-1)}
.src .sbody{font-size:12.5px;line-height:1.9;color:var(--t2);padding:8px 0 2px;word-break:break-word;overflow-wrap:anywhere}

body.plain-only .fields,body.plain-only .src{display:none}
.hidden{display:none!important}

.empty{color:var(--t3);font-size:14px;padding:40px 0;text-align:center}
footer{color:var(--t3);font-size:12.5px;border-top:1px solid var(--divider);padding-top:18px;line-height:2}
footer a{color:var(--t2)}

#top{position:fixed;right:18px;bottom:18px;z-index:40;width:44px;height:44px;border-radius:50%;
  border:1px solid var(--divider);background:var(--bg-elv);color:var(--t2);cursor:pointer;
  font:400 17px/1 var(--font);box-shadow:var(--shadow);
  opacity:0;pointer-events:none;transition:opacity .2s,color .18s}
#top.show{opacity:1;pointer-events:auto}
#top:hover{color:var(--brand-1);border-color:var(--brand-1)}

@media (max-width:1080px){
  .toc{display:none}
  .jump{display:block}
  .hero{padding:48px 22px 36px}
  main{padding:8px 22px 130px;max-width:none}
}
@media (max-width:820px){
  .bar{padding:8px 12px;gap:8px;min-height:0}
  .bar h1{order:1;flex:1 1 120px;font-size:14px;overflow:hidden;text-overflow:ellipsis}
  .spacer{display:none}
  .jump{order:2}
  #theme{order:3}
  #f-all{order:4}#f-a{order:5}#f-plain{order:6}
  .count{order:7;margin-left:auto}
  .search{order:8;width:auto;max-width:none;flex:1 1 100%;margin-top:2px}
  .search input{height:34px}
  .search kbd{display:none}
  body.compact .jump,body.compact #f-all,body.compact #f-a,
  body.compact #f-plain,body.compact .count{display:none}
  body.compact .search{order:2;flex:1 1 120px;margin-top:0}
  body.compact #theme{order:3}
  .hero{padding:40px 16px 30px}
  .hero h1{font-size:30px}
  .hero .lede{font-size:15.5px}
  .hero .stat{padding:12px 18px 12px 0;margin-right:18px}
  .hero .stat+.stat{padding-left:18px}
  .hero .stat b{font-size:22px}
  main{padding:8px 13px 110px}
  .sec-h h2{font-size:21px}
  .card{padding:18px 16px 14px;border-radius:12px;margin-bottom:12px}
  .chead h3{font-size:16.5px}
  .plain{font-size:15.5px;padding:12px 14px}
  .f{font-size:13.5px;grid-template-columns:44px 1fr;gap:8px}
  .intro{font-size:14px;margin:12px 0 20px}
}
@media (max-width:520px){
  .bar h1 small{display:none}
  .chips,.plain,.fields,.src{margin-left:0}
  .num{min-width:22px;height:22px;font-size:11px;line-height:22px}
  .hero .stat{padding-right:14px;margin-right:14px}
  .hero .stat+.stat{padding-left:14px}
}
@media (max-width:380px){
  .btn{padding:0 8px;font-size:11px}
  .bar h1{flex:1 1 90px;font-size:13px}
  .jump{max-width:32vw}
}
@media print{
  .bar,.toc,#top,.hero .stats{display:none}
  .hero{padding:0;max-width:none}
  main{max-width:none;padding:0}
  .card{break-inside:avoid;border-color:#ccc;box-shadow:none}
  .src .sbody{display:block}
  body{font-size:11pt;background:#fff}
}
"""


def render_entry(e, sec_no):
    t = parse_tags(e["tags_raw"])
    f = e["fields"]
    grade = (f.get("证据等级") or "?").strip()[:1]
    ratio = ratio_of(t)
    chips = []
    gcls = {"A": "gA", "B": "gB", "C": "gC"}.get(grade, "gC")
    chips.append('<span class="badge %s">%s 级</span>' % (gcls, grade))
    if ratio:
        chips.append('<span class="badge r%d">性价比 %s</span>' % (RATIO_ORDER[ratio], ratio))
    for k in ("口径",):
        if t.get(k):
            chips.append('<span class="tag">%s %s</span>' % (k, t[k]))
    for k in ("钱", "时间", "毅力"):
        if t.get(k):
            chips.append('<span class="tag">%s %s</span>' % (k, t[k]))
    if t.get("收益"):
        chips.append('<span class="tag">收益 %s</span>' % t["收益"])

    rows = []
    for k in ("成本", "收益"):
        if f.get(k):
            rows.append('<div class="f"><b>%s</b><div>%s</div></div>' % (k, inline(f[k])))
    if f.get("备注"):
        rows.append('<div class="f note"><b>备注</b><div>%s</div></div>' % inline(f["备注"]))

    src = f.get("来源", "")
    n = link_count(src)
    src_html = ""
    if src:
        src_html = ('<details class="src"><summary>来源%s</summary>'
                    '<div class="sbody">%s</div></details>'
                    % ("（%d 条文献）" % n if n else "", inline(src)))

    return ('<article class="card" id="s%d-%d" data-grade="%s" data-ratio="%s">'
            '<div class="chead"><span class="num">%d</span><h3>%s</h3></div>'
            '<div class="chips">%s</div>'
            '<p class="plain">%s</p>'
            '<div class="fields">%s</div>%s</article>') % (
        sec_no, e["no"], grade, ratio or "-", e["no"], inline(e["title"]),
        "".join(chips), inline(f.get("说人话", "")), "".join(rows), src_html)


JS = r"""
const cards=[...document.querySelectorAll('.card')];
const secs=[...document.querySelectorAll('section')];
const bar=document.querySelector('.bar');
const q=document.getElementById('q');
const cnt=document.getElementById('cnt');
const jump=document.getElementById('jump');
const fAll=document.getElementById('f-all');
const fA=document.getElementById('f-a');
const fP=document.getElementById('f-plain');
const themeBtn=document.getElementById('theme');
const topBtn=document.getElementById('top');
let grade=null, plainOnly=false;

/* 顶栏高度会随换行变化，交给 JS 实测，锚点跳转才不会被顶栏盖住 */
function syncBar(){
  const h=Math.round(bar.getBoundingClientRect().height);
  document.documentElement.style.setProperty('--bar', h+'px');
}

function clearMarks(root){
  const ms=[...root.querySelectorAll('mark')];
  ms.forEach(m=>m.replaceWith(document.createTextNode(m.textContent)));
  if(ms.length) root.normalize();
}
function markAll(root,term){
  if(!term) return;
  const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(n){
    if(!n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
    const p=n.parentElement;
    if(!p) return NodeFilter.FILTER_REJECT;
    if(p.closest('script,style,mark,a')) return NodeFilter.FILTER_REJECT;
    return NodeFilter.FILTER_ACCEPT;
  }});
  const nodes=[]; while(w.nextNode()) nodes.push(w.currentNode);
  const t=term.toLowerCase();
  nodes.forEach(n=>{
    const raw=n.nodeValue.toLowerCase();
    if(raw.indexOf(t)<0) return;
    const frag=document.createDocumentFragment();
    let i=raw.indexOf(t), last=0;
    while(i>=0){
      frag.appendChild(document.createTextNode(n.nodeValue.slice(last,i)));
      const m=document.createElement('mark');
      m.textContent=n.nodeValue.slice(i,i+t.length);
      frag.appendChild(m);
      last=i+t.length; i=raw.indexOf(t,last);
    }
    frag.appendChild(document.createTextNode(n.nodeValue.slice(last)));
    n.replaceWith(frag);
  });
}
function apply(){
  const term=q.value.trim().toLowerCase();
  clearMarks(document.querySelector('main'));
  let shown=0;
  cards.forEach(c=>{
    let ok=true;
    if(grade && c.dataset.grade!==grade) ok=false;
    if(ok && term && !c.textContent.toLowerCase().includes(term)) ok=false;
    c.classList.toggle('hidden',!ok);
    if(ok) shown++;
  });
  secs.forEach(s=>{
    const n=s.querySelectorAll('.card:not(.hidden)').length;
    s.classList.toggle('hidden',n===0);
    if(jump){
      const o=jump.querySelector('option[value="'+s.id+'"]');
      if(o) o.disabled=(n===0);
    }
  });
  document.getElementById('empty').classList.toggle('hidden',shown>0);
  cnt.textContent=shown+' / '+cards.length+' 条';
  if(term) markAll(document.querySelector('main'),term);
  document.querySelectorAll('.toc a').forEach(a=>{
    const el=document.getElementById(a.getAttribute('href').slice(1));
    a.classList.toggle('hidden',!el||el.classList.contains('hidden'));
  });
}
let timer=null;
q.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(apply,90);});
function setMode(mode){
  grade=(mode==='A')?'A':null;
  plainOnly=(mode==='plain');
  document.body.classList.toggle('plain-only',plainOnly);
  const map={'all':fAll,'A':fA,'plain':fP};
  Object.keys(map).forEach(k=>map[k].setAttribute('aria-pressed',String(k===mode)));
  apply();
}
fAll.onclick=()=>setMode('all');
fA.onclick=()=>setMode('A');
fP.onclick=()=>setMode('plain');
fAll.setAttribute('aria-pressed','true');

if(jump){
  jump.addEventListener('change',()=>{
    const el=document.getElementById(jump.value);
    if(el) el.scrollIntoView({block:'start'});
  });
}
themeBtn.onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',cur);
  try{localStorage.setItem('htib-theme',cur);}catch(e){}
};
try{
  const t=localStorage.getItem('htib-theme');
  if(t) document.documentElement.setAttribute('data-theme',t);
  else if(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.setAttribute('data-theme','dark');
}catch(e){}
document.addEventListener('keydown',e=>{
  if(e.key==='/'&&document.activeElement!==q&&!/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)){
    e.preventDefault();q.focus();
  }
  if(e.key==='Escape'&&document.activeElement===q){q.value='';apply();q.blur();}
});
topBtn.onclick=()=>window.scrollTo({top:0,behavior:'smooth'});
/* 滚动状态：① 顶栏收起（手机）② 回到顶部按钮出现。
   用 rAF 节流，避免滚动时每帧都跑；阈值留迟滞区间，防止在临界点来回抖动。 */
let compact=false, ticking=false;
function onScroll(){
  const y=window.scrollY;
  const want = compact ? (y>200) : (y>420);
  if(want!==compact){compact=want;document.body.classList.toggle('compact',compact);syncBar();}
  topBtn.classList.toggle('show',y>900);
}
addEventListener('scroll',()=>{
  if(ticking) return;
  ticking=true;
  requestAnimationFrame(()=>{ticking=false;onScroll();});
},{passive:true});
addEventListener('resize',syncBar);
if(document.fonts&&document.fonts.ready) document.fonts.ready.then(syncBar);
syncBar();

const links=[...document.querySelectorAll('.toc a')];
const io=new IntersectionObserver(es=>{
  es.forEach(e=>{ if(e.isIntersecting){
    if(e.target.classList.contains('card'))
      links.forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+e.target.id));
    else if(jump && e.target.tagName==='SECTION')
      jump.value=e.target.id;
  }});
},{rootMargin:'-70px 0px -75% 0px'});
cards.forEach(c=>io.observe(c));
if(jump) secs.forEach(s=>io.observe(s));
"""


def main():
    sec_toc = []
    sec_html = []
    jump_opts = []
    total = 0
    grade_cnt = {"A": 0, "B": 0, "C": 0}
    link_total = 0

    for n in SECTIONS:
        p = find_file(n)
        title, intro, entries = parse(p)
        cards = []
        links = []
        for e in entries:
            g = (e["fields"].get("证据等级") or "?").strip()[:1]
            if g in grade_cnt:
                grade_cnt[g] += 1
            total += 1
            link_total += link_count(e["fields"].get("来源", "")) + link_count(e["fields"].get("备注", ""))
            cards.append(render_entry(e, n))
            r = ratio_of(parse_tags(e["tags_raw"]))
            short = e["title"] if len(e["title"]) <= 34 else e["title"][:33] + "…"
            links.append('<a href="#s%d-%d" title="%s"><span class="dot d%d"></span>'
                         '<i>%d</i><span>%s</span></a>'
                         % (n, e["no"], html.escape(e["title"], quote=True),
                            RATIO_ORDER.get(r, 2), e["no"], html.escape(short)))
        sec_toc.append('<div class="grp"><div class="gt">%s<small>%d 条</small></div>%s</div>'
                       % (inline(title), len(entries), "".join(links)))
        sec_html.append(
            '<section id="sec%d"><div class="sec-h"><h2>%s</h2>'
            '<span class="meta">%d 条</span></div>%s%s</section>'
            % (n, inline(title), len(entries),
               ('<p class="intro">%s</p>' % inline(" ".join(intro))) if intro else "",
               "".join(cards)))
        jump_opts.append('<option value="sec%d">%s</option>' % (n, html.escape(title)))

    rev, rev_date = source_rev()

    head = ('<!DOCTYPE html><html lang="zh-CN" data-theme="light"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="color-scheme" content="light dark">'
            '<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f7f3ec">'
            '<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#1e1a16">'
            '<meta name="description" content="《高性价比投资指南》%s，共 %d 条投资中容易犯的错误，'
            '每条标注成本、代价、证据等级（A/B/C）与来源。单文件、零依赖、可离线阅读。仅供投资者教育，不构成投资建议。">'
            '<title>高性价比投资指南 · %s</title><style>%s</style></head><body>'
            % (SCOPE, total, SCOPE, CSS))

    bar = ('<header class="bar"><h1>高性价比投资指南<small>%s</small></h1>'
           '<select class="jump" id="jump" aria-label="跳转到某一节">%s</select>'
           '<div class="spacer"></div>'
           '<button class="btn" id="f-all">全部</button>'
           '<button class="btn" id="f-a">只看 A 级</button>'
           '<button class="btn" id="f-plain">只看说人话</button>'
           '<div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/>'
           '<path d="M20 20l-3.5-3.5"/></svg>'
           '<input id="q" type="search" placeholder="搜索标题、说人话、收益…" autocomplete="off">'
           '<kbd>/</kbd></div>'
           '<span class="count" id="cnt">%d / %d 条</span>'
           '<button class="btn" id="theme">明/暗</button></header>' % (
               SCOPE, "".join(jump_opts), total, total))

    src_line = '内容来源：本仓库 book/ 中的原创整理，每条的「来源」栏列出所引用的报告、研究或投资者教育材料'
    src_line += '；结构与渲染方式对标 <a href="https://github.com/cdyforever/how-to-live-better" target="_blank" rel="noopener">cdyforever/how-to-live-better</a>'
    src_line += '（Unlicense，公有领域）。本书内容仅供投资者教育，不构成投资建议'
    if rev:
        src_line += '，数据截至 <span style="font-family:var(--mono)">%s</span>%s' % (
            rev, '（%s）' % rev_date if rev_date else '')

    footer = ('<footer>%s。<br>'
              '本页共 %d 条，'
              'A 级 %d 条、B 级 %d 条、C 级 %d 条，含 %d 条文献外链。<br>'
              '单文件自包含，不引用任何外部资源（正文中的文献链接除外），可离线阅读。'
              '由 build.py 生成。</footer>'
              % (src_line, total, grade_cnt["A"], grade_cnt["B"], grade_cnt["C"], link_total))

    hero = ('<header class="hero"><p class="eyebrow">高性价比投资指南 · 新手避坑手册</p>'
            '<h1>高性价比投资指南</h1>'
            '<p class="lede">投资亏钱，很多时候不是选错了标的，而是先犯了一个本可以避开的错误。'
            '本书把新手最容易犯的错误一条一条写清楚：它会花掉你什么、代价有多大、证据有多硬，以及改掉它该怎么做。</p>'
            '<div class="stats">'
            '<div class="stat"><b>%d</b><span>章节</span></div>'
            '<div class="stat"><b>%d</b><span>条错误</span></div>'
            '<div class="stat"><b>%d</b><span>A 级证据</span></div>'
            '</div>'
            '<p class="note">仅供投资者教育，不构成投资建议。单文件、零依赖，可离线阅读。</p></header>'
            % (len(SECTIONS), total, grade_cnt["A"]))
    shell = ('<div class="shell"><aside class="toc">%s</aside><main>%s'
             '<div class="empty hidden" id="empty">没有匹配的条目</div>%s'
             '</main></div>'
             '<button id="top" title="回到顶部" aria-label="回到顶部">↑</button>'
             % ("".join(sec_toc), "".join(sec_html), footer))

    # 注意：JS 字符串只含脚本体，<script> 开合标签在这里拼。
    # 之前漏了开标签，导致整段 JS 被当纯文本渲染在页面底部、脚本从未执行。
    out = head + bar + hero + shell + "<script>" + JS + "</script></body></html>"

    if ARGS.out:
        name = Path(ARGS.out)
        if not name.is_absolute():
            name = HERE / name
    else:
        name = HERE / ("index.html" if SECTIONS == ALL else ("高性价比投资指南_%s.html" % "_".join("第%d节" % n for n in SECTIONS)))

    name.write_text(out, encoding="utf-8")
    print("范围 %s ｜ 节数 %d ｜ 条目 %d ｜ A %d B %d C %d ｜ 外链 %d"
          % (SCOPE, len(SECTIONS), total, grade_cnt["A"], grade_cnt["B"], grade_cnt["C"], link_total))
    print("输出：%s  (%d 字节)" % (name, len(out.encode("utf-8"))))


if __name__ == "__main__":
    main()
