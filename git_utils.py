import subprocess
import shlex
import logging

logger = logging.getLogger(__name__)

# Generic helper to run Git commands
def run_git_command(command_args, repo_path):
    """
    Runs a Git command in the specified repository path.
    Returns a tuple: (stdout, stderr, return_code)
    """
    try:
        process = subprocess.Popen(
            ['git'] + command_args,
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate()
        return stdout.strip(), stderr.strip(), process.returncode
    except FileNotFoundError:
        return "", "Git command not found. Ensure Git is installed and in PATH.", -1
    except Exception as e:
        return "", f"An unexpected error occurred: {str(e)}", -2

def fetch(repo_path):
    """Runs git fetch --all in the repository."""
    return run_git_command(['fetch', '--all', '--prune'], repo_path)

def get_branches(repo_path):
    """Lists all local and remote branches."""
    # Using --format='%(refname:short)' to get clean branch names
    stdout, stderr, retcode = run_git_command(['branch', '-a', "--format='%(refname:short)'"], repo_path)
    if retcode == 0:
        # Filter out empty lines or lines that are not branch names (e.g., HEAD pointer)
        branches = [line for line in stdout.split('\n') if line and not line.startswith('HEAD ->')]
        return branches, stderr, retcode
    return stdout, stderr, retcode


def get_tags(repo_path):
    """Lists all tags."""
    return run_git_command(['tag', '-l'], repo_path)

def get_log(repo_path, count=20):
    """Gets the commit log (e.g., git log --oneline -n count)."""
    return run_git_command(['log', '--oneline', '--decorate', f'-n{count}'], repo_path)

def checkout(repo_path, ref_name):
    """
    Performs git checkout <ref_name>.
    If ref_name is a remote branch (e.g., remotes/origin/feature),
    it attempts to check it out as a local tracking branch.
    """
    logger.info(f"checkout: Received ref_name='{ref_name}' for repo_path='{repo_path}'")
    safe_ref_name = shlex.quote(ref_name)
    final_command_args = []

    if ref_name.startswith('remotes/'):
        logger.info(f"checkout: '{ref_name}' appears to be a remote branch.")
        parts = ref_name.split('/')
        if len(parts) > 2: # Minimum remotes/<remote_name>/<branch_name>
            simple_branch_name = parts[-1]
            safe_simple_branch_name = shlex.quote(simple_branch_name)
            logger.info(f"checkout: Extracted simple_branch_name='{simple_branch_name}' from remote ref.")

            branch_check_cmd = ['branch', '--list', safe_simple_branch_name]
            logger.info(f"checkout: Checking for existing local branch '{simple_branch_name}' with command: git {' '.join(branch_check_cmd)}")
            stdout_check, stderr_check, retcode_check = run_git_command(branch_check_cmd, repo_path)
            logger.info(f"checkout: 'git branch --list' stdout: '{stdout_check}', stderr: '{stderr_check}', retcode: {retcode_check}")

            if retcode_check == 0: # 'git branch --list' command executed successfully
                if not stdout_check.strip():
                    logger.info(f"checkout: Local branch '{simple_branch_name}' not found. Preparing to create new tracking branch.")
                    final_command_args = ['checkout', '-b', safe_simple_branch_name, safe_ref_name]
                else:
                    logger.info(f"checkout: Local branch '{simple_branch_name}' exists. Preparing to checkout local branch.")
                    final_command_args = ['checkout', safe_simple_branch_name]
            else:
                logger.warning(f"checkout: 'git branch --list {safe_simple_branch_name}' failed (retcode: {retcode_check}). Falling back to checkout original ref_name.")
                final_command_args = ['checkout', safe_ref_name]
        else:
            logger.warning(f"checkout: Remote branch name '{ref_name}' seems malformed. Falling back to direct checkout.")
            final_command_args = ['checkout', safe_ref_name]
    else:
        logger.info(f"checkout: '{ref_name}' is not a remote branch. Proceeding with normal checkout.")
        final_command_args = ['checkout', safe_ref_name]

    logger.info(f"checkout: Executing final checkout command: git {' '.join(final_command_args)}")
    stdout, stderr, retcode = run_git_command(final_command_args, repo_path)
    logger.info(f"checkout: Final checkout stdout: '{stdout}', stderr: '{stderr}', retcode: {retcode}")
    return stdout, stderr, retcode

def pull(repo_path):
    """Performs git pull on the current branch."""
    logger.info(f"pull: Attempting pull for repo_path='{repo_path}'")

    logger.info(f"pull: Determining current branch/commit before pull...")
    current_branch, cb_stderr, cb_retcode = get_current_branch_or_commit(repo_path)
    if cb_retcode == 0:
        logger.info(f"pull: Pre-pull status - Current branch/commit: '{current_branch}'")
    else:
        logger.warning(f"pull: Pre-pull status - Error determining current branch/commit. Stderr: '{cb_stderr}', Retcode: {cb_retcode}")
        # Potentially, one might choose not to proceed with pull if branch cannot be determined,
        # but current behavior is to attempt pull regardless.

    pull_command_args = ['pull']
    logger.info(f"pull: Executing command: git {' '.join(pull_command_args)}")

    stdout, stderr, retcode = run_git_command(pull_command_args, repo_path)
    logger.info(f"pull: 'git pull' stdout: '{stdout}', stderr: '{stderr}', retcode: {retcode}")

    return stdout, stderr, retcode

def get_current_branch_or_commit(repo_path):
    """Gets the current active branch or commit hash if detached HEAD."""
    # Try to get branch name
    stdout, stderr, retcode = run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'], repo_path)
    if retcode == 0 and stdout != 'HEAD':
        return stdout, stderr, retcode
    
    # If HEAD, likely detached, get commit hash
    return run_git_command(['rev-parse', 'HEAD'], repo_path)
