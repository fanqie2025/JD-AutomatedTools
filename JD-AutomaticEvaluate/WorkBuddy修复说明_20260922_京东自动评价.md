# JD-AutomaticEvaluate 修复说明（WorkBuddy 2026-09-22）

> 基于官方源码 `Goodnameisfordoggy/JD-AutomatedTools` · JD-AutomaticEvaluate v2.9.19
> 工作副本：`D:\JD-AutomaticEvaluate\source`
> 运行入口：`JDpc-AutomaticEvaluate.py`（必须在 `source` 目录下运行，代码用 `os.getcwd()` 拼路径）

---

## 一、结论先说

**原项目的选择器全部还是有效的**，不存在「京东改版导致整块失效」。
它跑不起来的真实原因是三类**工程问题**：

1. 登录态判定依赖一个京东已删除的元素 → 每次运行都把好用的 cookies 删掉；
2. 京东 2026 年页面渲染明显变慢，而原代码超时普遍只给了 2000–3000ms → 被误判成「没有评价 / 页面变动」；
3. 若干「写到一半」的笔误，导致点击行为打在自己刚展开的弹层上。

修复方式 = 调超时 + 改判定 + 加重试，**没有重写架构**。

---

## 二、逐条修复清单

### 1. `pc/src/logInWithCookies.py` —— 登录判定（最致命）

| 项 | 原实现 | 现实现 |
|---|---|---|
| 判定登录 | `page.wait_for_selector('.nickname')` | 访问 `club.jd.com/.../myJdcomment` 看是否被重定向到 `passport.jd.com` |
| 失效处理 | `os.remove(cookies.json)` **直接删除** | `os.replace(... → cookies.json.bak)` **改为备份** |
| 浏览器窗口 | 默认小窗 | `--start-maximized` |

**为什么必须改**：2026-09 实测京东首页 `.nickname` / `.user-info` / `#ttbar-login`
元素数**全为 0**。判定必然超时 → 被判为「cookies 失效」→ 而原代码的处理是
`os.remove()`。用户 9-15 的日志里「Cookies 已失效」后面紧跟「未找到 Cookies 文件」，
就是它自己刚删的。**等于每次白登录一次。**

### 2. `pc/src/AutomaticEvaluate.py` —— 超时全面放宽

| 位置 | 原值 | 现值 |
|---|---|---|
| `__step_2` 评价页等待 | 2000ms / 超时 3000ms | 4000ms / 超时 15000ms |
| `__step_3` 商详页等 `.all-btn` | 2000ms | 先等 3000ms，超时 15000ms |
| `__automatic_evaluate` 文本输入框 | 3000ms + 绝对 XPath | 先等 3000ms + 相对选择器 |
| 文件上传框 `input[type=file]` | 2000ms | 15000ms |
| 提交按钮 `.btn-submit` | 2000ms | 15000ms |

实测依据：京东评价页首屏渲染 ≥5s；商详页评价弹层（`#rateList`）点击「全部评价」
之后需要 4s 以上才渲染出虚拟列表。

### 3. 虚拟列表抓取改为「重试 + 滚动催促」

`__get_text_infinite_scroll_version` / `__get_image_infinite_scroll_version` 两处：

- 原逻辑：对 `div[data-testid="virtuoso-item-list"] > div[data-item-index=N]`
  **单次** `wait_for_selector(timeout=2000)`，一超时就打
  `相关商品没有评价！` 并 `break`。
- 现逻辑：每个索引最多试 3 次，失败时 `mouse.wheel(0, 900)` 滚动催促渲染
  （该弹层**必须滚动才会渲染后续索引**）；连续 3 个索引取不到才判定到尾，正常结束。

### 4. 去掉两处复制笔误

`__get_text_infinite_scroll_version` 与 `__get_image_infinite_scroll_version` 中，
注释写着「点击只看当前商品」，选择器却**又写了一遍 `.all-btn`** —— 等于把刚展开的
评价弹层再点一次，很可能直接把弹层关掉。实测弹层里也没有 `#comm-curr-sku`
单选项，故整段停用（保留注释说明原因）。

### 5. 评论文本输入框：绝对 XPath → 相对选择器

- 原：`/html/body/div[4]/div/div/div[2]/div[1]/div[7]/.../textarea[1]`，页面层级一动就废。
- 现：`.f-textarea textarea` 全量遍历，并跳过两类框：
  - placeholder 含「服务」的框（那是**店铺服务评价**，不是商品评价）；
  - 已有内容的框（保证多商品订单**逐个商品评**，不重复评同一个）。

### 6. `pc/src/api_service.py` —— 可选依赖不再卡死主流程

`python-dotenv` 与 `websocket-client` 只在「用 AI 生成文案」时需要，
原代码是顶层 `import`，缺包直接 `ModuleNotFoundError` → **整个工具起不来**。
现改为 try/except 可选导入，缺包不影响默认的「抓取已有真实评价」模式。
另外 `self.ws: websocket.WebSocketApp = None` 这种会实际求值的注解也一并去掉。

### 7. `__step_1` 加翻页保护

原为 `while True`，只靠 `.tip-icon` 判断列表结束。京东不再渲染该元素就会**无限翻页空转**。
现加两重保护：页数上限 `MAX_PAGES`（20）+ 本页 `.btn-def` 数为 0 即结束。

### 8. 命令行参数映射修复（隐藏 Bug）

原 `parse_args()` 用「dest 名转大写作类属性名」的朴素方式赋值，但这几个对不上：

| 参数 | dest | 真实类属性 |
|---|---|---|
| `-md` | `min_descriptions` | `MIN_EXISTING_PRODUCT_DESCRIPTIONS` |
| `-mi` | `min_images` | `MIN_EXISTING_PRODUCT_IMAGES` |
| `-mc` | `min_charcount` | `MIN_DESCRIPTION_CHAR_COUNT` |
| `-g` | `ai_group` | `CURRENT_AI_GROUP` |
| `-m` | `ai_model` | `CURRENT_AI_MODEL` |

后果：**这些参数从来就没生效过**，只在终端打一行「未知参数错误」不报错。
尤其 `-g/-m` —— 也就是说**命令行走 AI 生成文案一直是个摆设**（必须改源码里的类属性才能用）。
现已加别名映射表，全部生效。

### 9. 新增实用参数

| 参数 | 作用 |
|---|---|
| `-wl / --whitelist` | 白名单，只处理指定订单编号（试跑用） |
| `-bl / --blacklist` | 黑名单，跳过指定订单编号 |
| `-mt / --max-tasks` | 最多处理多少个商品评价任务，`1` = 只跑第一件商品 |

`MAX_TASKS` / `WHITELIST` / `BLACKLIST` / `MAX_PAGES` 同时也是类属性，改源码即可长期生效。

> 注：原代码 `__generate_task()` 里的白/黑名单是**局部空列表**（死代码，永远不生效），
> 现改为读取类属性。

### 10. 抓图数量上限尊重 `-mi`

原为 `len(image_url_group) >= max(20, MIN_EXISTING_PRODUCT_IMAGES)`，
导致 `-mi` 在 20 以下**完全无效**，抓图阶段被迫至少跑满 20 组（很慢）。
现改为直接取 `MIN_EXISTING_PRODUCT_IMAGES`：想快就调小，想图多就调大。

---

## 三、怎么用

### 第一次 / cookies 过期后

```
1_LoginAndDiagnose.bat
```
弹浏览器 → 手动登录（推荐扫码或验证码，有效期更长）→ cookies 自动保存到
`pc/cookies/cookies.json` 与 `D:\JD-AutomaticEvaluate\cookies.json`（双写，兼容 exe）。

> cookies 存在 `thor` + `pin` 即可用，**不需要 `pt_key`**（实测 2026-09 账号里就没有 pt_key）。

### 试跑（只填不提交，只跑一个订单一件商品）

```
2_TrialRun_NoSubmit.bat
```
回车使用默认订单号，或输入别的订单号。跑完浏览器**故意不关**，自己核对表单。

### 正式全自动（会真的提交）

```
3_Run_FullAuto.bat
```
会遍历所有待评价订单并提交。可先输入要排除的订单号。

### 直接用命令行

```bash
# 试跑第一单第一件商品，不提交，DEBUG 日志
python JDpc-AutomaticEvaluate.py -cac -mt 1 -wl 3620277019820006 -L DEBUG

# 全量自动提交
python JDpc-AutomaticEvaluate.py

# 用 AI（xAI）生成文案，跳过某几个订单
python JDpc-AutomaticEvaluate.py -g XAI -m grok-3 -bl 3620277019820006 3651234567890123
```

常用开关：

| 开关 | 含义 |
|---|---|
| `-cac` | 关闭自动提交（只填表单，人工确认） |
| `-md N` | 商品已有文案最少条数（默认 15） |
| `-mi N` | 商品已有图片最少张数（默认 15） |
| `-mc N` | 筛选已有文案的最少字数（默认 60，京东「优质评价」门槛） |
| `-gc` | 保底评价：抓不到素材时用默认文案池 |
| `-dtv 1` | 遇到图灵验证时阻塞等你手动过，而不是直接退出 |
| `-L DEBUG` | 全量日志（排障用） |

日志：`pc/logs/log_YYYY-MM-DD.log`

---

## 四、环境要求（已确认本机可用）

- Python：`C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe`（3.14.5）
- 已装：`playwright 1.60.0`、`loguru`、`pillow`、`requests`
- **未装**：`python-dotenv`、`websocket-client` —— 已改为可选，只影响 AI 生成文案

---

## 四·五、⚠️ 风控（2026-09-22 实测踩到）

调试当晚连跑 3 次完整试跑，10 分钟后评价区提示「正在维修」——**评价接口被软封**。

**原因是调试方式，不是工具本身**：短时间内反复打开同一商详页评价弹层 +
逐个点击每张晒单图开预览再关闭，是最像脚本的行为组合。

**处置**：
1. 立即停手，**不要「再试试看」**——反复探测会延长封锁；
2. 用正常浏览器正常逛京东，让会话保持活跃；
3. 一般几小时到 24 小时自行解除。**封的是评价接口**，登录和待评价列表通常不受影响。

**使用铁律**：
- **一次只跑一次。** 验证靠读日志，不靠重跑。
- 调试一律用 `2_TrialRun_NoSubmit.bat`（只填不提交），且一轮就够。
- 抓图阶段最危险 → 把 `-mi` 调小（3–5），别把评价弹层翻个底朝天。
- 全量跑建议放闲置时段，单次完成，多单之间留间隔。

**判断依据（21:28 已实测拿到铁证）**：

| 现象 | 更像 |
|---|---|
| 弹层内文本 = **`商品评价 \| 页面正在维修中，请稍后重试`** | **风控**（这是京东评价区软封的原文签名） |
| 弹层正常列出评价、但元素计数为 0 | 真改版，改选择器 |

判据不止「看提示」，还要看这两条：

- `#rateList` count=1（弹层壳开了）但 `virtuoso=0 / data-item-index=0`（里面 0 条）→ 接口被卡。
- **首屏那 3 条「热门评价」和它的图片仍然正常**（`img30.360buyimg.com/shaidan/...` 返回 200）。
  那是**另一套接口**，千万别拿它当「评价区正常」的证据。

### ★ 浏览器切换（2026-09-22 21:27 起）

同一账号、同一 IP、同一时刻的对照实验：

| 浏览器 | 「全部评价」弹层 |
|---|---|
| Playwright 自带 Chromium | `商品评价 \| 页面正在维修中，请稍后重试` ❌ |
| 换 `channel="msedge"`（真 Edge） | 完整评价列表 ✅ |

→ **京东封的是浏览器指纹/会话，不是 IP、不是账号。** 已把工具切到本机 Edge：

- 源码模式：`launch_persistent_context(channel="msedge", user_data_dir=pc/edge-profile)`
  —— **固定 profile 持久化**（默认每次新建临时 profile = 「每 3 分钟换一台新设备」，是强风控信号）
- 启动失败自动回退内置 Chromium；打包 exe 模式不变
- 环境变量 `JD_BROWSER_CHANNEL` 可切换（留空 = 用内置 Chromium）
- 追加启动参数 `--no-first-run / --no-default-browser-check / --disable-features=msEdgeFirstRunExperience`

**但换浏览器只是必要条件，不是充分条件。** 实测 21:27 成功后，21:28、21:31 两次连点**又被限流**。
京东的限流是**行为触发**的：指纹对了、profile 固定了、节奏慢了，**剩下的就是别短时间内反复跑**。

**因此：21:31 之后已全面停手。建议隔几个小时（最好隔夜）再跑，且只跑一次。**

验证手段优先级（越靠后越危险）：

1. **你自己用日常浏览器点一次「全部评价」** —— 零自动化信号，最安全，
   还能顺带判断是「IP 级封锁」还是「会话/指纹级封锁」；
2. 最小探测（1 次加载 + 1 次点击，不点图片）；
3. 完整试跑（`2_TrialRun_NoSubmit.bat`）—— **一轮为限**；
4. 全量提交 —— 确认没问题后再做，放闲置时段。

---

## 五、已知限制（对手视角，先给你交底）

1. **京东下次改版还会挂。** 该项目 8 个月内发了 10 次「网页元素变动适配」，作者已停更约 9 个月。
   这次修好只能保证「当前版本可用」，不保证长期。好处是源码在手，以后自己能改。
2. **抓图阶段很慢。** 每组图要逐个点击开预览 → 取 URL → 关预览，一条 9 图的评价约 36s。
   想快就把 `-mi` 调小（比如 5）。
3. **图片版权/查重。** 用的是同款商品下真实买家秀的图。京东对重复图会判「参考价值低」，
   可能影响京豆奖励，但不影响评价发布。
4. **提交不可撤销。** 京东评价发布后不能改。所以先用 `2_TrialRun_NoSubmit.bat` 看效果。
5. **图灵验证**：`-dtv` 默认 0（遇到就退出）。要无人值守就设 `-dtv 1`，但得有人守着过验证。

---

## 附：改动文件一览

| 文件 | 改动 |
|---|---|
| `pc/src/logInWithCookies.py` | 登录判定重写 + cookies 备份不删除 + 最大化窗口 |
| `pc/src/AutomaticEvaluate.py` | 超时放宽 / 虚拟列表重试 / 笔误停用 / 相对选择器 / 翻页保护 / 参数映射 / 新增 3 个参数 / 抓图上限 |
| `pc/src/api_service.py` | dotenv 与 websocket 降为可选导入 |
| 新增 `2_TrialRun_NoSubmit.bat` | 试跑（不提交） |
| 新增 `3_Run_FullAuto.bat` | 全量自动提交 |
| 新增 `_probe_cookie.py` | 快速验证 cookies 是否仍有效 |

所有改动处均带 `[FIX 2026-09-22 WorkBuddy]` / `[ADD 2026-09-22 WorkBuddy]` 注释，便于日后对照。

---

## 附二：与上游仓库的对齐情况（2026-09-22 21:37）

已克隆上游 `Goodnameisfordoggy/JD-AutomatedTools`（HEAD `d215cd1`，2025-12-25）到
`D:\JD-AutomaticEvaluate\upstream`，与工作副本逐文件比对：

| 类别 | 结果 |
|---|---|
| `pc/` 下的其他文件（`data.py` / `logger.py` / `__init__.py` / `common/utils.py` / `JDpc-AutomaticEvaluate.py` / `requirements.txt`） | **完全一致** |
| 有差异的文件 | 仅 3 个，**全部是我们打的补丁**（已逐块核对，无上游改动被覆盖） |
| 上游有、我们缺的 | `ios/`（iOS 版）、`README.md`、`.gitignore` —— **已并入** |

**补丁文件**：`D:\JD-AutomaticEvaluate\WorkBuddy_JD修复补丁_20260922.patch`
（3 files changed, 412 insertions(+), 92 deletions(-)）

已验证：
- `git apply --check` 通过（可干净打到纯上游克隆上）
- 应用后 3 个文件与工作副本**逐字节一致**
- 验证完已把 upstream 还原为纯净克隆

用法见 `补丁使用说明.md`。

**⚠️ 推到自己仓库前**：`.gitignore` 已排除 `.env` / `pc/cookies/` / `pc/logs/` /
`pc/edge-profile/`，推之前务必 `git status` 再扫一眼 —— 凭据和日志绝不能进公开仓库。
