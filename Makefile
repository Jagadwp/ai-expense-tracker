.PHONY: install api frontend dev kill migrate test typecheck genkey

# Install backend (venv) and frontend (npm) dependencies.
install:
	python3.12 -m venv venv
	venv/bin/pip install -r requirements.txt
	cd frontend && npm install

# Run the FastAPI backend alone (port 8080).
api:
	venv/bin/uvicorn app.main:app --reload --port 8080

# Run the Vue frontend alone (port 5173).
frontend:
	cd frontend && npm run dev

# Run backend + frontend together. Ctrl+C stops both.
dev:
	@trap 'kill 0' SIGINT SIGTERM EXIT; \
	venv/bin/uvicorn app.main:app --reload --port 8080 & \
	(cd frontend && npm run dev) & \
	wait

# Kill anything still listening on the backend (8080) or frontend (5173)
# ports — for when `make dev` was interrupted without cleaning up (e.g. the
# terminal was closed instead of Ctrl+C).
kill:
	-lsof -ti :8080 | xargs kill -9
	-lsof -ti :5173 | xargs kill -9

# Apply all database migrations in order.
migrate:
	psql "$$DATABASE_URL" -f migrations/001_epic1.sql
	psql "$$DATABASE_URL" -f migrations/002_sender_filters.sql
	psql "$$DATABASE_URL" -f migrations/003_add_is_transfer.sql
	psql "$$DATABASE_URL" -f migrations/004_add_is_manual.sql
	psql "$$DATABASE_URL" -f migrations/005_soft_delete_transactions.sql
	psql "$$DATABASE_URL" -f migrations/006_transactions_date_no_tz.sql

# Run backend tests.
test:
	venv/bin/python -m pytest app/tests/ -v

# Type-check the frontend.
typecheck:
	cd frontend && npx vue-tsc -b

# Generate a random 32-byte base64 key, for ENCRYPTION_KEY / SESSION_SECRET.
genkey:
	openssl rand -base64 32
