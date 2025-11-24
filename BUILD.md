# Building GPU Modules

**Internal Documentation for Maintainers**

This guide explains how to compile and maintain the proprietary GPU modules for the GPU Miner.

## Overview

The GPU acceleration code (`gpu_core/engine.py` and `gpu_core/kernels.py`) contains proprietary CUDA kernel implementations. These files are **not** committed to the public repository. Instead, we distribute pre-compiled binaries for each platform.

## Source Code Protection

### What's Protected

- `gpu_core/engine.py` - GPU mining engine
- `gpu_core/kernels.py` - CUDA kernel implementations

### What's Public

- All files in `core/` - Wallet management, API client, database, etc.
- `gpu_core/__init__.py` - Binary loader
- `gpu_core/bin/` - Pre-compiled binaries
- All scripts, configs, and documentation

## Local Compilation

### Prerequisites

- Python 3.12+
- CUDA Toolkit 11.8+ (for testing)
- PyCUDA installed
- Nuitka (installed automatically by build scripts)

### Windows

```powershell
cd "c:\Users\Elias\Documents\Cursor Porjects\GPU Miner\GPUMiner"
.\scripts\build_modules.bat
```

The script will:
1. Activate venv if available
2. Install Nuitka and dependencies
3. Compile `engine.py` and `kernels.py`
4. Move `.pyd` files to `gpu_core/bin/windows/`
5. Test the import

**Output:** `gpu_core/bin/windows/engine.pyd` and `kernels.pyd`

### Linux/macOS

```bash
cd ~/gpu-miner  # or your project path
chmod +x scripts/build_modules.sh
./scripts/build_modules.sh
```

The script will:
1. Detect platform (Linux or macOS)
2. Activate venv if available
3. Install Nuitka and dependencies
4. Compile modules
5. Move `.so` files to `gpu_core/bin/{platform}/`
6. Test the import

**Output:** `gpu_core/bin/linux/engine.so` and `kernels.so` (or `macos/`)

## GitHub Actions Automation

### Workflow Triggers

The build workflow (`.github/workflows/build-gpu-modules.yml`) runs when:

1. **Push to main/master** with changes to:
   - `gpu_core/engine.py`
   - `gpu_core/kernels.py`
   - The workflow file itself

2. **Manual trigger** via GitHub Actions tab → "Build GPU Modules" → Run workflow

3. **Release creation** - Automatically builds and uploads artifacts

### What the Workflow Does

For each platform (Windows, Linux, macOS):
1. Checks out the repository
2. Sets up Python 3.12
3. Installs Nuitka and dependencies
4. Compiles the modules
5. Verifies the binaries
6. Commits them back to the repo (only on push)
7. Uploads artifacts (accessible for 90 days)

### Monitoring Builds

1. Go to your GitHub repository
2. Click **Actions** tab
3. Select "Build GPU Modules" workflow
4. View recent runs and their status

### Downloading Artifacts

If you need to manually download binaries from a workflow run:

1. Open the workflow run in GitHub Actions
2. Scroll to "Artifacts" section
3. Download `gpu-modules-windows`, `gpu-modules-linux`, or `gpu-modules-macos`

## Committing Binaries

### First Time Setup

After building locally, commit the binaries:

```bash
git add gpu_core/bin/windows/
git add gpu_core/bin/linux/
git add gpu_core/bin/macos/
git commit -m "Add pre-compiled GPU module binaries"
git push
```

### Subsequent Updates

When you modify `engine.py` or `kernels.py`:

1. **Update the source locally** (not in the GitHub repo)
2. **Build locally** using the scripts above
3. **Test thoroughly** with `python main.py`
4. **Commit only the binaries**:
   ```bash
   git add gpu_core/bin/
   git commit -m "Update GPU modules: <describe changes>"
   git push
   ```

Alternatively, rely on GitHub Actions to build automatically after you push source changes to a private branch or local repo.

## Repository Structure

```
GPUMiner/
├── .gitignore                  # Excludes engine.py, kernels.py
├── gpu_core/
│   ├── __init__.py            # Auto-loads binaries
│   ├── engine.py              # ❌ NOT in repo (protected)
│   ├── kernels.py             # ❌ NOT in repo (protected)
│   └── bin/
│       ├── README.md          # ✅ Binary documentation
│       ├── windows/           # ✅ .pyd files
│       ├── linux/             # ✅ .so files
│       └── macos/             # ✅ .so files
├── scripts/
│   ├── build_modules.bat      # ✅ Windows build script
│   └── build_modules.sh       # ✅ Unix build script
└── .github/workflows/
    └── build-gpu-modules.yml  # ✅ CI/CD automation
```

## Keeping Source Code Safe

### Primary Source Repository

**Recommended:** Maintain a separate **private** GitHub repository with the complete source code, including `engine.py` and `kernels.py`.

### Local Backup

**Minimum:** Keep backups of the proprietary source files:

```powershell
# Windows - Create backup
xcopy gpu_core\engine.py ..\GPU_Source_Backup\ /Y
xcopy gpu_core\kernels.py ..\GPU_Source_Backup\ /Y
```

```bash
# Linux/macOS - Create backup
cp gpu_core/engine.py gpu_core/kernels.py ../GPU_Source_Backup/
```

### Before Making Repo Public

1. ✅ Verify `.gitignore` excludes sensitive files
2. ✅ Build binaries for all platforms
3. ✅ Test that miner works with binaries only
4. ✅ Commit and push binaries
5. ✅ Clone repo in a fresh directory
6. ✅ Verify source files are NOT present
7. ✅ Run miner in fresh clone to confirm it works
8. ✅ **Only then** make the repository public

## Troubleshooting

### Build Fails with "Module not found"

Ensure all dependencies are installed:
```bash
pip install -r requirements.txt
pip install nuitka ordered-set zstandard
```

### Import Test Fails

Check that:
1. Binaries are in the correct directory (`gpu_core/bin/{platform}/`)
2. File extensions are correct (`.pyd` for Windows, `.so` for others)
3. Python version matches (3.12)

### GitHub Actions Build Fails

Common issues:
- **Missing dependencies**: Workflow should auto-install, but check logs
- **Directory permissions**: Ensure workflow can create directories
- **Platform-specific errors**: Test locally on that platform first

### Binary Compatibility Issues

If users report "module not compatible":
- Verify Python version (must be 3.12)
- Check architecture (x86_64/AMD64 only)
- Rebuild for the specific platform

## Security Notes

- Never commit `engine.py` or `kernels.py` to the public repository
- Keep GitHub Actions logs private if they might contain source info
- Consider code obfuscation for additional protection
- Monitor repository forks and ensure they don't contain source code

## Release Process

When creating a new release:

1. Update version number in relevant files
2. Build binaries locally and test
3. Update CHANGELOG.md
4. Create a Git tag: `git tag v1.0.0`
5. Push tag: `git push origin v1.0.0`
6. Create GitHub Release
7. GitHub Actions will automatically build and attach binaries

## Questions?

For questions about the build process, contact the maintainer (that's you!).
