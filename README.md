# MediExplain MVP 🩺

[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.14+-3776AB?style=flat-square&logo=python)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-4169E1?style=flat-square&logo=postgresql)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)

**MediExplain** is a secure, privacy-conscious backend microservice built with FastAPI and PostgreSQL. It automatically ingests complex medical lab report PDFs, extracts key diagnostic metrics using pattern recognition, and synthesizes them into plain-language summaries and actionable recommendations.

---

## 📋 Features

- 📄 **PDF Report Parsing**: Extracts raw text content from uploaded medical documents using `pypdf`.
- 📊 **Diagnostic Metric Extraction**: Identifies key biomarkers, reference ranges, and test values.
- 💡 **Plain-Language Explanations**: Generates clear, non-alarmist health summaries and care recommendations.
- 📜 **User Audit History**: Tracks past document uploads, parsed metrics, and report explanations per user profile.
- 🔒 **Security & Credentials**: Strict environment isolation via `.env` with complete decoupling from version control.

---

## 🛠️ Architecture & Tech Stack

- **Framework:** FastAPI (Python 3.14)
- **Database:** PostgreSQL (via `psycopg` v3 driver)
- **PDF Engine:** `pypdf`
- **Environment Handling:** `python-dotenv`
- **API Spec:** OpenAPI / Swagger UI

### Directory Layout

```text
mediexplain-mvp/
├── backend/
│   ├── database.py         # PostgreSQL connection management & pooling
│   ├── main.py             # FastAPI initialization & router setup
│   ├── routers/
│   │   ├── reports.py      # /reports/upload endpoint pipeline
│   │   └── history.py      # /reports/history/{user_id} retrieval route
│   └── services/
│       ├── parser.py       # Regex & pattern matching for lab metrics
│       └── explainer.py    # Health summary & recommendation engine
├── uploads/                # Local document storage directory
├── .env.example            # Environment variable template
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites

- **Python**: 3.14+
- **PostgreSQL**: 15+ database server running locally or hosted

### Installation & Environment Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/evasafi/mediexplain-mvp.git
   cd mediexplain-mvp
   ```

2. **Configure Environment Variables**
   Create a local `.env` file based on the provided template:
   ```bash
   cp .env.example .env
   ```
   Populate `.env` with your PostgreSQL database credentials:
   ```ini
   DB_HOST=localhost
   DB_NAME=mediexplain_db
   DB_USER=postgres
   DB_PASSWORD=your_secure_password
   DB_PORT=5432
   ```

3. **Set Up Virtual Environment & Dependencies**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install fastapi uvicorn psycopg[binary] pypdf python-dotenv
   ```

4. **Launch Application**
   ```bash
   uvicorn backend.main:app --reload
   ```
   The API server will run at `http://127.0.0.1:8000`.

---

## 📡 API Endpoints Summary

| Method | Route | Description |
| :--- | :--- | :--- |
| `POST` | `/reports/upload` | Uploads PDF report, extracts metrics, stores data, returns summary. |
| `GET` | `/reports/history/{user_id}` | Retrieves past report history and summaries for a specific user ID. |
| `GET` | `/health` | Server status check. |
| `GET` | `/db-test` | Verifies active database connection. |

Interactive API documentation and schema testing are available at `http://127.0.0.1:8000/docs`.

---

## 🛡️ License

Distributed under the MIT License. See `LICENSE` for more information.