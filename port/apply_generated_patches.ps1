<#
.SYNOPSIS
  Re-applies the hand patches to port\generated\default\*.cpp that the ReXGlue
  codegen step cannot produce on its own. generated\ is rebuilt from scratch by
  codegen (build.ps1 runs both), which wipes any manual edit to that tree. Run
  this script once after every codegen run, before building.

.DESCRIPTION
  Each patch replaces a whole guest function, found by its symbol name: which
  generated file (diablo3_recomp.N.cpp) holds it depends on the codegen version.

  1. setjmp/longjmp fix (sub_831583B0 / sub_83158680): the recompiler
     mistranslates the guest setjmp/longjmp pair (truncated at an unsupported
     VMX instruction), which corrupts Lua's protected-call mechanism and
     crashes the GC. Replaced with host ppc_setjmp/ppc_longjmp plus manual
     save/restore of the guest callee-saved registers (src\guest_jump.h).

  2. Main-menu "B -> confirm -> Exit" fix (sub_82632E00): redirects the game's
     "leave session, return to title screen" routine to close the game window
     instead, so confirming the native "return to title screen?" dialog from
     the main menu quits the app like a normal PC game's Exit option. The
     host-side hook it calls (D3RequestGameExit) lives in src\base_exit.cpp.

  Idempotent: safe to run more than once. Every patch is checked before any
  file is written, and the script stops with an error if a function is missing
  or found more than once.

.EXAMPLE
  .\apply_generated_patches.ps1
#>
param(
    [string]$GeneratedDir = "$PSScriptRoot\generated\default"
)

$ErrorActionPreference = 'Stop'

$exitDecl = 'extern "C" void D3RequestGameExit();'

$patches = [ordered]@{
    # [D3 s9d] Correct setjmp. The recompiler truncated the guest setjmp at an
    # unsupported VMX instruction (halt_baddata @0x83158464), so setjmp returned
    # garbage (nonzero) -> every luaD_rawrunprotected skipped its protected
    # function -> half-built lua_State -> GC crash.
    'sub_831583B0' = @'
DEFINE_REX_FUNC(sub_831583B0) {
	// [D3 s9d] Guest setjmp(jmp_buf=r3): host ppc_setjmp plus the guest
	// callee-saved registers (r1, r13..r31, lr, f14..f31), keyed by jmp_buf.
	// Hand patch: reapply with port/apply_generated_patches.ps1 after codegen.
	const uint32_t buf = ctx.r3.u32;
	d3_jmp_save(ctx, buf);
	if (ppc_setjmp(buf) != 0)
		ctx.r3.u64 = d3_jmp_restore(ctx, buf);
	else
		ctx.r3.u64 = 0;
}
'@
    'sub_83158680' = @'
DEFINE_REX_FUNC(sub_83158680) {
	// [D3 s9d] Guest longjmp(jmp_buf=r3, val=r4): stash val and transfer to the
	// ppc_setjmp in sub_831583B0, which restores the guest registers. [[noreturn]].
	const uint32_t buf = ctx.r3.u32;
	const int value = ctx.r4.s32 ? ctx.r4.s32 : 1;
	d3_jmp_regs()[buf].val = static_cast<uint32_t>(value);
	ppc_longjmp(buf, value);
}
'@
    # [D3 main-menu-exit] sub_82632E00 is the live "leave session, return to
    # title screen" teardown routine, reached from the main-menu B -> confirm
    # dialog -> A (Aceptar) flow (sub_8277D398 -> sub_82634E20 shows the confirm
    # dialog -> its OnOK handler sub_82636F20 unconditionally calls this).
    'sub_82632E00' = @"
$exitDecl
DEFINE_REX_FUNC(sub_82632E00) {
	// [D3 main-menu-exit] Close the game like a PC "Exit" option instead of
	// returning to the title screen. Hand patch: reapply after codegen.
	D3RequestGameExit();
}
"@
}

$files = @(Get-ChildItem -LiteralPath $GeneratedDir -Filter '*_recomp.*.cpp' -ErrorAction SilentlyContinue)
if ($files.Count -eq 0) {
    throw "No generated sources in $GeneratedDir - run codegen first (build.ps1)."
}

# Work on copies in memory and write only once every patch has matched.
$texts = @{}
foreach ($file in $files) { $texts[$file.FullName] = [System.IO.File]::ReadAllText($file.FullName) }

foreach ($symbol in $patches.Keys) {
    # From the function header to the first closing brace in column 0.
    $pattern = [regex]::new('DEFINE_REX_FUNC\(' + $symbol + '\) \{.*?^\}',
        [System.Text.RegularExpressions.RegexOptions]'Singleline, Multiline')
    $found = @($texts.Keys | Where-Object { $pattern.Matches($texts[$_]).Count -gt 0 })
    $count = ($found | ForEach-Object { $pattern.Matches($texts[$_]).Count } | Measure-Object -Sum).Sum
    if ($count -ne 1) {
        throw "Expected one definition of $symbol in $GeneratedDir, found $count - codegen output changed shape."
    }
    $path = $found[0]
    # Drop our declaration from an earlier run, then replace the whole function.
    $text = $texts[$path].Replace("$exitDecl`r`n", '').Replace("$exitDecl`n", '')
    $replacement = $patches[$symbol].Replace("`r`n", "`n").TrimEnd()
    $text = $pattern.Replace($text, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $replacement }, 1)
    if ($symbol -ne 'sub_82632E00' -and -not $text.Contains('#include "guest_jump.h"')) {
        $text = "#include `"guest_jump.h`"`n" + $text
    }
    $texts[$path] = $text
    Write-Host "$symbol`: patched in $(Split-Path -Leaf $path)" -ForegroundColor Green
}

foreach ($path in $texts.Keys) {
    if ([System.IO.File]::ReadAllText($path) -ne $texts[$path]) {
        [System.IO.File]::WriteAllText($path, $texts[$path])
    }
}

Write-Host "`nDone. Run 'port\build.ps1 -SkipCodegen' to rebuild." -ForegroundColor Cyan
