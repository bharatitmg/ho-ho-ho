#!/bin/bash

echo "🚀 GitHub Actions Deployment Setup"
echo "=================================="

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
    git branch -M main
fi

# Add all files
echo "Adding files to git..."
git add .

# Commit
echo "Creating initial commit..."
git commit -m "Initial commit: Automated data scraper with GitHub Actions"

echo ""
echo "✅ Repository prepared for GitHub!"
echo ""
echo "Next steps:"
echo "1. Create a new repository on GitHub.com"
echo "2. Copy the remote URL (e.g., https://github.com/username/repo.git)"
echo "3. Run: git remote add origin YOUR_REPO_URL"
echo "4. Run: git push -u origin main"
echo "5. Go to GitHub → Settings → Secrets and variables → Actions"
echo "6. Add these secrets:"
echo "   - OPENROUTER_API_KEY: Your OpenRouter API key"
echo "   - YOUR_SITE_URL: https://appsisi.com"
echo "   - YOUR_SITE_NAME: appsi"
echo "7. Go to Actions tab and run 'Data Scraping Automation' workflow"
echo ""
echo "📖 See README.md for detailed instructions"