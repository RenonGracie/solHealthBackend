from flask import Blueprint, Flask


def register_blueprints(app: Flask) -> None:
    """Register all Flask blueprints with the application."""

    # Import blueprints
    from .appointments import appointments_bp
    from .availability import availability_bp
    from .clients import clients_bp
    from .intakeq_forms import intakeq_forms_bp
    from .lambda_practitioner import lambda_practitioner_bp
    from .nirvana_callback import nirvana_callback_bp
    from .railway_practitioner import railway_practitioner_bp
    from .therapists import therapists_bp
    from .tracking import tracking_bp

    # Register all blueprints
    app.register_blueprint(clients_bp)
    app.register_blueprint(therapists_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(intakeq_forms_bp)
    app.register_blueprint(lambda_practitioner_bp)  # AWS Lambda option
    app.register_blueprint(nirvana_callback_bp)  # Nirvana immediate logging
    app.register_blueprint(railway_practitioner_bp)  # Railway native option
    app.register_blueprint(availability_bp)
    app.register_blueprint(tracking_bp)

    # Admin endpoints temporarily disabled for deployment stability
    # TODO: Re-enable after deployment is stable
    # try:
    #     from .admin import admin_bp
    #     app.register_blueprint(admin_bp)
    # except ImportError as e:
    #     print(f"   - Admin endpoints not available: {e}")

    # Basic API blueprint
    api_bp = Blueprint("api", __name__)

    @api_bp.route("/")
    def index():
        """Basic sanity endpoint to verify that the API is reachable."""
        return {"message": "SolHealth API v1.0", "status": "running"}

    app.register_blueprint(api_bp)

    print("✅ Registered all API blueprints:")
    print("   - /clients_signup (GET, POST)")
    print("   - /clients_signup/<id> (PATCH)")
    print("   - /therapists/match")
    print("   - /therapists/slots")
    print("   - /therapists/programs (debug)")
    print("   - /appointments")
    print("   - /intakeq/create-client")
    print("   - /intakeq/client")
    print("   - /intakeq_forms/mandatory_form")
    print("   - /lambda/assign-practitioner (POST) [AWS Lambda]")
    print("   - /lambda/assign-practitioner/test (GET) [AWS Lambda]")
    print("   - /lambda/health (GET) [AWS Lambda]")
    print("   - /railway/assign-practitioner (POST) [Railway Native]")
    print("   - /railway/assign-practitioner/test (GET) [Railway Native]")
    print("   - /railway/health (GET) [Railway Native]")
    print("   - /therapists/availability")
    print("   - /therapists/<email>/availability/daily")
    print("   - /track-dropout")
    print("   - /track-completion")
    print("   - /track-interaction")
    print("   - /track-booking-context")
    print("   - /journey-analytics")
    print("   - /journey-summary/<response_id>")
    print("   - /nirvana/verified (POST) [Immediate Nirvana logging]") 
    print("   - /nirvana/failed (POST) [Nirvana failure logging]")
