# AWS Lambda Deployment Guide for IntakeQ Selenium Automation

This guide shows you how to deploy the IntakeQ practitioner assignment function to AWS Lambda, enabling your Railway app to call browser automation without running Selenium locally.

## 🏗️ Architecture Overview

```
Railway App (API) → AWS Lambda (Selenium) → IntakeQ Website
```

- **Railway**: Your existing Flask app with new `/lambda/assign-practitioner` endpoint
- **AWS Lambda**: Runs headless Chrome with Selenium for IntakeQ automation
- **IntakeQ**: Target website for practitioner assignment

---

## 📋 Prerequisites

1. **AWS Account** with access to Lambda, IAM
2. **AWS CLI** installed and configured
3. **Chrome Layer** for Lambda (see Chrome Setup section)

---

## 🚀 Quick Setup

### Step 1: Install AWS CLI

```bash
# macOS
brew install awscli

# Configure with your AWS credentials
aws configure
```

Enter:
- AWS Access Key ID
- AWS Secret Access Key
- Default region: `us-east-1`
- Default output format: `json`

### Step 2: Create IAM Role for Lambda

```bash
# Create trust policy
cat > lambda-trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create the role
aws iam create-role \
  --role-name lambda-execution-role \
  --assume-role-policy-document file://lambda-trust-policy.json

# Attach basic Lambda execution policy
aws iam attach-role-policy \
  --role-name lambda-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

### Step 3: Set Up Chrome Layer

AWS Lambda needs Chrome and ChromeDriver. Use this pre-built layer:

```bash
# Create layer (one-time setup)
wget https://github.com/shelfio/chrome-aws-lambda-layer/releases/download/v1.0.0/chrome-aws-lambda-layer.zip
aws lambda publish-layer-version \
  --layer-name chrome-layer \
  --zip-file fileb://chrome-aws-lambda-layer.zip \
  --compatible-runtimes python3.11
```

Note the `LayerVersionArn` from the output - you'll need it for deployment.

### Step 4: Deploy Lambda Function

```bash
cd lambda_function/

# Build deployment package
make build

# Deploy (replace YOUR_ACCOUNT_ID with your AWS account ID)
aws lambda create-function \
  --function-name intakeq-practitioner-assignment \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/lambda-execution-role \
  --handler lambda_intakeq_assignment.lambda_handler \
  --zip-file fileb://lambda-deployment.zip \
  --timeout 300 \
  --memory-size 1024 \
  --layers arn:aws:lambda:us-east-1:YOUR_ACCOUNT_ID:layer:chrome-layer:1
```

### Step 5: Set Environment Variables

```bash
aws lambda update-function-configuration \
  --function-name intakeq-practitioner-assignment \
  --environment Variables='{
    "INSURANCE_INTAKEQ_USR":"your_insurance_username",
    "INSURANCE_INTAKEQ_PAS":"your_insurance_password",
    "CASH_PAY_INTAKEQ_USR":"your_cash_pay_username",
    "CASH_PAY_INTAKEQ_PAS":"your_cash_pay_password"
  }'
```

---

## 🔧 Railway Configuration

### Environment Variables for Railway

Add these to your Railway environment:

```bash
# AWS Credentials for Lambda calls
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key
AWS_REGION=us-east-1

# Lambda function name
LAMBDA_FUNCTION_NAME=intakeq-practitioner-assignment
```

### Test the Integration

After deployment, test the endpoint:

```bash
# Test Lambda connection
curl https://your-railway-app.com/lambda/assign-practitioner/test

# Test practitioner assignment
curl -X POST https://your-railway-app.com/lambda/assign-practitioner \
  -H "Content-Type: application/json" \
  -d '{
    "account_type": "insurance",
    "client_id": "5781",
    "therapist_full_name": "Catherine Burnett"
  }'
```

---

## 📝 Usage Examples

### From Python Code

```python
# Replace your existing assign_practitioner calls
from src.api.lambda_practitioner import assign_practitioner_lambda

# Old way (won't work in Railway)
# success = assign_practitioner("insurance", "5781", "Catherine Burnett")

# New way (works in Railway via Lambda)
result = assign_practitioner_lambda("insurance", "5781", "Catherine Burnett")
if result["success"]:
    print(f"✅ Assignment successful: {result['message']}")
else:
    print(f"❌ Assignment failed: {result['message']}")
```

### Via HTTP API

```javascript
// From your frontend or other services
const response = await fetch('/lambda/assign-practitioner', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    account_type: 'insurance',
    client_id: '5781',
    therapist_full_name: 'Catherine Burnett'
  })
});

const result = await response.json();
console.log(result.success ? '✅ Success' : '❌ Failed', result.message);
```

---

## 🔍 Troubleshooting

### Common Issues

#### 1. Chrome Layer Issues
```bash
# Error: Chrome binary not found
# Solution: Ensure Chrome layer is properly attached
aws lambda get-function --function-name intakeq-practitioner-assignment
```

#### 2. Timeout Errors
```bash
# Increase timeout (max 15 minutes)
aws lambda update-function-configuration \
  --function-name intakeq-practitioner-assignment \
  --timeout 900
```

#### 3. Memory Issues
```bash
# Increase memory (affects CPU allocation)
aws lambda update-function-configuration \
  --function-name intakeq-practitioner-assignment \
  --memory-size 2048
```

#### 4. Environment Variable Issues
```bash
# Check environment variables
aws lambda get-function-configuration \
  --function-name intakeq-practitioner-assignment
```

### Debug Endpoints

Your Railway app includes debug endpoints:

- `GET /lambda/assign-practitioner/test` - Test Lambda connection
- `GET /lambda/health` - Health check
- `GET /debug/routes` - List all endpoints

### CloudWatch Logs

Monitor Lambda execution:

1. Go to AWS CloudWatch Console
2. Navigate to Log Groups
3. Find `/aws/lambda/intakeq-practitioner-assignment`
4. View real-time logs during execution

---

## 💰 Cost Estimation

AWS Lambda pricing (as of 2024):
- **Free tier**: 1M requests + 400,000 GB-seconds per month
- **After free tier**: $0.0000166667 per GB-second

Estimated costs for IntakeQ automation:
- Memory: 1024MB (1GB)
- Duration: ~30-60 seconds per assignment
- Monthly volume: 1000 assignments

**Monthly cost**: ~$1-2 (well within free tier limits)

---

## 🔄 Updates and Maintenance

### Updating the Lambda Function

```bash
cd lambda_function/
make build
aws lambda update-function-code \
  --function-name intakeq-practitioner-assignment \
  --zip-file fileb://lambda-deployment.zip
```

### Monitoring

Set up CloudWatch alarms:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "IntakeQ-Lambda-Errors" \
  --alarm-description "Alert on Lambda errors" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --dimensions Name=FunctionName,Value=intakeq-practitioner-assignment \
  --evaluation-periods 1
```

---

## 🔐 Security Best Practices

1. **Least Privilege IAM**: Only grant necessary permissions
2. **Environment Variables**: Never hardcode credentials
3. **VPC Configuration**: Consider running in VPC for additional isolation
4. **Encryption**: Enable encryption at rest for environment variables

```bash
# Enable encryption for environment variables
aws lambda update-function-configuration \
  --function-name intakeq-practitioner-assignment \
  --kms-key-arn arn:aws:kms:us-east-1:YOUR_ACCOUNT_ID:key/YOUR_KMS_KEY
```

---

## 📞 Support

If you encounter issues:

1. **Check CloudWatch logs** for detailed error messages
2. **Test locally** using the debug script: `python debug_selenium.py`
3. **Verify credentials** are set correctly in both Lambda and Railway
4. **Check IntakeQ website** for UI changes that might break selectors

---

## ✅ Verification Checklist

- [ ] AWS CLI configured with valid credentials
- [ ] Lambda function deployed successfully
- [ ] Chrome layer attached to function
- [ ] Environment variables set in Lambda
- [ ] AWS credentials set in Railway
- [ ] Test endpoint returns success
- [ ] CloudWatch logs are accessible
- [ ] Cost monitoring alerts configured

---

## 🎯 Where to Insert This in Your Code

### Replace existing assign_practitioner calls:

**File: `intakeq_integration.py:44`**
```python
# OLD (won't work in Railway):
success = assign_intakeq_practitioner(
    account_type=account_type,
    client_email=client_email,  # ❌ This was wrong anyway
    practitioner_name=practitioner_name,
    headless=headless
)

# NEW (works in Railway via Lambda):
from src.api.lambda_practitioner import assign_practitioner_lambda

result = assign_practitioner_lambda(
    account_type=account_type,
    client_id=client_id,  # ✅ Fixed parameter name
    therapist_full_name=practitioner_name
)
success = result["success"]
```

### Or use the HTTP endpoint directly:

```python
import requests

response = requests.post(f"{your_railway_url}/lambda/assign-practitioner",
    json={
        "account_type": account_type,
        "client_id": client_id,
        "therapist_full_name": practitioner_name
    }
)
result = response.json()
success = result["success"]
```

This Lambda solution will work perfectly with your Railway deployment! 🚀
