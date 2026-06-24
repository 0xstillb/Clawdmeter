$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$fontRoot = Join-Path $repoRoot "assets\fonts\inter\static"
$outRoot = Join-Path $repoRoot "firmware\src"
$pnpm = "C:\Users\x_boa\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\pnpm.cmd"

if (!(Test-Path -LiteralPath $fontRoot)) {
    throw "Missing Inter fonts at $fontRoot"
}

$jobs = @(
    @{ Name = "font_ui_9"; Font = "Inter_18pt-Regular.ttf"; Size = 9 },
    @{ Name = "font_ui_11"; Font = "Inter_18pt-Regular.ttf"; Size = 11 },
    @{ Name = "font_ui_12"; Font = "Inter_18pt-Regular.ttf"; Size = 12 },
    @{ Name = "font_ui_14"; Font = "Inter_18pt-Regular.ttf"; Size = 14 },
    @{ Name = "font_ui_16"; Font = "Inter_18pt-Regular.ttf"; Size = 16 },
    @{ Name = "font_ui_20"; Font = "Inter_24pt-Regular.ttf"; Size = 20 },
    @{ Name = "font_ui_bold_9"; Font = "Inter_18pt-SemiBold.ttf"; Size = 9 },
    @{ Name = "font_ui_bold_10"; Font = "Inter_18pt-SemiBold.ttf"; Size = 10 },
    @{ Name = "font_ui_bold_11"; Font = "Inter_18pt-SemiBold.ttf"; Size = 11 },
    @{ Name = "font_ui_bold_12"; Font = "Inter_18pt-SemiBold.ttf"; Size = 12 },
    @{ Name = "font_ui_bold_14"; Font = "Inter_18pt-SemiBold.ttf"; Size = 14 },
    @{ Name = "font_ui_bold_16"; Font = "Inter_18pt-Bold.ttf"; Size = 16 },
    @{ Name = "font_ui_bold_20"; Font = "Inter_24pt-Bold.ttf"; Size = 20 },
    @{ Name = "font_ui_bold_24"; Font = "Inter_24pt-ExtraBold.ttf"; Size = 24 },
    @{ Name = "font_ui_bold_26"; Font = "Inter_28pt-ExtraBold.ttf"; Size = 26 },
    @{ Name = "font_ui_bold_28"; Font = "Inter_28pt-ExtraBold.ttf"; Size = 28 },
    @{ Name = "font_ui_bold_48"; Font = "Inter_28pt-ExtraBold.ttf"; Size = 48 }
)

foreach ($job in $jobs) {
    $fontPath = Join-Path $fontRoot $job.Font
    $outPath = Join-Path $outRoot ($job.Name + ".c")
    if (!(Test-Path -LiteralPath $fontPath)) {
        throw "Missing font file $fontPath"
    }

    Write-Host "Generating $($job.Name) from $($job.Font) @ $($job.Size)px"
    & $pnpm dlx lv_font_conv `
        --font $fontPath `
        --range 0x20-0x7E `
        --size $job.Size `
        --bpp 4 `
        --format lvgl `
        --no-compress `
        --force-fast-kern-format `
        --lv-include lvgl.h `
        --lv-font-name $job.Name `
        -o $outPath

    if ($LASTEXITCODE -ne 0) {
        throw "lv_font_conv failed for $($job.Name)"
    }
}
