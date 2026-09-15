param([string]$Shas)
$list = $Shas -split "[,\s]+" | Where-Object { $_ }
foreach ($sha in $list) {
  $out = git cherry-pick -x $sha 2>&1 | Out-String
  if ($LASTEXITCODE -ne 0) {
    $files = @(git diff --name-only --diff-filter=U)
    foreach ($f in $files) {
      git checkout --theirs -- $f 2>$null | Out-Null
      git add -- $f 2>$null | Out-Null
    }
    git add -A 2>$null | Out-Null
    $out2 = git -c core.editor=true cherry-pick --continue 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Output "FAIL $sha"; Write-Output $out2; break }
    Write-Output ("OK(theirs:" + ($files -join ",") + ") " + $sha)
  } else {
    Write-Output "OK(clean) $sha"
  }
}
git log --oneline -1 | Out-String
