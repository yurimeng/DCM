# Cloudflare 部署指南

> DCM 可以通过 Docker 容器部署到 Cloudflare

---

## 方式一：Docker 容器部署

### 1. 本地构建

```bash
# 构建镜像
docker build -t dcm-api .

# 本地运行
docker run -d \
  --name dcm-api \
  -p 8000:8000 \
  -e DCM_DATABASE_URL=sqlite:///./dcm.db \
  dcm-api
```

### 2. 推送到 Container Registry

```bash
# 登录 Container Registry
docker login ghcr.io

# 标记镜像
docker tag dcm-api ghcr.io/your-username/dcm-api:latest

# 推送
docker push ghcr.io/your-username/dcm-api:latest
```

### 3. 部署到 Cloudflare

使用 [Cloudflare Container Hosting](https://developers.cloudflare.com/container-platform/)：

```bash
# 安装 cf CLI
npm install -g cf-cli

# 登录
cf login

# 部署
cf deploy ghcr.io/your-username/dcm-api:latest
```

---

## 方式二：Cloudflare Workers (改造)

Cloudflare Workers 使用 V8 JavaScript runtime，不支持 Python。
如需使用 Workers，需要：

1. 用 TypeScript 重写核心逻辑
2. 或使用 Python Workers (Beta)

### Python Workers (Beta)

```python
# workers/hello.py
def on_request(request):
    return Response("Hello from Cloudflare Workers!")
```

---

## 方式三：Cloudflare Pages + Functions

Cloudflare Pages 支持 Python Functions：

### 1. 项目结构

```
dcm/
├── functions/
│   └── api/
│       ├── _middleware.py
│       └── jobs.py
├── static/
├── wrangler.toml
└── requirements.txt
```

### 2. 部署

```bash
# 安装 Wrangler
npm install -g wrangler

# 登录
wrangler login

# 部署
wrangler pages deploy . --project-name=dcm-api
```

---

## 方式四：Docker Compose (开发环境)

```bash
# 启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| DCM_DATABASE_URL | 数据库连接 | sqlite:///./dcm.db |
| DCM_API_HOST | 监听地址 | 0.0.0.0 |
| DCM_API_PORT | 监听端口 | 8000 |
| DCM_MVP_MODE | MVP 模式 | true |
| DCM_CHAIN_RPC_URL | 链 RPC URL | 空 |

---

## 健康检查

```bash
curl http://localhost:8000/health

# Response:
{
  "status": "healthy",
  "version": "0.1.0"
}
```

---

## 数据库

MVP 使用 SQLite，数据文件：`dcm.db`

### 持久化

```bash
# 挂载数据卷
docker run -d \
  -v ./data:/app/data \
  -e DCM_DATABASE_URL=sqlite:///./data/dcm.db \
  dcm-api
```

### Cloudflare D1 (未来)

```bash
# 创建 D1 数据库
wrangler d1 create dcm-db

# 更新 wrangler.toml
[[d1_databases]]
binding = "DB"
database_name = "dcm-db"
database_id = "xxx"
```

---

## HTTPS 配置

### Cloudflare Proxy

1. 将域名添加到 Cloudflare
2. DNS 指向容器 IP
3. SSL/TLS 模式设为 "Full"

### 自定义证书

```bash
# 上传证书
wrangler certificates add cert.pem key.pem
```

---

## 监控

### Cloudflare Analytics

- Dashboard → Analytics & Logs
- 查看请求量、延迟、错误

### 日志

```bash
# 查看容器日志
docker logs -f dcm-api

# Cloudflare Logpush
wrangler logpush --bucket=your-bucket
```

---

## CI/CD

### GitHub Actions

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build and Push
        run: |
          docker build -t ghcr.io/${{ github.repository }}/dcm-api:${{ github.sha }} .
          docker push ghcr.io/${{ github.repository }}/dcm-api:${{ github.sha }}
      
      - name: Deploy to Cloudflare
        run: |
          cf deploy ghcr.io/${{ github.repository }}/dcm-api:${{ github.sha }}
        env:
          CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}
```

---

## 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/yurimeng/DCM.git
cd DCM

# 2. 启动本地服务
docker-compose up -d

# 3. 初始化钱包
curl -X POST http://localhost:8000/api/v1/wallet/initialize

# 4. 测试 API
curl http://localhost:8000/health
curl http://localhost:8000/docs
```

---

## 下一步

1. 配置自定义域名
2. 设置环境变量
3. 配置 CI/CD
4. 启用监控告警
