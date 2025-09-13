import os
import logging
from notion_client import Client

# --- 初始化 ---
logger = logging.getLogger(__name__)

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# 初始化 Notion 同步客户端
notion_client = None
if NOTION_API_KEY and NOTION_DATABASE_ID:
    try:
        notion_client = Client(auth=NOTION_API_KEY)
        logger.info("Notion Client 初始化成功。")
    except Exception as e:
        logger.error(f"初始化 Notion Client 失败: {e}")
else:
    logger.warning("NOTION_API_KEY 或 NOTION_DATABASE_ID 未设置，Notion 功能将不可用。")


def get_tags_from_database() -> list[str]:
    """
    从 Notion 数据库中获取 "Tags" 属性的所有可用选项（即预定义的标签）。
    Returns:
        A list of tag names, or an empty list if fetching fails.
    """
    if not notion_client or not NOTION_DATABASE_ID:
        logger.warning("Notion client 未初始化，无法获取标签。")
        return []
    try:
        logger.info(f"正在从 Notion 数据库 ({NOTION_DATABASE_ID}) 获取属性...")
        db_info = notion_client.databases.retrieve(database_id=NOTION_DATABASE_ID)
        tags_property = db_info.get("properties", {}).get("Tags")

        if not tags_property or tags_property.get("type") != "multi_select":
            logger.warning("数据库中未找到名为 'Tags' 的 'multi_select' 属性。")
            return []

        tag_options = tags_property.get("multi_select", {}).get("options", [])
        tag_names = [option["name"] for option in tag_options]
        logger.info(f"成功获取到 {len(tag_names)} 个预定义标签: {tag_names}")
        return tag_names

    except Exception as e:
        logger.error(f"从 Notion 获取数据库标签时出错: {e}", exc_info=True)
        return []


def create_notion_page(tweet_data: dict, title: str, summary: str, matched_tags: list[str], ai_tag: str):
    """
    在 Notion 数据库中创建一个新页面来存储推文信息。
    """
    if not notion_client or not NOTION_DATABASE_ID:
        logger.error("Notion client 未初始化，无法创建页面。")
        return

    logger.info(f"准备在 Notion 中创建页面，URL: {tweet_data.get('url')}")

    properties = {
        "X Title": {
            "type": "title",
            "title": [{"type": "text", "text": {"content": title or "无标题"}}],
        },
        "X Content": {
            "type": "rich_text",
            "rich_text": [{"type": "text", "text": {"content": tweet_data.get("text", "N/A")}}],
        },
        "URL": {
            "type": "url",
            "url": tweet_data.get("url"),
        },
        "Summary": {
            "type": "rich_text",
            "rich_text": [{"type": "text", "text": {"content": summary}}],
        },
        "AI Tag": {
            "type": "rich_text",
            "rich_text": [{"type": "text", "text": {"content": ai_tag or "N/A"}}],
        },
        "Tags": {
            "type": "multi_select",
            "multi_select": [{"name": tag} for tag in matched_tags],
        },
    }

    try:
        notion_client.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties=properties
        )
        logger.info(f"成功在 Notion 中创建页面，URL: {tweet_data.get('url')}")
    except Exception as e:
        logger.error(f"在 Notion 中创建页面时出错: {e}", exc_info=True)