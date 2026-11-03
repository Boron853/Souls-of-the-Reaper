import argparse
import hashlib
import struct
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import import_ps3_save
import sdk_patches
import build_client
import codegen_title_update
import stage_title_update
from apply_generated_patches import patch_generated
from run_linux import launch_command, prepare_ps3_import
from stage_title_update import verify_patch_source


class LinuxToolsTests(unittest.TestCase):
    def test_explicit_window_mode_overrides_saved_preference(self):
        args = argparse.Namespace(probe=False, render_smoke=False, extra_features=True,
                                  game_dir=ROOT / "game", state_dir=pathlib.Path("/tmp/window-state"))
        for extra in (["--fullscreen=true"], ["--fullscreen", "false"]):
            command = launch_command(args, extra)
            self.assertIn("--pc_use_saved_window_mode=false", command)
            self.assertEqual(extra, command[-len(extra):])
        args.extra_features = False
        self.assertNotIn("--pc_use_saved_window_mode=false",
                         launch_command(args, ["--fullscreen=true"]))

    @unittest.skipUnless(shutil.which("clang++") or shutil.which("c++"), "C++ compiler required")
    def test_window_mode_persistence(self):
        harness = r"""
#include "features/pc_features_logic.h"
#include <cassert>
int main(int argc, char** argv) {
  assert(argc == 2);
  const auto path = std::filesystem::path(argv[1]) / "state/pc-settings.ini";
  using namespace d3::features;
  assert(ReadWindowMode(path, 2) == 2);
  for (int mode : {1, 2, 1}) {
    SaveWindowMode(path, mode);
    assert(ReadWindowMode(path, 0) == mode);
  }
  bool failed = false;
  try { SaveWindowMode(path, 3); }
  catch (const std::invalid_argument&) { failed = true; }
  assert(failed && ReadWindowMode(path, 0) == 1);
  for (const auto text : {"", "window_mode=0", "window_mode=3", "window_mode=-1",
                          "window_mode=2 garbage", "garbage"}) {
    std::ofstream(path) << text;
    assert(ReadWindowMode(path, 2) == 2);
  }
  // Both settings share the file and keep each other when saved.
  std::filesystem::remove(path);
  SaveRenderScale(path, 3);
  SaveWindowMode(path, 2);
  assert(ReadRenderScale(path, 0) == 3 && ReadWindowMode(path, 0) == 2);
  SaveRenderScale(path, 1);
  assert(ReadRenderScale(path, 0) == 1 && ReadWindowMode(path, 0) == 2);
  // Values from the earlier one-file-per-setting layout are still honoured.
  std::filesystem::remove(path);
  std::ofstream(path.parent_path() / "pc-render-scale.txt") << "2" << '\n';
  std::ofstream(path.parent_path() / "pc-window-mode.txt") << "1" << '\n';
  assert(ReadRenderScale(path, 0) == 2 && ReadWindowMode(path, 0) == 1);
  SaveWindowMode(path, 2);
  assert(ReadWindowMode(path, 0) == 2 && ReadRenderScale(path, 0) == 2);
  std::filesystem::remove(path.parent_path() / "pc-render-scale.txt");
  std::filesystem::remove(path.parent_path() / "pc-window-mode.txt");
  std::filesystem::remove(path);
  std::filesystem::create_directory(path);
  std::ofstream(path / "preserve") << "keep";
  failed = false;
  try { SaveWindowMode(path, 2); }
  catch (const std::exception&) { failed = true; }
  assert(failed && std::filesystem::exists(path / "preserve"));
  assert(!std::filesystem::exists(path.string() + ".tmp"));
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "window-mode.cpp"
            source.write_text(harness)
            executable = root / "window-mode-test"
            compiler = shutil.which("clang++") or shutil.which("c++")
            subprocess.run([compiler, "-std=c++23", "-Wall", "-Wextra", "-Werror",
                            f"-I{ROOT / 'port/src'}", str(source),
                            str(ROOT / "port/src/features/pc_features_storage.cpp"),
                            "-o", str(executable)], check=True)
            subprocess.run([str(executable), str(root)], check=True)

    @unittest.skipUnless(shutil.which("clang++") or shutil.which("c++"), "C++ compiler required")
    def test_game_exit_runs_on_ui_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = pathlib.Path(directory) / "linux-exit-test"
            compiler = shutil.which("clang++") or shutil.which("c++")
            subprocess.run([compiler, "-std=c++23", "-Wall", "-Wextra", "-Werror",
                            f"-I{ROOT / 'tests/fixtures/exit'}",
                            str(ROOT / "tests/linux_exit.cpp"),
                            str(ROOT / "port/src/base_exit.cpp"),
                            "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

    @unittest.skipUnless(shutil.which("clang++") or shutil.which("c++"), "C++ compiler required")
    def test_shared_fullscreen_handler(self):
        source = (ROOT / "port/src/diablo3_app.h").read_text()
        start = source.index("  void OnKeyDown(")
        end = source.index("\n  }", start) + len("\n  }")
        handler = source[start:end].replace(" override", "")
        harness = r"""
#include <cassert>
namespace rex::ui {
enum class VirtualKey { kF11, kF4 };
struct KeyEvent {
  VirtualKey key;
  bool repeat = false, handled = false;
  VirtualKey virtual_key() const { return key; }
  bool prev_state() const { return repeat; }
  void set_handled(bool value) { handled = value; }
};
int dispatched = 0;
void ProcessKeyEvent(KeyEvent&) { ++dispatched; }
}
struct Window {
  bool fullscreen = false;
  int toggles = 0;
  bool IsFullscreen() const { return fullscreen; }
  void SetFullscreen(bool value) { fullscreen = value; ++toggles; }
};
struct App {
  Window win;
  Window* window() { return &win; }
HANDLER
};
int main() {
  App app;
  rex::ui::KeyEvent press{rex::ui::VirtualKey::kF11};
  app.OnKeyDown(press);
  assert(app.win.fullscreen && press.handled && app.win.toggles == 1);
  rex::ui::KeyEvent repeat{rex::ui::VirtualKey::kF11, true};
  app.OnKeyDown(repeat);
  assert(app.win.fullscreen && repeat.handled && app.win.toggles == 1);
  app.OnKeyDown(press);
  assert(!app.win.fullscreen && app.win.toggles == 2);
  rex::ui::KeyEvent other{rex::ui::VirtualKey::kF4};
  app.OnKeyDown(other);
  assert(!other.handled && rex::ui::dispatched == 1);
}
""".replace("HANDLER", handler)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / "fullscreen.cpp").write_text(harness)
            compiler = shutil.which("clang++") or shutil.which("c++")
            for platform in ("linux", "windows"):
                executable = path / platform
                subprocess.run([compiler, "-std=c++23", "-Wall", "-Wextra", "-Werror",
                                "-D__linux__" if platform == "linux" else "-D_WIN32",
                                str(path / "fullscreen.cpp"), "-o", str(executable)], check=True)
                subprocess.run([str(executable)], check=True)

    def test_guest_patches_across_shards_and_repeat_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for index, symbol in enumerate(("sub_831583B0", "sub_83158680", "sub_82632E00")):
                (root / f"diablo3_recomp.{index}.cpp").write_text(
                    f"DEFINE_REX_FUNC({symbol}) {{\n\t// original\n}}\n"
                    "DEFINE_REX_FUNC(sub_12345678) {\n\t// preserve\n}\n")
            caller = root / "diablo3_recomp.3.cpp"
            caller.write_text("DEFINE_REX_FUNC(sub_82DAD168) {\n\t// preserve\n\tsub_831583B0(ctx, base);\n}\n")
            patch_generated(root)
            first = {p: p.read_bytes() for p in root.iterdir()}
            patch_generated(root)
            self.assertEqual(first, {p: p.read_bytes() for p in root.iterdir()})
            for path in root.iterdir():
                self.assertIn("// preserve", path.read_text())
            self.assertIn("ppc_longjmp", (root / "diablo3_recomp.1.cpp").read_text())
            # The host setjmp runs in the caller, whose frame outlives the protected call.
            self.assertIn("\tD3_GUEST_SETJMP(ctx);\n", caller.read_text())
            self.assertTrue(caller.read_text().startswith('#include "guest_jump.h"\n'))

    def test_setjmp_without_callers_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for index, symbol in enumerate(("sub_831583B0", "sub_83158680", "sub_82632E00")):
                (root / f"diablo3_recomp.{index}.cpp").write_text(f"DEFINE_REX_FUNC({symbol}) {{\n}}\n")
            before = {p: p.read_bytes() for p in root.iterdir()}
            with self.assertRaisesRegex(ValueError, "at least one call"):
                patch_generated(root)
            self.assertEqual(before, {p: p.read_bytes() for p in root.iterdir()})

    def test_missing_symbol_does_not_partially_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = root / "diablo3_recomp.0.cpp"
            original = "DEFINE_REX_FUNC(sub_831583B0) {\n}\n"
            path.write_text(original)
            with self.assertRaises(ValueError):
                patch_generated(root)
            self.assertEqual(original, path.read_text())

    def test_duplicate_definition_does_not_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = root / "diablo3_recomp.0.cpp"
            original = "DEFINE_REX_FUNC(sub_831583B0) {\n}\n" * 2
            path.write_text(original)
            with self.assertRaises(ValueError):
                patch_generated(root)
            self.assertEqual(original, path.read_text())

    def test_launch_defaults_and_explicit_overrides(self):
        args = argparse.Namespace(probe=False, render_smoke=False,
                                  game_dir=pathlib.Path("/tmp/disc with spaces"),
                                  state_dir=pathlib.Path("/tmp/sotr-state"))
        command = launch_command(args, ["--render_target_path_vulkan=host",
                                        "--log_file", "/tmp/custom.log", "--vulkan_device=1"])
        self.assertIn("--game_data_root=/tmp/disc with spaces", command)
        self.assertNotIn("--render_target_path_vulkan=fsi", command)
        self.assertEqual(["--log_file"], [x for x in command if x.startswith("--log_file")])
        self.assertIn("--user_data_root=/tmp/sotr-state", command)

    def test_keyboard_enabled_and_can_be_disabled(self):
        args = argparse.Namespace(probe=False, render_smoke=False,
                                  game_dir=ROOT / "game", state_dir=ROOT / "state")
        self.assertIn("--mnk_mode=true", launch_command(args, []))
        for extra in (["--mnk_mode=false"], ["--mnk_mode", "false"]):
            command = launch_command(args, extra)
            self.assertNotIn("--mnk_mode=true", command)
            self.assertEqual(extra, command[-len(extra):])
        command = launch_command(args, ["--mnk_mouse=true", "--keybind_a=Return"])
        self.assertIn("--mnk_mouse=true", command)
        self.assertIn("--keybind_a=Return", command)

    def test_diagnostics_do_not_mount_game_or_saves(self):
        args = argparse.Namespace(probe=True, render_smoke=False)
        command = launch_command(args, [])
        self.assertEqual(1, len(command))
        self.assertTrue(command[0].endswith("d3-gpu-probe"))

    def test_user_data_override_keeps_default_cache_and_log_together(self):
        args = argparse.Namespace(probe=False, render_smoke=False,
                                  game_dir=ROOT / "game", state_dir=ROOT / "unused-state")
        command = launch_command(args, ["--user_data_root", "custom-state"])
        self.assertIn(f"--cache_root={ROOT / 'custom-state/cache'}", command)
        self.assertIn(f"--log_file={ROOT / 'custom-state/diablo3.log'}", command)


class TitleUpdateTests(unittest.TestCase):
    def inputs(self):
        base = bytearray(0x500)
        patch = bytearray(0x100)
        for data, option in ((base, 0x40006), (patch, 0x5FF)):
            data[:4] = b"XEX2"
            struct.pack_into(">I", data, 20, 1)
            struct.pack_into(">II", data, 24, option, 0x80)
        struct.pack_into(">I", base, 16, 0x100)
        struct.pack_into(">IIII", base, 0x80, 0x38E299CD, 2, 2, 0x394F07D4)
        base[0x108:0x208] = bytes(range(256))
        struct.pack_into(">III", patch, 0x80, 0x4C, 0x202, 2)
        patch[0x8C:0xA0] = hashlib.sha1(base[0x108:0x208]).digest()
        return base, patch

    def test_digest_uses_rsa_signature(self):
        base, patch = self.inputs()
        # The old checker used this unrelated security-header field.
        base[0x264:0x278] = b"\xEE" * 20
        verify_patch_source(base, patch)
        base[0x108] ^= 1
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_patch_source(base, patch)

    def test_wrong_identity_and_versions_rejected(self):
        for offset in (0x80, 0x84, 0x8C):
            base, patch = self.inputs()
            struct.pack_into(">I", base, offset, 0)
            with self.assertRaisesRegex(ValueError, "versions"):
                verify_patch_source(base, patch)
        for offset in (0x84, 0x88):
            base, patch = self.inputs()
            struct.pack_into(">I", patch, offset, 6)
            with self.assertRaisesRegex(ValueError, "versions"):
                verify_patch_source(base, patch)

    def test_truncated_xex_rejected(self):
        base, patch = self.inputs()
        for broken_base, broken_patch in ((base[:12], patch), (base, patch[:48])):
            with self.assertRaises(ValueError):
                verify_patch_source(broken_base, broken_patch)

    def test_update_hooks_and_repeat_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for index, symbol in enumerate(("sub_83161AD0", "sub_83161DA0", "sub_826374E8")):
                (root / f"diablo3_recomp.{index}.cpp").write_text(
                    f"DEFINE_REX_FUNC({symbol}) {{\n  // original\n}}\n")
            (root / "diablo3_recomp.3.cpp").write_text(
                "DEFINE_REX_FUNC(sub_82DAD168) {\n\tsub_83161AD0(ctx, base);\n}\n")
            patch_generated(root, "usa")
            first = {p: p.read_bytes() for p in root.iterdir()}
            patch_generated(root, "usa")
            self.assertEqual(first, {p: p.read_bytes() for p in root.iterdir()})
            text = "".join(p.read_text() for p in root.iterdir())
            self.assertIn("D3_GUEST_SETJMP(ctx);", text)
            self.assertNotIn("sub_83161AD0(ctx, base);", text)
            self.assertIn("ppc_longjmp", text)
            self.assertIn("D3RequestTitleUpdateExit();", text)
            self.assertNotIn("sub_831583B0", text)

    def test_update_extra_features_flag_and_plain_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            state = pathlib.Path(directory)
            (state / "pc-settings.ini").write_text("window_mode=1\nrender_scale=2\n")
            args = argparse.Namespace(probe=False, render_smoke=False, extra_features=True,
                                      title_update="usa", game_dir=pathlib.Path("/tmp/update-disc"),
                                      state_dir=state)
            command = launch_command(args, ["--vulkan_device=1"])
            self.assertTrue(command[0].endswith("linux-amd64-update-relwithdebinfo/diablo3"))
            self.assertIn("--extra_features=true", command)
            self.assertIn("--resolution_scale=2", command)
            self.assertIn("--update_data_root=/tmp/update-disc", command)
            self.assertIn("--vulkan_device=1", command)
            command = launch_command(args, ["--draw_resolution_scale_x=3"])
            self.assertNotIn("--resolution_scale=2", command)
            self.assertIn("--pc_use_saved_render_scale=false", command)
            args.extra_features = False
            command = launch_command(args, [])
            self.assertNotIn("--resolution_scale=2", command)
            self.assertNotIn("--extra_features=true", command)
            self.assertTrue(command[0].endswith("linux-amd64-update-relwithdebinfo/diablo3"))
            args.plain = True
            command = launch_command(args, [])
            self.assertTrue(command[0].endswith("linux-amd64-update-plain-relwithdebinfo/diablo3"))

    def test_update_never_patches_base_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = root / "diablo3_recomp.0.cpp"
            original = "DEFINE_REX_FUNC(sub_831583B0) {\n}\n"
            path.write_text(original)
            with self.assertRaises(ValueError):
                patch_generated(root, "usa")
            self.assertEqual(original, path.read_text())

    def test_shared_update_codegen_rejects_wrong_executable_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "Default.xex").write_bytes(b"wrong executable")
            with mock.patch.object(codegen_title_update.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "verified USA update"):
                    codegen_title_update.generate_update(root, "rexglue.exe")
                run.assert_not_called()

    def test_shared_update_codegen_checks_stamp_before_patching(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            game = root / "game"
            game.mkdir()
            data = b"test executable"
            (game / "Default.xex").write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            generated = root / "port/generated/update"
            generated.mkdir(parents=True)
            with mock.patch.object(codegen_title_update, "ROOT", root), mock.patch.object(codegen_title_update, "USA_UPDATE_SHA256", digest), mock.patch.object(codegen_title_update, "patch_generated") as patch:
                with self.assertRaisesRegex(ValueError, "missing or stale"):
                    codegen_title_update.generate_update(game, "rexglue.exe", True)
                patch.assert_not_called()
                (generated / "source-xex.sha256").write_text(digest)
                self.assertEqual(codegen_title_update.generate_update(game, "rexglue.exe", True), generated)
                patch.assert_called_once_with(generated, "usa")

    def test_failed_update_regeneration_invalidates_existing_stamp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            game = root / "game"
            game.mkdir()
            data = b"test executable"
            (game / "Default.xex").write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            generated = root / "port/generated/update"
            generated.mkdir(parents=True)
            stamp = generated / "source-xex.sha256"
            stamp.write_text(digest)
            manifest = root / "port/title_updates/update"
            manifest.mkdir(parents=True)
            (manifest / "diablo3_manifest.toml").write_text('game_root = "../../../game-update"')
            with mock.patch.object(codegen_title_update, "ROOT", root), mock.patch.object(codegen_title_update, "USA_UPDATE_SHA256", digest), mock.patch.object(codegen_title_update.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "rexglue")), mock.patch.object(codegen_title_update, "patch_generated") as patch:
                with self.assertRaises(subprocess.CalledProcessError):
                    codegen_title_update.generate_update(game, "rexglue.exe")
                self.assertFalse(stamp.exists())
                patch.assert_not_called()

    def test_update_launch_selects_separate_binary(self):
        args = argparse.Namespace(probe=False, render_smoke=False, extra_features=False,
                                  title_update="usa", game_dir=pathlib.Path("/tmp/update-disc"),
                                  state_dir=pathlib.Path("/tmp/update-state"))
        command = launch_command(args, [])
        self.assertTrue(command[0].endswith("linux-amd64-update-relwithdebinfo/diablo3"))
        self.assertIn("--game_data_root=/tmp/update-disc", command)
        self.assertIn("--user_data_root=/tmp/update-state", command)
        self.assertIn("--update_data_root=/tmp/update-disc", command)




class Ps3SaveImportTests(unittest.TestCase):
    @staticmethod
    def varint(value):
        result = bytearray()
        while value > 127:
            result.append((value & 127) | 128)
            value >>= 7
        result.append(value)
        return bytes(result)

    @classmethod
    def integer(cls, number, value):
        return cls.varint(number << 3) + cls.varint(value)

    @classmethod
    def message(cls, number, value):
        return cls.varint((number << 3) | 2) + cls.varint(len(value)) + value

    @staticmethod
    def encrypt(data):
        state = 0x305F92D82EC9A01B
        result = bytearray()
        for plain in data:
            result.append(plain ^ (state & 255))
            state = (((state ^ plain) << 56) | (state >> 8)) & 0xFFFFFFFFFFFFFFFF
        return bytes(result)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        entity = self.integer(1, 123) + self.integer(2, 0xDA93EB8A4006B788)
        digest = self.integer(1, 905) + self.message(2, entity)
        hero = (self.integer(1, 905) + self.message(2, digest) +
                self.message(3, self.integer(1, 1)) + self.message(123, b"unknown field"))
        account = self.integer(1, 108) + self.message(2, self.integer(1, 1))
        profile = self.message(1, self.integer(1, 1))
        index = self.message(1, self.message(1, entity))
        for name, data in {"ACCOUNT.DAT": account, "PROFILE.DAT": profile,
                           "HEROES.IDX": index, "4006B788.HRO": hero}.items():
            (self.source / name).write_bytes(self.encrypt(data))
        (self.source / "PREFS.DAT").write_bytes(b"platform preferences")
        self.before = {p.name: p.read_bytes() for p in self.source.iterdir()}

    def test_import_preserves_payloads_and_source(self):
        output = self.root / "new-state"
        report = import_ps3_save.import_save(self.source, output, import_ps3_save.DEFAULT_XUID)
        package = pathlib.Path(report["destination_package"])
        self.assertEqual(self.before["ACCOUNT.DAT"], (package / "account.dat").read_bytes())
        self.assertEqual(self.before["4006B788.HRO"],
                         (package / "heroes/da93eb8a4006b788.dat").read_bytes())
        self.assertFalse((package / "prefs.dat").exists())
        self.assertTrue((output / "import-report.json").is_file())
        self.assertFalse(report["runtime_validated"])
        self.assertEqual(self.before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        # Compare against the output as an Xbox reference on a second inspection.
        _, compared, _ = import_ps3_save.inspect_source(self.source, package)
        self.assertTrue(compared["known_update_versions_match"])

    def test_launch_imports_once_and_preserves_subsequent_saves(self):
        output = self.root / "launch-state"
        self.assertEqual(prepare_ps3_import(self.source, output), "Imported PS3 save")
        account = output / import_ps3_save.DEFAULT_XUID / "394F07D4/00000001/d3save/account.dat"
        account.write_bytes(b"subsequent game save")
        self.assertEqual(prepare_ps3_import(self.source, output), "Reusing imported PS3 save")
        self.assertEqual(account.read_bytes(), b"subsequent game save")
        with self.assertRaises(import_ps3_save.SaveError):
            prepare_ps3_import(self.root / "different-source", output)
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        with self.assertRaises(import_ps3_save.SaveError):
            prepare_ps3_import(self.source, unrelated)

    def test_existing_output_is_never_overwritten(self):
        output = self.root / "existing"
        output.mkdir()
        (output / "keep").write_bytes(b"existing save")
        with self.assertRaises(FileExistsError):
            import_ps3_save.import_save(self.source, output, import_ps3_save.DEFAULT_XUID)
        self.assertEqual((output / "keep").read_bytes(), b"existing save")

    def test_output_cannot_overlap_source(self):
        for output in (self.source, self.source / "new", self.root):
            with self.subTest(output=output), self.assertRaises(import_ps3_save.SaveError):
                import_ps3_save.import_save(self.source, output, import_ps3_save.DEFAULT_XUID)
        self.assertEqual(self.before, {p.name: p.read_bytes() for p in self.source.iterdir()})

    def test_index_mismatch_rejects_import(self):
        (self.source / "HEROES.IDX").write_bytes(self.encrypt(
            self.message(1, self.message(1, self.integer(1, 123) + self.integer(2, 456)))))
        with self.assertRaises(import_ps3_save.SaveError):
            import_ps3_save.import_save(self.source, self.root / "output", import_ps3_save.DEFAULT_XUID)
        self.assertFalse((self.root / "output").exists())

    def test_unknown_version_inspects_but_does_not_import(self):
        account = self.integer(1, 109) + self.message(2, self.integer(1, 1))
        (self.source / "ACCOUNT.DAT").write_bytes(self.encrypt(account))
        _, report, _ = import_ps3_save.inspect_source(self.source)
        self.assertFalse(report["known_update_versions_match"])
        with self.assertRaises(import_ps3_save.SaveError):
            import_ps3_save.import_save(self.source, self.root / "output", import_ps3_save.DEFAULT_XUID)

    def test_corrupt_wire_data_and_symlinks_are_rejected(self):
        for data in (b"", b"\x08\x80", b"\x12\xff\x7f", b"\x00", b"\x0f"):
            with self.subTest(data=data), self.assertRaises(import_ps3_save.SaveError):
                import_ps3_save.fields(data)
        (self.source / "4006B788.HRO").unlink()
        external = self.root / "external"
        external.write_bytes(self.before["4006B788.HRO"])
        (self.source / "4006B788.HRO").symlink_to(external)
        with self.assertRaises(import_ps3_save.SaveError):
            import_ps3_save.inspect_source(self.source)


class BuildClientTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)

    def args(self, **overrides):
        values = dict(iso=None, title_update=None, variants=["base"], data_only=False,
                      game_dir=self.root / "game", game_dir_update=self.root / "game-update",
                      sdk_source=self.root / "sdk", sdk_prefix=self.root / "prefix", patcher=None,
                      cmake="cmake", jobs=2, regenerate=False, no_sdk_download=False)
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_staging_never_writes_through_hardlinks_to_the_base_disc(self):
        base, update, output = self.root / "base", self.root / "update", self.root / "out/update"
        (base / "CPKs").mkdir(parents=True)
        (base / "Default.xex").write_bytes(b"base")
        (base / "CPKs/Common.cpk").write_bytes(b"common")
        files = []
        for name in ("Default.xexp", "CPKs/Patch.cpk", "CPKs/Patch2.cpk",
                     "CPKs/enUS_Patch.cpk", "CPKs/enUS_Patch2.cpk"):
            (update / name).parent.mkdir(parents=True, exist_ok=True)
            (update / name).write_bytes(name.encode())
            files.append(dict(path=name, size=len(name), sha256=hashlib.sha256(name.encode()).hexdigest()))
        (update / "update-manifest.json").write_text(build_client.json.dumps(dict(
            sha256="pkg", title_id="394F07D4", media_id="38E299CD", version=2,
            block_hashes_verified=True, files=files)))
        patcher = self.root / "patch.sh"
        patcher.write_text('#!/bin/sh\nprintf patched > "$3"\n')
        patcher.chmod(0o755)
        sha = lambda data: hashlib.sha256(data).hexdigest()
        with mock.patch.multiple(stage_title_update, DISC_SHA256=sha(b"base"), USA_UPDATE_SHA256=sha(b"patched"),
                                 USA_UPDATE_PACKAGE_SHA256="pkg", verify_patch_source=mock.DEFAULT):
            stage_title_update.stage(base, update, output, patcher)
        self.assertEqual((base / "Default.xex").read_bytes(), b"base")
        self.assertEqual((output / "Default.xex").read_bytes(), b"patched")
        self.assertEqual((output / "CPKs/Patch.cpk").read_bytes(), b"CPKs/Patch.cpk")
        self.assertFalse((base / "CPKs/Patch.cpk").exists())
        self.assertTrue((output / "CPKs/Common.cpk").samefile(base / "CPKs/Common.cpk"))

    def test_wrong_disc_is_rejected_before_extracting(self):
        iso = self.root / "other.iso"
        iso.write_bytes(b"x")
        with mock.patch.object(build_client.extract_disc, "file_sha256", return_value="0" * 64), \
                mock.patch.object(build_client.extract_disc, "extract") as extract:
            with self.assertRaisesRegex(build_client.BuildError, "not the USA"):
                build_client.plan(self.args(iso=iso, data_only=True))
            extract.assert_not_called()
        with self.assertRaisesRegex(build_client.BuildError, "choose your disc image"):
            build_client.plan(self.args(data_only=True))

    def test_incomplete_update_folder_is_never_replaced(self):
        (self.root / "game-update").mkdir()
        with mock.patch.object(build_client, "base_ready", return_value=True):
            with self.assertRaisesRegex(build_client.BuildError, "move it aside"):
                build_client.plan(self.args(variants=["update"], title_update=self.root / "tu"))
            (self.root / "game-update").rmdir()
            with self.assertRaisesRegex(build_client.BuildError, "Title Update package"):
                build_client.plan(self.args(variants=["update"]))

    def test_finished_steps_are_skipped_and_codegen_is_reused(self):
        (self.root / "game").mkdir()
        (self.root / "prefix/bin").mkdir(parents=True)
        (self.root / "prefix/bin/rexglue").touch()
        args = self.args(variants=["base", "update-plain"])
        with mock.patch.multiple(build_client, base_ready=mock.DEFAULT, update_ready=mock.DEFAULT,
                                 missing_tools=mock.DEFAULT) as mocks:
            mocks["base_ready"].return_value = mocks["update_ready"].return_value = True
            mocks["missing_tools"].return_value = []
            steps = build_client.plan(args)
        self.assertEqual([title for title, _ in steps],
                         ["Build Base (codegen and compile)", "Build Update (no extras) (codegen and compile)"])
        for regenerate, stamped in ((False, True), (True, True), (False, False)):
            args.regenerate = regenerate
            with mock.patch.object(build_client, "stamp_matches", return_value=stamped), \
                    mock.patch.object(build_client, "run") as run:
                build_client.build_variant(args, "update-plain")
            command = [str(arg) for arg in run.call_args.args]
            self.assertIn("--no-extra-features", command)
            self.assertEqual(command[command.index("--title-update") + 1], "usa")
            self.assertEqual("--skip-codegen" in command, stamped and not regenerate)


class SdkStampTests(unittest.TestCase):
    def test_stamp_is_current_only_for_the_pinned_commit_and_patches(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = pathlib.Path(tmp)
            self.assertEqual(sdk_patches.stamp_state(prefix, "linux"), "stale")  # no stamp
            sdk_patches.write_stamp(prefix, "linux")
            self.assertEqual(sdk_patches.stamp_state(prefix, "linux"), "current")
            self.assertEqual(sdk_patches.stamp_state(prefix, "win"), "stale")  # other host's patch set
            stamp = prefix / sdk_patches.STAMP
            stamp.write_text(stamp.read_text().replace(sdk_patches.lock()["commit"], "0" * 40))
            self.assertEqual(sdk_patches.stamp_state(prefix, "linux"), "stale")

    def test_patch_hash_changes_with_patch_contents(self):
        before = sdk_patches.patch_hash("linux")
        with mock.patch.object(sdk_patches, "ROOT", pathlib.Path(tempfile.mkdtemp())) as root:
            for name in sdk_patches.PATCH_DIRS["linux"]:
                (root / "patches" / name).mkdir(parents=True)
            (root / "patches/common/a.patch").write_bytes(b"one\r\n")
            first = sdk_patches.patch_hash("linux")
            (root / "patches/common/a.patch").write_bytes(b"one\n")
            self.assertEqual(first, sdk_patches.patch_hash("linux"))  # line endings ignored
            (root / "patches/common/a.patch").write_bytes(b"two\n")
            self.assertNotEqual(first, sdk_patches.patch_hash("linux"))
        self.assertEqual(before, sdk_patches.patch_hash("linux"))


if __name__ == "__main__":
    unittest.main()
