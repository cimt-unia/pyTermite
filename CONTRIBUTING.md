# Contributing to pyTermite

Thank you for considering contributing to pyTermite! To improve this package and make it more useful for everyone, your help is needed. This document provides some guidelines for contributing to pyTermite.

## Found a bug?

The easiest way to contribute is to report a bug. To do so, please open an issue on the project's GitHub repository (or use the Issues tab for this repository).
Please provide as much information as possible, including the version of pyTermite you are using, the operating system you are using, and the steps to reproduce the bug.
If you find a security vulnerability, do NOT open an issue. Email [lukas.behammer@uni-a.de](mailto:lukas.behammer@uni-a.de) instead.

## Want to suggest a feature?

If you want to suggest a feature for pyTermite, please open an issue with a feature request. We will discuss the proposal and decide whether it is a good fit for the project.

## Want to contribute code?

You want to contribute code to pyTermite? Great! Here is some information to get you started:

1. Have a look at the open issues to see if there is something you would like to work on.
2. Fork the repository and create a new branch for your feature or bug fix.
3. Write your code and tests.
4. Make sure that all tests pass by running `pytest`.
5. Create a pull request to the `dev` branch of the repository.
6. We will review your pull request and provide feedback.
7. Once your pull request is approved, we will merge it into the `dev` branch.
8. The changes on `dev` will be tested and merged into the `main` branch.
9. Your contribution will be part of the next release of pyTermite!

For more information on the development see the generated developer guide in the docs (e.g. `docs/build/html/developer_guide.html`).

## Want to improve the documentation or examples?

You can also contribute to pyTermite by improving the documentation or examples. To do so, please follow the same steps as for contributing code.
To make sure that your work is not duplicated, please open an issue or pull request to discuss your ideas before you start working on them.

## Commit message style (Conventional Commits)

To keep the project history clear and to support automated changelog generation,
please use the Conventional Commits specification for commit messages where
possible. The basic form is::

    <type>[optional scope]: <short description>

Common types include:

- ``feat``: a new feature
- ``fix``: a bug fix
- ``docs``: documentation only changes
- ``style``: formatting, missing semi-colons, etc (no code change)
- ``refactor``: code change that neither fixes a bug nor adds a feature
- ``test``: adding or updating tests
- ``chore``: build process or auxiliary tools

Examples::

    feat(cli): add `--interactive` flag
    fix(connection): handle response timeout when connecting
    docs: update developer guide with testing instructions

Using this convention makes it easier to generate changelogs and to review
history. If you want to automate linting of commit messages consider adding
an appropriate git hook or CI check (e.g., `commitlint`).

## Other questions?

Email the author: [lukas.behammer@uni-a.de](mailto:lukas.behammer@uni-a.de)

## Code of Conduct

Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project you agree to abide by its terms.