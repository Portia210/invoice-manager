# 🧾 מנהל קבלות חכם (Smart Invoice Manager)

A robust, AI-powered system that automatically scans your Gmail inbox, classifies financial documents using **Gemini 2.0 Flash**, and organizes them into a structured Google Drive hierarchy.

---

## 🚀 Current State (March 2026)

The project is currently in a **stable, production-ready state** with the following capabilities:

### 1. Automated Gmail Scanning
- **Deep Inbox Analysis**: Scans the last year of emails for potential receipts and invoices.
- **Smart Filtering**: Uses text-based heuristics to filter out non-financial emails before AI processing (saves costs/time).
- **Concurrency**: Processes multiple emails in parallel for high performance.
- **Resumption & Persistence**: If stopped or interrupted, the scan can be resumed. Results are cached in the UI for review.

### 2. Intelligent AI Classification
- **Chain of Thought (CoT)**: Gemini is prompted to perform a logical reasoning step (analyzing Tax ID, unique document numbers, and merchant context) before classifying.
- **Context-Aware**: The AI reads both the email body and the document image/PDF to distinguish between "Price Offers" (skipped) and "Actual Invoices" (processed).
- **Business Expense Logic**: Intelligent handling of ambiguous cases (e.g., software subscriptions like YouTube Music are correctly marked as non-business if applicable).

### 3. Rock-Solid Stability
- **No-Shared-Service Strategy**: Resolves all thread-related SSL errors by isolating Google Drive transports per operations.
- **Duplicate Prevention**: Global threading locks prevent the creation of duplicate folders (e.g., multiple "2026" folders) during parallel runs.
- **Playwright PDF Rendering**: High-fidelity conversion of HTML emails to PDF for archiving.

### 4. Advanced UI (Streamlit)
- **Live Progress Logging**: Real-time visibility into what the AI is thinking for each email.
- **Stop Control**: Dedicated button to gracefully stop a running Gmail scan.
- **History Metrics**: Immediate summary of processed documents with direct links to Google Drive.

---

## 🛠 Technical Architecture

- **Core**: Python 3.11 + Streamlit
- **AI Engine**: `google-generativeai` (Gemini 2.0 Flash)
- **Storage**: Google Drive API (`google-api-python-client`)
- **PDF Core**: Playwright (Headless Chromium)
- **Concurrency**: `concurrent.futures.ThreadPoolExecutor` with thread-safe resource isolation.

---

## 📁 Drive Structure Logic

| Expense Type | Target Folder | Filename Pattern |
|---|---|---|
| Regular Monthly | `YYYY/MM-YYYY` | `[Type] - [Amount] - [Provider] - [Date].ext` |
| Annual (Fees/Insurance) | `YYYY/YYYY שנתי` | Same |
| Non-Business | `YYYY/.../Non-Business` | `NOT_BUSINESS - [Amount] - [Provider] - [Date].ext` |
| Fixed Asset | Regular folder | Suffix: `.רכוש קבוע` |

---

## 🔧 Installation & Setup

### 1. Credentials
1. Place `credentials.json` (OAuth2 or Service Account) in the root.
2. If using OAuth2, run: `uv run python setup_auth.py` and follow the link.
3. Configure `.env`:
   ```env
   GEMINI_API_KEY=your_key
   DRIVE_FOLDER_ID=your_id
   REQUIRE_PASSWORD=FALSE  # For local use
   ```

### 2. Launch
```bash
uv run streamlit run app.py
```

---

## 🔮 Roadmap
- [ ] **Manual Correction UI**: Allow users to edit AI-detected amounts or providers directly in the history tab.
- [ ] **Email Auto-Archive**: Move processed emails to a "Processed Receipts" label in Gmail.
- [ ] **Direct Export**: Generate monthly CSV/Excel reports for accountants.
