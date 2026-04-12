# Cloud Run 部署指南

> Google Cloud Run - 无服务器容器平台

---

## 概述

Cloud Run 是 Google Cloud 的无服务器容器平台：
- 完全托管，自动扩缩
- 按请求计费（免费额度充足）
- 与 Docker 完美兼容

---

## 免费额度

| 资源 | 免费额度 | DCM 估算 |
|------|---------|---------|
| vCPU-秒 | 450,000/月 | ~15,000/月 |
| GB-秒 | 360,000/月 | ~12,000/月 |
| 请求 | 2,000,000/月 | ~30,000/月 |

> **结论**：MVP 测试完全在免费额度内！

---

## 前置要求

1. **Google Cloud 账号**
2. **新建项目** 或使用现有项目
3. **gcloud CLI** 安装

### 安装 gcloud CLI

```bash
# macOS
brew install google-cloud-sdk

# 或下载
curl https://sdk.cloud.google.com | bash
gcloud init
```

---

## 部署步骤

### 1. 设置项目

```bash
# 创建新项目（可选）
gcloud projects create dcm-mvp --name="DCM MVP"

# 设置项目
export GCP_PROJECT_ID=your-project-id
gcloud config set project $GCP_PROJECT_ID
```

### 2. 启用 API

```bash
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    containerregistry.googleapis.com
```

### 3. 运行部署脚本

```bash
cd ~/Code/Platform/DCM
./scripts/deploy-cloudrun.sh
```

### 4. 或手动部署

```bash
# 构建并推送
gcloud builds submit --tag gcr.io/$PROJECT_ID/dcm-api

# 部署
gcloud run deploy dcm-api \
    --image gcr.io/$PROJECT_ID/dcm-api \
    --region us-central1 \
    --platform managed \
    --allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --port 8000
```

---

## 部署后

### 获取服务 URL

```bash
gcloud run services describe dcm-api --region us-central1 --format 'value(status.url)'
```

### 初始化钱包

```bash
SERVICE_URL="https://dcm-api-xxxx-uc.a.run.app"

curl -X POST $SERVICE_URL/api/v1/wallet/initialize
```

### 查看 API 文档

```
https://dcm-api-xxxx-uc.a.run.app/docs
```

---

## 环境变量

| 变量 | 值 | 说明 |
|------|-----|------|
| DCM_MVP_MODE | true | MVP 模式 |
| DCM_DATABASE_URL | sqlite:///./dcm.db | 数据库 |
| DCM_API_PORT | 8000 | 端口 |

---

## 数据库注意事项

### SQLite 限制

Cloud Run 的 SQLite：
- **临时文件系统**：重启后数据丢失
- **适合测试**：不保存重要数据

### 建议

MVP 测试使用默认 SQLite 即可。

**正式环境**：
- Cloud SQL (PostgreSQL)
- Firestore
- Cloud Storage (持久化 SQLite)

---

## 监控和日志

### 查看日志

```bash
gcloud run services logs read dcm-api --region us-central1
```

### Cloud Console

访问 https://console.cloud.google.com/run

---

## 自定义域名（可选）

```bash
gcloud run domain-mappings create \
    --service dcm-api \
    --domain api.your-domain.com \
    --region us-central1
```

需要验证域名所有权。

---

## CI/CD（可选）

### GitHub Actions

```yaml
# .github/workflows/deploy-cloudrun.yml
name: Deploy to Cloud Run

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - id: auth
        uses: google-github-actions/auth@v1
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}
      
      - name: Deploy
        run: |
          ./scripts/deploy-cloudrun.sh
        env:
          GCP_PROJECT_ID: ${{ secrets.GCP_PROJECT_ID }}
```

### 创建 Service Account

```bash
# 创建 SA
gcloud iam service-accounts create github-actions \
    --display-name="GitHub Actions"

# 授予权限
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/iam.serviceAccountUser"

# 创建密钥
gcloud iam service-accounts keys create key.json \
    --iam-account=github-actions@$PROJECT_ID.iam.gserviceaccount.com

# 在 GitHub Secrets 添加:
# GCP_SA_KEY: 密钥内容
# GCP_PROJECT_ID: 项目 ID
```

---

## 清理资源

```bash
# 删除服务
gcloud run services delete dcm-api --region us-central1

# 删除镜像
gcloud container images delete gcr.io/$PROJECT_ID/dcm-api --force-delete-tags
```

---

## 快速参考

```bash
# 部署
./scripts/deploy-cloudrun.sh

# 查看服务
gcloud run services describe dcm-api --region us-central1

# 查看日志
gcloud run services logs read dcm-api --region us-central1

# 更新
gcloud run deploy dcm-api --image gcr.io/$PROJECT_ID/dcm-api:latest

# 扩缩
gcloud run services update dcm-api --region us-central1 --min-instances=1

# 删除
gcloud run services delete dcm-api --region us-central1
```

---

## 故障排除

### 权限错误

```bash
# 确保已启用 API
gcloud services enable run.googleapis.com
```

### 镜像构建失败

```bash
# 本地测试构建
docker build -t dcm-api .
docker run -p 8000:8000 dcm-api
```

### 服务启动失败

```bash
# 查看日志
gcloud run services logs read dcm-api --region us-central1 --limit=50
```

---

## 下一步

1. 部署到 Cloud Run
2. 初始化钱包
3. 测试 API
4. 可选：配置自定义域名
