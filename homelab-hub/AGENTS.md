# Homelab Hub development guidance

## Architecture

- Keep the FastAPI entry point focused on routing and application composition.
- Put shared infrastructure under `app/core` and integrations under `app/modules/<integration>` as those areas are extracted from `app/main.py`.
- Keep Docker, Unraid, WebCal, FileBrowser Quantum, and future service integrations isolated from one another.
- A failure in one external integration must not prevent the dashboard or other integrations from loading.

## Runtime and security

- Preserve the `/data` data directory and the Docker socket deployment contract.
- Never commit passwords, API tokens, session secrets, or host-specific URLs.
- Treat Docker socket access as administrative access.
- Do not expose secret values in normal API responses, logs, or client-side state.

## UI and metrics

- The Hub is a control center, not a bookmark dashboard.
- Prefer stable DOM updates over replacing complete panels during polling.
- Default views should answer one operational question; use focused views and drill-downs for detail.
- Show metric units, sampling context, thresholds, and trends. Normalize CPU values by available cores where comparisons require it.
- Keep unavailable integrations visible as contained status messages rather than allowing them to break the page.

## Deployment and validation

- Production is managed through the Unraid XML template, not Docker Compose.
- Keep the XML template compatible with the published GHCR image and `/mnt/user/appdata/homelab-hub -> /data` mapping.
- Before submitting changes, run the available Python, JavaScript, and workspace diagnostics. Update the README for major features.
