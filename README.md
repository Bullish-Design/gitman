# Gitman

Sync GitHub issues, discussions, and comments to local JSON files stored in your repository.

## Overview

Gitman is a simple command-line tool that keeps your GitHub events synchronized as plain JSON files in a `.gitman` directory at your repository root. Perfect for:

- Offline access to issues and discussions
- Building custom search and analytics tools
- Creating backups of your GitHub data
- Integrating GitHub data with other tools

## Features

- **Simple file-based storage** - Issues and discussions stored as individual JSON files
- **Incremental syncing** - Only fetches updates since last sync (configurable)
- **Full GitHub API support** - Uses REST API for issues, GraphQL for discussions
- **Rich CLI** - Beautiful terminal output with progress indicators
- **No dependencies on external services** - Just you, GitHub, and local files

## Installation

```bash
# Clone and install locally
git clone https://github.com/Bullish-Design/gitman.git
cd gitman
pip install -e .
```

## Quick Start

### 1. Set up authentication

```bash
export GITHUB_TOKEN=ghp_...  # Your GitHub Personal Access Token
export GITHUB_REPO=owner/repo  # Repository to sync
```

Your token needs the following scopes:
- `repo` - For accessing private repositories and issues
- `read:discussion` - For reading discussions

### 2. Initialize .gitman directory

```bash
gitman init
```

This creates the following structure:
```
.gitman/
├── issues/              # One JSON file per issue
├── issue_comments/      # Comments organized by issue number
├── discussions/         # One JSON file per discussion
├── discussion_comments/ # Comments organized by discussion number
└── sync_state.json      # Tracks last sync timestamps
```

### 3. Sync your data

```bash
# Sync everything (incremental)
gitman sync

# Full sync (fetch all data)
gitman sync --full

# Sync only issues
gitman sync --issues-only

# Sync only discussions
gitman sync --discussions-only

# Sync specific issue
gitman sync --issue 123

# Sync specific discussion
gitman sync --discussion 456
```

### 4. Check status

```bash
gitman status
```

## Usage Examples

```bash
# Initialize in a specific directory
gitman -d /path/to/repo init

# Sync a different repository
gitman -r owner/other-repo sync

# Use token from different env var or pass directly
export GITHUB_TOKEN=ghp_another_token
gitman sync
```

## Data Structure

### Issues
Each issue is stored as `.gitman/issues/{number}.json` with the full GitHub API response, including:
- Title, body, state, labels
- Author, assignees, milestone
- Creation and update timestamps
- Reactions, comments count

### Issue Comments
Comments are stored as `.gitman/issue_comments/{issue_number}/{comment_id}.json`

### Discussions
Each discussion is stored as `.gitman/discussions/{number}.json` with:
- Title, body, category
- Author, labels, upvotes
- Answer status
- Creation and update timestamps

### Discussion Comments
Comments are stored as `.gitman/discussion_comments/{discussion_number}/{comment_id}.json`

## Library Usage

You can also use Gitman as a Python library:

```python
from gitman import GitHubClient, FileStore, SyncManager

# Initialize components
client = GitHubClient(token="ghp_...")
store = FileStore()
sync_manager = SyncManager(client, store, "owner", "repo")

# Sync everything
sync_manager.sync_all()

# Load an issue
issue = store.load_issue(123)

# Get statistics
stats = store.get_stats()
print(f"Total issues: {stats['issues']}")
```

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/
```

## License

MIT License - see LICENSE file for details
