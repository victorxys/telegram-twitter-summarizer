import logging
import os
import re
from dotenv import load_dotenv
import google.generativeai as genai
from telegram import Update, MessageEntity
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import tweepy

# --- 配置 ---
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# TARGET_CHAT_ID 不再需要

# 配置日志记录
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("tweepy").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 配置 Gemini API
gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # 使用 gemini-1.0-pro 或 gemini-1.5-flash-latest
        gemini_model = genai.GenerativeModel('gemini-2.5-flash-preview-04-17')
        logger.info("Gemini API 配置成功。")
    except Exception as e:
        logger.error(f"配置 Gemini API 失败: {e}")
else:
    logger.warning("GEMINI_API_KEY 未设置，总结和标签生成功能将不可用。")


# --- Twitter 内容抓取函数 (使用 Tweepy - 保持不变) ---
def get_tweet_data(tweet_url: str) -> dict | None:
    logger.info(f"尝试通过 Twitter API v2 获取推文数据: {tweet_url}")
    if not TWITTER_BEARER_TOKEN:
        logger.error("TWITTER_BEARER_TOKEN 未设置。")
        return None
    match = re.search(r'/status/(\d+)', tweet_url)
    if not match:
        logger.error(f"无法从 URL 中解析 Tweet ID: {tweet_url}")
        return None
    tweet_id = match.group(1)
    logger.info(f"解析得到 Tweet ID: {tweet_id}")
    try:
        client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN, wait_on_rate_limit=True)
        response = client.get_tweet(
            id=tweet_id,
            expansions=['attachments.media_keys'],
            media_fields=['url', 'preview_image_url', 'type', 'variants'],
            tweet_fields=['created_at', 'text']
        )
        if response.errors:
            logger.error(f"Twitter API v2 错误 for {tweet_id}: {response.errors}")
            return None
        if not response.data:
            logger.warning(f"Twitter API v2 未找到推文 {tweet_id} 数据。")
            return None

        tweet = response.data
        tweet_text = tweet.text
        has_image = False
        has_video = False
        image_urls = []
        video_urls = []
        media_lookup = {}
        if response.includes and 'media' in response.includes:
            media_lookup = {m.media_key: m for m in response.includes['media']}
        if tweet.attachments and 'media_keys' in tweet.attachments:
            for media_key in tweet.attachments['media_keys']:
                media = media_lookup.get(media_key)
                if media:
                    if media.type == 'photo':
                        has_image = True
                        if media.url: image_urls.append(media.url)
                    elif media.type in ['video', 'animated_gif']:
                        has_video = True
                        best_variant_url = None
                        if media.variants:
                            for variant in media.variants:
                                if variant.get('content_type') == 'video/mp4':
                                    best_variant_url = variant.get('url')
                                    break
                        if best_variant_url: video_urls.append(best_variant_url)

        logger.info(f"通过 Twitter API v2 获取成功: Text='{tweet_text[:50]}...', Images={has_image}, Videos={has_video}")
        return {
            "text": tweet_text, "has_image": has_image, "has_video": has_video,
            "image_urls": image_urls, "video_urls": video_urls
        }
    except tweepy.errors.NotFound:
        logger.warning(f"推文 {tweet_id} 未找到 (NotFound)。")
        return None
    except tweepy.errors.Forbidden:
        logger.error(f"无权访问推文 {tweet_id} (Forbidden)。")
        return None
    except tweepy.errors.Unauthorized:
         logger.error(f"Twitter API 认证失败 (Unauthorized)。检查 Bearer Token。")
         return None
    except tweepy.errors.TweepyException as e:
        logger.error(f"获取推文 {tweet_id} 时发生 Tweepy 错误: {e}", exc_info=False) # 简化日志
        return None
    except Exception as e:
        logger.error(f"获取推文 {tweet_id} 时发生未知错误: {e}", exc_info=True)
        return None

# --- 重构：Gemini 总结与标签生成函数 ---
def get_summary_and_tags(text: str, has_image: bool, has_video: bool) -> tuple[str | None, list[str] | None]:
    """
    使用 Gemini API 总结推文内容并生成相关标签。
    返回 (summary, tags_list) 元组，失败则返回 (None, None)。
    """
    if not gemini_model:
        logger.error("Gemini 模型未初始化，无法进行总结和标签生成。")
        return None, None
    if not text and not has_image and not has_video:
        logger.info("推文内容为空，不进行总结和标签生成。")
        return "这条推文似乎没有可总结的内容。", [] # 返回空内容和空标签列表

    # -- 构建新的 Prompt --
    prompt_parts = ["根据以下推文内容："]
    if text:
        max_text_length = 3000 # 限制输入长度
        prompt_parts.append(f"\n文字内容 (可能被截断):\n{text[:max_text_length]}")
    if has_image:
        prompt_parts.append("\n(推文包含图片)")
    if has_video:
        prompt_parts.append("\n(推文包含视频)")

    prompt_parts.append("\n\n请执行以下操作：")
    prompt_parts.append("1. 生成一段简洁的中文总结。")
    prompt_parts.append("2. 提取或生成 3-5 个最相关的中文或英文标签 (Hashtags)，必须以 '#' 开头，并用空格分隔。")
    prompt_parts.append("\n请严格按照以下格式返回结果，不要添加任何额外的解释或说明文字：")
    prompt_parts.append("Summary:\n[这里是总结内容]\n\nTags:\n[#标签1 #标签2 #标签3 ...]") # <--- 指定输出格式

    prompt = "\n".join(prompt_parts)

    logger.info("向 Gemini 发送请求进行总结和标签生成...")
    try:
        response = gemini_model.generate_content(prompt)

        # -- 解析 Gemini 返回的文本 --
        if response and hasattr(response, 'text'):
            response_text = response.text
            logger.info("Gemini 处理完成。")
            logger.debug(f"Gemini 原始返回: {response_text}") # 打印原始返回，方便调试

            summary = None
            tags_list = []

            # 尝试根据我们指定的格式解析
            summary_match = re.search(r"Summary:\s*(.*?)\s*\n\nTags:", response_text, re.DOTALL | re.IGNORECASE)
            tags_match = re.search(r"\n\nTags:\s*(.*)", response_text, re.IGNORECASE)

            if summary_match:
                summary = summary_match.group(1).strip()
            else:
                # 如果严格格式匹配失败，尝试把 "Tags:" 之前的内容都当作 Summary (备用方案)
                parts = re.split(r'\n\nTags:', response_text, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) > 0:
                     summary = parts[0].replace("Summary:", "").strip() # 移除可能的"Summary:"前缀
                logger.warning("未能按预期格式解析 Summary，尝试使用备用方法。")

            if tags_match:
                tags_string = tags_match.group(1).strip()
                # 提取所有 # 开头的标签
                tags_list = [tag for tag in tags_string.split() if tag.startswith('#')]
            else:
                 logger.warning("未能按预期格式解析 Tags。")

            # 如果完全解析失败，可以返回原始文本作为 summary
            if summary is None and not tags_list:
                 summary = response_text.strip()
                 logger.warning("无法解析总结和标签，将返回原始 Gemini 文本。")

            return summary if summary else "无法提取总结。", tags_list # 确保 summary 不是 None

        elif response and response.prompt_feedback.block_reason:
             block_reason = response.prompt_feedback.block_reason
             logger.warning(f"Gemini 请求被阻止，原因: {block_reason}")
             return f"无法生成总结和标签，内容可能违反安全策略 ({block_reason})。", None
        else:
             logger.error(f"Gemini API 返回了意外的响应: {response}")
             return "无法生成总结和标签：收到意外的响应。", None

    except Exception as e:
        logger.error(f"调用 Gemini API 或解析结果时出错: {e}", exc_info=True)
        return f"无法生成总结和标签：调用 API 时出错 ({type(e).__name__})。", None

# --- Telegram Bot 处理函数 (修改发送逻辑) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    twitter_links = []
    # ... (链接查找逻辑保持不变) ...
    if message.entities:
        urls_in_entities = message.parse_entities(types=[MessageEntity.URL, MessageEntity.TEXT_LINK])
        for entity, url_text in urls_in_entities.items():
            link_url = url_text if entity.type == MessageEntity.URL else entity.url
            if link_url and ("twitter.com" in link_url or "x.com" in link_url) and "/status/" in link_url:
                 cleaned_url = re.sub(r'\?.*$', '', link_url)
                 if cleaned_url not in twitter_links:
                     twitter_links.append(cleaned_url)
    if not twitter_links:
         potential_links = re.findall(r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[^/]+/status/\d+', message.text)
         for link in potential_links:
             cleaned_url = re.sub(r'\?.*$', '', link)
             if cleaned_url not in twitter_links:
                 twitter_links.append(cleaned_url)
    if not twitter_links:
        return

    tweet_url = twitter_links[0]
    chat_id = update.message.chat_id # <--- 获取当前聊天的 ID
    user_id = update.effective_user.id
    logger.info(f"收到来自用户 {user_id} (聊天 {chat_id}) 的 Twitter 链接: {tweet_url}")

    # 发送处理中消息 (仍然可以回复原消息，让用户知道是针对哪条链接的处理)
    processing_msg = await message.reply_text(f"收到链接，正在处理总结和标签...", reply_to_message_id=message.message_id)

    # 1. 抓取推文内容 (保持不变)
    tweet_data = get_tweet_data(tweet_url)
    if not tweet_data:
        await processing_msg.edit_text(f"抱歉，无法通过 Twitter API 获取此推文的数据：{tweet_url}\n可能是推文不存在/受保护，或 API 访问权限/凭证有问题。")
        return

    # 2. 使用 Gemini 生成总结和标签 (调用新函数)
    summary, tags_list = get_summary_and_tags(
        tweet_data["text"],
        tweet_data["has_image"],
        tweet_data["has_video"]
    )

    # 3. 发送结果到当前聊天
    if summary is not None and tags_list is not None: # 检查两者都不是 None
        # 构建最终消息
        final_message_parts = [summary]
        if tags_list: # 只有当标签列表不为空时才添加
             tags_string = " ".join(tags_list) # 将标签列表转换为空格分隔的字符串
             final_message_parts.append(f"\n\n {tags_string}")
        # final_message_parts.append(f"\n\n---\n🔗 **原始链接:** {tweet_url}") # 添加原始链接
        # if tweet_data["has_image"]:
        #     final_message_parts.append("\n🖼️ (包含图片)")
        # if tweet_data["has_video"]:
        #     final_message_parts.append("\n🎬 (包含视频)")

        final_message = "".join(final_message_parts)

        try:
            # 发送到当前聊天，不作为回复
            await context.bot.send_message(
                chat_id=chat_id, # <--- 使用当前聊天的 ID
                text=final_message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            logger.info(f"总结和标签已成功发送到 Chat ID: {chat_id}")
            # 完成后删除 "处理中" 消息
            await processing_msg.delete()

        except Exception as e:
            logger.error(f"发送消息到 {chat_id} 时出错: {e}", exc_info=True)
            # 如果发送失败，编辑 "处理中" 消息告知用户
            await processing_msg.edit_text(f"抱歉，生成内容后发送到此聊天时遇到错误。")

    else:
        # 如果 get_summary_and_tags 返回 None (表示生成失败)
        await processing_msg.edit_text(f"抱歉，生成总结和标签时遇到问题。请检查日志。")


# --- /start 命令处理 (保持不变) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        rf"你好 {user.mention_html()}！请转发 Twitter/X 链接给我，我会尝试总结它并生成标签发送到这里。",
    )

# --- 主函数 (移除 TARGET_CHAT_ID 检查) ---
def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN 未设置！机器人无法启动。")
        return
    if not TWITTER_BEARER_TOKEN:
        logger.critical("TWITTER_BEARER_TOKEN 未设置！无法连接 Twitter API。")
        # return # 可以选择是否还启动
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY 未设置！总结和标签生成功能将不可用。")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("机器人启动中... (将发送结果到当前聊天)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()