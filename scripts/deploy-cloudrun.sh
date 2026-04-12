#!/bin/bash
# DCM - Deploy to Google Cloud Run
# ============================================

set -e

echo "🚀 DCM Cloud Run 部署脚本"
echo "========================="

# 配置
PROJECT_ID=${GCP_PROJECT_ID:-""}
REGION="us-central1"
SERVICE_NAME="dcm-api"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# 检查 gcloud
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI 未安装"
    echo "   安装: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# 检查项目 ID
if [ -z "$PROJECT_ID" ]; then
    echo "❌ 请设置 GCP_PROJECT_ID 环境变量"
    echo "   export GCP_PROJECT_ID=your-project-id"
    exit 1
fi

# 设置项目
echo "📁 设置项目: $PROJECT_ID"
gcloud config set project $PROJECT_ID

# 启用必要服务
echo "⚙️  启用 Cloud Run API..."
gcloud services enable run.googleapis.com --quiet

echo "⚙️  启用 Cloud Build API..."
gcloud services enable cloudbuild.googleapis.com --quiet

echo "⚙️  启用 Container Registry API..."
gcloud services enable containerregistry.googleapis.com --quiet

# 构建并推送镜像
echo "📦 构建 Docker 镜像..."
gcloud builds submit \
    --tag $IMAGE_NAME:latest \
    --timeout 600s

# 部署到 Cloud Run
echo "🚀 部署到 Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME:latest \
    --region $REGION \
    --platform managed \
    --allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --port 8000 \
    --min-instances 0 \
    --max-instances 10 \
    --concurrency 80 \
    --timeout 60s \
    --set-env-vars "DCM_MVP_MODE=true,DCM_DATABASE_URL=sqlite:///./dcm.db"

# 获取服务 URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)')

echo ""
echo "✅ 部署完成!"
echo "=================="
echo "🌐 服务地址: $SERVICE_URL"
echo ""
echo "📝 下一步:"
echo "   1. 初始化钱包: curl -X POST $SERVICE_URL/api/v1/wallet/initialize"
echo "   2. 查看 API: curl $SERVICE_URL/docs"
echo "   3. 查看日志: gcloud run services logs read $SERVICE_NAME --region $REGION"
