#!/bin/bash

# Kubernetes Deployment Script for Procurement Automation
# Supports: local (minikube/kind), azure (AKS), aws (EKS), gcp (GKE)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="procurement-automation"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="${SCRIPT_DIR}/k8s"

# Functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    print_info "Checking prerequisites..."
    
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl not found. Please install kubectl."
        exit 1
    fi
    
    if ! command -v kustomize &> /dev/null; then
        print_warn "kustomize not found. Using kubectl apply -k instead."
    fi
    
    print_info "Prerequisites check passed ✓"
}

build_images() {
    local registry=$1
    local tag=${2:-latest}
    
    print_info "Building Docker images..."
    
    docker build -t procurement-backend:${tag} ./backend
    docker build -t procurement-frontend:${tag} ./frontend
    
    if [ -n "$registry" ]; then
        print_info "Tagging images for registry: $registry"
        docker tag procurement-backend:${tag} ${registry}/procurement-backend:${tag}
        docker tag procurement-frontend:${tag} ${registry}/procurement-frontend:${tag}
        
        print_info "Pushing images to registry..."
        docker push ${registry}/procurement-backend:${tag}
        docker push ${registry}/procurement-frontend:${tag}
    fi
    
    print_info "Images built successfully ✓"
}

deploy() {
    local environment=$1
    
    print_info "Deploying to environment: $environment"
    
    if [ ! -d "${K8S_DIR}/overlays/${environment}" ]; then
        print_error "Environment overlay not found: ${environment}"
        exit 1
    fi

    if [ "${environment}" = "local" ]; then
        local env_local_path="${SCRIPT_DIR}/.env.local"
        local generated_env_path="${K8S_DIR}/overlays/${environment}/.env.local.generated"

        if [ ! -f "${env_local_path}" ]; then
            print_error "Missing ${env_local_path}. Create it before deploying local overlay."
            exit 1
        fi

        cp "${env_local_path}" "${generated_env_path}"
        print_info "Generated local kustomize env file from .env.local"
    fi
    
    # Create namespace if it doesn't exist
    kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -
    
    # Apply kustomization
    if [ "${environment}" = "local" ]; then
        trap 'rm -f "${K8S_DIR}/overlays/${environment}/.env.local.generated"' RETURN
    fi
    kubectl apply -k ${K8S_DIR}/overlays/${environment}/
    
    print_info "Deployment initiated ✓"
    print_info "Checking deployment status..."
    
    # Wait for deployments
    kubectl rollout status deployment/backend -n ${NAMESPACE} --timeout=300s
    kubectl rollout status deployment/worker -n ${NAMESPACE} --timeout=300s
    kubectl rollout status deployment/frontend -n ${NAMESPACE} --timeout=300s
    
    print_info "All deployments are ready ✓"
}

show_status() {
    print_info "Deployment Status:"
    echo ""
    kubectl get pods -n ${NAMESPACE}
    echo ""
    kubectl get services -n ${NAMESPACE}
    echo ""
    kubectl get ingress -n ${NAMESPACE} 2>/dev/null || print_warn "No ingress found"
}

show_logs() {
    local component=$1
    
    if [ -z "$component" ]; then
        print_error "Please specify component: backend, frontend, or worker"
        exit 1
    fi
    
    print_info "Showing logs for: $component"
    kubectl logs -f -n ${NAMESPACE} -l app=${component} --tail=100
}

port_forward() {
    print_info "Setting up port forwarding..."
    print_info "Frontend: http://localhost:3000"
    print_info "Backend: http://localhost:8000"
    print_info "Press Ctrl+C to stop"
    
    trap 'kill $(jobs -p)' EXIT
    
    kubectl port-forward -n ${NAMESPACE} svc/frontend-service 3000:80 &
    kubectl port-forward -n ${NAMESPACE} svc/backend-service 8000:8000 &
    
    wait
}

delete_deployment() {
    local environment=$1
    
    print_warn "This will delete all resources in namespace: ${NAMESPACE}"
    read -p "Are you sure? (yes/no): " confirm
    
    if [ "$confirm" == "yes" ]; then
        print_info "Deleting deployment..."
        kubectl delete -k ${K8S_DIR}/overlays/${environment}/ || true
        kubectl delete namespace ${NAMESPACE} || true
        print_info "Deployment deleted ✓"
    else
        print_info "Deletion cancelled"
    fi
}

setup_local() {
    print_info "Setting up local Kubernetes cluster..."
    
    if command -v minikube &> /dev/null; then
        print_info "Starting Minikube..."
        minikube start --cpus=4 --memory=8192
        eval $(minikube docker-env)
        print_info "Minikube started ✓"
    elif command -v kind &> /dev/null; then
        print_info "Creating Kind cluster..."
        kind create cluster --name procurement-local
        print_info "Kind cluster created ✓"
    else
        print_error "Neither minikube nor kind found. Please install one of them."
        exit 1
    fi
}

# Main script
main() {
    case "$1" in
        setup-local)
            setup_local
            ;;
        build)
            check_prerequisites
            build_images "$2" "$3"
            ;;
        deploy)
            check_prerequisites
            deploy "$2"
            ;;
        status)
            show_status
            ;;
        logs)
            show_logs "$2"
            ;;
        forward)
            port_forward
            ;;
        delete)
            delete_deployment "$2"
            ;;
        *)
            echo "Usage: $0 {setup-local|build|deploy|status|logs|forward|delete} [options]"
            echo ""
            echo "Commands:"
            echo "  setup-local              - Setup local Kubernetes cluster (minikube/kind)"
            echo "  build [registry] [tag]   - Build Docker images"
            echo "  deploy <environment>     - Deploy to environment (local|azure|aws|gcp)"
            echo "  status                   - Show deployment status"
            echo "  logs <component>         - Show logs (backend|frontend|worker)"
            echo "  forward                  - Setup port forwarding for local access"
            echo "  delete <environment>     - Delete deployment"
            echo ""
            echo "Examples:"
            echo "  $0 setup-local"
            echo "  $0 build myregistry.azurecr.io 1.0"
            echo "  $0 deploy local"
            echo "  $0 deploy azure"
            echo "  $0 status"
            echo "  $0 logs backend"
            echo "  $0 forward"
            exit 1
            ;;
    esac
}

main "$@"
