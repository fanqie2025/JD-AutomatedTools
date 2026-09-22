# -*- coding: utf-8 -*-
"""[诊断 2026-09-22] 快速验证 cookies.json 是否仍然有效（不弹登录页、不修改任何文件）。

判据：把 cookies 注入浏览器上下文后访问「我的待评价」列表页，
      若最终 URL 落到 passport.jd.com  → cookies 已失效
      若停留在 club.jd.com 且能读到订单元素 → cookies 有效
"""
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.sync_api import sync_playwright

COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pc", "cookies", "cookies.json")
ROOT_COOKIE_FILE = r"D:\JD-AutomaticEvaluate\cookies.json"
ORDER_URL = "https://club.jd.com/myJdcomments/myJdcomment.action?sort=0&page=1"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    print(f"[i] 读取 cookies: {COOKIE_FILE}")
    cookies = load(COOKIE_FILE)
    if isinstance(cookies, dict):
        cookies = cookies.get("cookies", cookies)
    print(f"[i] cookie 数量: {len(cookies)}")
    names = {c["name"] for c in cookies}
    print(f"[i] 含 pt_key: {'pt_key' in names} | 含 thor: {'thor' in names} | 含 pin: {'pin' in names}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        ctx = browser.new_context(no_viewport=True)
        ctx.add_cookies(cookies)
        page = ctx.new_page()

        # 先访问 jd.com 让 cookie 生效
        try:
            page.goto("https://www.jd.com/", timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[!] 打开首页异常: {e}")
        page.wait_for_timeout(1500)

        try:
            page.goto(ORDER_URL, timeout=40000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[!] 打开订单页异常: {e}")
        page.wait_for_timeout(4000)

        final_url = page.url
        print(f"[i] 最终 URL: {final_url}")

        # 登录判据
        logged_in = "passport.jd.com" not in final_url
        print(f"[=] 判定: {'✅ cookies 有效（登录态）' if logged_in else '❌ cookies 已失效（被踢到登录页）'}")

        # 附加信息：页面元素探针
        try:
            title = page.title()
            print(f"[i] 页面标题: {title}")
            for sel in [".tip-icon", "#o-info-orderinfo", ".comment-goods",
                        ".btn-submit", ".all-btn", "text=待评价", "text=立即评价",
                        "text=评价"]:
                try:
                    print(f"    {sel!r:28s} count={page.locator(sel).count()}")
                except Exception:
                    pass
        except Exception as e:
            print(f"[!] 元素探针异常: {e}")

        # 同步一份到根目录（保持 exe 与源码一致）——仅在有效时
        if logged_in:
            try:
                with open(ROOT_COOKIE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=4)
                print(f"[i] 已同步 cookies 到 {ROOT_COOKIE_FILE}")
            except Exception as e:
                print(f"[!] 同步失败: {e}")

        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()
