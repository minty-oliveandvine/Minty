# Petty Cash Management System

A Flask-based web application for managing petty cash transactions and expenses.

## 🌐 Live Deployments

| Environment | URL | Branch |
|-------------|-----|--------|
| **Production** | https://pettycash-oliveandvinehk.onrender.com | `main` |
| **Staging** | https://staging-pettycash-oliveandvinehk.onrender.com | `staging` |
| **Development** | https://dev-pettycash-oliveandvinehk.onrender.com | `dev` |

## 📁 Repository Structure

- **Main Branch**: [https://github.com/ovbenjie/pettycashv2/tree/main](https://github.com/ovbenjie/pettycashv2/tree/main)
- **Staging Branch**: [https://github.com/ovbenjie/pettycashv2/tree/staging](https://github.com/ovbenjie/pettycashv2/tree/staging)
- **Development Branch**: [https://github.com/ovbenjie/pettycashv2/tree/dev](https://github.com/ovbenjie/pettycashv2/tree/dev)

## 🐳 Running with Docker (recommended)

Docker runs the app **and** a PostgreSQL database in isolated containers, so you
don't need to install Python or Postgres locally. Everyone on the team gets an
identical environment from one command.

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac/Windows/Linux)
- Git

No Docker Hub account is required — the image is built locally from this repo.

### First-time setup

1. **Clone and enter the repo**
   ```bash
   git clone https://github.com/ovbenjie/pettycashv2.git
   cd pettycashv2
   ```

2. **Create your local env file**
   ```bash
   cp .env.example .env
   ```

3. **Start everything**
   ```bash
   cd docker
   docker compose up --build
   ```
   This builds the app image, starts Postgres, waits for the DB, runs migrations,
   then serves the app. Code changes reload automatically (dev override), so you
   normally won't need `--build` again unless dependencies change.

4. **Open the app** → http://localhost:5001

> All commands below assume you are in the `docker/` directory. The dev override
> (`docker-compose.override.yml`) is applied automatically when you run compose
> from there, giving you live code-reloading.

### Common commands (run from `docker/`)

| Task | Command |
|------|---------|
| Start (foreground, see logs) | `docker compose up` |
| Start in background | `docker compose up -d` |
| Rebuild after dependency changes | `docker compose up --build` |
| Stop containers | `docker compose down` |
| Stop **and wipe the database** | `docker compose down -v` |
| View app logs | `docker compose logs -f app` |
| Open a shell in the app container | `docker compose exec app sh` |
| Run a migration manually | `docker compose exec app flask --app main.py db upgrade` |

If you prefer running compose from the project root instead of `cd docker`, pass
both files explicitly so the dev override still applies:
```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.override.yml up --build
```

---

## 🚀 Local Development Setup (without Docker)

### Prerequisites
- Python 3.11.9
- Git

### Installation & Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/ovbenjie/pettycashv2.git
   cd pettycashv2
   ```

2. **⚠️ IMPORTANT: Switch to dev branch**
   ```bash
   git checkout dev
   ```

3. **Create virtual environment**
   ```bash
   python -m venv .venv
   ```

4. **Activate virtual environment**
   
   **Linux/Mac:**
   ```bash
   . .venv/scripts/activate
   ```
   source .venv/bin/activate
   
   **Windows:**
   ```powershell
   .venv\Scripts\Activate.ps1
   ```

5. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

6. **Run the application**
   ```bash
   flask run --host=localhost --port=5001 --debug
   ```
flask run --host=localhost --port=500x --debug

7. **Access the application**
   - Local: http://localhost:5001
   - Or use the dev deployment: https://dev-pettycash-oliveandvinehk.onrender.com

## 🔧 Development Workflow

### Branch Strategy
- `main` - Production-ready code
- `staging` - Pre-production testing
- `dev` - Active development

### Important Notes
- **Always work on the `dev` branch** when developing new features
- Test changes on the dev environment before promoting to staging
- Ensure all tests pass before merging to main

## 📋 Environment Configuration

Each environment runs on its respective branch:
- Production deploys from `main`
- Staging deploys from `staging` 
- Development deploys from `dev`

## 🤝 Contributing

1. Ensure you're on the `dev` branch
2. Create a feature branch from `dev`
3. Make your changes
4. Test locally
5. Submit a pull request to `dev`

## 📞 Support

For issues or questions, please contact the development team or create an issue in the GitHub repository.

---

**Remember**: Always switch to the `dev` branch before starting development!
