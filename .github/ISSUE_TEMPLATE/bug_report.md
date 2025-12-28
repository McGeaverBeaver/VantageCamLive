---
name: Bug report
about: Create a report to help us improve
title: ''
labels: ''
assignees: ''

---

## 🐞 Describe the Bug
A clear and concise description of what the bug is.

## 🔁 Steps to Reproduce
Steps to reproduce the behavior:
1. Set environment variable '...' to '...'
2. Start container with command '...'
3. Trigger event '...'
4. See error

## 🧐 Expected Behavior
A clear and concise description of what you expected to happen.

## 📸 Screenshots / Discord Alerts
If applicable, add screenshots or copy the text from the Discord notification you received.

## ⚙️ Environment Details
- **Host OS:** [e.g. Unraid, Ubuntu 22.04, Windows Docker Desktop]
- **Docker Version:** [e.g. 24.0.5]
- **Vantage Cam Version:** [e.g. v2.8 or latest]
- **Hardware Acceleration:** [e.g. Intel QuickSync (Vaapi) or Software (CPU)]
- **Camera Model:** [e.g. Reolink RLC-410]

## 📝 Configuration (`compose.yaml`)
```yaml
version: "3"
services:
  vantagecam:
    environment:
      - HARDWARE_ACCEL=true
      - WATCHDOG_ENABLED=true
      # ... other settings


📜 Logs
<details> <summary>Click to expand container logs</summary>

Paste logs here
</details>

<details> <summary>Click to expand watchdog logs (/config/watchdog.log)</summary>

Paste watchdog logs here
</details>

📋 Additional Context
Add any other context about the problem here.

Is this a fresh install or an upgrade?

Did it work in a previous version?
