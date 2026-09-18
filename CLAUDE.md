# Folder Location
Billing Backend=C:\dev\billing-backend
Billing Frontend=C:\dev\billing-frontend
Minty=C:\dev\Minty
Onboarding=C:\dev\onboarding
Onboarding Backend=C:\dev\onboarding-backend
Minty Landing Page=C:\dev\daily-minty-landing-page

# Development Guidelines
Stack
Frontend: Next.js, React, TypeScript
Backend: Django and Flask, Python
OS: Windows
<!-- GPU: NVIDIA RTX 2050 -->
Development environment: VS Code

# Resource Utilization
Use available system resources efficiently to maximize development and testing speed.
# CPU
Use multiple CPU cores when tasks can safely run in parallel.
Run independent builds, tests, linting, and type checking concurrently when possible.
Avoid unnecessary serialization of independent tasks.
Prefer incremental builds and caching.
# RAM
Make effective use of available RAM for development servers, builds, testing, and tooling.
Keep required Next.js, Django, Flask, and database services running concurrently when useful.
Avoid unnecessary memory duplication.
Reduce concurrency if memory pressure affects system stability.
# GPU
<!-- The system has an NVIDIA RTX 2050. -->
Do not force GPU usage for normal Next.js, Django, Flask, TypeScript, or database operations.
When Python workloads support CUDA, use the RTX 2050 when beneficial.
Detect CUDA availability automatically.
Monitor VRAM usage and avoid GPU out-of-memory errors.
Prefer CPU fallback when GPU acceleration is unsupported or slower.
# Development Workflow
Inspect docs folder
Inspect the existing project before making changes.
Reuse existing dependencies, caches, virtual environments, and development servers.
Run independent tasks concurrently when safe.
Do not run concurrent tasks that conflict over files, ports, databases, or shared state.
Use the fastest appropriate development and build commands.
Avoid unnecessary dependency reinstalls or full rebuilds.
Prefer incremental builds and hot reload during development.
# Next.js
Use the development server and Fast Refresh during development.
Use TypeScript and ESLint checks when appropriate.
Avoid unnecessary production builds during development.
Reuse the existing package manager and lockfile.
# Django
Use the project’s existing Python virtual environment.
Use Django’s development server during development.
Run relevant Django tests after backend changes.
Avoid unnecessary database resets.
Run migrations deliberately and verify their results.
# Flask
Use the project’s existing Python virtual environment.
Use Flask development/reload mode when appropriate.
Run relevant Flask tests after backend changes.
Verify affected API endpoints after changes.
# Python
Use the project’s existing virtual environment.
Use python -m pip for package management.
Use multiprocessing for CPU-heavy workloads when appropriate.
Use asynchronous or concurrent execution for I/O-heavy workloads when appropriate.
Do not introduce parallelism solely to increase CPU utilization.
# Testing
After making changes:
Run relevant frontend checks.
Run relevant backend checks.
Run linting and type checking where applicable.
Test affected API endpoints.
Test affected frontend functionality.
Run independent checks concurrently when safe.
Fix failures rather than ignoring them.
Re-run relevant tests after fixes.
# Claude Code Behavior
Inspect the project before making changes.
Understand the existing architecture before modifying it.
Identify independent tasks and perform them concurrently when safe.
Prefer efficient commands and existing tooling.
Avoid unnecessary file changes.
Avoid unnecessary dependency installations.
Avoid unnecessary rebuilds.
Ask if there are changes in the schema.
Verify changes rather than assuming they work.
# Resource Priority
When performing a task, optimize for:
Fast development feedback
Fast builds and tests
Reliable results
Efficient CPU and RAM usage
GPU acceleration when genuinely beneficial
Keeping the system responsive
Do not blindly target 100% CPU, RAM, or GPU utilization.
Use the available hardware aggressively when it improves performance, but avoid wasting resources when they provide no benefit.