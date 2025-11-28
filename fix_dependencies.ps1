# Quick fix script for LangChain dependency issues (Windows PowerShell)
# Usage: .\fix_dependencies.ps1

$ErrorActionPreference = "Stop"

Write-Host "🔧 LINE Bot Dependencies Fix Script" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're in the right directory
if (-not (Test-Path "main.py")) {
    Write-Host "❌ Error: main.py not found. Please run this script from the project root directory." -ForegroundColor Red
    exit 1
}

Write-Host "📦 Step 1: Removing old LangChain packages..." -ForegroundColor Yellow
pip uninstall -y langchain langchain_core langchain-community langchain_google_genai 2>$null

Write-Host ""
Write-Host "📦 Step 2: Installing locked versions..." -ForegroundColor Yellow
pip install -r requirements-lock.txt

Write-Host ""
Write-Host "✅ Step 3: Verifying installation..." -ForegroundColor Yellow
$verifyCode = @"
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import PromptTemplate
    from langchain.chains.summarize import load_summarize_chain
    print('✅ All LangChain imports successful!')
except ImportError as e:
    print(f'❌ Import error: {e}')
    exit(1)
"@

$result = python -c $verifyCode
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "🎉 Dependencies fixed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📋 Installed versions:" -ForegroundColor Cyan
    pip list | Select-String -Pattern "langchain|pydantic|google-generativeai" | Sort-Object
    Write-Host ""
    Write-Host "🚀 You can now run: uvicorn main:app --reload" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "❌ Verification failed. Please check the error messages above." -ForegroundColor Red
    exit 1
}
