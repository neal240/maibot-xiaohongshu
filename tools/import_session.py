"""Import a browser session over an already authenticated channel (stdin only)."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from session_store import SessionStore
from xhs_client import ReadOnlyClient
from xhs_policy import Policy


def main():
    if len(sys.argv) != 2:
        raise ValueError('expected an absolute plugin data directory')
    target = Path(sys.argv[1])
    if not target.is_absolute(): raise ValueError('data directory must be absolute')
    state = json.load(sys.stdin)
    if not ReadOnlyClient(state, Policy(frozenset(), 0)).authenticated():
        raise RuntimeError('account could not be verified')
    SessionStore(target / 'auth').save(state)
    print('SESSION_VERIFIED_AND_SAVED')


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('SESSION_IMPORT_FAILED:', type(exc).__name__, file=sys.stderr)
        sys.exit(1)
