This project was built with the microsoft-foundry skill. Before working on or answering questions about foundry agents, read the microsoft-foundry skill first.

For issue-keyed webhook status and diagnosis, use [jira-processing-status](./.agents/skills/jira-processing-status/SKILL.md). For publishing either or both Jira agent entry points, use [jira-agent-redeploy](./.agents/skills/jira-agent-redeploy/SKILL.md).

## Deployment fast path

For deployment requests, follow [DEPLOYMENT.md](./DEPLOYMENT.md) and execute deployments through `make`. Deploy only the entry points the user uses. Jira webhooks normally enter through the Azure Function; publishing the Hosted Agent does not update it, and vice versa. For code-only changes, do not run `azd provision`.

- **Orquestração via Makefile**: Always use `make` targets to run checks, package, and deploy:
  - Full production deployment (recommended): `make deploy` (orchestrates `test`, `lint`, `compile`, `package`, `deploy-foundry`, and `status-foundry`).
  - Direct Hosted Agent deployment to Foundry: `make deploy-foundry` (keeps inline `AZURE_DEV_USER_AGENT=microsoft_foundry_skill` and passes `--no-prompt`).
  - Azure Function deployment: `make deploy-function` (remote build).
  - Status check: `make status-foundry`.
  - Development prerequisites and configuration: `make setup` or `make prereqs`.
  - Local testing with Foundry Agent Inspector: `make run-foundry`.
- Check `git status` and review the exact source diff before packaging. This workspace may contain
  unrelated local changes; never publish them accidentally. Use a clean, temporary staging
  directory when needed, and include all reviewed shared `src/` modules required by the selected
  entry point.
- Publish the Function with `make deploy-function` (or from a sanitized staging directory with
  `func azure functionapp publish <app> --build remote`). If Core Tools cannot identify Python in
  the staged directory, include a local `local.settings.json` copied from the example only to
  identify the worker runtime; never pass `--publish-local-settings` or `--overwrite-settings`.
  Remote build avoids depending on the local Python version matching the Function runtime.
- Deploy the Hosted Agent with `make deploy` or `make deploy-foundry`.
  Confirm the selected azd environment and required values without printing `azd env get-values`.
- Keep `.env`, credentials, `.venv`, caches, tests, Terraform state, and local Foundry/azd state
  out of deployment packages except the azd context required to deploy from a temporary project
  copy. Never publish local Function settings.
- Verify the Function with `/api/health` and the Hosted Agent with `make status-foundry`
  (`azd ai agent show osb-jira-agent --output json`, verifying active status, new version, and expected
  non-secret settings). Do not invoke a production Jira issue for smoke testing when writes are
  enabled; use a non-production test issue or report that invocation testing was intentionally
  skipped.
