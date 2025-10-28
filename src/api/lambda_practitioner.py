"""
Lambda Practitioner Assignment API

This module provides endpoints for calling the AWS Lambda function that handles
IntakeQ practitioner assignment using Selenium automation.

Endpoints:
- POST /lambda/assign-practitioner: Trigger Lambda function for practitioner assignment
- GET /lambda/assign-practitioner/status/{request_id}: Check assignment status (if using async)

The Lambda function is called directly from Railway, providing a bridge between
your existing API and the browser automation running in AWS Lambda.
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

# Create Blueprint
lambda_practitioner_bp = Blueprint("lambda_practitioner", __name__)

# AWS Lambda configuration
LAMBDA_FUNCTION_NAME = os.getenv(
    "LAMBDA_FUNCTION_NAME", "intakeq-practitioner-assignment"
)
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def get_lambda_client():
    """Initialize AWS Lambda client with proper credentials"""
    try:
        # AWS credentials should be set via environment variables:
        # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
        return boto3.client("lambda", region_name=AWS_REGION)
    except Exception as e:
        logger.error(f"Failed to create Lambda client: {str(e)}")
        return None


@lambda_practitioner_bp.route("/lambda/assign-practitioner", methods=["POST"])
def assign_practitioner_via_lambda():
    """
    Trigger AWS Lambda function for IntakeQ practitioner assignment

    Request Body:
    {
        "account_type": "insurance" | "cash_pay",
        "client_id": "5781",
        "therapist_full_name": "Catherine Burnett",
        "async": false  // Optional: whether to invoke async (default: false)
    }

    Response:
    {
        "success": true/false,
        "message": "Success/error message",
        "details": {...},
        "lambda_request_id": "uuid"  // If async
    }
    """
    try:
        request_data = request.get_json() or {}

        logger.info("=== LAMBDA PRACTITIONER ASSIGNMENT REQUEST ===")
        logger.info(f"Request data: {json.dumps(request_data, indent=2)}")

        # Validate required fields
        required_fields = ["account_type", "client_id", "therapist_full_name"]
        missing_fields = [
            field for field in required_fields if not request_data.get(field)
        ]

        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            logger.error(f"❌ {error_msg}")
            return jsonify({"success": False, "message": error_msg}), 400

        # Validate account type
        account_type = request_data["account_type"]
        if account_type not in ["cash_pay", "insurance"]:
            error_msg = f"Invalid account_type: {account_type}. Must be 'cash_pay' or 'insurance'"
            logger.error(f"❌ {error_msg}")
            return jsonify({"success": False, "message": error_msg}), 400

        client_id = request_data["client_id"]
        therapist_full_name = request_data["therapist_full_name"]
        is_async = request_data.get("async", False)

        logger.info(
            f"🎯 Assignment target: {client_id} → {therapist_full_name} ({account_type})"
        )
        logger.info(
            f"🔄 Invocation type: {'Asynchronous' if is_async else 'Synchronous'}"
        )

        # Initialize Lambda client
        lambda_client = get_lambda_client()
        if not lambda_client:
            error_msg = "Failed to initialize AWS Lambda client. Check AWS credentials."
            logger.error(f"❌ {error_msg}")
            return jsonify({"success": False, "message": error_msg}), 500

        # Prepare Lambda payload
        lambda_payload = {
            "account_type": account_type,
            "client_id": str(client_id),  # Ensure string type
            "therapist_full_name": therapist_full_name,
        }

        logger.info(f"📤 Invoking Lambda function: {LAMBDA_FUNCTION_NAME}")
        logger.info(f"📦 Payload: {json.dumps(lambda_payload, indent=2)}")

        try:
            # Invoke Lambda function
            if is_async:
                # Asynchronous invocation
                response = lambda_client.invoke(
                    FunctionName=LAMBDA_FUNCTION_NAME,
                    InvocationType="Event",  # Async
                    Payload=json.dumps(lambda_payload),
                )

                request_id = response.get("ResponseMetadata", {}).get(
                    "RequestId", "unknown"
                )
                logger.info(
                    f"✅ Lambda invoked asynchronously. Request ID: {request_id}"
                )

                return jsonify(
                    {
                        "success": True,
                        "message": "Practitioner assignment initiated successfully",
                        "lambda_request_id": request_id,
                        "async": True,
                        "details": {
                            "account_type": account_type,
                            "client_id": client_id,
                            "therapist_full_name": therapist_full_name,
                        },
                    }
                )

            else:
                # Synchronous invocation (default)
                response = lambda_client.invoke(
                    FunctionName=LAMBDA_FUNCTION_NAME,
                    InvocationType="RequestResponse",  # Sync
                    Payload=json.dumps(lambda_payload),
                )

                # Parse Lambda response
                response_payload = response["Payload"].read().decode("utf-8")
                lambda_result = json.loads(response_payload)

                logger.info(f"📥 Lambda response: {json.dumps(lambda_result, indent=2)}")

                # Extract the actual result from Lambda's response body
                if lambda_result.get("statusCode") == 200:
                    actual_result = json.loads(lambda_result["body"])

                    if actual_result["success"]:
                        logger.info(f"✅ Practitioner assignment completed successfully")
                        return jsonify(actual_result), 200
                    else:
                        logger.error(
                            f"❌ Practitioner assignment failed: {actual_result['message']}"
                        )
                        return jsonify(actual_result), 500
                else:
                    # Lambda returned an error
                    error_result = json.loads(lambda_result.get("body", "{}"))
                    logger.error(
                        f"❌ Lambda error: {error_result.get('message', 'Unknown error')}"
                    )
                    return (
                        jsonify(
                            {
                                "success": False,
                                "message": error_result.get(
                                    "message", "Lambda function error"
                                ),
                                "lambda_status_code": lambda_result.get("statusCode"),
                            }
                        ),
                        500,
                    )

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]
            logger.error(f"❌ AWS Lambda ClientError ({error_code}): {error_message}")

            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"AWS Lambda error: {error_message}",
                        "error_code": error_code,
                    }
                ),
                500,
            )

        except NoCredentialsError:
            error_msg = "AWS credentials not found. Please configure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
            logger.error(f"❌ {error_msg}")
            return jsonify({"success": False, "message": error_msg}), 500

    except Exception as e:
        logger.error(f"❌ Unexpected error in Lambda practitioner assignment: {str(e)}")
        import traceback

        traceback.print_exc()

        return (
            jsonify({"success": False, "message": f"Internal server error: {str(e)}"}),
            500,
        )


@lambda_practitioner_bp.route("/lambda/assign-practitioner/test", methods=["GET"])
def test_lambda_connection():
    """
    Test endpoint to verify Lambda connection and configuration

    Returns:
    {
        "success": true/false,
        "message": "Test result",
        "details": {
            "lambda_function_name": "...",
            "aws_region": "...",
            "credentials_available": true/false
        }
    }
    """
    try:
        logger.info("🧪 Testing Lambda connection...")

        # Check Lambda client initialization
        lambda_client = get_lambda_client()
        if not lambda_client:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Failed to initialize AWS Lambda client",
                        "details": {
                            "lambda_function_name": LAMBDA_FUNCTION_NAME,
                            "aws_region": AWS_REGION,
                            "credentials_available": False,
                        },
                    }
                ),
                500,
            )

        # Try to get function information
        try:
            response = lambda_client.get_function(FunctionName=LAMBDA_FUNCTION_NAME)
            function_config = response["Configuration"]

            logger.info(f"✅ Lambda function found: {LAMBDA_FUNCTION_NAME}")

            return jsonify(
                {
                    "success": True,
                    "message": "Lambda connection test successful",
                    "details": {
                        "lambda_function_name": LAMBDA_FUNCTION_NAME,
                        "aws_region": AWS_REGION,
                        "credentials_available": True,
                        "function_runtime": function_config.get("Runtime"),
                        "function_timeout": function_config.get("Timeout"),
                        "function_memory": function_config.get("MemorySize"),
                        "last_modified": function_config.get("LastModified"),
                    },
                }
            )

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]

            if error_code == "ResourceNotFoundException":
                logger.error(f"❌ Lambda function not found: {LAMBDA_FUNCTION_NAME}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Lambda function not found: {LAMBDA_FUNCTION_NAME}",
                            "details": {
                                "lambda_function_name": LAMBDA_FUNCTION_NAME,
                                "aws_region": AWS_REGION,
                                "credentials_available": True,
                                "error_code": error_code,
                            },
                        }
                    ),
                    404,
                )
            else:
                logger.error(f"❌ AWS error ({error_code}): {error_message}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"AWS error: {error_message}",
                            "details": {
                                "lambda_function_name": LAMBDA_FUNCTION_NAME,
                                "aws_region": AWS_REGION,
                                "credentials_available": True,
                                "error_code": error_code,
                            },
                        }
                    ),
                    500,
                )

    except Exception as e:
        logger.error(f"❌ Lambda connection test error: {str(e)}")
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"Test error: {str(e)}",
                    "details": {
                        "lambda_function_name": LAMBDA_FUNCTION_NAME,
                        "aws_region": AWS_REGION,
                        "credentials_available": False,
                    },
                }
            ),
            500,
        )


# Health check endpoint
@lambda_practitioner_bp.route("/lambda/health", methods=["GET"])
def lambda_health_check():
    """Simple health check for the Lambda integration module"""
    return jsonify(
        {
            "status": "healthy",
            "service": "lambda-practitioner-assignment",
            "timestamp": time.time(),
        }
    )


# Legacy compatibility endpoint (maps to your existing function signature)
@lambda_practitioner_bp.route("/legacy/assign-practitioner", methods=["POST"])
def legacy_assign_practitioner():
    """
    Legacy compatibility endpoint that matches your existing assign_practitioner function signature

    Request Body:
    {
        "account_type": "insurance",
        "client_id": "5781",
        "therapist_full_name": "Catherine Burnett"
    }
    """
    # Simply forward to the main Lambda endpoint
    return assign_practitioner_via_lambda()


# For testing - simple wrapper function that matches your existing signature
def assign_practitioner_lambda(
    account_type: str, client_id: str, therapist_full_name: str
) -> Dict[str, Any]:
    """
    Simple wrapper function that matches your existing assign_practitioner signature
    but calls the Lambda function instead of running Selenium locally.

    Args:
        account_type: "cash_pay" or "insurance"
        client_id: IntakeQ Client ID (e.g., "5781")
        therapist_full_name: Full name of therapist (e.g., "Catherine Burnett")

    Returns:
        dict: Result with success status and details
    """
    try:
        lambda_client = get_lambda_client()
        if not lambda_client:
            return {
                "success": False,
                "message": "Failed to initialize AWS Lambda client",
            }

        payload = {
            "account_type": account_type,
            "client_id": str(client_id),
            "therapist_full_name": therapist_full_name,
        }

        response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )

        response_payload = response["Payload"].read().decode("utf-8")
        lambda_result = json.loads(response_payload)

        if lambda_result.get("statusCode") == 200:
            return json.loads(lambda_result["body"])
        else:
            error_result = json.loads(lambda_result.get("body", "{}"))
            return {
                "success": False,
                "message": error_result.get("message", "Lambda function error"),
            }

    except Exception as e:
        return {"success": False, "message": f"Error calling Lambda function: {str(e)}"}
