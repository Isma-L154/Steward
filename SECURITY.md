# Security policy

Report a vulnerability privately through GitHub: **Security → Report a vulnerability** on this repository. Please do not open a public issue for it.

## What Steward can do

Steward holds a GitHub App private key with write access to pull requests, issues and repository contents on the repositories where it is installed. Reports about webhook authentication, token handling, the account allowlist, or anything that could make it merge a pull request it should not, are the most valuable.

## Which accounts it acts on

Steward acts only on its owner's account and on the accounts listed in `ALLOWED_ACCOUNTS`. If any other account installs it, Steward uninstalls itself from that account and does nothing there. The owner's account is never uninstalled.

For an allowed account:

- install Steward with **Only select repositories**, choosing the repositories it should look after;
- Steward merges and labels Dependabot pull requests there, but never audits those repositories against the owner's standards, and they never appear on the owner's hub;
- the App asks for the same permissions on every account, and a new permission is never added without a note in this file.

Anyone who installs Steward trusts the owner, who holds the App's private key: that is true of any GitHub App.
