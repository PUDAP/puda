# Export deployment logs and learnings

## Export logs and learnings

When asked to export the PUDA deployment logs and learnings:

1. Collect everything from the deployment session: filled deployment/incident records, site and machine profiles, labware alignment records, error-catalog updates, and any other logs or learnings produced during the work. Redact secrets.
2. Resolve the zip name from the PUDA CLI username and today's date:
   - Username: `puda config get user.username`
   - Date: `YYYY-MM-DD` (UTC)
   - Filename: `<username>-<YYYY-MM-DD>.zip` (example: `zhao-2026-07-22.zip`)
3. Zip the collected files under that name and send the archive to the user.
