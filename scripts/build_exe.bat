@echo off
setlocal
cd /d "%~dp0\.."

set PY=C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
if not exist "%PY%" set PY=python
set PYTHONHOME=C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python
set PYTHONPATH=%CD%\.pydeps;%PYTHONHOME%\Lib;%PYTHONHOME%\DLLs
set TCL_LIBRARY=C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\tcl\tcl8.6
set TK_LIBRARY=C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\tcl\tk8.6

set OUT_DIR=dist\GPTImageGenerator
set OLD_OUT_DIR=dist\GPT Image Generator
set BUILD_DIST=.build_dist
set BUILD_OUT=%BUILD_DIST%\GPTImageGenerator
set KEEP=%CD%\.release_keep

if exist "%KEEP%" rmdir /s /q "%KEEP%"
mkdir "%KEEP%" >nul 2>nul

rem Preserve user runtime files from the canonical output first, then fallback to the old spaced folder.
if exist "%OUT_DIR%\config.ini" copy /Y "%OUT_DIR%\config.ini" "%KEEP%\config.ini" >nul
if not exist "%KEEP%\config.ini" if exist "%OLD_OUT_DIR%\config.ini" copy /Y "%OLD_OUT_DIR%\config.ini" "%KEEP%\config.ini" >nul
if exist "%OUT_DIR%\prompt_history.json" copy /Y "%OUT_DIR%\prompt_history.json" "%KEEP%\prompt_history.json" >nul
if not exist "%KEEP%\prompt_history.json" if exist "%OLD_OUT_DIR%\prompt_history.json" copy /Y "%OLD_OUT_DIR%\prompt_history.json" "%KEEP%\prompt_history.json" >nul
if exist "%OUT_DIR%\important.log" copy /Y "%OUT_DIR%\important.log" "%KEEP%\important.log" >nul
if not exist "%KEEP%\important.log" if exist "%OLD_OUT_DIR%\important.log" copy /Y "%OLD_OUT_DIR%\important.log" "%KEEP%\important.log" >nul
if exist "%OUT_DIR%\output" xcopy /E /I /Y "%OUT_DIR%\output" "%KEEP%\output" >nul
if not exist "%KEEP%\output" if exist "%OLD_OUT_DIR%\output" xcopy /E /I /Y "%OLD_OUT_DIR%\output" "%KEEP%\output" >nul


rem Force close old packaged app and Explorer windows that lock the output folders.
taskkill /F /IM GPTImageGenerator.exe >nul 2>nul
taskkill /F /IM "GPT Image Generator.exe" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$targets=@((Resolve-Path -LiteralPath 'dist' -ErrorAction SilentlyContinue).Path); if($targets){$shell=New-Object -ComObject Shell.Application; foreach($w in @($shell.Windows())){try{$p=$w.Document.Folder.Self.Path; foreach($t in $targets){if($p -and $p.StartsWith($t,[StringComparison]::OrdinalIgnoreCase)){$w.Quit(); break}}}catch{}}}" >nul 2>nul
timeout /t 1 /nobreak >nul 2>nul

if exist ".build_tmp" rmdir /s /q ".build_tmp"
if exist "%BUILD_DIST%" rmdir /s /q "%BUILD_DIST%"

if exist ".build_tmp" (
  echo Failed to remove ".build_tmp". Please close any process using it, then retry.
  exit /b 1
)
if exist "%BUILD_DIST%" (
  echo Failed to remove "%BUILD_DIST%". Please close any process using it, then retry.
  exit /b 1
)

"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --name "GPTImageGenerator" --distpath "%BUILD_DIST%" --workpath .build_tmp --specpath .build_tmp --paths "%PYTHONHOME%\Lib" --paths "%PYTHONHOME%\DLLs" --hidden-import tkinter --hidden-import tkinter.ttk --hidden-import tkinter.filedialog --hidden-import tkinter.messagebox --collect-submodules tkinter --add-binary "%PYTHONHOME%\DLLs\_tkinter.pyd;." --add-binary "%PYTHONHOME%\DLLs\tcl86t.dll;." --add-binary "%PYTHONHOME%\DLLs\tk86t.dll;." --add-data "%PYTHONHOME%\Lib\tkinter;tkinter" --add-data "%PYTHONHOME%\tcl\tcl8.6;tcl\tcl8.6" --add-data "%PYTHONHOME%\tcl\tk8.6;tcl\tk8.6" app\gpt_image_generator.py
if errorlevel 1 exit /b %errorlevel%

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%" >nul 2>nul

rem Replace only packaged program artifacts. Never delete runtime user data:
rem   config.ini, prompt_history.json, important.log, output\
if exist "%OUT_DIR%\GPTImageGenerator.exe" del /f /q "%OUT_DIR%\GPTImageGenerator.exe"
if exist "%OUT_DIR%\_internal" rmdir /s /q "%OUT_DIR%\_internal"
if exist "%OUT_DIR%\_tcl_data" rmdir /s /q "%OUT_DIR%\_tcl_data"
if exist "%OUT_DIR%\_tk_data" rmdir /s /q "%OUT_DIR%\_tk_data"
if exist "%OUT_DIR%\tcl8" rmdir /s /q "%OUT_DIR%\tcl8"

if exist "%OUT_DIR%\GPTImageGenerator.exe" (
  echo Failed to replace "%OUT_DIR%\GPTImageGenerator.exe". Please close any running packaged app, then retry.
  exit /b 1
)
if exist "%OUT_DIR%\_internal" (
  echo Failed to replace "%OUT_DIR%\_internal". Please close any Explorer window or running app inside it, then retry.
  exit /b 1
)

xcopy /E /I /Y "%BUILD_OUT%\*" "%OUT_DIR%\" >nul
if errorlevel 1 exit /b %errorlevel%

if exist "%KEEP%\config.ini" copy /Y "%KEEP%\config.ini" "%OUT_DIR%\config.ini" >nul
if exist "%KEEP%\prompt_history.json" copy /Y "%KEEP%\prompt_history.json" "%OUT_DIR%\prompt_history.json" >nul
if exist "%KEEP%\important.log" copy /Y "%KEEP%\important.log" "%OUT_DIR%\important.log" >nul
if exist "%KEEP%\output" xcopy /E /I /Y "%KEEP%\output" "%OUT_DIR%\output" >nul
if exist "%KEEP%" rmdir /s /q "%KEEP%"
if exist ".build_tmp" rmdir /s /q ".build_tmp"
if exist "%BUILD_DIST%" rmdir /s /q "%BUILD_DIST%"

echo Build complete: %CD%\%OUT_DIR%
endlocal
