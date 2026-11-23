from pathlib import Path
from zipfile import ZipFile
import importlib.util
import pytest

spec = importlib.util.spec_from_file_location('build_release', Path(__file__).resolve().parents[1] / 'scripts/build_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def setup_public(tmp_path):
    (tmp_path / 'PUBLIC_FILES.txt').write_text('PUBLIC_FILES.txt\nREADME.md\n', encoding='utf-8')
    (tmp_path / 'README.md').write_text('Fictional example project.', encoding='utf-8')


def test_export_omits_private_and_unlisted_files(tmp_path):
    setup_public(tmp_path)
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/office.sqlite3').write_bytes(b'private profile')
    (tmp_path / 'personal-notes.txt').write_text('private notes', encoding='utf-8')
    with ZipFile(release.build_release(tmp_path)) as archive:
        assert set(archive.namelist()) == {
            'local-ai-job-office/PUBLIC_FILES.txt', 'local-ai-job-office/README.md'}
        assert archive.read('local-ai-job-office/README.md') == b'Fictional example project.'


def test_export_includes_folder_guides_but_not_private_contents(tmp_path):
    setup_public(tmp_path)
    for name in release.PUBLIC_FOLDER_GUIDES:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('Public setup instructions.', encoding='utf-8')
    (tmp_path / 'PUT_YOURCV_HERE/master.docx').write_bytes(b'private CV')
    (tmp_path / 'PUT_YOUR_AI_MODEL_HERE/model.gguf').write_bytes(b'private model')
    with (tmp_path / 'PUBLIC_FILES.txt').open('a', encoding='utf-8') as handle:
        handle.write('\n'.join(sorted(release.PUBLIC_FOLDER_GUIDES)) + '\n')
    with ZipFile(release.build_release(tmp_path)) as archive:
        names = {name.removeprefix('local-ai-job-office/') for name in archive.namelist()}
    assert names == {'PUBLIC_FILES.txt', 'README.md'} | release.PUBLIC_FOLDER_GUIDES


@pytest.mark.parametrize('name', ['data/notes.txt', 'cv/profile.txt', 'PUT_YOURCV_HERE/private.txt',
    'PUT_YOUR_AI_MODEL_HERE/AI_instructions/job_preferences.md', 'PUT_YOUR_AI_MODEL_HERE/model.gguf',
    '../outside.txt', '.env', '.streamlit/secrets.toml', 'profile.pdf'])
def test_export_rejects_private_manifest_entries(tmp_path, name):
    setup_public(tmp_path)
    with (tmp_path / 'PUBLIC_FILES.txt').open('a', encoding='utf-8') as handle:
        handle.write(name + '\n')
    with pytest.raises(ValueError):
        release.public_files(tmp_path)


def test_export_rejects_machine_path_without_echoing_it(tmp_path):
    setup_public(tmp_path)
    private = 'C:' + chr(92) + 'Users' + chr(92) + 'FictionalPerson' + chr(92) + 'cv.pdf'
    (tmp_path / 'README.md').write_text(private, encoding='utf-8')
    with pytest.raises(ValueError) as error:
        release.public_files(tmp_path)
    assert 'machine-specific' in str(error.value)
    assert private not in str(error.value)


def test_fresh_install_has_no_personal_defaults(tmp_path, monkeypatch):
    from office import autonomous
    from office.db import Database
    from office.local_files import sync_local_files
    monkeypatch.setattr(autonomous, 'DATA', tmp_path / 'data')
    settings = autonomous.config()
    assert settings.regions == [] and settings.sources == []
    assert settings.timezone == 'UTC'
    db = Database(tmp_path / 'data/office.sqlite3')
    # Public templates are never imported as personal instructions.
    (tmp_path / 'examples').mkdir()
    (tmp_path / 'examples/job_preferences.example.md').write_text('[Your roles]', encoding='utf-8')
    assert sync_local_files(db, root=tmp_path) == []
    assert not db.facts() and not db.jobs()
    assert not db.preferences()['style'] and not db.preferences()['preferences']
