# Kubernetes Deployment Script for Procurement Automation (PowerShell)
# Supports: local (minikube/kind), azure (AKS), aws (EKS), gcp (GKE)

param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('setup-local', 'build', 'deploy', 'status', 'logs', 'forward', 'delete')]
    [string]$Command,
    
    [Parameter(Position=1)]
    [string]$Arg1,
    
    [Parameter(Position=2)]
    [string]$Arg2
)

$ErrorActionPreference = "Stop"

# Configuration
$NAMESPACE = "procurement-automation"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$K8S_DIR = Join-Path $SCRIPT_DIR "k8s"

# Functions
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Check-Prerequisites {
    Write-Info "Checking prerequisites..."
    
    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        Write-Error-Custom "kubectl not found. Please install kubectl."
        exit 1
    }
    
    if (-not (Get-Command kustomize -ErrorAction SilentlyContinue)) {
        Write-Warn "kustomize not found. Using kubectl apply -k instead."
    }
    
    Write-Info "Prerequisites check passed ?"
}

function Build-Images {
    param(
        [string]$Registry = "",
        [string]$Tag = "latest"
    )
    
    # Ensure Tag has a value
    if ([string]::IsNullOrWhiteSpace($Tag)) {
        $Tag = "latest"
    }
    
    Write-Info "Building Docker images with tag: $Tag"
    
    Push-Location $SCRIPT_DIR
    
    try {
        docker build -t "procurement-backend:$Tag" ./backend
        if ($LASTEXITCODE -ne 0) { throw "Backend build failed" }
        
        docker build -t "procurement-frontend:$Tag" ./frontend
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
        
        if (-not [string]::IsNullOrWhiteSpace($Registry)) {
            Write-Info "Tagging images for registry: $Registry"
            docker tag "procurement-backend:$Tag" "$Registry/procurement-backend:$Tag"
            docker tag "procurement-frontend:$Tag" "$Registry/procurement-frontend:$Tag"
            
            Write-Info "Pushing images to registry..."
            docker push "$Registry/procurement-backend:$Tag"
            docker push "$Registry/procurement-frontend:$Tag"
        }
        
        Write-Info "Images built successfully ✓"
    }
    catch {
        Write-Error-Custom "Build failed: $_"
        Pop-Location
        exit 1
    }
    finally {
        Pop-Location
    }
}

function Deploy-Environment {
    param([string]$Environment)
    
    Write-Info "Deploying to environment: $Environment"
    
    $overlayPath = Join-Path $K8S_DIR "overlays\$Environment"
    if (-not (Test-Path $overlayPath)) {
        Write-Error-Custom "Environment overlay not found: $Environment"
        exit 1
    }

    if ($Environment -eq "local") {
        $envLocalPath = Join-Path $SCRIPT_DIR ".env.local"
        $generatedEnvPath = Join-Path $overlayPath ".env.local.generated"

        if (-not (Test-Path $envLocalPath)) {
            Write-Error-Custom "Missing $envLocalPath. Create it before deploying local overlay."
            exit 1
        }

        Copy-Item -Path $envLocalPath -Destination $generatedEnvPath -Force
        Write-Info "Generated local kustomize env file from .env.local"
    }
    
    # Create namespace if it doesn't exist
    kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    
    # Apply kustomization
    try {
        kubectl apply -k $overlayPath
    }
    finally {
        if ($Environment -eq "local") {
            $generatedEnvPath = Join-Path $overlayPath ".env.local.generated"
            if (Test-Path $generatedEnvPath) {
                Remove-Item $generatedEnvPath -Force
            }
        }
    }
    
    Write-Info "Deployment initiated ?"
    Write-Info "Checking deployment status..."
    
    # Wait for deployments
    kubectl rollout status deployment/backend -n $NAMESPACE --timeout=300s
    kubectl rollout status deployment/worker -n $NAMESPACE --timeout=300s
    kubectl rollout status deployment/frontend -n $NAMESPACE --timeout=300s
    
    Write-Info "All deployments are ready ?"
}

function Show-Status {
    Write-Info "Deployment Status:"
    Write-Host ""
    kubectl get pods -n $NAMESPACE
    Write-Host ""
    kubectl get services -n $NAMESPACE
    Write-Host ""
    kubectl get ingress -n $NAMESPACE 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "No ingress found"
    }
}

function Show-Logs {
    param([string]$Component)
    
    if (-not $Component) {
        Write-Error-Custom "Please specify component: backend, frontend, or worker"
        exit 1
    }
    
    Write-Info "Showing logs for: $Component"
    kubectl logs -f -n $NAMESPACE -l "app=$Component" --tail=100
}

function Start-PortForward {
    Write-Info "Setting up port forwarding..."
    Write-Info "Frontend: http://localhost:3000"
    Write-Info "Backend: http://localhost:8000"
    Write-Info "Press Ctrl+C to stop"
    
    $jobs = @()
    
    $jobs += Start-Job -ScriptBlock {
        kubectl port-forward -n $using:NAMESPACE svc/frontend-service 3000:80
    }
    
    $jobs += Start-Job -ScriptBlock {
        kubectl port-forward -n $using:NAMESPACE svc/backend-service 8000:8000
    }
    
    try {
        $jobs | Wait-Job
    } finally {
        $jobs | Stop-Job
        $jobs | Remove-Job
    }
}

function Remove-Deployment {
    param([string]$Environment)
    
    Write-Warn "This will delete all resources in namespace: $NAMESPACE"
    $confirm = Read-Host "Are you sure? (yes/no)"
    
    if ($confirm -eq "yes") {
        Write-Info "Deleting deployment..."
        $overlayPath = Join-Path $K8S_DIR "overlays\$Environment"
        kubectl delete -k $overlayPath 2>$null
        kubectl delete namespace $NAMESPACE 2>$null
        Write-Info "Deployment deleted ?"
    } else {
        Write-Info "Deletion cancelled"
    }
}

function Setup-LocalCluster {
    Write-Info "Setting up local Kubernetes cluster..."
    
    if (Get-Command minikube -ErrorAction SilentlyContinue) {
        Write-Info "Starting Minikube..."
        minikube start --cpus=4 --memory=8192
        & minikube docker-env | Invoke-Expression
        Write-Info "Minikube started ?"
    } elseif (Get-Command kind -ErrorAction SilentlyContinue) {
        Write-Info "Creating Kind cluster..."
        kind create cluster --name procurement-local
        Write-Info "Kind cluster created ?"
    } else {
        Write-Error-Custom "Neither minikube nor kind found. Please install one of them."
        exit 1
    }
}

# Main script
switch ($Command) {
    "setup-local" {
        Setup-LocalCluster
    }
    "build" {
        Check-Prerequisites
        # Handle optional parameters properly
        if ([string]::IsNullOrWhiteSpace($Arg1) -and [string]::IsNullOrWhiteSpace($Arg2)) {
            # No registry, no tag - use defaults
            Build-Images
        } elseif (-not [string]::IsNullOrWhiteSpace($Arg1) -and [string]::IsNullOrWhiteSpace($Arg2)) {
            # Registry provided, no tag
            Build-Images -Registry $Arg1
        } elseif ([string]::IsNullOrWhiteSpace($Arg1) -and -not [string]::IsNullOrWhiteSpace($Arg2)) {
            # No registry, tag provided
            Build-Images -Tag $Arg2
        } else {
            # Both provided
            Build-Images -Registry $Arg1 -Tag $Arg2
        }
    }
    "deploy" {
        Check-Prerequisites
        Deploy-Environment -Environment $Arg1
    }
    "status" {
        Show-Status
    }
    "logs" {
        Show-Logs -Component $Arg1
    }
    "forward" {
        Start-PortForward
    }
    "delete" {
        Remove-Deployment -Environment $Arg1
    }
}
