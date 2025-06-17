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
    safe_ref_name = shlex.quote(ref_name) # This is the original ref, quoted, e.g., 'origin/feature/foo'

    # --- New Flexible Remote Detection Logic ---
    # Attempt to list remotes to handle cases like 'origin/feature-branch' directly
    remote_list_stdout, remote_list_stderr, remote_list_retcode = run_git_command(['remote'], repo_path)
    if remote_list_retcode == 0 and remote_list_stdout:
        known_remotes = remote_list_stdout.split()
        logger.info(f"checkout: Found known remotes: {known_remotes}")
        for remote_name in known_remotes:
            prefix = f"{remote_name}/"
            if ref_name.startswith(prefix):
                logger.info(f"checkout: Identified '{ref_name}' as prefixed by known remote '{remote_name}'.")
                simple_branch_name = ref_name[len(prefix):]

                if not simple_branch_name:
                    logger.warning(f"checkout: Extracted empty simple_branch_name from '{ref_name}' with prefix '{prefix}'. Skipping this remote.")
                    continue

                safe_simple_branch_name = shlex.quote(simple_branch_name)
                # The tracking ref for 'git checkout -b <local_name> <tracking_ref>' is the original, full ref_name.
                # safe_ref_name is already shlex.quote(ref_name)

                logger.info(f"checkout: Extracted simple_branch_name='{simple_branch_name}'. Checking for existing local branch.")

                branch_check_cmd = ['branch', '--list', safe_simple_branch_name]
                logger.info(f"checkout: Checking for existing local branch '{simple_branch_name}' with command: git {' '.join(branch_check_cmd)}")
                stdout_check, stderr_check, retcode_check = run_git_command(branch_check_cmd, repo_path)
                logger.info(f"checkout: 'git branch --list' stdout: '{stdout_check}', stderr: '{stderr_check}', retcode: {retcode_check}")

                final_checkout_cmd_args = []
                if retcode_check == 0: # 'git branch --list' command executed successfully
                    if not stdout_check.strip(): # Local branch does NOT exist
                        logger.info(f"checkout: Local branch '{simple_branch_name}' not found. Preparing to create new tracking branch from '{ref_name}'.")
                        final_checkout_cmd_args = ['checkout', '-b', safe_simple_branch_name, safe_ref_name]
                    else: # Local branch DOES exist
                        logger.info(f"checkout: Local branch '{simple_branch_name}' exists. Preparing to checkout this local branch.")
                        final_checkout_cmd_args = ['checkout', safe_simple_branch_name]
                else: # 'git branch --list' command failed
                    logger.warning(f"checkout: 'git branch --list {safe_simple_branch_name}' failed (retcode: {retcode_check}). Falling back to checkout original ref '{ref_name}'.")
                    final_checkout_cmd_args = ['checkout', safe_ref_name]

                logger.info(f"checkout: Executing command (from new logic): git {' '.join(final_checkout_cmd_args)}")
                stdout, stderr, retcode = run_git_command(final_checkout_cmd_args, repo_path)
                logger.info(f"checkout: Command (from new logic) stdout: '{stdout}', stderr: '{stderr}', retcode: {retcode}")
                return stdout, stderr, retcode # Crucial: return after handling
    else:
        logger.warning(f"checkout: Could not retrieve remote names (retcode: {remote_list_retcode}, stderr: {remote_list_stderr}). Proceeding with 'remotes/' prefix check or direct checkout.")
    # --- End of New Flexible Remote Detection Logic ---

    # --- Fallback to existing 'remotes/' prefix logic if new logic did not handle and return ---
    # This block is largely for refs that literally start with "remotes/"
    if ref_name.startswith('remotes/'):
        logger.info(f"checkout: (Fallback) '{ref_name}' appears to be a 'remotes/' prefixed branch.")
        parts = ref_name.split('/')
        # Example: remotes/origin/feature. parts[0]=remotes, parts[1]=origin, parts[2]=feature
        # We need at least 3 parts for a simple_branch_name (remotes/<remote_name>/<branch_name>)
        if len(parts) > 2:
            simple_branch_name_from_remotes_prefix = parts[-1] # Last part is the branch name
            safe_simple_branch_name_from_remotes_prefix = shlex.quote(simple_branch_name_from_remotes_prefix)
            logger.info(f"checkout: (Fallback) Extracted simple_branch_name='{simple_branch_name_from_remotes_prefix}' from 'remotes/' ref.")

            branch_check_cmd = ['branch', '--list', safe_simple_branch_name_from_remotes_prefix]
            logger.info(f"checkout: (Fallback) Checking for existing local branch '{simple_branch_name_from_remotes_prefix}' with command: git {' '.join(branch_check_cmd)}")
            stdout_check, stderr_check, retcode_check = run_git_command(branch_check_cmd, repo_path)
            logger.info(f"checkout: (Fallback) 'git branch --list' stdout: '{stdout_check}', stderr: '{stderr_check}', retcode: {retcode_check}")

            final_checkout_cmd_args = []
            if retcode_check == 0: # 'git branch --list' command executed successfully
                if not stdout_check.strip():
                    logger.info(f"checkout: (Fallback) Local branch '{simple_branch_name_from_remotes_prefix}' not found. Preparing to create new tracking branch from '{ref_name}'.")
                    final_checkout_cmd_args = ['checkout', '-b', safe_simple_branch_name_from_remotes_prefix, safe_ref_name]
                else:
                    logger.info(f"checkout: (Fallback) Local branch '{simple_branch_name_from_remotes_prefix}' exists. Preparing to checkout this local branch.")
                    final_checkout_cmd_args = ['checkout', safe_simple_branch_name_from_remotes_prefix]
            else:
                logger.warning(f"checkout: (Fallback) 'git branch --list {safe_simple_branch_name_from_remotes_prefix}' failed (retcode: {retcode_check}). Falling back to checkout original ref '{ref_name}'.")
                final_checkout_cmd_args = ['checkout', safe_ref_name]

            logger.info(f"checkout: Executing command (from fallback 'remotes/' logic): git {' '.join(final_checkout_cmd_args)}")
            stdout, stderr, retcode = run_git_command(final_checkout_cmd_args, repo_path)
            logger.info(f"checkout: Command (from fallback 'remotes/' logic) stdout: '{stdout}', stderr: '{stderr}', retcode: {retcode}")
            return stdout, stderr, retcode
        else: # Malformed 'remotes/' ref like 'remotes/origin'
            logger.warning(f"checkout: (Fallback) 'remotes/' prefixed ref_name '{ref_name}' seems malformed. Falling back to direct checkout of '{ref_name}'.")
            # Fall through to the final direct checkout

    # --- Final direct checkout if no other logic handled it ---
    logger.info(f"checkout: No specific remote branch logic matched or fell through. Executing direct checkout for '{ref_name}'.")
    final_checkout_cmd_args = ['checkout', safe_ref_name]
    logger.info(f"checkout: Executing command (direct): git {' '.join(final_checkout_cmd_args)}")
    stdout, stderr, retcode = run_git_command(final_checkout_cmd_args, repo_path)
    logger.info(f"checkout: Command (direct) stdout: '{stdout}', stderr: '{stderr}', retcode: {retcode}")
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


def get_stale_local_branches(repo_path):
    """
    Identifies local Git branches that are stale (remote upstream gone) and
    categorizes them into 'safe_to_delete' (merged into the current main branch)
    or 'unsafe_stale' (not merged or has unpushed commits).

    Args:
        repo_path (str): The file system path to the Git repository.

    Returns:
        dict: A dictionary with two keys:
              "safe_to_delete": A list of branch names that are stale and merged.
              "unsafe_stale": A list of branch names that are stale but not merged
                              or have other reasons to be kept.
              Returns None if an error occurs during Git command execution.
    """
    # 1. Ensure remote-tracking branches are up-to-date
    logger.info("get_stale_local_branches: Attempting initial fetch.")
    fetch_stdout, fetch_stderr, fetch_retcode = fetch(repo_path)
    if fetch_retcode != 0:
        logger.error(f"get_stale_local_branches: Initial fetch failed. Stderr: {fetch_stderr}. Cannot reliably determine stale branches.")
        return None

    # 2. Determine the current main branch name (or commit if detached HEAD)
    logger.info("get_stale_local_branches: Determining current branch or commit.")
    main_branch_name, main_branch_stderr, main_branch_retcode = get_current_branch_or_commit(repo_path)
    if main_branch_retcode != 0:
        logger.error(f"get_stale_local_branches: Failed to determine current branch/commit. Stderr: {main_branch_stderr}. Cannot proceed.")
        return None
    logger.info(f"get_stale_local_branches: Current branch/commit is '{main_branch_name}'.")

    # Get all local branches with their upstream tracking status
    # %(refname:short) gives the branch name
    # %(upstream:trackgone) prints '[gone]' if the upstream branch has been deleted
    identified_stale_branches = []
    original_stale_check_command = ['branch', '--format=%(refname:short)%(upstream:trackgone)']
    stale_check_stdout, stale_check_stderr, stale_check_retcode = run_git_command(
        original_stale_check_command, repo_path
    )

    if stale_check_retcode != 0:
        # Check for specific error indicating unsupported %(upstream:trackgone)
        unrecognized_arg_error = "unrecognized %(upstream:trackgone) argument" # Common part of the error
        # Git versions might have slightly different error messages, e.g. "fatal: ..." or "error: ..."
        if unrecognized_arg_error in stale_check_stderr.lower(): # Make check case-insensitive
            logger.warning("Git version does not support %(upstream:trackgone). Using fallback for stale branch detection.")

            # Fallback logic
            # 1. Fetch (already done at the beginning, but can do again if desired, or ensure it's robust)
            # For robustness, let's ensure fetch --prune is done here for the fallback.
            logger.info("Fallback: Running git fetch --all --prune for fallback strategy.")
            fetch_fb_stdout, fetch_fb_stderr, fetch_fb_retcode = fetch(repo_path)
            if fetch_fb_retcode != 0:
                logger.warning(f"Fallback: Failed to fetch during fallback: {fetch_fb_stderr}. Stale branch list might be incomplete or inaccurate.")
                # Not returning None here, will attempt to proceed with possibly stale local data.

            # 2. Get all local branches
            logger.info("Fallback: Getting all local branches.")
            local_branches_stdout, local_branches_stderr, local_branches_retcode = run_git_command(
                ['branch', '--format=%(refname:short)'], repo_path
            )
            if local_branches_retcode != 0:
                logger.error(f"Fallback: Critical error getting local branches. Stderr: {local_branches_stderr}. Cannot proceed with fallback.")
                return None

            local_branches = [b.strip() for b in local_branches_stdout.splitlines() if b.strip()]
            logger.debug(f"Fallback: Found local branches: {local_branches}")

            # 3. Get all remote-tracking branches (full ref names)
            logger.info("Fallback: Getting all remote-tracking branches.")
            remote_tracking_stdout, remote_tracking_stderr, remote_tracking_retcode = run_git_command(
                ['branch', '-r', '--format=%(refname)'], repo_path # Using %(refname) for full path
            )
            if remote_tracking_retcode != 0:
                logger.error(f"Fallback: Critical error getting remote-tracking branches. Stderr: {remote_tracking_stderr}. Cannot proceed with fallback.")
                return None

            remote_tracking_branches_full_refs = set(rtb.strip() for rtb in remote_tracking_stdout.splitlines() if rtb.strip())
            logger.debug(f"Fallback: Remote tracking branches (full refs): {remote_tracking_branches_full_refs}")

            # 4. Initialize identified_stale_branches (already done)

            # 5. For each local_branch, check its upstream
            for local_branch_name in local_branches:
                if not local_branch_name: continue

                # (a) Get configured remote
                remote_config_stdout, _, remote_config_retcode = run_git_command(
                    ['config', f'branch.{local_branch_name}.remote'], repo_path
                )
                if remote_config_retcode != 0 or not remote_config_stdout.strip():
                    logger.warning(f"Fallback: Could not get remote for local branch '{local_branch_name}'. Assuming not stale by this check. Stderr (if any): {_}")
                    continue
                configured_remote = remote_config_stdout.strip()

                # (b) Get configured merge ref
                merge_ref_stdout, merge_ref_stderr, merge_ref_retcode = run_git_command(
                    ['config', f'branch.{local_branch_name}.merge'], repo_path
                )
                if merge_ref_retcode != 0 or not merge_ref_stdout.strip():
                    logger.warning(f"Fallback: Could not get merge ref for local branch '{local_branch_name}'. Assuming not stale by this check. Stderr (if any): {merge_ref_stderr}")
                    continue
                configured_merge_ref = merge_ref_stdout.strip() # e.g., "refs/heads/feature-X"

                # (c.i) Construct the expected remote-tracking branch name
                # Typically, merge ref "refs/heads/foo" corresponds to remote-tracking "refs/remotes/<remote>/foo"
                if configured_merge_ref.startswith('refs/heads/'):
                    simple_branch_part = configured_merge_ref[len('refs/heads/'):]
                    expected_remote_tracking_ref = f"refs/remotes/{configured_remote}/{simple_branch_part}"
                    logger.debug(f"Fallback: For local '{local_branch_name}', expected remote ref: '{expected_remote_tracking_ref}'")

                    # (c.ii) Check if this constructed remote-tracking branch name exists
                    if expected_remote_tracking_ref not in remote_tracking_branches_full_refs:
                        logger.info(f"Fallback: Identified stale branch '{local_branch_name}' because its remote tracking ref '{expected_remote_tracking_ref}' is missing.")
                        identified_stale_branches.append(local_branch_name)
                    else:
                        logger.debug(f"Fallback: Local branch '{local_branch_name}' has existing remote tracking ref '{expected_remote_tracking_ref}'. Not stale by this check.")
                else:
                    logger.warning(f"Fallback: Merge ref '{configured_merge_ref}' for branch '{local_branch_name}' does not start with 'refs/heads/'. Cannot determine corresponding remote ref reliably. Will not be marked stale by this check.")
        else:
            # Original command failed for reasons other than "unrecognized argument"
            logger.error(f"get_stale_local_branches: Failed to get branch statuses using primary method (%(upstream:trackgone)). Stderr: {stale_check_stderr}. Cannot proceed.")
            return None
    else:
        # Original command was successful (%(upstream:trackgone) is supported)
        logger.info("get_stale_local_branches: Successfully used %(upstream:trackgone) to check for stale branches.")
        for line in stale_check_stdout.splitlines():
            if '[gone]' in line:
                branch_name = line.replace('[gone]', '').strip()
                if branch_name:
                    identified_stale_branches.append(branch_name)
        logger.info(f"Identified stale branches (via primary method): {identified_stale_branches}")


    if not identified_stale_branches:
        logger.info("get_stale_local_branches: No stale branches identified.")
        return [] # Return empty list as per format

    # Determine which of the identified stale branches are merged into the main_branch_name
    logger.info(f"get_stale_local_branches: Checking merge status of identified stale branches against '{main_branch_name}'.")
    merged_branches = []
    merged_stdout, merged_stderr, merged_retcode = run_git_command(
        ['branch', '--merged', main_branch_name], repo_path
    )
    if merged_retcode != 0:
        logger.error(f"get_stale_local_branches: Failed to get list of branches merged into '{main_branch_name}'. Stderr: {merged_stderr}. Conservatively assuming no stale branches are merged.")
        # Continue with an empty merged_branches list, meaning all stale branches will be 'has_local_changes'
    else:
        merged_branches = [branch.strip().lstrip('* ') for branch in merged_stdout.splitlines()]
        logger.debug(f"Branches merged into '{main_branch_name}': {merged_branches}")

    result_list = []

    for branch_name in identified_stale_branches:
        # Avoid marking the current branch as safe to delete if it's somehow stale
        if branch_name == main_branch_name:
            logger.info(f"Branch '{branch_name}' is the current branch/HEAD and also marked stale. Classifying as 'has_local_changes'.")
            result_list.append({"name": branch_name, "status": "has_local_changes"})
            continue

        if branch_name in merged_branches:
            # This branch is stale and merged into the main_branch_name.
            # Per requirements, this is "safe_to_delete".
            # The subtask implies that "safe_to_delete" means fully merged to current HEAD.
            # The original code's "unsafe_stale" maps to "has_local_changes".
            result_list.append({"name": branch_name, "status": "safe_to_delete"})
        else:
            # This branch is stale but not merged into the main_branch_name.
            # This means it has local changes not yet integrated.
            result_list.append({"name": branch_name, "status": "has_local_changes"})

    # Branches with no upstream configured will not have '[gone]' and won't be in identified_stale_branches.
    # Branches with an existing upstream that is simply diverged are also not caught by '[gone]'.

    return result_list


def delete_local_branch(repo_path, branch_name):
    """
    Deletes a local Git branch using 'git branch -d <branch_name>'.

    Args:
        repo_path (str): The file system path to the Git repository.
        branch_name (str): The name of the local branch to delete.

    Returns:
        tuple: (success: bool, message: str)
               success is True if the command exit code is 0,
               message contains stdout if successful, or stderr if failed.
               Returns (False, "Branch name cannot be empty or must be a string.") if branch_name is invalid.
    """
    if not branch_name or not isinstance(branch_name, str):
        logger.error("delete_local_branch: Branch name is invalid.")
        return False, "Branch name cannot be empty or must be a string."

    command_args = ['branch', '-d', branch_name]

    logger.info(f"Attempting to delete branch '{branch_name}' in '{repo_path}' (non-forced).")
    stdout, stderr, retcode = run_git_command(command_args, repo_path)

    if retcode == 0:
        logger.info(f"Successfully deleted branch '{branch_name}'. Stdout: {stdout}")
        return True, stdout
    else:
        logger.error(f"Failed to delete branch '{branch_name}'. Stderr: {stderr}. Retcode: {retcode}")
        return False, stderr
