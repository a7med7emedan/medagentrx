# SPDX-FileCopyrightText: 2026 Ahmed Hemedan
# SPDX-License-Identifier: Apache-2.0
#
# Terminal recording for the README. Run from the repository root:
#   vhs scripts/demo.tape
# Uses a clean shell with an anonymous prompt, so no user or machine name appears.

Output docs/assets/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1180
Set Height 620
Set Padding 24
Set TypingSpeed 35ms
Set Theme { "name": "MedAgentRx", "background": "#0F172A", "foreground": "#E2E8F0", "black": "#0F172A", "red": "#F87171", "green": "#4ADE80", "yellow": "#FCD34D", "blue": "#5EEAD4", "magenta": "#F0ABFC", "cyan": "#5EEAD4", "white": "#E2E8F0", "brightBlack": "#64748B", "brightRed": "#F87171", "brightGreen": "#4ADE80", "brightYellow": "#FCD34D", "brightBlue": "#5EEAD4", "brightMagenta": "#F0ABFC", "brightCyan": "#5EEAD4", "brightWhite": "#FFFFFF", "cursor": "#FCD34D", "selection": "#334155" }

Hide
Type `env -i PATH="$PWD/.venv/bin:/usr/bin:/bin" HOME=/tmp PS1='$ ' TERM=xterm-256color bash --norc --noprofile` Enter
Type "clear" Enter
Show

Type "medagentrx validate examples/sepsis-risk/change-plan.yaml" Sleep 400ms Enter
Sleep 2s
Type "medagentrx demo --out demo-out --scenario good-update --scenario subgroup-harm \" Enter
Type "  --scenario test-set-tampered --scenario bio-creep" Sleep 400ms Enter
Sleep 22s
Type "echo $?   # 0: every planted scenario gave its exact verdict" Sleep 300ms Enter
Sleep 4s

Hide
Type "rm -rf demo-out && exit" Enter
