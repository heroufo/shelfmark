# -*- coding: utf-8 -*-
"""生成小红书图文 v4（最终版）：5 张 1080x1440 卡片。"""
import sys, os, base64, subprocess, random

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

ROOT = r"C:\Users\Administrator\WorkBuddy\图书管理"
OUT = os.path.join(ROOT, "promo", "xiaohongshu")
HTML_DIR = r"C:\Temp\xhs\html"
PROFILE = r"C:\Temp\xhs\edge-profile"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

for d in (OUT, HTML_DIR, PROFILE):
    os.makedirs(d, exist_ok=True)

LOGO_B64 = base64.b64encode(
    open(os.path.join(ROOT, "static", "images", "shelfmark_logo.png"), "rb").read()
).decode()

FONT = "'HarmonyOS Sans SC','Microsoft YaHei UI','Microsoft YaHei','Noto Sans SC',sans-serif"
EMOJI = "'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif"

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1440px;overflow:hidden}
body{font-family:__FONT__;background:#0B0E14;-webkit-font-smoothing:antialiased}
.card{position:relative;width:1080px;height:1440px;overflow:hidden;
  background:radial-gradient(125% 82% at 12% -6%,#1D2646 0%,#131A2B 46%,#0A0D14 100%);
  padding:88px 84px;display:flex;flex-direction:column}
.glow{position:absolute;border-radius:50%;filter:blur(100px);pointer-events:none;z-index:0}
.g1{width:820px;height:820px;right:-280px;top:-260px;
  background:radial-gradient(circle,rgba(129,140,248,.50),transparent 66%)}
.g2{width:680px;height:680px;left:-260px;bottom:-260px;
  background:radial-gradient(circle,rgba(34,211,238,.26),transparent 66%)}
.grid{position:absolute;inset:0;pointer-events:none;z-index:0;opacity:.55;
  background-image:linear-gradient(rgba(255,255,255,.030) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,.030) 1px,transparent 1px);
  background-size:72px 72px}

/* ---------- 通用排版 ---------- */
.pill{display:inline-flex;align-items:center;gap:10px;height:56px;padding:0 26px;border-radius:28px;
  font-size:24px;font-weight:700;letter-spacing:.05em;color:#C7D2FE;
  background:rgba(129,140,248,.14);border:1.5px solid rgba(129,140,248,.38)}
.pill.dim{color:#7E8BA6;background:rgba(255,255,255,.045);border-color:rgba(255,255,255,.10)}
.dot{width:11px;height:11px;border-radius:50%;background:#818CF8;
  box-shadow:0 0 14px 3px rgba(129,140,248,.85)}
.kicker{display:flex;align-items:center;gap:14px;font-size:25px;font-weight:700;
  letter-spacing:.17em;color:#818CF8;margin-bottom:24px}
.kicker .bar{width:52px;height:4px;border-radius:2px;
  background:linear-gradient(90deg,#818CF8,#22D3EE)}
h2.title{font-size:78px;line-height:1.19;font-weight:800;color:#F3F7FE;letter-spacing:-.012em}
.sub{font-size:30px;line-height:1.58;color:#8A98B2;font-weight:400;margin-top:20px}
.foot{margin-top:auto;display:flex;align-items:center;gap:20px;
  padding-top:32px;border-top:1.5px solid rgba(255,255,255,.08);
  font-size:25px;color:#68758E;position:relative;z-index:3}
.logo{width:60px;height:60px;border-radius:16px;display:block}
.head{position:relative;z-index:3}

/* ---------- 1 封面 ---------- */
.cover-top{display:flex;gap:16px;position:relative;z-index:3}
.cover-title{position:relative;z-index:3;margin-top:118px;
  font-size:130px;line-height:1.15;font-weight:800;letter-spacing:-.028em;
  color:#F6F9FF;text-shadow:0 10px 44px rgba(0,0,0,.55)}
.cover-title em{font-style:normal;background:linear-gradient(100deg,#A5B4FC 0%,#818CF8 38%,#22D3EE 100%);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.cover-sub{position:relative;z-index:3;margin-top:30px;font-size:32px;line-height:1.6;
  color:#93A2BE;font-weight:400}
.spines{position:absolute;left:0;right:0;bottom:196px;height:430px;display:flex;
  align-items:flex-end;justify-content:space-between;padding:0 84px;z-index:1;
  -webkit-mask-image:linear-gradient(to top,rgba(0,0,0,.95) 8%,rgba(0,0,0,.34) 62%,transparent 100%);
  mask-image:linear-gradient(to top,rgba(0,0,0,.95) 8%,rgba(0,0,0,.34) 62%,transparent 100%)}
.spines i{display:block;width:46px;border-radius:10px 10px 4px 4px;
  background:linear-gradient(180deg,rgba(139,148,255,var(--o)),rgba(56,220,255,var(--o2)))}
.cover-foot{position:relative;z-index:3;margin-top:auto;display:flex;align-items:center;gap:22px;
  padding-top:34px;border-top:1.5px solid rgba(255,255,255,.085)}
.cover-foot .logo{width:82px;height:82px;border-radius:22px;
  box-shadow:0 16px 44px rgba(129,140,248,.45)}
.brand{font-size:39px;font-weight:800;color:#EAF0FC;letter-spacing:.008em}
.brand-url{font-size:24px;color:#6D7B96;margin-top:6px;font-weight:400}

/* ---------- 2 对比 ---------- */
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:46px;flex:1;
  position:relative;z-index:3}
.col{border-radius:32px;padding:38px 30px;display:flex;flex-direction:column;
  justify-content:center}
.col.bad{background:rgba(255,255,255,.035);border:1.5px solid rgba(255,255,255,.085)}
.col.good{background:linear-gradient(160deg,rgba(129,140,248,.18),rgba(34,211,238,.07));
  border:1.5px solid rgba(129,140,248,.46);box-shadow:0 24px 64px rgba(99,102,241,.26)}
.col-h{font-size:31px;font-weight:800;margin-bottom:30px;display:flex;align-items:center;gap:13px}
.col.bad .col-h{color:#7C8AA5}
.col.good .col-h{color:#C7D2FE}
.item{display:flex;gap:14px;margin-bottom:26px;font-size:27px;line-height:1.5;font-weight:400}
.col.bad .item{color:#75839E}
.col.good .item{color:#DDE5F5}
.item:last-child{margin-bottom:0}
.mk{flex:0 0 auto;width:33px;height:33px;border-radius:11px;display:flex;align-items:center;
  justify-content:center;font-size:20px;font-weight:800;margin-top:4px}
.col.bad .mk{background:rgba(255,255,255,.07);color:#8A97B0}
.col.good .mk{background:linear-gradient(140deg,#818CF8,#6366F1);color:#fff;
  box-shadow:0 7px 20px rgba(99,102,241,.5)}

/* ---------- 3 功能 ---------- */
.feats{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:repeat(3,1fr);
  gap:22px;margin-top:46px;flex:1;position:relative;z-index:3}
.feat{border-radius:28px;padding:30px 30px;background:rgba(255,255,255,.048);
  border:1.5px solid rgba(255,255,255,.088);display:flex;gap:20px;align-items:center}
.feat .ic{flex:0 0 auto;width:78px;height:78px;border-radius:22px;display:flex;
  align-items:center;justify-content:center;font-size:36px;font-family:__EMOJI__;
  background:linear-gradient(140deg,rgba(129,140,248,.28),rgba(34,211,238,.13));
  border:1.5px solid rgba(129,140,248,.32)}
.feat .fx{flex:1;min-width:0}
.feat .fn{font-size:31px;font-weight:800;color:#E8EFFB;margin-bottom:10px}
.feat .fd{font-size:23px;line-height:1.48;color:#8492AC;font-weight:400}

/* ---------- 4 界面预览 ---------- */
.win{margin-top:44px;flex:1;border-radius:26px;overflow:hidden;position:relative;z-index:3;
  background:#0E1117;border:1.5px solid rgba(255,255,255,.11);
  box-shadow:0 34px 80px rgba(0,0,0,.6);display:flex}
.side{width:196px;flex:0 0 auto;background:#0F1420;border-right:1.5px solid rgba(255,255,255,.07);
  padding:24px 16px;display:flex;flex-direction:column;gap:5px}
.side .sb{display:flex;align-items:center;gap:10px;font-size:15px;font-weight:800;
  color:#E4EBF9;padding:8px 10px 15px}
.side .sb img{width:26px;height:26px;border-radius:7px}
.snav{font-size:13.5px;color:#8B99B4;padding:8px 10px;border-radius:9px;font-weight:500}
.snav.on{background:rgba(129,140,248,.15);color:#B9C4FB;font-weight:700;
  border:1px solid rgba(129,140,248,.3)}
.snav.sec{color:#5C6A85;font-size:11.5px;font-weight:800;letter-spacing:.13em;
  padding:15px 10px 6px}
.snav.off{color:#7A88A3}
.snav.pub{margin-top:auto;text-align:center;font-weight:700;color:#7DD3F0;
  background:rgba(34,211,238,.10);border:1px solid rgba(34,211,238,.26)}
.main{flex:1;padding:22px 24px;display:flex;flex-direction:column;min-width:0}
.searchbar{display:flex;gap:10px;align-items:center;margin-bottom:18px;flex:0 0 auto}
.searchbar .s{flex:1;height:38px;border-radius:11px;background:rgba(255,255,255,.055);
  border:1px solid rgba(255,255,255,.09);display:flex;align-items:center;
  padding:0 14px;font-size:13.5px;color:#6D7B96;gap:9px}
.searchbar .b{height:38px;padding:0 17px;border-radius:11px;
  background:linear-gradient(140deg,#818CF8,#6366F1);font-size:13.5px;font-weight:700;
  color:#fff;display:flex;align-items:center;flex:0 0 auto}
.searchbar .b.ghost{background:rgba(255,255,255,.06);color:#A6B3CB;
  border:1px solid rgba(255,255,255,.1)}
.wall{flex:1;display:grid;grid-template-columns:repeat(4,1fr);
  grid-template-rows:repeat(3,1fr);gap:17px;min-height:0}
.bk{border-radius:11px;overflow:hidden;position:relative;min-height:0;
  box-shadow:0 9px 24px rgba(0,0,0,.45);display:flex;flex-direction:column;
  justify-content:center;padding:14px 12px}
.bk .bt{font-size:15.5px;font-weight:800;line-height:1.3;color:#fff;
  text-shadow:0 2px 8px rgba(0,0,0,.7)}
.bk .ba{font-size:11.5px;color:rgba(255,255,255,.74);margin-top:6px;
  text-shadow:0 2px 6px rgba(0,0,0,.7)}
.bk .spn{position:absolute;left:0;top:0;bottom:0;width:6px}
.stat{display:flex;gap:14px;margin-top:18px;flex:0 0 auto}
.stat div{flex:1;border-radius:13px;background:rgba(255,255,255,.05);
  border:1px solid rgba(255,255,255,.085);padding:11px 15px}
.stat .v{font-size:23px;font-weight:800;color:#C9D4FB}
.stat .k{font-size:11.5px;color:#74829D;margin-top:3px}

/* ---------- 5 步骤 ---------- */
.steps{margin-top:50px;flex:1;display:flex;flex-direction:column;justify-content:center;
  position:relative;z-index:3}
.step{display:flex;align-items:center;gap:32px;padding:42px 38px;border-radius:30px;
  background:rgba(255,255,255,.048);border:1.5px solid rgba(255,255,255,.088);
  margin-bottom:24px}
.step:last-child{margin-bottom:0}
.step .num{flex:0 0 auto;width:94px;height:94px;border-radius:26px;display:flex;
  align-items:center;justify-content:center;font-size:47px;font-weight:800;color:#fff;
  background:linear-gradient(140deg,#818CF8,#6366F1);box-shadow:0 14px 36px rgba(99,102,241,.48)}
.step .st{font-size:38px;font-weight:800;color:#F0F5FD;margin-bottom:8px}
.step .sd{font-size:25px;line-height:1.48;color:#8492AC;font-weight:400}
.note{margin-top:32px;padding:30px 36px;border-radius:26px;font-size:24px;line-height:1.6;
  color:#9BA9C4;background:rgba(34,211,238,.075);border:1.5px solid rgba(34,211,238,.26);
  position:relative;z-index:3;flex:0 0 auto}
.note b{color:#67E8F9;font-weight:700}
"""

CSS = CSS.replace("__FONT__", FONT).replace("__EMOJI__", EMOJI)

# ---------------------------------------------------------------- 装饰书脊
random.seed(7)
spine_html = []
for _ in range(15):
    h = random.choice([150, 210, 260, 300, 340, 390])
    o = round(random.uniform(0.12, 0.34), 2)
    o2 = round(o * 0.34, 2)
    spine_html.append(f'<i style="--o:{o};--o2:{o2};height:{h}px"></i>')
SPINES = "\n    ".join(spine_html)

# ---------------------------------------------------------------- 1 封面
CARD1 = f"""
<div class="card">
  <div class="glow g1"></div><div class="glow g2"></div><div class="grid"></div>
  <div class="spines">
    {SPINES}
  </div>
  <div class="cover-top">
    <span class="pill"><span class="dot"></span>OPEN SOURCE</span>
    <span class="pill dim">MIT · 完全免费</span>
  </div>
  <h1 class="cover-title">把整个<br>电子书库<br><em>装进一个 exe</em></h1>
  <p class="cover-sub">免安装 · 免联网 · 免注册<br>数据只留在你自己的电脑里</p>
  <div class="cover-foot">
    <img class="logo" src="data:image/png;base64,{LOGO_B64}">
    <div>
      <div class="brand">Shelfmark</div>
      <div class="brand-url">本地电子书库管理器 · 开源免费</div>
    </div>
  </div>
</div>
"""

# ---------------------------------------------------------------- 2 对比
CARD2 = """
<div class="card">
  <div class="glow g1"></div><div class="glow g2"></div><div class="grid"></div>
  <div class="head">
    <div class="kicker"><span class="bar"></span>WHY</div>
    <h2 class="title">为什么我又<br>自己造了个轮子</h2>
    <p class="sub">试完一圈现成方案，我决定自己写一个</p>
  </div>
  <div class="cmp">
    <div class="col bad">
      <div class="col-h">以前</div>
      <div class="item"><span class="mk">✕</span><span>电子书全躺在收藏夹里吃灰<br>越攒越多，也懒得整理</span></div>
      <div class="item"><span class="mk">✕</span><span>用 Excel 记书<br>记到第 30 本就放弃了</span></div>
      <div class="item"><span class="mk">✕</span><span>在线书库得先把书传上去<br>才肯给你用</span></div>
      <div class="item"><span class="mk">✕</span><span>出版社、页数、简介<br>全靠一本本手动填</span></div>
    </div>
    <div class="col good">
      <div class="col-h">现在</div>
      <div class="item"><span class="mk">✓</span><span>扫一遍硬盘<br>几百本书自己进库</span></div>
      <div class="item"><span class="mk">✓</span><span>封面墙浏览<br>一眼看到想读的那本</span></div>
      <div class="item"><span class="mk">✓</span><span>数据全在本机<br>断网也照样打开</span></div>
      <div class="item"><span class="mk">✓</span><span>书籍信息一键补齐<br>不用再手填</span></div>
    </div>
  </div>
  <div class="foot"><span>Shelfmark</span><span>·</span><span>本地电子书库管理器</span></div>
</div>
"""

# ---------------------------------------------------------------- 3 功能
FEATS = [
    ("📥", "批量扫盘导入", "扫一遍目录，书名、格式、作者自动识别"),
    ("🖼️", "封面墙浏览", "按标签 / 状态 / 星级 / 丛书随意筛"),
    ("🔍", "书籍信息补全", "出版社、出版年、页数、简介一次补齐"),
    ("🌏", "作者国籍自动标", "按文件名识别，几百本书几秒钟搞定"),
    ("🧠", "智能书架", "定好规则自动归集，不用手动整理"),
    ("🌐", "一键在线书架", "导出只读站点，手机上也能翻书单"),
]
feat_html = "\n    ".join(
    f'<div class="feat"><div class="ic">{i}</div><div class="fx">'
    f'<div class="fn">{n}</div><div class="fd">{d}</div></div></div>'
    for i, n, d in FEATS
)
CARD3 = f"""
<div class="card">
  <div class="glow g1"></div><div class="glow g2"></div><div class="grid"></div>
  <div class="head">
    <div class="kicker"><span class="bar"></span>FEATURES</div>
    <h2 class="title">它到底能干什么</h2>
    <p class="sub">一个 exe，把书库该有的都给你</p>
  </div>
  <div class="feats">
    {feat_html}
  </div>
  <div class="foot"><span>还有统计仪表盘 · 路径修正 · 书库备份与恢复</span></div>
</div>
"""

# ---------------------------------------------------------------- 4 界面预览
BOOKS = [
    ("红楼梦", "曹雪芹", "#8C1D18,#4A0F0B", "#C9A227"),
    ("百年孤独", "马尔克斯", "#1F5F4B,#0B2C22", "#E0B44A"),
    ("人类简史", "尤瓦尔·赫拉利", "#2B3E63,#111C31", "#7FB3E8"),
    ("活着", "余华", "#7A4B1E,#3A2009", "#E8C99B"),
    ("三体", "刘慈欣", "#1B1F28,#06080C", "#5FD3F8"),
    ("月亮与六便士", "毛姆", "#1E4C6B,#0A2333", "#F0D98A"),
    ("万历十五年", "黄仁宇", "#5A2A2A,#2A0F0F", "#D9A66C"),
    ("局外人", "加缪", "#3B3B45,#17171D", "#C9CBD6"),
    ("小王子", "圣埃克苏佩里", "#1B3F7A,#0A1C3D", "#F5D76E"),
    ("平凡的世界", "路遥", "#6B4515,#2E1B06", "#E5B86A"),
    ("追风筝的人", "胡赛尼", "#7C2A3A,#36101A", "#F0A6B4"),
    ("白夜行", "东野圭吾", "#161C29,#05080D", "#9FB4D9"),
]
bk_html = [
    f'<div class="bk" style="background:linear-gradient(165deg,{g})">'
    f'<span class="spn" style="background:linear-gradient(180deg,{ac},rgba(0,0,0,.5))"></span>'
    f'<div class="bt">{t}</div><div class="ba">{a}</div></div>'
    for t, a, g, ac in BOOKS
]
BOOKS_HTML = "\n      ".join(bk_html)

CARD4 = f"""
<div class="card">
  <div class="glow g1"></div><div class="glow g2"></div><div class="grid"></div>
  <div class="head">
    <div class="kicker"><span class="bar"></span>PREVIEW</div>
    <h2 class="title">它长什么样</h2>
    <p class="sub">深色封面墙，打开就是自己的书库</p>
  </div>
  <div class="win">
    <div class="side">
      <div class="sb"><img src="data:image/png;base64,{LOGO_B64}">Shelfmark</div>
      <div class="snav sec">书库</div>
      <div class="snav on">全部书籍</div>
      <div class="snav">最近添加</div>
      <div class="snav sec">状态</div>
      <div class="snav off">在读 · 未读</div>
      <div class="snav off">已读 · 搁置</div>
      <div class="snav sec">管理</div>
      <div class="snav off">工具合集</div>
      <div class="snav off">统计仪表盘</div>
      <div class="snav pub">🌐 在线发布</div>
    </div>
    <div class="main">
      <div class="searchbar">
        <div class="s">🔍 搜索书名 / 作者 / ISBN</div>
        <div class="b">批量导入</div>
        <div class="b ghost">新增书籍</div>
      </div>
      <div class="wall">
      {BOOKS_HTML}
      </div>
      <div class="stat">
        <div><div class="v">225</div><div class="k">全部藏书</div></div>
        <div><div class="v">38</div><div class="k">已读</div></div>
        <div><div class="v">12</div><div class="k">在读</div></div>
        <div><div class="v">6</div><div class="k">书架</div></div>
      </div>
    </div>
  </div>
  <div class="foot"><span>界面示意 · 你的书籍数据全部保存在本机</span></div>
</div>
"""

# ---------------------------------------------------------------- 5 步骤
CARD5 = f"""
<div class="card">
  <div class="glow g1"></div><div class="glow g2"></div><div class="grid"></div>
  <div class="head">
    <div class="kicker"><span class="bar"></span>HOW TO USE</div>
    <h2 class="title">三步就能用上</h2>
    <p class="sub">Windows 10 / 11 · 不用装 Python、不用管理员权限</p>
  </div>
  <div class="steps">
    <div class="step"><div class="num">1</div><div>
      <div class="st">下载</div>
      <div class="sd">到项目的发布页下载 zip，只有 11 MB 左右</div></div></div>
    <div class="step"><div class="num">2</div><div>
      <div class="st">解压</div>
      <div class="sd">解压到任意普通文件夹，比如 D:\\Shelfmark</div></div></div>
    <div class="step"><div class="num">3</div><div>
      <div class="st">双击</div>
      <div class="sd">运行 Shelfmark.exe，浏览器会自动帮你打开</div></div></div>
  </div>
  <div class="note">
    <b>首次运行</b>会在同目录自动建好 <b>data\\</b> 和 <b>covers\\</b>，这就是你的书库。<br>
    如果系统提示「已保护你的电脑」，点<b>更多信息 → 仍要运行</b>即可，这是未签名程序的常见误报。
  </div>
  <div class="foot">
    <img class="logo" src="data:image/png;base64,{LOGO_B64}">
    <span>Shelfmark · 本地电子书库管理器</span>
    <span class="pill dim" style="margin-left:auto">免费 · 开源 · 无广告</span>
  </div>
</div>
"""

CARDS = [
    ("01_封面", CARD1),
    ("02_为什么", CARD2),
    ("03_功能", CARD3),
    ("04_界面", CARD4),
    ("05_怎么用", CARD5),
]

PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>__CSS__</style></head><body>__BODY__</body></html>"""

print("===== 生成 HTML =====")
html_paths = []
for name, body in CARDS:
    p = os.path.join(HTML_DIR, name + ".html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(PAGE.replace("__CSS__", CSS).replace("__BODY__", body))
    html_paths.append((name, p))
    print("  ", p)

print()
print("===== Edge headless 截图 =====")
for name, p in html_paths:
    out = os.path.join(OUT, f"xhs_{name}.png")
    cmd = [
        EDGE, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--window-size=1080,1440",
        "--virtual-time-budget=4000",
        f"--user-data-dir={PROFILE}",
        f"--screenshot={out}",
        "file:///" + p.replace("\\", "/"),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    ok = os.path.exists(out)
    size = os.path.getsize(out) if ok else 0
    print(f"  {'OK ' if ok else 'FAIL'} {os.path.basename(out):<22} {size:>9} bytes")

print()
print("输出目录:", OUT)
