# Custom capes registry

Public, static registry for the **Custom Capes** native Horizon mod. The registry
serves one `index.json` and content-addressed PNG cape textures from GitHub Pages,
with jsDelivr as a fallback mirror.

Intended URLs (owner `moarthy2`; replace `moarthy2` if the deploying account
differs):

- Pages: <https://moarthy2.github.io/moarthy2/>
- jsDelivr: <https://cdn.jsdelivr.net/gh/moarthy2/moarthy2@main/>
- Index: <https://moarthy2.github.io/moarthy2/index.json>

These URLs are not live until this repository is pushed to `main`, Pages is
enabled, and the first workflow run succeeds.

## Layout

```text
uploads/                       files waiting for the workflow
uploads/uuid-<uuid>.png        one UUID (premium or offline)
uploads/name-<name>.png        one username (premium and/or offline)
uploads/remove.txt             optional keys to remove, one per line
capes/<hash16>.png             cleaned, hash-addressed cape textures
index.json                     generated lookup table
tools/build_index.py           validation, cleaning, hashing, index builder
tools/test_build_index.py      automated tests
.github/workflows/build.yml    runs on uploads changes
```

`hash16` is the first 16 hex characters of SHA-256 over the cleaned PNG bytes.
The same cape content always gets the same path.

## Add or replace a cape

1. Create a PNG that is exactly **64×32** or **128×64**, at most **20 KB**, and
   not animated. Transparency is supported.
2. Copy it into `uploads/` using one of these names:
   - `uuid-<uuid>.png` (dashes optional; case-insensitive), or
   - `name-<username>.png` (`^[A-Za-z0-9_]{1,16}$`, case-insensitive).
3. Commit and push to `main` in this repository.
4. Wait for **Actions → Build capes** and the Pages deployment. The mod picks
   the new `index.json` up at its next 30-minute refresh, or immediately after
   a game restart.

`name-Steve.png` and `name-steve.png` are the same key. A UUID entry always wins
over a name entry for the same player. One `name-` upload is enough to cover a
premium account and a cracked/offline account with the same name.

The workflow cleans metadata, re-encodes the PNG, validates every upload before
changing anything, writes `capes/<hash16>.png`, updates both maps in
`index.json`, deletes the processed upload, and removes capes nothing references.
If any file is invalid, the run fails and no upload is removed or indexed.

To remove entries, add `uploads/remove.txt`:

```text
uuid-069a79f4-44e9-4726-a5be-fca90e38aaf5
name-Steve
```

Push it. The keys and any now-orphaned capes are removed, then `remove.txt` is
deleted. `uploads/.gitkeep` and `uploads/remove.txt` are exempt from PNG checks.

## Samples

`uploads/name-sample.png` and `uploads/uuid-0123456789abcdef0123456789abcdef.png`
are valid samples. The first successful workflow run will index them and remove
the upload files. Remove the resulting entries with `remove.txt` if you only
wanted to test the pipeline.

## One-time repository setup

1. Create a **public** repository named `moarthy2` under the GitHub account that
   owns the Pages URL above.
2. Push this directory to its `main` branch.
3. **Settings → Actions → General → Workflow permissions**: select
   **Read and write permissions**, then save. The workflow needs this to commit
   `index.json` and `capes/`.
4. **Settings → Pages → Build and deployment**: Source **Deploy from a branch**,
   Branch **main**, Folder **/ (root)**, Save.
5. Run **Actions → Build capes → Run workflow** once if the initial upload did
   not trigger it. Wait for both the workflow and the Pages deployment to finish.
6. If the account or repository name differs, update the mod's default URLs and
   rebuild the `.hmod`. The runtime config also accepts `baseUrl` and `mirrorUrl`.

The workflow uses `GITHUB_TOKEN` supplied by Actions. Never put a personal token
in this repository.

## Test locally

Pillow is the only Python dependency used by the builder and tests.

```sh
python3 -m pip install "pillow>=11,<13"
python3 -m unittest discover -s tools -p 'test_*.py'
python3 tools/build_index.py
```

Run the builder from the repository root. It is intentionally a file-tree tool:
the workflow performs the commit and push after it succeeds.

## Privacy and limits

This repository and every uploaded PNG are public. Keep private skins out. A
name entry is not proof of identity, so a player can deliberately use someone
else's name; UUID entries are the exact route. The mod never sends session
tokens, chat, or player data anywhere; it only fetches the index and cape PNGs
from the two configured HTTPS hosts.
