#!/usr/bin/env python3
import re
import sys

path = "/home/ec2-user/clock-bound/clock-bound/src/daemon/io.rs"

with open(path) as f:
    src = f.read()

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