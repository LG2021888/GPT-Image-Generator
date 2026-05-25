@echo off
setlocal
cd /d "%~dp0\.."
set PY=C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
if not exist "%PY%" set PY=python
set PYTHONPATH=%CD%\.pydeps
set TCL_LIBRARY=C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\tcl\tcl8.6
set TK_LIBRARY=C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\tcl\tk8.6
set KEEP=%CD%\.release_keep
if exist "%KEEP%" rmdir /s /q "%KEEP%"
mkdir "%KEEP%" >nul 2>nul
if exist "dist\GPTImageGenerator\config.ini" copy /Y "dist\GPTImageGenerator\config.ini" "%KEEP%\config.ini" >nul
if exist "dist\GPTImageGenerator\output" xcopy /E /I /Y "dist\GPTImageGenerator\output" "%KEEP%\output" >nul
if exist ".build_tmp" rmdir /s /q ".build_tmp"
"%PY%" -m PyInstaller --noconfirm --clean --onedir --windowed --name "GPT Image Generator" --distpath dist --workpath .build_tmp --specpath .build_tmp --paths "C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib" --hidden-import tkinter --hidden-import tkinter.ttk --hidden-import tkinter.filedialog --hidden-import tkinter.messagebox --collect-submodules tkinter --add-binary "C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\DLLs\_tkinter.pyd;." --add-binary "C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\DLLs\tcl86t.dll;." --add-binary "C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\DLLs\tk86t.dll;." --add-data "C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\tkinter;tkinter" --add-data "C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\tcl\tcl8.6;tcl\tcl8.6" --add-data "C:\Users\57276\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\tcl\tk8.6;tcl\tk8.6" app\gpt_image_generator.py
if errorlevel 1 exit /b %errorlevel%
if exist "dist\GPTImageGenerator" rmdir /s /q "dist\GPTImageGenerator"
if exist "dist\GPT Image Generator" ren "dist\GPT Image Generator" "GPTImageGenerator"
if exist "%KEEP%\config.ini" copy /Y "%KEEP%\config.ini" "dist\GPTImageGenerator\config.ini" >nul
if exist "%KEEP%\output" xcopy /E /I /Y "%KEEP%\output" "dist\GPTImageGenerator\output" >nul
if exist "%KEEP%" rmdir /s /q "%KEEP%"
if exist ".build_tmp" rmdir /s /q ".build_tmp"
endlocal
