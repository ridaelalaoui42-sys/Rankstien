# AgentMemory iii Runtime

`scripts/dev/start_agentmemory.ps1` downloads the pinned Windows `iii.exe`
runtime into this folder when it is missing, then copies it to
`%USERPROFILE%\.local\bin\iii.exe` for AgentMemory's Windows fallback lookup.

The downloaded `.exe` and `.zip` files are local runtime artifacts and are not
tracked in Git.
