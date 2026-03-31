name: Daily Macro Data Update

# 設定觸發條件：每天 UTC 時間 00:00 (台灣時間早上 08:00) 自動執行，或是手動點擊執行
on:
  schedule:
    - cron: '0 0 * * *'
  workflow_dispatch:

jobs:
  update-data:
    runs-on: ubuntu-latest
    
    # 給予 GitHub Actions 寫入儲存庫 (Commit) 的權限
    permissions:
      contents: write

    steps:
    - name: Checkout repository
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install requests yfinance google-generativeai beautifulsoup4

    - name: Run Data Update Script
      env:
        GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
      run: |
        python scripts/update_data.py

    - name: Commit and push changes
      uses: stefanzweifel/git-auto-commit-action@v5
      with:
        commit_message: "🤖 Auto-update macro data and AI analysis"
        file_pattern: "data/*.json"
