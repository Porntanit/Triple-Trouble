# Mac share bundle verification

Source copied from the user's latest project in `Documents/triple-trouble` without editing that original folder.

Added `Start-on-Mac.command`, `launch.py`, `START-HERE-TH.md` and six bootstrap tests. The launcher checks Python 3.10–3.13, prepares a fresh per-copy virtual environment, skips unchanged setup on later launches, checks/opens Ollama, requests consent to download missing models, selects a free localhost port, starts Flask and opens the browser. Personal runtime data is stored separately in the recipient's Application Support folder.

Verification: 27 tests passed (21 existing application tests plus six launcher tests). Shell syntax and non-installing bundle validation passed. Launcher tests mock process/network actions; they do not claim that installation or inference was tested on a clean recipient Mac. The available test interpreter remains Python 3.9.6; actual launching requires the documented supported Python version. A fresh Mac setup and download were not run in this session.

The ZIP is checked for corruption, executable permission on the `.command` file and exclusion of virtual environments, Git metadata, runtime databases, uploads, signing keys and environment files. Documentation screenshots contain fictional test data.
