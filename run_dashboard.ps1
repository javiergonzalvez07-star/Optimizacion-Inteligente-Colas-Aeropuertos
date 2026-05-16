Set-Location $PSScriptRoot
python -m streamlit run dashboard/app.py
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Si falla, usa el mismo Python con el que ejecutaste pip install:"
    Write-Host "  python -m pip install -r requirements.txt"
    Write-Host "  python -m streamlit run dashboard/app.py"
}
