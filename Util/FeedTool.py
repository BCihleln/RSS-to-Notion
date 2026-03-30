import feedparser
from bs4 import BeautifulSoup

import re
import json
import requests
from datetime import datetime, timezone, timedelta
from dateutil import parser
import time

now = datetime.now(timezone.utc)
load_time = 1  # 导入1天内的文章
max_post_count = 10 # 導入文章的最大數量


def parse_publish_time(date_str):
	"""
	尝试多种格式解析发布时间
	1. 先用 dateutil.parser.parse() 尝试
	2. 如果失败，用正则表达式提取 JS 日期格式并用 strptime 解析
	3. 如果都失败，返回当前时间
	
	Args:
		date_str: 日期字符串
	
	Returns:
		datetime 对象with UTC timezone
	"""
	if not date_str:
		return now
	
	# 方法1: 尝试 dateutil.parser.parse()
	try:
		published_time = parser.parse(date_str)
		return published_time
	except (ValueError, TypeError, AttributeError):
		pass
	
	# 方法2: 尝试用正则表达式提取 JS 日期格式
	# 匹配格式如: "Fri Mar 27 2026 00:00:00" 或 "Fri Mar 27 2026 00:00:00 GMT+0000 ..."
	js_date_pattern = r'(\w+\s+\w+\s+\d+\s+\d+\s+\d+:\d+:\d+)'
	match = re.search(js_date_pattern, str(date_str))
	if match:
		try:
			date_part = match.group(1)
			published_time = datetime.strptime(date_part, "%a %b %d %Y %H:%M:%S")
			# 添加 UTC 时区
			published_time = published_time.replace(tzinfo=timezone.utc)
			return published_time
		except (ValueError, TypeError):
			pass
	
	# 方法3: fallback 到当前时间
	print(f"Warning: Failed to parse publish time '{date_str}', using current time")
	return now


def parse_rss_entries(url, retries=3):
	feed = []
	entries = []

	# DEBUG
	print(f"Processing : {url}")

	for attempt in range(retries):
		try:
			response = requests.get(
				url=url,
				headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.55 Safari/537.36 Edg/96.0.1054.34"},
			)
			error_code = 0
		except (requests.exceptions.RequestException, Exception) as e:
			print(f"Load {url} Error, Attempt {attempt + 1} failed: {type(e).__name__}: {e}")
			time.sleep(1)  # 等待1秒后重试
			error_code = 1

		if error_code == 0:
			parsed_feed = feedparser.parse(response.content)
			soup = BeautifulSoup(response.content, 'xml')

			## Update RSS Feed Status
			feed_title = soup.find('title').text if soup.find('title') else 'No title available'
			feed = {
				"title": feed_title,
				"link": url,
				"status": "Active"
			}

			for entry in parsed_feed.entries:

				# Get publish date
				published_time = parse_publish_time(entry.get("published"))
				if not published_time.tzinfo:
					published_time = published_time.replace(tzinfo=timezone(timedelta(hours=8)))


				if now - published_time < timedelta(days=load_time):
					cover = BeautifulSoup(entry.get("summary"),'html.parser')
					cover_list = cover.find_all('img')
					src = "https://www.notion.so/images/page-cover/rijksmuseum_avercamp_1620.jpg" if not cover_list else cover_list[0]['src']
					# Use re.search to find the first match
					entries.append(
						{
							"title": entry.get("title"),
							"link": entry.get("link"),
							"time": published_time.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S%z"),
							"summary": re.sub(r"<.*?>|\n*", "", entry.get("summary"))[:2000],
							"content": entry.get("content"),
							"cover": src
						}
				)

			return feed, entries[:max_post_count]
			# return feed, entries[:3]
		
	feed = {
		"title": "Unknown",
		"link": url,
		"status": "Error"
	}

		
	return feed, entries


class NotionAPI:
	NOTION_API_pages = "https://api.notion.com/v1/pages"
	NOTION_API_database = "https://api.notion.com/v1/databases"


	def __init__(self, secret, read, feed) -> None:
		self.reader_id = read
		self.feeds_id = feed
		self.headers = {
			"Authorization": f"Bearer {secret}",
			"Notion-Version": "2022-06-28",
			"Content-Type": "application/json",
		}
		# self.delete_rss()

	def queryFeed_from_notion(self):
		"""
		从URL Database里读取url和page_id

		return:
		dict with "url" and "page_id"
		"""
		rss_feed_list = []
		url=f"{self.NOTION_API_database}/{self.feeds_id}/query"
		payload = {
			"page_size": 100,
			"filter": {
				"property": "Disabled",
				"checkbox": {"equals": False},
			}
		}
		response = requests.post(url, headers=self.headers, json=payload)

		# Check Status
		if response.status_code != 200:
			raise Exception(f"Failed to query Notion database: {response.text}")
		
		# Grab requests
		data = response.json()

		# DEBUG: Dump the requested JSON file for test
		# with open('db.json', 'w', encoding='utf8') as f:
		# 	json.dump(data, f, ensure_ascii=False, indent=4)

		rss_feed_list = []
		for page in data['results']:
			props = page["properties"]
			rss_feed_list.append(
				{
					"url": props["URL"]["url"],
					"page_id": page.get("id")
				}
			)

		return rss_feed_list

	def saveEntry_to_notion(self, entry, page_id):
		"""
		Save entry lists into reading database

		params: entry("title", "link", "time", "summary"), page_id

		return:
		api response from notion
		"""
		# print(entry.get("cover"))
		# Construct post request to reading database
		payload = {
			"parent": {"database_id": self.reader_id},
			"cover": {
				"type": "external",
				"external": {"url": entry.get("cover")}
			},
			"properties": {
				"Name": {
					"title": [
						{
							"type": "text",
							"text": {"content": entry.get("title")},
						}
					]
				},
				"URL": {"url": entry.get("link")},
				"Published": {"date": {"start": entry.get("time")}},
				"Source":{
					"relation": [{"id": page_id}]
				}
			},
			"children": [
				{
					"type": "paragraph",
					"paragraph": {
						"rich_text": [
							{
								"type": "text",
								"text": {"content": entry.get("summary")},
							}
						]
					},
				}
			],
		}
		response = requests.post(url=self.NOTION_API_pages, headers=self.headers, json=payload)

		# DEBUG: print Notion API responce status
		# print(response.status_code)
		return response
	
	def updateFeedInfo_to_notion(self, prop, page_id):
		"""
		Update feed info into URL database

		params: prop("title", "status"), page_id

		return:
		api response from notion
		"""

		# Update to Notion
		url = f"{self.NOTION_API_pages}/{page_id}"
		payload = {
			"parent": {"database_id": self.feeds_id},
			"properties": {
				"Status":{
					"select":{
						"name": prop.get("status"),
						"color": "red" if prop.get("status") == "Error" else "green"
					}
					
				}
			},
		}

		response = requests.patch(url=url, headers=self.headers, json=payload)
		# DEBUG
		# print(response.status_code)
		return response

	## Todo: figure out deleting process
	# def delete_rss(self):
	# 	filter_json = {
	# 		"filter": {
	# 			"and": [
	# 				{
	# 					"property": "Check",
	# 					"checkbox": {"equals": True},
	# 				},
	# 				{
	# 					"property": "Published",
	# 					"date": {"before": delete_time.strftime("%Y-%m-%dT%H:%M:%S%z")},
	# 				},
	# 			]
	# 		}
	# 	}
	# 	results = requests.request("POST", url=f"{self.NOTION_API_database}/{self.reader_id}/query", headers=self.headers, json=filter_json).json().get("results")
	# 	responses = []
	# 	if len(results) != 0:
	# 		for result in results:
	# 			url = f"https://api.notion.com/v1/blocks/{result.get('id')}"
	# 			responses += [requests.delete(url, headers=self.headers)]
	# 	return responses
	
