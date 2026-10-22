---
name: jira-agent-redeploy
description: "Safely redeploy the Jira commercial agent after code or configuration changes. Use when asked to redeploy, publish, release, or update the Jira webhook Azure Function, Microsoft Foundry Hosted Agent, or both."
argument-hint: "Optional target: Function, Hosted Agent, or both"
---

# Jira Agent Redeployment

Deploy only the requested entry point(s). Jira webhooks normally enter the Azure Function; the Foundry Hosted Agent is a separate entry point. Publishing one does not publish the other. When the user asks for a complete redeployment and both are in use, deploy and verify both.

## Required workflow references

- Before any `azd` command, run `./.agents/skills/microsoft-foundry/scripts/check-and-setup-dependencies.sh` from the repository root and read [Microsoft Foundry azd guidance](../microsoft-foundry/foundry-agent/azd-guidance/azd-guidance.md).
- Before redeploying the Hosted Agent, read [Microsoft Foundry deploy workflow](../microsoft-foundry/foundry-agent/deploy/deploy.md) and follow its post-deploy evaluation-suite handoff.
- Use the project-specific commands and safety checks in [DEPLOYMENT.md](../../../DEPLOYMENT.md).

## Procedure

1. **Resolve target and environment.** Inspect `azure.yaml`, the Function App, selected `azd` environment, and the request to identify which entry points are in use. Confirm the resource names and active environment before publishing. If the target is ambiguous or multiple production environments are possible, ask before deploying.
2. **Preflight the changes.** Inspect `git status` and review the exact requested diff. Run the project tests and relevant lint/format/type checks. Run Terraform formatting/validation only when Terraform files are part of the change; do not run `azd provision` for a code-only release. If unrelated or unreviewed changes are present, do not publish from the dirty workspace. Create a temporary staging copy from the approved source and overlay only the reviewed changes; retain all shared `src/` modules needed by the runtime.
3. **Protect deployment contents.** Exclude `.env`, credentials, local settings, `.venv`, caches, tests, Terraform files/state, `.foundry` artifacts, and unrelated local files. For the Hosted Agent, retain only the selected `.azure` environment context needed by azd; ensure `.agentignore` excludes it from the uploaded code package. Never use `--publish-local-settings` or `--overwrite-settings`.
4. **Publish the Azure Function** when requested or when Jira webhooks use it:

   ```bash
   func azure functionapp publish <function-app-name> --build remote
   ```

   Run from the sanitized Function staging directory containing `function_app.py`, `host.json`, `requirements.txt`, and the reviewed `src/` package. Remote build matches the Function's configured Python runtime even when local Python differs. If Core Tools cannot detect the Python worker in staging, copy `local.settings.json.example` to `local.settings.json` solely for runtime detection; do not publish its settings. If publish fails, stop and diagnose the reported build/deployment error rather than changing app settings or provisioning infrastructure.
5. **Publish the Microsoft Foundry Hosted Agent** when requested or when that entry point is in use. Confirm `codeConfiguration` exists in `azure.yaml`, and verify the selected environment has the required endpoint, project ID, tenant ID, model deployment, and non-secret settings without printing all environment values. Run from the project or clean staging directory:

   ```bash
   AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd deploy osb-jira-agent --no-prompt
   ```

   Keep `AZURE_DEV_USER_AGENT` inline and never persist it. Do not run `azd provision` for code-only changes. Each successful deploy creates an immutable agent version.
6. **Verify each deployed entry independently.**

   Function health:

   ```bash
   curl --fail-with-body https://<function-app-name>.azurewebsites.net/api/health
   ```

   Hosted Agent version/status:

   ```bash
   AZURE_DEV_USER_AGENT=microsoft_foundry_skill azd ai agent show osb-jira-agent --output json
   ```

   Confirm the Function reports healthy and the Hosted Agent is active with a new version and expected endpoint/configuration. Check only non-secret settings.
7. **Smoke-test safely.** Never invoke the production agent with a real Jira issue when Jira writes are enabled. Use a non-production issue and approved test payload only when available and authorized. Otherwise, rely on deployment health/version checks and say that a live issue invocation was intentionally skipped.
8. **Report completion.** State which entry points were deployed, version/build status, verification results, environment, and any skipped smoke test or warning. Do not claim a webhook was processed merely because deployment succeeded. Follow the Foundry deploy workflow for the evaluation-suite handoff; do not run evaluation generation unless the user chooses it.

## Failure handling

- **Function build fails or runtime warning appears:** verify remote build output, configured Function Python version, and package contents; do not change the Function runtime or overwrite settings as a workaround.
- **Hosted Agent deploy fails or does not activate:** inspect `azd ai agent show`, then `azd ai agent doctor --output json` and deployment logs. Do not retry repeatedly or provision resources as a generic fix.
- **Health/version check fails:** stop and diagnose the relevant deployment. Do not report success until the required entry point is healthy/active.
- **Dirty workspace:** do not silently package unrelated changes. Stage only the reviewed release contents or ask the user to resolve an ambiguous change set.
