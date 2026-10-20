This project was built with the microsoft-foundry skill. Before working on or answering questions about foundry agents, read the microsoft-foundry skill first.

## Deployment fast path

For deployment requests, follow [DEPLOYMENT.md](./DEPLOYMENT.md) and deploy only the entry points
the user uses. Jira webhooks normally enter through the Azure Function; publishing the Hosted Agent
does not update it, and vice versa. For code-only changes, do not run `azd provision`.

- Check `git status` and review the exact source diff before packaging. This workspace may contain
  unrelated local changes; never publish them accidentally. Use a clean, temporary staging
  directory when needed, and include all reviewed shared `src/` modules required by the selected
  entry point.
- Publish the Function from the sanitized staging directory with
  `func azure functionapp publish <app> --build remote`. If Core Tools cannot identify Python in
  the staged directory, include a local `local.settings.json` copied from the example only to
  identify the worker runtime; never pass `--publish-local-settings` or `--overwrite-settings`.
  Remote build avoids depending on the local Python version matching the Function runtime.
- Deploy the Hosted Agent from the project/staging directory with
  `AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy osb-jira-agent --no-prompt`.
  Keep the user-agent variable inline; confirm the selected azd environment and required values
  without printing `azd env get-values`.
- Keep `.env`, credentials, `.venv`, caches, tests, Terraform state, and local Foundry/azd state
  out of deployment packages except the azd context required to deploy from a temporary project
  copy. Never publish local Function settings.
- Verify the Function with `/api/health` and the Hosted Agent with
  `azd ai agent show osb-jira-agent --output json` (active status, new version, and expected
  non-secret settings). Do not invoke a production Jira issue for smoke testing when writes are
  enabled; use a non-production test issue or report that invocation testing was intentionally
  skipped.
