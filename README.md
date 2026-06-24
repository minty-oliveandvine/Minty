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

## 🚀 Local Development Setup

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
