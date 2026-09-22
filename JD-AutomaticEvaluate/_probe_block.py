# -*- coding: utf-8 -*-
"""[诊断 2026-09-22] 定性探测：评价弹层为什么打不开？风控 还是 改版？

只做 1 次页面加载 + 1 次「全部评价」点击，但同时**监听网络层**，
把评价相关请求的状态码与响应体抓下来 —— 这是唯一能一锤定音的证据。
不点图片、不提交、不动订单页。
"""
import json
import os
import re

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
COOKIES_PATH = os.path.join(ROOT, "pc", "cookies", "cookies.json")
OUT = os.path.join(ROOT, "_diagnose", "风控定性报告.txt")
SKU = "100099425465"

KEY = re.compile(r"comment|rate|evaluate|shaidan|club\.jd\.com|voucher", re.I)
BLOCK_WORDS = ["维修", "维护", "系统繁忙", "稍后再试", "访问异常", "安全验证",
               "出错了", "暂时无法", "稍后重试", "活动太火爆"]

records = []
report = []


def log(m):
    print(m, flush=True)
    report.append(str(m))


def on_response(resp):
    try:
        if KEY.search(resp.url):
            records.append({"status": resp.status, "url": resp.url[:160],
                            "type": resp.headers.get("content-type", "")[:40]})
    except Exception:
        pass


def main():
    with open(COOKIES_PATH, encoding="utf-8") as f:
        cookies = json.load(f)
    if isinstance(cookies, dict):
        cookies = cookies.get("cookies", cookies)

    with sync_playwright() as pw:
        # [FIX 2026-09-22 WorkBuddy] 改用本机 Edge，验证「风控是否为指纹级」
        try:
            browser = pw.chromium.launch(channel="msedge", headless=False, args=[
                "--disable-blink-features", "--disable-blink-features=AutomationControlled",
                "--start-maximized"])
            log("[0] 已启动本机 Edge（channel=msedge）")
        except Exception as e:
            log(f"[0] Edge 启动失败（{e}），回退内置 Chromium")
            browser = pw.chromium.launch(headless=False, args=[
                "--disable-blink-features", "--disable-blink-features=AutomationControlled",
                "--start-maximized"])
        ctx = browser.new_context(no_viewport=True)
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.on("response", on_response)

        try:
            log("[1] 打开商详页（等 10s 让首屏铺开）...")
            page.goto(f"https://item.jd.com/{SKU}.html", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(10000)
        except Exception as e:
            log(f"[!] 页面打开/等待异常: {type(e).__name__}: {e}")
            log("[!] 常见原因：弹出的浏览器窗口被手动关掉了。请重跑并保持窗口开着。")

        try:
            body = page.evaluate("() => (document.body && document.body.innerText) || ''")
            log(f"[2] 页面可见文本长度: {len(body)}")
            for w in BLOCK_WORDS:
                if w in body:
                    i = body.find(w)
                    log(f"    ★ 命中关键词「{w}」上下文: ...{body[max(0,i-80):i+80]}...".replace('\n', ' | '))
        except Exception as e:
            log(f"[2] 文本扫描失败: {e}")
            body = ""

        try:
            log(f"[3] 点击前: .all-btn={page.locator('.all-btn').count()}  "
                f"comment-root={page.locator('#comment-root').count()}")
        except Exception as e:
            log(f"[3] 计数失败: {e}")
        try:
            btn = page.wait_for_selector(".all-btn", timeout=15000)
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(1200)
            btn.click()
            log("[4] 已点击『全部评价』")
        except Exception as e:
            log(f"[4] 点击失败: {type(e).__name__}: {e}")

        try:
            page.wait_for_timeout(10000)
        except Exception as e:
            log(f"[4·5] 点击后等待被中断: {type(e).__name__}: {e}")

        # 弹层内容
        for sel in ["#rateList", "div.jdc-page-overlay"]:
            try:
                loc = page.locator(sel)
                n = loc.count()
                log(f"[5] {sel}: count={n}")
                if n:
                    txt = (loc.first.inner_text() or "")[:1200]
                    log(f"    弹层文本: {txt.replace(chr(10), ' | ')}")
            except Exception as e:
                log(f"[5] {sel} 读取异常: {e}")

        try:
            log(f"[6] 点击后: virtuoso={page.locator('div[data-testid=virtuoso-item-list]').count()}  "
                f"data-item-index={page.locator('div[data-item-index]').count()}  "
                f"rate-card-desc={page.locator('.jdc-pc-rate-card-main-desc').count()}")
            page.wait_for_timeout(3000)
        except Exception as e:
            log(f"[6] 点击后计数被中断: {type(e).__name__}: {e}")
        # 点击后页面文本再扫一遍
        try:
            body2 = page.evaluate("() => (document.body && document.body.innerText) || ''")
            for w in BLOCK_WORDS:
                if w in body2:
                    i = body2.find(w)
                    log(f"    ★★ 点击后命中「{w}」: ...{body2[max(0,i-100):i+100]}...".replace('\n', ' | '))
        except Exception as e:
            log(f"[6·5] 二次文本扫描失败: {e}")

        # ---- 网络层证据 ----
        log("\n[7] 评价/评论相关网络请求汇总（这是定性关键）:")
        seen = {}
        for r in records:
            k = (r["status"], r["url"].split("?")[0][:110])
            seen[k] = seen.get(k, 0) + 1
        if not seen:
            log("    （未捕获到任何评价相关请求 —— 说明弹层根本没发起请求）")
        for (st, u), c in sorted(seen.items(), key=lambda x: -x[1]):
            log(f"    {st}  x{c:<3} {u}")

        try:
            page.wait_for_timeout(1500)
            browser.close()
        except Exception:
            pass

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print(f"\n[已保存] {OUT}")


if __name__ == "__main__":
    main()
