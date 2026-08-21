#!/usr/bin/env python3
"""
Patches clock-bound's daemon/io.rs to stop hard-panicking when the VMClock
device (/dev/vmclock0) isn't present on the instance.

Discovered live, on a running node: clock-bound 3.0.0-alpha.1 (the tip of
both its tags and `main` as of this writing - there is no upstream fix)
unconditionally tries to enable AWS's VMClock device on any non-metal EC2
instance, and hard panics (process exit 101) if that device isn't present.
VMClock is separate from PHC and isn't exposed on m7i.large / this AMI - so
without this patch, clockbound crash-loops immediately on every boot.

The fix mirrors the graceful-fallback pattern the same function already uses
for its other failure modes (IMDS failure, metal-instance detection): turn
the `.unwrap_or_else(|_| panic!(...))` on VMClock::construct() into a match
that logs a warning and returns instead of panicking.

This uses a regex anchored on the distinctive, non-whitespace parts of the
snippet (VMClock::construct(...) ... .unwrap_or_else(|_| panic!(...))) with
free-form whitespace in between, rather than a byte-for-byte literal string
match - indentation of this block has already been observed to differ
between checkouts even at the same pinned tag (8 spaces vs 16 spaces seen in
practice), and a literal match is too brittle against that. The regex still
asserts exactly one match before rewriting, and preserves the original
indentation of the matched block in the replacement, so this fails loudly
(non-zero exit) instead of silently no-op'ing if clock-bound's source
changes in some more fundamental way upstream.
"""
import re
import sys

path = "/home/ec2-user/clock-bound/clock-bound/src/daemon/io.rs"

with open(path) as f:
    src = f.read()

# Matches (capturing the leading indentation of the `let vmclock = ...` line):
#   <indent>let vmclock = VMClock::construct(
#       ... anything (non-greedy) ...
#   .unwrap_or_else(|_| panic!("vmclock device not found {vmclock_shm_path}"));
pattern = re.compile(
    r'(?P<indent>[ \t]*)let vmclock = VMClock::construct\((?P<args>.*?)\)\s*'
    r'\.await\s*'
    r'\.unwrap_or_else\(\|_\| panic!\("vmclock device not found \{vmclock_shm_path\}"\)\);',
    re.DOTALL,
)

matches = list(pattern.finditer(src))
if len(matches) != 1:
    print(
        f"ERROR: expected exactly 1 match for the VMClock panic snippet, found {len(matches)}. "
        "clock-bound source has likely changed upstream in a way this patch script doesn't "
        "account for - inspect daemon/io.rs's create_vmclock() by hand and update this script.",
        file=sys.stderr,
    )
    sys.exit(1)

m = matches[0]
indent = m.group("indent")
args = m.group("args")

replacement = (
    f'{indent}let vmclock = match VMClock::construct({args})\n'
    f'{indent}    .await\n'
    f'{indent}{{\n'
    f'{indent}    Ok(vmclock) => vmclock,\n'
    f'{indent}    Err(e) => {{\n'
    f'{indent}        warn!(?e, "VMClock device not found at {{vmclock_shm_path}}; continuing without VMClock.");\n'
    f'{indent}        return;\n'
    f'{indent}    }}\n'
    f'{indent}}};'
)

src = src[: m.start()] + replacement + src[m.end():]

with open(path, "w") as f:
    f.write(src)

print("patched OK")
print("--- replacement applied ---")
print(replacement)