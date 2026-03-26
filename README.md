# SKFS LoRaWAN Security Lab

SKFS LoRaWAN Security Lab is a Docker-based demo environment for visualizing LoRaWAN-style telemetry and security events. After startup, the system automatically builds the required services, seeds demo data, and exposes a dashboard, a security page, API endpoints, and pgAdmin. No manual scripts are required after the containers are started.

## Setup and run

1. `wsl --update`  
   Updates Windows Subsystem for Linux so Docker Desktop can use an up-to-date WSL backend.

2. `winget install --id Git.Git -e --source winget`  
   Installs Git for Windows from the Windows package manager.

3. `cd "$HOME\Downloads"`  
   Moves PowerShell to the Downloads folder so the project is cloned in an easy-to-find location.

4. `git clone https://github.com/BorisKisyov/LoRa-LoRaWAN-Security-SKFS.git`  
   Downloads the SKFS project from GitHub to your computer.

5. `cd ".\LoRa-LoRaWAN-Security-SKFS"`  
   Opens the project folder so the Docker command runs in the correct directory.

6. `docker compose up --build -d`  
   Builds the images, starts the containers in the background, and launches the full SKFS demo stack.

## Open in browser

- Dashboard: `http://localhost:8081`
- Security page: `http://localhost:8081/security`
- Latest data endpoint: `http://localhost:8000/latest?limit=20`
- Security summary endpoint: `http://localhost:8000/security/summary`
- Raw demo endpoint: `http://localhost:8000/security/raw-demo`
- pgAdmin: `http://localhost:5050`

## Database / pgAdmin credentials

- Email: `admin@skfs.com`
- Password: `admin`

The PostgreSQL server is already preconfigured in pgAdmin as `SKFS DB`.
