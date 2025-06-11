import subprocess
import shlex

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
    safe_ref_name = shlex.quote(ref_name)

    if ref_name.startswith('remotes/'):
        # Potential remote branch. Example: remotes/origin/my-feature
        parts = ref_name.split('/')
        if len(parts) > 2: # Minimum remotes/<remote_name>/<branch_name>
            simple_branch_name = parts[-1]
            safe_simple_branch_name = shlex.quote(simple_branch_name)

            # Check if a local branch with this simple name already exists
            # `git branch --list <branch_name>` outputs the branch name if it exists, or empty otherwise.
            stdout_check, _, retcode_check = run_git_command(['branch', '--list', safe_simple_branch_name], repo_path)

            if retcode_check == 0 and not stdout_check.strip():
                # Local branch does not exist, create it and track the remote branch
                # Command: git checkout -b <simple_branch_name> <original_remote_ref_name>
                return run_git_command(['checkout', '-b', safe_simple_branch_name, safe_ref_name], repo_path)
            else:
                # Local branch exists, or there was an error checking. Fallback to direct checkout.
                # This will checkout the existing local branch if simple_branch_name matches a local one,
                # or attempt to checkout the remote ref directly (which might lead to detached HEAD if not what user wants,
                # but aligns with standard git behavior if local branch of same name isn't the target).
                # The prompt specified "git checkout <ref_name>" for this case.
                return run_git_command(['checkout', safe_ref_name], repo_path)
        else:
            # Malformed remote branch name, fallback to direct checkout
            return run_git_command(['checkout', safe_ref_name], repo_path)
    else:
        # Not a remote-looking branch, proceed with normal checkout
        return run_git_command(['checkout', safe_ref_name], repo_path)

def pull(repo_path):
    """Performs git pull on the current branch."""
    return run_git_command(['pull'], repo_path)

def get_current_branch_or_commit(repo_path):
    """Gets the current active branch or commit hash if detached HEAD."""
    # Try to get branch name
    stdout, stderr, retcode = run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'], repo_path)
    if retcode == 0 and stdout != 'HEAD':
        return stdout, stderr, retcode
    
    # If HEAD, likely detached, get commit hash
    return run_git_command(['rev-parse', 'HEAD'], repo_path)
