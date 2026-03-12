# puda-cli

## Commands

```
puda
├── protocol
│   ├── run                  Run a protocol on machines via NATS
│   └── validate             Validate a protocol JSON file
├── machine
│   ├── list                 Discover machines via heartbeat
│   ├── state <machine_id>   Get the state of a machine
│   ├── reset <machine_id>   Reset a machine
│   └── commands <machine_id> Show available commands
├── login                    Log in to a PUDA account
├── logout                   Log out of a PUDA account
├── config
│   ├── list                 List configuration values
│   └── edit                 Edit configuration in default editor
├── init [path]              Initialize a new PUDA project
├── skills
│   ├── install              Install and sync agent skills
│   └── update               Update agent skills and sync AGENTS.md
└── db
    ├── exec [sql]           Execute SQL queries on the database
    └── schema               Display the database schema
```

## Setup

After extracting, place in the project folder, then follow these steps:

1. **Login**: Run `puda login` and enter your username.

2. **Initialize project**: 
   ```bash
   puda init <project_folder>
   ```
   Or if you're already the project folder:
   ```bash
   puda init .
   ```

3. **Install Skills**:
   ```bash
   puda skills install
   ```

## Troubleshooting

### Windows Issues

If you see **"Python was not found"** when running `puda.exe`, the executable is using Windows PATH and not finding your Python. Use the method below.

**Option 1 – One-off (current session)**  
Prepend your Python directory to PATH, then run puda:

```powershell
$env:PATH = "C:\Python313;$env:PATH"
.\puda.exe machine list
```

Use the folder where your `python.exe` lives (e.g. `C:\Python313` if `which python` is `/c/Python313/python`).



Replace `machine list` with any puda command.

**If you see "Python was not found" (Microsoft Store message)**  
Disable the Store aliases: **Settings** → **Apps** → **Advanced app settings** → **App execution aliases** → turn **Off** for `python.exe` and `python3.exe`.

**If you see `exec: "python3": executable file not found in %PATH%`**  
`puda.exe` looks for **`python3`**; on Windows the installer often only provides `python.exe`.

- **Option :** Create a copy in your Python folder (run PowerShell **as Administrator**):  
  `Copy-Item "C:\Python313\python.exe" "C:\Python313\python3.exe"` 
