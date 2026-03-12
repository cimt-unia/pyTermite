## [unreleased]

### 📚 Documentation

- Fix readthedocs build
- Remove environment.yml from readthedocs post_checkout step
- Avoid dirty Git index issues in readthedocs build

### ⚙️ Miscellaneous Tasks

- Update changelog

## [0.0.2] - 2026-03-11

### 🚀 Features

- Add cli and logging
- Add interactive mode to keep connection alive
- Enable user interrupt for scanning
- Add command to start and stop recordings
- Add option to set name manually for WiredConnection

### 🐛 Bug Fixes

- Await getting the name of connection for commands
- Retrieve version at runtime and throw meaningful error when \_\_version\_\_ is not available

### 🚜 Refactor

- Make helper functions for cli private
- Fix typing for commands
- Pre-commit fixes
- Remove custom timeout behaviour

### 📚 Documentation

- Add missing docstrings
- Add documentation with Sphinx
- Add developer guide, cli documentation and quickstart
- Update sphinx config
- Update page titles
- Update docs
- Remove whitespace and comments on index page of docs
- Add changelog

### ⚡ Performance

- Add explicit timeout to request in commands.py:get_preset_status

### 🎨 Styling

- Fix typing errors
- Follow lint rules
- Fix after running pre-commit
- Pre-commit fixes
- Apply markdown formatting

### 🧪 Testing

- Add tests
- Fix tests by providing an asynchronous name property for DummyWiredConnection
- Update tox config

### ⚙️ Miscellaneous Tasks

- Add Code of Conduct
- Add dev requirements
- Add contributing guidelines
- Add coverage config
- Remove linting and formatting for docs
- Add tox
- Enable pre-commit
- Remove docs directory from type checks
- Update pre-commit config
- Add readthedocs config for documentation building and publishing
- Add GitHub action for test running
- Pin github action version to full-length commit SHA
- Fix requirements file path for readthedocs building
- Add docs dependencies to readthedocs config
- Move dev dependencies to dependency-groups
- Update README
- Install package in readthedocs build to enable automatic build of api reference
- Fix docs building by installing the package
- Add branch option for coverage
- Add config for codecov
- Run tests only if necessary
- Add flags to codecov upload
- Replace codecov flags with components
- Restructure dependency groups
- Add labels for tox environments
- Remove dev requirements file to facilitate using of dependency groups
- Add dependabot config
- Add pygrep-hooks to ruff config
- Add \_\_init\_\_.py for tests
- Add linting and CI as GitHub Workflows
- Add config for git-cliff
- Add concurrency for tests workflow
- Fix linting workflow
- Fix CI workflow
- Update changelog
- Add needs statements to CI workflow to ensure correct job order
- Run linting workflow only on dev branch
- Fix concurrency groups in GitHub workflows
- Fix deadlock due to same job and workflow name
- Give explicit concurrency names
- Enable signed commits from github-actions[bot]
- Run tests only on dev branch when not run from workflow_call or workflow_dispatch
- Let tests and linting run concurrently during CI workflow
- Add project urls
- Add release workflow
- Fix nested workflow permissions
- Add mdformat step before committing changelog
- Run CI workflow only on non-version-tagged commits
- Temporarily disable job until publishing to TestPyPI works
- Fix paths for built dist
- Enable test upload and release
- Fix project name to pyTermite in every place
- Add deploy environment for package release
- Fix package name in path for artifact attestation step during release job
- Remove commits from bots and duplicate commit messages from changelog generation
- Add automatic versioning with setuptools_scm
- Enable upload to regular PyPI
- Add workflow to manually trigger releases
- Fix changelog generation in CI workflow when called from other workflow
- Format changelog before committing when run from release workflow
- Fix tag pushing in release workflow
- Escape dunder names in changelog for correct markdown rendering
- Add link to package logo in README.md for correct rendering on PyPI
- Remove release workflow
- Strip leading v from CI workflow input in CD workflow

## [0.0.1] - 2026-02-05

### ⚙️ Miscellaneous Tasks

- Init
