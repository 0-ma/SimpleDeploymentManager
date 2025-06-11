import unittest
import json
from unittest.mock import patch, MagicMock
import shlex 

# Changed import
from deployment_service import app 

class TestDeploymentServiceEndpoints(unittest.TestCase): # Renamed class

    def setUp(self):
        self.app = app.test_client()
        app.config['TESTING'] = True
        # Use config keys as defined in deployment_service.py
        app.config['GIT_REPO_PATH'] = '/fake/repo/path/for/testing/deployment_service'
        app.config['MAIN_APP_RESTART_COMMAND'] = 'echo "fake main app restart"'
        # DS_HOST and DS_PORT are used at app.run, not typically in test_client usage directly

    # Test for '/' route serving git_admin.html
    @patch('os.path.isdir')
    def test_admin_interface_route_valid_path(self, mock_isdir):
        mock_isdir.return_value = True
        # Ensure GIT_REPO_PATH is explicitly set for this test context if it might be altered by others
        app.config['GIT_REPO_PATH'] = '/fake/repo/path' 
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Git Repository Management", response.data)
        self.assertNotIn(b"Configuration Warning:", response.data)

    @patch('os.path.isdir')
    def test_admin_interface_route_invalid_path(self, mock_isdir):
        mock_isdir.return_value = False
        app.config['GIT_REPO_PATH'] = '/invalid/path' # Set a specific invalid path for the test
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200) # Page still loads
        self.assertIn(b"Configuration Warning:", response.data) # Warning should be present
        self.assertIn(b"/invalid/path", response.data) # Check if path is in warning

    @patch('os.path.isdir', return_value=True) # Mock for repo path check in endpoint
    @patch('git_utils.get_current_branch_or_commit')
    @patch('git_utils.get_branches')
    @patch('git_utils.get_tags')
    @patch('git_utils.get_log')
    def test_git_info_success(self, mock_get_log, mock_get_tags, mock_get_branches, mock_get_current_branch, mock_repo_is_dir):
        mock_get_current_branch.return_value = ('main', '', 0)
        # Ensure the mocked get_branches returns a list of strings as expected by the endpoint
        mock_get_branches.return_value = (['main', 'dev'], '', 0) 
        mock_get_tags.return_value = ("v1.0\nv1.1", "", 0) # Raw string output from git_utils
        mock_get_log.return_value = ("commit1\ncommit2", "", 0) # Raw string output

        response = self.app.get('/git/info')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        self.assertEqual(data['current_branch_or_commit'], 'main')
        self.assertEqual(data['branches'], ['main', 'dev'])
        self.assertEqual(data['tags'], ['v1.0', 'v1.1'])
        self.assertEqual(data['log'], ['commit1', 'commit2'])
        self.assertIsNone(data['errors']['branches_error'])

    @patch('os.path.isdir', return_value=False) # Simulate repo path is invalid
    def test_git_info_repo_not_found(self, mock_repo_is_dir):
        response = self.app.get('/git/info')
        self.assertEqual(response.status_code, 500)
        data = json.loads(response.data)
        self.assertIn("Git repository path not configured or not a valid directory", data['error'])

    @patch('os.path.isdir', return_value=True)
    @patch('git_utils.fetch')
    def test_git_fetch_success(self, mock_fetch, mock_repo_is_dir):
        mock_fetch.return_value = ("fetch stdout", "fetch stderr", 0)
        response = self.app.post('/git/fetch')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['message'], "Fetch successful.")
        self.assertEqual(data['stdout'], "fetch stdout")

    @patch('os.path.isdir', return_value=True)
    @patch('git_utils.checkout')
    def test_git_checkout_success(self, mock_checkout, mock_repo_is_dir):
        mock_checkout.return_value = ("checkout stdout", "", 0)
        response = self.app.post('/git/checkout', json={'ref': 'main'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['message'], "Checkout to 'main' successful.")

    @patch('os.path.isdir', return_value=True)
    def test_git_checkout_missing_ref(self, mock_repo_is_dir):
        response = self.app.post('/git/checkout', json={}) # No 'ref'
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn("Request body must be JSON and contain a 'ref' field.", data['error'])

        response = self.app.post('/git/checkout', json={'ref': ''}) # Empty 'ref'
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn("Reference name ('ref') must not be empty.", data['error'])

    @patch('os.path.isdir', return_value=True)
    @patch('git_utils.pull')
    def test_git_pull_success(self, mock_pull, mock_repo_is_dir):
        mock_pull.return_value = ("pull stdout", "", 0)
        response = self.app.post('/git/pull')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['message'], "Pull successful.")

    @patch('subprocess.run') # No need to mock os.path.isdir for /service/restart
    def test_service_restart_success(self, mock_subprocess_run):
        mock_process = MagicMock()
        mock_process.stdout = "Main app restarted"
        mock_process.stderr = ""
        mock_process.returncode = 0
        mock_subprocess_run.return_value = mock_process
        
        response = self.app.post('/service/restart')
        data = json.loads(response.data)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['message'], 'Main application restart command executed successfully.')
        
        # Check that subprocess.run was called with the correct command
        expected_command_args = shlex.split(app.config['MAIN_APP_RESTART_COMMAND'])
        mock_subprocess_run.assert_called_once_with(
            expected_command_args,
            capture_output=True,
            text=True,
            check=False
        )

    @patch('subprocess.run')
    def test_service_restart_failure(self, mock_subprocess_run):
        mock_process = MagicMock()
        mock_process.stdout = ""
        mock_process.stderr = "Failed to restart"
        mock_process.returncode = 1
        mock_subprocess_run.return_value = mock_process

        response = self.app.post('/service/restart')
        data = json.loads(response.data)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(data['error'], 'Main application restart command failed.')
        self.assertEqual(data['stderr'], 'Failed to restart')

    def test_service_restart_not_configured(self):
        original_command = app.config['MAIN_APP_RESTART_COMMAND']
        app.config['MAIN_APP_RESTART_COMMAND'] = 'echo "Main app restart command not configured"'
        try:
            response = self.app.post('/service/restart')
            data = json.loads(response.data)
            self.assertEqual(response.status_code, 500)
            self.assertEqual(data['error'], 'Main application restart command not configured in deployment service.')
        finally:
            app.config['MAIN_APP_RESTART_COMMAND'] = original_command


if __name__ == '__main__':
    unittest.main()
