release: python db/setup.py
web: npm run build --prefix frontend && python -m uvicorn app:app --host 0.0.0.0 --port $PORT
