"""
Utilities for downloading checkpoint data from HuggingFace or from a local run.

NOTE: Assumes that models have been uploaded to HuggingFace via Pico.
"""

import os
import re
import torch
import yaml

from functools import lru_cache

from huggingface_hub import hf_hub_download, snapshot_download, HfApi
from datasets import load_from_disk

from src.utils.initialization import CheckpointLocation
from src.utils.exceptions import InvalidStepError


def get_checkpoint_states(
    checkpoint_location: CheckpointLocation, step: int = None, data_split: str = "val"
) -> dict:
    """
    Returns all the available checkpoint states available for a given step, data split, in a given
    run path or a given HuggingFace repository and branch. We assume that the checkpoint states are
    stored in the checkpoint folder in the checkpoint folder (generated by Pico) and has the
    following structure:

    learning_dynamics/
        checkpoint/
            step_<step>/
                learning_dynamics/
                    train_activations.pt
                    train_weights.pt
                    train_gradients.pt
                    train_data/
                        [...]
                    val_activations.pt
                    val_weights.pt
                    val_gradients.pt

    Args:
        checkpoint_location: CheckpointLocation
        step: Step to get data from
        data_split: Data split to get data from (i.e. "train" or "val")

    Returns:
        dict: Dictionary containing the checkpoint states for a given step and data split.

            For instance, if the data split is "train", the dictionary will have the following
            structure.
            {
                "activations": {
                    "model.0.mlp": torch.Tensor, # model activations across layer
                    [...]
                },
                "weights": {
                    "model.0.mlp": torch.Tensor, # model weights across layer
                    [...]
                },
                "gradients": {
                    "model.0.mlp": torch.Tensor, # model gradients across layer
                    [...]
                },
                "dataset": torch.utils.data.Dataset,
            }
    """
    if checkpoint_location.is_remote:
        return _download_checkpoint_states(
            checkpoint_location.repo_id, checkpoint_location.branch, step, data_split
        )
    else:
        return _load_checkpoint_states(checkpoint_location.run_path, step, data_split)


def get_training_config(checkpoint_location: CheckpointLocation) -> dict:
    """
    Loads in the training config from a checkpoint location.
    """
    if checkpoint_location.is_remote:
        return _download_training_config(
            checkpoint_location.repo_id, checkpoint_location.branch
        )
    else:
        return _load_training_config(checkpoint_location.run_path)


####################
#
# Helper Functions for loading/setting up learning dynamics data
#
####################

# -----------------
# Load Training Config
# -----------------


def _load_training_config(run_path: str) -> dict:
    """
    Loads in the training config from the run path. If using Pico, the run_config will always be
    stored as training_config.yaml in the root of the run path.
    """
    return yaml.safe_load(open(os.path.join(run_path, "training_config.yaml"), "r"))


def _download_training_config(repo_id: str, branch: str) -> dict:
    """
    Downloads the training config from the HuggingFace repository. If using Pico, the run_config
    will always be stored as training_config.yaml in the root of the repository.
    """

    # Get the training_config.yaml file from the HuggingFace repository
    training_config_path = hf_hub_download(
        repo_id=repo_id, revision=branch, filename="training_config.yaml"
    )

    return yaml.safe_load(open(training_config_path, "r"))


# -----------------
# HuggingFace API Helper Functions
# -----------------


@lru_cache()
def _get_learning_dynamics_commits(repo_id: str, branch: str, data_split: str) -> dict:
    """
    Get the list of commits for a given repository and branch on HuggingFace that store out
    checkpoint states for computing learning dynamics. We cache the results to avoid making too
    many requests to the HuggingFace API.

    Args:
        repo_id: HuggingFace repository ID
        branch: Branch to get commits from
        data_split: Data split to get commits for

    Returns:
        dict: Dictionary containing the commits for the given data split.
    """

    api = HfApi()

    # NOTE: this pattern is specific to how Pico saves the learning dynamics data.
    pattern = rf"Saving Learning Dynamics Data \({data_split}\) -- Step (\d+)"

    # Create defaultdict to store commits by type and step
    learning_dynamics_commits = dict()

    # Get all commits
    commits = api.list_repo_commits(repo_id=repo_id, revision=branch)

    # Process each commit
    for commit in commits:
        match = re.search(pattern, commit.title)
        if match:
            step = int(match.group(1))  # step number is now in group 1

            learning_dynamics_commits[step] = {
                "commit_id": commit.commit_id,
                "date": commit.created_at,
                "message": commit.title,
            }

    return learning_dynamics_commits


# -----------------
# Load Learning Dynamics Data
# -----------------


def _get_checkpoint_states_dict(
    learning_dynamics_path: str, data_split: list[str]
) -> dict:
    """
    Load in the checkpoint states from the directory at learning_dynamics_path. This is a helper
    function called on by _load_checkpoint_states and _download_checkpoint_states to load in the
    stored checkpoint states for a given data split.

    Args:
        learning_dynamics_path: Path to the learning dynamics directory that stores the model
            checkpoint states for computing learning dynamics.
        data_split: Data split to get data from (i.e. "train" or "val")

    Returns:
        states: Dictionary containing the loaded checkpoint states
    """
    # load the data
    states = {}
    for state_type in ["activations", "weights", "gradients"]:
        file_path = os.path.join(
            learning_dynamics_path, f"{data_split}_{state_type}.pt"
        )
        if os.path.exists(file_path):
            states[state_type] = torch.load(file_path)

    dataset_path = os.path.join(learning_dynamics_path, f"{data_split}_data")
    if os.path.exists(dataset_path):
        states["dataset"] = load_from_disk(dataset_path)

    return states


def _load_checkpoint_states(run_path: str, step: int, data_split: str) -> dict:
    """
    Load checkpoint states from a local run path for a given step and data split.

    This is a helper function called on by get_checkpoint_states to load in the checkpoint states
    from a local run path.

    Args:
        run_path: Path to the run
        step: Step to get data from
        data_split: Data split to get data from (e.g. "train", "val")

    Returns:
        dict: Dictionary containing the learning dynamics data for the given step and data split.
    """

    # ensure that the run_path is a valid path
    if not os.path.exists(run_path):
        raise ValueError(f"Run path {run_path} does not exist")

    checkpoint_path = os.path.join(run_path, "checkpoint")
    # ensure that the run_path contains a checkpoint folder
    if not os.path.exists(checkpoint_path):
        raise ValueError(f"Run path {run_path} does not contain a checkpoint folder")

    step_path = os.path.join(checkpoint_path, f"step_{step}")

    # ensure that the step exists
    if not os.path.exists(step_path):
        raise InvalidStepError(
            step, f"Step {step} does not exist in run path {run_path}"
        )

    # states to compute learning dynamics are stored in the learning_dynamics folder
    learning_dynamics_path = os.path.join(step_path, "learning_dynamics")
    return _get_checkpoint_states_dict(learning_dynamics_path, data_split)


def _download_checkpoint_states(
    repo_id: str, branch: str, step: int, data_split: str
) -> dict:
    """
    Download checkpoint states for a specific commit and step and data split.

    Args:
        repo_id: HuggingFace repository ID
        branch: Branch to get commits from
        step: Step to get data from
        data_split: Data split to get data from (i.e. "train" or "val")

    Returns:
        dict: Dictionary containing the loaded learning dynamics data
    """

    # get all of the commits in the branch
    learning_dynamics_commits = _get_learning_dynamics_commits(
        repo_id, branch, data_split
    )

    if step not in learning_dynamics_commits:
        raise InvalidStepError(
            step, f"Step {step} does not exist in {repo_id} on branch {branch}"
        )

    commit = learning_dynamics_commits[step]
    checkpoint_dir = snapshot_download(
        repo_id=repo_id,
        revision=commit["commit_id"],
    )

    # states to compute learning dynamics are stored in the learning_dynamics folder
    learning_dynamics_path = os.path.join(checkpoint_dir, "learning_dynamics")
    return _get_checkpoint_states_dict(learning_dynamics_path, data_split)
