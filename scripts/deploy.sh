#!/bin/bash
# DCM Deployment Script for Cloudflare

set -e

echo "🚀 DCM Deployment Script"
echo "======================"

# Configuration
PROJECT_NAME="dcm-api"
REGION="us-east-1"

# Functions
deploy_docker() {
    echo "📦 Building Docker image..."
    docker build -t $PROJECT_NAME .
    
    echo "🐳 Running container..."
    docker run -d \
        --name $PROJECT_NAME \
        -p 8000:8000 \
        -e DCM_DATABASE_URL=sqlite:///./dcm.db \
        -v dcm-data:/app/data \
        $PROJECT_NAME
    
    echo "✅ Container deployed!"
    echo "   URL: http://localhost:8000"
}

deploy_cloudflare_pages() {
    echo "☁️ Deploying to Cloudflare Pages..."
    
    # Install Wrangler if not present
    if ! command -v wrangler &> /dev/null; then
        echo "   Installing Wrangler..."
        npm install -g wrangler
    fi
    
    # Deploy
    wrangler pages deploy .cloudflare --project-name=$PROJECT_NAME
    
    echo "✅ Cloudflare Pages deployed!"
}

deploy_cloudflare_container() {
    echo "☁️ Deploying to Cloudflare Container..."
    
    # Build and push to Cloudflare Container Registry
    docker tag $PROJECT_NAME ghcr.io/your-username/$PROJECT_NAME:latest
    docker push ghcr.io/your-username/$PROJECT_NAME:latest
    
    # Deploy via Cloudflare
    cf deploy --image ghcr.io/your-username/$PROJECT_NAME:latest
    
    echo "✅ Cloudflare Container deployed!"
}

# Main
case "${1:-docker}" in
    docker)
        deploy_docker
        ;;
    cf-pages)
        deploy_cloudflare_pages
        ;;
    cf-container)
        deploy_cloudflare_container
        ;;
    *)
        echo "Usage: $0 [docker|cf-pages|cf-container]"
        exit 1
        ;;
esac

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "Next steps:"
echo "  1. Initialize test wallets: POST /api/v1/wallet/initialize"
echo "  2. Check health: GET /health"
echo "  3. View docs: GET /docs"
