# 使用官方的、轻量的 Python 3.11 镜像作为基础
FROM python:3.11-slim

# 在容器中设置一个工作目录
WORKDIR /app

# 将依赖文件复制到工作目录
# 我们先只复制这个文件，是为了利用 Docker 的层缓存机制
# 只要 requirements.txt 不变，下面的安装步骤就不会重复执行，从而加快构建速度
COPY requirements.txt .

# 安装项目依赖，--no-cache-dir 选项可以减小镜像体积
RUN pip install --no-cache-dir -r requirements.txt

# 将项目中的所有其他文件复制到工作目录
COPY . .

# 定义容器启动时要执行的命令
CMD ["python", "bot.py"]
