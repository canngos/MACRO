Set-Location -LiteralPath 'C:\Users\shane\Documents\NLP\group_project\MACRO'
$taskPython = (Resolve-Path -LiteralPath '..\venv\Scripts\python.exe').Path
& $taskPython -m macro run --config configs/deepseek-final-400.json --cases data/benchmark-v2 --split test --limit 400 --allow-paid-api --max-calls 19200 --run-id deepseek-final-400-20261020-204705 --final-readiness readiness/deepseek-final-400/final-readiness.json
if ($LASTEXITCODE -ne 0) { throw 'Final run failed; inspect saved records before retrying.' }
& $taskPython -m macro summarize results/deepseek-final-400-20261020-204705
