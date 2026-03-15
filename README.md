# 🧾 מנהל קבלות חכם

A Streamlit app that automatically classifies and organizes business receipts into Google Drive using **Gemini 2.0 Flash** AI.

## Features

- 📤 Upload multiple images/PDFs at once
- 🤖 AI-powered expense classification (Gemini 2.0 Flash, temp=0)
- 📁 Automatic folder creation: monthly (`ינואר 2026`) or annual (`2026 שנתי`)
- ♻️ MD5 deduplication — never uploads the same file twice
- 🏷️ Smart filename: `YYYY-MM-DD - Provider - ExpenseType.ext`
- 🔒 Secure Service Account authentication

## Quick Start

### 1. Configure credentials

```
cp .env.example .env
# Edit .env → add GEMINI_API_KEY and DRIVE_FOLDER_ID
# Place your credentials.json in this folder
```

### 2. Run the app

```bash
uv run streamlit run app.py
```

Open `http://localhost:8501` in your browser.

## Project Structure

```
invoice_manager/
├── app.py              # Streamlit UI
├── config.py           # Constants, expense list, Hebrew months
├── drive_service.py    # Google Drive API wrapper
├── gemini_service.py   # Gemini AI analysis
├── deduplication.py    # MD5 hashing + metadata.json
├── file_processor.py   # Orchestration pipeline
├── pyproject.toml      # uv dependencies
├── .env.example        # Secret template
└── credentials.json    # ← you supply this (not in git)
```

## Folder Logic

| Expense Type | Target Folder |
|---|---|
| Regular monthly expenses | `חודש YYYY` (e.g. `מרץ 2026`) |
| Annual (חובה/טסט/ביטוח/ריבית/עמלות בנק) | `YYYY שנתי` |
| Fixed Asset (רכוש קבוע) | Monthly folder + `רכוש קבוע` in filename |

## Required Environment Variables

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio API key |
| `DRIVE_FOLDER_ID` | Google Drive folder shared with service account |
| `CREDENTIALS_PATH` | Path to service account JSON (default: `credentials.json`) |
