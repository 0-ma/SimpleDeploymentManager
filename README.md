# Deployment Service

This service provides capabilities to manage a Git repository and restart a main application. It is designed to simplify deployment and updates for a separate, primary application.

## Features

*   **Git Repository Management:**
    *   Fetch latest changes from the remote repository.
    *   Checkout specific branches or tags.
    *   Pull updates into the local repository.
*   **Main Application Restart:**
    *   Trigger a restart of the main application via a configured command.
*   **Flexible Configuration:**
    *   Configure the service using a `deploy_config.json` file.
    *   Override JSON configuration with environment variables.
*   **API Endpoints:**
    *   Programmatic access to all service capabilities via a REST API.
*   **Web Interface:**
    *   A simple web-based admin interface for easy management of the Git repository and application restarts.

## Configuration

The deployment service can be configured via a JSON file (`deploy_config.json`) or through environment variables. Environment variables will always take precedence over values set in the JSON file.

To configure using the JSON file:

1.  Make a copy of the `deploy_config.template.json` file.
2.  Rename the copy to `deploy_config.json`.
3.  Edit `deploy_config.json` with your desired settings:

    *   **`DS_GIT_REPO_PATH`**: (String) The absolute or relative path to the local Git repository of the main application that this service will manage.
        *   *Example*: `"/path/to/your/main/app/repo"` or `"../my-app"`
        *   If not set via environment variable or this JSON key, it defaults to the current working directory of the deployment service.

    *   **`DS_MAIN_APP_RESTART_COMMAND`**: (String) The command that will be executed to restart your main application.
        *   *Examples*:
            *   `"sudo systemctl restart my-main-app"`
            *   `"pm2 restart main_app_name"`
            *   To restart a Python application, you might first find its process ID (PID). You could list Python processes using a command like `ps aux | grep python`. Then, a more specific restart command might involve `pkill` (which sends a signal to processes based on name or other attributes). For instance, if your application is run with `/usr/local/bin/python /home/user/app/app.py`, you could use `pkill -f "/usr/local/bin/python /home/user/app/app.py"`. Be cautious with `pkill` to ensure you target the correct process. Often, this command would be part of a larger script that also handles restarting the application.
        *   If not configured, the service will not be able to restart the main application. The default is an echo command indicating it's not configured.

    *   **`DS_HOST`**: (String) The network host address on which the deployment service will listen.
        *   *Default*: `"0.0.0.0"` (listens on all available network interfaces)
        *   Can also be set to `"127.0.0.1"` for local access only.

    *   **`DS_PORT`**: (Integer) The network port on which the deployment service will listen.
        *   *Default*: `55009`

**Environment Variables:**

You can also set or override these configurations using environment variables:

*   `DS_GIT_REPO_PATH`
*   `DS_MAIN_APP_RESTART_COMMAND`
*   `DS_HOST`
*   `DS_PORT`

For example, to set the Git repository path via an environment variable:
`export DS_GIT_REPO_PATH="/path/to/your/main/app/repo"`

## Running the Service

To run the deployment service:

1.  Ensure you have Python installed.
2.  Install the required dependencies (Flask and GitPython):
    ```bash
    pip install -r requirements.txt
    ```
3.  Configure the service as described in the "Configuration" section (either via `deploy_config.json` or environment variables).
4.  Run the `deployment_service.py` script:
    ```bash
    python deployment_service.py
    ```

This will start the Flask development server. By default, it will be accessible at `http://<DS_HOST>:<DS_PORT>`.

**Important for Production:**

The Flask development server is not suitable for production environments. For production deployment, use a production-grade WSGI server such as Gunicorn or uWSGI.

*Example with Gunicorn:*

```bash
gunicorn --bind <DS_HOST>:<DS_PORT> deployment_service:app
```
Replace `<DS_HOST>` and `<DS_PORT>` with your configured host and port.

## Service Deployment (Systemd)

To run this deployment service as a background system service on Linux systems using systemd, follow these steps. Step 1 details the systemd unit configuration. Firewall configuration is detailed in Step 2 below.

1.  **Create or Update the Systemd Service File:**
    You will need to create a systemd service file for the deployment manager. Use a text editor like `nano` to create and edit the file, typically located at `/etc/systemd/system/svc-deployment-manager.service`:
    ```bash
    sudo nano /etc/systemd/system/svc-deployment-manager.service
    ```
    Paste the following configuration into the file. **Important:** You may need to adjust `User`, `WorkingDirectory`, and `ExecStart` to match your specific setup (e.g., username, path to the cloned repository, and path to your python3 executable if not in `/usr/local/bin/python3`).

    ```ini
    [Unit]
    Description=svc-deployment-manager
    After=network.target

    [Service]
    User=usr
    WorkingDirectory=/home/usr/svc-deployment-manager
    ExecStart=/usr/local/bin/python3 deployment_service.py
    Restart=always

    [Install]
    WantedBy=multi-user.target
    ```
    Ensure the `WorkingDirectory` points to the root of this service's directory (where `deployment_service.py` is located), and `ExecStart` correctly points to your Python 3 executable and the `deployment_service.py` script. The `User` should be the user under which the service will run.

2.  **Configure Firewall (if `ufw` is used):**
    If you are using `ufw` (Uncomplicated Firewall), you'll need to allow traffic on the port this service listens on. The service is configured via `DS_PORT`, which defaults to `55009` (see Configuration section).

    Execute the following commands, replacing `<DS_PORT>` with the actual port number if you have configured a different one:
    ```bash
    sudo ufw allow <DS_PORT>/tcp
    sudo ufw reload
    ```
    For example, if using the default port `55009`:
    ```bash
    sudo ufw allow 55009/tcp
    sudo ufw reload
    ```

3.  **Reload Systemd, Start, and Enable the Service:**
    After creating or modifying the service file and configuring the firewall, execute the following commands:
    ```bash
    sudo systemctl daemon-reload  # Reloads systemd manager configuration
    sudo systemctl start svc-deployment-manager  # Starts the service
    sudo systemctl enable svc-deployment-manager # Enables the service to start on boot
    sudo systemctl status svc-deployment-manager # Check the status of the service
    ```

The systemd unit configuration is provided in Step 1. Firewall rules are described in Step 2 above.

## API Endpoints

The service exposes the following REST API endpoints for programmatic control:

*   **`GET /health`**
    *   **Description:** Checks the health of the deployment service.
    *   **Response:** JSON object indicating the status, configured paths, and listening address.

*   **`GET /`**
    *   **Description:** Serves the HTML admin interface.
    *   **Response:** HTML page for managing the Git repository and service restart.

*   **`GET /git/info`**
    *   **Description:** Retrieves information about the configured Git repository, including the current branch/commit, all local branches, tags, and recent commit log.
    *   **Response:** JSON object with repository details.
    *   **Error:** Returns a 500 error if the `DS_GIT_REPO_PATH` is not configured or invalid.

*   **`POST /git/fetch`**
    *   **Description:** Performs a `git fetch --all` operation in the repository to retrieve the latest information from all remotes.
    *   **Response:** JSON object with the status of the fetch operation (stdout, stderr).
    *   **Error:** Returns a 500 error if the fetch fails or the repository path is invalid.

*   **`POST /git/checkout`**
    *   **Description:** Checks out a specified Git reference (branch, tag, or commit hash).
    *   **Request Body (JSON):**
        ```json
        {
            "ref": "your-branch-name-or-tag"
        }
        ```
    *   **Response:** JSON object with the status of the checkout operation.
    *   **Error:**
        *   Returns 400 if the `ref` field is missing or empty in the request body.
        *   Returns 500 if the checkout fails or the repository path is invalid.

*   **`POST /git/pull`**
    *   **Description:** Performs a `git pull` operation on the current branch to update it with changes from its upstream remote.
    *   **Response:** JSON object with the status of the pull operation.
    *   **Error:** Returns a 500 error if the pull fails or the repository path is invalid.

*   **`POST /service/restart`**
    *   **Description:** Executes the configured `DS_MAIN_APP_RESTART_COMMAND` to restart the main application.
    *   **Response:** JSON object with the status of the restart command execution (stdout, stderr).
    *   **Error:**
        *   Returns 500 if the `DS_MAIN_APP_RESTART_COMMAND` is not configured.
        *   Returns 500 if the command execution fails.

## Admin Interface

The service includes a basic web-based admin interface accessible by navigating to the root URL (e.g., `http://<DS_HOST>:<DS_PORT>/`) in a web browser.

From the admin interface, you can:

*   **View Repository Status:** See the current checked-out branch or commit, available local branches, and tags.
*   **Perform Git Operations:**
    *   **Fetch:** Update information from all remote repositories.
    *   **Checkout:** Switch to a different branch or tag by selecting from a dropdown and clicking "Checkout".
    *   **Pull:** Update the current branch with changes from its remote counterpart.
*   **Restart Main Application:** Click the "Restart Main Application" button to execute the configured restart command.

The interface will also display the configured Git repository path and show a warning if the path is not valid.