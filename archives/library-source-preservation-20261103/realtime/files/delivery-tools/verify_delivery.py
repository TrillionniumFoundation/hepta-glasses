"""Read-only verification of this local candidate package, not attestation."""
import hashlib,json
from pathlib import Path,PurePosixPath
root=Path(__file__).resolve().parent
m=json.loads((root/'MANIFEST.json').read_text())
for item in m['files']:
 rel=PurePosixPath(item['path'])
 if rel.is_absolute() or '..' in rel.parts:raise SystemExit('unsafe manifest path')
 p=root.joinpath(*rel.parts)
 if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root):raise SystemExit('missing/unsafe file: '+str(rel))
 b=p.read_bytes()
 if len(b)!=item['bytes'] or hashlib.sha256(b).hexdigest()!=item['sha256']:raise SystemExit('digest mismatch: '+str(rel))
for item in m['changed_files']:
 p=root/'candidate'/item['path'];b=p.read_bytes()
 if hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()!=item['candidate_git_blob']:raise SystemExit('git identity mismatch')
print('Verified',len(m['files']),'files and',len(m['changed_files']),'candidate source identities; unpublished, not independently attested.')
