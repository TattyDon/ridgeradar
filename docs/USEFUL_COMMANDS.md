# Useful Docker Commands for RidgeMarket

'''sudo apt update && sudo apt upgrade -y
git fetch origin
git merge --no-ff origin/main


Since the app directory is mounted as a read-only volume (./app:/app/app:ro), your code changes from git pull are picked up automatically — you just need to restart the containers, no rebuild needed:

cd ~/apps/ridgeradar && git pull && docker compose restart app celery celery-beat

If you've changed dependencies (e.g. requirements.txt) or the Dockerfile, then you need a rebuild:

cd ~/apps/ridgeradar && git pull && docker compose up -d --build


The deploy with a DB migration is:

cd ~/apps/ridgeradar
git pull
docker compose run --rm app alembic upgrade head
docker compose restart app celery celery-beat

Step by step:

git pull — get the latest code (including new migration files)
alembic upgrade head — runs all pending migrations against the DB. This uses the app service so it has the right DATABASE_URL_SYNC and network access to the DB container
restart — restart the app and workers to pick up the new code
If you've also changed dependencies (pyproject.toml), rebuild first:

git pull
docker compose build app
docker compose run --rm app alembic upgrade head
docker compose up -d

Note: You also have ./scripts/bootstrap.sh migrate as a shortcut for the alembic step — it does the same docker compose run --rm app alembic upgrade head under the hood.



## Viewing Logs

**View web service logs:**
```bash
docker-compose logs -f web
```

**View all service logs:**
```bash
docker-compose logs -f
```

## Odds Schedule Watchdog (Auto-Recover Beat)

If Celery beat stops emitting odds tasks, this watchdog restarts beat and triggers a run.

**Run manually:**
```bash
./odds_schedule_watchdog.sh
```

**Cron (every 5 minutes):**
```bash
*/5 * * * * /home/jl/apps/ridgemarkets/odds_schedule_watchdog.sh >> /var/log/ridgemarkets-watchdog.log 2>&1
```

## Fixture Ingestion Watchdog (Auto-Recover Beat)

If Celery beat stops emitting fixture ingestion tasks, this watchdog restarts beat and triggers API-Sports, Betfair, and linking tasks.

**Run manually:**
```bash
./fixtures_schedule_watchdog.sh
```

**Cron (every 10 minutes):**
```bash
*/10 * * * * /home/jl/apps/ridgemarkets/fixtures_schedule_watchdog.sh >> /var/log/ridgemarkets-watchdog.log 2>&1
```

## Rebuilding (after dependency changes)

**Rebuild and restart web service:**
```bash
docker-compose up -d --build web
```


THIS
cd ~/apps/ridgeradar
docker-compose down && docker-compose up -d --build

**Rebuild and restart all services:**
```bash
docker-compose up -d --build
```

## Docker Cleanup (Prune Commands)

**Safe cleanup (keeps volumes with data):**
```bash
# Remove stopped containers, unused images, and build cache
docker system prune -a
```

**Individual cleanup commands:**
```bash
# Remove all stopped containers
docker container prune

# Remove all unused images (not just dangling)
docker image prune -a

# Remove all unused networks
docker network prune

# Remove all unused build cache
docker builder prune
```

**Check what volumes exist:**
```bash
docker volume ls
```

**⚠️ DANGEROUS - Only use if you want to delete data:**
```bash
# Removes ALL unused volumes (including your database!)
docker volume prune

# Removes everything including volumes
docker system prune -a --volumes
```

**Note:** The safe prune commands (`docker system prune -a`) will clean up stopped containers, unused images, and build cache, but **preserve volumes** (including your database data).

## Database Migration (Local to Production)

**Migrate data from local database to production:**

### Option 1: Using Docker (Recommended)
If you have Docker containers running, use the Docker-based script:
```bash
./migrate_to_prod_docker.sh
```

### Option 2: Using PostgreSQL Client Tools
If you have `pg_dump` and `psql` installed on your host machine:
```bash
./migrate_to_prod.sh
```

**Important Notes:**
- Both scripts will **REPLACE all data** in the production database
- A backup file is automatically created in the `backups/` directory
- The scripts verify connectivity and perform basic validation after migration
- Make sure both local and production database containers are running before starting

**Prerequisites:**
- Local database running: `docker-compose up -d db`
- Production database running: `docker-compose -f docker-compose.prod.yml up -d db`

## Production Troubleshooting

### 502 Bad Gateway Error

If you're getting a 502 Bad Gateway on `https://ridgemarkets.penguinridge.co.uk`, follow these steps:

**1. SSH into the production server:**
```bash
ssh jl@135.181.198.140
cd /home/jl/apps/ridgemarkets
```

**2. Check if containers are running:**
```bash
docker-compose -f docker-compose.prod.yml ps
```

**3. Check web container logs for errors:**
```bash
docker-compose -f docker-compose.prod.yml logs --tail=100 web
```

**4. Test if the app is responding on port 8011:**
```bash
curl -I http://localhost:8011/health
```

**5. Check if nginx can reach the app:**
```bash
sudo nginx -t
curl -I http://127.0.0.1:8011/health
```

**6. Restart the web service:**
```bash
docker-compose -f docker-compose.prod.yml restart web
```

**7. If the container is down, restart all services:**
```bash
docker-compose -f docker-compose.prod.yml up -d
```

**8. Check nginx error logs:**
```bash
sudo tail -f /var/log/nginx/error.log
```

**9. Verify nginx configuration:**
```bash
sudo cat /etc/nginx/sites-available/ridgemarkets
```

**10. Reload nginx (if config changed):**
```bash
sudo nginx -t && sudo systemctl reload nginx
```

### Common Issues

**Container not running:**
- Check logs: `docker-compose -f docker-compose.prod.yml logs web`
- Rebuild if needed: `docker-compose -f docker-compose.prod.yml up -d --build web`

**Port 8011 not accessible:**
- Verify port mapping: `docker-compose -f docker-compose.prod.yml ps`
- Check if port is in use: `sudo netstat -tlnp | grep 8011`

**Database connection errors:**
- Check database is running: `docker-compose -f docker-compose.prod.yml ps db`
- Check database logs: `docker-compose -f docker-compose.prod.yml logs db`

## Notes

- **No virtual environment needed** - Docker containers have isolated environments with dependencies pre-installed
- Code changes in mounted volumes (like `app/`) are picked up after restart
- Database and Redis data persist in Docker volumes
- **Production URL**: https://ridgemarkets.penguinridge.co.uk
- **Production Port**: 8011 (mapped from container port 5000)