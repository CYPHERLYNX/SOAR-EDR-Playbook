# SOAR-EDR-Playbook
A cybersecurity project integrating SOAR (Tines) and EDR (LimaCharlie) for automated incident response.  



# Lazagne Detection Rule

**Filename:** `lazagne_detection_rule.yaml`  
**Purpose:** Detect execution or presence of the Lazagne password recovery tool on Windows endpoints.

## Description
This rule detects common signs of Lazagne execution by checking file paths, command-line indicators, and a known file hash. Lazagne is often used by red teamers and malicious actors to extract stored credentials from Windows machines. The rule is intended for use in SOAR/EDR rule collections to alert on potential credential access activity.

## Detection Logic
- Triggers on new or existing process events.
- Targets Windows platform processes.
- Matches if:
  - `FILE_PATH` ends with `lazagne.exe`, OR
  - `COMMAND_LINE` ends with or contains `lazagne`, OR
  - `event/HASH` equals the known hash value included in the rule.

## Recommended Response
- Default action: `report` (generate an alert).
- Suggested alert level: `medium`.
- Suggested tags: `attack.credential_access`.

## False Positives
- **Unlikely** in most environments, but possible if legitimate tools or developer binaries are named `lazagne` (rare).
- If you maintain a benign tool with this name, whitelist its known paths/hashes.

## Testing
1. Place `lazagne_detection_rule.yaml` in your rules directory (e.g., `rules/credential_access/`).
2. Reload or deploy detection rules to your EDR/SOAR platform.
3. Test with a benign sample:
   - Run `lazagne.exe` in a controlled lab VM that mimics production.
   - Execute a command that includes the string `lazagne` in the command line.
   - Verify that an alert is generated and contains expected metadata.
4. Test hash match:
   - Create a file with the detection hash (only for lab/testing) and run it to ensure the hash detection fires.
5. Validate no alerts from unrelated tools by running common admin tools and confirming the rule remains silent.

## Mitigation / Analyst Playbook
1. Triage the alert: confirm host and user context, start/stop time, and parent process.
2. Isolate host if malicious activity is suspected.
3. Collect forensic artifacts:
   - Process list, command line, and parent process.
   - Memory dump / process dump of `lazagne.exe`.
   - Network connections from the host during the event.
4. Rotate/verify credentials for impacted users.
5. Perform a scoped hunt for similar indicators across the environment.

## Mapping
- **MITRE ATT&CK:** `Credential Access` (e.g., credential dumping / password extraction)

## Notes & Customization
- Replace or add hashes specific to your threat intelligence feeds.
- If you have legitimate tools with similar names, add allowlist entries by file path, signer, or hash.
- Adjust alert level to `high` if runbook dictates aggressive response for credential-related detections.

## YAML code 
events:
  - NEW PROCESS
  - EXISTING PROCESS
op: and
rules:
  - op: is
    platform: windows
  - op: or
    rules:
      - case sensitive: false
        op: ends with
        path: event/FILE_PATH
        value: lazagne.exe
      - case sensitive: false
        op: ends with
        path: event/COMMAND_LINE
        value: .\lazagne
      - case sensitive: false
        op: contains
        path: event/COMMAND_LINE
        value: lazagne
      - case sensitive: false
        op: is
        path: event/HASH
        value: '467e4f9f1795c1b08245ae621c59cdf6df630ef1631dc0859da9a82285a846'

respond:
  - action: report
    metadata:
      author: my edr
      description: Detects Lazagne (SOAR EDR Tool)
      from_view: false
      falsepositives:
        - Unlikely
      level: medium
      tags:
        - attack.credential_access
      name: myydfir-hacktool-lazagne (kiko)



[SOAR EDR PROJECT1.docx](https://github.com/user-attachments/files/22878609/SOAR.EDR.PROJECT1.docx)
