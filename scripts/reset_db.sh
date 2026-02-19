#!/bin/bash

# RidgeRadar Database Reset Script
# Wipes all data from the database and Redis, then re-runs migrations.
# Use this when hibernating the app or starting fresh.

set -e

cd "$(dirname "$0")/.."

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "================================================"
echo -e "${RED}RidgeRadar Database Reset${NC}"
echo "This will DELETE ALL DATA from PostgreSQL and Redis."
echo "================================================"
echo ""

# Require explicit confirmation unless --yes flag is passed
if [[ "${1:-}" != "--yes" ]]; then
    read -p "Are you sure? Type 'RESET' to confirm: " confirmation
    if [[ "$confirmation" != "RESET" ]]; then
        echo "Aborted."
        exit 0
    fi
fi

echo ""

# 1. Stop application services (keep db and redis running)
echo "Stopping application services..."
docker compose stop app celery celery-beat 2>/dev/null || true
echo -e "${GREEN}✓ Application services stopped${NC}"

# 2. Wait for DB to be ready
echo "Checking database is available..."
until docker compose exec db pg_isready -U ridgeradar -d ridgeradar &>/dev/null; do
    echo "  Waiting for PostgreSQL..."
    sleep 2
done
echo -e "${GREEN}✓ PostgreSQL is ready${NC}"

# 3. Drop all tables by downgrading alembic to base
echo "Dropping all tables (alembic downgrade base)..."
docker compose run --rm app alembic downgrade base
echo -e "${GREEN}✓ All tables dropped${NC}"

# 4. Re-run all migrations
echo "Re-creating tables (alembic upgrade head)..."
docker compose run --rm app alembic upgrade head
echo -e "${GREEN}✓ Migrations applied - empty tables ready${NC}"

# 5. Flush Redis
echo "Flushing Redis..."
docker compose exec redis redis-cli FLUSHALL >/dev/null
echo -e "${GREEN}✓ Redis flushed${NC}"

# 6. Restart services (optional)
if [[ "${2:-}" == "--restart" ]] || [[ "${1:-}" == "--restart" ]]; then
    echo "Restarting application services..."
    docker compose up -d app celery celery-beat
    echo -e "${GREEN}✓ Services restarted${NC}"
else
    echo ""
    echo -e "${YELLOW}Application services are stopped.${NC}"
    echo "  To restart:  docker compose up -d"
    echo "  To hibernate: leave services stopped"
fi

echo ""
echo "================================================"
echo -e "${GREEN}Database reset complete.${NC}"
echo "  - All PostgreSQL tables wiped and recreated (empty)"
echo "  - Redis cache flushed"
echo "================================================"
