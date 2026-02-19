# puda-cli

## Running puda.exe on Windows

If you see **"Python was not found"** when running `puda.exe`, the executable is using Windows PATH and not finding your Python. Use the method below.

**Option 1 – One-off (current session)**  
Prepend your Python directory to PATH, then run puda:

```powershell
$env:PATH = "C:\Python313;$env:PATH"
.\puda.exe machine first help labware
```

Use the folder where your `python.exe` lives (e.g. `C:\Python313` if `which python` is `/c/Python313/python`).



Replace `machine first help labware` with any puda command. Ensure `pip install --upgrade puda-drivers` was run with this same Python.

**If you see "Python was not found" (Microsoft Store message)**  
Disable the Store aliases: **Settings** → **Apps** → **Advanced app settings** → **App execution aliases** → turn **Off** for `python.exe` and `python3.exe`.

**If you see `exec: "python3": executable file not found in %PATH%`**  
`puda.exe` looks for **`python3`**; on Windows the installer often only provides `python.exe`.

- **Option :** Create a copy in your Python folder (run PowerShell **as Administrator**):  
  `Copy-Item "C:\Python313\python.exe" "C:\Python313\python3.exe"` 
