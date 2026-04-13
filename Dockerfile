FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码（强制重新构建）
COPY src/ src/
COPY config.py .

# 构建时间戳（强制缓存失效）
RUN echo "Build time: $(date -u +%Y%m%d%H%M%S)" > /app/build_info.txt

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
