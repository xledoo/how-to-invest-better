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
/* ---- themes: A magazine / B minimal (default) / C dark fintech ----
   Tokens taken from the three preview pages (ts-spaces/...-yu-lan-a/b/c).
   A: paper #f6efe1, ink #221a11, accent #a9341f, serif Songti/Noto Serif SC.
   B: white #ffffff, text #111827, accent #111827, system sans.
   C: dark #070b12, panel #0e1422, ink #e8eef7, green #2fd598, red #fb7185,
      amber #fbbf24, cyan #38bdf8, mono numbers, 44px grid background. */
:root{
  --bg:#ffffff;--bg-alt:#fafafa;--bg-elv:#ffffff;--bg-mute:#f3f4f6;
  --divider:#e5e7eb;--divider-soft:#f0f0f0;
  --t1:#111827;--t2:#4b5563;--t3:#9ca3af;
  --brand-1:#111827;--brand-2:#111827;--brand-soft:#f3f4f6;
  --green-1:#15803d;--green-soft:#dcfce7;
  --yellow-1:#92400e;--yellow-soft:#fef3c7;
  --red-1:#b91c1c;--red-soft:#fee2e2;
  --gray-1:#6b7280;--gray-soft:#f3f4f6;
  --mark:rgba(17,24,39,.14);
  --serif:"Songti SC","STSong","Noto Serif CJK SC","Noto Serif SC",serif;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --bar:56px;--side:300px;--radius:14px;
  --shadow:0 1px 2px rgba(17,24,39,.05),0 8px 24px rgba(17,24,39,.05);
}
[data-theme="b"]{
  --bg:#ffffff;--bg-alt:#fafafa;--bg-elv:#ffffff;--bg-mute:#f3f4f6;
  --divider:#e5e7eb;--divider-soft:#f0f0f0;
  --t1:#111827;--t2:#4b5563;--t3:#9ca3af;
  --brand-1:#111827;--brand-2:#111827;--brand-soft:#f3f4f6;
  --green-1:#15803d;--green-soft:#dcfce7;
  --yellow-1:#92400e;--yellow-soft:#fef3c7;
  --red-1:#b91c1c;--red-soft:#fee2e2;
  --gray-1:#6b7280;--gray-soft:#f3f4f6;
  --mark:rgba(17,24,39,.14);
  --serif:"Songti SC","STSong","Noto Serif CJK SC","Noto Serif SC",serif;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --bar:56px;--side:300px;--radius:14px;
  --shadow:0 1px 2px rgba(17,24,39,.05),0 8px 24px rgba(17,24,39,.05);
}
[data-theme="a"]{
  --bg:#f6efe1;--bg-alt:#efe5cf;--bg-elv:#fbf7ec;--bg-mute:#efe5cf;
  --divider:#d9cbae;--divider-soft:#e8dcc2;
  --t1:#221a11;--t2:#4a3f30;--t3:#7d6f5a;
  --brand-1:#a9341f;--brand-2:#7c2a15;--brand-soft:#f3ddd2;
  --green-1:#2e6b4f;--green-soft:#e2efe6;
  --yellow-1:#8a6d2f;--yellow-soft:#f5e9cf;
  --red-1:#a9341f;--red-soft:#f3ddd2;
  --gray-1:#6b6257;--gray-soft:#ece7db;
  --mark:rgba(169,52,31,.18);
  --serif:"Noto Serif SC","Songti SC","STSong",serif;
  --font:"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --bar:56px;--side:300px;--radius:10px;
  --shadow:0 1px 2px rgba(60,45,20,.06),0 8px 24px rgba(60,45,20,.07);
}
[data-theme="c"]{
  --bg:#070b12;--bg-alt:#0a0f19;--bg-elv:#0e1422;--bg-mute:#111a2c;
  --divider:#1c2940;--divider-soft:#162136;
  --t1:#e8eef7;--t2:#aebdd2;--t3:#7d8ea9;
  --brand-1:#38bdf8;--brand-2:#7dd3fc;--brand-soft:#0e2233;
  --green-1:#2fd598;--green-soft:#123c2e;
  --yellow-1:#fbbf24;--yellow-soft:#3a2c0e;
  --red-1:#fb7185;--red-soft:#3d1a24;
  --gray-1:#7d8ea9;--gray-soft:#111a2c;
  --mark:rgba(56,189,248,.28);
  --serif:"Noto Serif SC","Songti SC","STSong",serif;
  --font:"IBM Plex Sans","Noto Sans SC",-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --bar:56px;--side:300px;--radius:10px;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px rgba(0,0,0,.4);
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
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:30px;height:auto;
  padding:6px 12px;border-radius:999px;border:1px solid var(--divider);background:var(--bg-elv);
  color:var(--t2);font:500 12px/1.4 var(--font);cursor:pointer;transition:all .18s;white-space:nowrap}
.btn:hover{border-color:var(--brand-1);color:var(--brand-1)}
.btn[aria-pressed=true]{background:var(--brand-soft);border-color:var(--brand-1);color:var(--brand-1)}
.count{font-size:12px;color:var(--t3);white-space:nowrap;font-variant-numeric:tabular-nums}
.jump{display:none;height:30px;max-width:38vw;padding:0 6px;border-radius:8px;border:1px solid var(--divider);
  background:var(--bg-elv);color:var(--t2);font:500 12px/1.4 var(--font)}

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
/* 章节号：默认以 "1. " 纯文本呈现（A/C 与旧版一致）；B 主题改成带圈数字。 */
.sec-h h2 .ch-num::after{content:". "}
.toc .gt .ch-num::after{content:". "}
.tools-b,.caps-b{display:none}
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
  .themes{order:3}
  #f-all{order:4}#f-a{order:5}#f-b{order:6}#f-c{order:7}#f-plain{order:8}
  .count{order:9;margin-left:auto}
  .search{order:10;width:auto;max-width:none;flex:1 1 100%;margin-top:2px}
  .search input{height:34px}
  .search kbd{display:none}
  body.compact .jump,body.compact #f-all,body.compact #f-a,body.compact #f-b,body.compact #f-c,
  body.compact #f-plain,body.compact .count{display:none}
  body.compact .search{order:2;flex:1 1 120px;margin-top:0}
  body.compact .themes{order:3}
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
  .btn{padding:4px 8px;font-size:11px}
  .bar h1{flex:1 1 90px;font-size:13px}
  .jump{max-width:32vw}
}

/* ---- theme switcher ---- */
.themes{display:flex;gap:2px;padding:2px;border:1px solid var(--divider);border-radius:999px;background:var(--bg-mute)}
.themes .btn{border:0;background:transparent;min-height:26px;height:auto;padding:4px 9px}
.themes .btn[aria-pressed=true]{background:var(--bg-elv);color:var(--brand-1);box-shadow:0 1px 3px rgba(0,0,0,.12)}

/* ---- layout-only blocks: hidden by default, each theme shows its own ---- */
.masthead,.cover,.toc-mag,.feature,.dash,.hero-c,.statusbar-c{display:none}
.cards{display:block}
.sec-no{display:none}
.mag-head{margin:64px 0 8px;display:flex;align-items:baseline;gap:16px;flex-wrap:wrap}
.mag-head .no{font-family:var(--serif);font-style:italic;font-weight:700;color:var(--brand-1);font-size:20px}
.mag-head h2{font-family:var(--serif);font-weight:900;font-size:clamp(28px,4.6vw,40px);margin:0;line-height:1.25}
.mag-head .en{font-family:var(--serif);letter-spacing:.24em;font-size:12px;color:var(--t3);text-transform:uppercase}
.mag-rule{border:0;border-top:1px solid var(--t1);margin:0}
.mag-rule2{border:0;border-top:1px solid var(--divider);margin:3px 0 0}

/* ================= A 杂志编辑风 =================
   Matches preview A: masthead, cover hero, magazine TOC with intros,
   Chapter 1 feature article (drop cap, two-column lead), editorial cards. */
[data-theme="a"] .toc{display:none}
[data-theme="a"] .hero{display:none}
[data-theme="a"] .hero-c{display:none}
[data-theme="a"] .dash{display:none}
[data-theme="a"] .statusbar-c{display:none}
[data-theme="a"] .masthead{display:block;max-width:1140px;margin:0 auto;padding:26px 22px 0}
[data-theme="a"] .masthead .mh-top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
  font-family:var(--serif);font-size:12px;font-weight:700;letter-spacing:.2em;color:var(--t2);
  border-bottom:1px solid var(--t1);padding-bottom:10px}
[data-theme="a"] .masthead .mh-top .brand{font-weight:900;letter-spacing:.24em;color:var(--t1)}
[data-theme="a"] .cover{display:block;max-width:1140px;margin:0 auto;padding:44px 22px 8px}
[data-theme="a"] .cover .issue-line{display:flex;align-items:center;gap:14px;color:var(--brand-1);
  font-size:13px;letter-spacing:.3em;font-weight:700;margin-bottom:20px}
[data-theme="a"] .cover .issue-line::after{content:"";flex:1;border-top:1px solid var(--divider)}
[data-theme="a"] .cover h1{font-family:var(--serif);font-weight:900;font-size:clamp(44px,8vw,84px);
  line-height:1.15;margin:18px 0}
[data-theme="a"] .cover h1 .thin{display:block;font-weight:400;font-size:.55em;letter-spacing:.18em}
[data-theme="a"] .cover h1 em{font-style:normal;color:var(--brand-1)}
[data-theme="a"] .cover .standfirst{font-family:var(--serif);font-size:18px;line-height:1.9;color:var(--t2);max-width:720px;margin:0}
[data-theme="a"] .cover-meta{display:grid;grid-template-columns:repeat(4,1fr);margin-top:34px;
  border-top:1px solid var(--t1);border-bottom:1px solid var(--divider)}
[data-theme="a"] .cover-meta div{padding:14px 16px 12px;border-left:1px solid var(--divider)}
[data-theme="a"] .cover-meta div:first-child{border-left:none;padding-left:0}
[data-theme="a"] .cover-meta b{font-family:var(--serif);font-size:30px;font-weight:900;display:block;line-height:1.1}
[data-theme="a"] .cover-meta span{font-size:12px;letter-spacing:.18em;color:var(--t3)}
[data-theme="a"] .cover-note{margin-top:14px;font-size:13px;color:var(--t3);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
[data-theme="a"] .cover-note .warn{color:var(--brand-1);font-weight:700}
[data-theme="a"] .toc-mag{display:block;max-width:1140px;margin:0 auto;padding:0 22px}
[data-theme="a"] .toc-item{display:grid;grid-template-columns:86px 1fr auto;gap:18px;align-items:start;
  padding:20px 4px;border-bottom:1px solid var(--divider)}
[data-theme="a"] .toc-item:hover{background:rgba(251,247,236,.7)}
[data-theme="a"] .toc-item:hover a{text-decoration:none}
[data-theme="a"] .toc-num{font-family:var(--serif);font-weight:900;font-size:28px;line-height:1.1;color:var(--t1)}
[data-theme="a"] .toc-num small{display:block;font-family:var(--serif);font-size:11px;font-weight:400;letter-spacing:.2em;color:var(--t3)}
[data-theme="a"] .toc-body h3{font-family:var(--serif);font-size:22px;font-weight:700;margin:0}
[data-theme="a"] .toc-body h3 a{color:var(--t1)}
[data-theme="a"] .toc-body p{color:var(--t2);font-size:15px;line-height:1.9;margin:6px 0 0}
[data-theme="a"] .toc-count{font-size:13px;color:var(--t3);white-space:nowrap}
[data-theme="a"] .feature{display:block;max-width:1140px;margin:26px auto 0;padding:clamp(22px,4.5vw,44px);
  background:var(--bg-elv);border:1px solid var(--divider);position:relative}
[data-theme="a"] .feature::before{content:"特稿 · FEATURE";position:absolute;top:-11px;left:26px;background:var(--bg);
  padding:0 10px;font-size:12px;letter-spacing:.3em;color:var(--brand-1);font-weight:700}
[data-theme="a"] .feature .ch{font-family:var(--serif);font-style:italic;color:var(--t3);font-size:15px}
[data-theme="a"] .feature h3{font-family:var(--serif);font-weight:900;font-size:clamp(26px,4vw,36px);margin:4px 0 6px;line-height:1.3}
[data-theme="a"] .feature .lead{font-family:var(--serif);font-size:17.5px;line-height:2;color:var(--t2);margin:18px 0 0;
  columns:2;column-gap:44px;column-rule:1px solid var(--divider)}
[data-theme="a"] .feature .lead::first-letter{font-family:var(--serif);font-weight:900;font-size:3.1em;float:left;
  line-height:1;padding:6px 10px 0 0;color:var(--brand-1)}
[data-theme="a"] .feature-list{margin:26px 0 0;padding:0;list-style:none;border-top:1px solid var(--divider)}
[data-theme="a"] .feature-list li{display:flex;gap:14px;align-items:baseline;padding:11px 2px;border-bottom:1px solid var(--divider);
  font-family:var(--serif);font-size:16.5px;font-weight:600}
[data-theme="a"] .feature-list li a{color:var(--t1)}
[data-theme="a"] .feature-list .n{font-family:var(--serif);font-style:italic;color:var(--brand-1);font-weight:700;min-width:26px}
[data-theme="a"] .feature-list .g{margin-left:auto;font-family:var(--font);font-size:12px;font-weight:700;color:var(--yellow-1);letter-spacing:.1em;white-space:nowrap}
[data-theme="a"] .shell{display:block}
[data-theme="a"] main{max-width:1140px;margin:0 auto;padding:8px 22px 120px}
[data-theme="a"] section{margin-bottom:64px}
[data-theme="a"] .sec-h{border-bottom:2px solid var(--t1);padding-bottom:10px}
[data-theme="a"] .sec-h h2{font-family:var(--serif);font-weight:900;font-size:34px}
[data-theme="a"] .intro{columns:2;column-gap:36px;column-rule:1px solid var(--divider)}
[data-theme="a"] .intro::first-letter{font-family:var(--serif);font-size:1.9em;line-height:1;color:var(--brand-1);margin-right:2px}
[data-theme="a"] .card{background:var(--bg-elv);border:1px solid var(--divider);border-radius:4px;box-shadow:none}
[data-theme="a"] .card:hover{border-color:var(--brand-1)}
[data-theme="a"] .chead h3{font-family:var(--serif);font-size:20px}
[data-theme="a"] .plain{font-family:var(--serif)}

/* ================= B 极简现代风 =================
   Matches preview B: 288px fixed left sidebar (brand + stats + nav),
   minimal hero with big sans headline + action buttons, simple cards
   indented under the chapter intro, lots of whitespace. */
[data-theme="b"] .masthead{display:none}
[data-theme="b"] .cover{display:none}
[data-theme="b"] .toc-mag{display:none}
[data-theme="b"] .feature{display:none}
[data-theme="b"] .hero-c{display:none}
[data-theme="b"] .dash{display:none}
[data-theme="b"] .statusbar-c{display:none}
[data-theme="b"] .hero{display:block}
[data-theme="b"] .hero{padding-bottom:32px;border-bottom:1px solid var(--divider)}
[data-theme="b"] .hero .eyebrow{letter-spacing:.14em;color:var(--t3);font-size:13px;font-weight:500}
[data-theme="b"] .hero .eyebrow::after{display:none}
[data-theme="b"] .hero h1{font-family:var(--font);font-weight:750;letter-spacing:-.03em;font-size:40px;line-height:1.15}
[data-theme="b"] .hero .lede{font-size:16.5px;line-height:1.8;max-width:620px}
[data-theme="b"] .hero-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}
[data-theme="b"] .btn-primary{background:var(--t1);color:var(--bg);border-color:var(--t1)}
[data-theme="b"] .btn-primary:hover{background:var(--t1);color:var(--bg);text-decoration:none;opacity:.88}

/* ---- hero action buttons: own sizing, never reuse the 30px top-bar pill ----
   Fixed height + line-height:1 clipped CJK glyphs (see screenshot). These are
   inline-flex, auto height, roomy line-height, and wrap on narrow screens. */
.hero-actions .btn{min-height:44px;height:auto;padding:10px 18px;font-size:14px;line-height:1.4;
  white-space:normal;text-align:center}
.hero-actions .btn:not(.btn-primary){color:var(--t1);border-color:var(--divider);background:var(--bg-elv)}
.hero-actions .btn:not(.btn-primary):hover{border-color:var(--brand-1);color:var(--brand-1)}
[data-theme="b"] .toc .brand{font-size:13px;font-weight:700;letter-spacing:.06em;color:var(--t2);margin-bottom:14px}
[data-theme="b"] .toc .book-title{font-family:var(--font);font-weight:750;font-size:26px;line-height:1.25;letter-spacing:-.02em}
[data-theme="b"] .toc .book-sub{font-size:13.5px;line-height:1.8;color:var(--t2);margin:10px 0 16px}
[data-theme="b"] .toc-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding-bottom:16px;margin-bottom:16px;border-bottom:1px solid var(--divider)}
[data-theme="b"] .toc-stats b{display:block;font-size:22px;font-weight:750;line-height:1.2}
[data-theme="b"] .toc-stats span{font-size:11px;color:var(--t3)}
[data-theme="b"] .toc .nav-label{font-size:12px;font-weight:600;color:var(--t3);letter-spacing:.08em;margin-bottom:8px}
[data-theme="b"] .sec-h{border-bottom:1px solid var(--divider)}
[data-theme="b"] .sec-h h2{font-family:var(--font);font-weight:700;letter-spacing:-.02em;font-size:24px}
[data-theme="b"] .chead h3{font-family:var(--font);font-weight:650;letter-spacing:-.01em;font-size:17.5px}
[data-theme="b"] .intro{margin-left:52px}
[data-theme="b"] .cards{display:flex;flex-direction:column;gap:16px;margin-left:52px}
[data-theme="b"] .card{margin-bottom:0;border-radius:14px}
[data-theme="b"] .plain{font-family:var(--font);border-left-width:2px}
[data-theme="b"] .hero .stat b{font-family:var(--font);font-weight:750}

/* ---- B: 整页按预览 B 重做（只影响 B 主题）----
   老顶栏隐藏；左侧导航只剩 8 行章节（带圈数字 + 章名 + 5 条），不展开条目；
   hero 移进主内容列，搜索 + 等级筛选放在 hero 下方；章节头带圈数字；卡片去阴影。 */
/* ---- B: 顶栏恢复，但按 B 的极简审美重做：白底、细线、小字 ----
   之前整条隐藏导致 B 下无法切换主题/跳转/筛选；现在恢复同一条 .bar，
   只在 B 下收窄、去装饰。高度与 A/C 一致：56px（与基础 .bar 的 min-height 相同），
   不再用 48px 矮条。顶栏里已有跳转下拉、全部/只看 A 级/只看说人话、
   搜索框、计数和主题切换；B/C 级按钮只在 B 下显示（见 .f-bc）。 */
[data-theme="b"] .bar{display:flex;background:#fff;border-bottom:1px solid var(--divider-soft);
  padding:0 20px;min-height:56px;gap:8px}
[data-theme="b"] .bar h1{font-family:var(--font);font-size:14px;font-weight:650;letter-spacing:-.01em}
[data-theme="b"] .bar h1 small{display:none}
[data-theme="b"] .bar .jump{display:block;height:32px}
[data-theme="b"] .bar .search{width:200px;max-width:30vw}
[data-theme="b"] .bar .search input{height:32px}
[data-theme="b"] .bar .btn{min-height:28px;padding:4px 10px;font-size:12px}
[data-theme="b"] .bar .count{display:none}
[data-theme="b"] .bar .themes .btn{padding:4px 8px}
.f-bc{display:none}
[data-theme="b"] .f-bc{display:inline-flex}
[data-theme="b"]{--side:288px}
[data-theme="b"] .toc{background:var(--bg)}
[data-theme="b"] .toc .grp{padding:0;margin:0 0 4px;border-bottom:0}
[data-theme="b"] .toc .grp a.entry{display:none}
[data-theme="b"] .toc .gt{display:flex;align-items:center;gap:12px;margin:0;padding:11px 12px;
  border-radius:10px;font-family:var(--font);font-size:15px;font-weight:650;line-height:1.4;
  letter-spacing:0;color:var(--t1)}
[data-theme="b"] .toc .gt .ch-num{flex:none;width:32px;height:32px;border:1px solid var(--divider);
  border-radius:50%;display:inline-flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:600;color:var(--t2);font-variant-numeric:tabular-nums}
[data-theme="b"] .toc .gt .ch-num::after{content:""}
[data-theme="b"] .toc .gt .gt-name{flex:1;min-width:0}
[data-theme="b"] .toc .gt small{margin-left:auto;flex:none;font-size:12.5px;color:var(--t3)}
[data-theme="b"] .toc .gt:hover{background:var(--bg-mute);text-decoration:none}
[data-theme="b"] .toc .gt.active{background:var(--bg-mute);color:var(--t1)}
[data-theme="b"] .hero{max-width:none;margin:0;padding:48px 0 32px}
[data-theme="b"] .tools-b{display:block}
[data-theme="b"] .tools-b .search-b{position:relative;margin:26px 0 14px}
[data-theme="b"] .tools-b .search-b svg{position:absolute;left:14px;top:50%;transform:translateY(-50%);
  width:16px;height:16px;fill:none;stroke:var(--t3);stroke-width:2;pointer-events:none}
[data-theme="b"] .tools-b .search-b input{width:100%;height:46px;padding:0 16px 0 42px;border-radius:12px;
  border:1px solid var(--divider);background:var(--bg-elv);color:var(--t1);font:inherit;font-size:14px}
[data-theme="b"] .tools-b .search-b input:focus{outline:0;border-color:var(--brand-1);box-shadow:0 0 0 3px var(--brand-soft)}
[data-theme="b"] .tools-b .filters-b{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
[data-theme="b"] .tools-b .fbtn{min-height:36px;padding:8px 16px;font-size:13.5px}
[data-theme="b"] .tools-b .fbtn[aria-pressed="true"]{background:var(--t1);color:var(--bg);border-color:var(--t1)}
[data-theme="b"] .tools-b .count{margin-left:auto}
[data-theme="b"] .themes-b{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:22px;
  padding-top:16px;border-top:1px solid var(--divider-soft);font-size:12.5px;color:var(--t3)}
[data-theme="b"] .themes-b .btn{min-height:28px;padding:4px 10px;font-size:12px}
[data-theme="b"] .themes-b .btn[aria-pressed="true"]{background:var(--bg-mute);color:var(--brand-1);border-color:var(--divider)}
[data-theme="b"] .sec-h h2{display:flex;align-items:center;gap:12px;font-size:20px}
[data-theme="b"] .sec-h h2 .ch-num{flex:none;width:36px;height:36px;border:1px solid var(--divider);
  border-radius:50%;display:inline-flex;align-items:center;justify-content:center;
  font-size:15px;font-weight:600;color:var(--t2)}
[data-theme="b"] .sec-h h2 .ch-num::after{content:""}
[data-theme="b"] .card{box-shadow:none}
@media (max-width:1080px){
  [data-theme="b"] .caps-b{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
  [data-theme="b"] .caps-b a{border:1px solid var(--divider);border-radius:999px;padding:8px 14px;
    font-size:13px;color:var(--t1);background:var(--bg-elv)}
  [data-theme="b"] .caps-b a:hover{border-color:var(--brand-1);color:var(--brand-1);text-decoration:none}
}

/* ================= C 深色金融风 =================
   Matches preview C: status bar, KPI dashboard hero (2x2 KPI cards with
   spark bars), chapter ticker, grade-distribution bar, 8-chapter index
   table with grade mini-bars, 2-column cards with red/green P/L fields. */
[data-theme="c"] .masthead{display:none}
[data-theme="c"] .cover{display:none}
[data-theme="c"] .toc-mag{display:none}
[data-theme="c"] .feature{display:none}
[data-theme="c"] .hero{display:none}
[data-theme="c"] .toc{display:none}
[data-theme="c"] body{background-image:linear-gradient(rgba(56,89,140,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(56,89,140,.055) 1px,transparent 1px);background-size:44px 44px}
[data-theme="c"] .statusbar-c{display:flex;max-width:1180px;margin:0 auto;padding:12px 20px 0;gap:16px;align-items:center;
  font-family:var(--mono);font-size:12px;color:var(--t3);flex-wrap:wrap}
[data-theme="c"] .statusbar-c .live-dot{width:8px;height:8px;border-radius:50%;background:var(--green-1);flex:none;
  box-shadow:0 0 0 3px rgba(47,213,152,.18)}
[data-theme="c"] .statusbar-c a{color:var(--t2)}
[data-theme="c"] .statusbar-c nav{display:flex;gap:16px;margin-left:auto}
[data-theme="c"] .hero-c{display:block;max-width:1180px;margin:14px auto 0;padding:0 20px}
[data-theme="c"] .hero-c .panel{border:1px solid var(--divider);border-radius:14px;
  background:linear-gradient(180deg,var(--bg-elv) 0%,#0b111e 100%);overflow:hidden}
[data-theme="c"] .hero-grid{display:grid;grid-template-columns:1.25fr .95fr}
[data-theme="c"] .hero-main{padding:34px 34px 30px;border-right:1px solid var(--divider-soft)}
[data-theme="c"] .hero-kicker{font-family:var(--mono);font-size:12px;letter-spacing:.22em;color:var(--green-1);text-transform:uppercase;margin:0 0 14px}
[data-theme="c"] .hero-c h1{font-family:var(--font);font-size:clamp(34px,5.4vw,54px);line-height:1.12;font-weight:900;letter-spacing:.01em;margin:0 0 14px}
[data-theme="c"] .hero-c h1 .thin{color:var(--t2);font-weight:500}
[data-theme="c"] .hero-sub{color:var(--t2);font-size:16.5px;line-height:1.8;margin:0;max-width:34em}
[data-theme="c"] .hero-sub strong{color:var(--t1)}
[data-theme="c"] .hero-meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:22px}
[data-theme="c"] .hero-meta .chip{font-family:var(--mono);font-size:12px;color:var(--t2);border:1px solid var(--divider);
  border-radius:999px;padding:5px 12px}
[data-theme="c"] .hero-meta .chip b{color:var(--t1)}
[data-theme="c"] .hero-meta .chip .down{color:var(--red-1)}
[data-theme="c"] .hero-meta .chip .up{color:var(--green-1)}
[data-theme="c"] .kpis{display:grid;grid-template-columns:1fr 1fr}
[data-theme="c"] .kpi{padding:24px 24px 20px;border-bottom:1px solid var(--divider-soft)}
[data-theme="c"] .kpi:nth-child(odd){border-right:1px solid var(--divider-soft)}
[data-theme="c"] .kpi:nth-child(3),[data-theme="c"] .kpi:nth-child(4){border-bottom:none}
[data-theme="c"] .kpi-label{font-family:var(--mono);font-size:11.5px;letter-spacing:.16em;color:var(--t3);text-transform:uppercase;
  margin:0 0 8px;display:flex;justify-content:space-between;gap:8px}
[data-theme="c"] .kpi-num{font-family:var(--mono);font-size:clamp(34px,4vw,44px);font-weight:600;line-height:1;color:var(--t1)}
[data-theme="c"] .kpi-num small{font-size:16px;color:var(--t3);font-weight:500}
[data-theme="c"] .kpi-note{color:var(--t3);font-size:13px;margin:9px 0 0;line-height:1.55}
[data-theme="c"] .spark{display:flex;gap:3px;align-items:flex-end;height:28px;margin-top:12px}
[data-theme="c"] .spark i{flex:1;background:#22345c;border-radius:2px 2px 0 0}
[data-theme="c"] .spark i.hot{background:var(--brand-1)}
[data-theme="c"] .dash{display:block;max-width:1180px;margin:0 auto;padding:0 20px}
[data-theme="c"] .ticker{border:1px solid var(--divider);border-top:none;border-radius:0 0 14px 14px;background:var(--bg-alt);overflow:hidden}
[data-theme="c"] .ticker-track{display:flex;gap:0;white-space:nowrap;animation:tick 46s linear infinite;padding:10px 0;width:max-content}
[data-theme="c"] .ticker:hover .ticker-track{animation-play-state:paused}
[data-theme="c"] .ticker span{font-family:var(--mono);font-size:12.5px;color:var(--t3);padding:0 18px}
[data-theme="c"] .ticker span b{color:var(--t2);font-weight:600}
[data-theme="c"] .ticker span .g{color:var(--green-1)}
[data-theme="c"] .ticker span .r{color:var(--red-1)}
[data-theme="c"] .ticker span .a{color:var(--yellow-1)}
@keyframes tick{to{transform:translateX(-50%)}}
[data-theme="c"] .dash-sec{margin-top:28px}
[data-theme="c"] .dash-sec .sec-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:16px}
[data-theme="c"] .dash-sec .sec-head .no{font-family:var(--mono);color:var(--green-1);font-size:13px;letter-spacing:.14em}
[data-theme="c"] .dash-sec .sec-head h2{font-size:24px;font-weight:700;margin:0;letter-spacing:.01em}
[data-theme="c"] .dash-sec .sec-head p{margin:0;color:var(--t3);font-size:14px;margin-left:auto}
[data-theme="c"] .dist{border:1px solid var(--divider);border-radius:12px;padding:22px 24px;background:var(--bg-elv)}
[data-theme="c"] .dist-bar{display:flex;height:34px;border-radius:6px;overflow:hidden;border:1px solid var(--divider)}
[data-theme="c"] .dist-bar div{display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:13px;font-weight:600;min-width:0}
[data-theme="c"] .seg-a{background:var(--green-1);color:#06281c}
[data-theme="c"] .seg-b{background:var(--yellow-1);color:#2b1d05}
[data-theme="c"] .seg-c{background:#33415e;color:var(--t1)}
[data-theme="c"] .dist-legend{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:16px;font-size:13px;color:var(--t2)}
[data-theme="c"] .dist-foot{margin-top:16px;padding-top:14px;border-top:1px dashed var(--divider);color:var(--t3);font-size:13px;
  display:flex;gap:8px 22px;flex-wrap:wrap;font-family:var(--mono)}
[data-theme="c"] .dist-foot b{color:var(--t2)}
[data-theme="c"] .idx-row{display:grid;grid-template-columns:44px 1fr 70px 180px;gap:14px;align-items:center;
  padding:12px 4px;border-bottom:1px solid var(--divider-soft)}
[data-theme="c"] .idx-row .idx-no{font-family:var(--mono);font-size:13px;color:var(--t3)}
[data-theme="c"] .idx-row a{color:var(--t1);font-weight:600}
[data-theme="c"] .idx-row .idx-count{font-family:var(--mono);font-size:12.5px;color:var(--t3);text-align:right}
[data-theme="c"] .minibar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:var(--bg-mute)}
[data-theme="c"] .minibar i{display:block;height:100%}
[data-theme="c"] .shell{display:block}
[data-theme="c"] main{max-width:1180px;margin:0 auto;padding:8px 20px 120px}
[data-theme="c"] .sec-h .sec-no{display:inline;font-family:var(--mono);color:var(--green-1);font-size:13px;letter-spacing:.14em}
[data-theme="c"] .sec-h h2{font-family:var(--font);font-weight:700;font-size:24px}
[data-theme="c"] .sec-h{border-bottom:1px solid var(--divider)}
[data-theme="c"] .cards{display:grid;grid-template-columns:1fr 1fr;gap:16px}
[data-theme="c"] .card{margin-bottom:0;background:var(--bg-elv);border-radius:10px}
[data-theme="c"] .card:hover{border-color:#2b4166}
[data-theme="c"] .num{font-family:var(--mono)}
[data-theme="c"] .chead h3{font-size:19.5px}
[data-theme="c"] .chips,[data-theme="c"] .plain,[data-theme="c"] .src{margin-left:0}
[data-theme="c"] .plain{font-family:var(--font);border-left-color:var(--green-1)}
[data-theme="c"] .fields{margin-left:0;display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--divider);
  border-radius:8px;overflow:hidden}
[data-theme="c"] .fields .f{display:block;padding:12px 14px;border-top:0}
[data-theme="c"] .fields .f b{display:block;font-size:11px;letter-spacing:.1em;margin-bottom:4px}
[data-theme="c"] .f-cost{background:rgba(251,113,133,.06)}
[data-theme="c"] .f-cost b{color:var(--red-1)}
[data-theme="c"] .f-gain{background:rgba(47,213,152,.06)}
[data-theme="c"] .f-gain b{color:var(--green-1)}
[data-theme="c"] .fields .f.note{grid-column:1/-1;background:transparent;border-top:1px solid var(--divider-soft)}
[data-theme="c"] .bar{background:var(--bg)}

/* ---- per-theme mobile ---- */
@media (max-width:820px){
  [data-theme="a"] .cover-meta{grid-template-columns:1fr 1fr}
  [data-theme="a"] .cover-meta div{padding-left:12px}
  [data-theme="a"] .cover-meta div:nth-child(odd){border-left:none;padding-left:0}
  [data-theme="a"] .cover-meta div:nth-child(n+3){border-top:1px solid var(--divider)}
  [data-theme="a"] .toc-item{grid-template-columns:64px 1fr;gap:12px}
  [data-theme="a"] .toc-count{display:none}
  [data-theme="a"] .feature .lead{columns:1}
  [data-theme="a"] .intro{columns:1}
  [data-theme="b"] .hero h1{font-size:32px}
  [data-theme="b"] .intro,[data-theme="b"] .cards{margin-left:0}
  [data-theme="c"] .hero-grid{grid-template-columns:1fr}
  [data-theme="c"] .hero-main{border-right:none;border-bottom:1px solid var(--divider-soft);padding:26px 22px 24px}
  [data-theme="c"] .kpi{padding:18px 16px 16px}
  [data-theme="c"] .cards{grid-template-columns:1fr}
  [data-theme="c"] .dist-legend{grid-template-columns:1fr}
  [data-theme="c"] .idx-row{grid-template-columns:34px 1fr 56px}
  [data-theme="c"] .idx-row .minibar{display:none}
  [data-theme="c"] .ticker-track{animation:none;flex-wrap:wrap;white-space:normal;width:auto}
  [data-theme="c"] .kpi-label .delta{display:none}
  [data-theme="c"] .kpi-label{letter-spacing:.08em}
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
            cls = "f-cost" if k == "成本" else "f-gain"
            rows.append('<div class="f %s"><b>%s</b><div>%s</div></div>' % (cls, k, inline(f[k])))
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
const q2=document.getElementById('q2');
const cnt=document.getElementById('cnt');
const cnt2=document.getElementById('cnt2');
const jump=document.getElementById('jump');
const fAll=document.getElementById('f-all');
const fA=document.getElementById('f-a');
const fB=document.getElementById('f-b');
const fC=document.getElementById('f-c');
const fP=document.getElementById('f-plain');
const themeBtns=[...document.querySelectorAll('[data-theme-opt]')];
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
  if(cnt2) cnt2.textContent=shown+' / '+cards.length+' 条';
  if(term) document.querySelectorAll('main section').forEach(s=>markAll(s,term));
  document.querySelectorAll('.toc a').forEach(a=>{
    const el=document.getElementById(a.getAttribute('href').slice(1));
    a.classList.toggle('hidden',!el||el.classList.contains('hidden'));
  });
}
let timer=null;
function onSearch(src){
  const other=(src===q)?q2:q;
  if(other&&other.value!==src.value) other.value=src.value;
  clearTimeout(timer);timer=setTimeout(apply,90);
}
q.addEventListener('input',()=>onSearch(q));
if(q2) q2.addEventListener('input',()=>onSearch(q2));
const fB2=document.getElementById('f-b2');
const fC2=document.getElementById('f-c2');
const fAll2=document.getElementById('f-all2');
const fA2=document.getElementById('f-a2');
const fP2=document.getElementById('f-plain2');
function setMode(mode){
  grade=(mode==='A'||mode==='B'||mode==='C')?mode:null;
  plainOnly=(mode==='plain');
  document.body.classList.toggle('plain-only',plainOnly);
  const map={'all':[fAll,fAll2],'A':[fA,fA2],'B':[fB,fB2],'C':[fC,fC2],'plain':[fP,fP2]};
  Object.keys(map).forEach(k=>map[k].forEach(b=>{if(b) b.setAttribute('aria-pressed',String(k===mode));}));
  apply();
}
fAll.onclick=()=>setMode('all');
fA.onclick=()=>setMode('A');
if(fB) fB.onclick=()=>setMode('B');
if(fC) fC.onclick=()=>setMode('C');
fP.onclick=()=>setMode('plain');
if(fAll2) fAll2.onclick=()=>setMode('all');
if(fA2) fA2.onclick=()=>setMode('A');
if(fB2) fB2.onclick=()=>setMode('B');
if(fC2) fC2.onclick=()=>setMode('C');
if(fP2) fP2.onclick=()=>setMode('plain');
fAll.setAttribute('aria-pressed','true');

if(jump){
  jump.addEventListener('change',()=>{
    const el=document.getElementById(jump.value);
    if(el) el.scrollIntoView({block:'start'});
  });
}
/* 主题切换：A 杂志 / B 极简 / C 深色。只改呈现，不改内容。
   已保存的选择优先；无保存时，系统深色偏好用 C（深色主题）作 tie-breaker，否则默认 B。 */
const THEME_COLORS={a:'#f6efe1',b:'#ffffff',c:'#070b12'};
function setTheme(name){
  if(!THEME_COLORS[name]) name='b';
  document.documentElement.setAttribute('data-theme',name);
  requestAnimationFrame(syncBar);
  themeBtns.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeOpt===name)));
  const mc=document.querySelector('meta[name="theme-color"]');
  if(mc) mc.setAttribute('content',THEME_COLORS[name]);
  try{localStorage.setItem('htib-theme',name);}catch(e){}
}
themeBtns.forEach(b=>b.addEventListener('click',()=>setTheme(b.dataset.themeOpt)));
try{
  const saved=localStorage.getItem('htib-theme');
  if(saved&&THEME_COLORS[saved]) setTheme(saved);
  else if(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches) setTheme('c');
  else setTheme('b');
}catch(e){setTheme('b');}
document.addEventListener('keydown',e=>{
  const qs=(document.documentElement.getAttribute('data-theme')==='b'&&q2)?q2:q;
  if(e.key==='/'&&document.activeElement!==qs&&!/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)){
    e.preventDefault();qs.focus();
  }
  if(e.key==='Escape'&&document.activeElement===qs){q.value='';if(q2)q2.value='';apply();qs.blur();}
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
function setActiveGt(secId){
  if(document.documentElement.getAttribute('data-theme')!=='b') return;
  document.querySelectorAll('.toc .gt').forEach(g=>g.classList.toggle('active',g.getAttribute('href')==='#'+secId));
}
const io=new IntersectionObserver(es=>{
  es.forEach(e=>{ if(e.isIntersecting){
    if(e.target.classList.contains('card')){
      links.forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+e.target.id));
      const sec=e.target.closest('section');
      if(sec) setActiveGt(sec.id);
    } else if(e.target.tagName==='SECTION'){
      if(jump) jump.value=e.target.id;
      setActiveGt(e.target.id);
    }
  }});
},{rootMargin:'-70px 0px -75% 0px'});
cards.forEach(c=>io.observe(c));
if(jump) secs.forEach(s=>io.observe(s));
"""


def main():
    sec_toc = []
    sec_html = []
    chapters = []
    jump_opts = []
    total = 0
    grade_cnt = {"A": 0, "B": 0, "C": 0}
    link_total = 0

    for n in SECTIONS:
        p = find_file(n)
        title, intro, entries = parse(p)
        _m = re.match(r"^(\d+)\.\s*(.*)$", title)
        _num, _name = (int(_m.group(1)), _m.group(2)) if _m else (n, title)
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
            links.append('<a class="entry" href="#s%d-%d" title="%s"><span class="dot d%d"></span>'
                         '<i>%d</i><span>%s</span></a>'
                         % (n, e["no"], html.escape(e["title"], quote=True),
                            RATIO_ORDER.get(r, 2), e["no"], html.escape(short)))
        sec_toc.append('<div class="grp"><a class="gt" href="#sec%d"><span class="ch-num">%d</span><span class="gt-name">%s</span><small>%d 条</small></a>%s</div>'
                       % (n, _num, inline(_name), len(entries), "".join(links)))
        sec_html.append(
            '<section id="sec%d"><div class="sec-h"><span class="sec-no">/ %02d</span><h2><span class="ch-num">%d</span><span class="ch-name">%s</span></h2>'
            '<span class="meta">%d 条</span></div>%s<div class="cards">%s</div></section>'
            % (n, n, _num, inline(_name), len(entries),
               ('<p class="intro">%s</p>' % inline(" ".join(intro))) if intro else "",
               "".join(cards)))
        jump_opts.append('<option value="sec%d">%s</option>' % (n, html.escape(title)))
        chg = {"A": 0, "B": 0, "C": 0}
        ch_entries = []
        for e in entries:
            gg = (e["fields"].get("证据等级") or "?").strip()[:1]
            if gg in chg:
                chg[gg] += 1
            ch_entries.append((e["title"], gg))
        chapters.append({"n": n, "title": title, "intro": " ".join(intro),
                         "grades": chg, "entries": ch_entries})

    rev, rev_date = source_rev()

    head = ('<!DOCTYPE html><html lang="zh-CN" data-theme="b"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="color-scheme" content="light dark">'
            '<meta name="theme-color" content="#ffffff">'
            '<script>try{var _t=localStorage.getItem("htib-theme");if(_t==="a"||_t==="b"||_t==="c"){document.documentElement.setAttribute("data-theme",_t);}else if(window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches){document.documentElement.setAttribute("data-theme","c");}}catch(e){}</script>'
            '<meta name="description" content="《高性价比投资指南》%s，共 %d 条投资中容易犯的错误，'
            '每条标注成本、代价、证据等级（A/B/C）与来源。单文件、零依赖、可离线阅读。仅供投资者教育，不构成投资建议。">'
            '<title>高性价比投资指南 · %s</title><style>%s</style></head><body>'
            % (SCOPE, total, SCOPE, CSS))

    bar = ('<header class="bar"><h1>高性价比投资指南<small>%s</small></h1>'
           '<select class="jump" id="jump" aria-label="跳转到某一节">%s</select>'
           '<div class="spacer"></div>'
           '<button class="btn" id="f-all">全部</button>'
           '<button class="btn" id="f-a">只看 A 级</button>'
           '<button class="btn f-bc" id="f-b">B 级</button>'
           '<button class="btn f-bc" id="f-c">C 级</button>'
           '<button class="btn" id="f-plain">只看说人话</button>'
           '<div class="search"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/>'
           '<path d="M20 20l-3.5-3.5"/></svg>'
           '<input id="q" type="search" placeholder="搜索标题、说人话、收益…" autocomplete="off">'
           '<kbd>/</kbd></div>'
           '<span class="count" id="cnt">%d / %d 条</span>'
           '<div class="themes" role="group" aria-label="主题切换">'
           '<button class="btn" data-theme-opt="a" aria-pressed="false">A 杂志编辑风</button>'
           '<button class="btn" data-theme-opt="b" aria-pressed="true">B 极简现代风</button>'
           '<button class="btn" data-theme-opt="c" aria-pressed="false">C 深色金融风</button></div></header>' % (
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

    # --- A 杂志编辑风: masthead + cover ---
    masthead = ('<div class="masthead"><div class="mh-top">'
                '<span class="brand">HOW TO INVEST BETTER</span>'
                '<span>第 01 期 · 投资避坑特辑</span></div></div>')
    cover = ('<header class="cover"><div class="issue-line"><span>特辑 · SPECIAL ISSUE</span></div>'
             '<h1><span class="thin">高 性 价 比</span>投资<em>指南</em></h1>'
             '<p class="standfirst">总结投资中容易犯的错误，让新手投资者阅读完以后能有所受益——'
             '不追热点，不赌运气，先把学费省下来。</p>'
             '<div class="cover-meta">'
             '<div><b>%d</b><span>全书章节</span></div>'
             '<div><b>%d</b><span>错误条目</span></div>'
             '<div><b>%d</b><span>A 级证据条目</span></div>'
             '<div><b>5</b><span>每章条目</span></div></div>'
             '<div class="cover-note"><span>本页 8 章 40 条，文字未作改动。</span>'
             '<span class="warn">仅供投资者教育，不构成投资建议。</span></div></header>'
             % (len(SECTIONS), total, grade_cnt["A"]))
    # --- B 极简现代风: minimal hero (preview B copy) ---
    hero = ('<header class="hero">'
            '<h1>少犯错，<br>就是高性价比。</h1>'
            '<p class="lede">投资亏钱，很多时候不是选错了标的，而是先犯了一个本可以避开的错误。'
            '本书把 40 个常见错误按类型分成 8 章，每条都标了证据等级、代价和“说人话”——先看错在哪，再想怎么改。</p>'
            '<div class="hero-actions">'
            '<a class="btn btn-primary" href="#sec1">从第 1 章开始看</a>'
            '<a class="btn" href="#sec4">直接看费用与税</a></div></header>')
    # --- C 深色金融风: status bar + KPI dashboard hero ---
    spark1 = "".join('<i style="height:%d%%"%s></i>' % (h, ' class="hot"' if hot else "")
                     for h, hot in [(55, False), (55, False), (55, False), (55, False),
                                    (55, False), (55, False), (55, False), (55, True)])
    spark2 = "".join('<i style="height:%d%%"%s></i>' % (h, ' class="hot"' if hot else "")
                     for h, hot in [(40, False), (52, False), (47, False), (66, False),
                                    (58, False), (74, False), (69, False), (88, True)])
    spark3 = "".join('<i style="height:%d%%"%s></i>' % (h, ' class="hot"' if hot else "")
                     for h, hot in [(80, True), (34, False), (72, True), (90, True),
                                    (64, True), (30, False), (84, True), (70, True)])
    spark4 = "".join('<i style="height:%d%%"%s></i>' % (h, ' class="hot"' if hot else "")
                     for h, hot in [(52, False), (74, False), (52, False), (76, False),
                                    (52, False), (76, False), (64, False), (50, False)])
    statusbar_c = ('<div class="statusbar-c"><span class="live-dot"></span>'
                   '<span>Investor Error Database · 投资者错误数据库</span>'
                   '<nav><a href="#dash">章节索引</a><a href="#sec1">错误条目</a>'
                   '<a href="https://github.com/xledoo/how-to-invest-better" target="_blank" rel="noopener">GitHub ↗</a></nav></div>')
    hero_c = ('<div class="hero-c"><div class="panel"><div class="hero-grid">'
              '<div class="hero-main"><p class="hero-kicker">Investor Error Database · 投资者错误数据库</p>'
              '<h1>高性价比<br>投资指南 <span class="thin">/ 全书总览</span></h1>'
              '<p class="hero-sub">总结<strong>投资中容易犯的错误</strong>，让新手投资者阅读完以后能有所受益。'
              '全书按错误类型分成 8 章，每条都标了证据等级、代价和“说人话”——先看数据，再读条目。</p>'
              '<div class="hero-meta">'
              '<span class="chip">风险 <b class="down">&nbsp;▼ 红</b></span>'
              '<span class="chip">收益 <b class="up">&nbsp;▲ 绿</b></span></div></div>'
              '<div class="kpis">'
              '<div class="kpi"><p class="kpi-label">章节 Chapters <span class="delta">全覆盖</span></p>'
              '<p class="kpi-num">%d<small> 章</small></p><p class="kpi-note">从心态与认知，到个股与估值</p>'
              '<div class="spark">%s</div></div>'
              '<div class="kpi"><p class="kpi-label">错误条目 Errors <span class="delta">已收录</span></p>'
              '<p class="kpi-num">%d<small> 条</small></p><p class="kpi-note">每章 5 条，每条一张卡片</p>'
              '<div class="spark">%s</div></div>'
              '<div class="kpi"><p class="kpi-label">A 级证据 A-Grade <span class="delta">优先读</span></p>'
              '<p class="kpi-num">%d<small> 条 · %d%%</small></p><p class="kpi-note">有长期数据或经典研究支撑</p>'
              '<div class="spark">%s</div></div>'
              '<div class="kpi"><p class="kpi-label">B + C 级合计 <span class="delta">看口径</span></p>'
              '<p class="kpi-num">%d<small> 条 · %d%%</small></p><p class="kpi-note">有支撑但要看条件，或属教育共识</p>'
              '<div class="spark">%s</div></div>'
              '</div></div></div></div>'
              % (len(SECTIONS), spark1, total, spark2,
                 grade_cnt["A"], round(100 * grade_cnt["A"] / total) if total else 0, spark3,
                 grade_cnt["B"] + grade_cnt["C"],
                 round(100 * (grade_cnt["B"] + grade_cnt["C"]) / total) if total else 0, spark4))
    # --- C dash: ticker + distribution + index table ---
    tick_notes = [("▲ 先稳心态", "g"), ("▼ 别踩反节奏", "r"), ("▲ 摊开风险", "g"),
                  ("◆ 看不见的对手", "a"), ("▼ 双向放大", "r"), ("◆ 先查再听", "a"),
                  ("▲ 看基准不看排名", "g"), ("▲ 先懂业务再谈价格", "g")]
    tick_items = "".join(
        '<span><b>%02d %s</b> <i class="%s">%s</i></span>' % (c["n"], html.escape(c["title"]), tick_notes[i][1], tick_notes[i][0])
        for i, c in enumerate(chapters))
    dist_w = lambda x: round(100 * x / total) if total else 0
    idx_rows = []
    for c in chapters:
        g = c["grades"]
        idx_rows.append(
            '<div class="idx-row"><span class="idx-no">%02d</span>'
            '<a href="#sec%d">%s</a><span class="idx-count">%d 条</span>'
            '<span class="minibar"><i style="width:%d%%;background:var(--green-1)"></i>'
            '<i style="width:%d%%;background:var(--yellow-1)"></i>'
            '<i style="width:%d%%;background:#33415e"></i></span></div>'
            % (c["n"], c["n"], html.escape(c["title"]), len(c["entries"]),
               dist_w(g["A"]) * 5 // 1 if False else round(100 * g["A"] / 5),
               round(100 * g["B"] / 5), round(100 * g["C"] / 5)))
    dash = ('<div class="dash" id="dash">'
            '<div class="ticker" aria-hidden="true"><div class="ticker-track">%s%s</div></div>'
            '<section class="dash-sec"><div class="sec-head"><span class="no">/ 01</span><h2>证据等级分布</h2>'
            '<p>40 条的成色，一眼看清</p></div>'
            '<div class="dist"><div class="dist-bar">'
            '<div class="seg-a" style="width:%d%%">A %d</div>'
            '<div class="seg-b" style="width:%d%%">B %d</div>'
            '<div class="seg-c" style="width:%d%%">C %d</div></div>'
            '<div class="dist-legend"><span>A 级：有长期数据或经典研究支撑</span>'
            '<span>B 级：有支撑，但要看条件</span><span>C 级：属教育共识，谨慎引用</span></div>'
            '<div class="dist-foot"><span>合计 <b>%d 条</b></span><span>A <b>%d</b></span>'
            '<span>B <b>%d</b></span><span>C <b>%d</b></span></div></div></section>'
            '<section class="dash-sec"><div class="sec-head"><span class="no">/ 02</span><h2>章节索引</h2>'
            '<p>每章 5 条 · 点击直达</p></div>%s</section></div>'
            % (tick_items, tick_items, dist_w(grade_cnt["A"]), grade_cnt["A"],
               dist_w(grade_cnt["B"]), grade_cnt["B"], dist_w(grade_cnt["C"]), grade_cnt["C"],
               total, grade_cnt["A"], grade_cnt["B"], grade_cnt["C"], "".join(idx_rows)))
    # --- A 杂志 TOC + Chapter 1 feature ---
    toc_items = "".join(
        '<article class="toc-item"><div class="toc-num">%02d<small>CHAPTER</small></div>'
        '<div class="toc-body"><h3><a href="#sec%d">%s</a></h3><p>%s</p></div>'
        '<div class="toc-count">%d 条</div></article>'
        % (c["n"], c["n"], html.escape(c["title"]), inline(c["intro"]), len(c["entries"]))
        for c in chapters)
    toc_mag = ('<div class="toc-mag"><div class="mag-head"><span class="no">№ 01</span><h2>本期目录</h2>'
               '<span class="en">Contents</span></div><hr class="mag-rule"><hr class="mag-rule2">%s</div>' % toc_items)
    ch1 = chapters[0] if chapters else {"n": 1, "title": "", "intro": "", "entries": []}
    feat_items = "".join(
        '<li><span class="n">%d.</span><a href="#s%d-%d">%s</a><span class="g">%s 级证据</span></li>'
        % (i + 1, ch1["n"], i + 1, html.escape(ti), gr)
        for i, (ti, gr) in enumerate(ch1["entries"]))
    feature = ('<div class="toc-mag"><div class="mag-head"><span class="no">№ 02</span><h2>本期特稿</h2>'
               '<span class="en">Feature</span></div><hr class="mag-rule"><hr class="mag-rule2">'
               '<section class="feature"><span class="ch">Chapter 01 — 第一章</span><h3>%s</h3>'
               '<p class="lead">%s</p><ul class="feature-list">%s</ul></section></div>'
               % (html.escape(ch1["title"]), inline(ch1["intro"]), feat_items))
    toc_head = ('<div class="brand">How to Invest Better</div>'
                '<div class="book-title">高性价比<br>投资指南</div>'
                '<p class="book-sub">总结投资中容易犯的错误，让新手投资者阅读完以后能有所受益。</p>'
                '<div class="toc-stats"><div><b>%d</b><span>章节</span></div>'
                '<div><b>%d</b><span>条目</span></div>'
                '<div><b>%d</b><span>A 级证据</span></div></div>'
                '<div class="nav-label">目录 — 全书 %d 节</div>'
                % (len(SECTIONS), total, grade_cnt["A"], len(SECTIONS)))
    # --- B 极简现代风: hero 下方的工具区（搜索 + 等级筛选 + 手机胶囊导航 + 主题切换）。
    # 只在 B 主题下显示；A/C 的搜索/筛选仍在顶栏里，不受影响。 ---
    caps_b = "".join('<a href="#sec%d">%s</a>'
                     % (c["n"], html.escape(re.sub(r"^\d+\.\s*", "", c["title"])))
                     for c in chapters)
    tools_b = ('<div class="tools-b">'
               '<div class="search-b"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/>'
               '<path d="M20 20l-3.5-3.5"/></svg>'
               '<input id="q2" type="search" placeholder="搜索错误、关键词… 例如：费率 / 杠杆 / 追涨" autocomplete="off"></div>'
               '<div class="filters-b" role="group" aria-label="等级筛选">'
               '<button class="btn fbtn" id="f-all2" aria-pressed="true">全部等级</button>'
               '<button class="btn fbtn" id="f-a2" aria-pressed="false">只看 A 级</button>'
               '<button class="btn fbtn" id="f-b2" aria-pressed="false">B 级</button>'
               '<button class="btn fbtn" id="f-c2" aria-pressed="false">C 级</button>'
               '<button class="btn fbtn" id="f-plain2" aria-pressed="false">只看说人话</button>'
               '<span class="count" id="cnt2">%d / %d 条</span></div>'
               '<nav class="caps-b" aria-label="章节导航">%s</nav>'
               '<div class="themes-b" role="group" aria-label="主题切换"><span>主题切换</span>'
               '<button class="btn" data-theme-opt="a" aria-pressed="false">A 杂志编辑风</button>'
               '<button class="btn" data-theme-opt="b" aria-pressed="true">B 极简现代风</button>'
               '<button class="btn" data-theme-opt="c" aria-pressed="false">C 深色金融风</button></div></div>'
               % (total, total, caps_b))
    shell = ('<div class="shell"><aside class="toc">%s</aside><main>%s%s'
             '<div class="empty hidden" id="empty">没有匹配的条目</div>%s'
             '</main></div>'
             '<button id="top" title="回到顶部" aria-label="回到顶部">↑</button>'
             % (toc_head + "".join(sec_toc), hero + tools_b, "".join(sec_html), footer))

    # 注意：JS 字符串只含脚本体，<script> 开合标签在这里拼。
    # 之前漏了开标签，导致整段 JS 被当纯文本渲染在页面底部、脚本从未执行。
    out = head + bar + masthead + cover + statusbar_c + hero_c + dash + toc_mag + feature + shell + "<script>" + JS + "</script></body></html>"

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
