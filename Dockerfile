# QQ AI Bot — Docker 镜像
# ==========================
# 构建:  docker build -t qq-ai-bot .
# 运行:  docker run -d --name my-bot \
#          -v $(pwd)/data:/app/data \
#          -v $(pwd)/characters:/app/characters \
#          -v $(pwd)/config.yml:/app/config.yml \
#          -p 8765:8765 \
#          -e AIBOT_LLM__API_KEY=sk-xxx \
#          -e AIBOT_LLM__PROVIDER=deepseek \
#          qq-ai-bot

FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 数据目录
RUN mkdir -p /app/data

# WebSocket 端口（go-cqhttp 反向连接）
EXPOSE 8765

# 默认以 server 模式启动
CMD ["python", "main.py", "--bot", "server"]
