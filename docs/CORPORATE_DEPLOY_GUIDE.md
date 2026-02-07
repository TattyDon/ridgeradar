
# 🐧 CORPORATE_DEPLOYMENT_GUIDE.md  
## PenguinRidge – Multi-App Server Deployment Reference

This document provides an overview of PenguinRidge's deployment architecture and references to detailed documentation.

## 📚 Documentation Structure

This corporate deployment guide is now split into focused documents:

### 🏢 [CORPORATE_STANDARDS.md](./CORPORATE_STANDARDS.md)
**Corporate shared standards and best practices** used across all PenguinRidge applications:
- Core infrastructure standards
- Authentication patterns
- Nginx configuration
- Standard deployment scripts
- Port assignment conventions
- Troubleshooting procedures
- Corporate best practices

### 🐧 [RIDGEEDGE_DEPLOYMENT.md](./RIDGEEDGE_DEPLOYMENT.md)
**RidgeEdge-specific deployment details** and project features:
- RidgeEdge application configuration
- Health endpoints and monitoring
- Docker service architecture
- Paper trading mode
- Background task processing
- Project-specific troubleshooting

---

## 🧩 Current Applications Overview

| App Name       | Subdomain                             | Internal Docker Port | External Host Port | Database Port | Redis Port | Health Check | Authentication | Version Tracking | Notes                         |
|----------------|---------------------------------------|-----------------------|---------------------|---------------|------------|---------------|----------------|------------------|-------------------------------|
| RidgeCommand   | https://ridgecommand.penguinridge.co.uk | 5000                  | 8000                | 5433          | 6379        | `/health`     | Simple Auth   | Git commit in container | Redis exposed for caching     |
| RidgeFlow       | https://fintrack.penguinridge.co.uk     | 5000                  | 8003                | 5434          | *(none)*    | `/health`     | Simple Auth   | Git commit in container | No Redis required             |
| RidgeChat      | https://ridgechat.penguinridge.co.uk     | 5000                  | 8005                | 5435          | 6381        | `/health`     | Simple Auth   | Git commit in container | Redis used for chat sessions |
| RidgeEdge      | https://ridgeedge.penguinridge.co.uk     | 5000                  | 8007                | 5436          | 6380        | `/health`, `/api/health`, `/admin/health` | Username Auth | Git commit in container | Redis + Celery workers, Paper trading |
| RidgeMarkets   | https://ridgemarkets.penguinridge.co.uk  | 5000                  | 8011                | 5437          | 6382        | `/health`     | Username Auth | Git commit in container | Redis + Celery workers, Paper + Real betting |

---

## 🚀 Quick Start

### For New Projects
1. **Review Standards**: Read [CORPORATE_STANDARDS.md](./CORPORATE_STANDARDS.md) for shared practices
2. **Copy Template**: Use existing project as template
3. **Update Ports**: Add new app to port assignment case block
4. **Customize Environment**: Update app-specific environment variables
5. **Test Deployment**: Run deployment script and verify health checks

### For RidgeEdge
1. **Read Project Guide**: See [RIDGEEDGE_DEPLOYMENT.md](./RIDGEEDGE_DEPLOYMENT.md) for specific details
2. **Follow Standards**: Apply corporate standards from [CORPORATE_STANDARDS.md](./CORPORATE_STANDARDS.md)
3. **Deploy**: Use standard deployment process with RidgeEdge-specific configuration

---

## 🔐 Authentication Overview

**🔐 Authentication Standard**: PenguinRidge applications use different authentication methods. RidgeEdge uses **username-based authentication**, while other apps may use **Google OAuth** for authentication with email-based access control.

---

## 📚 Documentation References

### Corporate Standards
- **[CORPORATE_STANDARDS.md](./CORPORATE_STANDARDS.md)**: Shared deployment patterns, authentication standards, and best practices
- **[PRODUCTION_TROUBLESHOOTING.md](./PRODUCTION_TROUBLESHOOTING.md)**: Common troubleshooting procedures
- **[USEFUL_COMMANDS.MD](./USEFUL_COMMANDS.MD)**: Quick reference commands

### Project-Specific Guides
- **[RIDGEEDGE_DEPLOYMENT.md](./RIDGEEDGE_DEPLOYMENT.md)**: RidgeEdge-specific deployment and features
- **[PAPER_TRADING.md](./PAPER_TRADING.md)**: Paper trading mode documentation
- **[API_DOCUMENTATION.md](./API_DOCUMENTATION.md)**: API endpoints and usage

---

## 🎯 Next Steps

1. **For New Projects**: Follow the [CORPORATE_STANDARDS.md](./CORPORATE_STANDARDS.md) for setup
2. **For RidgeEdge**: Use [RIDGEEDGE_DEPLOYMENT.md](./RIDGEEDGE_DEPLOYMENT.md) for specific details
3. **For Troubleshooting**: Check [PRODUCTION_TROUBLESHOOTING.md](./PRODUCTION_TROUBLESHOOTING.md)
4. **For Commands**: Reference [USEFUL_COMMANDS.MD](./USEFUL_COMMANDS.MD)

---

🎉 **This modular documentation structure provides clear separation between corporate standards and project-specific details, making it easier to maintain and scale across multiple PenguinRidge applications.**

---

## ✅ RidgeMarkets Deployment Checklist

**Subdomain**: `ridgemarkets.penguinridge.co.uk`  
**Ports**: web `8011`, db `5437`, redis `6382`  
**Health**: `/health`

1. **DNS**: Add A record for `ridgemarkets.penguinridge.co.uk` to server IP
2. **Repo**: Clone to `/home/jl/apps/ridgemarkets`
3. **Env**: Populate `.env` with API keys, Betfair creds, and `SECRET_KEY`
4. **Compose**: Use `docker-compose.prod.yml` with `8011:5000`, `5437:5432`, `6382:6379`
5. **Deploy**: `docker-compose -f docker-compose.prod.yml up -d --build`
6. **Migrate**: `docker-compose -f docker-compose.prod.yml exec web flask db upgrade`
7. **Nginx**: Add vhost proxy to `http://127.0.0.1:8011`
8. **SSL**: `certbot --nginx -d ridgemarkets.penguinridge.co.uk`
9. **Verify**: `https://ridgemarkets.penguinridge.co.uk/health`
