#!/bin/bash

# 如果任何命令失败，立即停止脚本
set -e

# --- 配置 ---
# 你的 Docker Hub 用户名/仓库名
IMAGE_NAME="victorxys/telegram-summarize-bot"
# 目标服务器的硬件架构
PLATFORM="linux/amd64"

# --- 1. 从 Docker Hub 获取最新版本 ---
echo "🔎 正在从 Docker Hub 获取 [${IMAGE_NAME}] 的版本标签..."

# 使用 curl 请求 Docker Hub API，通过一系列管道命令筛选出版本号最高的标签
# - grep -o '"name"\: *"v[0-9\.]*"' : 匹配 "name": "vX.Y.Z" 格式的行
# - grep -o 'v[0-9\.]*' : 从上面结果中只提取 vX.Y.Z 部分
# - sort -V : 按版本号自然排序 (例如 v1.10 会排在 v1.2 之后)
# - tail -n 1 : 取最后一行，也就是版本号最高的那个
LATEST_VERSION=$(curl -s "https://hub.docker.com/v2/repositories/${IMAGE_NAME}/tags/?page_size=100" | \
                 grep -o '"name"\: *"v[0-9\.]*"' | \
                 grep -o 'v[0-9\.]*' | \
                 sort -V | \
                 tail -n 1)

if [ -z "$LATEST_VERSION" ]; then
  echo "⚠️ 未找到历史版本，将从 v1.0.0 开始。"
  # 如果这是第一次构建，我们从 v1.0.0 开始
  # 这里我们假设使用三段式版本号 X.Y.Z (主版本.次版本.修订号)
  NEW_VERSION="v1.0.0"
else
  echo "✅ 已找到最新版本: ${LATEST_VERSION}"
  
  # --- 2. 递增版本号 ---
  # 使用 awk 来递增修订号 (最后一段数字)
  NEW_VERSION=$(echo "$LATEST_VERSION" | awk -F. -v OFS=. '{ 
    # 移除版本号开头的 'v' 以便计算
    sub(/^v/, "", $1);
    # 将最后一段（修订号）加一
    $NF = $NF + 1;
    # 把 'v' 加回来并打印
    print "v" $0;
  }')
fi

echo "🚀 即将构建的新版本为: ${NEW_VERSION}"

# --- 3. 构建并推送镜像 ---
echo "🛠️ 正在为平台 [${PLATFORM}] 构建并推送镜像..."
echo "   镜像: ${IMAGE_NAME}:${NEW_VERSION}"
echo "   同时标记为: ${IMAGE_NAME}:latest"

docker buildx build \
  --platform "$PLATFORM" \
  -t "${IMAGE_NAME}:${NEW_VERSION}" \
  -t "${IMAGE_NAME}:latest" \
  --push \
  .

echo ""
echo "✅ Successfully built and pushed ${IMAGE_NAME}:${NEW_VERSION} 和 ${IMAGE_NAME}:latest."
echo ""
echo "--------------------------------------------------"
echo "下一步：在你的生产服务器上执行以下操作"
echo "--------------------------------------------------"
echo ""
echo "1. SSH 登录到你的服务器。"
echo ""
echo "2. 编辑 docker-compose.yml 文件，将 image 更新为新版本:"
echo "   image: ${IMAGE_NAME}:${NEW_VERSION}"
echo ""
echo "3. 拉取新镜像并重启服务:"
echo "   docker-compose pull && docker-compose up -d"
echo ""
echo "--------------------------------------------------"
