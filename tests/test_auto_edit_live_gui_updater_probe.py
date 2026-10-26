import os
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/"rg_remote_control"/"auto_edit_features"/"live_studio_gui_updater_probe_v1.ps1"

class LiveProbeTests(unittest.TestCase):
    def test_no_mutating_commands(self):
        txt=FILE.read_text(encoding="utf-8")
        for forbidden in ("Stop-Process","Start-Process","Remove-Item","Set-Content",
                          "Out-File","Copy-Item","Move-Item","Restart-Computer",
                          "Unregister-","Terminate","Set-ItemProperty"):
            self.assertNotIn(forbidden,txt)
        self.assertIn("RG_LIVE_GUI_UPDATER|",txt)
        self.assertIn("VISIBLE_WINDOW_RESPONDING",txt)
        self.assertIn("RUNNING_WINDOW_NOT_VISIBLE_TO_RUNNER",txt)

    @unittest.skipUnless(os.name=="nt","PowerShell AST parser requires Windows CI")
    def test_powershell_syntax(self):
        quoted=str(FILE).replace("\x27","\x27\x27")
        ps=f"$path=\x27{quoted}\x27;$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::ParseFile($path,[ref]$t,[ref]$e)|Out-Null;foreach($x in $e){{Write-Output $x.Message}};if($e.Count){{exit 2}}"
        p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",ps],
                         capture_output=True,text=True,timeout=25)
        self.assertEqual(p.returncode,0,p.stdout+"\n"+p.stderr)

if __name__=="__main__":
    unittest.main()
