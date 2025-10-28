# src/config_aws.py
"""
AWS-specific configuration handler for production deployment.
Retrieves secrets from AWS Secrets Manager or Systems Manager Parameter Store.
"""
import json
import logging
import os
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class AWSConfigManager:
    """Manages configuration retrieval from AWS services."""

    def __init__(self):
        """Initialize AWS clients."""
        self.is_aws = os.getenv("IS_AWS", "false").lower() == "true"
        self.region = os.getenv("AWS_REGION", "us-east-1")

        if self.is_aws:
            self.secrets_client = boto3.client(
                "secretsmanager", region_name=self.region
            )
            self.ssm_client = boto3.client("ssm", region_name=self.region)
            logger.info(f"AWS Config Manager initialized in region {self.region}")
        else:
            logger.info("Running in local mode - using .env file")

    def get_secret(self, secret_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve secret from AWS Secrets Manager.

        Args:
            secret_name: Name of the secret in AWS Secrets Manager

        Returns:
            Secret value as dictionary or None if not found
        """
        if not self.is_aws:
            return None

        try:
            response = self.secrets_client.get_secret_value(SecretId=secret_name)

            if "SecretString" in response:
                return json.loads(response["SecretString"])
            else:
                # Binary secret
                return {"value": response["SecretBinary"]}

        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.warning(f"Secret {secret_name} not found")
            else:
                logger.error(f"Error retrieving secret {secret_name}: {str(e)}")
            return None

    def get_parameter(self, parameter_name: str, decrypt: bool = True) -> Optional[str]:
        """
        Retrieve parameter from AWS Systems Manager Parameter Store.

        Args:
            parameter_name: Name of the parameter
            decrypt: Whether to decrypt SecureString parameters

        Returns:
            Parameter value or None if not found
        """
        if not self.is_aws:
            return None

        try:
            response = self.ssm_client.get_parameter(
                Name=parameter_name, WithDecryption=decrypt
            )
            return response["Parameter"]["Value"]

        except ClientError as e:
            if e.response["Error"]["Code"] == "ParameterNotFound":
                logger.warning(f"Parameter {parameter_name} not found")
            else:
                logger.error(f"Error retrieving parameter {parameter_name}: {str(e)}")
            return None

    def get_airtable_config(self) -> Dict[str, str]:
        """
        Get Airtable configuration from AWS or environment.

        Returns:
            Dictionary with Airtable configuration
        """
        config = {}

        if self.is_aws:
            # Try to get from Secrets Manager first
            airtable_secret = self.get_secret("solhealth/airtable")
            if airtable_secret:
                config["AIRTABLE_API_KEY"] = airtable_secret.get("api_key", "")
                config["AIRTABLE_BASE_ID"] = airtable_secret.get("base_id", "")
                config["AIRTABLE_TABLE_ID"] = airtable_secret.get(
                    "table_id", "Therapists"
                )
                logger.info("Airtable config loaded from AWS Secrets Manager")
            else:
                # Fall back to Parameter Store
                config["AIRTABLE_API_KEY"] = (
                    self.get_parameter("/solhealth/airtable/api_key") or ""
                )
                config["AIRTABLE_BASE_ID"] = (
                    self.get_parameter("/solhealth/airtable/base_id") or ""
                )
                config["AIRTABLE_TABLE_ID"] = (
                    self.get_parameter("/solhealth/airtable/table_id") or "Therapists"
                )
                logger.info("Airtable config loaded from AWS Parameter Store")
        else:
            # Use environment variables in local mode
            config["AIRTABLE_API_KEY"] = os.getenv("AIRTABLE_API_KEY", "")
            config["AIRTABLE_BASE_ID"] = os.getenv("AIRTABLE_BASE_ID", "")
            config["AIRTABLE_TABLE_ID"] = os.getenv("AIRTABLE_TABLE_ID", "Therapists")
            logger.info("Airtable config loaded from environment variables")

        return config

    def inject_config_to_env(self):
        """
        Inject AWS configuration into environment variables.
        This allows existing code to work without modification.
        """
        if self.is_aws:
            airtable_config = self.get_airtable_config()
            for key, value in airtable_config.items():
                if value:
                    os.environ[key] = value
                    logger.debug(f"Injected {key} into environment")


# Create singleton instance
aws_config_manager = AWSConfigManager()

# Automatically inject config on import if in AWS
if aws_config_manager.is_aws:
    aws_config_manager.inject_config_to_env()
