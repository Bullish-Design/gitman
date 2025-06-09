from pathlib import Path
import sys
import os
import time
from datetime import datetime

alembic_version_dir = None
alembic_replace_text = "def upgrade() -> None:"
drop_table_lines = """def upgrade() -> None:
    op.drop_table(None)
    
    """
## Get latest alembic version:


def find_matching_files(directory, pattern, file_ext: str = ".py"):
    """
    Find all files in a directory that match a given pattern in their filename.

    Args:
        directory (str): Path to the directory to search
        pattern (str): Pattern to match in filenames

    Returns:
        list: List of Path objects for matching files
    """
    directory_path = Path(directory)
    matching_files = []

    for file_path in directory_path.glob(f"**/*{file_ext}"):
        if file_path.is_file() and pattern in file_path.name:
            matching_files.append(file_path)

    return matching_files


def filter_by_creation_time(file_paths, start_time, end_time):
    """
    Filter a list of file paths by creation time within a specific time window.
    Sort the results so the most recently created file is first.

    Args:
        file_paths (list): List of Path objects to filter
        start_time (float): Start time in seconds since epoch
        end_time (float): End time in seconds since epoch

    Returns:
        list: List of Path objects for files created within the time window,
              sorted by creation time (newest first)
    """
    filtered_files = []

    # Store files with their creation times for sorting
    files_with_times = []

    for file_path in file_paths:
        creation_time = os.path.getctime(file_path)
        if start_time <= creation_time <= end_time:
            files_with_times.append((file_path, creation_time))

    # Sort by creation time (descending order)
    files_with_times.sort(key=lambda x: x[1], reverse=True)

    # Extract just the file paths in sorted order
    filtered_files = [file_path for file_path, _ in files_with_times]

    return filtered_files


def replace_lines(file: Path, replaced_text: str, replacing_text: str):
    """Reads in the lines from the file. Finds the line that matches 'replaced_text',
    replaces it with 'replacing_text'. Insert additional lines if needed."""

    # Read all lines from the file
    with open(file, "r") as f:
        lines = f.readlines()

    # Flag to check if replacement was made
    replacement_made = False

    # Process each line
    for i in range(len(lines)):
        if replaced_text in lines[i]:
            print(f"    Found text on line {i}: {lines[i]}")
            lines[i] = replacing_text + "\n"
            print(f"            Replaced Text: {lines[i]}")
            replacement_made = True
            break

    # If replacing_text contains multiple lines, split and insert them
    if "\n" in replacing_text and replacement_made:
        # Get the index where replacement was made
        replacement_index = next(
            i for i, line in enumerate(lines) if replacing_text in line
        )

        # Remove the single line that was replaced
        lines.pop(replacement_index)

        # Split the replacing text into multiple lines
        new_lines = replacing_text.split("\n")

        # Insert each new line at the appropriate position
        for j, new_line in enumerate(new_lines):
            # if new_line:  # Skip empty lines
            lines.insert(replacement_index + j, new_line + "\n")

    # Write the modified lines back to the file
    with open(file, "w") as f:
        f.writelines(lines)


def get_version():
    match_str = "reset"
    alembic_resets = find_matching_files(alembic_version_dir, match_str)
    now = time.time()
    past_minute = now - 600
    recent_versions = filter_by_creation_time(alembic_resets, past_minute, now)
    print(f"\nRecent Versions:")
    for ver in recent_versions:
        print(f"    {ver}")
    return recent_versions


def insert_delete_table_commands():
    print(f"\n** Inserting drop table commands in alembic upgrade **")
    alembic_file = get_version()
    print(f"       Reset file: {alembic_file[0].name}\n")
    replace_text = replace_lines(
        alembic_file[0], alembic_replace_text, drop_table_lines
    )
    print(f"\nReplaced text in Alembic version - please run: alembic upgrade head")
