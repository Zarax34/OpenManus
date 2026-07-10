import time

from daytona import (
    CreateSandboxFromImageParams,
    Daytona,
    DaytonaConfig,
    Resources,
    Sandbox,
    SandboxState,
    SessionExecuteRequest,
)

from app.config import config
from app.utils.logger import logger


_daytona_instance = None
_daytona_settings = None


def get_daytona_settings():
    global _daytona_settings
    if _daytona_settings is None:
        _daytona_settings = config.daytona
    return _daytona_settings


def get_daytona():
    global _daytona_instance
    if _daytona_instance is not None:
        return _daytona_instance

    ds = get_daytona_settings()
    logger.info("Initializing Daytona sandbox configuration")
    daytona_config = DaytonaConfig(
        api_key=ds.daytona_api_key,
        server_url=ds.daytona_server_url,
        target=ds.daytona_target,
    )

    if daytona_config.api_key:
        logger.info("Daytona API key configured successfully")
    else:
        logger.warning("No Daytona API key found in environment variables")

    if daytona_config.server_url:
        logger.info(f"Daytona server URL set to: {daytona_config.server_url}")
    else:
        logger.warning("No Daytona server URL found in environment variables")

    if daytona_config.target:
        logger.info(f"Daytona target set to: {daytona_config.target}")
    else:
        logger.warning("No Daytona target found in environment variables")

    _daytona_instance = Daytona(daytona_config)
    logger.info("Daytona client initialized")
    return _daytona_instance


async def get_or_start_sandbox(sandbox_id: str):
    """Retrieve a sandbox by ID, check its state, and start it if needed."""

    logger.info(f"Getting or starting sandbox with ID: {sandbox_id}")

    try:
        d = get_daytona()
        sandbox = d.get(sandbox_id)

        # Check if sandbox needs to be started
        if (
            sandbox.state == SandboxState.ARCHIVED
            or sandbox.state == SandboxState.STOPPED
        ):
            logger.info(f"Sandbox is in {sandbox.state} state. Starting...")
            try:
                d.start(sandbox)
                sandbox = d.get(sandbox_id)
                start_supervisord_session(sandbox)
            except Exception as e:
                logger.error(f"Error starting sandbox: {e}")
                raise e

        logger.info(f"Sandbox {sandbox_id} is ready")
        return sandbox

    except Exception as e:
        logger.error(f"Error retrieving or starting sandbox: {str(e)}")
        raise e


def start_supervisord_session(sandbox: Sandbox):
    """Start supervisord in a session."""
    session_id = "supervisord-session"
    try:
        logger.info(f"Creating session {session_id} for supervisord")
        sandbox.process.create_session(session_id)

        # Execute supervisord command
        sandbox.process.execute_session_command(
            session_id,
            SessionExecuteRequest(
                command="exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf",
                var_async=True,
            ),
        )
        time.sleep(25)  # Wait a bit to ensure supervisord starts properly
        logger.info(f"Supervisord started in session {session_id}")
    except Exception as e:
        logger.error(f"Error starting supervisord session: {str(e)}")
        raise e


def create_sandbox(password: str, project_id: str = None):
    """Create a new sandbox with all required services configured and running."""

    logger.info("Creating new Daytona sandbox environment")
    logger.info("Configuring sandbox with browser-use image and environment variables")

    ds = get_daytona_settings()

    labels = None
    if project_id:
        logger.info(f"Using sandbox_id as label: {project_id}")
        labels = {"id": project_id}

    params = CreateSandboxFromImageParams(
        image=ds.sandbox_image_name,
        public=True,
        labels=labels,
        env_vars={
            "CHROME_PERSISTENT_SESSION": "true",
            "RESOLUTION": "1024x768x24",
            "RESOLUTION_WIDTH": "1024",
            "RESOLUTION_HEIGHT": "768",
            "VNC_PASSWORD": password,
            "ANONYMIZED_TELEMETRY": "false",
            "CHROME_PATH": "",
            "CHROME_USER_DATA": "",
            "CHROME_DEBUGGING_PORT": "9222",
            "CHROME_DEBUGGING_HOST": "localhost",
            "CHROME_CDP": "",
        },
        resources=Resources(
            cpu=2,
            memory=4,
            disk=5,
        ),
        auto_stop_interval=15,
        auto_archive_interval=24 * 60,
    )

    # Create the sandbox
    sandbox = get_daytona().create(params)
    logger.info(f"Sandbox created with ID: {sandbox.id}")

    # Start supervisord in a session for new sandbox
    start_supervisord_session(sandbox)

    logger.info(f"Sandbox environment successfully initialized")
    return sandbox


async def delete_sandbox(sandbox_id: str):
    """Delete a sandbox by its ID."""
    logger.info(f"Deleting sandbox with ID: {sandbox_id}")

    try:
        # Get the sandbox
        d = get_daytona()
        sandbox = d.get(sandbox_id)

        # Delete the sandbox
        d.delete(sandbox)

        logger.info(f"Successfully deleted sandbox {sandbox_id}")
        return True
    except Exception as e:
        logger.error(f"Error deleting sandbox {sandbox_id}: {str(e)}")
        raise e
