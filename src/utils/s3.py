# src/utils/s3.py
import os
from enum import Enum
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from src.config import get_config

settings = get_config()

# Initialize S3 client only if AWS is enabled
_s3_client = None
if settings.IS_AWS:
    _s3_client = boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "us-east-2"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

S3_BUCKET_NAME = "therapists-personal-data"


class S3MediaType(Enum):
    IMAGE = "image"
    VIDEO = "video"
    WELCOME_VIDEO = "welcome_video"
    INTRO_VIDEO = "intro_video"
    GREETINGS_VIDEO = "greetings_video"


def get_media_url(
    user_email: str, s3_media_type: S3MediaType, expiration: int = 604800
) -> Optional[str]:
    """
    Generate presigned URL for S3 media using email-based keys.

    Your S3 structure:
    - images/email@domain.com (no file extension)
    - videos/email@domain.com_welcome (or similar suffixes)

    Args:
        user_email: Email address of the therapist
        s3_media_type: Type of media (IMAGE, VIDEO, etc.)
        expiration: URL expiration time in seconds (default 7 days)

    Returns:
        Presigned URL string or None if not found
    """
    if not settings.IS_AWS or not _s3_client:
        print(f"⚠️ S3 is disabled (IS_AWS={settings.IS_AWS})")
        return None

    if not user_email:
        print("⚠️ get_media_url called with empty email")
        return None

    # Clean and standardize the email
    email = user_email.strip().lower()

    # Determine the S3 key based on media type
    if s3_media_type == S3MediaType.IMAGE:
        # Images are stored as: images/email@domain.com
        object_key = f"images/{email}"
    elif s3_media_type in [S3MediaType.VIDEO, S3MediaType.WELCOME_VIDEO]:
        # Videos might have _welcome suffix
        # First try with _welcome suffix
        object_key = f"videos/{email}_welcome"
    elif s3_media_type in [S3MediaType.INTRO_VIDEO, S3MediaType.GREETINGS_VIDEO]:
        # Try other video patterns
        object_key = f"videos/{email}_intro"
    else:
        print(f"⚠️ Unsupported media type: {s3_media_type}")
        return None

    try:
        # First, check if the object exists
        _s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=object_key)

        # Generate presigned URL
        url = _s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": object_key},
            ExpiresIn=expiration,
        )

        print(f"✅ Generated presigned URL for {email} ({s3_media_type.value})")
        return url

    except ClientError as e:
        error_code = e.response["Error"]["Code"]

        if error_code == "404":
            # If video with _welcome doesn't exist, try without suffix
            if (
                s3_media_type in [S3MediaType.VIDEO, S3MediaType.WELCOME_VIDEO]
                and "_welcome" in object_key
            ):
                try:
                    fallback_key = f"videos/{email}"
                    _s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=fallback_key)

                    url = _s3_client.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": S3_BUCKET_NAME, "Key": fallback_key},
                        ExpiresIn=expiration,
                    )
                    print(f"✅ Generated presigned URL for {email} (fallback video)")
                    return url
                except ClientError:
                    pass

            print(f"⚠️ Object not found in S3: {object_key}")
        else:
            print(f"❌ S3 error for {object_key}: {error_code}")

        return None
    except Exception as e:
        print(f"❌ Unexpected error generating URL for {email}: {str(e)}")
        return None


def list_therapist_media(email: str) -> dict:
    """
    List all media files for a therapist.
    Useful for debugging what's actually in S3.
    """
    if not settings.IS_AWS or not _s3_client:
        return {"images": [], "videos": []}

    email = email.strip().lower()
    result = {"images": [], "videos": []}

    try:
        # List all objects that contain this email
        paginator = _s3_client.get_paginator("list_objects_v2")

        # Check images
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=f"images/{email}"):
            if "Contents" in page:
                for obj in page["Contents"]:
                    result["images"].append(obj["Key"])

        # Check videos
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=f"videos/{email}"):
            if "Contents" in page:
                for obj in page["Contents"]:
                    result["videos"].append(obj["Key"])

        return result

    except Exception as e:
        print(f"❌ Error listing media for {email}: {str(e)}")
        return result


# For backward compatibility
class S3Utils:
    def __init__(self):
        self.is_aws = settings.IS_AWS
        self.bucket_name = S3_BUCKET_NAME

    def get_media_url(
        self, email: str, media_type: S3MediaType, expiration: int = 604800
    ) -> Optional[str]:
        return get_media_url(email, media_type, expiration)

    def list_therapist_files(self, email: str, prefix: str) -> list:
        media = list_therapist_media(email)
        if prefix == "images":
            return media.get("images", [])
        elif prefix == "videos":
            return media.get("videos", [])
        return []


# Create global instance for backward compatibility
s3_utils = S3Utils() if settings.IS_AWS else None
