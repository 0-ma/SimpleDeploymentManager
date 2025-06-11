import unittest
import json
from unittest.mock import patch, MagicMock
import shlex
import tempfile
import shutil
import os
import subprocess

# Changed import
from deployment_service import app, git_utils # Import git_utils directly for test setup/assertions

class TestDeploymentServiceEndpoints(unittest.TestCase): # Renamed class

    def _run_git_command_in_path(self, command_args, path):
        """Helper to run git commands for setup via subprocess."""
        try:
            # Ensure git commands are run with a known language setting for predictable output
            env = os.environ.copy()
            env['LANG'] = 'C'
            env['LC_ALL'] = 'C'
            result = subprocess.run(
                ['git'] + command_args,
                cwd=path,
                capture_output=True,
                text=True,
                check=True, # Raise exception on non-zero exit
                env=env
            )
            return result.stdout.strip(), result.stderr.strip()
        except subprocess.CalledProcessError as e:
            print(f"Git command failed: {e.cmd}")
            print(f"Stdout: {e.stdout}")
            print(f"Stderr: {e.stderr}")
            raise
        except FileNotFoundError:
            print("Git command not found. Ensure Git is installed and in PATH.")
            raise

    def setUp(self):
        self.app_client = app.test_client() # Use a different name to avoid conflict if self.app is used by Flask extensions
        app.config['TESTING'] = True
        self.original_git_repo_path = app.config.get('GIT_REPO_PATH')
        self.original_main_app_restart_command = app.config.get('MAIN_APP_RESTART_COMMAND')

        self.local_repo_dir = tempfile.mkdtemp(prefix="test_local_repo_")
        self.remote_repo_dir = tempfile.mkdtemp(prefix="test_remote_repo_")

        app.config['GIT_REPO_PATH'] = self.local_repo_dir
        # Set a default restart command for tests that might touch it, can be overridden per test
        app.config['MAIN_APP_RESTART_COMMAND'] = 'echo "fake main app restart during test"'

        self._init_git_repos()

    def _init_git_repos(self):
        # Init bare remote repo
        self._run_git_command_in_path(['init', '--bare'], self.remote_repo_dir)

        # Init local repo
        self._run_git_command_in_path(['init', '-b', 'main'], self.local_repo_dir) # Initialize with main branch
        self._run_git_command_in_path(['config', 'user.email', '"test@example.com"'], self.local_repo_dir)
        self._run_git_command_in_path(['config', 'user.name', '"Test User"'], self.local_repo_dir)

        # Initial commit in local repo
        with open(os.path.join(self.local_repo_dir, 'initial.txt'), 'w') as f:
            f.write('initial content')
        self._run_git_command_in_path(['add', 'initial.txt'], self.local_repo_dir)
        self._run_git_command_in_path(['commit', '-m', 'Initial commit'], self.local_repo_dir)

        # Add remote and push initial commit
        self._run_git_command_in_path(['remote', 'add', 'origin', self.remote_repo_dir], self.local_repo_dir)
        self._run_git_command_in_path(['push', '-u', 'origin', 'main'], self.local_repo_dir)

        # Create a new feature branch and push it to remote
        self._run_git_command_in_path(['branch', 'new-feature-branch'], self.local_repo_dir)
        # Make a commit on the new branch so it's distinct
        with open(os.path.join(self.local_repo_dir, 'feature.txt'), 'w') as f:
            f.write('feature content')
        self._run_git_command_in_path(['add', 'feature.txt'], self.local_repo_dir) # Stage the new file
         # Checkout the branch to make the commit on it
        self._run_git_command_in_path(['checkout', 'new-feature-branch'], self.local_repo_dir)
        self._run_git_command_in_path(['commit', '-m', 'Add feature content'], self.local_repo_dir)
        self._run_git_command_in_path(['push', 'origin', 'new-feature-branch'], self.local_repo_dir)

        # Switch back to main in local repo to set a known state before tests
        self._run_git_command_in_path(['checkout', 'main'], self.local_repo_dir)


    def tearDown(self):
        if self.original_git_repo_path is not None:
            app.config['GIT_REPO_PATH'] = self.original_git_repo_path
        else:
            # If it was not set, perhaps remove it or set to a default test value
            app.config.pop('GIT_REPO_PATH', None)

        if self.original_main_app_restart_command is not None:
             app.config['MAIN_APP_RESTART_COMMAND'] = self.original_main_app_restart_command
        else:
            app.config.pop('MAIN_APP_RESTART_COMMAND', None)

        if os.path.exists(self.local_repo_dir): # Check path exists before trying to remove
            shutil.rmtree(self.local_repo_dir)
        if os.path.exists(self.remote_repo_dir): # Check path exists
            shutil.rmtree(self.remote_repo_dir)

    # Test for '/' route serving git_admin.html
    @patch('os.path.isdir')
    def test_admin_interface_route_valid_path(self, mock_isdir):
        # This test now uses the GIT_REPO_PATH set in setUp (self.local_repo_dir)
        # So, we want os.path.isdir to return True for that path.
        # We need to ensure the mock targets the os.path.isdir used by the *route*, not by setup.
        # The route uses current_app.config.get('GIT_REPO_PATH'), which is self.local_repo_dir

        # If GIT_REPO_PATH is self.local_repo_dir, os.path.isdir should be True
        mock_isdir.side_effect = lambda path: path == self.local_repo_dir

        response = self.app_client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Git Repository Management", response.data)
        # Check that the warning is NOT present if the path is valid
        self.assertNotIn(b"Configuration Warning:", response.data)
        mock_isdir.assert_called_with(self.local_repo_dir)


    @patch('os.path.isdir')
    def test_admin_interface_route_invalid_path(self, mock_isdir):
        # For this test, we specifically want os.path.isdir to return False for the path
        # even if app.config['GIT_REPO_PATH'] points to a normally valid temp directory.
        # The mock needs to reflect this specific test scenario.
        test_invalid_path = "/invalid/path/for/this/test"
        app.config['GIT_REPO_PATH'] = test_invalid_path # Temporarily override for this test
        mock_isdir.return_value = False # Mock os.path.isdir to always return False

        response = self.app_client.get('/')
        self.assertEqual(response.status_code, 200) # Page still loads
        self.assertIn(b"Configuration Warning:", response.data) # Warning should be present
        self.assertIn(bytes(test_invalid_path, 'utf-8'), response.data) # Check if path is in warning
        # Restore GIT_REPO_PATH for other tests if it was changed
        app.config['GIT_REPO_PATH'] = self.local_repo_dir


    # For tests that use the real git repo, we don't mock os.path.isdir for GIT_REPO_PATH
    # It should be a valid directory (self.local_repo_dir)
    # We only mock git_utils functions if we want to isolate from their actual execution.
    # For /git/info, we want it to actually call git_utils on our temp repo.
    def test_git_info_success_with_real_repo(self):
        # No mocks for git_utils, let it run against self.local_repo_dir
        with app.app_context(): # Ensure current_app context for git_utils if they use it
            response = self.app_client.get('/git/info')

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        
        self.assertEqual(data['current_branch_or_commit'], 'main')
        # Branches will include local 'main', 'new-feature-branch', and remotes
        self.assertIn('main', data['branches'])
        self.assertIn('new-feature-branch', data['branches']) # This is local due to setup
        self.assertIn('remotes/origin/main', data['branches'])
        self.assertIn('remotes/origin/new-feature-branch', data['branches'])
        self.assertEqual(data['tags'], []) # No tags created in setup
        self.assertTrue(len(data['log']) > 0) # Should have some commits
        self.assertIsNone(data['errors']['branches_error']) # Expect no errors

    def test_git_info_repo_not_found_override_config(self):
        # Temporarily set an invalid path for this specific test
        original_path = app.config['GIT_REPO_PATH']
        app.config['GIT_REPO_PATH'] = '/invalid/path/for/this/specific/test'
        try:
            response = self.app_client.get('/git/info')
            self.assertEqual(response.status_code, 500)
            data = json.loads(response.data)
            self.assertIn("Git repository path not configured or not a valid directory", data['error'])
        finally:
            app.config['GIT_REPO_PATH'] = original_path # Restore

    # Test fetch with real git repo
    def test_git_fetch_success_with_real_repo(self):
        # No mock for git_utils.fetch
        with app.app_context():
            response = self.app_client.post('/git/fetch')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['message'], "Fetch successful.")
        # Stdout/stderr from git fetch can vary, so just check presence or basic content
        self.assertIsNotNone(data['stdout'])

    # Test checkout of a local branch with real git repo
    def test_git_checkout_local_branch_success_with_real_repo(self):
        # Checkout 'new-feature-branch' which was created and pushed, then fetched (implicitly by setup)
        # and exists locally because we created it locally.
        with app.app_context():
            response = self.app_client.post('/git/checkout', json={'ref': 'new-feature-branch'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['message'], "Checkout to 'new-feature-branch' successful.")

        # Verify current branch is indeed 'new-feature-branch'
        current_branch, _, _ = git_utils.get_current_branch_or_commit(self.local_repo_dir)
        self.assertEqual(current_branch, 'new-feature-branch')

    def test_git_checkout_remote_branch_creates_local_tracking_branch(self):
        # This is the core test for the new functionality
        # Setup:
        # - 'remotes/origin/new-feature-branch' exists due to _init_git_repos and push.
        # - Local 'new-feature-branch' also exists due to _init_git_repos.
        # To test the *creation* of local tracking branch, we need a remote branch
        # that does *not* yet exist locally.

        # 1. Create another branch on the remote, not yet present locally
        REMOTE_ONLY_BRANCH = "remote-only-feature"
        self._run_git_command_in_path(['checkout', '-b', REMOTE_ONLY_BRANCH], self.local_repo_dir)
        with open(os.path.join(self.local_repo_dir, 'remote_only.txt'), 'w') as f:
            f.write('remote only content')
        self._run_git_command_in_path(['add', 'remote_only.txt'], self.local_repo_dir)
        self._run_git_command_in_path(['commit', '-m', 'Commit for remote only branch'], self.local_repo_dir)
        self._run_git_command_in_path(['push', 'origin', REMOTE_ONLY_BRANCH], self.local_repo_dir)
        # Switch back to main and delete the local version of REMOTE_ONLY_BRANCH
        self._run_git_command_in_path(['checkout', 'main'], self.local_repo_dir)
        self._run_git_command_in_path(['branch', '-D', REMOTE_ONLY_BRANCH], self.local_repo_dir)

        # 2. Fetch so the local repo is aware of remotes/origin/remote-only-feature
        with app.app_context():
            fetch_resp = self.app_client.post('/git/fetch')
        self.assertEqual(fetch_resp.status_code, 200)

        # 3. Call checkout for the remote branch
        remote_ref_name = f"remotes/origin/{REMOTE_ONLY_BRANCH}"
        with app.app_context():
            response = self.app_client.post('/git/checkout', json={'ref': remote_ref_name})

        self.assertEqual(response.status_code, 200, msg=f"Checkout failed. Response data: {response.data.decode() if response.data else 'No data'}")
        data = json.loads(response.data)
        self.assertEqual(data['message'], f"Checkout to '{remote_ref_name}' successful.")

        # 4. Assertions
        # a. Local branch REMOTE_ONLY_BRANCH now exists
        stdout_list, _, retcode_list = git_utils.run_git_command(['branch', '--list', REMOTE_ONLY_BRANCH], self.local_repo_dir)
        self.assertEqual(retcode_list, 0)
        self.assertIn(REMOTE_ONLY_BRANCH, stdout_list)

        # b. Current branch is REMOTE_ONLY_BRANCH
        current_branch, _, retcode_cb = git_utils.get_current_branch_or_commit(self.local_repo_dir)
        self.assertEqual(retcode_cb, 0)
        self.assertEqual(current_branch, REMOTE_ONLY_BRANCH)

        # c. New local branch REMOTE_ONLY_BRANCH tracks origin/REMOTE_ONLY_BRANCH
        # Use: git rev-parse --abbrev-ref --symbolic-full-name @{u}
        # This command returns the upstream tracking branch, e.g., "origin/remote-only-feature"
        # Ensure we are on the branch first for @{u} to resolve correctly
        self._run_git_command_in_path(['checkout', REMOTE_ONLY_BRANCH], self.local_repo_dir)

        tracking_branch_stdout, _, retcode_track = git_utils.run_git_command(
            ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'],
            self.local_repo_dir
        )
        self.assertEqual(retcode_track, 0, msg=f"Could not get tracking info. Stderr: {_}")
        self.assertEqual(tracking_branch_stdout, f"origin/{REMOTE_ONLY_BRANCH}")

    def test_git_checkout_missing_ref_with_real_repo(self):
        # No mock for os.path.isdir needed as GIT_REPO_PATH is valid
        with app.app_context():
            response = self.app_client.post('/git/checkout', json={}) # No 'ref'
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn("Request body must be JSON and contain a 'ref' field.", data['error'])

        with app.app_context():
            response = self.app_client.post('/git/checkout', json={'ref': ''}) # Empty 'ref'
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertIn("Reference name ('ref') must not be empty.", data['error'])

    # Test pull with real git repo
    def test_git_pull_success_with_real_repo(self):
        # Ensure current branch (main) is tracking origin/main from setup
        with app.app_context():
            response = self.app_client.post('/git/pull')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['message'], "Pull successful.")
        # Stdout for pull on an up-to-date branch is usually "Already up to date."
        self.assertIn("Already up to date.", data['stdout'])


    @patch('subprocess.run')
    def test_service_restart_success(self, mock_subprocess_run):
        # This test remains largely the same, using mocks for subprocess
        mock_process = MagicMock()
        mock_process.stdout = "Main app restarted"
        mock_process.stderr = ""
        mock_process.returncode = 0
        mock_subprocess_run.return_value = mock_process
        
        # Use the test client from setUp
        response = self.app_client.post('/service/restart')
        data = json.loads(response.data)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['message'], 'Main application restart command executed successfully.')
        
        # Check that subprocess.run was called with the correct command from app.config
        # Ensure the command used here matches what's in app.config during this test
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
