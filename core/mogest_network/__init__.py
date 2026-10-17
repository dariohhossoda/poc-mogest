"""
Delineation code copied from mogest-network (package ``mogest_network``).

The source repository has no commits yet, so each copy is identified by the
source path, the copy date and the SHA-256 of the copied file:

- ``dem.py`` from ``src/mogest_network/dem.py``, 2026-10-17, SHA-256
  444ca28a4e53ac6b2f1f1fcdf9e0adf4fa236fbe78fcfd55a805d2c6f9a5cc14
- ``delineacao.py`` from ``src/mogest_network/delineacao.py``, 2026-10-17, SHA-256
  db46a6306b6afb6425b4236347a81e4dc069d5cd8cd6875872af5cb816204999
- ``muskingum_k.py`` from ``src/mogest_network/muskingum_k.py``, 2026-10-17, SHA-256
  4851f04563a779847e3308f8a52b1a25504693476489bf3550b02e8113c8d87a

Changes made to the copies are listed at the top of each module. Fix bugs in
mogest-network first and copy again, so the two do not drift apart.
"""

# Downstream id of the basin outlet in the topology (mogest_network.rede)
JUSANTE_FINAL = -999
