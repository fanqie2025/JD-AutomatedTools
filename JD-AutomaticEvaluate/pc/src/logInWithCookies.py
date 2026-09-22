'''
Author: HDJ @https://github.com/Goodnameisfordoggy
LastEditTime: 2025-07-10 22:42:43
FilePath: \pythond:\LocalUsers\Goodnameisfordoggy-Gitee\JD-Automated-Tools\JD-AutomaticEvaluate\pc\src\logInWithCookies.py
Description: @VSCode

				|	早岁已知世事艰，仍许飞鸿荡云间；
				|	曾恋嘉肴香绕案，敲键弛张荡波澜。
				|					 
				|	功败未成身无畏，坚持未果心不悔；
				|	皮囊终作一抔土，独留屎山贯寰宇。

Copyright (c) 2024-2025 by HDJ, All Rights Reserved. 
'''
import os
import sys
import time
import json
from playwright.sync_api import sync_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from pc.src import COOKIES_DIR
from pc.src.data import NetworkError
from pc.src.logger import get_logger
from common.utils import sync_retry
LOG = get_logger()

LOGIN_URL = 'https://passport.jd.com/new/login.aspx'  # 京东登录页面
COOKIES_SAVE_PATH = os.path.join(COOKIES_DIR, "cookies.json")  # 保存 cookies 的路径

# [ADD 2026-09-22 WorkBuddy] 浏览器指纹修复 —— 换用本机 Edge，而不是 Playwright 自带的 Chromium。
#
# 实测依据（2026-09-22 21:28）：同一账号、同一出口 IP、
#   · Playwright 自带 Chromium 打开「全部评价」→ 弹层显示「商品评价 | 页面正在维修中，请稍后重试」
#   · 用户自己的 Edge 打开同一商品「全部评价」→ 正常
# 结论：京东封的是**浏览器指纹 / 会话**，不是 IP。
# 所以让自动化直接跑在真实 Edge 上（channel="msedge"），指纹与用户日常浏览器一致。
# 想临时切回内置 Chromium：设环境变量 JD_BROWSER_CHANNEL=  （留空即可）
BROWSER_CHANNEL = os.environ.get("JD_BROWSER_CHANNEL", "msedge")
LAUNCH_ARGS = [
    "--disable-blink-features",
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
    # [ADD 2026-09-22 WorkBuddy] 首次用 channel="msedge" 会走「全新 profile + 首次运行」流程，
    # 可能弹出欢迎页/默认浏览器询问，干扰元素点击。
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=msEdgeFirstRunExperience",
]


# [ADD 2026-09-22 WorkBuddy] 固定 profile 目录。
#
# 为什么必须持久化：Playwright 默认每次启动都用**全新的临时 profile**。
# 在京东眼里，这等于「同一个账号每隔几分钟就换一台全新设备来点评价」——
# 这本身就是极强的自动化信号。实测对照：
#   21:27 首次用 Edge 通道探测 → 评价区正常
#   21:28 / 21:31 再点两次 → 弹层开了但 0 条数据（重新被限流）
# 改成固定 profile 后，多轮运行复用同一个「设备」，profile 里还会自然累积
# cookies / localStorage / 历史，指纹连续性大幅提升。
EDGE_PROFILE_DIR = os.path.join(os.getcwd(), "pc", "edge-profile")


def _launch_context(playwright):
    """返回一个 BrowserContext。

    · 打包 exe 模式：仍用内置 chromium（无 Edge 可用）
    · 源码模式：优先「本机 Edge + 固定 profile（持久化）」，
      失败则回退「内置 Chromium + 临时 profile」
    """
    if getattr(sys, 'frozen', False):  # 打包模式
        temp_dir = os.path.join(sys._MEIPASS, "chromium")
        browser = playwright.chromium.launch(
            headless=False,
            args=LAUNCH_ARGS,
            executable_path=os.path.join(temp_dir, "chrome.exe"),
        )
        return browser.new_context(no_viewport=None)

    if BROWSER_CHANNEL:
        try:
            os.makedirs(EDGE_PROFILE_DIR, exist_ok=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=EDGE_PROFILE_DIR,
                channel=BROWSER_CHANNEL,
                headless=False,
                no_viewport=True,
                args=LAUNCH_ARGS,
            )
            LOG.success(f"已启动本机浏览器：{BROWSER_CHANNEL} + 固定 profile"
                        f"（指纹连续，profile: {EDGE_PROFILE_DIR}）")
            return context
        except Exception as e:
            LOG.warning(f"启动 {BROWSER_CHANNEL} 失败（{e}），回退到内置 Chromium")

    browser = playwright.chromium.launch(headless=False, args=LAUNCH_ARGS)
    return browser.new_context(no_viewport=None)

@sync_retry(max_retries=3, retry_delay=2, exceptions=(PlaywrightTimeoutError,))
def __load_page(page: Page, url: str, timeout: float):
    return page.goto(url, timeout=timeout)


# [FIX 2026-09-22] 登录态判定修复
# 原判定依赖京东首页的 `.nickname` 元素。2026-09 实测：京东首页已无 .nickname /
# .user-info / #ttbar-login（元素数均为 0），该判定必然超时，进而被当成「Cookies 失效」
# 并直接删除 cookies 文件 —— 即使 cookies 其实有效，也要重新手动登录一次。
# 现改为：访问「我的订单」页，看是否被重定向到 passport 登录页来判定。
ORDER_LIST_URL = "https://club.jd.com/myJdcomments/myJdcomment.action?sort=0&page=1"


def _is_logged_in(page: Page) -> bool:
    """判定当前上下文是否处于登录态。

    判据：访问待评价列表页，若未登录会被重定向到 passport.jd.com。
    该判据不依赖首页的易变元素，京东改版首页也不受影响。
    """
    try:
        __load_page(page, ORDER_LIST_URL, timeout=20000)
        page.wait_for_timeout(1500)
        if "passport.jd.com" in page.url:
            LOG.debug("被重定向到登录页，判定为未登录")
            return False
        # 已登录（即使没有待评价订单，页面仍停留在 club.jd.com）
        LOG.debug(f"登录态判定通过，当前 url: {page.url}")
        return True
    except Exception as e:
        LOG.debug(f"登录态判定异常: {e}")
        return False


def logInWithCookies(target_url: str = "https://www.jd.com/", retry: int = 0, context: BrowserContext | None = None):
    """ 
    使用 cookies 模拟登录

    Params:
        retry: 重新尝试登录的次数
        context: 每次重新尝试登录通用一个 BrowserContext 对象，减少了其初始化的开支
    Returns:
        登录成功时返回 tuple[Page, BrowserContext], 失败则程序退出。
    """
    # 初始化 playwright
    if retry == 0:
        playwright = sync_playwright().start()
        # 初始化浏览器对象
        # [FIX 2026-09-22 WorkBuddy] 原为写死的 playwright.chromium.launch(...) +
        # browser.new_context()。现改为 _launch_context()：源码模式优先
        # 「本机 Edge + 固定 profile（持久化）」，失败回退内置 Chromium + 临时 profile。
        context = _launch_context(playwright)
        

    # 没有 Cookies 先登录获取
    if not os.path.exists(COOKIES_SAVE_PATH):
        LOG.info("未找到 Cookies 文件，将跳转手动登录！")
        page = context.new_page() # 这里的 context 在 retry=0时用的local变量，其余情况均使用递归传递的参数
        try:
            response = __load_page(page, LOGIN_URL, timeout=10000)  # 打开登录界面
            if response.status != 200:
                LOG.error(f"请求错误，状态码：{response.status}")
            else:
                LOG.info("登录页面已跳转，建议使用手机验证码登录以获得较长有效期的 Cookies")
        except PlaywrightTimeoutError:
            raise NetworkError(message=f"页面加载超时：{LOGIN_URL}")
            
        # 等待用户手动登录京东
        while True:
            try:
                # 检查页面是否已经跳转到京东主页
                page.wait_for_url(target_url, timeout=3000)
                LOG.success("手动登录成功！")
                break
            except PlaywrightTimeoutError:
                LOG.info("等待用户完成登录...")
        # 获取 Cookies 并保存到文件
        cookies = page.context.cookies()
        with open(COOKIES_SAVE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=4)
            LOG.info(f'Cookies 已保存到 {os.getcwd()}/cookies.json')
        # 视觉效果优化，以便使用者查看日志信息并进行下一步操作
        page.close()
        time.sleep(2) 

    # 用 Cookies 登录
    page = context.new_page()
    try:
        __load_page(page, target_url, timeout=10000)  # 打开登录页面
    except PlaywrightTimeoutError:
        raise NetworkError(message=f"页面加载超时: {target_url}")
    
    with open(COOKIES_SAVE_PATH, 'r', encoding='utf-8') as f:
        cookies = json.load(f) # 读取文件中的 cookies
        page.context.add_cookies(cookies) # 加载 cookies 到页面上下文
    page.reload()  # 刷新页面以应用 cookies
    # 检查是否成功登录
    # [FIX 2026-09-22] 原代码：page.wait_for_selector('.nickname', timeout=10000)
    # 该元素在京东现行首页已不存在，导致误判 + 误删 cookies。改用 _is_logged_in()。
    if _is_logged_in(page):
        LOG.success('使用已保存的 Cookies 登录')
        return page, context

    # 判定为未登录：不再直接删除 cookies 文件，改为重命名备份。
    # 理由：判定本身可能因页面改版而误报，直接删会让用户白白重登一次。
    if os.path.isfile(COOKIES_SAVE_PATH):
        backup_path = COOKIES_SAVE_PATH + '.bak'
        try:
            if os.path.isfile(backup_path):
                os.remove(backup_path)
            os.replace(COOKIES_SAVE_PATH, backup_path)
            LOG.warning(f'Cookies 疑似失效，已备份为 {backup_path}（原文件未删除，可手动恢复）')
        except Exception as e:
            LOG.error(f'备份 cookies 失败: {e}')
        else:
            LOG.warning('将跳转手动登录！')
        # 视觉效果优化，以便使用者查看日志信息并进行下一步操作
        page.close()
        time.sleep(2)
    if retry >= 3: # 防止无限递归，但暂未想到发生异常的情况
        LOG.critical("登录异常")
        sys.exit(1)
    else:
        return logInWithCookies(retry=retry + 1, context=context) # 尾递归，语义明了
