# Sol Health Backend

Flask-based backend API for Sol Health's therapist matching and appointment booking platform. This service integrates with IntakeQ, Airtable, Google Calendar, and insurance verification services to provide a complete client onboarding and scheduling solution.

## Overview

Sol Health Backend powers the end-to-end client journey:
- Client intake form collection via IntakeQ
- Insurance verification through Nirvana API
- Intelligent therapist matching based on availability, specialties, and insurance
- Automated appointment scheduling with Google Calendar integration
- Progressive data tracking and analytics throughout the client journey

## Tech Stack

- **Framework**: Flask with Blueprints
- **Database**: PostgreSQL (Railway)
- **Cache**: Redis (optional)
- **Integrations**:
  - IntakeQ (forms and client management)
  - Airtable (therapist database)
  - Google Calendar (availability and scheduling)
  - Nirvana (insurance verification)
  - AWS S3 (media storage)
- **Deployment**: Railway / AWS Lambda
- **Testing**: pytest
- **Code Quality**: ruff, mypy, pre-commit hooks

## Architecture

```
src/
├── api/                      # Flask API endpoints
│   ├── clients.py           # Client signup & management
│   ├── therapists.py        # Therapist matching & search
│   ├── appointments.py      # Appointment booking
│   ├── availability.py      # Availability queries
│   ├── intakeq_forms.py     # IntakeQ form handling
│   ├── tracking.py          # Analytics & tracking
│   ├── nirvana_callback.py  # Insurance verification callbacks
│   └── railway_practitioner.py  # Practitioner assignment
├── services/                # Business logic services
│   ├── airtable_sync_service.py
│   ├── google_sheets_progressive_logger.py
│   ├── cache_service.py
│   ├── data_flow_integration.py
│   └── scheduler.py
├── utils/                   # Utilities
│   ├── google/              # Google Calendar integration
│   ├── intakeq/             # IntakeQ utilities
│   ├── insurance_mapping.py
│   └── progressive_data_capture.py
├── db/                      # Database models & connection
└── config.py               # Configuration management
```

## Setup

### 1. Prerequisites
- Python 3.9+
- PostgreSQL
- Redis (optional, for caching)

### 2. Installation

```bash
# Clone the repository
git clone <repository-url>
cd solHealthBackend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies (optional)
pip install -r dev-requirements.txt
```

### 3. Environment Configuration

Create a `.env` file in the root directory:

```bash
# Environment
ENV=dev  # dev, test, or prod

# Database (Railway PostgreSQL)
DATABASE_URL=postgresql://user:password@host:5432/database
# Or use individual variables:
PGHOST=
PGPORT=5432
PGUSER=
PGPASSWORD=
PGDATABASE=

# Security
SECRET_KEY=your-secret-key
JWT_SECRET_KEY=your-jwt-secret

# Airtable (Required)
AIRTABLE_API_KEY=
AIRTABLE_BASE_ID=
AIRTABLE_TABLE_ID=Therapists

# IntakeQ
CASH_PAY_INTAKEQ_API_KEY=
INSURANCE_INTAKEQ_API_KEY=
INTAKEQ_BASE_URL=https://intakeq.com/api/v1
CASH_PAY_MANDATORY_FORM_ID=
INSURANCE_MANDATORY_FORM_ID=

# Insurance Verification
NIRVANA_API_KEY=
NIRVANA_API_URL=https://coverage-api-sandbox.meetnirvana.com/v1

# Google Calendar Integration
GOOGLE_SHEETS_ID=
GOOGLE_SHEETS_CREDENTIALS=

# AWS S3 (Optional - for therapist media)
AWS_REGION=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
S3_BUCKET_NAME=

# Redis Cache (Optional)
REDIS_URL=redis://localhost:6379
REDIS_HOST=localhost
REDIS_PORT=6379

# CORS
CORS_ORIGINS=http://localhost:3000,https://app.solhealth.co

# Feature Flags
ENABLE_INSURANCE_VERIFICATION=true
ENABLE_ANALYTICS=false
ENABLE_SENTRY=false
SYNC_ON_STARTUP=true
```

### 4. Database Setup

```bash
# Initialize the database
python -c "from src.db import init_db; init_db()"

# Run migrations (if using Alembic)
alembic upgrade head
```

### 5. Run the Application

```bash
# Development mode
python run.py

# Production mode (with Gunicorn)
gunicorn app:app --bind 0.0.0.0:8080 --workers 4
```

The API will be available at `http://localhost:8080`

## API Endpoints

### Core Endpoints

#### Client Management
- `POST /clients_signup` - Create new client signup
- `GET /clients_signup` - Get all client signups
- `PATCH /clients_signup/<id>` - Update client signup

#### Therapist Matching
- `POST /therapists/match` - Match clients with therapists
- `GET /therapists/slots` - Get available appointment slots
- `GET /therapists/programs` - Get therapist programs (debug)
- `GET /therapists/<email>/availability/daily` - Get daily availability

#### Appointments
- `POST /appointments` - Create appointment
- `GET /appointments` - List appointments

#### IntakeQ Integration
- `POST /intakeq/create-client` - Create IntakeQ client
- `GET /intakeq/client` - Get client information
- `POST /intakeq_forms/mandatory_form` - Submit mandatory forms

#### Practitioner Assignment
- `POST /railway/assign-practitioner` - Assign practitioner (Railway)
- `GET /railway/health` - Health check
- `POST /lambda/assign-practitioner` - Assign practitioner (AWS Lambda)
- `GET /lambda/health` - Lambda health check

#### Insurance Verification
- `POST /nirvana/verified` - Handle verified insurance callback
- `POST /nirvana/failed` - Handle failed insurance callback

#### Analytics & Tracking
- `POST /track-dropout` - Track user dropouts
- `POST /track-completion` - Track completions
- `POST /track-interaction` - Track user interactions
- `POST /track-booking-context` - Track booking context
- `GET /journey-analytics` - Get journey analytics
- `GET /journey-summary/<response_id>` - Get user journey summary

## Key Features

### 1. Centralized Data Management
See [CENTRALIZED_DATA_MANAGEMENT.md](./CENTRALIZED_DATA_MANAGEMENT.md) for details on the progressive data capture system that ensures all user data flows properly through all services.

### 2. Intelligent Therapist Matching
- Specialty-based matching
- Insurance network filtering
- Availability-aware scheduling
- Program compatibility checking

### 3. Progressive Logging
Comprehensive Google Sheets integration for tracking client journeys through all stages of the onboarding process.

### 4. Insurance Verification
Integration with Nirvana API for real-time insurance verification and eligibility checking.

### 5. Automated Scheduling
Google Calendar integration for:
- Real-time availability checking
- Automated appointment creation
- Conflict detection
- Multi-therapist coordination

## Deployment

### Railway Deployment

The application is configured for Railway deployment with:
- Automatic PostgreSQL provisioning
- Environment variable management
- Built-in health checks
- See [railway.json](./railway.json) for configuration

### AWS Lambda Deployment

For serverless deployment:
- See [LAMBDA_DEPLOYMENT.md](./LAMBDA_DEPLOYMENT.md)
- Lambda function code in `src/api/lambda_practitioner.py`

### Selenium Bot Setup

For automated IntakeQ form handling:
- See [RAILWAY_SELENIUM_SETUP.md](./RAILWAY_SELENIUM_SETUP.md)
- Bot implementation in `intakeq_selenium_bot.py`

## Development

### Code Quality

```bash
# Run linting
ruff check .

# Run type checking
mypy .

# Run pre-commit hooks
pre-commit run --all-files
```

### Testing

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

## Project Structure

- `app.py` - Main Flask application entry point
- `run.py` - Development server runner
- `src/` - Application source code
- `migrations/` - Alembic database migrations
- `Dockerfile` - Container configuration
- `docker-compose.yml` - Local development stack
- `Procfile` - Railway/Heroku deployment config
- `Makefile` - Development commands

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and linters
4. Submit a pull request

## License

Proprietary - Sol Health

## Support

For issues or questions, contact the development team.
