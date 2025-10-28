# Railway Selenium Grid Setup

This application has been configured to work with Railway's Selenium Standalone Chrome deployment.

## For Railway Deployment

### Option 1: Deploy Selenium Grid as a Separate Service (Recommended)

1. **Deploy the Selenium Grid Service:**
   - Create a new Railway service
   - Use the Docker image: `selenium/standalone-chrome:latest`
   - Set the following environment variables:
     ```
     SE_OPTS=--log-level INFO
     SE_NODE_MAX_SESSIONS=2
     SE_NODE_OVERRIDE_MAX_SESSIONS=true
     ```
   - The service will automatically expose port 4444

2. **Configure Your Main App:**
   - Set the `SELENIUM_GRID_URL` environment variable to your Selenium service URL:
     ```
     SELENIUM_GRID_URL=https://your-selenium-service.up.railway.app/wd/hub
     ```

### Option 2: Use Railway's One-Click Selenium Template

1. Deploy using Railway's Selenium template from their templates gallery
2. Note the generated URL (e.g., `https://selenium-abc123.up.railway.app`)
3. Set your `SELENIUM_GRID_URL` environment variable to: `https://selenium-abc123.up.railway.app/wd/hub`

## Environment Variables Required

In your main application service, set these environment variables:

```bash
# Selenium Grid URL (set to your deployed Selenium service)
SELENIUM_GRID_URL=https://your-selenium-service.up.railway.app/wd/hub

# IntakeQ Credentials
INSURANCE_INTAKEQ_USR=your_insurance_username
INSURANCE_INTAKEQ_PAS=your_insurance_password
CASH_PAY_INTAKEQ_USR=your_cashpay_username
CASH_PAY_INTAKEQ_PAS=your_cashpay_password

# Railway Environment (automatically set by Railway)
RAILWAY_ENVIRONMENT=production
```

## Testing

Once deployed, you can test the Selenium integration by calling any of your IntakeQ automation endpoints. The application will automatically:

1. Connect to the Remote Selenium Grid
2. Execute browser automation in the cloud
3. Return results without needing local Chrome installation

## Local Development

For local development, the application will fall back to using local Chrome if the Selenium Grid is not available. You can also run the full stack locally with Docker Compose:

```bash
docker-compose up
```

This will start:
- PostgreSQL database
- Redis cache
- DynamoDB Local
- Selenium Standalone Chrome Grid
- Your main application

## Debugging

- Selenium Grid health check: `GET https://your-selenium-service.up.railway.app/wd/hub/status`
- VNC access (if enabled): `https://your-selenium-service.up.railway.app:7900` (password: `secret`)
- Application health: `GET https://your-app.up.railway.app/health`

## Benefits of This Setup

1. **No Chrome Dependencies**: Your main app container is much smaller
2. **Scalability**: Selenium grid can scale independently
3. **SSL/TLS**: Railway provides HTTPS by default
4. **Reliability**: Dedicated Selenium resources
5. **Cost-Effective**: Only pay for what you use
