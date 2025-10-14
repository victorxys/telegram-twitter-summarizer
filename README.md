# Telegram Twitter Summarizer Bot

一个功能强大的 Telegram 机器人，能够自动抓取、总结 Twitter/X 链接，并将其结构化地存入 Notion 数据库，帮助你建立个人知识库。

## ✨ 功能特性

- **自动处理链接**: 监控 Telegram 对话，自动识别并处理消息中的 Twitter/X 链接。
- **AI 驱动的总结与标签**: 利用 Google Gemini Pro 模型，为每条推文生成简明扼要的中文标题和摘要。
- **智能标签系统**:
    - 从你的 Notion 数据库中预定义的标签列表进行匹配。
    - AI 会建议一个全新的、更具洞察力的标签。
- **结构化存储**: 将推文的原文、URL、AI 生成的标题、摘要和标签，完整地存入指定的 Notion 数据库。
- **清爽的交互**: 任务处理成功后，自动删除原始消息，保持对话界面的整洁。
- **队列化处理**: 采用后台工作线程和任务队列，确保在高负载下也能稳定、顺序地处理每一条链接。
- **Docker 化部署**: 提供 Dockerfile，支持快速、一致的容器化部署。

## 🛠️ 技术栈

- **后端**: Python 3.11
- **Telegram 机器人框架**: `python-telegram-bot`
- **Twitter API**: `tweepy`
- **Notion API**: `notion-client`
- **AI 模型**: Google Gemini Pro
- **部署**: Docker

## ⚙️ 配置指南

在运行此机器人之前，你需要完成以下配置步骤。

### 1. Notion 数据库设置

1.  在你的 Notion workspace 中创建一个新的**数据库 (Database)**。
2.  确保该数据库包含以下**属性 (Properties)**，并且**名称和类型完全匹配**：
    - `X Title` (类型: `Title`)
    - `X Content` (类型: `Rich Text`)
    - `URL` (类型: `URL`)
    - `Summary` (类型: `Rich Text`)
    - `AI Tag` (类型: `Rich Text`)
    - `Tags` (类型: `Multi-select`)
3.  在 `Tags` 属性中，你可以预先创建一些你常用的标签选项（例如 `AI`, `Web3`, `Programming`）。机器人会读取这些选项作为 AI 分类的基准。

### 2. 获取 API 密钥和 ID

你需要获取以下所有凭证：

- **`TELEGRAM_BOT_TOKEN`**: 从 Telegram 的 BotFather 那里获取你的机器人 Token。
- **`GEMINI_API_KEY`**: 访问 [Google AI for Developers](https://aistudio.google.com/app/apikey) 创建并获取你的 Gemini API 密钥。
- **`TWITTER_BEARER_TOKEN`**: 访问 [Twitter Developer Portal](https://developer.twitter.com/) 创建一个应用，并获取其 Bearer Token (App-only authentication)。
- **`NOTION_API_KEY`**:
    - 访问 [Notion Integrations](https://www.notion.so/my-integrations) 创建一个新的内部集成 (Internal Integration)。
    - 复制生成的 `Internal Integration Token`。
    - 回到你创建的 Notion 数据库，点击右上角的 `...` -> `Add connections`，然后选择你刚刚创建的那个集成，给予它编辑权限。
- **`NOTION_DATABASE_ID`**:
    - 在浏览器中打开你的 Notion 数据库页面。
    - URL 的结构通常是 `https://www.notion.so/YOUR_WORKSPACE/DATABASE_ID?v=VIEW_ID`。
    - `DATABASE_ID` 就是中间那段长字符串。复制它。

### 3. 创建 `.env` 文件

在项目的根目录下，创建一个名为 `.env` 的文件，并将你获取到的所有凭证填入其中：

```env
TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
GEMINI_API_KEY="your_gemini_api_key"
TWITTER_BEARER_TOKEN="your_twitter_bearer_token"
NOTION_API_KEY="your_notion_api_key"
NOTION_DATABASE_ID="your_notion_database_id"
```

## 🚀 运行与部署

### 本地开发环境

1.  **克隆仓库**
    ```bash
    git clone https://github.com/your-username/telegram-twitter-summarizer.git
    cd telegram-twitter-summarizer
    ```

2.  **创建并激活虚拟环境**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **安装依赖**
    ```bash
    pip install -r requirements.txt
    ```

4.  **配置 `.env` 文件** (参考上一节)

5.  **运行机器人**
    ```bash
    python bot.py
    ```

### 生产环境 (使用 Docker)

使用 Docker 是推荐的生产环境部署方式，它能确保环境的一致性和稳定性。

1.  **准备 `.env` 文件**: 在你的服务器上，确保与 `docker-compose.yml` 文件相同的目录下有一个配置正确的 `.env` 文件。

2.  **构建镜像**:
    在项目根目录，使用你的 Docker Hub 用户名和期望的版本号来构建并标记镜像。
    ```bash
    docker build -t your-dockerhub-username/telegram-summarize-bot:v1.0 .
    ```

3.  **推送镜像到仓库**:
    ```bash
    docker push your-dockerhub-username/telegram-summarize-bot:v1.0
    ```

4.  **使用 `docker-compose` 部署**:
    在服务器上创建一个 `docker-compose.yml` 文件，内容如下。**注意**：将 `image` 的值替换成你自己的镜像地址和版本号。

    ```yaml
    version: '3.8'

    services:
      bot:
        image: your-dockerhub-username/telegram-summarize-bot:v1.0
        container_name: my-telegram-bot
        restart: unless-stopped
        env_file:
          - .env
    ```

5.  **启动服务**:
    ```bash
    # 拉取最新镜像并以后台模式启动服务
    docker-compose pull && docker-compose up -d
    ```

## 🤝 贡献

欢迎提交 Pull Requests 或创建 Issues 来改进这个项目。

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源。