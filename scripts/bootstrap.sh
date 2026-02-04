#!/bin/bash

# RidgeRadar Bootstrap Script
# This script sets up the development environment for RidgeRadar Phase 1

set -e

echo "================================================"
echo "RidgeRadar Phase 1 Bootstrap"
echo "Shadow Mode - Measurement Infrastructure"
echo "================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check for required tools
check_requirements() {
    echo "Checking requirements..."

    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: Docker is not installed${NC}"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        echo -e "${RED}Error: Docker Compose is not installed${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ Docker and Docker Compose found${NC}"
}

# Check for .env file
check_env() {
    if [ ! -f .env ]; then
        echo -e "${YELLOW}Warning: .env file not found${NC}"
        echo "Creating .env from .env.example..."
        cp .env.example .env
        echo -e "${YELLOW}Please edit .env and add your Betfair credentials${NC}"
        echo ""
    else
        echo -e "${GREEN}✓ .env file found${NC}"
    fi
}

# Start infrastructure services (DB, Redis)
start_infrastructure() {
    echo ""
    echo "Starting infrastructure services..."
    docker compose up -d db redis

    echo "Waiting for PostgreSQL to be ready..."
    sleep 5

    # Wait for PostgreSQL
    until docker compose exec db pg_isready -U ridgeradar -d ridgeradar &> /dev/null; do
        echo "  Waiting for PostgreSQL..."
        sleep 2
    done

    echo -e "${GREEN}✓ PostgreSQL is ready${NC}"

    # Wait for Redis
    until docker compose exec redis redis-cli ping &> /dev/null; do
        echo "  Waiting for Redis..."
        sleep 2
    done

    echo -e "${GREEN}✓ Redis is ready${NC}"
}

# Run database migrations
run_migrations() {
    echo ""
    echo "Running database migrations..."

    # Build the app image first
    docker compose build app

    # Run migrations
    docker compose run --rm app alembic upgrade head

    echo -e "${GREEN}✓ Migrations complete${NC}"
}

# Start all services
start_all() {
    echo ""
    echo "Starting all RidgeRadar services..."
    docker compose up -d

    echo ""
    echo "Waiting for services to be healthy..."
    sleep 10
}

# Check service health
check_health() {
    echo ""
    echo "Checking service health..."

    # Check app
    if curl -s http://localhost:8000/health | grep -q "healthy"; then
        echo -e "${GREEN}✓ App is healthy${NC}"
    else
        echo -e "${RED}✗ App is not responding${NC}"
    fi
}

# Print summary
print_summary() {
    echo ""
    echo "================================================"
    echo -e "${GREEN}RidgeRadar Phase 1 is running!${NC}"
    echo "================================================"
    echo ""
    echo "Services:"
    echo "  - Web UI:     http://localhost:8000"
    echo "  - API Docs:   http://localhost:8000/docs"
    echo "  - PostgreSQL: localhost:5432"
    echo "  - Redis:      localhost:6379"
    echo ""
    echo "Quick Commands:"
    echo "  View logs:    docker compose logs -f"
    echo "  Stop all:     docker compose down"
    echo "  Run tests:    docker compose run --rm app pytest"
    echo ""
    echo -e "${YELLOW}IMPORTANT: RidgeRadar is in SHADOW MODE${NC}"
    echo "  - No betting or live execution"
    echo "  - Measurement infrastructure only"
    echo "  - Focus on secondary leagues"
    echo ""

    # Check if Betfair credentials are set
    if grep -q "BETFAIR_USERNAME=$" .env; then
        echo -e "${YELLOW}⚠ Betfair credentials not configured${NC}"
        echo "  Edit .env and add your Betfair credentials"
        echo "  Then restart: docker compose restart"
        echo ""
    fi
}

# Main
main() {
    cd "$(dirname "$0")/.."

    check_requirements
    check_env
    start_infrastructure
    run_migrations
    start_all
    check_health
    print_summary
}

# Handle arguments
case "${1:-}" in
    "infra")
        check_requirements
        check_env
        start_infrastructure
        echo -e "${GREEN}Infrastructure started${NC}"
        ;;
    "migrate")
        run_migrations
        ;;
    "stop")
        docker compose down
        echo -e "${GREEN}All services stopped${NC}"
        ;;
    "logs")
        docker compose logs -f
        ;;
    "test")
        docker compose run --rm app pytest "${@:2}"
        ;;
    *)
        main
        ;;
esac
