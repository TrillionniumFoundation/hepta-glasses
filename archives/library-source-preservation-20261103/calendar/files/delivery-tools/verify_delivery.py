#!/usr/bin/env python3
"""Read-only byte verification. No network, execution of candidate code or Git writes."""
from pathlib import Path, PurePosixPath
import hashlib, json, sys

def verify(root: Path) -> dict:
    manifest_path = root / 'DELIVERY_MANIFEST.json'
    if manifest_path.is_symlink():
        raise ValueError('linked manifest')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    expected = {row['path'] for row in manifest['files']}
    if len(expected) != len(manifest['files']):
        raise ValueError('duplicate manifest path')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != expected | {'DELIVERY_MANIFEST.json'}:
        raise ValueError('unexpected or missing delivery files')
    for row in manifest['files']:
        parts = PurePosixPath(row['path'])
        if parts.is_absolute() or '..' in parts.parts or '\\' in row['path']:
            raise ValueError('unsafe path')
        file = root.joinpath(*parts.parts)
        current = root
        for part in parts.parts:
            current /= part
            if current.is_symlink():
                raise ValueError('linked path')
        raw = file.read_bytes()
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('content mismatch: ' + row['path'])
    changes = json.loads((root/'validation/change-manifest.json').read_text())
    for row in changes['files']:
        raw = (root/'candidate-files'/row['path']).read_bytes()
        git = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if git != row['git_blob'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('candidate identity mismatch: ' + row['path'])
    return {'ok': True, 'files_verified': len(expected), 'candidate_git_blobs_verified': len(changes['files']),
            'published': False, 'independent_attestation': False, 'base_ci_failure_fixed': False}

if __name__ == '__main__':
    try:
        print(json.dumps(verify(Path(__file__).resolve().parent), sort_keys=True))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        sys.exit(1)
