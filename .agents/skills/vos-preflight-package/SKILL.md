---
name: vos-preflight-package
description: Build and install a VOS candidate package on explicitly confirmed devices before release. Use only for VAI applications whose AGENTS.md or release runbook opts into this skill and the user asks to 构建预检包 or install a candidate build.
---

# Vos Preflight Package

Build or reuse the application's candidate images and package, run a lightweight image smoke check, then install the package through the normal VOS upgrade path. The workflow ends when installation succeeds. Do not run UI, API, inference, or other functional verification.

The skill currently belongs to V-yovoice. Other VAI applications can copy it into their own `.agents/skills` directory when they add a compatible package and device mapping.

For V-yovoice image checks and device mappings, read [references/v-voice.md](references/v-voice.md).

## Inputs

Get these from the application's AGENTS.md or release runbook:

- One explicit candidate version for the entire preflight cycle.
- The generated candidate package path.
- The application ID.
- The mapping from VOS profile to SSH device.
- The application-specific image smoke command and target image references.

Keep the candidate version fixed across image rebuilds, package rebuilds, retries, and device reinstalls. Rebuilds must overwrite the same candidate image tags and package path; do not increment the version between preflight attempts. Persist or publish that version only after final validation and the user's release decision.

Build each target image on its matching host and run the application-specific smoke check before any push. The candidate image references must be pullable before the VOS devices are changed. Push candidates without recording them in Feishu; formal publication remains a separate user decision.

## Image smoke

Follow the application-specific reference, such as [references/v-voice.md](references/v-voice.md), immediately after the image build and before `publish-only` or a direct push. Every applicable profile must pass. Treat a missing local image, wrong architecture, failed runtime import, or failed catalog/source check as a build failure.

The smoke may start a temporary container, but it must use `docker run --rm` and must not mount persistent data, publish ports, execute inference, or leave a container behind. Verify no temporary container remains after the check.

## Plan first

Load credentials from the approved source without printing them:

```bash
: "${VOS_ADMIN_PASSWORD:?load from approved credential source}"
```

Run the read-only plan on every target:

```bash
python3 .agents/skills/vos-preflight-package/scripts/vos_preflight.py plan \
  --package <candidate.tar> \
  --target <ssh-device>=<profile>
```

Before changing any device, show the user:

- device
- installed application version
- candidate version
- installed and candidate profiles
- dependency result

Wait for explicit confirmation. A general prior request to build the package does not authorize device upgrades by itself.

## Apply

After confirmation, run the same targets in the same order:

```bash
python3 .agents/skills/vos-preflight-package/scripts/vos_preflight.py apply \
  --package <candidate.tar> \
  --target <ssh-device>=<profile> \
  --confirmed
```

The script upgrades existing installations in sequence and stops after the first failure. Success requires:

- VOS task status `Completed`
- installed version equals the candidate version
- active profile equals the selected profile
- application state is `installed`
- `runtime_ready` is true

Do not uninstall the application or clear its configuration or storage. Report successful, failed, and unattempted devices. Functional testing is outside this skill.
