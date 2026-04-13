FROM python:3.11-slim AS builder

WORKDIR /app

# 复制依赖文件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有代码
COPY . .

FROM python:3.11-slim
WORKDIR /app

# 只复制必要文件（强制重新构建）
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=builder /app/src ./src
COPY --from=builder /app/config.py .

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口 (Render 会覆盖)
EXPOSE 10000

# 启动命令 - 使用 PORT 环境变量
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
