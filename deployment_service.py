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
from flask import Flask, jsonify, request, current_app, render_template # Ensure all are here
import git_utils
import shlex
import subprocess

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

# --- End of Configuration Loading ---

# --- Application Setup ---
app = Flask(__name__) # Flask app for the deployment service

# Load configuration into Flask app config for easier access in routes
app.config['GIT_REPO_PATH'] = GIT_REPO_PATH
app.config['MAIN_APP_RESTART_COMMAND'] = MAIN_APP_RESTART_COMMAND

# --- Basic Health Check Route ---
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "message": "Deployment service is running.",
        "git_repo_path": app.config['GIT_REPO_PATH'],
        "main_app_restart_command": app.config['MAIN_APP_RESTART_COMMAND']
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
