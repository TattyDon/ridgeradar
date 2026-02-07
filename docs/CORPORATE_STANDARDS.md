# 🏢 CORPORATE_STANDARDS.md
## PenguinRidge – Corporate Deployment Standards & Best Practices

This document outlines the standardized architecture, deployment patterns, and best practices used across all PenguinRidge applications. This is the **shared foundation** that all projects follow.

---

## ✅ Core Infrastructure Standards

### Server Configuration
- **OS**: Ubuntu 24.04 LTS (VPS)
- **IP**: 135.181.198.140
- **Reverse Proxy**: Host-level Nginx
- **SSL**: Let's Encrypt via Certbot
- **Firewall**: UFW
- **Docker Orchestration**: Docker Compose v2
- **Apps Directory**: `/home/jl/apps/<appname>`
- **Subdomains**: `*.penguinridge.co.uk`
- **DNS Control Panel**: https://ap.www.namecheap.com/Domains/DomainControlPanel/penguinridge.co.uk/advancedns
- **Version Control**: Git commit tracking in all containers
- **Build Process**: No-cache rebuilds with verification

---

## 🔐 Authentication Standards

### Application-Specific Authentication
PenguinRidge applications use different authentication methods depending on their requirements:

#### Simple Authentication (Default)
All PenguinRidge applications use simple authentication by default:
- **Username-Based Login**: Standard username/password authentication
- **Auto-Creation**: Default admin user created automatically on startup
- **Role-Based Access**: Admin, trader, readonly, and system roles supported
- **No OAuth Required**: Direct login without external authentication
- **Environment Variables**: Basic authentication configuration only

#### OAuth Applications (Optional)
Some applications may use OAuth for multi-user scenarios:
- **Google OAuth**: For multi-user applications (if needed)
- **Email-Based Access Control**: Via environment variables
- **Optional Whitelisting**: Email-based access control

### Required Environment Variables (Standard)

**For Simple Authentication (All Apps):**
```bash
# Basic Configuration (no OAuth needed)
SECRET_KEY=your-secret-key-here
ADMIN_EMAIL=john.laverick@gmail.com
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=admin123

# Optional Whitelisting (if enabled)
WHITELIST_ENABLED=false  # Set to true to enable whitelisting
ALLOWED_USERS=john.laverick@gmail.com  # Only used if WHITELIST_ENABLED=true
```

**For OAuth Applications (if implemented):**
```bash
# Google OAuth Configuration (only if using OAuth)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Access Control Configuration (only if using OAuth)
ADMIN_EMAIL=john.laverick@gmail.com
ALLOWED_USERS=john.laverick@gmail.com,user2@domain.com
ADMIN_USERS=john.laverick@gmail.com
```

### Access Control Logic

**Simple Authentication (Default):**
- **User Access**: Default admin user automatically created on startup
- **Admin Access**: Username-based login with configurable credentials
- **Auto-Creation**: Admin user created automatically if none exists
- **No Whitelisting**: No email-based access control required

**Optional Whitelisting (if enabled):**
- **User Access**: Only emails in `ALLOWED_USERS` can access applications
- **Admin Access**: Admin privileges granted if email matches `ADMIN_EMAIL` OR is in `ADMIN_USERS`
- **Access Denial**: Non-whitelisted users are denied access with appropriate error messages
- **Development Mode**: If `WHITELIST_ENABLED=false`, all users are allowed

---

## 🔌 Nginx Setup (Host-Level)

### Standard Configuration
- All reverse proxy configs are stored in `/etc/nginx/sites-available/`
- Enabled via symlinks in `/etc/nginx/sites-enabled/`
- Main Nginx config includes:
  ```nginx
  # /etc/nginx/nginx.conf
  include /etc/nginx/sites-enabled/*;
  ```

### Per-App Configuration
Each app gets:
- **HTTP block**: Listens on port 80, redirects to HTTPS
- **HTTPS block**: Listens on port 443 with app-specific SSL, proxies to `localhost:$APP_PORT`

---

## 📁 Standard Folder Structure

```
/home/jl/apps/
├── <appname>/
│   ├── .env                    # Clean secrets-only configuration
│   ├── docker-compose.yml     # Project-agnostic template (customized by deploy.sh)
│   ├── deploy.sh               # Handles template customization and deployment
│   ├── app/config/__init__.py  # Application defaults and non-secret configuration
│   └── ...
```

**Key Standards:**
- **Smaller .env files**: Only secrets and environment-specific values
- **Identical templates**: All projects use the same `docker-compose.yml` structure
- **Config files**: Non-secret defaults moved to `app/config/__init__.py`
- **Deployment consistency**: Same deployment logic across all projects

---

## 🛠 Standard Deployment Script Features

All PenguinRidge applications use a standardized deployment script with **project-agnostic Docker templates**:

### Core Features
- **Project-Agnostic Templates**: Uses generic `docker-compose.yml` template customized per project
- **Dynamic Customization**: Uses `sed` to replace generic names with project-specific values
- **Port Assignment**: Unique host port, database port, and Redis port automatically set per app
- **Clean .env Generation**: Creates minimal `.env` with secrets only (non-secrets moved to config files)
- **Authentication Setup**: Auto-configures simple auth for all apps, OAuth optional for multi-user apps
- **Git Pull**: Ensures latest code is used with commit tracking
- **Docker Build/Run**: Maps `$APP_PORT:5000` (internal app always runs on port 5000)
- **Database Setup**: Maps `$DB_PORT:5432` for PostgreSQL with project-specific naming
- **Redis Setup**: Maps `$REDIS_PORT:6379` for Redis with project-specific naming (optional)
- **Host-Level Nginx Config**: Created or updated dynamically
- **SSL Setup**: Uses Certbot for HTTPS, falls back to self-signed if needed
- **Health Checks**: Validates health endpoints post-deploy
- **Configuration Validation**: Tests docker-compose validity before deployment
- **Debug Scripts**: Included for logs, static file checks, port probing

### Environment Setup Standards

**New Architecture**: Environment variables are now split between secrets (in `.env`) and configuration defaults (in `app/config/__init__.py`). This keeps `.env` files clean and secure while making non-secret settings visible in code.

#### Standard .env Structure
```bash
# Database Configuration (secrets)
DATABASE_URL=postgresql://app_user:secure_password@db:5432/app_db
DB_NAME=appname_db
DB_USER=appname_user
DB_PASSWORD=secure_password
DB_PORT=543X

# API Keys (secrets)
API_KEY=your-api-key-here

# Basic Authentication Configuration
SECRET_KEY=generated-secret-key
ADMIN_EMAIL=john.laverick@gmail.com
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=admin123

# Optional Whitelisting (if enabled)
WHITELIST_ENABLED=false
ALLOWED_USERS=john.laverick@gmail.com

# Redis Configuration (environment-specific)
REDIS_PASSWORD=generated-redis-password
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
REDIS_PORT=637X

# Docker Environment Variables (deployment-specific)
APP_NAME=appname
APP_PORT=800X
REDIS_ENABLED=true
```

**Non-secret defaults** are in `app/config/__init__.py`:
```python
# Application settings with sensible defaults
DEFAULT_TIMEZONE = os.environ.get('DEFAULT_TIMEZONE', 'UTC')
SESSION_COOKIE_HTTPONLY = os.environ.get('SESSION_COOKIE_HTTPONLY', 'True').lower() == 'true'
```

---

## 🔌 Port Assignment Convention

### Dynamic Port Logic
Each app defines its port using a `case` block in the deployment script:

```bash
case "$APP_NAME" in
  ridgecommand) APP_PORT=8000; DB_PORT=5433; REDIS_PORT=6379 ;;
  fintrack)     APP_PORT=8003; DB_PORT=5434; REDIS_PORT="" ;;
  ridgechat)    APP_PORT=8005; DB_PORT=5435; REDIS_PORT=6381 ;;
  ridgeedge)    APP_PORT=8007; DB_PORT=5436; REDIS_PORT=6380 ;;
  ridgemarkets) APP_PORT=8011; DB_PORT=5437; REDIS_PORT=6382 ;;
  *)            APP_PORT=8010; DB_PORT=5439; REDIS_PORT=6385 ;;
esac
```

### Port Mapping Standards
- **Internal Docker Port**: Always `5000` (Gunicorn or Flask runs on this)
- **External Host Port**: Assigned uniquely via `$APP_PORT`
- **Database Port**: Assigned uniquely via `$DB_PORT`
- **Redis Port**: Assigned uniquely via `$REDIS_PORT` (optional, empty string if not used)
- **Nginx**: Forwards based on subdomain to `http://localhost:$APP_PORT`

---

## 🚀 Deployment Best Practices

### Code Version Control
All PenguinRidge applications implement git commit tracking to ensure deployed code matches the latest repository state:

```bash
# Deploy script ensures latest code
git fetch origin
git reset --hard origin/main
git clean -fd

# Docker build includes commit verification
export GIT_COMMIT=$(git rev-parse --short HEAD)
docker compose build --no-cache --pull --force-rm
```

### Docker Build Process
To ensure latest code is deployed:

1. **Complete cleanup** of existing containers/images
2. **Fresh git pull** from origin/main
3. **No-cache build** with latest commit hash
4. **Verification** that container matches local commit

### Deployment Verification
Each deployment includes automatic verification:

- **Commit Comparison**: Local vs container commit hash
- **Health Check**: Application startup verification
- **Database Migration**: Automatic schema updates
- **SSL Certificate**: Automatic Let's Encrypt renewal

### Enhanced Docker Configuration
All applications include git in their Dockerfile for version tracking:

```dockerfile
# Install git for version tracking
RUN apt-get update && apt-get install -y git

# Track actual git commit in container
RUN echo "$(git rev-parse --short HEAD)" > /app/.git-commit
```

---

## 🔍 Standard Troubleshooting

### Authentication Issues
- **"Access Denied"**: User not in `ALLOWED_USERS` list (if whitelisting enabled)
- **"Login not working"**: Check if user is auto-created on startup
- **"Admin not working"**: Verify username/password match configured credentials
- **"Whitelisting not working"**: Check `WHITELIST_ENABLED` setting in environment

### Deployment Issues
- **"Old code deployed"**: Container not rebuilt with latest commit
  - Solution: Use `docker compose build --no-cache --pull --force-rm`
  - Verify: Check container commit with `docker compose exec web cat /app/.git-commit`

- **"Docker build cache"**: Old image layers being reused
  - Solution: Use `docker system prune -af` before build
  - Use `DOCKER_BUILDKIT=1` for improved build performance

- **"Database migration failed"**: Schema changes not applied
  - Solution: Run `docker compose exec web flask db upgrade`
  - Check: `docker compose exec web flask db current`

- **"SSL certificate expired"**: Let's Encrypt renewal failed
  - Solution: Run `sudo certbot renew --nginx`
  - Check: `sudo certbot certificates`

### Health Check Commands
```bash
# Check application health
curl -sSf https://appname.penguinridge.co.uk/health

# Check container status
docker compose ps

# Check deployed commit
docker compose exec web cat /app/.git-commit

# Check database migration status
docker compose exec web flask db current

# Check Redis connectivity (if Redis is configured)
if [ -n "$REDIS_PORT" ]; then
  docker compose exec redis redis-cli ping
  docker compose exec redis redis-cli info memory
fi

# Check SSL certificate expiry
sudo certbot certificates
```

### 502 Bad Gateway
- Confirm container is running:  
  ```bash
  docker ps --format "table {{.Names}}	{{.Status}}	{{.Ports}}"
  ```
- Confirm container is listening on correct internal port (`5000`)
- Confirm Nginx is proxying to correct external port (`$APP_PORT`)

### Nginx Fails to Reload
- Run: `sudo nginx -t` to validate config
- Restart with: `sudo systemctl reload nginx`
- Inspect logs: `journalctl -xeu nginx`

### App Not Responding
- Check logs:
  ```bash
  docker compose logs -f
  ```
- Try internal curl:
  ```bash
  curl -I http://localhost:$APP_PORT/health
  ```

---

## 🛡 Corporate Best Practices

### General Deployment Best Practices
- Keep deployment idempotent — rerunning the script should never break the app
- Store `.env` files locally, never in Git (now smaller and cleaner)
- Set up crontab backups per app via `backup.sh`
- Each app lives completely in its own folder and Docker namespace
- **Authentication Security**: Use HTTPS for session cookies and secure authentication
- **Access Control**: Use `WHITELIST_ENABLED` to control access (optional)
- **Admin Management**: Use least privilege principle for admin access
- **Database Security**: Use unique database ports and credentials per app
- **Configuration Management**: Use environment variables for secrets, config files for defaults
- **Docker Resource Naming**: Let deployment script handle resource naming for isolation

### New Project Setup
1. **Copy Template**: Use existing project as template
2. **Update Ports**: Add new app to port assignment case block
3. **Customize Environment**: Update app-specific environment variables
4. **Test Deployment**: Run deployment script and verify health checks
5. **Document Features**: Add project-specific features to project guide

---

## 🧪 Standard Validation Commands

- Check Docker ports:  
  `docker ps --format "table {{.Names}}	{{.Ports}}"`

- Nginx reload test:  
  `sudo nginx -t && sudo systemctl reload nginx`

- Health check:  
  `curl -I https://<subdomain>.penguinridge.co.uk/health --insecure`

- Authentication test:  
  ```bash
  # Simple auth apps
  curl -I https://<subdomain>.penguinridge.co.uk/auth/login
  ```

- Access control test:  
  ```bash
  # Simple auth apps
  python -c "import os; print('Whitelist enabled:', os.getenv('WHITELIST_ENABLED', 'false'))"
  python -c "import os; print('Allowed users:', os.getenv('ALLOWED_USERS', 'none'))"
  ```

- Environment configuration test:
  ```bash
  # Check project-agnostic variables
  python -c "import os; print('APP_NAME:', os.getenv('APP_NAME'))"
  python -c "import os; print('APP_PORT:', os.getenv('APP_PORT'))"
  python -c "import os; print('REDIS_PORT:', os.getenv('REDIS_PORT'))"
  python -c "import os; print('DB_NAME:', os.getenv('DB_NAME'))"
  ```

- Database connectivity test:
  `docker compose exec db psql -U $DB_USER -d $DB_NAME -c "SELECT 1;"`

- Redis connectivity test (if Redis is configured):
  ```bash
  if [ -n "$REDIS_PORT" ]; then
    docker compose exec redis redis-cli ping
    docker compose exec redis redis-cli info server
  fi
  ```

---

🎉 **This document provides the shared foundation for all PenguinRidge applications. Each project should reference this for standard practices and create its own project-specific guide for unique features.**
