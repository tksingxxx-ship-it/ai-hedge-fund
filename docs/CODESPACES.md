# Codespaces fixture preview

Private browser preview of this unmerged branch. It does not start a paper session, a research mission, or a universe download. It does not use provider keys.

GitHub Codespaces billing is separate from Cursor and from Grok Bot. This repository cannot see your included hours, storage, or spending limit. Before you create a codespace, open [GitHub billing](https://github.com/settings/billing) and [Codespaces settings](https://github.com/settings/codespaces). Confirm what your account still includes. Set a spending limit that blocks paid overage if you do not want GitHub to charge past the included amount. Creating or leaving a codespace running can consume that allowance. Stopping it stops compute; GitHub may still count storage until you delete it. This is not free 24/7 hosting.

A devcontainer file can request a private port. It cannot force GitHub's account policy. After the port appears, open the Ports panel and confirm **8765** says **Private**. If it says Public, change it to Private or stop the preview. An organization policy can override this file.

## Branch

Use the open pull request, not `main`.

- Pull request: https://github.com/tksingxxx-ship-it/ai-hedge-fund/pull/1
- Branch: `cursor/virtual-office-685a`

In the browser, open that pull request, choose **Code**, then **Codespaces**, then **Create codespace on cursor/virtual-office-685a**. If GitHub asks for a machine type, a 2-core machine meets the minimum in `.devcontainer/devcontainer.json`. This file does not promise how fast setup will be. Image download time was not measured here.

## What setup does

The create step runs `bash .devcontainer/setup.sh` once. That installs Python dependencies with Poetry (`office` extra) and builds the UI. It does not start the server. Running it again skips `npm ci` when `web/package-lock.json` has not changed, and runs `poetry install` again, which reuses what is already installed.

On the build VM, with Poetry already installed and a warm npm cache, that script took 4 seconds the first measured run and 3 seconds the second. Those times do not include downloading the devcontainer image. A Codespace create will take longer. That image pull was not timed.

Python in the image is 3.12. The app also accepts 3.12 on the build machine and declares 3.11 or 3.12.

## Start

In the codespace terminal:

```bash
bash .devcontainer/preview.sh
```

Or **Terminal → Run Task… → Start fixture-only office preview**.

The app listens on `127.0.0.1:8765` with `OFFICE_FIXTURE_ONLY=1`. Inherited API keys are unset by that script, and the process drops them again. `~/.hedge-fund/.env` is not loaded. `OFFICE_ALLOW_REMOTE` is not set. No mission, paper tick, or universe refresh runs until you click something in the page.

When port 8765 appears, use **Open in Browser** from the Ports panel. The page banner should say **Fixture-only preview** and **EXTERNAL CALLS OFF**.

A second start does not launch another copy. It tells you the port is already in use.

## Stop

1. In the preview terminal, press Ctrl+C. Or run `bash .devcontainer/preview.sh stop`, or the task **Stop fixture-only office preview**.
2. On github.com/codespaces, stop the codespace so compute is not left running.
3. Delete the codespace when you do not need it. Delete removes the workspace copy, including preview records. Stop keeps them until GitHub's retention period, which you set in Codespaces settings, removes the codespace. This repository does not set that period.

## What is kept

Preview SQLite, paper ledgers, backtests, and mandates go to `.office-preview/` inside the workspace. That directory is gitignored. Do not commit it, and do not put API keys in it.

| Event | Preview records in `.office-preview/` |
| --- | --- |
| Stop codespace | Kept on the codespace disk |
| Start the same codespace again | Still there |
| Rebuild container | Kept; setup runs again and does not delete them |
| Delete codespace | Removed with the codespace |

A later real research run needs your own data and model keys and can cost money at those providers. Leave fixture-only mode off only when you mean to do that, outside this preview script. Fixture preview does not need those keys.

## If setup fails

Open the creation log. Fix the reported command, then **Rebuild container**. The preview command will exit with "poetry is not on PATH" if setup did not finish. Python other than 3.11 or 3.12 makes setup exit before install.
