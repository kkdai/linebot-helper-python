#!/bin/bash
# Quick fix script for LangChain dependency issues
# Usage: bash fix_dependencies.sh

set -e

echo "🔧 LINE Bot Dependencies Fix Script"
echo "===================================="
echo ""

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: main.py not found. Please run this script from the project root directory."
    exit 1
fi

echo "📦 Step 1: Removing old LangChain packages..."
pip uninstall -y langchain langchain_core langchain-community langchain_google_genai 2>/dev/null || true

echo ""
echo "📦 Step 2: Installing locked versions..."
pip install -r requirements-lock.txt

echo ""
echo "✅ Step 3: Verifying installation..."
python3 -c "
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import PromptTemplate
    from langchain.chains.summarize import load_summarize_chain
    print('✅ All LangChain imports successful!')
except ImportError as e:
    print(f'❌ Import error: {e}')
    exit(1)
"

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 Dependencies fixed successfully!"
    echo ""
    echo "📋 Installed versions:"
    pip list | grep -E "langchain|pydantic|google-generativeai" | sort
    echo ""
    echo "🚀 You can now run: uvicorn main:app --reload"
else
    echo ""
    echo "❌ Verification failed. Please check the error messages above."
    exit 1
fi
