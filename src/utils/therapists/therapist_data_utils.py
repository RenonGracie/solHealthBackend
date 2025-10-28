# src/utils/therapists/therapist_data_utils.py

# --- FIX: ADD ALL MISSING IMPORTS ---
from src.config import get_config
from src.utils import s3  # Import the s3 module
from src.utils.logger import get_logger
from src.utils.s3 import S3MediaType  # Import the Enum

# --- FIX: INITIALIZE LOGGER AND SETTINGS ---
settings = get_config()
logger = get_logger()


def provide_therapist_data(data: dict) -> dict:
    """
    Enriches therapist data with presigned S3 URLs and test data.
    """
    therapist_model = data["therapist"]
    email = (
        settings.TEST_THERAPIST_EMAIL
        if settings.TEST_THERAPIST_EMAIL
        else therapist_model.email
    )
    therapist = therapist_model.to_therapist()
    therapist.available_slots = data["available_slots"]
    data.pop("available_slots")

    logger.info(f"Enriching media URLs for therapist: {email}")

    # Apply test video links from settings if available
    if not therapist.welcome_video_link and settings.TEST_WELCOME_VIDEO:
        therapist.welcome_video_link = settings.TEST_WELCOME_VIDEO
    if not therapist.greetings_video_link and settings.TEST_GREETINGS_VIDEO:
        therapist.greetings_video_link = settings.TEST_GREETINGS_VIDEO

    # --- FIX: These calls will now work because s3 and S3MediaType are imported ---
    # Generate and assign the presigned URL for the therapist's image
    image_url = s3.get_media_url(user_id=email, s3_media_type=S3MediaType.IMAGE)
    therapist.image_link = image_url

    # You could also add logic for other media types here if needed
    # For example, to always override the welcome video link:
    # welcome_video_url = s3.get_media_url(user_id=email, s3_media_type=S3MediaType.WELCOME_VIDEO)
    # if welcome_video_url:
    #     therapist.welcome_video_link = welcome_video_url

    logger.info(
        f"Generated image URL for {email}: {'found' if image_url else 'not found'}"
    )

    data["therapist"] = therapist.dict()
    return data
