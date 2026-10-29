# Visual Studio Code Setup

This document lists my recommended Visual Studio Code extensions and settings used for CloudinatorFTP development.

## Recommended Extensions

| Extension | Publisher |
|---|---|
| Better Jinja | Samuel Colvin |
| Black Formatter | Microsoft |
| HTML CSS Support | ecmel |
| Pylance | Microsoft |
| Python | Microsoft |
| Python Debugger | Microsoft |
| Python Environments | Microsoft |
| Python Indent | Kevin Rose |
| shfmt | Martin Kühl |
| YAML | Red Hat |
| Even Better TOML | tamasfe |
| Requirements Formatter | MoritzB |

## VS Code Settings

The following settings configure LF line endings, Git Bash as the default integrated terminal, and formatters for Python and shell scripts.

Add `"files.eol": "\n"` to your VS Code `settings.json`:

```json
{
    "files.eol": "\n", # Add this line
    "terminal.integrated.profiles.windows": {
        "PowerShell": {
            "source": "PowerShell",
            "icon": "terminal-powershell"
        },
        "Command Prompt": {
            "path": [
                "${env:windir}\\Sysnative\\cmd.exe",
                "${env:windir}\\System32\\cmd.exe"
            ],
            "args": [],
            "icon": "terminal-cmd"
        },
        "Git Bash": {
            "path": "C:\\Program Files\\Git\\bin\\bash.exe",
            "args": [
                "--login",
                "-i"
            ]
        }
    },
    "terminal.integrated.defaultProfile.windows": "Git Bash",
    "[python]": {
        "editor.defaultFormatter": "ms-python.black-formatter"
    },
    "[shellscript]": {
        "editor.defaultFormatter": "mkhl.shfmt"
    },
    "claudeCode.preferredLocation": "sidebar",
    "terminal.integrated.initialHint": false,
    "redhat.telemetry.enabled": false,
    "security.workspace.trust.untrustedFiles": "open",
    "terminal.integrated.allowedLinkSchemes": [
        "file",
        "http",
        "https",
        "mailto",
        "vscode",
        "vscode-insiders",
        "ms-settings"
    ]
}
```

### Important Settings

- **LF line endings:** `"files.eol": "\n"` sets LF as the default line ending for VS Code.
- **Default terminal:** Git Bash is used for the integrated terminal on Windows (My preference by the way).
- **Python formatting:** Black Formatter is the default formatter for Python files.
- **Shell formatting:** shfmt is the default formatter for shell scripts.

**Note:** These settings are intended for your VS Code environment. The repository's `.gitattributes` rules independently enforce LF line endings for the configured file extensions when Git checks out and normalizes files.