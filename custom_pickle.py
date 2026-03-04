import pickletools

with open("persistent", "rb") as f:
    data = f.read()

import zlib
uncompressed = zlib.decompress(data)

# This will print every single pickle opcode so we can see the structure
pickletools.dis(uncompressed[:500])  # first 500 bytes is enough to see the shape