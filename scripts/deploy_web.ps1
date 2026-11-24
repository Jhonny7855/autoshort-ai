# Rebuilds the React interface and publishes it to the gh-pages branch.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\deploy_web.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "web"
$repo = (git -C $root remote get-url origin) -replace "^.*[:/]", "" -replace "\.git$", ""
$repoName = Split-Path -Leaf $repo

Write-Host "Building $repoName with base /$repoName/" -ForegroundColor Cyan
Push-Location $web
$env:VITE_BASE = "/$repoName/"
try {
    npm run typecheck
    npm run build
} finally {
    Pop-Location
}

$dist = Join-Path $web "dist"
Copy-Item (Join-Path $dist "index.html") (Join-Path $dist "404.html") -Force
New-Item -ItemType File -Path (Join-Path $dist ".nojekyll") -Force | Out-Null

Write-Host "Publishing to gh-pages" -ForegroundColor Cyan
Push-Location $dist
try {
    if (-not (Test-Path ".git")) { git init -b gh-pages | Out-Null }
    git add -A
    git -c core.safecrlf=false commit -m "Deploy interface $(Get-Date -Format o)" --allow-empty | Out-Null
    git push -f "https://github.com/$repo.git" gh-pages:gh-pages
} finally {
    Pop-Location
}

Write-Host "Live at https://$(($repo -split '/')[0]).github.io/$repoName/" -ForegroundColor Green
