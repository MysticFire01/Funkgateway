# FunkGateway Community Directory

Public Zello channel directory shared by FunkGateway Linux and (later) Windows.

Submit proposals via GitHub Issues. Maintainers review the channel name, authorization for public listing, and duplicates before manually adding an entry to `zello_channels.json`.

Example entry:

```json
{"platform":"zello","name":"Example Public Channel","description":"Public community channel"}
```

Never publish passwords, private channel links, API tokens, or personal information. A channel listed here has not necessarily been tested for availability. Do not auto-delete a channel because one connection attempt failed. An entry must be a genuine Zello channel, not a placeholder or a guessed name. Repository maintainers handle moderation. An authenticated GitHub account is needed to submit an issue until an independently secured intake service is available.

## Automated maintainer approval

1. Create the issue label `approved` in the repository (if it does not exist).
2. A user submits an issue from FunkGateway's **Public Directory** with the title
   `[Community Directory] Zello: CHANNEL` and body fields `Plattform: Zello`,
   `Kanalname: CHANNEL` and `Beschreibung: OPTIONAL`.
3. A maintainer with write access reviews the name, public-listing permission,
   and any sensitive information, then attaches the `approved` label.
4. The workflow `.github/workflows/community-directory-approve.yml` checks
   the label actor's repository permission, validates the fields, checks for
   duplicates, appends a channel to `community/zello_channels.json`, comments,
   and closes the issue.
5. Clients fetch the published directory using **Liste aktualisieren**.

Do not approve requests without verifying permission to list them publicly.
The issue and its body are public. Never include passwords, tokens or private URLs.
The bot does not test whether Zello channels are currently online.

**GitHub configuration:** GitHub Actions must be enabled and the repository must
allow `GITHUB_TOKEN` to write repository contents and issues. Branch rules may
restrict automated commits; if so, adapt the workflow to use a reviewed pull
request instead. If automation fails, check the Actions run and keep the Issue
open for manual handling. Only authorized maintainers should apply `approved`.
