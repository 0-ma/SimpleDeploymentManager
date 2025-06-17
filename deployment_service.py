# deployment_service.py
# This service provides Git repository management and restart capabilities
# for a separate, main application (e.g., the recipe app defined in app.py).
# It runs as an independent Flask application.
#
# Configuration is loaded with the following precedence:
# 1. Environment Variables (e.g., DS_GIT_REPO_PATH)
# 2. Values from 'deploy_config.json' file
# 3. Hardcoded defaults in this script

import os
import json # Add this import
import sys # Import sys module
import signal # Import signal module
from flask import Flask, jsonify, request, current_app, render_template
import git_utils # Assuming git_utils is in the same package
from git_utils import get_stale_local_branches, delete_local_branch # Specific imports
import shlex
import subprocess
import logging
import logging.handlers
import os # Added os for path joining if needed, though not strictly necessary for LOG_FILENAME='deployment_service.log'

# --- Logging Configuration ---
LOG_FILENAME = 'deployment_service.log'
LOG_LEVEL = logging.INFO

# Get root logger to configure logging for the entire application (including imported modules like git_utils)
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# Create rotating file handler
# For simplicity, LOG_FILENAME is relative to the current working directory of the script.
# For more robust path handling, os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_FILENAME)
# could be used if __file__ is reliably defined in the execution environment.
log_file_path = LOG_FILENAME

file_handler = logging.handlers.RotatingFileHandler(
    log_file_path,
    maxBytes=1024*1024, # 1 MB
    backupCount=3
)
file_handler.setLevel(LOG_LEVEL)

# Create formatter and add it to the handler
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Add the handler to the logger
logger.addHandler(file_handler)

# Optional: Log to console as well during development
# stream_handler = logging.StreamHandler()
# stream_handler.setLevel(LOG_LEVEL)
# stream_handler.setFormatter(formatter)
# logger.addHandler(stream_handler)

logger.info("Logging configured successfully.") # This message will go to the file and console (if stream_handler active)
# --- End of Logging Configuration ---


# --- Configuration Loading ---
# Defines the name of the JSON configuration file to be loaded.
CONFIG_FILE_PATH = 'deploy_config.json'
config_from_json = {}

try:
    with open(CONFIG_FILE_PATH, 'r') as f:
        config_from_json = json.load(f)
    print(f"Loaded configuration from {CONFIG_FILE_PATH}") # Optional: for logging/debugging
except FileNotFoundError:
    print(f"Info: {CONFIG_FILE_PATH} not found. Using defaults and environment variables.")
except json.JSONDecodeError:
    print(f"Warning: Could not decode {CONFIG_FILE_PATH}. File might be malformed. Using defaults and environment variables.")

# Helper function to get config value with precedence: Env Var > JSON file > Default code value
def get_config_value(env_var_name, json_key, default_value, value_type=str):
    # """
    # Retrieves a configuration value with a defined order of precedence:
    # 1. Environment Variable (if set)
    # 2. Value from JSON config file (if key exists and value is not null)
    # 3. Hardcoded default_value
    # Handles type conversion for integers.
    # """
    value = os.environ.get(env_var_name)
    if value is not None:
        # print(f"Using value from env var {env_var_name}") # Debug
        pass
    elif json_key in config_from_json and config_from_json[json_key] is not None:
        # print(f"Using value from JSON key {json_key}") # Debug
        value = config_from_json[json_key]
    else:
        # print(f"Using default value for {json_key}") # Debug
        value = default_value
    
    if value_type == int and isinstance(value, str): # Env vars are strings
        try:
            return int(value)
        except ValueError:
            print(f"Warning: Could not convert value '{value}' for {env_var_name or json_key} to int. Using default: {default_value}")
            return default_value if not isinstance(default_value, str) else int(default_value) # Ensure default is also int
    elif value_type == str and not isinstance(value, str):
            return str(value) # Ensure it's a string
    return value

# Define configurations using the helper

# DS_GIT_REPO_PATH: Path to the local Git repository of the MAIN application.
# Resolved in order: DS_GIT_REPO_PATH env var > 'DS_GIT_REPO_PATH' in JSON > current working directory.
_git_repo_path_default_from_code = os.getcwd()
GIT_REPO_PATH_FROM_JSON = config_from_json.get('DS_GIT_REPO_PATH') # Get value, could be null

if os.environ.get('DS_GIT_REPO_PATH'):
    GIT_REPO_PATH = os.environ.get('DS_GIT_REPO_PATH')
elif GIT_REPO_PATH_FROM_JSON: # Not None and not empty string from JSON
    GIT_REPO_PATH = GIT_REPO_PATH_FROM_JSON
else: # Env var not set, and JSON is null, empty or key missing
    GIT_REPO_PATH = _git_repo_path_default_from_code

# DS_MAIN_APP_RESTART_COMMAND: Command to restart the main application.
# Resolved in order: DS_MAIN_APP_RESTART_COMMAND env var > 'DS_MAIN_APP_RESTART_COMMAND' in JSON > coded default.
MAIN_APP_RESTART_COMMAND = get_config_value(
    'DS_MAIN_APP_RESTART_COMMAND', 
    'DS_MAIN_APP_RESTART_COMMAND', 
    "echo 'Main app restart command not configured'"
)

# DS_HOST: Network host for this deployment service.
# Resolved in order: DS_HOST env var > 'DS_HOST' in JSON > coded default '127.0.0.1'.
DS_HOST = get_config_value('DS_HOST', 'DS_HOST', '127.0.0.1')

# DS_PORT: Network port for this deployment service.
# Resolved in order: DS_PORT env var > 'DS_PORT' in JSON > coded default 5001.
DS_PORT = get_config_value('DS_PORT', 'DS_PORT', 5001, value_type=int)

# --- End of Configuration Loading ---

# --- Application Setup ---
app = Flask(__name__) # Flask app for the deployment service

# Load configuration into Flask app config for easier access in routes
app.config['GIT_REPO_PATH'] = GIT_REPO_PATH
app.config['MAIN_APP_RESTART_COMMAND'] = MAIN_APP_RESTART_COMMAND
app.config['DS_HOST'] = DS_HOST
app.config['DS_PORT'] = DS_PORT

# --- Basic Health Check Route ---
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "message": "Deployment service is running.",
        "git_repo_path": app.config['GIT_REPO_PATH'],
        "main_app_restart_command": app.config['MAIN_APP_RESTART_COMMAND'],
        "listening_on": f"{app.config['DS_HOST']}:{app.config['DS_PORT']}"
    }), 200

# --- Admin Interface ---
@app.route('/', methods=['GET'])
def admin_interface():
    # This route serves the main admin page for Git management and service restart.
    # It relies on templates/git_admin.html being available.
    repo_path = current_app.config.get('GIT_REPO_PATH')
    # Basic check to pass to template, so it can display an error if path is not set.
    # The API calls from the page will do more robust checks.
    is_repo_path_valid = os.path.isdir(repo_path if repo_path else "") # Avoid error if repo_path is None

    # Potentially pass other necessary config or status to the template if needed
    # For now, just the validity of the repo path for initial display.
    return render_template('git_admin.html', git_repo_path_valid=is_repo_path_valid, git_repo_path=repo_path)

# --- Git API Endpoints ---
# These endpoints provide programmatic control over the Git repository.
# Security: Protect these endpoints if the service is exposed.

@app.route('/git/info', methods=['GET'])
def git_info():
    repo_path = current_app.config.get('GIT_REPO_PATH')
    # It's crucial to check if the path is a directory, especially since it's configurable.
    if not repo_path or not os.path.isdir(repo_path):
        return jsonify({"error": "Git repository path not configured or not a valid directory.", "details": f"Path checked: {repo_path}"}), 500

    current_branch_or_commit, stderr_branch, retcode_branch = git_utils.get_current_branch_or_commit(repo_path)
    branches, stderr_branches, retcode_branches = git_utils.get_branches(repo_path)
    tags, stderr_tags, retcode_tags = git_utils.get_tags(repo_path)
    log, stderr_log, retcode_log = git_utils.get_log(repo_path) # Default count is 20

    cleaned_branches = []
    if retcode_branches == 0 and isinstance(branches, list):
        cleaned_branches = [b.strip("'") for b in branches if b] # Filter out empty strings
    elif retcode_branches !=0 :
        cleaned_branches = "Error fetching branches"


    processed_tags = []
    if retcode_tags == 0 and isinstance(tags, str):
        processed_tags = [tag for tag in tags.split('\n') if tag] # Filter out empty strings after split
    elif retcode_tags !=0:
        processed_tags = "Error fetching tags"
        
    processed_log = []
    if retcode_log == 0 and isinstance(log, str):
        processed_log = [l for l in log.split('\n') if l] # Filter out empty strings after split
    elif retcode_log != 0:
        processed_log = "Error fetching log"


    return jsonify({
        "current_branch_or_commit": current_branch_or_commit if retcode_branch == 0 else "Error fetching current branch/commit",
        "branches": cleaned_branches,
        "tags": processed_tags,
        "log": processed_log,
        "errors": {
            "branch_commit_error": stderr_branch if retcode_branch != 0 else None,
            "branches_error": stderr_branches if retcode_branches != 0 else None,
            "tags_error": stderr_tags if retcode_tags != 0 else None,
            "log_error": stderr_log if retcode_log != 0 else None,
        }
    })

@app.route('/git/fetch', methods=['POST'])
def git_fetch_route():
    repo_path = current_app.config.get('GIT_REPO_PATH')
    if not repo_path or not os.path.isdir(repo_path):
        return jsonify({"error": "Git repository path not configured or not a valid directory."}), 500

    stdout, stderr, retcode = git_utils.fetch(repo_path)
    if retcode == 0:
        return jsonify({"message": "Fetch successful.", "stdout": stdout, "stderr": stderr})
    else:
        return jsonify({"error": "Fetch failed.", "stdout": stdout, "stderr": stderr}), 500

@app.route('/git/checkout', methods=['POST'])
def git_checkout_route():
    repo_path = current_app.config.get('GIT_REPO_PATH')
    if not repo_path or not os.path.isdir(repo_path):
        return jsonify({"error": "Git repository path not configured or not a valid directory."}), 500

    data = request.get_json()
    if not data or 'ref' not in data:
        return jsonify({"error": "Request body must be JSON and contain a 'ref' field."}), 400
    
    ref_name = data.get('ref')
    if not ref_name: # Handles cases like {'ref': null} or {'ref': ''}
        return jsonify({"error": "Reference name ('ref') must not be empty."}), 400
    
    stdout, stderr, retcode = git_utils.checkout(repo_path, ref_name)
    if retcode == 0:
        return jsonify({"message": f"Checkout to '{ref_name}' successful.", "stdout": stdout, "stderr": stderr})
    else:
        return jsonify({"error": f"Checkout to '{ref_name}' failed.", "stdout": stdout, "stderr": stderr}), 500

@app.route('/git/pull', methods=['POST'])
def git_pull_route():
    repo_path = current_app.config.get('GIT_REPO_PATH')
    if not repo_path or not os.path.isdir(repo_path):
        return jsonify({"error": "Git repository path not configured or not a valid directory."}), 500

    stdout, stderr, retcode = git_utils.pull(repo_path)
    if retcode == 0:
        return jsonify({"message": "Pull successful.", "stdout": stdout, "stderr": stderr})
    else:
        return jsonify({"error": "Pull failed.", "stdout": stdout, "stderr": stderr}), 500

# --- Service Management Endpoint (for the Main Application) ---
# Security: This endpoint is particularly sensitive. It executes DS_MAIN_APP_RESTART_COMMAND.
@app.route('/service/restart', methods=['POST'])
def service_restart_route():
    # This command restarts the MAIN application (e.g., app.py), NOT this deployment service.
    restart_command = current_app.config.get('MAIN_APP_RESTART_COMMAND')
    
    if not restart_command or restart_command == 'echo "Main app restart command not configured"': # Check against placeholder
        return jsonify({"error": "Main application restart command not configured in deployment service."}), 500

    try:
        # Using shlex.split for safer command parsing.
        command_args = shlex.split(restart_command)
        
        # Execute the command.
        # Consider implications if the command requires sudo or specific permissions.
        # The user running deployment_service.py needs appropriate permissions.
        process = subprocess.run(
            command_args,
            capture_output=True,
            text=True,
            check=False # Handle non-zero exit codes manually
        )

        if process.returncode == 0:
            return jsonify({
                "message": "Main application restart command executed successfully.",
                "stdout": process.stdout,
                "stderr": process.stderr # stderr might contain informational messages too
            })
        else:
            return jsonify({
                "error": "Main application restart command failed.",
                "stdout": process.stdout,
                "stderr": process.stderr,
                "returncode": process.returncode
            }), 500
    except FileNotFoundError:
         return jsonify({
            "error": f"The main app restart command '{restart_command}' or its components not found. Ensure it is correct and in PATH.",
            "details": "FileNotFoundError"
        }), 500
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred while trying to restart the main application: {str(e)}"}), 500

# --- Deployment Service Management Endpoints ---

@app.route('/deployment-service/restart-self', methods=['POST'])
def deployment_service_restart_self_route():
    current_app.logger.info("Gunicorn self-restart initiated. Attempting to signal Gunicorn master.")

    pid_file_path = os.environ.get('GUNICORN_PID_FILE_PATH')

    if not pid_file_path:
        error_msg = "GUNICORN_PID_FILE_PATH environment variable not set. Cannot determine Gunicorn master PID."
        current_app.logger.error(error_msg)
        return jsonify({"error": "Gunicorn PID file path not configured. Cannot initiate self-restart."}), 500

    try:
        with open(pid_file_path, 'r') as f:
            master_pid_str = f.read().strip()

        if not master_pid_str:
            raise ValueError("PID file is empty.")

        master_pid = int(master_pid_str)
        current_app.logger.info(f"Read Gunicorn master PID {master_pid} from {pid_file_path}.")

        os.kill(master_pid, signal.SIGTERM)
        current_app.logger.info(f"Sent SIGTERM to Gunicorn master PID {master_pid}.")

        return jsonify({"message": "SIGTERM signal sent to Gunicorn master. Service restart initiated."}), 200

    except FileNotFoundError:
        error_msg = f"Gunicorn PID file not found at {pid_file_path}."
        current_app.logger.error(error_msg)
        return jsonify({"error": f"Gunicorn PID file not found at {pid_file_path}. Cannot initiate self-restart."}), 500
    except ValueError:
        error_msg = f"Invalid PID found in Gunicorn PID file {pid_file_path}."
        current_app.logger.error(error_msg)
        return jsonify({"error": f"Invalid PID in Gunicorn PID file {pid_file_path}. Cannot initiate self-restart."}), 500
    except Exception as e:
        error_msg = f"An unexpected error occurred while processing Gunicorn PID: {str(e)}"
        current_app.logger.error(error_msg)
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

# --- Log Viewing API Endpoint ---
@app.route('/api/git/recent-logs', methods=['GET'])
def get_recent_logs_route():
    num_lines_to_fetch = request.args.get('lines', 100, type=int) # Allow 'lines' query param, default 100
    if num_lines_to_fetch <= 0 or num_lines_to_fetch > 1000: # Basic validation
        num_lines_to_fetch = 100

    log_lines = []
    # LOG_FILENAME is defined globally in this module.
    # In a larger app, this might come from app.config.
    try:
        with open(LOG_FILENAME, 'r') as f:
            all_lines = f.readlines()

        # Get the last N lines and strip whitespace
        log_lines = [line.strip() for line in all_lines[-num_lines_to_fetch:]]

    except FileNotFoundError:
        # Using current_app.logger which is configured by the root logger setup earlier.
        current_app.logger.info(f"Log file '{LOG_FILENAME}' not found when trying to read for API.")
        # It's okay to return 200 with a message if file not found, as it's not strictly a client error.
        return jsonify({"logs": [], "message": f"Log file '{LOG_FILENAME}' not found or is empty."}), 200
    except Exception as e:
        current_app.logger.error(f"Error reading log file '{LOG_FILENAME}' for API: {str(e)}")
        return jsonify({"error": "Failed to read log file.", "details": str(e)}), 500

    return jsonify({"logs": log_lines})


# --- New Git Endpoints for Stale and Delete Branch Operations ---

@app.route('/git/stale-branches', methods=['GET']) # Renamed route
def get_stale_local_branches_route(): # Function name can remain descriptive
    repo_path = current_app.config.get('GIT_REPO_PATH')
    if not repo_path or not os.path.isdir(repo_path):
        current_app.logger.error(f"Stale branches check: Git repository path '{repo_path}' not configured or invalid.")
        return jsonify({"error": "Git repository path not configured or not a valid directory."}), 500

    current_app.logger.info(f"Fetching stale local branches for repo: {repo_path}")
    try:
        stale_branches_data = get_stale_local_branches(repo_path)
        if stale_branches_data is None: # get_stale_local_branches returns None on some errors
            current_app.logger.error(f"get_stale_local_branches returned None for repo: {repo_path}")
            return jsonify({"error": "Error processing stale branches. Could not retrieve current branch or branch statuses."}), 500

        current_app.logger.info(f"Successfully fetched stale branches list for repo {repo_path}")
        # Wrap the list in a dictionary as per requirements
        return jsonify({"stale_branches": stale_branches_data}), 200
    except Exception as e:
        current_app.logger.error(f"Exception in /git/stale-branches: {str(e)}", exc_info=True) # Updated log message
        return jsonify({"error": "An unexpected error occurred while fetching stale branches.", "details": str(e)}), 500


@app.route('/git/delete-local-branch', methods=['POST']) # Changed route and removed path:branch_name
def delete_local_branch_route(): # Removed branch_name from signature
    repo_path = current_app.config.get('GIT_REPO_PATH')
    if not repo_path or not os.path.isdir(repo_path):
        current_app.logger.error(f"Delete branch: Git repository path '{repo_path}' not configured or invalid.")
        return jsonify({"error": "Git repository path not configured or not a valid directory."}), 500

    data = request.get_json()
    if not data or 'branch_name' not in data:
        current_app.logger.warning("Delete branch: Request body must be JSON and contain a 'branch_name' field.")
        return jsonify({"error": "Request body must be JSON and contain a 'branch_name' field."}), 400

    branch_name = data.get('branch_name')
    if not isinstance(branch_name, str) or not branch_name.strip():
        current_app.logger.warning("Delete branch: 'branch_name' must be a non-empty string.")
        return jsonify({"error": "'branch_name' must be a non-empty string."}), 400

    branch_name = branch_name.strip() # Use stripped branch name

    current_app.logger.info(f"Processing delete request for branch '{branch_name}' in repo '{repo_path}'.")

    # Crucial Safety Check
    try:
        stale_branches_list = get_stale_local_branches(repo_path)
        if stale_branches_list is None:
            current_app.logger.error(f"Could not get stale branches list for safety check when attempting to delete '{branch_name}'.")
            return jsonify({"error": "Could not verify branch status for deletion. Check service logs."}), 500

        branch_to_delete_info = None
        for branch_info in stale_branches_list:
            if branch_info.get('name') == branch_name:
                branch_to_delete_info = branch_info
                break

        if not branch_to_delete_info:
            current_app.logger.warning(f"Branch '{branch_name}' not found among stale branches. Cannot delete.")
            return jsonify({"error": f"Branch '{branch_name}' is not recognized as a stale branch." , "details": "It may not be stale, or may no longer exist."}), 404 # 404 or 400

        if branch_to_delete_info.get('status') != 'safe_to_delete':
            current_app.logger.warning(f"Branch '{branch_name}' is stale but not marked 'safe_to_delete'. Status: {branch_to_delete_info.get('status')}. Cannot delete.")
            return jsonify({
                "error": f"Branch '{branch_name}' is not eligible for deletion.",
                "details": f"Current status: '{branch_to_delete_info.get('status')}'. Only branches marked 'safe_to_delete' can be removed via this endpoint."
            }), 403 # 403 Forbidden as the action is understood but not allowed

    except Exception as e: # Catch errors during the safety check itself
        current_app.logger.error(f"Exception during safety check for deleting branch '{branch_name}': {str(e)}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred during branch safety check.", "details": str(e)}), 500

    # If safety check passed, proceed with deletion
    current_app.logger.info(f"Branch '{branch_name}' is 'safe_to_delete'. Proceeding with deletion.")
    try:
        # git_utils.delete_local_branch was updated to not take `force`
        success, message = delete_local_branch(repo_path, branch_name)

        if success:
            current_app.logger.info(f"Successfully deleted branch '{branch_name}'. Details: {message}")
            return jsonify({
                "message": f"Branch '{branch_name}' deleted successfully.",
                "details": message  # message is stdout from the command
            }), 200
        else:
            # This case should ideally not be hit often if "safe_to_delete" is accurate,
            # but could happen if e.g. git state changes between check and delete, or other issues.
            current_app.logger.warning(f"Failed to delete branch '{branch_name}' even after 'safe_to_delete' check. Details: {message}")
            return jsonify({
                "error": f"Failed to delete branch '{branch_name}'.",
                "details": message # message is stderr from the command
            }), 500 # 500 because it was expected to succeed

    except Exception as e: # Catch errors during the deletion attempt itself
        current_app.logger.error(f"Exception while attempting to delete branch '{branch_name}': {str(e)}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred while deleting the branch.", "details": str(e)}), 500
