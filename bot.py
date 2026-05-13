# First, load environment variables
from dotenv import load_dotenv
load_dotenv()

# Then, import other modules
import logging
import os
import re
import json
import queue
import threading
import time
import asyncio
import google.generativeai as genai
from telegram import Update, MessageEntity
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
from ntscraper import Nitter

# --- 自定义模块导入 (现在是安全的) ---
import notion_utils

# --- 配置 ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# 已移除过时的 TWITTER_BEARER_TOKEN

# 日志配置
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("tweepy").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- API 和队列初始化 ---

# Gemini API
gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # models/gemini-2.5-flash
        gemini_model = genai.GenerativeModel('gemini-3.1-flash-lite')
        logger.info("Gemini API 配置成功。 ")
    except Exception as e:
        logger.error(f"配置 Gemini API 失败: {e}")
else:
    logger.warning("GEMINI_API_KEY 未设置，总结和标签生成功能将不可用。 ")

# 推文处理队列
tweet_queue = queue.Queue()

# --- Twitter 内容抓取函数 (基本保持不变) ---
# --- Twitter 内容抓取函数 (纯非官方多策略) ---
def get_tweet_data(tweet_url: str) -> dict | None:
    match = re.search(r'/status/(\d+)', tweet_url)
    if not match:
        logger.error(f"无法从 URL 中解析 Tweet ID: {tweet_url}")
        return None
    tweet_id = match.group(1)
    
    # 获取用户名的正则表达式 (备选，部分接口可能需要)
    user_match = re.search(r'(?:twitter\.com|x\.com)/([^/]+)/status/', tweet_url)
    username = user_match.group(1) if user_match else "i"

    # 策略 1: API 阵列 (基于 JSON 的镜像接口)
    # vxtwitter, fxtwitter, fixupx 等
    endpoints = [
        f"https://api.vxtwitter.com/{username}/status/{tweet_id}",
        f"https://api.fxtwitter.com/{username}/status/{tweet_id}"
    ]

    for url in endpoints:
        logger.info(f"尝试通过非官方 API 获取: {url}")
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                try:
                    data = response.json()
                    # 某些接口返回 200 但内容是错误信息
                    if data and (data.get("text") or data.get("description")):
                        content = data.get("text") or data.get("description")
                        logger.info(f"获取成功 (API): {content[:50]}...")
                        return {"text": content, "url": tweet_url}
                except ValueError:
                    logger.warning(f"接口 {url} 返回了非 JSON 内容，跳过。")
            else:
                logger.warning(f"接口 {url} 响应异常: {response.status_code}")
        except Exception as e:
            logger.warning(f"接口 {url} 请求出错: {e}")

    # 策略 2: 使用 ntscraper (抓取 Nitter 镜像)
    logger.info(f"所有 API 接口均失效，尝试使用 ntscraper 抓取...")
    try:
        scraper = Nitter(log_level=1)
        # 尝试从 Nitter 抓取单个推文
        tweet = scraper.get_tweets(username, mode='term', number=1)
        # 注意：ntscraper 获取的是列表，我们需要找到匹配 ID 的那个
        if tweet and 'tweets' in tweet and len(tweet['tweets']) > 0:
            for t in tweet['tweets']:
                # 模糊匹配 ID 或通过内容尝试
                if tweet_id in t.get('link', '') or not tweet_id:
                    logger.info("ntscraper 抓取成功。")
                    return {"text": t.get('text', ''), "url": tweet_url}
    except Exception as e:
        logger.error(f"ntscraper 抓取失败: {e}")

    logger.error(f"所有非官方抓取手段均已失效: {tweet_url}")
    return None

# --- 重构后的 Gemini 总结与标签生成函数 ---
def get_summary_and_tags(text: str, existing_tags: list[str]) -> dict | None:
    if not gemini_model:
        logger.error("Gemini 模型未初始化。 ")
        return None
    if not text:
        logger.info("推文内容为空，不进行总结。 ")
        return None

    prompt = f"""
You are a content analysis and tagging expert.
Here is a list of predefined categories:
{existing_tags}

Here is the content of a tweet:
---
{text}
---

Based on the tweet content, perform the following tasks and provide the output ONLY in a valid JSON format:

1.  **title**: Generate a short, concise title in Chinese for the tweet, under 10 characters.
2.  **summary**: Write a concise, neutral summary of the tweet in Chinese.
3.  **matched_tags**: From the predefined categories list, select up to three (3) of the most relevant tags. The result must be a JSON array of strings. If no tags match, return an empty array.
4.  **ai_suggested_tag**: Generate exactly one new, insightful tag in Chinese or English that best categorizes the tweet, even if it's not in the predefined list. This tag must start with '#'. The result must be a JSON string.

Your response MUST be a single JSON object and nothing else.
"""

    logger.info("向 Gemini 发送请求...")
    try:
        response = gemini_model.generate_content(prompt)
        response_text = response.text
        logger.debug(f"Gemini 原始返回: {response_text}")
        cleaned_json_str = re.sub(r"```json\n|```", "", response_text).strip()
        ai_result = json.loads(cleaned_json_str)
        if all(k in ai_result for k in ["title", "summary", "matched_tags", "ai_suggested_tag"]):
            return ai_result
        else:
            logger.error(f"Gemini 返回的 JSON 结构不完整: {ai_result}")
            return None
    except json.JSONDecodeError:
        logger.error(f"无法解析 Gemini 返回的 JSON: {response_text}")
        return None
    except Exception as e:
        logger.error(f"调用 Gemini API 或解析结果时出错: {e}", exc_info=True)
        return None


# --- 后台工人线程 ---
def worker(application: Application, loop: asyncio.AbstractEventLoop):
    """
    后台工作线程，用于顺序处理队列中的任务。
    """
    logger.info("后台工人线程已启动。 ")

    while True:
        tweet_url, chat_id, status_message_id, original_message_id = tweet_queue.get()
        try:
            logger.info(f"工人: 开始处理来自聊天 {chat_id} 的链接: {tweet_url} (原始消息ID: {original_message_id})")

            # --- 线程安全的 Telegram 通信辅助函数 ---
            def edit_status_message(text: str):
                coro = application.bot.edit_message_text(text, chat_id=chat_id, message_id=status_message_id)
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                try:
                    future.result(timeout=10)
                except Exception as e:
                    logger.error(f"从 worker 线程编辑消息时出错: {e}")

            def delete_message_safely(msg_id: int):
                coro = application.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                try:
                    future.result(timeout=10)
                    logger.info(f"成功删除消息 {msg_id} from chat {chat_id}")
                except Exception as e:
                    logger.error(f"从 worker 线程删除消息 {msg_id} 时出错: {e}")

            # 1. 更新状态为“正在处理”
            edit_status_message(f"⚙️ 正在处理链接...\n{tweet_url}")

            # 2. 抓取推文内容
            tweet_data = get_tweet_data(tweet_url)
            if not tweet_data:
                logger.error(f"工人: 无法获取推文数据: {tweet_url}")
                edit_status_message(f"❌ 处理失败: 无法获取推文数据。\n{tweet_url}")
                continue

            # 3. 从 Notion 获取标签
            existing_tags = notion_utils.get_tags_from_database()
            if not existing_tags:
                logger.warning("工人: 未能从 Notion 获取标签，将使用空列表。")

            # 4. 使用 Gemini 生成总结和标签
            ai_result = get_summary_and_tags(tweet_data["text"], existing_tags)
            if not ai_result:
                logger.error(f"工人: AI 处理失败: {tweet_url}")
                edit_status_message(f"❌ 处理失败: AI 无法总结此内容。\n{tweet_url}")
                continue

            # 5. 将结果存入 Notion
            notion_utils.create_notion_page(
                tweet_data=tweet_data,
                title=ai_result["title"],
                summary=ai_result["summary"],
                matched_tags=ai_result["matched_tags"],
                ai_tag=ai_result["ai_suggested_tag"]
            )

            logger.info(f"工人: 成功处理并存储链接: {tweet_url}")
            edit_status_message(f"✅ 已存入 Notion: {ai_result['title']}\n{tweet_url}")

            # 删除原始消息
            delete_message_safely(original_message_id)
            logger.info(f"工人: 已删除原始消息 {original_message_id}")

        except Exception as e:
            logger.error(f"工人线程发生未知错误: {e}", exc_info=True)
            try:
                edit_status_message(f"❌ 处理时发生未知错误。\n{tweet_url}")
            except Exception as e_inner:
                logger.error(f"发送最终错误通知时再次失败: {e_inner}")
        finally:
            tweet_queue.task_done()
            time.sleep(15)

# --- Telegram Bot 处理函数 ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    urls_in_entities = message.parse_entities(types=[MessageEntity.URL, MessageEntity.TEXT_LINK])
    potential_links = re.findall(r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[^/]+/status/\d+', message.text)
    
    all_links = [entity.url for entity, _ in urls_in_entities.items() if entity.type == MessageEntity.TEXT_LINK]
    all_links.extend([url for _, url in urls_in_entities.items() if _.type == MessageEntity.URL])
    all_links.extend(potential_links)

    twitter_links = []
    for link in all_links:
        if link and ("twitter.com" in link or "x.com" in link) and "/status/" in link:
            cleaned_url = re.sub(r'\?.*', '', link)
            if cleaned_url not in twitter_links:
                twitter_links.append(cleaned_url)

    if not twitter_links:
        return

    # 先发送一条“收到”消息，并获取其 message_id
    reply_text = f"收到 {len(twitter_links)} 条链接，正在排队处理..."
    status_message = await message.reply_text(reply_text, reply_to_message_id=message.message_id)
    status_message_id = status_message.message_id

    # 将任务（包含原始消息ID和状态消息ID）放入队列
    for url in twitter_links:
        tweet_queue.put((url, message.chat_id, status_message_id, message.message_id))
        logger.info(f"链接已加入队列: {url} (来自聊天 {message.chat_id})，原始消息ID: {message.message_id}，状态消息ID: {status_message_id}")


# --- /start 命令处理 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        rf"你好 {user.mention_html()}！请转发 Twitter/X 链接给我，我会自动总结并存入你的 Notion 数据库。",
    )


# --- 主函数 ---
def main() -> None:
    # 检查关键环境变量
    if not all([TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, notion_utils.NOTION_API_KEY, notion_utils.NOTION_DATABASE_ID]):
        logger.critical("一个或多个关键环境变量未设置！请检查 .env 文件。机器人无法启动。 ")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 获取主线程的事件循环并传递给 worker
    loop = asyncio.get_event_loop()
    worker_thread = threading.Thread(target=worker, args=(application, loop), daemon=True)
    worker_thread.start()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("机器人启动中...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
