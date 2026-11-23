"""Export a reviewed source manifest, never the whole working directory.

Uses only the standard library. This is a publication guardrail, not a PII detector.
"""
import argparse
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'PUBLIC_FILES.txt'
PRIVATE_PARTS = {
    'data', 'cv', 'ai_model', '.venv', 'venv', '__pycache__', '.pytest_cache',
    '.git', '.aws', '.codex', '.agents', 'dist', 'build', '.idea', '.vscode',
    'put_yourcv_here', 'put_your_ai_model_here',
}
PUBLIC_FOLDER_GUIDES = {
    'PUT_YOURCV_HERE/README.md',
    'PUT_YOUR_AI_MODEL_HERE/README.md',
    'PUT_YOUR_AI_MODEL_HERE/Modelfile',
}
TEXT_SUFFIXES = {'.py', '.md', '.txt', '.json', '.html', '.toml', '.ini', '.ps1', '.bat', '.yml', '.yaml'}
SPECIAL_NAMES = {'.gitignore', 'LICENSE', 'Modelfile'}
PATTERNS = {
    'machine-specific home path': re.compile(r'(?i)(?:[a-z]:[\\/](?:users|documents and settings)[\\/][^\s\\/]+|/(?:Users|home)/[A-Za-z0-9_.-]+)'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'common access token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{32,})\b'),
}


def public_files(root=ROOT):
    root = Path(root).resolve()
    manifest = root / MANIFEST
    if manifest.is_symlink() or manifest.is_junction():
        raise ValueError('Release manifest must not be a link.')
    names = [line.strip() for line in manifest.read_text('utf-8').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if MANIFEST not in names:
        raise ValueError('The release manifest must include itself.')
    seen = set()
    files = []
    for name in names:
        relative = PurePosixPath(name)
        if ('\\' in name or ':' in name or relative.is_absolute() or '..' in relative.parts
                or str(relative) != name or name.casefold() in seen):
            raise ValueError(f'Invalid or duplicate manifest path: {name}')
        seen.add(name.casefold())
        if name not in PUBLIC_FOLDER_GUIDES and any(part.casefold() in PRIVATE_PARTS for part in relative.parts):
            raise ValueError(f'Private path in release manifest: {name}')
        if (relative.name.startswith('.env') or relative.name == 'secrets.toml'
                or (name not in PUBLIC_FOLDER_GUIDES and relative.suffix not in TEXT_SUFFIXES and relative.name not in SPECIAL_NAMES)):
            raise ValueError(f'Non-public file type in manifest: {name}')
        path = root.joinpath(*relative.parts)
        for parent in [path, *path.parents]:
            if parent == root:
                break
            if parent.is_symlink() or parent.is_junction():
                raise ValueError(f'Linked path in release manifest: {name}')
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f'Missing or external release file: {name}')
        content = path.read_bytes()
        text = content.decode('utf-8')
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                # Do not repeat potentially sensitive matches in logs.
                raise ValueError(f'{label} found in {name}; review before publishing.')
        files.append((name, content))
    return files


def build_release(root=ROOT):
    root = Path(root).resolve()
    files = public_files(root)
    output = root / 'dist'
    if output.is_symlink() or output.is_junction():
        raise ValueError('Release output directory must not be a link.')
    output.mkdir(exist_ok=True)
    archive_path = output / 'local-ai-job-office-source.zip'
    if archive_path.is_symlink() or archive_path.is_junction():
        raise ValueError('Release archive must not be a link.')
    with ZipFile(archive_path, 'w', compression=ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr('local-ai-job-office/' + name, content)
    return archive_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate public files without writing an archive.')
    args = parser.parse_args()
    try:
        if args.check:
            print(f'PASS: {len(public_files())} public files checked.')
        else:
            path = build_release()
            print(f'Created {path.relative_to(ROOT)}')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Release check failed: {exc}\n')


if __name__ == '__main__':
    main()
