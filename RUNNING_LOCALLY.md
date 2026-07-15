# Running AEGIS Locally (No Docker)

The database is Neon (managed Postgres 17). No local Postgres instance needed.

## Setup

1. **Add your Neon URL to `.env`** in the project root or `backend/` directory:
   ```
   DATABASE_URL=postgresql://...neon.tech/aegis?sslmode=require
   ```
   The `.env` file is gitignored and must never be committed — your Neon password is in it.

2. **Install dependencies:**
   ```
   cd backend
   pip install -r requirements.txt
   ```

3. **Start the backend:**
   ```
   uvicorn main:app --reload --port 8000
   ```
   Tables are auto-created on first startup. The `load_dotenv()` in `database.py` picks up `.env` automatically — no need to export variables manually.

4. **Open the dashboard:**
   ```
   http://localhost:8000/dashboard
   ```
   The API health check is at `http://localhost:8000/`.

## SDK smoke test
```
cd sdk
python test_sdk.py
```
Expected output: step 1 OK, step 2 OK, step 3 BLOCKED.
