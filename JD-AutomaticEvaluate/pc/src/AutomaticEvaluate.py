'''
Author: HDJ @https://github.com/Goodnameisfordoggy
LastEditTime: 2025-07-12 23:31:13
FilePath: \pythond:\LocalUsers\Goodnameisfordoggy-Gitee\JD-Automated-Tools\JD-AutomaticEvaluate\pc\src\AutomaticEvaluate.py
Description: @VSCode

				|	早岁已知世事艰，仍许飞鸿荡云间；
				|	曾恋嘉肴香绕案，敲键弛张荡波澜。
				|					 
				|	功败未成身无畏，坚持未果心不悔；
				|	皮囊终作一抔土，独留屎山贯寰宇。

Copyright (c) 2024-2025 by HDJ, All Rights Reserved. 
'''
import os
import re
import sys
import time
import random
import hashlib
import secrets
import argparse
import requests
from PIL import Image, ImageFilter
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, Locator, ElementHandle, Page 

from pc.src import TEMP_IMAGE_DIR
from pc.src.data import EvaluationTask, TuringVerificationRequiredError, NetworkError, DEFAULT_COMMENT_TEXT_LIST
from pc.src.logger import get_logger, init_logger
from pc.src.api_service import *
from pc.src.logInWithCookies import logInWithCookies
from common.utils import *

LOG = get_logger()


class AutomaticEvaluate(object):

	MIN_EXISTING_PRODUCT_DESCRIPTIONS: int = 15  	# 商品已有文案的最少数量 | 真实评论文案多余这个数脚本才会正常获取已有文案。
	MIN_EXISTING_PRODUCT_IMAGES: int = 15        	# 商品已有图片的最少数量 | 真实评论图片多余这个数脚本才会正常获取已有图片。
	MIN_DESCRIPTION_CHAR_COUNT: int = 60         	# 评论文案的最少字数 | 在已有评论中随机筛选文案的限制条件，JD:优质评价要求60字以上。
	CLOSE_SELECT_CURRENT_PRODUCT: bool = False   	# 关闭仅查看当前商品 | 启用此设置，在获取已有评论文案与图片时将查看商品所有商品评论信息，关闭可能会导致评论准确性降低
	CLOSE_AUTO_COMMIT: bool = False                 # 关闭自动提交 | 启用此设置，在自动填充完评价页面后将不会自动点击提交按钮
	DEAL_TURING_VERIFICATION: int = 0           	# 图灵测试的处理 | 0触发测试直接退出，1阻塞等待手动处理
	GUARANTEE_COMMIT: bool = False                  # 保底评价 | 在获取不到已有信息时使用文本默认评价并提交
	CURRENT_AI_GROUP: str = ""                   	# AI模型的组别名称 | 使用AI模型生成评论文案
	CURRENT_AI_MODEL: str = ""                   	# AI模型的名称 | 使用AI模型生成评论文案
	LOG_LEVEL: str = "INFO"                         # 日志记录等级
	MAX_TASKS: int = 0                              # [ADD 2026-09-22 WorkBuddy] 最多处理多少个商品评价任务；0 = 不限。试跑时设 1 可只跑第一件商品
	MAX_PAGES: int = 20                             # [FIX 2026-09-22 WorkBuddy] 待评价列表页最多翻多少页，防止「结束标志失效」时死循环
	WHITELIST: list = []                            # [FIX 2026-09-22 WorkBuddy] 只处理这些订单（按 订单编号 或 orderVoucher url 匹配）；留空 = 不限制
	BLACKLIST: list = []                            # [FIX 2026-09-22 WorkBuddy] 跳过这些订单；留空 = 不限制

	def __init__(self) -> None:
		self.__page, browser = None, None
		self.__task_list: list[EvaluationTask] = []
		self.__start_time = time.time() # 标记初始化时间戳
		self.__err_occurred = False

	@classmethod
	def parse_args(cls):
		"""解析命令行参数，并直接修改类属性"""
		parser = argparse.ArgumentParser(
			description="https://github.com/Goodnameisfordoggy/JD-AutomatedTools/tree/main/JD-AutomaticEvaluate",
			prog="JD-AutomaticEvaluate")

		parser.add_argument('-v', '--version', action='version', version='%(prog)s version: 2.9.19')
		parser.add_argument('-T', '--supported-table', action=ShowSupportedTableAction, help="show supported AI groups and models")
		parser.add_argument('-L', '--log-level', type=str, default="INFO", dest="log_level", help="DEBUG < INFO < WARNING < ERROR < CRITICAL")

		auto_settings = parser.add_argument_group(title="自动化设置")
		auto_settings.add_argument('-md', '--min-descriptions', type=int, default=15, dest="min_descriptions", help="商品已有文案的最少数量(15) | 真实评论文案多余这个数工具才会正常获取已有文案。")
		auto_settings.add_argument('-mi', '--min-images', type=int, default=15, dest="min_images", help="商品已有图片的最少数量(15) | 真实评论图片多余这个数工具才会正常获取已有图片。")
		auto_settings.add_argument('-mc', '--min-charcount', type=int, default=60, dest="min_charcount", help="评论文案的最少字数(60) | 在已有评论中随机筛选文案的限制条件，JD:优质评价要求60字以上。")
		# 使用 store_true 动作：如果命令行传入 --auto-commit 参数，则 auto_commit 为 True，否则为 False
		auto_settings.add_argument('-cscp', '--close-select-current-product', action='store_true', default=False, dest="close_select_current_product", help="关闭仅查看当前商品 | 启用此设置，在获取已有评论文案与图片时将查看商品所有商品评论信息，关闭可能会导致评论准确性降低")
		auto_settings.add_argument('-cac', '--close-auto-commit', action='store_true', default=False, dest="close_auto_commit", help="关闭自动提交 | 启用此设置，在自动填充完评价页面后将不会自动点击提交按钮")
		auto_settings.add_argument('-dtv', '--deal-turing-verification', type=int, choices=[0, 1], default=0, dest="deal_turing_verification", help="图灵测试的处理| 0触发测试直接退出，1阻塞等待手动处理")
		auto_settings.add_argument('-gc', '--guarantee-commit', action='store_true', default=False, dest="guarantee_commit", help="保底评价 | 在获取不到已有信息时使用文本默认评价并提交")
		# [ADD 2026-09-22 WorkBuddy] 白/黑名单，便于「只试跑某一单」或跳过个别订单。留空不传 = 全部处理。
		auto_settings.add_argument('-wl', '--whitelist', type=str, nargs='+', default=None, dest="whitelist", help="白名单 | 只处理这些订单编号（可多个，空格分隔）")
		auto_settings.add_argument('-bl', '--blacklist', type=str, nargs='+', default=None, dest="blacklist", help="黑名单 | 跳过这些订单编号（可多个，空格分隔）")
		auto_settings.add_argument('-mt', '--max-tasks', type=int, default=None, dest="max_tasks", help="最多处理多少个商品评价任务(0=不限) | 试跑建议设 1")

		ai_settings = parser.add_argument_group(title="AI设置", description="-g 与 -m 需同时设置;")
		ai_settings.add_argument('-g', '--ai-group', type=str, default=None, dest="ai_group", help="AI模型的组别名称 | 使用AI模型生成评论文案")
		ai_settings.add_argument('-m', '--ai-model', type=str, default=None, dest="ai_model", help="AI模型的名称 | 使用AI模型生成评论文案")
		args = parser.parse_args()  # 解析命令行参数

		# [FIX 2026-09-22 WorkBuddy] 原实现是「dest 名直接转大写作类属性名」，但
		# -md/-mi/-mc/-g/-m 的 dest（min_descriptions / min_images / min_charcount /
		# ai_group / ai_model）与真实类属性名对不上：
		#     MIN_EXISTING_PRODUCT_DESCRIPTIONS / MIN_EXISTING_PRODUCT_IMAGES /
		#     MIN_DESCRIPTION_CHAR_COUNT     / CURRENT_AI_GROUP / CURRENT_AI_MODEL
		# 结果这些命令行参数全部静默失效（只在终端打一行「未知参数错误」，不报错），
		# 包括最关键的 -g/-m —— 也就是说命令行走 AI 生成文案从来就没生效过。
		# 故加一张别名映射表。
		ALIASES = {
			"min_descriptions": "MIN_EXISTING_PRODUCT_DESCRIPTIONS",
			"min_images": "MIN_EXISTING_PRODUCT_IMAGES",
			"min_charcount": "MIN_DESCRIPTION_CHAR_COUNT",
			"ai_group": "CURRENT_AI_GROUP",
			"ai_model": "CURRENT_AI_MODEL",
		}
		# 直接使用 dest 参数的全大写形式更新类属性
		for key, value in vars(args).items():
			if key == "supported_table":  # -T 由自定义 Action 自行处理，不映射到类属性
				continue
			attr = ALIASES.get(key, key.upper())
			if value is not None and hasattr(cls, attr):
				setattr(cls, attr, value)
			elif not hasattr(cls, attr):
				print(f"未知参数错误：{key}")
		return cls

	def exec_(self) -> bool | None:
		"""主循环"""
		try:
			init_logger(self.LOG_LEVEL)
			if self.CURRENT_AI_MODEL or self.CURRENT_AI_GROUP:
				from pc.src.api_service import init_env
				init_env()
			self.__page, _ = logInWithCookies()
			self.__init_image_directory(TEMP_IMAGE_DIR)

			# [ADD 2026-09-22 WorkBuddy] 风控规避：多单之间留随机间隔，避免机械连续作业
			_task_no = 0
			for task in self.__generate_task():
				if _task_no > 0:
					_pause = random.randint(15, 45)
					LOG.info(f"多单间隔：休息 {_pause} 秒（降低风控概率）")
					self.__page.wait_for_timeout(_pause * 1000)
				_task_no += 1
				LOG.debug(f"任务已生成：{task}")
				self.__automatic_evaluate(task)
			return True
		except Exception as err:
			self.__err_occurred = True
			LOG.error(f"执行过程中发生异常: {str(err)}")
			if self.LOG_LEVEL == "DEBUG":
				raise # 调试专用
		finally:
			hours, remainder = divmod(int(time.time()-self.__start_time), 3600)
			minutes, seconds = divmod(remainder, 60)
			# 根据是否有异常发生，显示不同的结束信息
			if self.__err_occurred:
				LOG.warning(f"JD-AutomaticEvaluate: 意外退出--耗时:{hours:02d}小时-{minutes:02d}分钟-{seconds:02d}秒")
			else:
				LOG.success(f"JD-AutomaticEvaluate: 运行结束--耗时:{hours:02d}小时-{minutes:02d}分钟-{seconds:02d}秒")
			# 打包模式保留终端窗口
			if getattr(sys, 'frozen', False):
				input("按任意位置继续...")

	def __step_1(self):
		"""
		创建任务，获取 `orderVoucher_url`
		"""
		page = 1 # 起始页
		# [FIX 2026-09-22 WorkBuddy] 原为 `while True`，仅靠 .tip-icon 兜底。
		# 一旦京东不再渲染 .tip-icon，就会无限翻页空转。加页数上限。
		while page <= self.MAX_PAGES:
			url_1 = f'https://club.jd.com/myJdcomments/myJdcomment.action?sort=0&page={page}' # 待评价订单页面
			try:
				# 等待结束标志
				if self.__page.wait_for_selector('.tip-icon', timeout=5000):
					LOG.info('识别到结束标志，所有待评价页面url获取结束！') #检查元素tip-icon，这个元素标识没有待评价的订单了
					break
			except PlaywrightTimeoutError:
				LOG.info('结束标志未出现！')

			try:
				self.__load_page(url_1, timeout=20000)
			except PlaywrightTimeoutError:
				raise NetworkError(message=f"页面加载超时：{url_1}")

			btn_elements: list = self.__page.locator('.btn-def').element_handles()
			# [FIX 2026-09-22 WorkBuddy] 本页没有「评价」按钮 = 没有待评价订单，直接结束。
			# 避免 .tip-icon 失效时翻到空页仍继续。
			if not btn_elements:
				LOG.info(f'第 {page} 页未发现待评价订单，任务收集结束！')
				break
			for btn_element in btn_elements:
				parent_element = btn_element.evaluate_handle("el => el.closest('.operate')")
				# 检查父级元素中是否包含提示“请在手机客户端查看订单详情”
				try:
					mobile_tip_element = parent_element.query_selector('.tip-box .item-fore h3')
					if mobile_tip_element and "请在手机客户端查看订单详情" in mobile_tip_element.inner_text():
						LOG.info("外卖订单(跳过)或该订单仅限手机客户端查看")
						continue  # 跳过该元素
				except Exception as e:
					LOG.debug(f"检查提示信息时出错: {e}")
				orderVoucher_url: str = 'https:' + btn_element.get_attribute('href')
				# [FIX 2026-09-22 WorkBuddy] 白/黑名单在收集阶段就生效，避免为了过滤 1 单
				# 还要把 20 个评价页全打开一遍。京东列表页的 ruleid 即「订单编号」，
				# 所以用订单编号当关键词即可命中。
				if self.WHITELIST and not any(k in orderVoucher_url for k in self.WHITELIST):
					continue
				if self.BLACKLIST and any(k in orderVoucher_url for k in self.BLACKLIST):
					continue
				task = EvaluationTask()
				task.orderVoucher_url = orderVoucher_url
				# LOG.debug(f"{task}")
				self.__task_list.append(task)
			page += 1

	def __step_2(self):
		"""
		进入评价页面，获取 `order_id` `productHtml_url` `product_name`；
		"""
		for task in self.__task_list:

			try:
				self.__load_page(task.orderVoucher_url, timeout=30000)
			except PlaywrightTimeoutError:
				raise NetworkError(message=f"页面加载超时：{task.orderVoucher_url}")

			# [FIX 2026-09-22 WorkBuddy] 原为 wait_for_timeout(2000) + timeout=3000。
			# 实测京东评价页首屏渲染要 5s+，9-15 日志正是崩在这一句
			# （Page.wait_for_selector: Timeout 3000ms exceeded）。
			self.__page.wait_for_timeout(timeout=4000)  # 等待元素加载
			order_id_element = self.__page.wait_for_selector('//*[@id="o-info-orderinfo"]/div/div/span[1]/a', timeout=15000)
			order_id = order_id_element.inner_text()  # 评价页面的订单编号
			task.order_id = order_id

			goods_elements: Locator = self.__page.locator('.comment-goods')
			child_task_list: list[EvaluationTask] = [] # 一个评论页面下的所有子商品
			for i in range(goods_elements.count()):
				child_task = task.copy() # 为多个子任务同步任务信息 order_id, orderVoucher_url
				goods_element: Locator = goods_elements.nth(i) # 每个商品的区域
				# 商品名称
				product_link_ele = goods_element.locator('div.p-name > a')
				product_name = product_link_ele.inner_text()
				child_task.product_name = product_name

				try:
					# 商品详情页面 url
					productHtml_url_text = product_link_ele.get_attribute("href", timeout=3000)
					if not productHtml_url_text or "javascript:void(0)" in productHtml_url_text :
						# 部分有 href 但值为空，也走超时处理
						raise PlaywrightTimeoutError(message="href为空值")
					productHtml_url = "https:" + productHtml_url_text
					child_task.productHtml_url = productHtml_url
				except PlaywrightTimeoutError:
					LOG.error(f"单号 {task.order_id} 商品详情页面链接获取超时")
					if self.GUARANTEE_COMMIT is False:
						continue

				# LOG.debug(f"{task}")
				child_task_list.append(child_task)
			yield child_task_list

	def __step_3(self, task: EvaluationTask) -> EvaluationTask:
		"""
		获取评论文本与图片
		"""
		input_text = ""
		input_image = []
		# 使用已有的文案，图片
		if task.productHtml_url:
			try:
				self.__load_page(task.productHtml_url, timeout=30000) # 部分页面加载缓慢，如京东国际
				LOG.debug(f'goto {task.productHtml_url}')
			except PlaywrightTimeoutError:
				raise NetworkError(message=f"页面加载超时：{task.productHtml_url}")

			version = None
			# [FIX 2026-09-22] 商详页评价区是异步渲染的，原 2000ms 太短。
			# 再放宽到 8000ms：对照实验发现「先稳定等 10s 再点全部评价」才稳定点开弹层，
			# 只等 3s 时点击会被吞掉（2026-09-22 21:29 Edge 试跑实测）。
			self.__page.wait_for_timeout(timeout=8000)
			try:
				if self.__page.wait_for_selector('.all-btn', timeout=15000):
					version = 2024
			except PlaywrightTimeoutError:
				# 目前来看JD国际等商品使用的是2014的界面，直接简单粗暴匹配两个关键元素
				try:
					if self.__page.wait_for_selector('li[data-tab="trigger"][data-anchor="#comment"]', timeout=2000):
						version = 2014
				except PlaywrightTimeoutError:
					self.__requires_TuringVerification()
			match version:
				case 2014:
					# 使用 AI 模型生成评价文案; 确认页面版本后再获取避免浪费 tokens
					if self.CURRENT_AI_GROUP and self.CURRENT_AI_MODEL:
						input_text: str = self.__get_text_from_ai(task.product_name)
					# 获取已有评价内容
					else:
						input_text: str = self.__get_text_paginated_version()

						try:
							self.__load_page(task.productHtml_url, timeout=30000) # 重定向到商详页；部分页面加载缓慢，如京东国际；
						except PlaywrightTimeoutError:
							raise NetworkError(message=f"页面加载超时：{task.productHtml_url}")

					input_image: list = self.__get_image_paginated_version()
				case 2024:
					if self.CURRENT_AI_GROUP and self.CURRENT_AI_MODEL:
						input_text: str = self.__get_text_from_ai(task.product_name)
					else:
						input_text: str = self.__get_text_infinite_scroll_version()

						try:
							self.__load_page(task.productHtml_url, timeout=30000) # 重定向到商详页；部分页面加载缓慢，如京东国际；
						except PlaywrightTimeoutError:
							raise NetworkError(message=f"页面加载超时：{task.productHtml_url}")

					input_image: list = self.__get_image_infinite_scroll_version()
				case _:
					if self.__requires_TuringVerification():
						pass
					else:
						# 如果没有跳验证，那么大概率是页面变动了
						LOG.critical(f"商品 {task.productHtml_url} 页面发生变动，请issue联系作者！")

		else:
			# 没有商详页 url
			if not task.productHtml_url:
				LOG.warning(f"商品详情 {task.productHtml_url} 页面加载失败！")
			# 保底生成评价文案
			if self.GUARANTEE_COMMIT is True and not task.input_text:
				input_text = random.choice(DEFAULT_COMMENT_TEXT_LIST)
				LOG.warning(f'单号 {task.order_id} 的订单使用了默认文案池。')

		task.input_text = input_text
		task.input_image = input_image
		return task

	def __generate_task(self):
		self.__step_1()
		# [ADD 2026-09-22 WorkBuddy] 任务数上限，便于试跑（MAX_TASKS=1 只跑第一件商品）
		_yielded = 0

		for child_task_list in self.__step_2():
			for child_task in child_task_list:
				LOG.info("正在生成任务......")
				# [FIX 2026-09-22 WorkBuddy] 原代码把白/黑名单写成局部空列表，永远不生效（死代码）。
				# 改为读取类属性 WHITELIST / BLACKLIST，支持按「订单编号」或 orderVoucher url 匹配。
				# 两者默认留空 → 行为与原版完全一致（不限制）。
				blacklist = self.BLACKLIST or []
				whitelist = self.WHITELIST or []
				_key = f"{child_task.order_id}|{child_task.orderVoucher_url}"
				if whitelist and not any(k in _key for k in whitelist): # 白名单
					continue
				if blacklist and any(k in _key for k in blacklist): # 黑名单
					continue
				task = self.__step_3(child_task)
				_yielded += 1
				yield task
				if self.MAX_TASKS and _yielded >= self.MAX_TASKS:
					LOG.info(f"已达到 MAX_TASKS={self.MAX_TASKS} 上限，任务生成提前结束。")
					return

	@staticmethod
	def is_bmp_compliant(text: str):
		"""
		检测所有字符是否符合基本多文种平面 BMP(Basic Multilingual Plane)
		"""
		for char in text:
			if ord(char) > 0xFFFF:
				return False
		return True

	def get_random_text(self, text_list):
		"""
		取随机评价
		"""
		if not text_list or len(text_list) * 2 < self.MIN_EXISTING_PRODUCT_DESCRIPTIONS:
			LOG.info("已有评论文案过少，无法进行随机筛选！")
			return ""
		selected_value = random.choice(text_list)
		if len(selected_value) > self.MIN_DESCRIPTION_CHAR_COUNT and self.is_bmp_compliant(selected_value): # 取长度大于规定个字符的评价文案。
			return selected_value
		else:
			return self.get_random_text(text_list)

	def __get_text_paginated_version(self) -> (str | None):
		"""
		从网页上获取已有的评价文本，随机翻页版
		"""
		# 点击“商品评价”
		try:
			element_to_click_1 = self.__page.wait_for_selector('li[data-tab="trigger"][data-anchor="#comment"]', timeout=2000)
			element_to_click_1.click()
		except PlaywrightTimeoutError:
			LOG.warning("“商品评价” 点击失败")
			self.__requires_TuringVerification()

		try:
			if self.__page.wait_for_selector('img[alt="展示图片"]', timeout=2000):
				LOG.info("检测到展示图片，开始滚动加载")
				# 滚动到底部触发加载
				self.__page.evaluate("""
					window.scrollTo({
						top: document.documentElement.scrollHeight,
						behavior: 'smooth'
					});
				""")
				self.__page.wait_for_timeout(timeout=2000)  # 等待内容加载
				# 获取新的页面高度后滚动到30%位置
				new_height = self.__page.evaluate('document.documentElement.scrollHeight')
				self.__page.evaluate(f"""
					window.scrollTo({{
						top: {new_height * 0.3},
						behavior: 'smooth'
					}});
				""")
				self.__page.wait_for_timeout(timeout=1000) # 等待元素稳定
		except PlaywrightTimeoutError:
			LOG.debug("未检测到展示图片，继续执行")
			#部分采用2014网页的商品，点击全部评论，会先出现“京东工业”图片，影响元素加载
			#需要先滚动到底部，发出请求
			#之后重新滚动新页面高度30%，避免出现加载不完全

		try:
			if self.CLOSE_SELECT_CURRENT_PRODUCT is False:
				# 点击“只看当前商品”
				element_to_click_2 = self.__page.wait_for_selector('#comm-curr-sku', timeout=2000)
				element_to_click_2.click()
		except PlaywrightTimeoutError:
			self.__requires_TuringVerification()

		text_list = []
		for page in range(1, 4):
			LOG.debug(f'Turn to page {page}')
			self.__page.wait_for_timeout(timeout=1000) # QwQ适当停顿避免触发反爬验证, 同时等待元素内容加载完毕
			try:
				comment_con_elements = self.__page.locator('.comment-con').element_handles()
				for comment_con_element in comment_con_elements:
					text_list.append(comment_con_element.inner_text())
			except Exception as err:
				if page == 1:
					LOG.info('当前暂无评价')
					break
			# 翻页
			try:
				pager_next_element = self.__page.wait_for_selector('.ui-pager-next', timeout=2000)
				pager_next_element.click()
			except PlaywrightTimeoutError:
				LOG.info('已到最后一页，抓取页数小于设定数！')
				break

		try:
			text = self.get_random_text(text_list[int(len(text_list) / 2):]) # 取后半部分评价进行筛选
		except RecursionError:
			LOG.info('未筛出符合要求的评论文案！')
			return ""

		return text

	def __get_text_infinite_scroll_version(self) -> (str | None):
		"""
		从网页上获取已有的评价文本，无限滚动版
		"""
		# 点击 “全部评价”
		# [FIX 2026-09-22 WorkBuddy] 原为 wait_for_selector(timeout=2000) 后直接 click。
		# 实测：该按钮位于页面下方，未滚入视口就点会落空；点击后评价弹层
		# （#rateList → virtuoso-item-list）需数秒渲染。9-15 日志里的
		# "'全部评价'点击失败!" 与 "相关商品没有评价！" 均源于此。
		try:
			all_btn_element = self.__page.wait_for_selector('.all-btn', timeout=15000)
			all_btn_element.scroll_into_view_if_needed()
			self.__page.wait_for_timeout(timeout=800)
			all_btn_element.click()
			# [FIX 2026-09-22 WorkBuddy] 关键门闸：先等虚拟列表容器真的挂载出来，再进抓取循环。
			# 实测（决定性验证报告）：点击后 T+2s 只渲染 3 条，容器要 ~5-9s 才稳定；
			# 若不等这一步而直接把「首条渲染时间」摊进循环，3s 超时会导致 0 条（已实测复现）。
			#
			# [FIX 2026-09-22 第二轮] 增加「点击被吞」与「风控」的区分：
			#   · #rateList 不存在 → 点击没生效 → 允许再点一次
			#   · #rateList 已存在但 virtuoso 迟迟不来 → 接口被卡（风控），再点只会更糟，立即报明
			self.__page.wait_for_timeout(timeout=3000)
			opened = False
			for _try in range(2):
				try:
					self.__page.wait_for_selector('div[data-testid="virtuoso-item-list"]', timeout=15000)
					opened = True
					break
				except PlaywrightTimeoutError:
					if self.__page.locator('#rateList').count() > 0:
						LOG.critical("评价弹层已打开但一条数据都没有 —— 疑似被风控"
									 "（弹层内若显示「页面正在维修中」即为风控，停手等几小时）")
						break
					LOG.warning(f"第 {_try + 1} 次点击未生效，重试点击『全部评价』")
					try:
						all_btn_element.scroll_into_view_if_needed()
						self.__page.wait_for_timeout(timeout=600)
						all_btn_element.click()
						self.__page.wait_for_timeout(timeout=2500)
					except Exception:
						pass
			if opened:
				self.__page.wait_for_timeout(timeout=2000) # 让虚拟列表完成首次铺开
			else:
				LOG.critical("'全部评价'点击失败!")
		except PlaywrightTimeoutError:
			LOG.critical("'全部评价'点击失败!")

		# [FIX 2026-09-22 WorkBuddy] 原代码此处注释写“只看当前商品”，选择器却再次
		# 写成 `.all-btn`（与上一段完全重复），是明显的复制笔误 —— 它会把刚展开的
		# 评价弹层再点一次，很可能直接把弹层关掉。实测弹层内也没有“只看当前商品”
		# 单选项，故停用该分支。
		# try:
		# 	if self.CLOSE_SELECT_CURRENT_PRODUCT is False:
		# 		current_radio_element = self.__page.wait_for_selector('#comm-curr-sku', timeout=3000)
		# 		current_radio_element.click()
		# 	self.__page.wait_for_timeout(timeout=1000) # 等待动态加载
		# except PlaywrightTimeoutError:
		# 	self.__requires_TuringVerification()

		# 包含评价内容的 div 在滚动时动态刷新，且每次刷新数量较少，可看做逐个刷新；每次获取一个评论元素
		text_group = []
		max_scrolls = 60  # 预设滚动次数，等价于抓取的评论元素个数
		miss = 0
		for item_index in range(max_scrolls): # data-item-index 从 0 开始
			# [FIX 2026-09-22 WorkBuddy] 原为单次 wait(timeout=2000)，一超时就
			# LOG.info("相关商品没有评价！") 并 break —— 把“加载慢”误报成“没评价”。
			# 实测该弹层需滚动才会继续渲染后续索引，故改为重试 + 滚动催促。
			item = None
			for attempt in range(3):
				try:
					# [FIX 2026-09-22 WorkBuddy] 实测校准：3000ms 太短（会 0 条），
					# 8000ms 偏慢。6000ms + 3 次重试 + 滚轮催促 是稳妥区间。
					item = self.__page.wait_for_selector(f'div[data-testid="virtuoso-item-list"] > div[data-item-index="{item_index}"]', state="visible", timeout=6000)
					break
				except PlaywrightTimeoutError:
					self.__page.mouse.wheel(0, 900)   # 滚动催促虚拟列表渲染
					self.__page.wait_for_timeout(timeout=800)
			if item is None:
				miss += 1
				if miss >= 4:
					LOG.info(f"连续 4 个索引取不到，判定已到末尾（本次已收集 {len(text_group)} 条）")
					break
				continue
			miss = 0
			if item_index % 10 == 0:
				LOG.debug(f"文案抓取进度: 索引 {item_index}, 已收集 {len(text_group)} 条")
			# 向下滚动，将元素平滑滚动到视图中；对 item 元素进行滚动时需要其可见
			try:
				self.__page.evaluate("element => element.scrollIntoView({behavior: 'smooth', block: 'center'})", item)
				self.__page.wait_for_timeout(timeout=300)
			except Exception:
				pass
			# 获取评价文本
			try:
				text_element = item.wait_for_selector('.jdc-pc-rate-card-main-desc', state="visible", timeout=5000)
				text = text_element.inner_text() # 获取元素属内容前，需等待其可见
				if text:
					text_group.append(text)
			except Exception as err:
				LOG.debug(".jdc-pc-rate-card-main-desc 获取文本失败")
		LOG.info(f"评价文案采集完成，共 {len(text_group)} 条")

		# 随机筛选出一条评价
		try:
			text = self.get_random_text(text_group)
		except RecursionError:
			LOG.info('未筛出符合要求的评论文案！')
			return ""
		return text

	def __get_text_from_ai(self, product_name):
		content = f"""
		背景：我在京东上购买了一款商品 "{product_name}"
		角色：消费者
		任务：请用一段陈述来评价这个商品
		要求：
			[1] 禁止过多的重复商品别名！
			[2] 大约需要100个汉字的文本，且文本长度不少于80个字符！
			[3] 仅用一段陈述完成，不要换行！
		"""
		from pc.src.api_service import Http_XAI, Ws_SparkAI
		while True:
			time.sleep(2)
			match self.CURRENT_AI_GROUP:
				case "XAI":
					text = Http_XAI(content, self.CURRENT_AI_MODEL).get_response()
				case "SparkAI":
					ws_client = Ws_SparkAI(self.CURRENT_AI_MODEL)
					ws_client.send_request(content)
					text = ws_client.get_response()
				case _:
					LOG.error(f"使用了未支持的AI模型：{self.CURRENT_AI_GROUP}:{self.CURRENT_AI_MODEL}")
			if len(text) > self.MIN_DESCRIPTION_CHAR_COUNT:
				LOG.info(f"{self.CURRENT_AI_GROUP}({self.CURRENT_AI_MODEL}): {text}")
				return text

	def get_random_image_group(self, image_url_lists: list) -> list:
		"""
		取随机评价的图片组

		Args:
			image_url_lists (list): [[url(str), ...], ...]

		Returns:
			一个图片组(list): [url(str), ...]
		"""
		if not image_url_lists or sum(len(image_url_list) for image_url_list in image_url_lists) < self.MIN_EXISTING_PRODUCT_IMAGES:
			LOG.info("已有评论图片过少，无法进行随机筛选！")
			return []
		selected_value = random.choice(image_url_lists)
		if len(selected_value) >= 2: # 组内图片数量
			return selected_value
		else:
			return self.get_random_image_group(image_url_lists)

	def download_image_group(self, image_url_group: list):
		"""
		下载图片组到image目录

		Args:
			image_url_group (list): [url(str), ...]

		Returns:
			一个图片组 (list): [absPath(str), ...]
		"""
		image_files_path = []
		# 使用随机哈希标识图片组
		random_bytes = secrets.token_bytes(32)  # 生成随机字节
		hash_object = hashlib.sha256()  # 创建一个 SHA-256 哈希对象
		hash_object.update(random_bytes)    # 更新哈希对象的内容
		order_hash_hex = hash_object.hexdigest()  # 获取十六进制格式的哈希值
		try:
			for index, image_url in enumerate(image_url_group, start=1):
				image_file_path = os.path.join(TEMP_IMAGE_DIR, f'{order_hash_hex[-12:]}_{index}.jpg')
				response = requests.get(image_url)
				if response.status_code == 200:
					# 保存图片到本地文件
					with open(image_file_path, 'wb') as f:
						f.write(response.content)
					image_files_path.append(image_file_path)
					# 处理图片
					img = Image.open(image_file_path)
					img = img.resize((img.width * 5, img.height * 5), Image.LANCZOS) # 提高分辨率
					img = img.filter(ImageFilter.SHARPEN) # 增加清晰度
					img.save(image_file_path)
				else:
					LOG.error(f'{image_url} 文件下载失败！Status code: {response.status_code}')
		except RecursionError:
			LOG.info('未筛出符合要求的图片组！')
		except TypeError: # get_random_image_group返回结果为None时忽略
			pass
		return image_files_path

	def __get_image_paginated_version(self) -> list:
		"""
		获取已有的评价图片(部分)，筛选(随机取一组)后以订单编号为命名依据，并储存到本地。随机翻页版

		Returns:
			image_files_path(list): 储存到本地的(image目录下)隶属一个订单编号下的所有图片文件路径。
		"""
		# 点击“商品评价”
		try:
			element_to_click_1 = self.__page.wait_for_selector('li[data-tab="trigger"][data-anchor="#comment"]', timeout=2000)
			element_to_click_1.click()
		except PlaywrightTimeoutError:
			self.__requires_TuringVerification()

		try:
			if self.__page.wait_for_selector('img[alt="展示图片"]', timeout=2000):
				LOG.info("检测到展示图片，开始滚动加载")
				# 滚动到底部触发加载
				self.__page.evaluate("""
					window.scrollTo({
						top: document.documentElement.scrollHeight,
						behavior: 'smooth'
					});
				""")
				self.__page.wait_for_timeout(timeout=2000)  # 等待内容加载
				# 获取新的页面高度后滚动到30%位置
				new_height = self.__page.evaluate('document.documentElement.scrollHeight')
				self.__page.evaluate(f"""
					window.scrollTo({{
						top: {new_height * 0.3},
						behavior: 'smooth'
					}});
				""")
				self.__page.wait_for_timeout(timeout=1000)
		except PlaywrightTimeoutError:
			LOG.debug("未检测到展示图片，继续执行")
			self.__requires_TuringVerification()

		try:
			if self.CLOSE_SELECT_CURRENT_PRODUCT is False:
				# 点击“只看当前商品”
				element_to_click_2 = self.__page.wait_for_selector('#comm-curr-sku', timeout=2000)
				element_to_click_2.click()
		except PlaywrightTimeoutError:
			self.__requires_TuringVerification()

		image_url_lists: list[list] = []
		previous_image_url = ''

		for page in range(1, 4):
			LOG.trace(f'Turn to page {page}')
			self.__page.wait_for_timeout(timeout=4000) # QwQ适当停顿避免触发反爬验证, 同时等待资源加载完毕
			# 评价主体组件
			comment_item_elements = self.__page.locator('.comment-item').element_handles()
			for comment_item_element in comment_item_elements:
				image_url_list = []
				# 图片预览组件(小图)
				thumb_img_elements = comment_item_element.query_selector_all('.J-thumb-img')
				for thumb_img_element in thumb_img_elements:
					# LOG.debug(f'Visible: {thumb_img_element.is_visible()}')
					thumb_img_element.click() # 模拟点击后会出现更大的图片预览组件
					self.__page.wait_for_timeout(timeout=200)
					# 图片预览组件(大图)
					pic_view_elements = comment_item_element.query_selector_all('xpath=//div[@class="pic-view J-pic-view"]/img')
					if pic_view_elements: # 起始预览组件为非image组件会导致pic_view_elements为空
						pic_view_element = pic_view_elements[-1] # 该组件出现后不会消失，故每次点击后均选取最新的组件
						image_url = 'https:' + pic_view_element.get_attribute('src')
						if image_url and image_url != previous_image_url: #评论的视频文件也会出现在预览位置，但是预览组件类型不是img；在该策略中(每次点击后均选取最新的组件)出现非img组件会导致前一个img组件的src重复获取，故进行url的重复检测。
							image_url_list.append(image_url)
							previous_image_url = image_url
				image_url_lists.append(image_url_list)

			# 翻页
			try:
				pager_next_element = self.__page.wait_for_selector('.ui-pager-next', timeout=2000)
				pager_next_element.click()
			except PlaywrightTimeoutError:
				LOG.info('已到最后一页，抓取页数小于设定数！')
				break
		return self.download_image_group(self.get_random_image_group(image_url_lists))

	def __get_image_infinite_scroll_version(self) -> list:
		"""
		获取已有的评价图片(部分)，筛选(随机取一组)后以订单编号为命名依据，并储存到本地。无限滚动版

		Returns:
			image_files_path(list): 储存到本地的(image目录下)隶属一个订单编号下的所有图片文件路径。
		"""
		# 点击 “全部评价”
		# [FIX 2026-09-22 WorkBuddy] 同 __get_text_infinite_scroll_version：
		# 原 2000ms 超时 + 未滚入视口即点击，必然失败。
		try:
			all_btn_element = self.__page.wait_for_selector('.all-btn', timeout=15000)
			all_btn_element.scroll_into_view_if_needed()
			# [FIX 2026-09-22] 这里是重新 goto 商品页后的第一次点击，页面刚加载完，
			# 停留时间需要比文案版更长（800ms → 3000ms），否则点击会被吞掉。
			self.__page.wait_for_timeout(timeout=3000)
			all_btn_element.click()
			# [FIX 2026-09-22 WorkBuddy] 同文案版：等虚拟列表容器挂载 + 区分「点击被吞」与「风控」
			self.__page.wait_for_timeout(timeout=3000)
			opened = False
			for _try in range(2):
				try:
					self.__page.wait_for_selector('div[data-testid="virtuoso-item-list"]', timeout=15000)
					opened = True
					break
				except PlaywrightTimeoutError:
					if self.__page.locator('#rateList').count() > 0:
						LOG.critical("评价弹层已打开但一条数据都没有 —— 疑似被风控，停手等几小时")
						break
					LOG.warning(f"第 {_try + 1} 次点击未生效，重试点击『全部评价』")
					try:
						all_btn_element.scroll_into_view_if_needed()
						self.__page.wait_for_timeout(timeout=600)
						all_btn_element.click()
						self.__page.wait_for_timeout(timeout=2500)
					except Exception:
						pass
			if opened:
				self.__page.wait_for_timeout(timeout=2000)
			else:
				LOG.critical("'全部评价'点击失败!")
				self.__requires_TuringVerification()
		except PlaywrightTimeoutError:
			LOG.critical("'全部评价'点击失败!")
			self.__requires_TuringVerification()

		# [FIX 2026-09-22 WorkBuddy] 同 text 版：此处选择器写成 `.all-btn` 是复制笔误，
		# 会把刚展开的评价弹层再点一次。停用。
		# try:
		# 	if self.CLOSE_SELECT_CURRENT_PRODUCT is False:
		# 		current_radio_element = self.__page.wait_for_selector('#comm-curr-sku', timeout=3000)
		# 		current_radio_element.click()
		# 	self.__page.wait_for_timeout(timeout=1000) # 等待动态加载
		# except PlaywrightTimeoutError:
		# 	self.__requires_TuringVerification()

		# 包含评价内容的 div 在滚动时动态刷新，且每次刷新数量较少，可看做逐个刷新；每次获取一个评论元素
		image_url_group: list[list] = []
		max_scrolls = 100  # 预设滚动次数，等价于抓取的评论元素个数
		miss = 0
		for item_index in range(max_scrolls): # data-item-index 从 0 开始
			# [FIX 2026-09-22 WorkBuddy] 同 text 版：原单次 2000ms 超时即 break，
			# 把“加载慢”误报成“相关商品没有评价”。改为重试 + 滚动催促。
			item = None
			for attempt in range(3):
				try:
					# [FIX 2026-09-22 WorkBuddy] 同文案版，校准为 6000ms + 重试 + 滚轮催促
					item = self.__page.wait_for_selector(f'div[data-testid="virtuoso-item-list"] > div[data-item-index="{item_index}"]', state="visible", timeout=6000)
					break
				except PlaywrightTimeoutError:
					self.__page.mouse.wheel(0, 900)
					self.__page.wait_for_timeout(timeout=800)
			if item is None:
				miss += 1
				if miss >= 4:
					LOG.info(f"连续 4 个索引取不到，判定已到末尾（本次已收集图片组 {len(image_url_group)} 组）")
					break
				continue
			miss = 0
			if item_index % 5 == 0:
				LOG.info(f"图片抓取进度: 索引 {item_index}, 已收集图片组 {len(image_url_group)} 组")
			# 向下滚动，将元素平滑滚动到视图中；对 item 元素进行滚动时需要其可见
			try:
				self.__page.evaluate("element => element.scrollIntoView({behavior: 'smooth', block: 'center'})", item)
			except Exception:
				pass
			# [ADD 2026-09-22 WorkBuddy] 风控规避：加点「人的节奏」。
			# 实测教训——固定节拍的机械操作是触发京东评价区风控的主因。
			self.__page.wait_for_timeout(timeout=random.randint(300, 1100))
			# 获取图片 url
			image_url_list = []
			image_items = item.query_selector_all('.jd-content-pc-media-list-item') # 一个评论内的全部图片元素，视频与图片都需要点击此元素打开预览元素。其子元素当出现视频时不可点击
			if image_items:
				self.__page.wait_for_timeout(timeout=200) # 等待滚动完成；由于使用的 JS 滚动操作时异步的，不能单使用 playwright 判断元素是否稳定来确定滚动是否完成；仅为了视觉效果，不影响下面的内容获取
				item.wait_for_element_state(state="stable", timeout=2000) # 有图片元素，需等待页面元素稳定
				for image_item in image_items:
					# [ADD 2026-09-22 WorkBuddy] 逐张开预览是最像脚本的动作，插入随机停顿
					self.__page.wait_for_timeout(timeout=random.randint(400, 1500))
					image_item.click() # 点击后会出现更大的图片预览元素
					try:
						preview_image_element = self.__page.wait_for_selector('.jdc-pc-media-preview-image', state="visible", timeout=2000) # 等待预览图可见
						if preview_image_element:
							style = self.__page.evaluate("element => element.getAttribute('style')", preview_image_element)
							# 使用正则表达式提取图片 URL
							url_match = re.search(r'https://img[^"\']+\.jpg', style)
							if url_match:
								url = url_match.group(0)
								image_url_list.append(url)
							else:
								LOG.debug("未获取到图片url")
					except PlaywrightTimeoutError:
						# 由于评价视频与图片混放，有的 image_item 点击后是出现视频预览元素，所以在此忽略掉
						pass
					except Exception as err:
						LOG.debug(f"{err}")
					# 关闭预览图
					try:
						preview_close_element = self.__page.wait_for_selector('.jdc-pc-media-preview-close', timeout=2000)
						preview_close_element.click()
						# [ADD 2026-09-22 WorkBuddy] 关上预览再喘一口，别连点
						self.__page.wait_for_timeout(timeout=random.randint(300, 900))
					except PlaywrightTimeoutError as err:
						LOG.error("预览图关闭失败！")
						self.__requires_TuringVerification()
			if image_url_list:
				image_url_group.append(image_url_list)
			# [FIX 2026-09-22 WorkBuddy] 原为 max(20, MIN_EXISTING_PRODUCT_IMAGES)，
			# 导致 -mi 参数在最常见区间（<20）完全无效，抓图阶段被迫至少跑满 20 组。
			# 改为直接尊重 -mi：想快就调小，想图多就调大。默认 15 与原版接近。
			if len(image_url_group) >= self.MIN_EXISTING_PRODUCT_IMAGES: # 评论图片充足，仅取部分; 最差情况，每组一张图也可满足 MIN_EXISTING_PRODUCT_IMAGES
				break
		LOG.info(f"图片抓取结束，共收集 {len(image_url_group)} 组、"
				 f"{sum(len(g) for g in image_url_group)} 张图")
		return self.download_image_group(self.get_random_image_group(image_url_group))

	def __automatic_evaluate(self, task: EvaluationTask):
		"""自动评价操作，限单个评价页面"""
		try:
			self.__load_page(task.orderVoucher_url, timeout=30000) # 进入评价页面
		except PlaywrightTimeoutError:
			raise NetworkError(message=f"页面加载超时：{task.orderVoucher_url}")

		# 商品评价文本
		# [FIX 2026-09-22 WorkBuddy] 原用绝对 XPath
		# `/html/body/div[4]/div/div/div[2]/div[1]/div[7]/div[2]/div[2]/div[2]/div[1]/textarea`，
		# 页面结构一动就废；且 3000ms 超时对首屏渲染太短（9-15 日志多次报此错）。
		# 实测评价页共有 4 个 textarea：第 1 个 placeholder 为「完善服务…」（服务评价），
		# 其余是各商品的评价框，统一被 `.f-textarea` 包裹。改为相对选择器 + 跳过服务框 +
		# 跳过已有内容的框（保证多商品订单逐个填、不重复评同一个）。
		try:
			self.__page.wait_for_timeout(timeout=3000)  # 等首屏渲染
			boxes = self.__page.locator('.f-textarea textarea')
			count = boxes.count()
			if count == 0:
				boxes = self.__page.locator('textarea')
				count = boxes.count()
			LOG.debug(f"评价页 textarea 数量: {count}")
			filled = False
			for i in range(count):
				box = boxes.nth(i)
				try:
					ph = box.get_attribute('placeholder') or ''
					if '服务' in ph:
						continue  # 服务评价框，不填
					if not box.is_visible():
						continue
					if (box.input_value() or '').strip():
						continue  # 已有内容（已评价），跳过
					box.click()
					box.fill(task.input_text)
					filled = True
					break
				except Exception as err:
					LOG.debug(f"第 {i} 个输入框填充失败: {err}")
			if not filled:
				raise PlaywrightTimeoutError(message="未找到可填写的商品评价输入框")
		except PlaywrightTimeoutError:
			LOG.error("超时，未识别到评价文本输入框！")
			return False

		# 星级评分
		try:
			commstar_elements =  self.__page.locator('.commstar').element_handles()
			star5_elements = [el for el in commstar_elements if el.get_attribute("class") == "commstar"] # 筛选出类名完全匹配 'commstar' 的元素
			for star5_element in star5_elements:
				# 获取元素的大小和位置
				bounding_box = star5_element.bounding_box()
				if bounding_box:
					x = bounding_box['x']
					y = bounding_box['y']
					width = bounding_box['width']
					height = bounding_box['height']

					# 计算相对位置（第五颗星）
					x_offset = x + int(width / 5 * 4) + int(width / 5 * 1) / 2   # 星条元素第五颗星 X 坐标中值
					y_offset = y + (height / 2)  # 星条元素 Y 坐标中值

					# 模拟点击
					self.__page.mouse.move(x_offset, y_offset)
					self.__page.mouse.click(x_offset, y_offset)
			LOG.info(f'单号{task.order_id}识别到{len(star5_elements)}个星级评分组件, 全部给予五星好评。')
		except Exception as err:
			LOG.error("未识别到星级评分组件！")


		try:
			# [FIX 2026-09-22] 2000ms → 15000ms
			file_input_element = self.__page.wait_for_selector('xpath=//input[@type="file"]', timeout=15000) # 查找隐藏的文件上传输入框
			# 商品评价图片
			if file_input_element and not task.input_image and self.GUARANTEE_COMMIT is False:
				LOG.warning(f'单号{task.order_id}的订单未上传评价图片，跳过该任务。')
				return False
			# 发送文件路径到文件上传输入框
			for path in task.input_image:
				file_input_element.set_input_files(path)

		except Exception as err:
			LOG.error("未识别到评价图片路径输入框！")

		LOG.success(f'单号{task.order_id}的订单评价页面填充完成。')
		# 提交评价
		self.__page.wait_for_timeout(timeout=max(5, len(task.input_image) * 2.5) * 1000) # 等待图片上传完成
		try:
			# [FIX 2026-09-22] 2000ms → 15000ms
			btn_submit = self.__page.wait_for_selector('.btn-submit', timeout=15000)
			btn_submit.hover()
			if self.CLOSE_AUTO_COMMIT is False:
				btn_submit.click()
			self.__page.wait_for_timeout(timeout=5000) # 切换下一个评价任务的间隔
			return True
		except Exception as err:
			LOG.error("未识别到提交按钮！")

	def __init_image_directory(self, directory_path):
		# 确保目标路径存在
		if not os.path.exists(directory_path):
			os.makedirs(directory_path)
			return
		# 确保目标是路径指向目录
		if not os.path.isdir(directory_path):
			return
		# 清空目录文件
		for filename in os.listdir(directory_path):
			file_path = os.path.join(directory_path, filename)
			if os.path.isfile(file_path):
				try:
					os.remove(file_path)
				except Exception as e:
					LOG.error(f"Error deleting {file_path}: {e}")

	def __requires_TuringVerification(self) -> bool:
		"""判断是否进入图灵验证界面"""
		# 该方法是通过 timeout 异常调用的，也就是说在自动化流程中出现了元素获取失败的情况，即使在此刻通过了人机验证，也无法回到上一步（获取元素）
		# 1. 所有等待元素的方法都进行retry 2.跳过当前任务，继续往下进行（不适用于连续多个任务都出现人机验证的情况）
		try:
			# 一般来说，进入测试页面时 page 还在等待其他元素，故 timeout 不宜过大，进而确保整体性能。
			if self.__page.wait_for_selector('.verifyBtn', timeout=1500):
				match self.DEAL_TURING_VERIFICATION:
					case 0:
						raise TuringVerificationRequiredError(message="当前设置--自动退出")
					case 1:
						self.__handle_TuringVerification()
					case _ as e:
						LOG.error(f"DEAL_TURING_VERIFICATION 参数所选值 {e} 非法！")
		except PlaywrightTimeoutError:
			pass
		return False

	def __handle_TuringVerification(self) -> bool:
		"""
		进行图灵测试

		Returns:
			图灵测试是否通过(bool):
		"""
		turing_url = self.__page.url
		LOG.debug(f"{turing_url}")
		LOG.info("等待手动人机验证......")
		while True:
			# 检测是否通过验证：1.是否还在验证页面 2.根据验证页面的 url 参数 returnurl 可以获取测试成功后的跳转页面
			# 但是不同类型的的商品最终重定向的页面 url 与 returnurl 不完全匹配，如京东国际等
			try:
				# 持续检测页面 url，一经变动立刻抛出异常
				self.__page.wait_for_url(turing_url, timeout=0.1) # 为了 url 检测的灵敏度更高，超时时长应设置的尽可能小
				self.__page.wait_for_timeout(timeout=200) # url 保持在测试时页面会快速的循环，考虑到性能方面建议阻塞
			except PlaywrightTimeoutError:
				# 暂认为，离开验证页面即为验证通过
				LOG.success("人机验证已通过")
				return True

	@sync_retry(max_retries=3, retry_delay=2, exceptions=(PlaywrightTimeoutError,))
	def __load_page(self, url: str, timeout: float):
		return self.__page.goto(url, timeout=timeout)


class ShowSupportedTableAction(argparse.Action):
	"""自定义命令行参数动作，用于显示支持的AI组和模型"""

	def __init__(self, option_strings, dest, **kwargs):
		super().__init__(option_strings, dest, nargs=0, **kwargs)

	def __call__(self, parser, namespace, values, option_string=None):
		import sys
		# 表格整体缩进两个Tab
		table = """
									Currently supported
		+========================+======================+=======================+
		| Group                  | Model                | Required env variables|
		+========================+======================+=======================+
		| None(default)          | None(default)        | None                  |
		+------------------------+----------------------+-----------------------+			
		| XAI                    | grok-beta            | XAI_API_KEY           |
		|                        | grok-vision-beta     |                       |
		|                        | grok-2-vision-1212   |                       |
		|                        | grok-2-1212     (Rec)|                       |
		+------------------------+----------------------+-----------------------+
		| SparkAI                | Lite            (Rec)| SparkAI_WS_APP_ID     |
		|                        | Pro                  | SparkAI_WS_API_Secret |
		|                        | Pro-128K             | SparkAI_WS_API_KEY    |
		|                        | Max                  |                       |
		|                        | Max-32K              |                       |
		|                        | 4.0-Ultra            |                       |
		+------------------------+----------------------+-----------------------+
"""
		print(table)
		sys.exit(0)  # 显示后退出程序
