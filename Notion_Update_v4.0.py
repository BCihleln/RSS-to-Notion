# coding=utf-8

import os
from Util.FeedTool import NotionAPI, parse_rss_entries
import requests


# 从环境变量中获取Notion API信息
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_READING_DATABASE_ID = os.getenv('NOTION_READING_DATABASE_ID')
NOTION_URL_DATABASE_ID = os.getenv('NOTION_URL_DATABASE_ID')

def update():

	if NOTION_API_KEY is None:
		print("NOTION_API_KEY secrets not set!")
		return

	api = NotionAPI(NOTION_API_KEY, NOTION_READING_DATABASE_ID, NOTION_URL_DATABASE_ID)

	rss_feed_list = api.queryFeed_from_notion()

	for rss_feed in rss_feed_list:
		feed, entries = parse_rss_entries(rss_feed.get("url"))
		rss_page_id = rss_feed.get("page_id")
		rss_feed_name = feed.get("title")
		if len(entries) == 0:
			api.updateFeedInfo_to_notion(feed, page_id=rss_page_id)
			continue
		
		# Check for Repeat Entries
		url=f"{api.NOTION_API_database}/{api.reader_id}/query"
		payload = {
			"filter": {
				"property": "Source",
				"relation": {"contains": rss_page_id},
			},
		}
		response = requests.post(url=url, headers=api.headers, json=payload)

		current_urls = [x.get("properties").get("URL").get("url") for x in response.json().get("results")]
		repeat_count = 0

		api.updateFeedInfo_to_notion(feed, page_id=rss_page_id)
		for entry in entries:
			if entry.get("link") not in current_urls:
				api.saveEntry_to_notion(entry, rss_page_id)
				current_urls += [entry.get("link")]
			else:
				repeat_count += 1
		
		repeat_count_msg = ""
		if repeat_count>0: repeat_count_msg = f"，重複 {repeat_count} 篇"
		print(f"訊息源 {rss_feed_name} 读取到 {len(entries)} 篇内容{repeat_count_msg}。")


if __name__ == "__main__":
	update()