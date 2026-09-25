import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TM = os.path.join(HERE, "..", "scripts", "tm.py")


def run_tm(args, home, stdin=None, env_extra=None):
    """Run tm.py as a subprocess with HOME=home and cwd=home.

    cwd=home makes cache_util.project_key() fall back to basename(home), so the
    per-repo cache lands at <home>/.cortex/cortex-workflow/<basename(home)>.json.
    The Asana token env vars are removed unless env_extra sets them.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASANA_")}
    env["HOME"] = home
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, TM] + list(args),
        input=stdin, capture_output=True, text=True, env=env, cwd=home,
    )
    return proc.returncode, proc.stdout, proc.stderr


def cache_key(home):
    return os.path.basename(home.rstrip("/"))


def cache_path(home, key):
    return os.path.join(home, ".cortex", "cortex-workflow", key + ".json")


def write_cache(home, key, obj):
    path = cache_path(home, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f)


def read_cache(home, key):
    with open(cache_path(home, key)) as f:
        return json.load(f)


def write_json(home, name, obj):
    path = os.path.join(home, name)
    with open(path, "w") as f:
        json.dump(obj, f)
    return path
