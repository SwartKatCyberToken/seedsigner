# Third-party code

`dilithium-py` and `kyber-py` are copied into this repository rather than linked as git submodules, so a clone or a build never fetches them from outside. They're both MIT licensed, and each keeps its own `LICENSE`.

| Folder | Upstream | Commit | Commit date |
| --- | --- | --- | --- |
| `dilithium-py` | https://github.com/GiacomoPope/dilithium-py | `23cb5ee9dd7fa15d9e3c17527e7964c58f3cc549` | 2026-10-13 |
| `kyber-py` | https://github.com/GiacomoPope/kyber-py | `897923667b2fa80afcf910fc8c1825dddf54a97d` | 2025-12-15 |

Each folder is the upstream tree at that commit with two things left out: `.git`, and `assets/`, which holds about 18 MB of known-answer test vectors. Neither the app nor the image build uses `assets/`. Without it, the upstream tests that read those vectors don't run. To run them, copy `assets/` from the same commit.

Change these folders only on purpose. The ML-DSA and ML-KEM keys a seed produces depend on this code. To update a library, replace the whole folder with the new upstream tree, minus `.git` and `assets/`, update this table, and check that `tests/test_message_crypto.py` still passes.

`pycryptodome` is still a submodule. It's a reference copy for reading only, it isn't downloaded by default, and nothing builds from it. The app installs pycryptodome 4.2.0 from PyPI, hash-checked.
