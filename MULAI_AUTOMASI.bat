@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0"
if errorlevel 1 exit /b 1

if not exist ".venv\Scripts\python.exe" goto system_python
".venv\Scripts\python.exe" -u "isi_form_ulasan.py" --interaktif
set "BOT_EXIT_CODE=%errorlevel%"
goto finish

:system_python
python --version >nul 2>&1
if errorlevel 1 goto try_py
python -u "isi_form_ulasan.py" --interaktif
set "BOT_EXIT_CODE=%errorlevel%"
goto finish

:try_py
py -3 --version >nul 2>&1
if errorlevel 1 goto no_python
py -3 -u "isi_form_ulasan.py" --interaktif
set "BOT_EXIT_CODE=%errorlevel%"
goto finish

:no_python
echo Python 3 tidak ditemukan. Pasang Python 3, lalu jalankan file ini lagi.
set "BOT_EXIT_CODE=1"

:finish
if "%BOT_EXIT_CODE%"=="0" goto done
echo.
echo Program berhenti dengan kode %BOT_EXIT_CODE%. Baca pesan di atas.
pause
:done
popd
exit /b %BOT_EXIT_CODE%
