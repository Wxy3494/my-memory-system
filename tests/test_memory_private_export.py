from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch
from scripts import freeze_memory_candidate as freeze
from scripts import prepare_memory_release as prepare
from scripts.memory_private_paths import PRIVATE_DIRECTORIES, audit_private_git, require_private_git_clear

ROOT=Path(__file__).resolve().parents[1]


class PrivateExport(unittest.TestCase):
    def test_private_trace_paths_are_excluded_even_if_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"docs").mkdir()
            (root/"docs/public.md").write_text("synthetic public summary")
            (root/".gitignore").write_text(".private-eval/\n.env.memory\n")
            listing="\0".join([prefix+directory+"/synthetic.json" for directory in PRIVATE_DIRECTORIES
                              for prefix in ("","docs/","docs/nested/")]+["docs/public.md",".gitignore",""]).encode()
            with patch.object(freeze,"ROOT",root),patch.object(freeze.subprocess,"check_output",return_value=listing):
                paths=freeze.source_candidates()
            self.assertEqual([name for name,path in paths],[".gitignore","docs/public.md"])
            with patch.object(prepare,"ROOT",root),patch.object(prepare.subprocess,"check_output",return_value=listing),\
                 patch.object(prepare.subprocess,"run"):
                self.assertEqual([name for name,path in prepare.candidates()],[".gitignore","docs/public.md"])

    def test_actual_repository_ignores_all_root_and_nested_private_directories(self):
        report=audit_private_git(ROOT)
        self.assertEqual(len(report["ignored"]),9)
        self.assertEqual(report["unignored"],[])
        self.assertTrue(report["passed"])
        self.assertEqual(report["tracked_private_paths_count"],0)

    def test_tracked_private_file_blocks_release_despite_ignore_and_export_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            subprocess.run(["git","init","--quiet"],cwd=root,check=True,capture_output=True)
            (root/".gitignore").write_text((ROOT/".gitignore").read_text(encoding="utf-8"),encoding="utf-8")
            path=root/"docs/platform-private/synthetic.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"synthetic":true}',encoding="utf-8")
            subprocess.run(["git","add","--force","--",str(path.relative_to(root))],cwd=root,check=True,capture_output=True)
            report=audit_private_git(root)
            self.assertEqual(len(report["ignored"]),9)
            self.assertEqual(report["tracked_private_paths_count"],1)
            self.assertFalse(report["passed"])
            with self.assertRaisesRegex(ValueError,"private_git_release_guard_failed"):
                require_private_git_clear(root)
            with patch.object(freeze,"ROOT",root):
                self.assertEqual([name for name,path in freeze.source_candidates()],[".gitignore"])


if __name__=="__main__":
    unittest.main()
