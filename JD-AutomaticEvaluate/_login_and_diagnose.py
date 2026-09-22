# -*- coding: utf-8 -*-
"""
一键：登录京东 + 保存 Cookies + 诊断当前页面结构
------------------------------------------------
用途：修 JD-AutomatedTools 的失效选择器。
      会弹出浏览器，请在里面手动登录京东（扫码 or 验证码）。
      登录成功后自动保存 cookies 并 dump 页面结构，不会提交任何评价。

运行后请把终端输出、以及 _diagnose 文件夹下的报告，发回给 WorkBuddy。
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
COOKIES_SRC_PATH = os.path.join(ROOT, "pc", "cookies", "cookies.json")   # 源码版路径
COOKIES_EXE_PATH = os.path.join(os.path.dirname(ROOT), "cookies.json")   # exe 版路径
OUT_DIR = os.path.join(ROOT, "_diagnose")

LOGIN_URL = "https://passport.jd.com/new/login.aspx"
ORDER_LIST_URL = "https://club.jd.com/myJdcomments/myJdcomment.action?sort=0&page=1"
LOGIN_WAIT_SECONDS = 600
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.dirname(COOKIES_SRC_PATH), exist_ok=True)

report = []


def log(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    report.append(line)


def save(name, text):
    p = os.path.join(OUT_DIR, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    log(f"[已保存] {name}  ({len(text)} 字符)")


# 京东登录成功的核心凭证 cookie（未登录时不存在）。
# 用 cookie 判定，比看页面元素/URL 可靠得多 —— 页面改版也不会影响。
LOGIN_COOKIE_NAMES = ("pt_key", "thor")


def has_login_cookie(ctx):
    try:
        names = {c.get("name") for c in ctx.cookies()}
    except Exception:
        return False
    return any(n in names for n in LOGIN_COOKIE_NAMES)


def probe(page, label, selectors):
    lines = [f"", f"===== {label} =====", f"url: {page.url}"]
    for sel in selectors:
        try:
            n = page.locator(sel).count()
        except Exception as e:
            n = f"ERR({type(e).__name__})"
        lines.append(f"  {str(n):>5}  {sel}")
    block = "\n".join(lines)
    log(block)
    return block


def js_list(page, js, arg=None):
    try:
        return page.evaluate(js) if arg is None else page.evaluate(js, arg)
    except Exception as e:
        return f"ERR: {e}"


with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features",
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ],
    )
    ctx = browser.new_context(no_viewport=None, user_agent=UA)
    page = ctx.new_page()

    # ---------- 1. 打开登录页，等用户登录 ----------
    log("正在打开京东登录页……")
    try:
        page.goto(LOGIN_URL, timeout=45000)
        page.bring_to_front()          # 把窗口抢到前台，避免被其它窗口盖住
        page.wait_for_timeout(1500)
        log(f"登录页已打开，标题：{page.title()}")
    except Exception as e:
        log(f"登录页加载异常: {e}")

    log("=" * 62)
    log(">>> 请在弹出的【这个】浏览器窗口里登录京东（扫码最快）")
    log(">>> 重要：只有这个窗口里的登录会被记录，你平时用的浏览器不算数")
    log(">>> 登录页若卡住，刷新一下；若出现滑块验证，手动滑一下")
    log(f">>> 最多等待 {LOGIN_WAIT_SECONDS} 秒")
    log("=" * 62)

    deadline = time.time() + LOGIN_WAIT_SECONDS
    logged = False
    tick = 0
    while time.time() < deadline:
        tick += 1
        url = ""
        try:
            url = page.url
        except Exception:
            pass

        # 判据 1（主）：拿到了登录凭证 cookie
        if has_login_cookie(ctx):
            logged = True
            log(f"√ 检测到登录凭证 cookie，登录成功！（当前页 {url[:80]}）")
            break
        # 判据 2（辅）：已离开登录站
        if url and "passport.jd.com" not in url:
            logged = True
            log(f"√ 已离开登录页，判定登录成功（当前页 {url[:80]}）")
            break

        if tick % 4 == 0:
            remain = int(deadline - time.time())
            log(f"    等待登录中… 剩余 {remain}s ｜ 当前页: {url[:80]}")
        time.sleep(3)

    if not logged:
        log("!!! 超时未检测到登录。仍保存当前 cookies 并继续诊断（可能只是判定不准）。")

    log("检测到已离开登录页，等待页面稳定……")
    page.wait_for_timeout(4000)
    log(f"当前地址: {page.url}")

    # ---------- 2. 保存 cookies（两份路径都写） ----------
    cookies = ctx.cookies()
    names = sorted({str(c.get("name")) for c in cookies})
    log(f"当前 cookies 共 {len(cookies)} 条")
    log(f"cookie 名单: {names}")
    log("关键登录凭证 pt_key/thor: " + ("有 √" if has_login_cookie(ctx) else "无 ×（说明这个窗口确实没登录成功）"))
    for path in (COOKIES_SRC_PATH, COOKIES_EXE_PATH):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=4)
            log(f"Cookies 已保存: {path}")
        except Exception as e:
            log(f"保存 cookies 失败 {path}: {e}")

    # ---------- 3. 登录态复验 ----------
    try:
        page.goto(ORDER_LIST_URL, timeout=45000)
        page.wait_for_timeout(5000)
    except Exception as e:
        log(f"列表页加载异常: {e}")
    probe(page, "① 待评价订单列表页", [
        ".operate", ".btn-def", ".tip-icon", "a[href*='orderVoucher']",
    ])
    hrefs = js_list(page, """() => Array.from(document.querySelectorAll("a[href*='orderVoucher']"))
        .map(e => e.getAttribute('href'))""")
    log(f"orderVoucher 链接数: {len(hrefs) if isinstance(hrefs, list) else hrefs}")
    if isinstance(hrefs, list) and hrefs:
        for h in hrefs[:5]:
            log(f"    {h}")
    try:
        save("列表页_operate.html", page.eval_on_selector_all(
            ".operate", "els => els.slice(0,2).map(e=>e.outerHTML).join('\\n<!--next-->\\n')") or "(空)")
    except Exception as e:
        log(f"dump operate 失败: {e}")

    # ---------- 4. 评价页结构 ----------
    voucher = None
    if isinstance(hrefs, list) and hrefs:
        h = hrefs[0]
        voucher = ("https:" + h) if h.startswith("//") else h
    if voucher:
        log(f"打开评价页: {voucher}")
        try:
            page.goto(voucher, timeout=45000)
            page.wait_for_timeout(6000)
        except Exception as e:
            log(f"评价页加载异常: {e}")

        probe(page, "② 评价页 · 旧选择器存活情况", [
            "xpath=//*[@id='o-info-orderinfo']/div/div/span[1]/a",
            "#o-info-orderinfo", ".comment-goods", "div.p-name > a",
            ".f-textarea textarea", "textarea", ".commstar", ".btn-submit",
            "input[type=file]", ".btn-upload",
        ])

        # 输入框清单（含自动生成 XPath）
        boxes = js_list(page, """() => Array.from(document.querySelectorAll("textarea,[contenteditable='true']"))
            .map(e => {
                let n = e, p = [];
                while (n && n.nodeType === 1 && p.length < 12) {
                    let i = 1, s = n.previousElementSibling;
                    while (s) { if (s.tagName === n.tagName) i++; s = s.previousElementSibling; }
                    p.unshift(n.tagName.toLowerCase() + '[' + i + ']');
                    n = n.parentElement;
                }
                return {tag: e.tagName, id: e.id, cls: e.className,
                        ph: e.getAttribute('placeholder'), xpath: '/' + p.join('/')};
            })""")
        log("输入框清单:\n" + json.dumps(boxes, ensure_ascii=False, indent=2))

        # 按钮
        btns = js_list(page, """() => Array.from(document.querySelectorAll("a,button,div,span"))
            .filter(e => /^(发表|提交|发布|评价晒单|发表评价)$/.test((e.innerText||'').trim()))
            .slice(0, 15)
            .map(e => ({tag: e.tagName, id: e.id, cls: e.className,
                        txt: (e.innerText||'').trim()}))""")
        log("疑似提交按钮:\n" + json.dumps(btns, ensure_ascii=False, indent=2))

        # 星级
        star = js_list(page, """() => Array.from(document.querySelectorAll("[class*='star'],[class*='Star'],[class*='commstar']"))
            .slice(0, 20)
            .map(e => ({tag: e.tagName, cls: e.className, id: e.id}))""")
        log("疑似星级组件:\n" + json.dumps(star, ensure_ascii=False, indent=2))

        # 评价页整体结构摘要：顶层容器
        layout = js_list(page, """() => {
            const walk = (el, d) => {
                if (d > 4 || !el) return '';
                let out = '';
                for (const c of el.children) {
                    const cls = (typeof c.className === 'string' ? c.className : '').trim();
                    const id = c.id ? '#' + c.id : '';
                    out += '  '.repeat(d) + c.tagName.toLowerCase() + id + (cls ? '.' + cls.split(/\\s+/).join('.') : '') + '\\n';
                    out += walk(c, d + 1);
                }
                return out;
            };
            return walk(document.body, 0).slice(0, 6000);
        }""")
        save("评价页_DOM骨架.txt", layout if isinstance(layout, str) else str(layout))
        save("评价页_完整HTML.html", page.content())
    else:
        log("!!! 没有待评价订单或链接未取到，跳过评价页诊断")
        save("评价页_完整HTML.html", page.content())

    try:
        browser.close()
    except Exception:
        pass

save("诊断报告.txt", "\n".join(report))
log("")
log("=" * 62)
log(f">>> 完成。请把 {OUT_DIR} 整个文件夹 + 终端输出发回给 WorkBuddy。")
log("=" * 62)
print("\n按回车关闭...", end="")
try:
    input()
except Exception:
    pass
