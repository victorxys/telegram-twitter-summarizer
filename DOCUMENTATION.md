
# Telegram-Twitter-Notion 总结机器人 | 需求与设计文档

**版本:** 1.0
**日期:** 2025-09-13

## 1. 需求文档 (Requirements Document)

本文档从用户和功能角度出发，定义了系统的目标和行为。

### 1.1. 项目目标

构建一个自动化工具，通过 Telegram 机器人接收用户分享的 Twitter/X 链接，利用 AI 对推文进行总结和分类，并最终将结构化数据存入指定的 Notion 数据库中，以方便后续的归档、检索和回顾。

### 1.2. 核心功能 (Features)

*   **F1: 推文提交**
    *   用户可以通过 Telegram 向机器人发送包含一个或多个 Twitter/X 链接 (`twitter.com` 或 `x.com`) 的消息。

*   **F2: 链接处理**
    *   机器人必须能够从单条消息中准确地解析出所有合法的推文链接。
    *   机器人必须能够处理普通链接 (`https://...`) 和文本超链接。

*   **F3: AI 内容处理**
    *   对于每一条推文，系统必须：
        *   **抓取内容:** 获取推文的完整文本。
        *   **生成总结:** 使用 AI 模型（Gemini）生成一段简洁、中立的中文总结。
        *   **智能分类:**
            *   从 Notion 数据库中预设的标签列表里，匹配并选择最多 3 个最相关的标签。
            *   额外生成一个 AI 认为最合适的新标签（可以不在预设列表中），以补充和扩展标签库。

*   **F4: 数据持久化**
    *   所有处理完成的数据必须作为一个新条目（Page）添加到用户指定的 Notion 数据库中。
    *   存储的数据字段应包括：推文原文、原始链接、AI 总结、匹配的标签（`Multi-select`）、AI 建议的标签。

*   **F5: 可靠性与稳定性**
    *   系统必须能可靠地处理每一条提交的链接，即使在短时间内收到大量链接，也不应丢失任何请求。
    *   系统必须能优雅地处理外部 API（特别是 Twitter）的速率限制，通过排队机制确保请求按顺序、按间隔处理。

### 1.3. 用户交互

*   **即时反馈:** 当用户发送链接后，机器人应立即回复，告知链接已收到并加入处理队列。
*   **状态更新:** 在处理过程中，机器人应向用户发送关键状态的通知，例如“正在处理链接...”、“处理完成，已存入 Notion”或“处理失败”等。

### 1.4. 非功能性需求

*   **成本:** 所有使用的外部服务（API）都必须在免费套餐（Free Tier）范围内，以满足个人用户的零成本使用需求。
*   **部署:** 应用应为单个独立的 Python 程序，不依赖于任何需要额外部署和维护的外部服务（如 Redis, RabbitMQ 等）。

---

## 2. 设计文档 (Design Document)

本文档从技术实现角度出发，描述了系统的架构、组件和工作流程。

### 2.1. 高层架构

本系统是一个单进程、多线程的 Python 应用。其核心设计思想是 **“异步接收，同步处理”**，通过一个内存队列实现任务的解耦和削峰。

数据处理流程如下：
`用户` -> `Telegram 机器人` -> `内存队列 (Queue)` -> `后台工人 (Worker)` -> `[Twitter API -> Gemini API -> Notion API]` -> `Notion 数据库`

### 2.2. 核心组件

#### 2.2.1. `bot.py` (主应用模块)

*   **Telegram 接口:**
    *   使用 `python-telegram-bot` 库。
    *   `start()` 和 `handle_message()` 是主要的异步消息处理器。
    *   `handle_message()` 的职责被严格限定：快速解析消息中的链接，然后将其投入 `tweet_queue` 队列中，并向用户发送确认消息。这确保了前台交互的响应速度。

*   **任务队列 (`queue.Queue`)**
    *   使用 Python 内置的、线程安全的 `queue` 模块。
    *   队列中存放的是一个元组 `(tweet_url, chat_id, message_id)`，这使得后台工人在处理时，能够知道任务的上下文（例如，向哪个聊天窗口发送反馈）。

*   **后台工人 (`worker` 函数与 `threading.Thread`)**
    *   在程序启动时，一个独立的守护线程（Daemon Thread）会启动并运行 `worker` 函数。
    *   `worker` 函数是一个无限循环，是所有核心业务逻辑的执行者：
        1.  通过 `tweet_queue.get()` 以阻塞方式从队列中获取一个任务。
        2.  调用 `get_tweet_data()` 抓取推文。
        3.  调用 `notion_utils.get_tags_from_database()` 获取 Notion 中的预设标签。
        4.  调用 `get_summary_and_tags()` 将推文和标签列表发送给 Gemini AI 进行处理。
        5.  调用 `notion_utils.create_notion_page()` 将结果写入 Notion。
        6.  通过 `notify_user()` 辅助函数，安全地在 `worker` 线程中调用主程序的异步事件循环，向用户发送状态更新。
        7.  `time.sleep(15)` 强制等待 15 秒，以严格遵守 API 速率限制。

#### 2.2.2. `notion_utils.py` (Notion 服务模块)

*   一个完全 **同步** 的模块，封装了所有与 Notion API 的交互。
*   使用 `notion-client` 库的同步 `Client`。
*   **`get_tags_from_database()`**: 通过 `databases.retrieve` API 获取数据库的结构信息，并解析出 "Tags" 属性（`multi_select` 类型）的所有可用选项。
*   **`create_notion_page()`**: 按照 Notion API 的格式要求，构建创建页面的 `properties` JSON 对象，并调用 `pages.create` API。

#### 2.2.3. AI Prompt 设计

为了获取稳定、结构化的 AI 输出，我们设计了特定的 Prompt，要求 Gemini 以 JSON 格式返回结果。这是保证系统健壮性的关键。

```text
You are a content analysis and tagging expert.
Here is a list of predefined categories:
<['#标签1', '#标签2', ...]>

Here is the content of a tweet:
---
[推文内容]
---

Based on the tweet content, perform the following tasks and provide the output ONLY in a valid JSON format:

1.  **summary**: Write a concise, neutral summary of the tweet in Chinese.
2.  **matched_tags**: From the predefined categories list, select up to three (3) of the most relevant tags. The result must be a JSON array of strings. If no tags match, return an empty array.
3.  **ai_suggested_tag**: Generate exactly one new, insightful tag in Chinese or English that best categorizes the tweet, even if it's not in the predefined list. This tag must start with '#'. The result must be a JSON string.

Your response MUST be a single JSON object and nothing else.
```

### 2.3. 数据模型

*   **Notion 数据库结构:**

| 属性名称        | 类型 (`Type`)    | 描述                                     |
| --------------- | ---------------- | ---------------------------------------- |
| `Tweet Content` | `Text`           | 推文的完整原文。                         |
| `URL`           | `URL`            | 指向原始推文的链接。                     |
| `Summary`       | `Text`           | AI 生成的总结。                          |
| `Tags`          | `Multi-select`   | 从预设列表中匹配的标签。                 |
| `AI Tag`        | `Text`           | AI 建议的单个新标签。                    |
| `Processed Date`| `Created time`   | Notion 自动记录的创建时间。              |

*   **AI 输出 (JSON):**
    ```json
    {
      "title": "这是ai总结的title...",
      "summary": "这篇推文讨论了...",
      "matched_tags": ["#Tech", "#AI"],
      "ai_suggested_tag": "#LanguageModel"
    }
    ```

### 2.4. 环境配置 (`.env`)

系统启动需要以下 5 个环境变量：
*   `TELEGRAM_BOT_TOKEN`: Telegram 机器人的 token。
*   `TWITTER_BEARER_TOKEN`: Twitter API v2 的 Bearer Token。
*   `GEMINI_API_KEY`: Google Gemini API 的密钥。
*   `NOTION_API_KEY`: Notion Integration 的内部集成 Token。
*   `NOTION_DATABASE_ID`: Notion 数据库的 ID。

### 2.5. 未来迭代方向

*   **持久化队列:** 对于更严肃的场景，可将内存队列替换为基于 SQLite 的持久化队列，以确保在机器人重启时任务不丢失。
*   **批量通知:** 当用户一次性发送多个链接时，可在所有任务处理完毕后，发送一条总的成功通知，而不是多次打扰。
*   **更详细的错误处理:** 向用户提供更具体的失败原因（例如，“推文是私密的”或“AI 内容安全策略阻断”）。
