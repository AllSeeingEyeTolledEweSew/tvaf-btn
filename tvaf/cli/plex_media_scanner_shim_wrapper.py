import os
import sys

PASS_ENV = {
    "LD_LIBRARY_PATH": "",
}

def main():
    env = {}
    for k, v in os.environ.items():
        if k in PASS_ENV:
            env["TVAF_PLEX_PASSTHRU_" + k] = v
            env[k] = PASS_ENV[k]
        else:
            env[k] = v

    os.execvpe("tvaf_plex_media_scanner_shim", sys.argv, env)
